variable "prefix" {
  default = "hornbach"
}

variable "region" {
  default = "us-east-1"
}

variable "ssh_public_key_file" {
  default = "../keys/hornbach.pub"
}

# variable "external_ip_allocation" {
#   default = "<AWS_IP_ALLOCATION_ID>"
# }

variable "epfl_cidr_blocks" {
  default = ["128.178.0.0/16", "128.179.0.0/16"]
}
