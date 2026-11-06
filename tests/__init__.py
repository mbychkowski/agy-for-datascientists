"""Test package setup.

Guardrail hook tests trigger denies, which the hook also records as Evidence
Board `blocked` events. Point every hook run without its own workspace at a
throwaway one, so the suite never writes the repo's `.evidence-board/` log.
"""

import atexit
import os
import shutil
import tempfile

from tests.helpers import EVIDENCE_BOARD_WORKSPACE_ENV

if not os.environ.get(EVIDENCE_BOARD_WORKSPACE_ENV):
    _workspace = tempfile.mkdtemp(prefix="evidence-board-tests-")
    atexit.register(shutil.rmtree, _workspace, ignore_errors=True)
    os.environ[EVIDENCE_BOARD_WORKSPACE_ENV] = _workspace
