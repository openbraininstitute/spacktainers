# Gitlab on AWS

## Prerequisites

Get the private SSH key for Project Hornbach.

## Provision Resources

To deploy a single EC2 instance to run Gitlab on, accessible via HTTP only:

    cd terraform
    terraform apply

This will create a `tf_vars.yml` file in the Ansible inventory directory.

## Set Up Gitlab

    cd ansible
    ansible-playbook -i inventory playbooks/setup.yml
