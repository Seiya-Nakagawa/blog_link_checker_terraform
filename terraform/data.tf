# ----------------------------------------------------
# S3上のライブラリ用ZIPの情報を取得するためのデータソース
# ----------------------------------------------------
data "aws_s3_object" "lambda_libraries_zip" {
  bucket = aws_s3_bucket.s3_link_checker.id # s3.tfで定義されているアーティファクト用バケット
  key    = "lambda-layers/${var.system_name}_python_libraries.zip"
}

# ----------------------------------------------------
# 関数コード用のZIPファイルを自動で作成するためのデータソース
# ----------------------------------------------------
data "archive_file" "lambda_function_zip" {
  type        = "zip"
  
  # ZIPに含めるソースファイルを指定します (ワーキングディレクトリからの相対パス)
  source_file = "${path.cwd}/lambda/link_checker_lambda.py"
  
  # Terraformが実行される一時ディレクトリにZIPファイルが作成されます
  output_path = "${path.cwd}/build/lambda_function.zip"
}

# SNSトピックのポリシードキュメントを作成
data "aws_iam_policy_document" "sns_topic_policy_document_system" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["*"]
    }
    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.sns_topic_system.arn]
    
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = var.aws_account_id
    }
  }
}