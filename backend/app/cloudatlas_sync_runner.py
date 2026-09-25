"""Dedicated agent-compose entrypoint; no model or browser dependency."""

import json
import os
import re
import sys
import uuid
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.db import engine
from app.domain import external_assets as service
from app.domain.external_asset_models import ExternalAssetVersion, ExternalSync
from app.domain.models import SourceInstance


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1:3] == ["--purge-expired", "--source-id"]:
        # Trusted deployment maintenance, not a project business-write API.
        # Explicit source scoping prevents a retention sweep of unrelated data.
        try:
            source_id = uuid.UUID(sys.argv[3])
            with Session(engine) as session:
                source = session.exec(
                    select(SourceInstance)
                    .where(
                        SourceInstance.id == source_id,
                        col(SourceInstance.capability_profile).in_(
                            ("assets-v1", "root-domains-v1")
                        ),
                    )
                    .with_for_update()
                ).one_or_none()
                if source is None:
                    return 1
                count = service.purge_expired(session, source, None)
            sys.stdout.write(json.dumps({"deleted_records": count}) + "\n")
            return 0
        except ValueError, SQLAlchemyError:
            return 1
    if len(sys.argv) != 1:
        return 1
    try:
        sync_id = uuid.UUID(os.environ.get("EXTERNAL_SYNC_ID", ""))
        run_id = os.environ.get("EXTERNAL_SYNC_RUN_ID", "")
        session_id = os.environ.get("SANDBOX_ID", "")
        if not re.fullmatch(r"[0-9a-f]{64}", run_id) or not re.fullmatch(
            r"[0-9a-f]{64}", session_id
        ):
            return 1
        build = (
            Path(
                os.environ.get("RUNNER_BUILD_VERSION_PATH", "/app/runner-build-version")
            )
            .read_text(encoding="utf-8")
            .strip()
        )
        if build != settings.governance_runner_build_version:
            return 1
        with Session(engine) as session:
            service.execute_sync(session, sync_id, run_id, session_id)
        return 0
    except ValueError, OSError:
        return 1
    except Exception:
        # Do not expose source responses, credentials or exception text. An interrupted
        # execution stays reserved until an explicit same-Session reconciliation.
        try:
            with Session(engine) as session:
                sync = session.exec(
                    select(ExternalSync)
                    .where(ExternalSync.id == sync_id)
                    .with_for_update()
                ).one_or_none()
                if (
                    sync is not None
                    and sync.agent_run_id == run_id
                    and sync.session_id == session_id
                    and sync.status in service.UNFINISHED
                ):
                    sync.status, sync.error_code = (
                        "UNKNOWN",
                        "external_execution_unknown",
                    )
                    session.add(sync)
                    for version in session.exec(
                        select(ExternalAssetVersion).where(
                            ExternalAssetVersion.sync_id == sync.id
                        )
                    ).all():
                        if version.status not in ("PUBLISHED", "FAILED"):
                            version.status, version.error_code = (
                                "UNKNOWN",
                                "external_execution_unknown",
                            )
                            session.add(version)
                    session.commit()
        except SQLAlchemyError:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
