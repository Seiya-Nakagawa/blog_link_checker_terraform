# versions.tf

# Terraformの実行環境に関する設定
terraform {
  required_version = ">= 1.12.2"

  # Terraform Cloudをバックエンドとして設定
  cloud {
    organization = "aibdlnew1-organization"

    # このコードがどのワークスペース群に属するかを示すタグを設定
    workspaces {
      name = "aws-blogcheker-prd"
    }
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.30"
    }
  }
}

# プライマリリージョン (東京)
provider "aws" {
  region = "ap-northeast-1"

  assume_role {
    role_arn = "arn:aws:iam::${var.aws_account_id}:role/member-${var.env}-iamrole-terraform"
  }
}

# グローバルサービス用プロバイダ (バージニア北部)
provider "aws" {
  alias  = "us-east-1"
  region = "us-east-1"
}