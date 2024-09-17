module "gitlab_ref_arch_aws" {
  source = "git::https://gitlab.com/gitlab-org/gitlab-environment-toolkit.git//terraform/modules/gitlab_ref_arch_aws"

  prefix         = var.prefix
  ssh_public_key = file(var.ssh_public_key_file)

  # 1k
  gitlab_rails_node_count    = 1
  gitlab_rails_instance_type = "t3.large"

  object_storage_buckets = []

  gitlab_rails_security_group_ids = [aws_security_group.external_gitlab_vm_https_access.id]

  # haproxy_external_node_count                = 1
  # haproxy_external_instance_type             = "t3.medium"
  # haproxy_external_elastic_ip_allocation_ids = [var.external_ip_allocation]
}

resource "aws_security_group" "external_gitlab_vm_https_access" {
  name_prefix = "${var.prefix}-vm-https-access-"
  vpc_id      = "${module.gitlab_ref_arch_aws.network.vpc_id}"

  description = "${var.prefix} - VM HTTPS Access Security Group"

  tags = {
    Name = "${var.prefix}-vm-https-access"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "external_gitlab_vm_https_access" {
  for_each = toset(var.epfl_cidr_blocks)

  security_group_id = aws_security_group.external_gitlab_vm_https_access.id

  description = "External HTTPS access for VMs from CIDR block ${each.key}"
  from_port   = 443
  to_port     = 443
  ip_protocol = "tcp"

  cidr_ipv4 = each.key

  tags = {
    Name = "${var.prefix}-vm-https-${each.key}"
  }
}

output "gitlab_ref_arch_aws" {
  value = module.gitlab_ref_arch_aws
}
