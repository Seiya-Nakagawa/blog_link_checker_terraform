# ----------------------------------------------------
# SNSトピック
# ----------------------------------------------------
resource "aws_sns_topic" "link_checker_sns_topic" {
  name = "${var.system_name}-${var.env}-link-checker-notifications"
}

# ----------------------------------------------------
# ステップ1: ビルド用ディレクトリに必要なファイルをすべて集める
# ----------------------------------------------------
resource "null_resource" "prepare_lambda_package" {
  triggers = {
    # Pythonコードかライブラリリストが変更されたら再実行
    lambda_py_hash  = filebase64sha256("${path.cwd}/lambda/link_checker_lambda.py")
    requirements_hash = filebase64sha256("${path.cwd}/lambda/requirements.txt")
  }

  provisioner "local-exec" {
    # 複数のコマンドを順に実行
    command = <<-EOT
      # 既存のビルドディレクトリをクリーンアップ
      rm -rf ${path.cwd}/build/lambda_package
      
      # ビルド用ディレクトリを作成
      mkdir -p ${path.cwd}/build/lambda_package
      
      # ライブラリをビルド用ディレクトリにインストール
      pip install -r ${path.cwd}/lambda/requirements.txt -t ${path.cwd}/build/lambda_package
      
      # あなたのLambdaコードをビルド用ディレクトリにコピー
      cp ${path.cwd}/lambda/link_checker_lambda.py ${path.cwd}/build/lambda_package/
    EOT
  }
}

# ----------------------------------------------------
# ステップ2: ビルド用ディレクトリを丸ごとZIP化する
# ----------------------------------------------------
data "archive_file" "lambda_zip" {
  type        = "zip"
  output_path = "${path.cwd}/build/lambda_package.zip"

  # 【修正】source_dirで、すべてのファイルが集約されたディレクトリを指定
  source_dir  = "${path.cwd}/build/lambda_package"

  # null_resourceによるファイル準備が終わってからZIP化を実行するように依存関係を設定
  depends_on = [null_resource.prepare_lambda_package]
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