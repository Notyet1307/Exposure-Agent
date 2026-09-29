"""Synthetic consumer regressions over the real pinned wheel, never model calls."""

import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest
from netflow_processor import feedback
from netflow_processor.readers import CANON

from app.integrations.netflow_processor import (
    ProcessorError,
    default_config,
    import_result,
    load_bundle,
    load_feedback,
    process,
    review_feedback_patch,
)


def context() -> dict:
    return {
        "tenant_id": "synthetic-tenant", "project_id": "synthetic-project",
        "dataset_id": "synthetic-dataset", "network_namespace": "synthetic-edge",
        "scope_confirmation": "confirmed", "managed_cidrs": [],
        "observation_point": {"id": "synthetic", "view": "UNKNOWN", "nat_context": "none"},
        "sampling": {"mode": "unknown", "rate": None}, "input_timezone": "UTC",
        "test_fixture": True, "fixture_notice": "Synthetic integration fixture only",
        "context_contract": "netflow-context-v1", "endpoint_selection": "declared_source",
        "scope_evidence": "Synthetic SRC is local and DST is a separate peer position",
    }


def source(tmp_path: Path, rows: int = 24) -> Path:
    path = tmp_path / "canonical.csv"
    lines = [",".join(CANON)]
    for index in range(rows):
        # Repeated records, a crossover, self loop and IPv6 remain source facts.
        src = "2001:db8::1" if index == 23 else "192.0.2.1"
        dst = "192.0.2.1" if index == 0 else "198.51.100.2"
        lines.append(f"opaque-source-{index},{src},{dst},6,51000,443,2026-01-01T00:00:00Z,2026-01-01T00:01:00Z,10,1,2")
    path.write_text("\n".join(lines) + "\n")
    return path


def bundle(tmp_path: Path, rows: int = 24):
    return process(source(tmp_path, rows), context=context(), config=default_config(), output_dir=tmp_path / "analysis-bundle", allow_test=True)


def package(root: Path, destination: Path, *, extra: tuple[str, bytes] | None = None) -> None:
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for directory in ("analysis", "review", "feedback"):
            if (root / directory).exists():
                for path in sorted((root / directory).rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(root).as_posix())
        if extra:
            archive.writestr(*extra)


def do_import(tmp_path: Path, original, archive: Path):
    return import_result(archive, raw_path=tmp_path / "canonical.csv", canonical_path=tmp_path / "canonical.csv", target_context=context(), config=default_config(), source_manifest_sha256=hashlib.sha256((original.root / "analysis/manifest.json").read_bytes()).hexdigest(), output_dir=tmp_path / "imported", max_compressed_bytes=50 * 1024 * 1024, allow_test=True)


def reseal(root: Path, relative: str, value: object) -> None:
    path = root / relative
    path.write_text(json.dumps(value) + "\n")
    manifest_path = root / "analysis/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest["artifacts"]:
        if entry["path"] == path.name:
            entry.update(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    manifest_path.write_text(json.dumps(manifest))


def test_full_sources_and_peers_are_not_candidate_filtered(tmp_path: Path) -> None:
    result = bundle(tmp_path)
    assert result.manifest["counts"]["candidates"] == 0
    assert {o["ip"] for o in result.observations} == {"192.0.2.1", "2001:db8::1"}
    assert sum(o["features"]["record_count"] for o in result.observations) == 24
    assert sum(p["record_count"] for p in result.peers) == 24
    assert {p["ip"] for p in result.peers} == {"192.0.2.1", "198.51.100.2"}
    local = next(o for o in result.observations if o["ip"] == "192.0.2.1")
    assert local["features"]["destination_count"] == 0
    assert len(local["source_refs"]) == 20 and local["source_refs_omitted"] == 3
    assert local["source_refs"][0] == "opaque-source-0"
    assert "nat" not in {task["task_kind"] for task in result.tasks}
    initial = load_feedback(result.root / "initial-feedback", namespace="synthetic-edge", allow_test=True)
    assert {row["material_status"] for row in initial.progress} == {"AWAITING_FEEDBACK"}
    assert all(not row["task_closed"] and not row["facts_changed"] for row in initial.progress)


def test_valid_empty_retains_real_empty_counts_and_feedback(tmp_path: Path) -> None:
    result = bundle(tmp_path, 0)
    assert result.manifest["input_state"] == "empty"
    assert result.observations == [] and result.peers == []
    assert result.manifest["counts"]["valid_records"] == 0
    initial = load_feedback(result.root / "initial-feedback", namespace="synthetic-edge", allow_test=True)
    assert initial.summary["total_tasks"] == len(result.tasks)
    assert all(task["applies_to_count"] == 0 for task in result.tasks)


def test_fixture_rejected_without_explicit_isolated_admission(tmp_path: Path) -> None:
    result = bundle(tmp_path)
    with pytest.raises(ProcessorError, match="netflow_test_fixture_forbidden"):
        load_bundle(result.root, namespace="synthetic-edge")
    with pytest.raises(ProcessorError, match="netflow_test_fixture_forbidden"):
        process(tmp_path / "canonical.csv", context=context(), config=default_config(), output_dir=tmp_path / "denied")


def test_partial_replacement_retains_other_answers_and_original(tmp_path: Path) -> None:
    result = bundle(tmp_path)
    initial = load_feedback(result.root / "initial-feedback", namespace="synthetic-edge", allow_test=True)
    first, second = result.tasks[:2]
    patch = lambda task, answers: {"task_id": task["task_id"], "provided_by": "Declared synthetic provider", "submitted_at": "2026-01-01T00:00:00Z", "answers": answers, "note_checks": []}
    first_answers = {key: None for key in feedback.feedback_schema()["$defs"]["answers_" + first["task_kind"]]["properties"]}
    changed = review_feedback_patch(result, initial, [patch(first, first_answers)], output_dir=tmp_path / "revision-one", allow_test=True)
    next_revision = review_feedback_patch(result, changed, [patch(second, {})], output_dir=tmp_path / "revision-two", allow_test=True)
    by_id = {r["task"]["task_id"]: r for r in next_revision.submission["responses"]}
    assert by_id[first["task_id"]] == next(r for r in changed.submission["responses"] if r["task"]["task_id"] == first["task_id"])
    assert by_id[second["task_id"]]["answers"] == {}
    assert all(r["provided_by"] is None for r in initial.submission["responses"])
    duplicate = patch(first, {})
    with pytest.raises(ProcessorError):
        review_feedback_patch(result, next_revision, [duplicate, duplicate], output_dir=tmp_path / "duplicate", allow_test=True)


def test_answer_schema_and_semantic_dependency_errors_remain_distinct(tmp_path: Path) -> None:
    result = bundle(tmp_path)
    initial = load_feedback(result.root / "initial-feedback", namespace="synthetic-edge", allow_test=True)
    task = next(t for t in result.tasks if t["task_kind"] == "export")
    response = {"task_id": task["task_id"], "provided_by": None, "submitted_at": None, "answers": {"business_role": "server"}, "note_checks": []}
    with pytest.raises(ProcessorError) as error:
        review_feedback_patch(result, initial, [response], output_dir=tmp_path / "wrong-kind", allow_test=True)
    assert error.value.status == 422
    response["answers"] = {"input_timezone": "Invalid/Zone"}
    revised = review_feedback_patch(result, initial, [response], output_dir=tmp_path / "invalid-material", allow_test=True)
    row = next(r for r in revised.progress if r["task"]["task_id"] == task["task_id"])
    assert row["material_status"] == "INVALID_MATERIAL"
    assert row["field_errors"]
    assert any(task["task_id"] in r["blocked_by"] for r in revised.progress)


def test_response_limit_applies_after_merge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = bundle(tmp_path)
    initial = load_feedback(result.root / "initial-feedback", namespace="synthetic-edge", allow_test=True)
    # The patch is empty, but the retained full submission still exceeds the cap.
    monkeypatch.setattr(feedback, "MAX_FEEDBACK_BYTES", 128)
    with pytest.raises(ProcessorError) as error:
        review_feedback_patch(result, initial, [], output_dir=tmp_path / "too-large", allow_test=True)
    assert error.value.status == 413
    assert (initial.root / "submission.json").exists()


@pytest.mark.parametrize("member", ["../escape", "/absolute", "analysis/manifest.json", "private-viewer.html"])
def test_zip_rejects_traversal_duplicates_and_unknown_members(tmp_path: Path, member: str) -> None:
    result = bundle(tmp_path)
    archive = tmp_path / "invalid.zip"
    package(result.root, archive, extra=(member, b"untrusted"))
    with pytest.raises(ProcessorError):
        do_import(tmp_path, result, archive)
    assert not (tmp_path / "escape").exists()


def test_zip_rejects_links(tmp_path: Path) -> None:
    result = bundle(tmp_path)
    archive = tmp_path / "link.zip"
    package(result.root, archive)
    with zipfile.ZipFile(archive, "a") as out:
        link = zipfile.ZipInfo("feedback/submission.json")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        out.writestr(link, "/private")
    with pytest.raises(ProcessorError):
        do_import(tmp_path, result, archive)


def test_real_replay_preserves_original_identity_and_blank_system_revision(tmp_path: Path) -> None:
    result = bundle(tmp_path)
    archive = tmp_path / "valid.zip"
    package(result.root, archive)
    imported = do_import(tmp_path, result, archive)
    assert imported.manifest == result.manifest
    assert imported.tasks == result.tasks
    assert imported.observations == result.observations
    assert (imported.root / "analysis/manifest.json").read_bytes() == (result.root / "analysis/manifest.json").read_bytes()
    blank = load_feedback(imported.root / "initial-feedback", namespace="synthetic-edge", allow_test=True)
    assert all(row["provided_by"] is None for row in blank.submission["responses"])


def test_forged_manifest_count_and_incomplete_pipeline_fail_closed(tmp_path: Path) -> None:
    result = bundle(tmp_path)
    path = result.root / "analysis/manifest.json"
    original = path.read_bytes()
    for change in ({"pipeline_complete": False}, {"counts": result.manifest["counts"] | {"valid_records": 999}}, {"component_version": "0.5.0"}):
        path.write_text(json.dumps(result.manifest | change))
        with pytest.raises(ProcessorError):
            load_bundle(result.root, namespace="synthetic-edge", allow_test=True)
    path.write_bytes(original)


def test_changed_pinned_input_rejected_even_with_valid_bundle_hashes(tmp_path: Path) -> None:
    result = bundle(tmp_path)
    archive = tmp_path / "valid.zip"
    package(result.root, archive)
    path = tmp_path / "canonical.csv"
    path.write_text(path.read_text().replace("51000", "51001"))
    with pytest.raises(ProcessorError, match="netflow_import_replay_mismatch"):
        do_import(tmp_path, result, archive)


def test_candidate_subset_cannot_introduce_a_forged_source(tmp_path: Path) -> None:
    result = bundle(tmp_path)
    # Exact component observation from immutable analysis, not the enriched DTO.
    observation = json.loads((result.root / "analysis/observations.jsonl").read_text().splitlines()[0])
    reseal(result.root, "analysis/candidates.jsonl", observation)
    with pytest.raises(ProcessorError):
        load_bundle(result.root, namespace="synthetic-edge", allow_test=True)


def test_self_declared_manifest_hash_does_not_replace_rules_replay(tmp_path: Path) -> None:
    result = bundle(tmp_path)
    path = result.root / "analysis/manifest.json"
    manifest = json.loads(path.read_text())
    manifest["counts"]["duplicate_records"] = 0
    path.write_text(json.dumps(manifest))
    archive = tmp_path / "forged.zip"
    package(result.root, archive)
    with pytest.raises(ProcessorError, match="netflow_import_replay_mismatch"):
        do_import(tmp_path, result, archive)


def test_imported_provider_claims_are_not_the_system_blank_revision(tmp_path: Path) -> None:
    result = bundle(tmp_path)
    initial = load_feedback(result.root / "initial-feedback", namespace="synthetic-edge", allow_test=True)
    task = result.tasks[0]
    imported_feedback = review_feedback_patch(
        result, initial,
        [{"task_id": task["task_id"], "provided_by": "Original synthetic provider",
          "submitted_at": "2026-01-01T00:00:00Z", "answers": {}, "note_checks": []}],
        output_dir=result.root / "feedback", allow_test=True,
    )
    original_bytes = (imported_feedback.root / "submission.json").read_bytes()
    archive = tmp_path / "with-feedback.zip"
    package(result.root, archive)
    imported = do_import(tmp_path, result, archive)
    retained = load_feedback(imported.root / "imported-feedback", namespace="synthetic-edge", allow_test=True)
    blank = load_feedback(imported.root / "initial-feedback", namespace="synthetic-edge", allow_test=True)
    assert (retained.root / "submission.json").read_bytes() == original_bytes
    assert any(r["provided_by"] == "Original synthetic provider" for r in retained.progress)
    assert all(r["provided_by"] is None for r in blank.progress)
