resource "aws_sns_topic" "link_checker_sns_topic" {
  name = "${var.system_name}-${var.env}-link-checker-notifications"
}