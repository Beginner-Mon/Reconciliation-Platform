output "api_url" {
  description = "URL API Gateway"
  value       = module.aws.api_url
}

output "documents_bucket" {
  description = "Tên S3 bucket chứng từ"
  value       = module.aws.documents_bucket
}

output "documents_table" {
  description = "Tên bảng DynamoDB documents"
  value       = module.aws.documents_table
}

output "audit_log_table" {
  description = "Tên bảng DynamoDB audit_log"
  value       = module.aws.audit_log_table
}

output "gcp_service_account_email" {
  description = "Email service account Google (dùng để kiểm tra quyền)"
  value       = module.gcp.sa_email
}
