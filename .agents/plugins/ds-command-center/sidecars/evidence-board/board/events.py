"""Workspace event log: what the agent is doing, as recorded by the hooks.

The ds-command-center event recorder hook appends one JSON line per tool call
to `<workspace>/.evidence-board/events.jsonl` (`bin/event_recorder.py`). The
board tails that file, reading only the bytes appended since the last read,
and keeps the events since the most recent `reset` event. Malformed lines are
skipped; a missing log means no events.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args

EVENT_LOG = Path(".evidence-board") / "events.jsonl"
# pre / post: a tool call starting / finishing; blocked: a guardrail deny;
# reset: a rehearsal reset, which hides every earlier event.
Phase = Literal["pre", "post", "blocked", "reset"]
PHASES: frozenset[str] = frozenset(get_args(Phase))


def event_log_path(workspace: str | Path) -> Path:
    return Path(workspace) / EVENT_LOG


@dataclass(frozen=True)
class Event:
    ts: str
    phase: Phase
    tool: str
    summary: str
    ok: bool | None = None
    reason: str | None = None
    # The Antigravity conversation the call ran in, for the Ask button (#97).
    conversation_id: str | None = None


def parse_event(line: str) -> Event | None:
    try:
        raw: Any = json.loads(line)
    except ValueError:
        return None
    if not isinstance(raw, dict) or raw.get("phase") not in PHASES:
        return None
    ok, reason = raw.get("ok"), raw.get("reason")
    conversation = raw.get("conversationId")
    return Event(
        ts=str(raw.get("ts", "")),
        phase=raw["phase"],
        tool=str(raw.get("tool", "")),
        summary=str(raw.get("summary", "")),
        ok=ok if isinstance(ok, bool) else None,
        reason=reason if isinstance(reason, str) else None,
        conversation_id=conversation if isinstance(conversation, str) else None,
    )


def since_last_reset(events: list[Event]) -> list[Event]:
    for i in range(len(events) - 1, -1, -1):
        if events[i].phase == "reset":
            return events[i + 1 :]
    return events


class EventLog:
    """Incremental reader of one workspace event log."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._identity: tuple[int, int] | None = None
        self._offset = 0
        self._partial = b""
        self._events: list[Event] = []

    def read(self) -> list[Event]:
        """Events since the last `reset`, including any appended since the last call."""
        try:
            stat = os.stat(self._path)
        except FileNotFoundError:
            self._restart(None)
            return []
        identity = (stat.st_dev, stat.st_ino)
        if identity != self._identity or stat.st_size < self._offset:
            self._restart(identity)  # replaced or truncated: read from the top
        if stat.st_size > self._offset:
            with self._path.open("rb") as log:
                log.seek(self._offset)
                chunk = log.read(stat.st_size - self._offset)
            self._offset += len(chunk)
            *lines, self._partial = (self._partial + chunk).split(b"\n")
            parsed = (parse_event(line.decode("utf-8", "replace")) for line in lines)
            self._events = since_last_reset(
                self._events + [event for event in parsed if event]
            )
        return list(self._events)

    def _restart(self, identity: tuple[int, int] | None) -> None:
        self._identity, self._offset, self._partial, self._events = (
            identity,
            0,
            b"",
            [],
        )
