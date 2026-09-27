# Module này CỐ Ý chỉ tạo service account + key, không bật API và không gán
# quyền. Lý do là quyền của tài khoản CHẠY Terraform:
#
#   google_project_service      cần serviceusage.services.enable
#                               -> vai trò Service Usage Admin (bật/tắt MỌI API)
#   google_project_iam_member   cần resourcemanager.projects.setIamPolicy
#                               -> vai trò Project IAM Admin, mà ai có nó thì TỰ
#                                  gán được Owner cho chính mình
#
# Đổi lấy hai thao tác tay làm MỘT LẦN (xem infra/README.md §3), tài khoản chạy
# Terraform chỉ cần Service Account Admin + Service Account Key Admin:
#   1. Bật API `documentai.googleapis.com` cho project.
#   2. Gán `roles/documentai.apiUser` cho service account tạo ở dưới.
#
# KHÔNG cần `roles/aiplatform.user`: Gemini gọi bằng API key (Secrets Manager
# `recon-gemini-api-key-<env>`), không dùng service account này.

resource "google_service_account" "lambda" {
  account_id   = "recon-lambda-${var.env}"
  display_name = "Recon Lambda (${var.env})"
}

# Key này đi thẳng vào Secrets Manager của AWS (xem infra/main.tf) — worker OCR
# đọc nó khi chạy engine `dococr`.
resource "google_service_account_key" "lambda" {
  service_account_id = google_service_account.lambda.name
}
