# ----------------------------------------------------
# SNSトピック
# ----------------------------------------------------
resource "aws_sns_topic" "link_checker_sns_topic" {
  name = "${var.system_name}-${var.env}-link-checker-notifications"
}

# ----------------------------------------------------
# Lambdaレイヤーを定義
# ----------------------------------------------------
resource "aws_lambda_layer_version" "dependencies_layer" {
  layer_name = "${var.system_name}-${var.env}-dependencies"
  description = "Shared libraries for link checker"
  s3_bucket = aws_s3_bucket.s3_link_checker.id
  s3_key    = "lambda-layers/dependencies.zip"
  source_code_hash = data.aws_s3_object.dependencies_zip.etag
  compatible_runtimes = ["python3.13"]
}

# ----------------------------------------------------
# 【追加】ZIPファイルの出力先ディレクトリを作成するためのリソース
# ----------------------------------------------------
resource "null_resource" "make_build_dir" {
  # このリソースは、コードが変更された場合にのみ再実行されるようにトリガーを設定
  triggers = {
    lambda_py_hash = filebase64sha256("${path.cwd}/lambda/link_checker_lambda.py")
  }

  provisioner "local-exec" {
    # buildディレクトリが存在しない場合にのみ作成する
    command = "mkdir -p ${path.cwd}/build"
  }
}

# ----------------------------------------------------
# 関数コード用のZIPファイルを自動で作成する
# ----------------------------------------------------
data "archive_file" "lambda_function_zip" {
  type        = "zip"
  source_file = "${path.cwd}/lambda/link_checker_lambda.py"
  output_path = "${path.cwd}/build/lambda_function.zip"

  # 【重要】ディレクトリ作成が終わってからZIP化を実行するように依存関係を設定
  depends_on = [null_resource.make_build_dir]
}

# ----------------------------------------------------
# Lambda関数を定義
# ----------------------------------------------------
resource "aws_lambda_function" "link_checker_lambda" {
  function_name = "${var.system_name}-${var.env}-link-checker-lambda"
  handler       = "link_checker_lambda.lambda_handler"
  runtime       = "python3.13"
  role          = aws_iam_role.lambda_exec_role.arn
  timeout       = 300
  memory_size   = 128

  filename         = data.archive_file.lambda_function_zip.output_path
  source_code_hash = data.archive_file.lambda_function_zip.output_base64sha256
  layers = [aws_lambda_layer_version.dependencies_layer.arn]

  environment {
    variables = {
      SNS_TOPIC_ARN = aws_sns_topic.link_checker_sns_topic.arn
    }
  }
}

# ----------------------------------------------------
# S3上のライブラリ用ZIPの情報を取得
# ----------------------------------------------------
data "aws_s3_object" "dependencies_zip" {
  bucket = aws_s3_bucket.s3_link_checker.id
  key    = "lambda-layers/dependencies.zip"
}

# ----------------------------------------------------
# S3からの実行権限
# ----------------------------------------------------
resource "aws_lambda_permission" "allow_s3_to_call_lambda" {
  statement_id  = "AllowExecutionFromS3Bucket"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.link_checker_lambda.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.s3_link_checker.arn
}