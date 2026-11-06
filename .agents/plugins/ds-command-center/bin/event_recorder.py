"""Evidence Board event recorder (ds-command-center).

Observe-only: turns one Antigravity hook payload into one redacted JSON line
appended to the workspace event log, `<repo>/.evidence-board/events.jsonl`,
which the Evidence Board tails to show Tiles in progress (spec #88, #92).

Run as `event_recorder.py pre|post` by `bin/event-recorder` (through its
`event-recorder-pre` / `-post` symlinks); `bin/guardrail-hook` imports `record()` to log its
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
from collections.abc import Iterable
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
# Longest ` [tables: ...]` suffix a summary carries.
TABLES_MAX = 100
# Longest ` [bqml: ...]` suffix a summary carries.
BQML_MAX = 60
RESPONSES = {"pre": {"decision": "allow"}, "post": {}}

_QUOTED = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'")
# A BigQuery table in one of the demo datasets, project-qualified or not.
_TABLE_REF = re.compile(r"(?i)\b(staging|features|ml|raw|ops)\.(\w+)\b")
# A BigQuery ML model type (`model_type='KMEANS'`, or `"model_type":"ARIMA_PLUS"`
# in JSON) or an upper-case ML./AI. function call; lower-case `ml.x` is a table.
_BQML_REF = re.compile(
    r"(?i:model_type)['\"]?\s*[=:]\s*['\"](\w+)['\"]|\b((?:AI|ML)\.[A-Z][A-Z_]*)\s*\("
)
_ENV_ASSIGNMENT = re.compile(r"\b([A-Z_][A-Z0-9_]*)=(\"[^\"]*\"?|'[^']*'?|[^\s;&|]+)")
_SECRET_FLAG = re.compile(
    r"(?i)(--?[\w-]*(?:token|password|passwd|secret|api[-_]?key|credential)[\w-]*[= ])\S+"
)
_BEARER = re.compile(r"(?i)\b(bearer\s+)\S+")
_ACCESS_TOKEN = re.compile(r"\bya29\.[\w.-]+")
_WHITESPACE = re.compile(r"\s+")
_COMMAND_KEYS = ("CommandLine", "command", "cmd")
# File-writing tools (write_file, edit_file, replace_file_content, ...): their
# content is source text, not a call on the tables it mentions.
_FILE_WRITE = re.compile(r"(?i)write|edit|replace")
_PATH_KEY = re.compile(r"(?i)path|file")
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
    """A short, redacted line saying what the call does.

    Commands, SQL and other tool calls end with the BigQuery ML model types
    and functions the call uses (`[bqml: KMEANS, ML.PREDICT]`), then the
    BigQuery tables it names (`[tables: staging.hospital_flu]`), so a Tile
    matcher still sees what the clipped command or SQL text no longer shows. Subagent
    dispatches carry only type and role, and file writes only their path:
    a table named in written source code is not one the call touches.
    """
    if name.endswith("invoke_subagent"):
        return clip(redact(f"{args.get('TypeName', '')}: {args.get('Role', '')}"))
    if _FILE_WRITE.search(name):
        paths = {k: v for k, v in args.items() if _PATH_KEY.search(k)}
        return clip(redact(_key_values(paths)))
    if name.endswith("call_mcp_tool"):
        inner = args.get("Arguments")
        text = f"{args.get('ServerName', '')}/{args.get('ToolName', '')} " + (
            _key_values(inner) if isinstance(inner, dict) else ""
        )
    else:
        command = next(
            (args[k] for k in _COMMAND_KEYS if isinstance(args.get(k), str)), None
        )
        text = _QUOTED.sub(_cut_quoted, command) if command else _key_values(args)
    suffix = _bqml_suffix(args) + _tables_suffix(args)
    return clip(redact(text), SUMMARY_MAX - len(suffix)) + suffix


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
            parts.append(f"{key}={_clip_value(str(value))}")
    return " ".join(parts)


def _clip_value(value: str) -> str:
    """Clip a value to VALUE_MAX; a path keeps its tail, where the file name is."""
    value = _WHITESPACE.sub(" ", value).strip()
    if len(value) > VALUE_MAX and "/" in value and " " not in value:
        return "…" + value[-(VALUE_MAX - 1) :]
    return clip(value, VALUE_MAX)


def _strings(value: Any, depth: int = 0) -> list[str]:
    """Every string in a (nested) args value, a few levels deep."""
    if isinstance(value, str):
        return [value]
    if depth >= 3:
        return []
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, list):
        return [s for item in value for s in _strings(item, depth + 1)]
    return []


def _bqml_suffix(args: dict[str, Any]) -> str:
    """` [bqml: KMEANS, ML.PREDICT]` for the BQML model types and functions in
    args, in first-mention order, or "" if none."""
    names: dict[str, None] = {}
    for text in _strings(args):
        for match in _BQML_REF.finditer(text):
            names.setdefault((match.group(1) or match.group(2)).upper())
    return _list_suffix("bqml", names, BQML_MAX)


def _list_suffix(tag: str, names: Iterable[str], limit: int) -> str:
    """` [tag: a, b]` holding as many names as fit in `limit` characters."""
    joined = ""
    for name in names:
        longer = f"{joined}, {name}" if joined else name
        if len(longer) + len(f" [{tag}: ]") > limit:
            break
        joined = longer
    return f" [{tag}: {joined}]" if joined else ""


def _tables_suffix(args: dict[str, Any]) -> str:
    """` [tables: a, b]` for the dataset.table names in args, or "" if none."""
    tables: dict[str, str] = {}
    for text in _strings(args):
        for match in _TABLE_REF.finditer(text):
            ref = f"{match.group(1)}.{match.group(2)}"
            tables.setdefault(ref.lower(), ref)
    return _list_suffix("tables", tables.values(), TABLES_MAX)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
