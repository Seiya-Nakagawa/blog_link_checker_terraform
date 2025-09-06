# ----------------------------------------------------
# SNSトピック
# ----------------------------------------------------
resource "aws_sns_topic" "link_checker_sns_topic" {
  name = "${var.system_name}-${var.env}-link-checker-notifications"
}

# ----------------------------------------------------
# 外部スクリプトを使ってLambdaパッケージをビルドする
# ----------------------------------------------------
data "external" "lambda_package" {
  # 【変更】スクリプトのパスを修正 (terraform/から見て ../scripts/ になる)
  program = ["bash", "${path.module}/../scripts/build_lambda.sh"]

  # 【変更】トリガーのファイルパスをすべて修正
  triggers = {
    script_sha1           = sha1(file("${path.module}/../scripts/build_lambda.sh"))
    lambda_py_sha1        = sha1(file("${path.module}/../lambda/link_checker_lambda.py"))
    requirements_txt_sha1 = sha1(file("${path.module}/../lambda/requirements.txt"))
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

  # 外部スクリプトが生成したZIPファイルのパスを指定 (この部分は変更なし)
  filename = data.external.lambda_package.result.output_path

  # ZIPファイルのハッシュを計算 (この部分は変更なし)
  source_code_hash = filebase64sha256(data.external.lambda_package.result.output_path)

  environment {
    variables = {
      SNS_TOPIC_ARN = aws_sns_topic.link_checker_sns_topic.arn
    }
  }
  
  depends_on = [data.external.lambda_package]
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