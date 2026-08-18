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

output "audit_log_table" {
  value = aws_dynamodb_table.audit_log.name
}

output "api_url" {
  value = aws_apigatewayv2_stage.default.invoke_url
}

output "state_machine_arn" {
  value = aws_sfn_state_machine.process.arn
}

output "api_function_name" {
  value = aws_lambda_function.api.function_name
}

output "worker_function_names" {
  value = { for name, fn in aws_lambda_function.worker : name => fn.function_name }
}
