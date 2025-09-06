# lambda.tf

# ----------------------------------------------------
# SNSトピック (変更なし)
# ----------------------------------------------------
resource "aws_sns_topic" "link_checker_sns_topic" {
  name = "${var.system_name}-${var.env}-link-checker-notifications"
}

# ----------------------------------------------------
# 【追加】Lambdaデプロイパッケージを自動でビルドするリソース
# ----------------------------------------------------
resource "null_resource" "build_lambda_package" {
  # このトリガーにより、Pythonコードやライブラリリストが変更された場合にのみ
  # 以下のビルド処理が再実行されます。
  triggers = {
    lambda_py_sha1        = sha1(file("${path.module}/lambda/link_checker_lambda.py"))
    requirements_txt_sha1 = sha1(file("${path.module}/lambda/requirements.txt"))
  }

  # Terraform Cloudの実行環境で以下のコマンドを実行します
  provisioner "local-exec" {
    command = <<-EOT
      # 一時的なビルド用ディレクトリを作成 (存在すれば削除してから作成)
      rm -rf ${path.module}/build
      mkdir -p ${path.module}/build/lambda_package
      
      # Lambdaのソースコードをビルド用ディレクトリにコピー
      cp ${path.module}/lambda/link_checker_lambda.py ${path.module}/build/lambda_package/
      
      # requirements.txtを使ってライブラリをビルド用ディレクトリにインストール
      pip install -r ${path.module}/lambda/requirements.txt -t ${path.module}/build/lambda_package/
    EOT
  }
}

# ----------------------------------------------------
# 【変更】ビルドされたパッケージ全体をZIP化する
# ----------------------------------------------------
resource "archive_file" "lambda_zip" {
  type        = "zip"
  # ビルドされたコードとライブラリが含まれるディレクトリを指定
  source_dir  = "${path.module}/build/lambda_package"
  output_path = "${path.module}/lambda_package.zip"

  # null_resourceによるビルド処理が終わってからZIP化を実行するように依存関係を設定
  depends_on = [null_resource.build_lambda_package]
}

# ----------------------------------------------------
# 【変更】Lambda関数の定義をシンプルにする
# ----------------------------------------------------
resource "aws_lambda_function" "link_checker_lambda" {
  function_name = "${var.system_name}-${var.env}-link-checker-lambda"
  handler       = "link_checker_lambda.lambda_handler"
  runtime       = "python3.13" # ご自身のランタイムに合わせてください
  role          = aws_iam_role.lambda_exec_role.arn # iam.tfで定義されていることを想定
  timeout       = 300
  memory_size   = 128

  # S3経由ではなく、生成したZIPファイルを直接指定
  filename         = resource.archive_file.lambda_zip.output_path
  source_code_hash = resource.archive_file.lambda_zip.output_base64sha256

  # 【削除】レイヤーは不要なのでlayers属性を削除します

  environment {
    variables = {
      SNS_TOPIC_ARN = aws_sns_topic.link_checker_sns_topic.arn
    }
  }
}

# ----------------------------------------------------
# S3からの実行権限 (変更なし)
# ----------------------------------------------------
resource "aws_lambda_permission" "allow_s3_to_call_lambda" {
  statement_id  = "AllowExecutionFromS3Bucket"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.link_checker_lambda.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.s3_link_checker_results.arn # s3.tfで定義されていることを想定
}