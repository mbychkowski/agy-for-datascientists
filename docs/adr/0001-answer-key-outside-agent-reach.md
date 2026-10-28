# Answer Key and Reveal data are kept outside the agents' reach

The Data Generator writes the Answer Key and the six Reveal weeks only to a GCS bucket the presenter creates manually, and neither this repo nor the demo project ever references that bucket. Antigravity can read every file in the workspace (gitignored or not) and query everything in the demo project, so an instruction telling it not to look would not make the agents' Attribution trustworthy; the only guarantee is that the data is unreachable.

## Considered Options

- **Gitignored file in the repo**: rejected. Gitignore only affects git; agents can still read the file.
- **Dataset in the demo project**: rejected. Agents query the demo project freely through BigQuery MCP and `bq`.
- **Separate, manually created bucket the repo never names**: chosen.
