# The Evidence Board is installed by copy and lands Tiles from working tables

The **Evidence Board** source lives in this repo at `.agents/plugins/ds-command-center/sidecars/evidence-board/`, where it is reviewed, tested and versioned with the **Command Center**. Antigravity discovers UI sidecars only under the global `~/.gemini/config/` directories, never in a workspace, so `./install-evidence-board` builds the frontend and copies the board to `~/.gemini/config/sidecars/evidence-board/` as a standalone sidecar, pinned by `install.env` to one workspace's `demo.env`. `./preflight` warns when the copy drifts from the repo. It is a standalone sidecar rather than a global copy of the **Command Center** plugin, so the stage clone stays the only source of the plugin's rules, skills and hooks.

A **Tile** lands when its source tables in `staging`, `features` or `ml` meet the readiness rule in `tiles.json`, read from BigQuery table metadata. Agent events, recorded by the **Command Center** hooks into `<workspace>/.evidence-board/events.jsonl`, only drive a **Tile**'s in-progress view. On stage the same table can come from the agent, a Window 2 fallback that runs reference code, or a **Checkpoint** swap; only table readiness is true in all three cases, so the board never shows a step as done before its table exists, and never misses one because no agent wrote it.

## Considered Options

- **Symlink the repo into `~/.gemini/config/sidecars/`**: rejected. A `git pull` or branch switch in the presenter repo would change the running board mid-session. A copy changes only when the presenter reruns the installer, and `./preflight` reports when it falls behind.
- **Install the whole plugin globally**: rejected. A global `ds-command-center` folder would share the workspace plugin's `config.json` enable toggle, which is keyed by folder name, and would load its rules and hooks twice.
- **Land Tiles from agent events**: rejected. Fallbacks and **Checkpoint** swaps write tables without agent events, and an agent can finish a tool call without producing the table.
