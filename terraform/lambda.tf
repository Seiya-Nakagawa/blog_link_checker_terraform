# ----------------------------------------------------
# S3上のライブラリ用ZIPの情報を取得するためのデータソース
# ----------------------------------------------------
data "aws_s3_object" "lambda_libraries_zip" {
  bucket = aws_s3_bucket.s3_link_checker.id # s3.tfで定義されているアーティファクト用バケット
  key    = "lambda-layers/${var.system_name}_python_libraries.zip"
}

# ----------------------------------------------------
# Lambdaレイヤーを定義
# ライブラリ(dependencies.zip)は、手動でS3にアップロードされていることを前提とします。
# ----------------------------------------------------
resource "aws_lambda_layer_version" "dependencies_layer" {
  layer_name          = "${var.system_name}-${var.env}-laver-python-libraries"
  description         = "Shared libraries for link checker"
  s3_bucket           = aws_s3_bucket.s3_link_checker.id
  s3_key              = data.aws_s3_object.lambda_libraries_zip.key

  # S3上のZIPが更新されたことを検知するために、そのファイルのETag(ハッシュ値)を監視します
  source_code_hash    = data.aws_s3_object.dependencies_zip.etag
  compatible_runtimes = var.lambda_runtime_version
}

# ----------------------------------------------------
# 関数コード用のZIPファイルを自動で作成するためのデータソース
# ----------------------------------------------------
data "archive_file" "lambda_function_zip" {
  type        = "zip"
  
  # ZIPに含めるソースファイルを指定します (ワーキングディレクトリからの相対パス)
  source_file = "${path.cwd}/lambda/link_checker_lambda.py"
  
  # Terraformが実行される一時ディレクトリにZIPファイルが作成されます
  output_path = "${path.cwd}/build/lambda_function.zip"
}

# ----------------------------------------------------
# Lambda関数を定義
# ----------------------------------------------------
resource "aws_lambda_function" "link_checker_lambda" {
  function_name     = "${var.system_name}-${var.env}-link-checker-lambda"
  handler           = "link_checker_lambda.lambda_handler"
  runtime           = var.lambda_runtime_version
  timeout           = var.lambda_timeout_seconds # タイムアウト（秒）
  memory_size       = var.lambda_memory_size     # メモリサイズ（MB）

  # archive_fileで動的にZIP化したファイルを、デプロイパッケージとして直接指定します
  filename          = data.archive_file.lambda_function_zip.output_path
  source_code_hash  = data.archive_file.lambda_function_zip.output_base64sha256

  layers            = [aws_lambda_layer_version.dependencies_layer.arn]

  # Lambda関数内で使用する環境変数を定義します
  environment {
    variables = {
      S3_OUTPUT_BUCKET   = aws_s3_bucket.s3_link_checker.id # 結果を出力するバケット
      LOG_LEVEL          = var.lambda_log_level
      REQUEST_TIMEOUT    = var.lambda_request_timeout
      MAX_RETRIES        = var.lambda_max_retries
      BACKOFF_FACTOR     = var.lambda_backoff_factor
      MAX_WORKERS        = var.lambda_max_workers
      CRAWL_WAIT_SECONDS = var.lambda_crawl_wait_seconds
      NG_WORDS           = var.lambda_ng_words
    }
  }
}

# ----------------------------------------------------
# S3バケットがLambda関数を呼び出すための権限
# ----------------------------------------------------
resource "aws_lambda_permission" "allow_s3_to_call_lambda" {
  statement_id  = "AllowExecutionFromS3Bucket"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.link_checker_lambda.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.s3_link_checker.arn # s3.tfで定義されているトリガー用バケット
}