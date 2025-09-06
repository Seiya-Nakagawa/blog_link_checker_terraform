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
resource "aws_iam_role_policy_attachment" "lambda_policy_s3_logs" {
  role       = aws_iam_role.lambda_exec_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# resource "aws_iam_role_policy" "lambda_s3_access_policy" {
#   name = "blog-link-checker-lambda-s3-access-policy"
#   role = aws_iam_role.lambda_exec_role.id

#   policy = jsonencode({
#     Version = "2012-10-17",
#     Statement = [
#       {
#         Action = [
#           "s3:GetObject",
#           "s3:GetObjectVersion"
#         ],
#         Effect = "Allow",
#         Resource = [
#           aws_s3_bucket.s3_link_checker.arn,
#           "${aws_s3_bucket.s3_link_checker.arn}/*"
#         ]
#       }
#     ]
#   })
# }
