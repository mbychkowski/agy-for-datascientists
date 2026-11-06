"""Send a chat message into an Antigravity conversation through `agentapi`.

Inside the sidecar, Antigravity puts `agentapi` on the backend's PATH, and
`agentapi send-message <conversation_id> <prompt>` posts into an existing
conversation (docs/agents/antigravity-sidecars.md). The command runs as an
argv list, never through a shell, with a timeout; any failure raises
`SendError`, which the API turns into a 503 so the frontend falls through to
the clipboard.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import Protocol

# Antigravity conversation IDs are UUIDs; anything else is refused before it
# reaches the command line.
_CONVERSATION_ID = re.compile(r"^[A-Za-z0-9-]{1,80}$")
TIMEOUT_SECONDS = 15.0


class SendError(RuntimeError):
    pass


class Sender(Protocol):
    def send(self, conversation_id: str, message: str) -> None: ...


def valid_conversation_id(value: object) -> bool:
    return isinstance(value, str) and bool(_CONVERSATION_ID.match(value))


class AgentApi:
    """`agentapi send-message`, resolved on PATH at send time."""

    def __init__(self, executable: str = "agentapi") -> None:
        self._executable = executable

    def send(self, conversation_id: str, message: str) -> None:
        if not valid_conversation_id(conversation_id):
            raise SendError("invalid conversation id")
        if not message.strip() or message.startswith("-"):
            raise SendError("message is empty or would parse as a flag")
        exe = shutil.which(self._executable)
        if exe is None:
            raise SendError(f"{self._executable} not found on PATH")
        try:
            result = subprocess.run(
                [exe, "send-message", conversation_id, message],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SendError(f"agentapi send-message failed: {exc}") from exc
        if result.returncode != 0:
            raise SendError(
                f"agentapi send-message exited {result.returncode}: "
                f"{result.stderr.strip()[:200]}"
            )
