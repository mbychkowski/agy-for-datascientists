# Dataproc Serverless batches run as the presenter

Pipeline batches run with the presenter's own credentials (the Dataproc Serverless runtime 3.0 default), not as the default compute service account. Every other piece of the Command Center already acts as the presenter (BigQuery, BQML, `AI.FORECAST`, BigQuery MCP), so one identity covers the whole demo. Terraform grants no service-account roles, there is no `serviceAccountUser` grant to explain, and the minimum IAM a reuser needs is shorter.

## Considered Options

- **Default compute service account**: rejected. Every submit needs an explicit `--service-account`, the account needs Dataproc and BigQuery roles, and the presenter needs `serviceAccountUser` on it. That is extra IAM that doesn't help the story.
- **Presenter credentials (runtime default)**: chosen. Revisit if a reuser's landing zone requires workloads to run under a service account.
