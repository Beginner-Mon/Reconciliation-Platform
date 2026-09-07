variable "aws_region" {
  description = "AWS region triển khai"
  type        = string
  default     = "ap-southeast-1"
}

variable "app_name" {
  description = "Tên ứng dụng (prefix tài nguyên)"
  type        = string
  default     = "recon"
}

variable "env" {
  description = "Môi trường: dev / prod"
  type        = string
  default     = "dev"
}

variable "artifacts_dir" {
  description = <<-EOT
    Thư mục chứa zip của TỪNG Lambda, dựng bằng scripts/build_backend.ps1.
    Mỗi function một gói riêng chỉ chứa thư viện nó cần — bảng gói ở
    backend/packaging.py.
  EOT
  type        = string
  default     = "artifacts"
}

variable "gcp_project_id" {
  description = "Google Cloud project ID"
  type        = string
}

variable "gcp_region" {
  description = "Google Cloud region"
  type        = string
  default     = "us-central1"
}

variable "gcp_docai_location" {
  description = "Document AI processor location: us | eu"
  type        = string
  default     = "us"
}

variable "gcp_docai_ocr_processor_id" {
  description = <<-EOT
    Document AI "Document OCR" processor ID — engine `dococr` mà giao diện cho
    chọn. Tạo thủ công tại console.cloud.google.com/ai/document-ai/processor-library
    (chọn Document OCR, KHÔNG phải Form Parser).
  EOT
  type        = string
}

variable "gcp_docai_processor_id" {
  description = <<-EOT
    Document AI Form Parser processor ID. KHÔNG bắt buộc: `formparser` không nằm
    trong APP_ENGINES nên app không chạy nó, chỉ `evaluation/` mới dùng. Để
    trống nếu không đo Form Parser.
  EOT
  type        = string
  default     = ""
}

variable "gcp_credentials_file" {
  description = "Đường dẫn file credentials Google (bỏ trống nếu đã chạy gcloud auth application-default login)"
  type        = string
  default     = ""
}

variable "gemini_model" {
  description = "Model Gemini dùng để extraction"
  type        = string
  default     = "gemini-2.5-flash"
}

variable "ocr_engine" {
  description = <<-EOT
    Engine OCR mặc định: textract | dococr. Giao diện chọn lại được cho từng
    lần chạy. textract KHÔNG hỗ trợ tiếng Việt (mất dấu, số vẫn đúng) — để mặc
    định vì đang có free tier; cần dấu thì chọn dococr.
    Xem backend/common/ocr_engines.py và evaluation/FINDINGS.md.
  EOT
  type        = string
  default     = "textract"
}

variable "gemini_api_key" {
  description = "Gemini API key (lấy miễn phí tại https://aistudio.google.com/apikey)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "frontend_origins" {
  description = "Origin được phép upload thẳng lên S3 (CORS)"
  type        = list(string)
  default     = ["*"]
}
