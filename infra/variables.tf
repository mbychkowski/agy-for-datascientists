variable "project_id" {
  description = "Existing Google Cloud project ID for the demo (sourced from demo.env via TF_VAR_project_id; no default)."
  type        = string

  validation {
    condition     = length(trimspace(var.project_id)) > 0 && !startswith(var.project_id, "your-")
    error_message = "project_id must be set to a real Google Cloud project ID (not empty or a placeholder)."
  }
}

variable "region" {
  description = "Google Cloud region for BigQuery datasets, Dataproc Serverless, and the staging bucket (sourced from demo.env via TF_VAR_region; no default)."
  type        = string

  validation {
    condition     = length(trimspace(var.region)) > 0
    error_message = "region must be explicitly provided."
  }
}

variable "staging_bucket" {
  description = "Name of the Cloud Storage bucket created for Dataproc Serverless staging (sourced from demo.env via TF_VAR_staging_bucket; no default)."
  type        = string

  validation {
    condition     = length(trimspace(var.staging_bucket)) > 0 && !startswith(var.staging_bucket, "your-")
    error_message = "staging_bucket must be set to a real bucket name (not empty or a placeholder)."
  }
}

variable "state_bucket" {
  description = "Name of the dedicated Cloud Storage bucket used for Terraform remote state (sourced from demo.env via TF_VAR_state_bucket; no default)."
  type        = string

  validation {
    condition     = length(trimspace(var.state_bucket)) > 0 && !startswith(var.state_bucket, "your-")
    error_message = "state_bucket must be set to a real bucket name (not empty or a placeholder)."
  }
}

variable "subnet" {
  description = "Optional existing subnet self_link or URI. Leave empty (\"\") to let Terraform provision a dedicated VPC, regional subnet with Private Google Access, and internal firewall rule."
  type        = string
  default     = ""
}
