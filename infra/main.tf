locals {
  # Required APIs only: BigQuery, BigQuery Storage, Dataproc (including the
  # resource-manager API required by Serverless runtime 3.0), Cloud Storage,
  # and Compute. No Vertex AI API or Feature Store (TimesFM is built into BQML).
  required_apis = toset([
    "bigquery.googleapis.com",
    "bigquerystorage.googleapis.com",
    "dataproc.googleapis.com",
    "dataprocrm.googleapis.com",
    "storage.googleapis.com",
    "compute.googleapis.com",
  ])

  # Six demo BigQuery datasets carrying the demo label
  demo_datasets = toset([
    "raw",
    "ops",
    "staging",
    "features",
    "ml",
    "checkpoint",
  ])

  demo_labels = {
    demo = "true"
  }

  create_network = trimspace(var.subnet) == ""
  subnet_cidr    = "10.10.0.0/24"
}

# ------------------------------------------------------------------------------
# 1. API Enablement
# ------------------------------------------------------------------------------
resource "google_project_service" "required_apis" {
  for_each = local.required_apis

  project                    = var.project_id
  service                    = each.key
  disable_on_destroy         = false
  disable_dependent_services = false
}

# ------------------------------------------------------------------------------
# 2. Networking (Conditional on var.subnet == "")
# ------------------------------------------------------------------------------
resource "google_compute_network" "demo_vpc" {
  count = local.create_network ? 1 : 0

  project                 = var.project_id
  name                    = "demo-dataproc-vpc"
  auto_create_subnetworks = false
  description             = "Dedicated VPC for Antigravity Command Center Dataproc Serverless batches"

  depends_on = [google_project_service.required_apis]
}

resource "google_compute_subnetwork" "demo_subnet" {
  count = local.create_network ? 1 : 0

  project                  = var.project_id
  name                     = "demo-dataproc-subnet"
  region                   = var.region
  network                  = google_compute_network.demo_vpc[0].id
  ip_cidr_range            = local.subnet_cidr
  private_ip_google_access = true
  description              = "Regional subnet with Private Google Access for Dataproc Serverless runtime 3.0"
}

resource "google_compute_firewall" "demo_internal" {
  count = local.create_network ? 1 : 0

  project     = var.project_id
  name        = "demo-dataproc-allow-internal"
  network     = google_compute_network.demo_vpc[0].name
  direction   = "INGRESS"
  priority    = 1000
  description = "Allow internal executor-to-executor traffic within the Dataproc Serverless subnet"

  source_ranges = [local.subnet_cidr]

  allow {
    protocol = "tcp"
    ports    = ["0-65535"]
  }

  allow {
    protocol = "udp"
    ports    = ["0-65535"]
  }

  allow {
    protocol = "icmp"
  }
}

# ------------------------------------------------------------------------------
# 3. Dataproc Serverless Staging Bucket
# ------------------------------------------------------------------------------
resource "google_storage_bucket" "staging" {
  project                     = var.project_id
  name                        = var.staging_bucket
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true
  labels                      = local.demo_labels

  depends_on = [google_project_service.required_apis]
}

# ------------------------------------------------------------------------------
# 4. Six Demo BigQuery Datasets (raw, ops, staging, features, ml, checkpoint)
#    Note: No service-account IAM grants are created. Per ADR 0002, Dataproc
#    Serverless runtime 3.0 batches run as the presenter identity.
# ------------------------------------------------------------------------------
resource "google_bigquery_dataset" "demo" {
  for_each = local.demo_datasets

  project                    = var.project_id
  dataset_id                 = each.key
  location                   = var.region
  delete_contents_on_destroy = true
  labels                     = local.demo_labels
  description                = "Antigravity for Data Scientists demo dataset (${each.key})"

  depends_on = [google_project_service.required_apis]
}
