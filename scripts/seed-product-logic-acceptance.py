#!/usr/bin/env python3
"""Seed only the task's isolated PostgreSQL/browser fixture; no external source calls."""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.core.time import get_datetime_utc
from app.domain.external_asset_models import (
    ExternalAssetRecord,
    ExternalAssetVersion,
    ExternalSync,
)
from app.main import app
from tests.api.routes.test_core_comparisons import _setup_core, _workbook
from tests.api.routes.test_netflow_datasets import _upload
from tests.utils.netflow_processing import (
    ControlPlane,
    context_request,
    execute,
    reserve,
)


def main() -> None:
    if (
        settings.ENVIRONMENT != "local"
        or not settings.POSTGRES_DB.startswith("product_browser_")
        or settings.POSTGRES_SERVER not in {"127.0.0.1", "localhost"}
        or not settings.NETFLOW_ALLOW_TEST_FIXTURES
    ):
        raise SystemExit(
            "Refusing seed outside an explicit isolated product_browser_* database"
        )
    path = Path(os.environ["PRODUCT_LOGIC_FIXTURE"])
    stage = sys.argv[1] if len(sys.argv) > 1 else "core"
    with (
        TestClient(app) as client,
        Session(engine) as db,
        MonkeyPatch.context() as patch,
    ):
        login = client.post(
            settings.API_V1_STR + "/login/access-token",
            data={
                "username": settings.FIRST_SUPERUSER,
                "password": settings.FIRST_SUPERUSER_PASSWORD,
            },
        )
        login.raise_for_status()
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        if stage == "core":
            core = _setup_core(client, db, headers, settings.ARTIFACT_ROOT, patch)
            root = core["root"]
            ips = (
                "192.0.2.10",
                "192.0.2.20",
                *(f"198.51.100.{i}" for i in range(1, 121)),
                "192.0.2.20",
            )
            upload = client.post(
                root + "/customer-uploads",
                headers=headers,
                files={"file": ("synthetic-current-register.xlsx", _workbook(ips))},
            )
            upload.raise_for_status()
            before = client.get(root + "/customer-ledger", headers=headers).json()
            body = {
                "candidate_upload_id": upload.json()["id"],
                "expected_upload_id": before["current_upload_id"],
                "expected_revision_id": before["current_revision_id"],
                "expected_profile_id": before["current_profile_id"],
            }
            response = client.post(
                root + "/customer-ledger/replacements",
                headers=headers | {"Idempotency-Key": "browser-customer-apply"},
                json=body,
            )
            response.raise_for_status()
            now = get_datetime_utc()
            original = core["version"]
            actor = client.get(
                settings.API_V1_STR + "/users/me", headers=headers
            ).json()["id"]
            sync = ExternalSync(
                source_id=core["source"].id,
                project_id=core["project"].id,
                actor_id=uuid.UUID(actor),
                idempotency_key=uuid.uuid4().hex,
                request_sha256="e" * 64,
                request={},
                fingerprint="b" * 64,
                token_sha256="c" * 64,
                status="SUCCEEDED",
                agent_run_id=uuid.uuid4().hex,
                agent_project_id="synthetic-browser",
                retain_until=now + timedelta(days=2),
            )
            db.add(sync)
            db.flush()
            atlas = (
                "192.0.2.20",
                "192.0.2.30",
                *(f"198.51.100.{i}" for i in range(1, 121)),
            )
            version = ExternalAssetVersion(
                sync_id=sync.id,
                source_id=original.source_id,
                domain="ip",
                space_id=original.space_id,
                instance_id=original.instance_id,
                capset_id=original.capset_id,
                status="RUNNING",
                record_count=len(atlas),
                expected_total=len(atlas),
                complete=True,
                filter={},
                fingerprint="f" * 64,
                fetched_at=now,
                published_at=now,
                retain_until=now + timedelta(days=2),
            )
            db.add(version)
            db.flush()
            for index, ip in enumerate(atlas, 1):
                db.add(
                    ExternalAssetRecord(
                        version_id=version.id,
                        source_id=str(index),
                        ip=ip,
                        canonical_ip=ip,
                        fields={"status": "valid"},
                    )
                )
            db.flush()
            version.status = "PUBLISHED"
            db.add(version)
            db.commit()
            data = {
                "project_id": str(core["project"].id),
                "source_id": str(core["source"].id),
                "customer_upload_id": upload.json()["id"],
                "cloud_version_id": str(version.id),
                "namespace": "synthetic-core",
                "expected": {
                    "total_addresses": 123,
                    "both": 121,
                    "customer_only": 1,
                    "cloud_only": 1,
                },
            }
            path.write_text(json.dumps(data, indent=2) + "\n")
        elif stage == "netflow":
            data = json.loads(path.read_text())
            root = settings.API_V1_STR + "/projects/" + data["project_id"]
            control = ControlPlane(patch)
            raw = "IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n192.0.2.20,203.0.113.1,6,50000,443\n192.0.2.40,203.0.113.1,17,50001,53\n"
            response = _upload(
                client,
                headers,
                data["project_id"],
                raw.encode(),
                "synthetic-netflow.csv",
            )
            response.raise_for_status()
            dataset = response.json()["id"]
            url = root + "/netflow-datasets/" + dataset
            response = client.post(
                url + "/processing-contexts",
                headers=headers | {"Idempotency-Key": "browser-flow-context"},
                json=context_request(
                    network_namespace=data["namespace"],
                    collection_scope="Synthetic edge",
                ),
            )
            response.raise_for_status()
            setup = {
                "dataset_url": url,
                "context_revision_id": response.json()["context_revision_id"],
                "headers": headers,
                "control": control,
            }
            queued = reserve(client, setup, key="browser-flow-analysis")
            analysis = execute(db, setup, queued["analysis_id"])
            if analysis.status not in {"SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"}:
                raise RuntimeError("Synthetic processor did not publish")
            data.update(
                dataset_id=dataset,
                analysis_id=str(analysis.id),
                context_revision_id=setup["context_revision_id"],
            )
            path.write_text(json.dumps(data, indent=2) + "\n")
        else:
            raise SystemExit("Expected core or netflow")
    print(
        json.dumps(
            {"fixture": str(path), "stage": stage, "project_id": data["project_id"]}
        )
    )


if __name__ == "__main__":
    main()
