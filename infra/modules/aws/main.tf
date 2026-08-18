resource "random_id" "suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "documents" {
  bucket        = "${var.app_name}-${var.env}-documents-${random_id.suffix.hex}"
  force_destroy = var.env != "prod"
}

# Frontend upload thẳng lên S3 bằng presigned POST, nên bucket PHẢI khai CORS —
# thiếu là trình duyệt chặn, dù curl vẫn chạy bình thường.
# Giữ khớp với CORS_RULES trong backend/devserver/bootstrap.py.
resource "aws_s3_bucket_cors_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["POST", "PUT", "GET", "HEAD"]
    allowed_origins = var.frontend_origins
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 3
    }
  }
}

resource "aws_dynamodb_table" "projects" {
  name         = "${var.app_name}-projects-${var.env}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "project_id"

  attribute {
    name = "project_id"
    type = "S"
  }
}

resource "aws_dynamodb_table" "documents" {
  name         = "${var.app_name}-documents-${var.env}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "document_id"

  attribute {
    name = "document_id"
    type = "S"
  }

  attribute {
    name = "project_id"
    type = "S"
  }

  attribute {
    name = "po_number"
    type = "S"
  }

  global_secondary_index {
    name            = "project_id-index"
    hash_key        = "project_id"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "po_number-index"
    hash_key        = "po_number"
    projection_type = "ALL"
  }
}

resource "aws_dynamodb_table" "processing_runs" {
  name         = "${var.app_name}-processing-runs-${var.env}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "run_id"

  attribute {
    name = "run_id"
    type = "S"
  }
}

resource "aws_dynamodb_table" "reconciliations" {
  name         = "${var.app_name}-reconciliations-${var.env}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "reconciliation_id"

  attribute {
    name = "reconciliation_id"
    type = "S"
  }
}

resource "aws_dynamodb_table" "audit_log" {
  name         = "${var.app_name}-audit-log-${var.env}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "entity_id"
  range_key    = "timestamp"

  attribute {
    name = "entity_id"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "S"
  }
}

locals {
  tables = [
    aws_dynamodb_table.projects.arn,
    aws_dynamodb_table.documents.arn,
    aws_dynamodb_table.processing_runs.arn,
    aws_dynamodb_table.reconciliations.arn,
    aws_dynamodb_table.audit_log.arn,
  ]

  table_indexes = ["${aws_dynamodb_table.documents.arn}/index/*"]
}

resource "aws_iam_role" "lambda_role" {
  name = "${var.app_name}-lambda-${var.env}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_policy" "lambda_policy" {
  name = "${var.app_name}-lambda-policy-${var.env}"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:GetObjectVersion",
        ]
        Resource = ["${aws_s3_bucket.documents.arn}/*"]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:Scan",
          "dynamodb:Query",
        ]
        Resource = concat(local.tables, local.table_indexes)
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [aws_secretsmanager_secret.google_sa_key.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["states:StartExecution", "states:DescribeExecution"]
        Resource = [aws_sfn_state_machine.process.arn, "${replace(aws_sfn_state_machine.process.arn, ":stateMachine:", ":execution:")}:*"]
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = ["*"]
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = aws_iam_policy.lambda_policy.arn
}

locals {
  lambda_env = {
    PROJECTS_TABLE            = aws_dynamodb_table.projects.name
    DOCUMENTS_TABLE           = aws_dynamodb_table.documents.name
    RUNS_TABLE                = aws_dynamodb_table.processing_runs.name
    RECONCILIATIONS_TABLE     = aws_dynamodb_table.reconciliations.name
    AUDIT_LOG_TABLE           = aws_dynamodb_table.audit_log.name
    DOCUMENTS_PROJECT_INDEX   = "project_id-index"
    DOCUMENTS_PO_NUMBER_INDEX = "po_number-index"
    DOCUMENTS_BUCKET          = aws_s3_bucket.documents.bucket
    DOCAI_PROJECT             = var.gcp_project_id
    DOCAI_LOCATION            = var.gcp_docai_location
    DOCAI_PROCESSOR_ID        = var.gcp_docai_processor_id
    GEMINI_MODEL              = var.gemini_model
    GEMINI_API_KEY            = var.gemini_api_key
    GOOGLE_SA_KEY_SECRET      = aws_secretsmanager_secret.google_sa_key.name
  }

  workers = {
    ocr = {
      handler = "workers.ocr.lambda_handler"
      timeout = 600
      memory  = 1024
    }
    extract = {
      handler = "workers.extract.lambda_handler"
      timeout = 300
      memory  = 512
    }
    validate = {
      handler = "workers.validate.lambda_handler"
      timeout = 60
      memory  = 256
    }
    reconcile = {
      handler = "workers.reconcile.lambda_handler"
      timeout = 120
      memory  = 512
    }
    mark-failed = {
      handler = "workers.mark_failed.lambda_handler"
      timeout = 30
      memory  = 256
    }
    mark-run-failed = {
      handler = "workers.mark_failed.mark_run_failed"
      timeout = 30
      memory  = 256
    }
  }
}

resource "aws_lambda_function" "worker" {
  for_each = local.workers

  function_name    = "${var.app_name}-${each.key}-${var.env}"
  role             = aws_iam_role.lambda_role.arn
  handler          = each.value.handler
  runtime          = "python3.11"
  timeout          = each.value.timeout
  memory_size      = each.value.memory
  filename         = var.backend_zip_path
  source_code_hash = filebase64sha256(var.backend_zip_path)

  environment {
    variables = local.lambda_env
  }
}

resource "aws_lambda_function" "api" {
  function_name    = "${var.app_name}-api-${var.env}"
  role             = aws_iam_role.lambda_role.arn
  handler          = "api.handler.lambda_handler"
  runtime          = "python3.11"
  timeout          = 30
  memory_size      = 512
  filename         = var.backend_zip_path
  source_code_hash = filebase64sha256(var.backend_zip_path)

  environment {
    variables = merge(local.lambda_env, {
      STATE_MACHINE_ARN = aws_sfn_state_machine.process.arn
    })
  }
}

resource "aws_iam_role" "sfn_role" {
  name = "${var.app_name}-sfn-${var.env}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "states.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "sfn_invoke_lambda" {
  name = "${var.app_name}-sfn-invoke-${var.env}"
  role = aws_iam_role.sfn_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = [for fn in aws_lambda_function.worker : fn.arn]
      }
    ]
  })
}

resource "aws_sfn_state_machine" "process" {
  name     = "${var.app_name}-process-${var.env}"
  role_arn = aws_iam_role.sfn_role.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/statemachine.asl.json", {
    ocr_lambda_arn             = aws_lambda_function.worker["ocr"].arn
    extract_lambda_arn         = aws_lambda_function.worker["extract"].arn
    validate_lambda_arn        = aws_lambda_function.worker["validate"].arn
    reconcile_lambda_arn       = aws_lambda_function.worker["reconcile"].arn
    mark_failed_lambda_arn     = aws_lambda_function.worker["mark-failed"].arn
    mark_run_failed_lambda_arn = aws_lambda_function.worker["mark-run-failed"].arn
  })
}

resource "aws_secretsmanager_secret" "google_sa_key" {
  name = "${var.app_name}-google-sa-key-${var.env}"
}

resource "aws_secretsmanager_secret_version" "google_sa_key" {
  secret_id     = aws_secretsmanager_secret.google_sa_key.id
  secret_string = var.gcp_sa_key_json
}

resource "aws_apigatewayv2_api" "api" {
  name          = "${var.app_name}-api-${var.env}"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST", "PATCH", "OPTIONS"]
    allow_headers = ["content-type"]
  }
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

locals {
  api_routes = [
    "POST /projects",
    "GET /projects",
    "GET /projects/{project_id}",
    "POST /projects/{project_id}/documents",
    "GET /projects/{project_id}/documents",
    "GET /projects/{project_id}/documents/{document_id}/ocr",
    "POST /projects/{project_id}/process",
    "POST /projects/{project_id}/reconcile",
    "PATCH /projects/{project_id}/documents/{document_id}",
    "GET /reconciliations/{reconciliation_id}",
    "POST /reconciliations/{reconciliation_id}/approve",
    "POST /reconciliations/{reconciliation_id}/reject",
  ]
}

resource "aws_apigatewayv2_route" "routes" {
  for_each  = toset(local.api_routes)
  api_id    = aws_apigatewayv2_api.api.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGWInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}
