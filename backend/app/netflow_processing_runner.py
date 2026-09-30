"""Dedicated direct-command worker; no model or CloudAtlas credentials/capability."""

import os
import re
import sys
import uuid
from pathlib import Path

from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.domain.netflow_models import NetFlowAnalysis
from app.domain.netflow_processing import SUCCESS, execute_analysis


def main() -> int:
    if len(sys.argv) != 1:
        return 1
    try:
        analysis_id = uuid.UUID(os.environ.get("NETFLOW_ANALYSIS_ID", ""))
        run_id = os.environ.get("NETFLOW_ANALYSIS_RUN_ID", "")
        session_id = os.environ.get("SANDBOX_ID", "")
        if not re.fullmatch(r"[0-9a-f]{64}", run_id) or not re.fullmatch(
            r"[0-9a-f]{64}", session_id
        ):
            return 1
        if (
            Path("/app/runner-build-version").read_text().strip()
            != settings.governance_runner_build_version
        ):
            return 1
        with Session(engine) as session:
            execute_analysis(session, analysis_id, run_id, session_id)
            row = session.get(NetFlowAnalysis, analysis_id)
            return 0 if row is not None and row.status in SUCCESS else 1
    except Exception:
        # An unobserved interruption stays reserved. Only explicit reconciliation
        # of the original Session may publish verified files or classify failure.
        # Never log source rows, filenames, exceptions or component submissions.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
