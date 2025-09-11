# ----------------------------------------------------
# S3上のライブラリ用ZIPの情報を取得するためのデータソース
# ----------------------------------------------------
data "aws_s3_object" "dependencies_zip" {
  bucket = aws_s3_bucket.s3_link_checker.id # s3.tfで定義されているアーティファクト用バケット
  key    = "lambda-layers/dependencies.zip"
}

# ----------------------------------------------------
# Lambdaレイヤーを定義
# ライブラリ(dependencies.zip)は、手動でS3にアップロードされていることを前提とします。
# ----------------------------------------------------
resource "aws_lambda_layer_version" "dependencies_layer" {
  layer_name = "${var.system_name}-${var.env}-dependencies"
  description = "Shared libraries for link checker"

  # 手動でS3にアップロードしたライブラリ用ZIPファイルを参照します
  s3_bucket = aws_s3_bucket.s3_link_checker.id
  s3_key    = "lambda-layers/${var.system_name}_python_libraries.zip"

  # S3上のZIPが更新されたことを検知するために、そのファイルのETag(ハッシュ値)を監視します
  source_code_hash = data.aws_s3_object.dependencies_zip.etag

  compatible_runtimes = ["python3.13"]
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
  function_name = "${var.system_name}-${var.env}-link-checker-lambda"
  handler       = "link_checker_lambda.lambda_handler"
  runtime       = "python3.13"
  role          = aws_iam_role.lambda_exec_role.arn # iam.tfで定義されているロール

  timeout     = 720 # タイムアウト（秒）
  memory_size = 256 # メモリサイズ（MB）- 複数のライブラリを使うため少し増やすことを推奨

  # archive_fileで動的にZIP化したファイルを、デプロイパッケージとして直接指定します
  filename         = data.archive_file.lambda_function_zip.output_path
  source_code_hash = data.archive_file.lambda_function_zip.output_base64sha256

  # 【重要】作成したLambdaレイヤーをこの関数に関連付けます
  layers = [aws_lambda_layer_version.dependencies_layer.arn]

  # Lambda関数内で使用する環境変数を定義します
  environment {
    variables = {
      S3_OUTPUT_BUCKET   = aws_s3_bucket.s3_link_checker.id # 結果を出力するバケット
      LOG_LEVEL          = "INFO"
      REQUEST_TIMEOUT    = 10
      MAX_RETRIES        = 3
      BACKOFF_FACTOR     = 2.0
      MAX_WORKERS        = 1
      CRAWL_WAIT_SECONDS = 5
      NG_WORDS           = "ご指定のページが見つかりませんでした,リンクが無効です"
      GAS_WEBAPP_URL     = "https://script.google.com/macros/s/AKfycbyFFJGBR5GegzTVOZNZOPbFdR6uGPm1-pqLY63K_ZRhecggcvD9QeD2HTiFQoM7aWVY/exec"
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