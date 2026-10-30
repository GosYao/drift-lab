# Capability-intent tests for the workloads stack.
#
# These run with mock providers only: no AWS or Kubernetes account is
# contacted and no credentials are needed. Runs use command = plan; the mock
# providers generate computed values during plan (override_during = plan), and
# the four computed ARNs that matter for scope and identity assertions are
# overridden explicitly so the comparisons below are distinct and meaningful.

# Synthetic, distinct, format-valid ARNs: scope and identity assertions below
# must compare real differences, not shared generated strings. The overrides are
# available during plan so the runs can stay plan-only.
mock_provider "aws" {
  override_during = plan

  override_resource {
    target = aws_iam_role.agent["support-agent"]
    values = {
      arn = "arn:aws:iam::123456789012:role/drift-lab-support-agent"
    }
    override_during = plan
  }

  override_resource {
    target = aws_iam_role.agent["reporting-agent"]
    values = {
      arn = "arn:aws:iam::123456789012:role/drift-lab-reporting-agent"
    }
    override_during = plan
  }

  override_resource {
    target = aws_dynamodb_table.synthetic["customer-orders"]
    values = {
      arn = "arn:aws:dynamodb:us-east-1:123456789012:table/drift-lab-customer-orders"
    }
    override_during = plan
  }

  override_resource {
    target = aws_dynamodb_table.synthetic["customer-archive"]
    values = {
      arn = "arn:aws:dynamodb:us-east-1:123456789012:table/drift-lab-customer-archive"
    }
    override_during = plan
  }
}

mock_provider "kubernetes" {
  override_during = plan
}

variables {
  account_id        = "123456789012" # Canonical synthetic value; never a real account.
  application_image = "000000000000.dkr.ecr.us-east-1.amazonaws.com/drift-lab-preview@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}

run "support_agent_reads_only_orders" {
  command = plan

  assert {
    condition     = jsondecode(aws_iam_role_policy.agent["support-agent"].policy).Statement[0].Effect == "Allow"
    error_message = "The support-agent policy must be a single Allow statement."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.agent["support-agent"].policy).Statement[0].Action == ["dynamodb:GetItem", "dynamodb:Query"]
    error_message = "support-agent may hold only the synthetic read actions: no writes, no wildcards."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.agent["support-agent"].policy).Statement[0].Resource == [aws_dynamodb_table.synthetic["customer-orders"].arn]
    error_message = "support-agent must read only the customer-orders table."
  }
}

run "reporting_agent_reads_orders_and_archive" {
  command = plan

  assert {
    condition     = jsondecode(aws_iam_role_policy.agent["reporting-agent"].policy).Statement[0].Action == ["dynamodb:GetItem", "dynamodb:Query"]
    error_message = "reporting-agent may hold only the synthetic read actions."
  }
  assert {
    condition = toset(jsondecode(aws_iam_role_policy.agent["reporting-agent"].policy).Statement[0].Resource) == toset([
      aws_dynamodb_table.synthetic["customer-orders"].arn,
      aws_dynamodb_table.synthetic["customer-archive"].arn
    ])
    error_message = "reporting-agent must read only the customer-orders and customer-archive tables."
  }
}

run "pod_identity_is_pinned_to_the_lab_roles" {
  command = plan

  assert {
    condition     = aws_eks_pod_identity_association.agent["support-agent"].service_account == "support-agent"
    error_message = "The support-agent association must bind the support-agent service account."
  }
  assert {
    condition     = aws_eks_pod_identity_association.agent["support-agent"].namespace == kubernetes_namespace_v1.demo.metadata[0].name
    error_message = "The support-agent association must live in the lab namespace."
  }
  assert {
    condition     = aws_eks_pod_identity_association.agent["support-agent"].role_arn == aws_iam_role.agent["support-agent"].arn
    error_message = "The support-agent association must point only at the support-agent role."
  }
  assert {
    condition     = aws_eks_pod_identity_association.agent["reporting-agent"].role_arn == aws_iam_role.agent["reporting-agent"].arn
    error_message = "The reporting-agent association must point only at the reporting-agent role."
  }
  assert {
    condition     = kubernetes_service_account_v1.agent["support-agent"].automount_service_account_token == false
    error_message = "Service accounts must not automount API tokens."
  }
  assert {
    condition     = kubernetes_service_account_v1.agent["reporting-agent"].automount_service_account_token == false
    error_message = "Service accounts must not automount API tokens."
  }
}

run "workload_runs_hardened_on_the_support_identity" {
  command = plan

  assert {
    condition     = kubernetes_deployment_v1.preview.spec[0].template[0].spec[0].service_account_name == "support-agent"
    error_message = "The preview workload must run as the support-agent identity."
  }
  assert {
    condition     = kubernetes_deployment_v1.preview.spec[0].template[0].spec[0].automount_service_account_token == false
    error_message = "The preview pod must not automount API tokens."
  }
  assert {
    condition     = tonumber(kubernetes_deployment_v1.preview.spec[0].replicas) == 1
    error_message = "The approved replica count is 1 (approved range 1-4)."
  }
  assert {
    condition     = can(regex("@sha256:[a-f0-9]{64}$", kubernetes_deployment_v1.preview.spec[0].template[0].spec[0].container[0].image))
    error_message = "The workload image must be pinned by immutable digest."
  }
  assert {
    condition     = kubernetes_deployment_v1.preview.spec[0].template[0].spec[0].container[0].security_context[0].run_as_non_root == true
    error_message = "The container must run as non-root."
  }
  assert {
    condition     = kubernetes_deployment_v1.preview.spec[0].template[0].spec[0].container[0].security_context[0].allow_privilege_escalation == false
    error_message = "The container must not allow privilege escalation."
  }
  assert {
    condition     = kubernetes_deployment_v1.preview.spec[0].template[0].spec[0].container[0].security_context[0].read_only_root_filesystem == true
    error_message = "The container filesystem must be read-only."
  }
  assert {
    condition     = toset(kubernetes_deployment_v1.preview.spec[0].template[0].spec[0].container[0].security_context[0].capabilities[0].drop) == toset(["ALL"])
    error_message = "The container must drop all Linux capabilities."
  }
}

run "namespace_is_isolated" {
  command = plan

  assert {
    condition     = kubernetes_namespace_v1.demo.metadata[0].labels["pod-security.kubernetes.io/enforce"] == "restricted"
    error_message = "The lab namespace must enforce restricted Pod Security."
  }
  assert {
    condition     = toset(kubernetes_network_policy_v1.default_deny.spec[0].policy_types) == toset(["Ingress", "Egress"])
    error_message = "The namespace must default-deny both ingress and egress."
  }
  assert {
    condition = (
      try(length(kubernetes_network_policy_v1.default_deny.spec[0].pod_selector[0].match_labels), 0) == 0 &&
      try(length(kubernetes_network_policy_v1.default_deny.spec[0].pod_selector[0].match_expressions), 0) == 0
    )
    error_message = "The default-deny policy must select all pods (no label filters in pod_selector)."
  }
}
