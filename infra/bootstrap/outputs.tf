output "bucket" {
  description = "Tên bucket chứa tfstate"
  value       = aws_s3_bucket.tfstate.bucket
}

output "backend_hcl" {
  description = "Nội dung backend.hcl in sẵn để copy"
  value       = <<-EOT
    bucket       = "${aws_s3_bucket.tfstate.bucket}"
    key          = "reconciliation-platform/prod/terraform.tfstate"
    region       = "${var.aws_region}"
    encrypt      = true
    use_lockfile = true
  EOT
}
