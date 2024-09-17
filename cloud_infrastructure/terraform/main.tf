terraform {
  backend "s3" {
    bucket = "hornbach-56730253c164"
    key    = "hornbach.tfstate"
    region = "us-east-1"
  }
  required_providers {
    aws = {
      source  = "hashicorp/aws"
    }
  }
}

# Configure the AWS Provider
provider "aws" {
  region = var.region
}
