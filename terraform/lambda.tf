# ----------------------------------------------------
# Lambda関数を定義 (最小構成)
# ----------------------------------------------------
resource "aws_lambda_function" "link_checker_lambda" {
  function_name = "${var.system_name}-${var.env}-link-checker-lambda"
  handler       = "link_checker_lambda.lambda_handler"
  runtime       = "python3.13"
  # role          = aws_iam_role.lambda_exec_role.arn

  # archive_fileで動的にZIP化したファイルを、デプロイパッケージとして直接指定します
  # filename         = data.archive_file.lambda_function_zip.output_path
  # source_code_hash = data.archive_file.lambda_function_zip.output_base64sha256
}

# # ----------------------------------------------------
# # 関数コード用のZIPファイルを自動で作成する (最小構成)
# # ----------------------------------------------------
# data "archive_file" "lambda_function_zip" {
#   type        = "zip"
  
#   # ZIPに含めるソースファイルを指定します
#   source_file = "${path.cwd}/lambda/link_checker_lambda.py"
  
#   # Terraformが実行される一時ディレクトリにZIPファイルが作成されます
#   # 出力先のディレクトリは指定せず、Terraformに任せます
#   output_path = "${path.cwd}/lambda_function.zip"
# }
