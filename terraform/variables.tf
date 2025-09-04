variable "aws_region" {
  description = "デプロイするAWSリージョン"
  type        = string
}

variable "system_name" {
  description = "システム識別子"
  type        = string
}

variable "env" {
  description = "環境識別子"
  type        = string
}

variable "aws_account_id" {
  description = "AWSアカウントID"
  type        = string
}