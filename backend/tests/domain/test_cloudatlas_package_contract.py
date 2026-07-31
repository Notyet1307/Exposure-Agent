import json
from pathlib import Path

from app.domain.cloudatlas_sources import (
    DESCRIPTOR_SHA256,
    METHOD,
    PACKAGE_SHA256,
    SERVICE_ID,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = REPOSITORY_ROOT / "octobus" / "cloudatlas-read"


def test_product_package_and_backend_pin_the_single_read_method() -> None:
    manifest = json.loads(
        (REPOSITORY_ROOT / "octobus" / "cloudatlas-read.hashes.json").read_text()
    )
    service = json.loads((PACKAGE_ROOT / "service.json").read_text())
    proto = (PACKAGE_ROOT / "proto" / "cloudatlas_read.proto").read_text()
    implementation = (PACKAGE_ROOT / "bin" / "cloudatlas-read.js").read_text()
    fixture_compose = (REPOSITORY_ROOT / "compose.cloudatlas-fixture.yml").read_text()
    deployment_compose = (REPOSITORY_ROOT / "compose.yml").read_text()
    octobus_image = (REPOSITORY_ROOT / "octobus" / "Dockerfile").read_text()

    assert manifest == {
        "service_id": SERVICE_ID,
        "package_sha256": PACKAGE_SHA256,
        "descriptor_sha256": DESCRIPTOR_SHA256,
        "selected_method": METHOD,
    }
    assert service["name"] == SERVICE_ID
    assert service["runtime"] == {"mode": "on-demand"}
    assert service["proto"] == {
        "roots": ["proto"],
        "files": ["proto/cloudatlas_read.proto"],
    }
    assert proto.count("rpc ") == 1
    assert "rpc ListIPAssets(" in proto
    assert f'"{METHOD}": listIPAssets' in implementation
    assert '"chaitin-cli"' in implementation
    assert '"list"' in implementation
    assert "Action" not in proto
    assert "--no-all-methods" in (
        REPOSITORY_ROOT / "tests" / "cloudatlas_fixture" / "init.sh"
    ).read_text()
    package_image_path = "/opt/exposure-agent/service-packages/cloudatlas-read"
    assert f"COPY octobus/cloudatlas-read {package_image_path}" in octobus_image
    assert "./octobus/cloudatlas-read:/service-package:ro" not in fixture_compose
    assert package_image_path in (
        REPOSITORY_ROOT / "tests" / "cloudatlas_fixture" / "init.sh"
    ).read_text()
    assert "dockerfile: octobus/Dockerfile" in fixture_compose
    assert "investigations/issue_29" not in fixture_compose
    assert "CHAITIN_CLI_VERSION=v2606.0.4" in octobus_image
    assert "99a0871a9a1c812b520067766b3592edccbe3d44d4f1b942831b4cbe82d8a482" in octobus_image
    assert "55be61691bb71420a1c849e8f7acb12934452d354f790a5125c8e2f5fff54e95" in octobus_image
    assert "fake-chaitin-cli" not in fixture_compose
    assert "dockerfile: octobus/Dockerfile" in deployment_compose
    assert "octobus-data:/var/lib/octobus" in deployment_compose
    assert "octobus-package-init:" in deployment_compose
    assert package_image_path in deployment_compose
    assert "service_completed_successfully" in deployment_compose
