data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, 2)
}

resource "aws_vpc" "lab" {
  cidr_block           = "10.84.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = { Name = var.name }
}

resource "aws_internet_gateway" "lab" {
  vpc_id = aws_vpc.lab.id
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.lab.id
  availability_zone       = local.azs[count.index]
  cidr_block              = cidrsubnet(aws_vpc.lab.cidr_block, 8, count.index)
  map_public_ip_on_launch = false
  tags = {
    Name                     = "${var.name}-public-${count.index}"
    "kubernetes.io/role/elb" = "1"
  }
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.lab.id
  availability_zone = local.azs[count.index]
  cidr_block        = cidrsubnet(aws_vpc.lab.cidr_block, 8, count.index + 10)
  tags = {
    Name                              = "${var.name}-private-${count.index}"
    "kubernetes.io/role/internal-elb" = "1"
  }
}

resource "aws_eip" "nat" {
  domain = "vpc"
}

resource "aws_nat_gateway" "lab" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id
  depends_on    = [aws_internet_gateway.lab]
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.lab.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.lab.id
  }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.lab.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.lab.id
  }
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

resource "aws_vpc_endpoint" "gateway" {
  for_each          = toset(["s3", "dynamodb"])
  vpc_id            = aws_vpc.lab.id
  service_name      = "com.amazonaws.${var.region}.${each.key}"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
}

resource "aws_iam_role" "cluster" {
  name = "${var.name}-cluster"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow", Principal = { Service = "eks.amazonaws.com" }, Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "cluster" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_cloudwatch_log_group" "cluster" {
  name              = "/aws/eks/${var.name}/cluster"
  retention_in_days = 7
}

resource "aws_eks_cluster" "lab" {
  name                      = var.name
  role_arn                  = aws_iam_role.cluster.arn
  version                   = var.kubernetes_version
  enabled_cluster_log_types = ["api", "audit", "authenticator"]
  access_config {
    authentication_mode                         = "API"
    bootstrap_cluster_creator_admin_permissions = false
  }
  vpc_config {
    subnet_ids              = aws_subnet.private[*].id
    endpoint_private_access = true
    endpoint_public_access  = length(var.public_access_cidrs) > 0
    public_access_cidrs     = length(var.public_access_cidrs) > 0 ? var.public_access_cidrs : null
  }
  depends_on = [
    aws_iam_role_policy_attachment.cluster,
    aws_cloudwatch_log_group.cluster,
    aws_route_table_association.private
  ]
}

resource "aws_eks_access_entry" "admin" {
  cluster_name  = aws_eks_cluster.lab.name
  principal_arn = var.cluster_admin_principal_arn
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "admin" {
  cluster_name  = aws_eks_cluster.lab.name
  principal_arn = aws_eks_access_entry.admin.principal_arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  access_scope {
    type = "cluster"
  }
}

resource "aws_iam_role" "nodes" {
  name = "${var.name}-nodes"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "nodes" {
  for_each = toset([
    "AmazonEKSWorkerNodePolicy",
    "AmazonEC2ContainerRegistryPullOnly",
    "AmazonEKS_CNI_Policy"
  ])
  role       = aws_iam_role.nodes.name
  policy_arn = "arn:aws:iam::aws:policy/${each.key}"
  # Initial bootstrap uses node-level CNI permissions. Move CNI to a dedicated
  # identity before any untrusted workload or real-data pilot (see ADR-0003).
}

resource "aws_launch_template" "nodes" {
  name_prefix = "${var.name}-"
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }
  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = 30
      volume_type           = "gp3"
      encrypted             = true
      delete_on_termination = true
    }
  }
}

resource "aws_eks_node_group" "lab" {
  cluster_name    = aws_eks_cluster.lab.name
  node_group_name = "demo"
  node_role_arn   = aws_iam_role.nodes.arn
  subnet_ids      = aws_subnet.private[*].id
  instance_types  = [var.instance_type]
  capacity_type   = "ON_DEMAND"
  ami_type        = "AL2023_x86_64_STANDARD"
  scaling_config {
    desired_size = 1
    min_size     = 0
    max_size     = 2
  }
  launch_template {
    id      = aws_launch_template.nodes.id
    version = aws_launch_template.nodes.latest_version
  }
  depends_on = [aws_iam_role_policy_attachment.nodes]
}

data "aws_eks_addon_version" "selected" {
  for_each           = toset(["vpc-cni", "coredns", "kube-proxy", "eks-pod-identity-agent"])
  addon_name         = each.key
  kubernetes_version = var.kubernetes_version
  most_recent        = true
}

resource "aws_eks_addon" "selected" {
  for_each                    = data.aws_eks_addon_version.selected
  cluster_name                = aws_eks_cluster.lab.name
  addon_name                  = each.key
  addon_version               = each.value.version
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "PRESERVE"
  configuration_values        = each.key == "vpc-cni" ? jsonencode({ enableNetworkPolicy = "true" }) : null
  depends_on                  = [aws_eks_node_group.lab]
}
