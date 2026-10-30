resource "kubernetes_namespace_v1" "demo" {
  metadata {
    name = "drift-lab"
    labels = {
      "app.kubernetes.io/part-of"                  = "drift-lab"
      "pod-security.kubernetes.io/enforce"         = "restricted"
      "pod-security.kubernetes.io/enforce-version" = "v${data.aws_eks_cluster.lab.version}"
    }
  }
}

resource "kubernetes_resource_quota_v1" "demo" {
  metadata {
    name      = "demo-quota"
    namespace = kubernetes_namespace_v1.demo.metadata[0].name
  }
  spec {
    hard = {
      "requests.cpu"    = "1"
      "requests.memory" = "1Gi"
      "limits.cpu"      = "2"
      "limits.memory"   = "2Gi"
      pods              = "6"
      services          = "3"
    }
  }
}

resource "kubernetes_service_account_v1" "agent" {
  for_each = toset(["support-agent", "reporting-agent"])
  metadata {
    name      = each.key
    namespace = kubernetes_namespace_v1.demo.metadata[0].name
  }
  automount_service_account_token = false
}

resource "aws_dynamodb_table" "synthetic" {
  for_each     = toset(["customer-orders", "customer-archive"])
  name         = "${var.cluster_name}-${each.key}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"
  attribute {
    name = "id"
    type = "S"
  }
  server_side_encryption {
    enabled = true
  }
  tags = { DataClassification = "synthetic-only" }
}

resource "aws_iam_role" "agent" {
  for_each = toset(["support-agent", "reporting-agent"])
  name     = "${var.cluster_name}-${each.key}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })
}

resource "aws_iam_role_policy" "agent" {
  for_each = aws_iam_role.agent
  name     = "synthetic-dataset-reader"
  role     = each.value.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["dynamodb:GetItem", "dynamodb:Query"]
      Resource = each.key == "support-agent" ? [
        aws_dynamodb_table.synthetic["customer-orders"].arn
        ] : [
        aws_dynamodb_table.synthetic["customer-orders"].arn,
        aws_dynamodb_table.synthetic["customer-archive"].arn
      ]
    }]
  })
}

resource "aws_eks_pod_identity_association" "agent" {
  for_each        = aws_iam_role.agent
  cluster_name    = var.cluster_name
  namespace       = kubernetes_namespace_v1.demo.metadata[0].name
  service_account = kubernetes_service_account_v1.agent[each.key].metadata[0].name
  role_arn        = each.value.arn
}

resource "kubernetes_deployment_v1" "preview" {
  metadata {
    name      = "support-agent"
    namespace = kubernetes_namespace_v1.demo.metadata[0].name
  }
  spec {
    replicas = 1
    selector {
      match_labels = { app = "drift-preview" }
    }
    template {
      metadata {
        labels = { app = "drift-preview" }
      }
      spec {
        service_account_name            = kubernetes_service_account_v1.agent["support-agent"].metadata[0].name
        automount_service_account_token = false
        security_context {
          run_as_non_root = true
          run_as_user     = 10001
          seccomp_profile {
            type = "RuntimeDefault"
          }
        }
        container {
          name    = "preview"
          image   = var.application_image
          command = ["python", "-m", "drift_lab", "serve", "--host", "0.0.0.0", "--port", "8765"]
          port {
            container_port = 8765
          }
          resources {
            requests = { cpu = "100m", memory = "64Mi" }
            limits   = { cpu = "500m", memory = "256Mi" }
          }
          # The provider sends run_as_non_root = false unless set here, which
          # overrides the pod-level value and fails restricted Pod Security.
          security_context {
            run_as_non_root            = true
            allow_privilege_escalation = false
            read_only_root_filesystem  = true
            capabilities {
              drop = ["ALL"]
            }
          }
          readiness_probe {
            http_get {
              path = "/api/health"
              port = 8765
            }
            initial_delay_seconds = 2
          }
          liveness_probe {
            http_get {
              path = "/api/health"
              port = 8765
            }
            initial_delay_seconds = 10
          }
        }
      }
    }
  }
  depends_on = [kubernetes_resource_quota_v1.demo]
}

# The fixture preview needs no network egress or public service.
# Pod Identity/Bedrock/DynamoDB access needs a separately reviewed egress design
# before a real agent is substituted. Do not silently broaden this policy.
resource "kubernetes_network_policy_v1" "default_deny" {
  metadata {
    name      = "default-deny"
    namespace = kubernetes_namespace_v1.demo.metadata[0].name
  }
  spec {
    pod_selector {}
    policy_types = ["Ingress", "Egress"]
  }
}
