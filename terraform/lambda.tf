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
  # 実行するビルドスクリプトを指定
  program = ["bash", "${path.module}/../scripts/build_lambda.sh"]

  # 【修正】"triggers" の代わりに "query" を使用します。
  # このqueryマップの値が変更されると、Terraformはこのデータソースを再評価し、
  # programで指定されたスクリプトを再実行します。
  # スクリプト自体はqueryの内容を使いませんが、この仕組みで変更を検知します。
  query = {
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

  # 外部スクリプトが生成したZIPファイルのパスを指定
  filename = data.external.lambda_package.result.output_path

  # ZIPファイルのハッシュを計算
  source_code_hash = filebase64sha256(data.external.lambda_package.result.output_path)

  environment {
    variables = {
      SNS_TOPIC_ARN = aws_sns_topic.link_checker_sns_topic.arn
    }
  }
  
  # depends_onは明示的な依存関係として残しておくとより安全です
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