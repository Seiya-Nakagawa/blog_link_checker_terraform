# ----------------------------------------------------
# CloudWatch Alarm for Lambda Errors
# ----------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "lambda_error_alarm" {
  alarm_name          = "${var.system_name}-${var.env}-lambda-error-alarm"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = "1"
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = "300"
  statistic           = "Sum"
  threshold           = "1"
  alarm_description   = "Alarm when the Lambda function has errors"
  alarm_actions       = [aws_sns_topic.sns_topic_system.arn]
  treat_missing_data  = "not_breaching"

  dimensions = {
    FunctionName = aws_lambda_function.link_checker_lambda.function_name
  }

  tags = {
    Name        = "${var.system_name}-${var.env}-lambda-error-alarm",
    SystemName  = var.system_name,
    Env         = var.env,
  }
}

# ----------------------------------------------------
# CloudWatch Alarm for Lambda Throttles
# ----------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "lambda_throttle_alarm" {
  alarm_name          = "${var.system_name}-${var.env}-lambda-throttle-alarm"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = "1"
  metric_name         = "Throttles"
  namespace           = "AWS/Lambda"
  period              = "300"
  statistic           = "Sum"
  threshold           = "1"
  alarm_description   = "Alarm when the Lambda function is throttled"
  alarm_actions       = [aws_sns_topic.sns_topic_system.arn]
  treat_missing_data  = "not_breaching"

  dimensions = {
    FunctionName = aws_lambda_function.link_checker_lambda.function_name
  }

  tags = {
    Name        = "${var.system_name}-${var.env}-lambda-throttle-alarm",
    SystemName  = var.system_name,
    Env         = var.env,
  }
}
