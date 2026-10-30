# Terraform Foundation (`infra/`)

Makes an existing Google Cloud project (with billing and baseline landing zone already in place) demo-ready for the **Command Center** with a single `terraform apply`.

## Design Guardrails

- **No Project / Org Mutation**: Never creates projects, billing accounts, folders, or organization policies.
- **Explicit Project & Region Pinning**: `project_id`, `region`, `staging_bucket`, and `state_bucket` have no defaults and are supplied from `demo.env` (`TF_VAR_*`). Every resource sets `project = var.project_id` explicitly.
- **Minimal API Surface**: Enables only BigQuery (`bigquery.googleapis.com`), BigQuery Storage (`bigquerystorage.googleapis.com`), Dataproc (`dataproc.googleapis.com` and `dataprocrm.googleapis.com` for Serverless runtime 3.0), Cloud Storage (`storage.googleapis.com`), and Compute (`compute.googleapis.com`). No Vertex AI API or Feature Store is enabled because TimesFM is built into BigQuery ML.
- **Conditional Networking**: Uses an existing subnet when `SUBNET` (`var.subnet`) is set in `demo.env`; otherwise creates `demo-dataproc-vpc`, regional `demo-dataproc-subnet` with Private Google Access (`private_ip_google_access = true`), and `demo-dataproc-allow-internal` firewall rule.
- **Demo Datasets & Staging Bucket**: Creates `gs://${STAGING_BUCKET}` and the six demo BigQuery datasets (`raw`, `ops`, `staging`, `features`, `ml`, `checkpoint`) in `${REGION}`, all carrying the `demo:true` label.
- **Presenter Identity ([ADR 0002](../docs/adr/0002-dataproc-runs-as-presenter.md))**: No service-account IAM bindings are created; Dataproc Serverless runtime 3.0 batches execute as the presenter.

## Step 1: Bootstrap the Dedicated State Bucket

Terraform state lives in a dedicated GCS bucket (`STATE_BUCKET` in `demo.env`) so it never collides with other workloads in a shared project.

Run the idempotent bootstrap script from the repository root:

```bash
./bin/bootstrap-tf-state
```

Or run the equivalent commands manually after sourcing `demo.env`:

```bash
source demo.env
gcloud storage buckets create "gs://${STATE_BUCKET}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --uniform-bucket-level-access \
  --pap=enforced
gcloud storage buckets update "gs://${STATE_BUCKET}" \
  --project="${PROJECT_ID}" \
  --versioning \
  --update-labels="demo=true"
terraform -chdir=infra init -reconfigure -backend-config="bucket=${STATE_BUCKET}"
```

## Step 2: Validate, Plan, and Apply

```bash
source demo.env
terraform -chdir=infra validate
terraform -chdir=infra plan
terraform -chdir=infra apply
```

## Step 3: Verify via Preflight (Dataproc Serverless Runtime 3.0 Hello-World Batch)

```bash
./preflight
```

`./preflight` submits a Dataproc Serverless runtime `3.0` batch as the presenter using the configured subnet and Shielded VM properties, verifies that it writes a record to BigQuery (`ops`), and cleans up the temporary table and batch automatically.
