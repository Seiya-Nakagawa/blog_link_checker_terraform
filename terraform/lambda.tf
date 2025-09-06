resource "aws_sns_topic" "link_checker_sns_topic" {
  name = "${var.system_name}-${var.env}-link-checker-notifications"
}

resource "aws_lambda_function" "link_checker_lambda" {
  function_name    = "${var.system_name}-${var.env}-link-checker-lambda"
  handler          = "link_checker_lambda.lambda_handler"
  runtime          = "python3.12"
  role             = aws_iam_role.lambda_exec_role.arn
  timeout          = 300
  memory_size      = 128

  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256

  environment {
    variables = {
      SNS_TOPIC_ARN = aws_sns_topic.link_checker_sns_topic.arn
    }
  }
}

data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/lambda"
  output_path = "lambda.zip"
}

resource "aws_lambda_permission" "allow_s3_to_call_lambda" {
  statement_id  = "AllowExecutionFromS3Bucket"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.link_checker_lambda.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.s3_link_checker_results.arn
}