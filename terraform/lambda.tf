# Lambda Function
resource "aws_lambda_function" "link_checker_lambda" {
  function_name    = "blog-link-checker-lambda"
  handler          = "link_checker_lambda.lambda_handler"
  runtime          = "python3.9"
  timeout          = 300 # 5 minutes
  memory_size      = 128

  # The Lambda function code is packaged as a zip file
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256

  role = aws_iam_role.lambda_exec_role.arn

  environment {
    variables = {
      LOG_LEVEL = "INFO"
      
      # SLACK_WEBHOOK_URL = "YOUR_SLACK_WEBHOOK_URL" # Replace with actual Slack webhook URL
    }
  }
}

# Data source for zipping the Lambda code
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/lambda"
  output_path = "${path.module}/lambda_function.zip"
  excludes    = ["lambda_function.zip", "*.tf"] # Exclude the zip itself and terraform files
}

# Permission for S3 to invoke Lambda
resource "aws_lambda_permission" "allow_s3_to_call_lambda" {
  statement_id  = "AllowS3InvokeLambda"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.link_checker_lambda.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.s3_link_checker_results.arn
}


