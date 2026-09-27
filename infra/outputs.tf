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

output "gcp_service_account_email" {
  description = "Email service account Google (dùng để kiểm tra quyền)"
  value       = module.gcp.sa_email
}

output "cognito_user_pool_id" {
  description = "ID Cognito User Pool"
  value       = module.aws.cognito_user_pool_id
}

output "cognito_client_id" {
  description = "ID Cognito App Client (SPA)"
  value       = module.aws.cognito_client_id
}

output "amplify_app_id" {
  description = "ID Amplify App"
  value       = module.aws.amplify_app_id
}

output "amplify_app_url" {
  description = "URL Amplify Hosting"
  value       = module.aws.amplify_app_url
}

output "amplify_branch" {
  description = "Nhánh Amplify"
  value       = module.aws.amplify_branch
}

output "dashboard_url" {
  description = "Link CloudWatch dashboard cho demo"
  value       = module.aws.dashboard_url
}
