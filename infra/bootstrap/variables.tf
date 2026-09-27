variable "aws_region" {
  description = "AWS region đặt bucket state — giữ KHỚP với aws_region của stack chính"
  type        = string
  default     = "us-east-1"
}

variable "app_name" {
  description = "Tên ứng dụng (prefix tài nguyên)"
  type        = string
  default     = "recon"
}
