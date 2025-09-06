# ----------------------------------------------------
# SNSトピック
# ----------------------------------------------------
resource "aws_sns_topic" "link_checker_sns_topic" {
  name = "${var.system_name}-${var.env}-link-checker-notifications"
}

# ----------------------------------------------------
# Pythonビルドスクリプトを実行して、ZIPのパスとハッシュを取得する
# ----------------------------------------------------
data "external" "lambda_package" {
  # Terraform Cloud環境でPython3を使ってビルドスクリプトを実行
  program = ["python3", "${path.cwd}/scripts/build_lambda.py"]

  # ソースコードが変更されたら、このデータソースを再評価（スクリプトを再実行）する
  query = {
    script_sha1           = sha1(file("${path.cwd}/scripts/build_lambda.py"))
    lambda_py_sha1        = sha1(file("${path.cwd}/lambda/link_checker_lambda.py"))
    requirements_txt_sha1 = sha1(file("${path.cwd}/lambda/requirements.txt"))
  }
}

# ----------------------------------------------------
# Lambda関数の定義
# ----------------------------------------------------
resource "aws_lambda_function" "link_checker_lambda" {
  function_name = "${var.system_name}-${var.env}-link-checker-lambda"
  handler       = "link_checker_lambda.lambda_handler"
  runtime       = "python3.13"
  role          = aws_iam_role.lambda_exec_role.arn
  timeout       = 300
  memory_size   = 128

  # ビルドスクリプトが出力したJSONから、ZIPのパスとハッシュを直接参照する
  filename         = data.external.lambda_package.result.output_path
  source_code_hash = data.external.lambda_package.result.output_base64sha256

  environment {
    variables = {
      SNS_TOPIC_ARN = aws_sns_topic.link_checker_sns_topic.arn
    }
  }
}

# ----------------------------------------------------
# S3からの実行権限
# ----------------------------------------------------
resource "aws_lambda_permission" "allow_s3_to_call_lambda" {
  statement_id  = "AllowExecutionFromS3Bucket"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.link_checker_lambda.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.s3_link_checker_results.arn
}