resource "google_project_service" "documentai" {
  project            = var.project_id
  service            = "documentai.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "generativelanguage" {
  project            = var.project_id
  service            = "generativelanguage.googleapis.com"
  disable_on_destroy = false
}

resource "google_service_account" "lambda" {
  account_id   = "recon-lambda-${var.env}"
  display_name = "Recon Lambda (${var.env})"
}

resource "google_project_iam_member" "documentai_user" {
  project = var.project_id
  role    = "roles/documentai.apiUser"
  member  = "serviceAccount:${google_service_account.lambda.email}"
}

resource "google_project_iam_member" "gemini_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.lambda.email}"
}

resource "google_service_account_key" "lambda" {
  service_account_id = google_service_account.lambda.name
}
