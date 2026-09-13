"""Seed an admitted synthetic published fixture, without mocking any AI execution."""
import json
import os
from pathlib import Path
import uuid
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlmodel import Session
from app.core.config import settings
from app.core.db import engine
from app.domain.models import Finding
from app.main import app
from tests.api.routes.test_ai_governance_draft_requests import _operator_draft_request_context

with TestClient(app) as client, Session(engine) as session, MonkeyPatch.context() as patch:
    response=client.post('/api/v1/login/access-token',data={'username':settings.FIRST_SUPERUSER,'password':settings.FIRST_SUPERUSER_PASSWORD})
    assert response.status_code==200
    headers={'Authorization':'Bearer '+response.json()['access_token']}
    project,report,_,finding,_=_operator_draft_request_context(client=client,superuser_token_headers=headers,db=session,
        tmp_path=Path(os.environ['SEED_ARTIFACT_ROOT']),monkeypatch=patch,qualify_model=False)
    row=session.get(Finding,uuid.UUID(finding));assert row is not None
    Path(os.environ['SEED_RESULT']).write_text(json.dumps({'project_id':str(project['id']),'run_id':str(report.governance_run_id),'resource_id':str(row.resource_id),'report_id':str(report.id),'finding_id':finding}))
