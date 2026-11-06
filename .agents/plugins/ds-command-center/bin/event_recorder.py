"""Evidence Board event recorder (ds-command-center).

Observe-only: turns one Antigravity hook payload into one redacted JSON line
appended to the workspace event log, `<repo>/.evidence-board/events.jsonl`,
which the Evidence Board tails to show Tiles in progress (spec #88, #92).

Run as `event_recorder.py pre|post` by `bin/event-recorder-pre` and
`bin/event-recorder-post`; `bin/guardrail-hook` imports `record()` to log its
own denies as `blocked` events, because a denied call may never reach
PostToolUse. Recording never raises and never decides anything: `main()`
always prints the allow / empty response and returns 0.

Event fields: `ts` (ISO-8601 UTC), `phase` (pre | post | blocked | reset),
`tool`, `summary` (at most SUMMARY_MAX characters, redacted), `ok` (post only),
`reason` (blocked only) and `conversationId` (when the payload carries one,
for the Ask button in #97). Summaries never hold full SQL bodies or env values.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# The repo the plugin lives in: <repo>/.agents/plugins/ds-command-center/bin/.
REPO_ROOT = Path(__file__).resolve().parents[4]
EVENT_LOG = Path(".evidence-board") / "events.jsonl"
# Overrides the workspace the log is written to (tests, rehearsal clones).
WORKSPACE_ENV = "EVIDENCE_BOARD_WORKSPACE"

SUMMARY_MAX = 200
QUOTED_MAX = 60
VALUE_MAX = 60
RESPONSES = {"pre": {"decision": "allow"}, "post": {}}

_QUOTED = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'")
_ENV_ASSIGNMENT = re.compile(r"\b([A-Z_][A-Z0-9_]*)=(\"[^\"]*\"?|'[^']*'?|[^\s;&|]+)")
_SECRET_FLAG = re.compile(
    r"(?i)(--?[\w-]*(?:token|password|passwd|secret|api[-_]?key|credential)[\w-]*[= ])\S+"
)
_BEARER = re.compile(r"(?i)\b(bearer\s+)\S+")
_ACCESS_TOKEN = re.compile(r"\bya29\.[\w.-]+")
_WHITESPACE = re.compile(r"\s+")
_COMMAND_KEYS = ("CommandLine", "command", "cmd")
# Envelope keys some hook payloads nest under (as unwrapped by bin/guardrail-hook).
_WRAPPER_KEYS = ("preToolHookArgs", "toolHookArgs", "hookArgs")


def unwrap(data: Any) -> Any:
    """The hook payload itself, unwrapped from a known envelope key if present."""
    if isinstance(data, dict):
        for key in _WRAPPER_KEYS:
            if isinstance(data.get(key), dict):
                return data[key]
    return data


def log_path(data: Any = None) -> Path:
    """The workspace event log: env override, else the payload's first
    `workspacePaths` entry, else the repo the plugin lives in."""
    workspace = os.environ.get(WORKSPACE_ENV)
    paths = data.get("workspacePaths") if isinstance(data, dict) else None
    if (
        not workspace
        and isinstance(paths, list)
        and paths
        and isinstance(paths[0], str)
    ):
        workspace = paths[0].removeprefix("file://")
    return Path(workspace or REPO_ROOT) / EVENT_LOG


def tool_call(data: Any) -> tuple[str, dict[str, Any]]:
    """(tool name, args) from a hook payload; ("", {}) when it has neither."""
    data = unwrap(data)
    if not isinstance(data, dict):
        return "", {}
    call = data.get("toolCall")
    if not isinstance(call, dict):
        call = data
    name = call.get("name") or call.get("toolName") or ""
    args = call.get("args", call.get("arguments", {}))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {"args": args}
    return str(name), args if isinstance(args, dict) else {}


def summarize(name: str, args: dict[str, Any]) -> str:
    """A short, redacted line saying what the call does."""
    if name.endswith("invoke_subagent"):
        text = f"{args.get('TypeName', '')}: {args.get('Role', '')}"
    elif name.endswith("call_mcp_tool"):
        inner = args.get("Arguments")
        text = f"{args.get('ServerName', '')}/{args.get('ToolName', '')} " + (
            _key_values(inner) if isinstance(inner, dict) else ""
        )
    else:
        command = next(
            (args[k] for k in _COMMAND_KEYS if isinstance(args.get(k), str)), None
        )
        text = _QUOTED.sub(_cut_quoted, command) if command else _key_values(args)
    return clip(redact(text))


def redact(text: str) -> str:
    text = _ENV_ASSIGNMENT.sub(r"\1=…", text)
    text = _SECRET_FLAG.sub(r"\1…", text)
    text = _BEARER.sub(r"\1…", text)
    return _ACCESS_TOKEN.sub("ya29.…", text)


def clip(text: str, limit: int = SUMMARY_MAX) -> str:
    text = _WHITESPACE.sub(" ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_event(data: Any, phase: str, reason: str | None = None) -> dict[str, Any]:
    data = unwrap(data)
    name, args = tool_call(data)
    event: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "phase": phase,
        "tool": clip(name, 80),
        "summary": summarize(name, args),
    }
    if phase == "post":
        error = data.get("error") if isinstance(data, dict) else None
        event["ok"] = not error
    if phase == "blocked":
        event["reason"] = clip(redact(reason or ""))
    conversation = data.get("conversationId") if isinstance(data, dict) else None
    if isinstance(conversation, str) and conversation:
        event["conversationId"] = clip(conversation, 80)
    return event


def record(data: Any, phase: str, reason: str | None = None) -> None:
    """Append one event for `data`; swallow every error (observe-only)."""
    try:
        line = json.dumps(build_event(data, phase, reason), ensure_ascii=False)
        path = log_path(unwrap(data))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log:
            log.write(line + "\n")
    except Exception:  # noqa: BLE001, S110 - a hook must never fail the tool call
        pass


def main(argv: list[str]) -> int:
    phase = argv[1] if len(argv) > 1 and argv[1] in RESPONSES else "pre"
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else None
        if isinstance(data, dict):
            record(data, phase)
    except Exception:  # noqa: BLE001, S110 - malformed payloads are ignored
        pass
    print(json.dumps(RESPONSES[phase]))
    return 0


def _cut_quoted(match: re.Match[str]) -> str:
    quoted = match.group(0)
    if len(quoted) <= QUOTED_MAX:
        return quoted
    return quoted[: QUOTED_MAX - 2] + "…" + quoted[0]


def _key_values(args: dict[str, Any]) -> str:
    parts = []
    for key, value in args.items():
        if isinstance(value, (str, int, float, bool)):
            parts.append(f"{key}={clip(str(value), VALUE_MAX)}")
    return " ".join(parts)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
