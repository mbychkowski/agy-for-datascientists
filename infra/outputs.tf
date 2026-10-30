output "project_id" {
  description = "Target Google Cloud project ID."
  value       = var.project_id
}

output "region" {
  description = "Target Google Cloud region."
  value       = var.region
}

output "staging_bucket" {
  description = "Dataproc Serverless staging bucket name."
  value       = google_storage_bucket.staging.name
}

output "subnet_uri" {
  description = "Subnet URI used by Dataproc Serverless batches (either supplied var.subnet or Terraform-provisioned demo-dataproc-subnet)."
  value       = local.create_network ? google_compute_subnetwork.demo_subnet[0].id : var.subnet
}

output "dataset_ids" {
  description = "Provisioned BigQuery demo dataset IDs."
  value       = sort([for ds in google_bigquery_dataset.demo : ds.dataset_id])
}
