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

# ----------------------------------------------------
# CloudWatch Logs Subscription Filter for SNS
# ----------------------------------------------------
resource "aws_cloudwatch_log_subscription_filter" "log_subscription_filter" {
  name           = "${var.system_name}-${var.env}-log-subscription-filter"
  log_group_name = aws_cloudwatch_log_group.lambda_log_group.name
  filter_pattern = "{ $.level = \"WARNING\" || $.level = \"ERROR\" }"
  destination_arn = aws_sns_topic.sns_topic_system.arn

  depends_on = [aws_sns_topic.sns_topic_system]
}
