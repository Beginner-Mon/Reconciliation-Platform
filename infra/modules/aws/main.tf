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
    allowed_origins = local.cors_origins
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id

  versioning_configuration {
    status = "Enabled"
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

  rule {
    id     = "expire-old-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
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

  point_in_time_recovery {
    enabled = true
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

  point_in_time_recovery {
    enabled = true
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

  point_in_time_recovery {
    enabled = true
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

  point_in_time_recovery {
    enabled = true
  }
}

locals {
  tables = [
    aws_dynamodb_table.projects.arn,
    aws_dynamodb_table.documents.arn,
    aws_dynamodb_table.processing_runs.arn,
    aws_dynamodb_table.reconciliations.arn,
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

# CHỈ 6 worker dùng role/policy này — api đã có 4 role riêng ở dưới. Nhờ vậy bỏ
# được hai thứ worker không hề dùng:
#   states:*      không worker nào gọi Step Functions (start_execution chỉ ở api)
#   dynamodb:Scan chỉ api/projects.py:45 dùng scan_table
# secretsmanager thì GIỮ: worker ocr/extract đọc key service account Google.
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
          "dynamodb:Query",
        ]
        Resource = concat(local.tables, local.table_indexes)
      },
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          aws_secretsmanager_secret.google_sa_key.arn,
          aws_secretsmanager_secret.gemini_api_key.arn,
        ]
      },
      # Engine OCR thay thế (var.ocr_engine = "textract" / "textract-analyze").
      # Textract KHÔNG nhận Resource cụ thể cho mấy action này — chỉ "*".
      # Nó đọc file bằng credential của CHÍNH role này, nên quyền s3:GetObject ở
      # trên là đủ; không cần SNS vì worker tự poll GetDocument*.
      {
        Effect = "Allow"
        Action = [
          "textract:StartDocumentTextDetection",
          "textract:GetDocumentTextDetection",
          "textract:StartDocumentAnalysis",
          "textract:GetDocumentAnalysis",
        ]
        Resource = ["*"]
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
    DOCUMENTS_PROJECT_INDEX   = "project_id-index"
    DOCUMENTS_PO_NUMBER_INDEX = "po_number-index"
    DOCUMENTS_BUCKET          = aws_s3_bucket.documents.bucket
    DOCAI_PROJECT             = var.gcp_project_id
    DOCAI_LOCATION            = var.gcp_docai_location
    # Mỗi engine Document AI đọc processor id của RIÊNG nó (xem
    # common/ocr_engines.py `processor_env`). `dococr` nằm trong APP_ENGINES nên
    # thiếu DOCAI_OCR_PROCESSOR_ID là bấm "Chạy lại với Document AI" trên giao
    # diện sẽ nổ ngay trên production. tests/test_routes.py chặn việc này.
    DOCAI_OCR_PROCESSOR_ID = var.gcp_docai_ocr_processor_id
    DOCAI_PROCESSOR_ID     = var.gcp_docai_processor_id
    GEMINI_MODEL           = var.gemini_model
    GEMINI_API_KEY_SECRET  = aws_secretsmanager_secret.gemini_api_key.name
    GOOGLE_SA_KEY_SECRET   = aws_secretsmanager_secret.google_sa_key.name
    # Engine OCR: tên tra trong backend/common/ocr_engines.py — hàm gọi, đơn
    # giá và nhãn audit đều lấy từ đó nên không thể lệch nhau.
    OCR_ENGINE = var.ocr_engine
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

  # Bốn Lambda api, chia theo MIỀN NGHIỆP VỤ (khớp api/handler.py). Handler và bộ
  # quyền để CÙNG MỘT CHỖ có chủ đích: tách ra là chỗ đã sai một lần trong repo
  # này (processor vs đơn giá), và ở đây hậu quả còn nặng hơn — cấp thừa quyền mà
  # không ai thấy.
  #
  #   `sfn = true` CHỈ ở process: `states:StartExecution` là quyền TIÊU TIỀN AI, và
  #     trong toàn backend chỉ api/process.py:143 gọi nó.
  #   `Scan` CHỈ ở projects: list_projects quét bảng projects; delete_project quét
  #     processing_runs và reconciliations theo project_id (hai bảng không có GSI).
  #   `s3_list` CHỈ ở projects: xoá project dọn mọi object dưới projects/{id}/.
  #   KHÔNG function nào cần secretsmanager — chỉ worker ocr/extract đọc key Google.
  #   `s3:GetObject` cần cho cả presigned GET (create_view_url) và head_object;
  #     `s3:PutObject` cần cho presigned POST upload. Ký URL không gọi API, nhưng
  #     URL chỉ dùng được nếu principal ký CÓ quyền tương ứng.
  api_functions = {
    projects = {
      handler  = "api.handler.projects_handler"
      timeout  = 30
      memory   = 512
      dynamodb = ["GetItem", "Query", "Scan", "PutItem", "UpdateItem", "DeleteItem"]
      s3       = ["GetObject", "DeleteObject"]
      s3_list  = true
      sfn      = false
      # Đối chiếu chạy ở MỘT Lambda duy nhất (recon-reconcile). Chỉ hai function
      # dưới đây có đường dẫn tới nó: `review` phục vụ POST /reconcile, `process`
      # phục vụ nhánh "không còn gì để xử lý".
      invoke_reconcile = false
    }
    documents = {
      handler  = "api.handler.documents_handler"
      timeout  = 30
      memory   = 512
      dynamodb = ["GetItem", "Query", "PutItem", "UpdateItem", "DeleteItem"]
      # PutObject: presigned POST ký bằng quyền của chính role này.
      # DeleteObject: xoá chứng từ (P1) — bucket có versioning nên tạo delete marker, khôi phục 30 ngày.
      s3               = ["GetObject", "PutObject", "DeleteObject"]
      s3_list          = false
      sfn              = false
      invoke_reconcile = true
    }
    review = {
      handler  = "api.handler.review_handler"
      timeout  = 30
      memory   = 512
      dynamodb = ["GetItem", "Query", "PutItem", "UpdateItem"]
      # KHÔNG còn PutObject: sau khi đối chiếu dời sang Lambda riêng, không
      # đường nào ở đây ghi S3 nữa — chỉ đọc file kết quả đối chiếu.
      s3               = ["GetObject"]
      s3_list          = false
      sfn              = false
      invoke_reconcile = true
    }
    process = {
      handler  = "api.handler.process_handler"
      timeout  = 30
      memory   = 512
      dynamodb = ["GetItem", "Query", "PutItem", "UpdateItem"]
      # KHÔNG còn PutObject: chỉ head_object để kiểm file đã upload chưa.
      s3               = ["GetObject"]
      s3_list          = false
      sfn              = true
      invoke_reconcile = true
    }
    anchor = {
      handler          = "api.handler.anchor_handler"
      timeout          = 30
      memory           = 512
      dynamodb         = ["GetItem", "Query", "UpdateItem"]
      s3               = ["GetObject"]
      s3_list          = false
      sfn              = false
      invoke_reconcile = true
    }
  }
}

resource "aws_lambda_function" "worker" {
  for_each = local.workers

  function_name = "${var.app_name}-${each.key}-${var.env}"
  role          = aws_iam_role.lambda_role.arn
  handler       = each.value.handler
  runtime       = "python3.11"
  timeout       = each.value.timeout
  memory_size   = each.value.memory

  # MỖI Lambda một gói riêng, chỉ chứa thư viện chính nó cần. Bảng gói ở
  # backend/packaging.py, tên file zip trùng tên function ở local.workers —
  # tests/test_packaging.py khoá hai bên lại với nhau.
  #
  # Trước đây cả 10 function dùng chung một zip 34 MB. Đo được: mark-failed
  # xuống 0,1 MB, bốn api xuống 2,5 MB. Cái tiết kiệm là COLD START, không phải
  # dung lượng — IAM vốn đã tách sẵn, gói không liên quan tới phân quyền.
  filename         = "${var.artifacts_dir}/${each.key}.zip"
  source_code_hash = filebase64sha256("${var.artifacts_dir}/${each.key}.zip")

  environment {
    variables = local.lambda_env
  }
}

resource "aws_iam_role" "api" {
  for_each = local.api_functions

  name = "${var.app_name}-api-${each.key}-${var.env}"

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

resource "aws_iam_policy" "api" {
  for_each = local.api_functions

  name = "${var.app_name}-api-${each.key}-policy-${var.env}"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [
        {
          Effect   = "Allow"
          Action   = [for action in each.value.s3 : "s3:${action}"]
          Resource = ["${aws_s3_bucket.documents.arn}/*"]
        },
        {
          Effect   = "Allow"
          Action   = [for action in each.value.dynamodb : "dynamodb:${action}"]
          Resource = concat(local.tables, local.table_indexes)
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
      ],
      each.value.invoke_reconcile ? [
        {
          Effect   = "Allow"
          Action   = ["lambda:InvokeFunction"]
          Resource = [aws_lambda_function.worker["reconcile"].arn]
        },
      ] : [],
      each.value.s3_list ? [
        {
          Effect    = "Allow"
          Action    = ["s3:ListBucket"]
          Resource  = [aws_s3_bucket.documents.arn]
          Condition = { StringLike = { "s3:prefix" = ["projects/*"] } }
        },
      ] : [],
      each.value.sfn ? [
        {
          Effect = "Allow"
          Action = ["states:StartExecution", "states:DescribeExecution"]
          Resource = [
            aws_sfn_state_machine.process.arn,
            "${replace(aws_sfn_state_machine.process.arn, ":stateMachine:", ":execution:")}:*",
          ]
        },
      ] : [],
    )
  })
}

resource "aws_iam_role_policy_attachment" "api" {
  for_each = local.api_functions

  role       = aws_iam_role.api[each.key].name
  policy_arn = aws_iam_policy.api[each.key].arn
}

locals {
  lambda_function_names = merge(
    { for k in keys(local.workers) : k => "${var.app_name}-${k}-${var.env}" },
    { for k in keys(local.api_functions) : "api-${k}" => "${var.app_name}-api-${k}-${var.env}" },
  )
}

resource "aws_cloudwatch_log_group" "lambda" {
  for_each          = local.lambda_function_names
  name              = "/aws/lambda/${each.value}"
  retention_in_days = var.log_retention_days
}

locals {
  audit_sources = join(" | ", [
    for ten in values(local.lambda_function_names) : "SOURCE '/aws/lambda/${ten}'"
  ])
}

resource "aws_cloudwatch_dashboard" "poc" {
  dashboard_name = "${var.app_name}-${var.env}"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "log"
        x      = 0
        y      = 0
        width  = 16
        height = 6
        properties = {
          region = var.aws_region
          title  = "Nhật ký audit — ai làm gì"
          view   = "table"
          query  = "${local.audit_sources} | fields @timestamp, actor, action, project_id, entity_id\n| filter audit = 1\n| sort @timestamp desc\n| limit 100"
        }
      },
      {
        type   = "log"
        x      = 16
        y      = 0
        width  = 8
        height = 6
        properties = {
          region = var.aws_region
          title  = "Đếm theo hành động"
          view   = "bar"
          query  = "${local.audit_sources} | filter audit = 1\n| stats count() by action"
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 8
        height = 6
        properties = {
          region = var.aws_region
          title  = "Chi phí AI mỗi ngày (USD)"
          view   = "timeSeries"
          stat   = "Sum"
          period = 86400
          metrics = [
            ["Recon/AI", "AiCostUsd", "Service", "recon"],
          ]
          annotations = {
            horizontal = [{ value = 1, label = "Ngưỡng $1/ngày" }]
          }
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 6
        width  = 8
        height = 6
        properties = {
          region = var.aws_region
          title  = "Số lần AI bị 429"
          view   = "timeSeries"
          stat   = "Sum"
          period = 86400
          metrics = [
            ["Recon/AI", "AiRateLimited", "Service", "recon"],
          ]
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 6
        width  = 8
        height = 6
        properties = {
          region = var.aws_region
          title  = "Latency AI p90"
          view   = "timeSeries"
          stat   = "p90"
          period = 86400
          metrics = [
            ["Recon/AI", "AiLatencyMs", "Service", "recon"],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 12
        height = 6
        properties = {
          region = var.aws_region
          title  = "Step Functions chạy xong / lỗi"
          view   = "timeSeries"
          stat   = "Sum"
          period = 86400
          metrics = [
            ["AWS/States", "ExecutionsSucceeded", "StateMachineArn", aws_sfn_state_machine.process.arn],
            ["AWS/States", "ExecutionsFailed", "StateMachineArn", aws_sfn_state_machine.process.arn],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 12
        width  = 12
        height = 6
        properties = {
          region = var.aws_region
          title  = "API Gateway 5xx + Latency"
          view   = "timeSeries"
          stat   = "Sum"
          period = 300
          metrics = [
            ["AWS/ApiGateway", "5xx", "ApiId", aws_apigatewayv2_api.api.id],
            ["AWS/ApiGateway", "Latency", "ApiId", aws_apigatewayv2_api.api.id, { stat = "Average" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 18
        width  = 16
        height = 6
        properties = {
          region = var.aws_region
          title  = "Lambda Errors theo function"
          view   = "timeSeries"
          stat   = "Sum"
          period = 300
          metrics = [
            for ten in values(local.lambda_function_names) :
            ["AWS/Lambda", "Errors", "FunctionName", ten]
          ]
        }
      },
      {
        type   = "log"
        x      = 16
        y      = 18
        width  = 8
        height = 6
        properties = {
          region = var.aws_region
          title  = "Log lỗi gần nhất"
          view   = "table"
          query  = "${local.audit_sources} | filter @message like /ERROR/\n| sort @timestamp desc\n| limit 100"
        }
      },
    ]
  })
}

resource "aws_lambda_function" "api" {
  for_each = local.api_functions

  function_name = "${var.app_name}-api-${each.key}-${var.env}"
  role          = aws_iam_role.api[each.key].arn
  handler       = each.value.handler
  runtime       = "python3.11"
  timeout       = each.value.timeout
  memory_size   = each.value.memory

  # Gói riêng, tên file có tiền tố "api-" để không đụng tên worker.
  filename         = "${var.artifacts_dir}/api-${each.key}.zip"
  source_code_hash = filebase64sha256("${var.artifacts_dir}/api-${each.key}.zip")

  environment {
    # STATE_MACHINE_ARN chỉ đặt cho function thật sự khởi động execution. Ba
    # function kia thiếu biến này vẫn import được: common/stepfunctions.py:7 đọc
    # bằng os.environ.get(..., "") và chỉ báo lỗi khi start_execution() bị gọi.
    variables = merge(
      local.lambda_env,
      each.value.sfn ? { STATE_MACHINE_ARN = aws_sfn_state_machine.process.arn } : {},
      each.value.invoke_reconcile ? {
        RECONCILE_LAMBDA_ARN = aws_lambda_function.worker["reconcile"].arn
      } : {},
    )
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

resource "aws_secretsmanager_secret" "gemini_api_key" {
  name = "${var.app_name}-gemini-api-key-${var.env}"
}

resource "aws_secretsmanager_secret_version" "gemini_api_key" {
  secret_id     = aws_secretsmanager_secret.gemini_api_key.id
  secret_string = var.gemini_api_key
}

resource "aws_cognito_user_pool" "main" {
  name = "${var.app_name}-users-${var.env}"

  admin_create_user_config {
    allow_admin_create_user_only = true
  }
}

resource "aws_cognito_user_pool_client" "main" {
  name         = "${var.app_name}-spa-${var.env}"
  user_pool_id = aws_cognito_user_pool.main.id

  generate_secret               = false
  explicit_auth_flows           = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors = "ENABLED"
  supported_identity_providers  = ["COGNITO"]
  write_attributes              = []
}

resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.api.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "${var.app_name}-cognito-${var.env}"

  jwt_configuration {
    issuer   = "https://${aws_cognito_user_pool.main.endpoint}"
    audience = [aws_cognito_user_pool_client.main.id]
  }
}

resource "aws_amplify_app" "main" {
  name = "${var.app_name}-${var.env}"

  custom_rule {
    source = "</^[^.]+$|\\.(?!(css|gif|ico|jpg|js|png|txt|svg|woff|woff2|ttf|map|json|webp)$)([^.]+$)/>"
    status = "200"
    target = "/index.html"
  }
}

resource "aws_amplify_branch" "main" {
  app_id      = aws_amplify_app.main.id
  branch_name = "main"

  enable_auto_build = false
}

locals {
  amplify_url  = "https://${aws_amplify_branch.main.branch_name}.${aws_amplify_app.main.id}.amplifyapp.com"
  cors_origins = concat(var.frontend_origins, [local.amplify_url])
}

resource "aws_apigatewayv2_api" "api" {
  name          = "${var.app_name}-api-${var.env}"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = local.cors_origins
    allow_methods = ["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"]
    allow_headers = ["content-type", "authorization"]
  }
}

resource "aws_apigatewayv2_integration" "api" {
  for_each = local.api_functions

  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api[each.key].invoke_arn
  payload_format_version = "2.0"
}

locals {
  # BẢNG ĐỊNH TUYẾN THẬT: route_key -> miền (khớp key của local.api_functions).
  # Đây là nơi API Gateway quyết định gọi Lambda nào, nên nó PHẢI trùng khít với
  # bốn danh sách trong backend/api/handler.py. Lệch một bên là 404 khó đoán:
  # khai ở đây mà quên bên Python -> handler.py trả 404; khai bên Python mà quên
  # ở đây -> API Gateway trả 404 trước khi Lambda kịp chạy.
  # backend/tests/test_routes.py ĐỌC CHÍNH KHỐI NÀY và chặn cả hai lỗi đó offline.
  api_routes = {
    "POST /projects"                                         = "projects"
    "GET /projects"                                          = "projects"
    "GET /projects/{project_id}"                             = "projects"
    "DELETE /projects/{project_id}"                          = "projects"
    "POST /projects/{project_id}/documents"                  = "documents"
    "GET /projects/{project_id}/documents"                   = "documents"
    "GET /projects/{project_id}/documents/{document_id}/ocr" = "documents"
    "DELETE /projects/{project_id}/documents/{document_id}"  = "documents"
    "POST /projects/{project_id}/reconcile"                  = "review"
    "PATCH /projects/{project_id}/documents/{document_id}"   = "review"
    "GET /reconciliations/{reconciliation_id}"               = "review"
    "POST /reconciliations/{reconciliation_id}/review"       = "review"
    "PUT /projects/{project_id}/anchor"                      = "anchor"
    "POST /projects/{project_id}/process"                    = "process"
    "POST /projects/{project_id}/process/stop"               = "process"
  }
}

resource "aws_apigatewayv2_route" "routes" {
  for_each           = local.api_routes
  api_id             = aws_apigatewayv2_api.api.id
  route_key          = each.key
  target             = "integrations/${aws_apigatewayv2_integration.api[each.value].id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "apigw" {
  for_each = local.api_functions

  statement_id  = "AllowAPIGWInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api[each.key].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}
