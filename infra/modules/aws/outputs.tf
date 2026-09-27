output "documents_bucket" {
  value = aws_s3_bucket.documents.bucket
}

output "projects_table" {
  value = aws_dynamodb_table.projects.name
}

output "documents_table" {
  value = aws_dynamodb_table.documents.name
}

output "processing_runs_table" {
  value = aws_dynamodb_table.processing_runs.name
}

output "reconciliations_table" {
  value = aws_dynamodb_table.reconciliations.name
}

output "api_url" {
  value = aws_apigatewayv2_stage.default.invoke_url
}

output "state_machine_arn" {
  value = aws_sfn_state_machine.process.arn
}

output "api_function_names" {
  value = { for name, fn in aws_lambda_function.api : name => fn.function_name }
}

output "worker_function_names" {
  value = { for name, fn in aws_lambda_function.worker : name => fn.function_name }
}

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.main.id
}

output "cognito_client_id" {
  value = aws_cognito_user_pool_client.main.id
}

output "amplify_app_id" {
  value = aws_amplify_app.main.id
}

output "amplify_app_url" {
  value = local.amplify_url
}

output "amplify_branch" {
  value = aws_amplify_branch.main.branch_name
}

output "dashboard_url" {
  value = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${aws_cloudwatch_dashboard.poc.dashboard_name}"
}
