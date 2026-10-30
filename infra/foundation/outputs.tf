output "state_bucket" {
  value = aws_s3_bucket.state.id
}

output "preview_repository_url" {
  value = aws_ecr_repository.preview.repository_url
}

output "github_observer_role_arn" {
  value = aws_iam_role.github_observer.arn
}
