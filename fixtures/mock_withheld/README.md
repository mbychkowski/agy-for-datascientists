# Mini Answer Key and Mini Reveal Test Fixtures

This directory contains the deterministic mini **Answer Key** (`answer_key.json`) and mini **Reveal** (`reveal/hospital_flu_feeds_reveal/reveal.csv`) accompanying the in-repo mock dataset (`fixtures/mock_dataset/`).

## Why ADR 0001 Does Not Apply Here

In accordance with [ADR 0001](../../docs/adr/0001-answer-key-outside-agent-reach.md), the live presentation's refined **Answer Key** and **Reveal** data are stored exclusively in a presenter-managed private Cloud Storage bucket that neither this repository nor the demo project ever names.

The files in `fixtures/mock_withheld/` are **test fixtures** for local development, automated CI verification, and rehearsal of the pipeline, reset, and **Workstream** reference steps before switching to the refined stage dataset. Because this is test fixture data rather than live stage data, [ADR 0001](../../docs/adr/0001-answer-key-outside-agent-reach.md) does not apply to this directory.

Even when running verification or **Reveal** load against the mock dataset, tooling still accepts `fixtures/mock_withheld` as an explicit runtime argument rather than hardcoding the path.
