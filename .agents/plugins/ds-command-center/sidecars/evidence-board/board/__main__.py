"""Run the Evidence Board backend: `python3 -m board` from the sidecar folder.

Binds 127.0.0.1 on `ANTIGRAVITY_SIDECAR_WEB_PORT` (injected by Antigravity), or
on `--port` for the standalone browser tab. Reads BigQuery under the
presenter's user ADC, pinned to PROJECT_ID and REGION from `<workspace>/demo.env`;
`--fake-catalog <json>` swaps in an offline catalog for rehearsal and tests.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from board.catalog import BigQueryCatalog, FakeCatalog, PinningError, load_pinning
from board.manifest import ManifestError, load_manifest

HOST = "127.0.0.1"
PORT_ENV = "ANTIGRAVITY_SIDECAR_WEB_PORT"
BOARD_DIR = Path(__file__).resolve().parent.parent
# In the repo the sidecar lives at <repo>/.agents/plugins/ds-command-center/sidecars/evidence-board.
DEFAULT_WORKSPACE = BOARD_DIR.parents[3]


def _port(flag: int | None, env: dict[str, str]) -> int:
    if flag is not None:
        return flag
    value = env.get(PORT_ENV, "")
    if not value.isdigit():
        raise SystemExit(f"evidence-board: no port; set {PORT_ENV} or pass --port")
    return int(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="evidence-board", description=__doc__.splitlines()[0]
    )
    parser.add_argument(
        "--port", type=int, help=f"port to bind on {HOST} (default: ${PORT_ENV})"
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=DEFAULT_WORKSPACE,
        help="repo root holding demo.env",
    )
    parser.add_argument(
        "--manifest", type=Path, default=BOARD_DIR / "tiles.json", help="Tile manifest"
    )
    parser.add_argument(
        "--fake-catalog", type=Path, help="offline catalog JSON instead of BigQuery"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    port = _port(args.port, dict(os.environ))
    try:
        manifest = load_manifest(args.manifest)
        if args.fake_catalog:
            catalog = FakeCatalog.from_json(args.fake_catalog)
        else:
            project, region = load_pinning(args.workspace)
            catalog = BigQueryCatalog.from_user_adc(project, region)
    except (ManifestError, PinningError, RuntimeError) as exc:
        print(f"evidence-board: {exc}", file=sys.stderr)
        return 2

    import uvicorn

    from board.app import create_app
    from board.service import Board

    uvicorn.run(
        create_app(Board(manifest, catalog)), host=HOST, port=port, log_level="info"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
