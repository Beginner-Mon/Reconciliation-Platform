variable "app_name" {
  type = string
}

variable "env" {
  type = string
}

variable "aws_region" {
  description = "AWS region để hiển thị dashboard CloudWatch"
  type        = string
  default     = "us-east-1"
}

variable "artifacts_dir" {
  description = "Thư mục chứa zip của TỪNG Lambda (<tên function>.zip)"
  type        = string
}

variable "log_retention_days" {
  description = <<-EOT
    Số ngày giữ log của cả 10 Lambda — cũng chính là hạn của vết audit, vì audit
    là dòng JSON trong log (xem docs/observability.md).

    CloudWatch Logs CHỈ nhận các giá trị dưới đây; 10, 15, 45... là lỗi
    InvalidParameterException lúc apply chứ không phải làm tròn.
    3653 = 10 năm, mức TỐI ĐA.

    Giữ 10 năm cho hạn kế toán thì đủ về THỜI GIAN nhưng chưa đủ về BẤT BIẾN:
    ai có logs:DeleteLogGroup vẫn xoá sạch được. Cần bằng chứng không sửa được
    thì phải đẩy sang S3 + Object Lock (docs/observability.md §8, §13).
  EOT
  type        = number
  default     = 3653

  validation {
    condition = contains(
      [1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653],
      var.log_retention_days
    )
    error_message = "log_retention_days phải là giá trị CloudWatch Logs chấp nhận: 1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653."
  }
}

variable "gcp_project_id" {
  type = string
}

variable "gcp_docai_location" {
  type = string
}

variable "gcp_docai_processor_id" {
  description = "Form Parser — chỉ evaluation/ dùng, app không chạy. Để trống được."
  type        = string
  default     = ""
}

variable "gcp_docai_ocr_processor_id" {
  description = "Document OCR — engine `dococr` mà giao diện cho chọn. Bắt buộc."
  type        = string
}

variable "gemini_model" {
  type = string
}

variable "ocr_engine" {
  description = <<-EOT
    Engine OCR MẶC ĐỊNH của worker. Phải khớp APP_ENGINES trong
    backend/common/ocr_engines.py:
      textract  Amazon Textract DetectDocumentText  $0,0015/trang
      dococr    Document AI Enterprise Document OCR $0,0015/trang  (mặc định)

    Đây chỉ là mặc định: giao diện chọn lại được cho từng lần chạy, và
    `/process` truyền engine qua payload xuống Map ItemSelector.

    CẢNH BÁO: textract KHÔNG hỗ trợ tiếng Việt (AWS chỉ liệt kê English, French,
    German, Italian, Portuguese, Spanish) — đo trên chứng từ thật thì mất gần
    hết dấu, tuy số vẫn đọc đúng. Vì vậy mặc định là dococr; textract vẫn chọn
    được. Xem evaluation/FINDINGS.md.
  EOT
  type        = string
  default     = "dococr"

  validation {
    condition     = contains(["textract", "dococr"], var.ocr_engine)
    error_message = "ocr_engine phải là một trong: textract, dococr."
  }
}

variable "gemini_api_key" {
  type      = string
  sensitive = true
  default   = ""

  validation {
    condition     = length(var.gemini_api_key) > 0
    error_message = "gemini_api_key không được rỗng: Secrets Manager và bước extract đều cần key."
  }
}

variable "gcp_sa_key_json" {
  type      = string
  sensitive = true
}

variable "frontend_origins" {
  description = "Origin được phép upload thẳng lên S3 (CORS). Thu hẹp lại khi có domain thật."
  type        = list(string)
  default     = []
}
