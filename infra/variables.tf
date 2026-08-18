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

variable "backend_zip_path" {
  description = "Đường dẫn zip code backend (tạo bằng scripts/build_backend.ps1)"
  type        = string
  default     = "artifacts/backend.zip"
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

variable "gcp_docai_processor_id" {
  description = "Document AI Form Parser processor ID (tạo thủ công trong GCP Console)"
  type        = string
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
