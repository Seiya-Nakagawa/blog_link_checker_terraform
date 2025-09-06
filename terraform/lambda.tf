# ----------------------------------------------------
# Lambda関数を定義 (最小構成)
# ----------------------------------------------------
resource "aws_lambda_function" "link_checker_lambda" {
  function_name = "${var.system_name}-${var.env}-link-checker-lambda"
  handler       = "link_checker_lambda.lambda_handler"
  runtime       = "python3.13"
  role          = aws_iam_role.lambda_exec_role.arn # iam.tfで定義されているロール名を指定

  # archive_fileで動的にZIP化したファイルを、デプロイパッケージとして直接指定します
  filename         = data.archive_file.lambda_function_zip.output_path
  source_code_hash = data.archive_file.lambda_function_zip.output_base64sha256
}

# ----------------------------------------------------
# 関数コード用のZIPファイルを自動で作成する (最小構成)
# ----------------------------------------------------
data "archive_file" "lambda_function_zip" {
  type        = "zip"
  
  # ZIPに含めるソースファイルを指定します
  source_file = "${path.cwd}/lambda/link_checker_lambda.py"
  
  # Terraformが実行される一時ディレクトリにZIPファイルが作成されます
  # 出力先のディレクトリは指定せず、Terraformに任せます
  output_path = "${path.cwd}/lambda_function.zip"
}

# ----------------------------------------------------
# S3からの実行権限
# ----------------------------------------------------
resource "aws_lambda_permission" "allow_s3_to_call_lambda" {
  statement_id  = "AllowExecutionFromS3Bucket"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.link_checker_lambda.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.s3_link_checker.arn
}

# ----------------------------------------------------
# Lambdaレイヤーを定義
# ----------------------------------------------------
# resource "aws_lambda_layer_version" "dependencies_layer" {
#   layer_name = "${var.system_name}-${var.env}-dependencies"
#   description = "Shared libraries for link checker"
#   s3_bucket = aws_s3_bucket.s3_link_checker.id
#   s3_key    = "lambda-layers/dependencies.zip"
#   source_code_hash = data.aws_s3_object.dependencies_zip.etag
#   compatible_runtimes = ["python3.13"]
# }

# ----------------------------------------------------
# S3上のライブラリ用ZIPの情報を取得
# ----------------------------------------------------
data "aws_s3_object" "dependencies_zip" {
  bucket = aws_s3_bucket.s3_link_checker.id
  key    = "lambda-layers/dependencies.zip"
}