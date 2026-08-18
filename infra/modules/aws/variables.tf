variable "app_name" {
  type = string
}

variable "env" {
  type = string
}

variable "backend_zip_path" {
  type = string
}

variable "gcp_project_id" {
  type = string
}

variable "gcp_docai_location" {
  type = string
}

variable "gcp_docai_processor_id" {
  type = string
}

variable "gemini_model" {
  type = string
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
