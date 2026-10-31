# Antigravity for Data Scientists

A reusable live demo for data science teams: agents investigate whether a flu **Spike** across 90 hospitals is a real **Outbreak**, a **Sampling Artifact**, or a **Pipeline Defect**, then build **Cohort**-level forecasts on the cleaned data.

## Quick Start for Reusers & Presenters

1. **Provision & Configure**: Follow the [Reuser Setup & Operations Guide](docs/reuser-guide.md) to configure `demo.env`, verify minimum presenter IAM roles ([ADR 0002](docs/adr/0002-dataproc-runs-as-presenter.md)), bootstrap and apply Terraform (`./bin/bootstrap-tf-state && terraform -chdir=infra apply`), install the licensed Data Agent Kit skills into `.gemini/skills/`, configure Java 21 for local Spark 4 tests, and run `./preflight`.
2. **Prepare for Stage**: Isolate personal workstation rules and skills with `./stage-clean-env --stash`, verify the **Workstream** 1 **Start Point** (`./verify-start-point ws1`), and follow the [Presenter Runbook](docs/presenter-runbook.md).

## Documentation

- [GLOSSARY.md](GLOSSARY.md): Project terminology and avoided synonyms.
- [Presenter Runbook](docs/presenter-runbook.md): Per-segment timings, prompts to type, narration cues, early-start job triggers ([`docs/recorded_runtimes.json`](docs/recorded_runtimes.json)), **Checkpoint** swap points, and the Antigravity 101 guardrail moment.
- [Reuser Setup & Operations Guide](docs/reuser-guide.md): `demo.env` configuration, minimum presenter IAM ([ADR 0002](docs/adr/0002-dataproc-runs-as-presenter.md)), Terraform bootstrap/apply, workspace Data Agent Kit skill installation, Java 21 setup, and stale ADC quota project troubleshooting.
- [Data Science Primer](docs/data-science-primer.md): Plain-language guide and Q&A playbook for presenters.
- [Demo Outline](docs/demo-outline.md): Company-neutral 90-minute demo structure, segment walkthroughs, and audience tailoring guide.
- [Architecture Decision Records](docs/adr/): Design decisions for **Answer Key** isolation ([ADR 0001](docs/adr/0001-answer-key-outside-agent-reach.md)) and Dataproc execution identity ([ADR 0002](docs/adr/0002-dataproc-runs-as-presenter.md)).
