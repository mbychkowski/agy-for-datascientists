# Antigravity sidecars and hooks

Platform reference for the Evidence Board sidecar, which fills in Tiles beside the Command Center across both Workstreams (spec #88; tickets #91 packaging and side pane, #92 event recorder hook, #97 Ask button). It has two tiers with different trust: build on the documented contract, and treat the undocumented web-UI layer as something to feature-detect and rehearse.

**Demo target:** the live demo runs in the **Antigravity App (2.0)**. The Antigravity CLI is a nice-to-have, served by the standalone `./evidence-board` browser launcher, because CLI side-pane support is unconfirmed. No ticket blocks on the CLI.

## Documented sidecar contract

Source of truth: <https://antigravity.google/docs/sidecars> ("Available on: Antigravity App"). Re-read it when a fact below looks wrong; the page wins.

- **Discovery** happens only under `~/.gemini/config/sidecars/<id>/` or `~/.gemini/config/plugins/<plugin>/sidecars/<id>/`; a repo's `.agents/plugins/` is outside discovery. A plugin sidecar's ID is `<plugin>/<id>`, so the Evidence Board is `ds-command-center/evidence-board`. The repo therefore **copies** the sidecar folder into the global plugin directory at install time; the decision is copy, not symlink.
- **Working directory**: the sidecar's folder is the cwd of its command, so relative paths in `sidecar.json` resolve against the installed copy, not the repo.
- **`sidecar.json`** fields:

  | Field | Notes |
  | --- | --- |
  | `command` | Executable to run. Exactly one of `command` or `builtin`. |
  | `builtin` | Only `schedule` (args: a 5-field cron expression, then the command and its args). |
  | `args` | Array of strings. |
  | `restart_policy` | `always` (default), `on-failure` or `never`. |
  | `env` | Map of extra environment variables. |
  | `description`, `display_name` | Shown in the UI. |

- **Enabling** is `{"sidecars": {"ds-command-center/evidence-board": {"enabled": true}}}` in `~/.gemini/config/config.json`. Sidecars are disabled until enabled. This is the presenter's step: install code prints the instruction, and agents never edit that file.
- **Runtime data** lives at `~/.gemini/antigravity/sidecar_data/<id>/`:
  - `data/`: persistent storage, also exposed as `ANTIGRAVITY_EXECUTABLE_DATA_DIR`.
  - `logs/`: timestamped stdout and stderr. Check here first when the sidecar won't start or the pane stays blank.
  - `events/`: JSON files recorded for `agentapi` calls (not hook events).
- **`agentapi`** is on the sidecar's PATH:
  - `agentapi send-message <conversation_id> <prompt>` posts into an existing conversation. This is the documented path for the Ask button.
  - `agentapi new-conversation <prompt>` needs `projectId` set on the sidecar's entry in `config.json` (beside `enabled`).

## Undocumented web-UI layer (agy v1.5.1)

These facts come from strings in the agy v1.5.1 binary, sit behind the `enable-ui-sidecars` experiment flag, and may change in any release. Feature-detect at runtime, keep the standalone launcher working, and rehearse on the stage machine. Cite new binary or docs evidence when extending this list.

- **Descriptor**: `"has_web_ui": true` plus `ui_config.views[]`, each view an object with `entrypoint`, `path` and `title`. The Evidence Board uses one view: `entrypoint: "SIDECAR_UI_ENTRYPOINT_AUX_PANE"`, `path: "/"`, `title: "Evidence Board"`. There is no port field.
- **Port**: Antigravity injects `ANTIGRAVITY_SIDECAR_WEB_PORT`; the sidecar serves its own HTTP on `127.0.0.1` at that port and Antigravity frames the view. Bind loopback only.
- **No push channel** exists from the agent to the sidecar, so the UI polls its backend.
- **`window.sidecar` bridge** (preload): `agent.sendMessage(message, conversationId?)`, `ui.toggleAuxPane`, `getWorkspaceUris`, and `fetch` (adds the sidecar token as `X-Sidecar-Token`). The view's URL query carries `token` and `conversationId`; the expected token is in `ANTIGRAVITY_SIDECAR_UI_TOKEN`.
  - Gotcha: in the reference Node backend found in the binary, `agent.sendMessage` POSTs to the sidecar's **own** `/_sidecar/send-message` route, which shells out to `agentapi send-message`, and that backend serves `/preload.js` itself. A non-reference backend (FastAPI) must provide equivalent routes, and whether the host injects the preload for it is unconfirmed. Hence the Ask button checks for `window.sidecar` and falls back to the clipboard.
- **Chat pill**: the agent opens the pane with a markdown link `[Evidence Board](sidecar://ds-command-center/evidence-board/)` (`sidecar://<sidecar-id>/<view-path>`); the label prefers the view `title`, then `display_name`. Emit it only when the sidecar is enabled and running.

## Hooks

Source of truth: <https://antigravity.google/docs/hooks>. Prior art: [`hooks.json`](../../.agents/plugins/ds-command-center/hooks.json) and [`bin/guardrail-hook`](../../.agents/plugins/ds-command-center/bin/guardrail-hook).

- Hooks work in the App, CLI and IDE. The docs list plugin-level `hooks.json` only under the CLI; the App section names workspace `.agents/hooks.json` and global `~/.gemini/config/hooks.json`. Confirm the recorder fires in the App during rehearsal.
- Events: `PreToolUse` and `PostToolUse` (matcher is a tool-name regex, `"*"` for all; handler `timeout` defaults to 30 s). `SessionStart`, `PreInvocation`, `PostInvocation` and `Stop` also exist.
- Payloads are camelCase JSON on stdin. Every event carries `conversationId` and `workspacePaths`, so a recorder can capture the conversation ID that `agentapi send-message` needs.
  - `PreToolUse` stdin: `toolCall{name,args}`, `stepIdx`. Stdout requires `decision`; an observe-only hook returns `{"decision": "allow"}`, which defers to the next hook and the default policy.
  - `PostToolUse` stdin: `toolCall{name,args}`, `stepIdx`, `error` (empty on success). Stdout is `{}`. The tool's output is not in the payload.
- A call denied at `PreToolUse` may never reach `PostToolUse`, so #92 makes the guardrail record its own `blocked` event for the Opening Tile (spec #88).
