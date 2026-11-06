# Antigravity sidecars and hooks

Platform reference for the Evidence Board sidecar, which fills in Tiles beside the Command Center across both Workstreams (spec #88; tickets #91 packaging and side pane, #92 event recorder hook, #97 Ask button). It has two tiers with different trust: build on the documented contract, and treat the undocumented web-UI layer as something to feature-detect and rehearse.

**Demo target:** the live demo runs in the **Antigravity App (2.0)**. The Antigravity CLI is a nice-to-have, served by the standalone `./evidence-board` browser launcher, because CLI side-pane support is unconfirmed. No ticket blocks on the CLI.

## Documented sidecar contract

Source of truth: <https://antigravity.google/docs/sidecars> ("Available on: Antigravity App"). Re-read it when a fact below looks wrong; the page wins.

- **Discovery** happens only under `~/.gemini/config/sidecars/<id>/` or `~/.gemini/config/plugins/<plugin>/sidecars/<id>/`; a repo's `.agents/plugins/` is outside discovery. A plugin sidecar's ID is `<plugin>/<id>`; a standalone sidecar's ID is its folder name. The repo therefore **copies** the sidecar folder at install time (copy, not symlink) to `~/.gemini/config/sidecars/evidence-board/`, so the Evidence Board's ID is `evidence-board`. It deliberately avoids a global `~/.gemini/config/plugins/ds-command-center/` folder: that would share a name with the workspace plugin, and `config.json` keys the plugin enable toggle by folder name. A full global copy of the plugin would also load the rules and hooks twice, since rules dedupe by file path and hooks have no name to dedupe on.
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

- **Enabling** is `{"sidecars": {"evidence-board": {"enabled": true}}}` in `~/.gemini/config/config.json`. Sidecars are disabled until enabled. This is the presenter's step: install code prints the instruction, and agents never edit that file.
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
- **Chat pill**: the agent opens the pane with a markdown link `[Evidence Board](sidecar://evidence-board/)` (`sidecar://<sidecar-id>/<view-path>`); the label prefers the view `title`, then `display_name`. Emit it only when the sidecar is enabled and running.

## Hooks

Source of truth: <https://antigravity.google/docs/hooks>. Prior art: [`hooks.json`](../../.agents/plugins/ds-command-center/hooks.json) and [`bin/guardrail-hook`](../../.agents/plugins/ds-command-center/bin/guardrail-hook).

- Hooks work in the App, CLI and IDE. The docs list plugin-level `hooks.json` only under the CLI; the App section names workspace `.agents/hooks.json` and global `~/.gemini/config/hooks.json`. Confirm the recorder fires in the App during rehearsal.
- Events: `PreToolUse` and `PostToolUse` (matcher is a tool-name regex, `"*"` for all; handler `timeout` defaults to 30 s). `SessionStart`, `PreInvocation`, `PostInvocation` and `Stop` also exist.
- Payloads are camelCase JSON on stdin. Every event carries `conversationId` and `workspacePaths`, so a recorder can capture the conversation ID that `agentapi send-message` needs.
  - `PreToolUse` stdin: `toolCall{name,args}`, `stepIdx`. Stdout requires `decision`; an observe-only hook returns `{"decision": "allow"}`, which defers to the next hook and the default policy.
  - `PostToolUse` stdin: `toolCall{name,args}`, `stepIdx`, `error` (empty on success). Stdout is `{}`. The tool's output is not in the payload.
- A call denied at `PreToolUse` may never reach `PostToolUse`, so #92 makes the guardrail record its own `blocked` event for the Opening Tile (spec #88).

### Event recorder (#92)

- [`hooks.json`](../../.agents/plugins/ds-command-center/hooks.json) registers `bin/event-recorder-pre` (PreToolUse) and `bin/event-recorder-post` (PostToolUse) beside the guardrail. Both are symlinks to [`bin/event-recorder`](../../.agents/plugins/ds-command-center/bin/event-recorder), which takes the phase from the name it was run as, so no hook command needs arguments. It runs [`bin/event_recorder.py`](../../.agents/plugins/ds-command-center/bin/event_recorder.py), discard its output and errors, then always return allow / `{}` and exit 0. The guardrail is the only hook that can deny.
- Each tool call appends one JSON line to `<repo>/.evidence-board/events.jsonl`, which is gitignored. The workspace is `EVIDENCE_BOARD_WORKSPACE` if set (tests set it), else the payload's first `workspacePaths` entry, else the repo the plugin lives in. The line holds `ts`, `phase` (`pre`, `post` or `blocked`), `tool`, a redacted `summary` of at most 200 characters (no full SQL bodies, env values or tokens), `ok` (post only), `reason` (blocked only) and `conversationId`, which the Ask button (#97) needs.
- On every deny, `bin/guardrail-hook` records a `blocked` event, so the Opening Tile shows the refused call.
- The board tails the log every 1 s. The `matchers` in [`tiles.json`](../../.agents/plugins/ds-command-center/sidecars/evidence-board/tiles.json) turn events into a Tile's `in_progress` lanes and its blocked items. Events before the latest `reset` event, which `reset ws1|ws2` will write (spec #88 item 9, a separate ticket), are ignored. Tables still decide `landed`, so a Tile whose tables appear with no events (a Checkpoint swap) still goes `locked` → `landed`.
