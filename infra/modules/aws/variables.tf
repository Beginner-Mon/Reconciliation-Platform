variable "app_name" {
  type = string
}

variable "env" {
  type = string
}

variable "artifacts_dir" {
  description = "Thư mục chứa zip của TỪNG Lambda (<tên function>.zip)"
  type        = string
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
      textract  Amazon Textract DetectDocumentText  $0,0015/trang  (mặc định)
      dococr    Document AI Enterprise Document OCR $0,0015/trang

    Đây chỉ là mặc định: giao diện chọn lại được cho từng lần chạy, và
    `/process` truyền engine qua payload xuống Map ItemSelector.

    CẢNH BÁO: textract KHÔNG hỗ trợ tiếng Việt (AWS chỉ liệt kê English, French,
    German, Italian, Portuguese, Spanish) — đo trên chứng từ thật thì mất gần
    hết dấu, tuy số vẫn đọc đúng. Vẫn để mặc định vì đang có free tier. Cần độ
    chính xác tiếng Việt thì chọn dococr. Xem evaluation/FINDINGS.md.
  EOT
  type        = string
  default     = "textract"

  validation {
    condition     = contains(["textract", "dococr"], var.ocr_engine)
    error_message = "ocr_engine phải là một trong: textract, dococr."
  }
}

variable "gemini_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "gcp_sa_key_json" {
  type      = string
  sensitive = true
}

variable "frontend_origins" {
  description = "Origin được phép upload thẳng lên S3 (CORS). Thu hẹp lại khi có domain thật."
  type        = list(string)
  default     = ["*"]
}
