# IAM Role for Lambda
resource "aws_iam_role" "lambda_exec_role" {
  name = "blog-link-checker-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action = "sts:AssumeRole",
        Effect = "Allow",
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

# IAM Policy for Lambda
resource "aws_iam_role_policy_attachment" "lambda_policy_cwlogs" {
  role       = aws_iam_role.lambda_exec_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_policy_s3" {
  role       = aws_iam_role.lambda_exec_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
}


# IAM Role for CloudWatchLogs
resource "aws_iam_role" "cwlogs_exec_role" {
  name = "blog-link-checker-cwlogs-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action = "sts:AssumeRole",
        Effect = "Allow",
        Principal = {
          Service = "logs.amazonaws.com"
        }
      }
    ]
  })
}

# IAM Policy for cwlogs
resource "aws_iam_role_policy_attachment" "cwlogs_policy_cwlogs" {
  role       = aws_iam_role.cwlogs_exec_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSNSFullAccess"
}
