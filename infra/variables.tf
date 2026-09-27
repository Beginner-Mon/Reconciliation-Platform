variable "aws_region" {
  description = "AWS region triển khai"
  type        = string
  # us-east-1: processor Document AI đặt ở `us` nên Lambda gọi sang Google gần
  # hơn nhiều so với Singapore — OCR/Gemini chiếm gần hết thời gian xử lý. Đổi
  # lại là người dùng ở VN chịu thêm độ trễ mỗi request.
  default = "us-east-1"
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

variable "log_retention_days" {
  description = <<-EOT
    Số ngày giữ log của 10 Lambda — cũng là hạn của vết audit (audit là dòng JSON
    trong log). Mặc định 3653 = 10 năm, mức tối đa CloudWatch Logs cho phép, đặt
    theo hạn lưu tài liệu kế toán.

    Chỉ nhận đúng danh sách giá trị của CloudWatch Logs (1, 3, 5, 7, 14, 30, 60,
    90, ..., 3653) — số khác là lỗi lúc apply. Hạ xuống 30 nếu chỉ cần điều tra
    sự cố và không coi audit là hồ sơ kế toán.
  EOT
  type        = number
  default     = 3653
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
  default     = []
}
