output "sa_email" {
  value = google_service_account.lambda.email
}

output "sa_private_key" {
  value     = google_service_account_key.lambda.private_key
  sensitive = true
}
