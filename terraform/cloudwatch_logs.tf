# ----------------------------------------------------
# CloudWatch Logs
# ----------------------------------------------------
resource "aws_cloudwatch_log_group" "lambda_log_group" {
  name              = "/aws/lambda/${var.system_name}-${var.env}-link-checker-lambda"
  retention_in_days = 1
  tags = {
    Name        = "${var.system_name}-${var.env}-link-checker-lambda-log-group",
    SystemName  = var.system_name,
    Env         = var.env,
  }
}