output "cluster_name" {
  value = aws_eks_cluster.lab.name
}

output "vpc_id" {
  value = aws_vpc.lab.id
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "expiry_is_advisory" {
  value = "ExpiresAt is a tag only. No scheduled teardown controller is installed."
}
