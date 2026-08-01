from __future__ import annotations

import logging
import os

from sqlmodel import Session

from app.core.db import engine
from app.domain.governance_runs import (
    GovernanceRunExecutionError,
    RunnerInputs,
    execute_governance_run,
)

logger = logging.getLogger(__name__)


def main() -> int:
    try:
        inputs = RunnerInputs.from_environment(dict(os.environ))
        with Session(engine) as session:
            run = execute_governance_run(session=session, inputs=inputs)
    except GovernanceRunExecutionError as error:
        logger.error(
            "Governance Runner stopped: %s",
            error.code,
            extra={"governance_run_error_code": error.code},
        )
        return 1
    logger.info(
        "Governance Runner finished",
        extra={"governance_run_id": str(run.id), "governance_run_status": run.status},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
