terraform {
  backend "s3" {
    bucket = "hornbach-56730253c164"
    key    = "hornbach-mirror.tfstate"
    region = "us-east-1"
  }
  required_providers {
    gitlab = {
      source  = "gitlabhq/gitlab"
    }
  }
}

provider "gitlab" {
  token = var.gitlab_token
  base_url = "http://44.203.10.216:80/api/v4/"
  insecure = true
}
