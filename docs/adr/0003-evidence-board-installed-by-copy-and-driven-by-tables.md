# The Evidence Board is installed by copy and lands Tiles from working tables

The **Evidence Board** source lives in this repo, versioned with the **Command Center**. Antigravity discovers UI sidecars only under the global `~/.gemini/config/` directories, so `./install-evidence-board` copies the board to `~/.gemini/config/sidecars/evidence-board/` as a standalone sidecar pinned to one workspace's `demo.env`, and `./preflight` warns when the copy drifts from the repo.

A **Tile** lands when its source tables in `staging`, `features` or `ml` meet the readiness rule in `tiles.json`; agent events only drive its in-progress view. On stage a table can come from the agent, a Window 2 fallback or a **Checkpoint** swap, and only table readiness is true in all three cases.

## Considered Options

- **Symlink the repo into `~/.gemini/config/sidecars/`**: rejected. A `git pull` or branch switch in the presenter repo would change the running board mid-session.
- **Install the whole plugin globally**: rejected. A global `ds-command-center` folder would share the workspace plugin's enable toggle, keyed by folder name, and load its rules and hooks twice.
- **Land Tiles from agent events**: rejected. Fallbacks and **Checkpoint** swaps write tables without agent events.
- **Standalone sidecar copy, landing from table readiness**: chosen.
