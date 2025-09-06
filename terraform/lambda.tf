# ----------------------------------------------------
# SNSトピック
# ----------------------------------------------------
resource "aws_sns_topic" "link_checker_sns_topic" {
  name = "${var.system_name}-${var.env}-link-checker-notifications"
}

# ----------------------------------------------------
# Lambdaレイヤーを定義
# ライブラリ(dependencies.zip)は、手動でS3にアップロードされていることを前提とします。
# ----------------------------------------------------
resource "aws_lambda_layer_version" "dependencies_layer" {
  layer_name = "${var.system_name}-${var.env}-dependencies"
  description = "Shared libraries for link checker"

  # 手動でS3にアップロードしたライブラリ用ZIPファイルを参照します
  s3_bucket = aws_s3_bucket.s3_link_checker.id # s3.tfで定義されているバケット名を指定
  s3_key    = "lambda-layers/dependencies.zip"

  # S3上のZIPが更新されたことを検知するために、そのファイルのETag(ハッシュ値)を監視します
  source_code_hash = data.aws_s3_object.dependencies_zip.etag

  compatible_runtimes = ["python3.13"]
}

# ----------------------------------------------------
# Lambda関数を定義
# Pythonコードは、Terraformが自動でZIP化してデプロイします。
# ----------------------------------------------------
resource "aws_lambda_function" "link_checker_lambda" {
  function_name = "${var.system_name}-${var.env}-link-checker-lambda"
  handler       = "link_checker_lambda.lambda_handler"
  runtime       = "python3.13"
  role          = aws_iam_role.lambda_exec_role.arn # iam.tfで定義されているロール名を指定
  timeout       = 300
  memory_size   = 128

  # archive_fileで動的にZIP化したファイルを、デプロイパッケージとして直接指定します
  filename         = data.archive_file.lambda_function_zip.output_path
  source_code_hash = data.archive_file.lambda_function_zip.output_base64sha256

  # 作成したLambdaレイヤーをこの関数に関連付けます
  layers = [aws_lambda_layer_version.dependencies_layer.arn]

  environment {
    variables = {
      SNS_TOPIC_ARN = aws_sns_topic.link_checker_sns_topic.arn
    }
  }
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
# S3上のライブラリ用ZIPの情報を取得するためのデータソース
# ----------------------------------------------------
data "aws_s3_object" "dependencies_zip" {
  bucket = aws_s3_bucket.s3_lambda_artifacts.id # s3.tfで定義されているバケット名を指定
  key    = "lambda-layers/dependencies.zip"
}

# ----------------------------------------------------
# S3からの実行権限
# ----------------------------------------------------
resource "aws_lambda_permission" "allow_s3_to_call_lambda" {
  statement_id  = "AllowExecutionFromS3Bucket"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.link_checker_lambda.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.s3_link_checker_results.arn # s3.tfで定義されているトリガー用バケット名を指定
}