# ----------------------------------------------------
# SNSトピック
# ----------------------------------------------------
resource "aws_sns_topic" "link_checker_sns_topic" {
  name = "${var.system_name}-${var.env}-link-checker-notifications"
}

# ----------------------------------------------------
# ステップ1: `pip install`を実行してライブラリを一時ディレクトリに配置する
# ----------------------------------------------------
resource "null_resource" "install_lambda_dependencies" {
  triggers = {
    # requirements.txtが変更されたら再実行
    requirements_hash = file("${path.cwd}/lambda/requirements.txt")
  }

  provisioner "local-exec" {
    # ライブラリをプロジェクトルートのbuild/dependenciesディレクトリにインストールする
    command = "pip install -r ${path.cwd}/lambda/requirements.txt -t ${path.cwd}/build/dependencies"
  }
}

# ----------------------------------------------------
# ステップ2: インストールされたライブラリのファイル一覧を取得する
# ----------------------------------------------------
data "archive_file" "lambda_zip" {
  type        = "zip"
  output_path = "${path.cwd}/build/lambda_package.zip"

  # あなたのLambdaコードをZIPに含める
  source {
    content  = file("${path.cwd}/lambda/link_checker_lambda.py")
    filename = "link_checker_lambda.py"
  }

  # ライブラリがインストールされたディレクトリをZIPに含める
  # このsource_dirは、null_resourceの実行後に存在する必要がある
  source_dir = "${path.cwd}/build/dependencies"

  # null_resourceによるインストールが終わってからZIP化を実行するように依存関係を設定
  depends_on = [null_resource.install_lambda_dependencies]
}

# ----------------------------------------------------
# ステップ3: Lambda関数を定義する
# ----------------------------------------------------
resource "aws_lambda_function" "link_checker_lambda" {
  function_name = "${var.system_name}-${var.env}-link-checker-lambda"
  handler       = "link_checker_lambda.lambda_handler"
  runtime       = "python3.13"
  role          = aws_iam_role.lambda_exec_role.arn
  timeout       = 300
  memory_size   = 128

  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256

  environment {
    variables = {
      SNS_TOPIC_ARN = aws_sns_topic.link_checker_sns_topic.arn
    }
  }
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