"""Helper to extract the first valid JSON document from noisy BigQuery CLI output."""

from __future__ import annotations

import json
import sys
from typing import Any


def extract_first_json(raw: str) -> Any:
    """Scan *raw* for the first valid JSON array or object and return it decoded.

    Skips leading ``bq`` status lines (even those containing bracketed tags like
    ``[status]``) until ``json.JSONDecoder().raw_decode`` succeeds on a ``[`` or
    ``{`` character. Raises ``ValueError`` when no valid JSON document is found.
    """
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(raw):
        if ch in "[{":
            try:
                obj, _ = decoder.raw_decode(raw[idx:])
            except json.JSONDecodeError:
                pass
            else:
                return obj
    raise ValueError("No valid JSON document found in bq output")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    raw = args[0] if args else sys.stdin.read()
    try:
        doc = extract_first_json(raw)
    except ValueError as exc:
        sys.stderr.write(f"[FAIL] {exc}\n")
        return 1
    sys.stdout.write(json.dumps(doc) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
