"""Ask prompt: the chat message a landed Tile's "Ask the Command Center" button sends.

Pure, no I/O. The prompt names the Tile (step and title), its source tables,
its "what this proves" line and the numbers on screen (the chart rows), so the
Command Center can explain the Tile without first rediscovering it. The board
serves it in `GET /api/tiles`; the frontend shows it verbatim in the confirm
dialog, and `POST /api/ask` only sends a prompt equal to the current one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

# Chart rows quoted in a prompt; the rest are counted, not listed.
MAX_ROWS = 12
# Longest single value quoted from a chart row.
VALUE_MAX = 80
# Longest prompt sent to the chat.
PROMPT_MAX = 4000


def prompt(
    step: str,
    title: str,
    tables: Sequence[str],
    proves: str,
    rows: Sequence[Mapping[str, Any]],
) -> str:
    """The Ask prompt for one landed Tile."""
    lines = [
        f'On the Evidence Board, the {step} Tile "{title}" has landed.',
        "Source table(s): " + ", ".join(f"`{t}`" for t in tables) + ".",
        f"What this proves: {proves}",
        "Numbers on screen:",
    ]
    lines += [f"- {_row(row)}" for row in rows[:MAX_ROWS]]
    if not rows:
        lines.append("- (no rows)")
    elif len(rows) > MAX_ROWS:
        lines.append(f"(+{len(rows) - MAX_ROWS} more rows not shown)")
    lines.append(
        "Explain what these numbers show and how they were produced from the "
        "source table(s), and flag anything that looks off."
    )
    return _clip("\n".join(lines), PROMPT_MAX)


def _row(row: Mapping[str, Any]) -> str:
    return ", ".join(f"{key}={_value(value)}" for key, value in row.items())


def _value(value: Any) -> str:
    if isinstance(value, list | tuple):
        text = "[" + ", ".join(_value(v) for v in value) + "]"
    elif value is None:
        text = "null"
    else:
        text = str(value)
    return _clip(text, VALUE_MAX)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
