terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

provider "google" {
  project     = var.gcp_project_id
  region      = var.gcp_region
  credentials = var.gcp_credentials_file != "" ? file(var.gcp_credentials_file) : null
}

module "gcp" {
  source = "./modules/gcp"

  env        = var.env
  project_id = var.gcp_project_id
}

module "aws" {
  source = "./modules/aws"

  app_name               = var.app_name
  env                    = var.env
  backend_zip_path       = var.backend_zip_path
  gcp_project_id         = var.gcp_project_id
  gcp_docai_location     = var.gcp_docai_location
  gcp_docai_processor_id = var.gcp_docai_processor_id
  gemini_model           = var.gemini_model
  gemini_api_key         = var.gemini_api_key
  gcp_sa_key_json        = base64decode(module.gcp.sa_private_key)
  frontend_origins       = var.frontend_origins
}
