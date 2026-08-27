"""Draft-ID-only runner entry that reloads bounded input from PostgreSQL."""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app.core.db import engine
from app.domain.ai_governance_drafts import (
    AiGovernanceDraftStateError,
    DraftRunnerHandoff,
    DraftRunnerInputs,
    load_draft_runner_inputs,
)

logger = logging.getLogger(__name__)


def _stop(code: str) -> int:
    logger.error(
        "AI governance draft runner stopped: %s",
        code,
        extra={"ai_draft_runner_error_code": code},
    )
    return 1


def _inputs_json(inputs: DraftRunnerInputs) -> str:
    return json.dumps(asdict(inputs), default=str, sort_keys=True)


def main() -> int:
    if len(sys.argv) != 1:
        return _stop("runner_handoff_invalid")
    try:
        handoff = DraftRunnerHandoff.from_environment(
            {
                "AI_DRAFT_ID": os.environ.get("AI_DRAFT_ID", ""),
                "SANDBOX_ID": os.environ.get("SANDBOX_ID", ""),
            }
        )
    except AiGovernanceDraftStateError as error:
        return _stop(error.code)
    try:
        with Session(engine) as session:
            inputs = load_draft_runner_inputs(
                session=session,
                draft_id=handoff.draft_id,
                session_id=handoff.session_id,
            )
    except AiGovernanceDraftStateError as error:
        return _stop(error.code)
    except SQLAlchemyError:
        return _stop("storage_unavailable")
    sys.stdout.write(_inputs_json(inputs) + "\n")
    logger.info(
        "AI governance draft runner handoff validated",
        extra={"ai_draft_id": str(inputs.draft_id)},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
