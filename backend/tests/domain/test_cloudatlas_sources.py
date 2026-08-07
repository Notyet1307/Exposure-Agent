import uuid

import pytest
from pytest import MonkeyPatch

from app.domain.cloudatlas_sources import (
    CloudAtlasBoundaryError,
    OctobusCloudAtlasClient,
)
from app.domain.models import SourceInstance


def _source() -> SourceInstance:
    return SourceInstance(
        project_id=uuid.uuid4(),
        instance_id="cloudatlas-fixture",
        capset_id="cloudatlas-readonly",
    )


@pytest.mark.parametrize(
    ("error_code", "expected_calls"),
    [
        ("cloudatlas_connectivity_failed", 3),
        ("cloudatlas_upstream_failed", 3),
        ("cloudatlas_authentication_failed", 1),
        ("cloudatlas_authorization_failed", 1),
        ("cloudatlas_response_contract_failed", 1),
    ],
)
def test_list_ip_assets_page_retries_only_transient_failures(
    monkeypatch: MonkeyPatch, error_code: str, expected_calls: int
) -> None:
    client = OctobusCloudAtlasClient()
    calls = 0

    def request(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        raise CloudAtlasBoundaryError(error_code)

    monkeypatch.setattr(client, "_request_json", request)

    with pytest.raises(CloudAtlasBoundaryError, match=error_code):
        client.list_ip_assets_page(
            _source(), capset_token="fixture-token", page=1, size=200
        )
    assert calls == expected_calls
