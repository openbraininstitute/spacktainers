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
  for_each = {
    for item in flatten([
      for block in var.epfl_cidr_blocks : [
        for port in [80] : {  # , 443, 8443] : {
          block = block
          port  = port
        }
      ]
    ])
    : "${item.block}:${item.port}" => item
  }
  #  toset(var.epfl_cidr_blocks)

  security_group_id = aws_security_group.external_gitlab_vm_https_access.id

  description = "External HTTP(S) access for VMs from CIDR block ${each.key}"
  from_port   = each.value.port
  to_port     = each.value.port
  ip_protocol = "tcp"

  cidr_ipv4 = each.value.block

  tags = {
    Name = "${var.prefix}-vm-https-${each.key}"
  }
}

resource "local_file" "public_ip" {
  filename = "../ansible/inventory/tf_vars.yml"
  file_permission = "0666"
  content = yamlencode({"all": {"vars": {"external_url": "http://${module.gitlab_ref_arch_aws.gitlab_rails.external_addresses[0]}"}}})
}

output "gitlab_ref_arch_aws" {
  value = module.gitlab_ref_arch_aws
}
