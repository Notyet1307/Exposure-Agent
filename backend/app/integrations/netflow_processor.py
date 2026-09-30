"""Bounded, rules-only bridge to the pinned public NetFlow component."""

import base64
import copy
import hashlib
import ipaddress
import json
import re
import shutil
import stat
import tempfile
import zipfile
import zlib
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from functools import wraps
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import ValidationError  # type: ignore[import-untyped]
from netflow_processor import (  # type: ignore[import-untyped]
    contracts,
    feedback,
    triage,
)
from netflow_processor.api import process_file  # type: ignore[import-untyped]

COMPONENT_IDENTITY = {
    "component_version": "0.4.0",
    "wheel_sha256": "eba079556be6066c66eb450421571acb07afe527d46dd4e5b8b6b95c93c56d3f",
    "schema_version": "netflow-candidates-v1",
    "rules_version": "netflow-rules-v2",
    "feature_template_version": "netflow-features-v2",
    "question_template_version": "netflow-role-question-v1",
    "review_schema_version": "netflow-review-v1",
    "review_policy_version": "netflow-review-policy-v2",
    "feedback_schema_version": "netflow-feedback-v1",
}
# Hashes from the approved wheel RECORD, not from an imported result's claims.
_FOOTPRINT = {
    "__init__.py": "vNfgYL8-zwxRENkAcIXnm2yi_6XDrQzjDECu4rH0jIE",
    "__main__.py": "ee5vE0xcUZM3fPmxicvcw-IJXkm6nOwxARREHBWpF8Q",
    "_laya_worker.py": "bA63V7PHataDqfu5UBYI6Vfqh0OO6g2mKdLCwXvjbD4",
    "api.py": "3K4LtR7lHxLna1NdgP-p4REM8cwwjg8c79rLt3fGLXs",
    "cli.py": "OKXFQW3aKYcGrL8kwVpKGn0TKIO5eTg7bVHLSSbIAC8",
    "contracts.py": "wrPXLfP5zkib4uKPTKx-zpdvI9p1usbB25n1DzXY27w",
    "decision.py": "AYllkEI4fDrZArWsOKeNWm3J05o5HMXZX7nFoE5y09I",
    "evaluation.py": "Xn12WuTCep4voT381byD2DQt2yd5UDzwfWa42lBCTbc",
    "features.py": "W8PJZeCPZ2dHPvE63u3LskeNyBMSqL4uTvmbntM4lGw",
    "feedback.py": "l35Wyu_x32OLufNjwedBeUooRqpQfoGg4JOjwxkedpU",
    "laya_adapter.py": "cVI5T5ac9cGbbFkHza_FOpdH5fRqIHjbmXgRy8LeXl4",
    "outputs.py": "KRC7mNN-Th7AB7SpfhFrcIglFmR3LlhyVEffJalLc_4",
    "readers.py": "YgBz8igifOflqNAVNDTFPjftWWOopqLpL6N69uns3V0",
    "triage.py": "Nuyx8zovuCJL4o6ra321zFcWP56Ut0WK6w0eMar5blg",
    "schemas/netflow-candidates-v1.json": "ePEbqR3-Ide-ui4lLP8PPDhKbAGu1WlG20TeKmneUTI",
    "schemas/netflow-feedback-v1.json": "3qkyAXc2S2D5k6M7A1BLviumYczJz4GyaiAIEaJeP_4",
    "schemas/netflow-review-v1.json": "l32wnynrtLXR90tk_kpaZ280qsc-8yHTzyji6pGOTRI",
}
_MIB = 1024 * 1024
_ANALYSIS = {
    "observations.jsonl": "observation",
    "candidates.jsonl": "candidate",
    "review.jsonl": "review",
    "peers.jsonl": "peer",
    "invalid-records.jsonl": "invalid_record",
}
_REVIEW = {"enriched-observations.jsonl", "review-tasks.jsonl"}
_FEEDBACK = {
    "submission.json",
    "result/summary.json",
    "result/review-progress.jsonl",
    "result/REVIEW.md",
}
_REQUIRED = (
    {"analysis/manifest.json", "review/summary.json"}
    | {"analysis/" + n for n in _ANALYSIS}
    | {"review/" + n for n in _REVIEW}
)


class ProcessorError(Exception):
    def __init__(self, code: str, status: int = 422):
        self.code, self.status = code, status
        super().__init__(code)


@dataclass
class ProcessorBundle:
    root: Path
    manifest: dict[str, Any]
    review_summary: dict[str, Any]
    observations: list[dict[str, Any]]
    peers: list[dict[str, Any]]
    tasks: list[dict[str, Any]]
    files: list[str]


@dataclass
class FeedbackBundle:
    root: Path
    submission: dict[str, Any]
    summary: dict[str, Any]
    progress: list[dict[str, Any]]
    files: list[str]


def _guard[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    @wraps(fn)
    def guarded(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            _footprint()
            return fn(*args, **kwargs)
        except ProcessorError:
            raise
        except contracts.PipelineError as exc:
            if exc.exit_code == 4:
                raise ProcessorError("netflow_processing_limit", 413) from None
            if exc.code == "TEST_FIXTURE_FORBIDDEN":
                raise ProcessorError("netflow_test_fixture_forbidden") from None
            raise ProcessorError("netflow_artifact_schema_invalid") from None
        except (
            ValidationError,
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            RecursionError,
            OverflowError,
        ):
            raise ProcessorError("netflow_artifact_schema_invalid") from None
        except OSError, zipfile.BadZipFile, EOFError, zlib.error:
            raise ProcessorError("netflow_artifact_integrity_failed", 409) from None

    return guarded


def _footprint() -> None:
    package = files("netflow_processor")
    for name, expected in _FOOTPRINT.items():
        actual = (
            base64.urlsafe_b64encode(
                hashlib.sha256(package.joinpath(name).read_bytes()).digest()
            )
            .decode()
            .rstrip("=")
        )
        if actual != expected:
            raise ProcessorError("netflow_component_version_unsupported")


def _require(
    value: Any, code: str = "netflow_artifact_schema_invalid", status: int = 422
) -> None:
    if not value:
        raise ProcessorError(code, status)


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in items:
        if key in value:
            raise ValueError("duplicate")
        value[key] = item
    return value


def _constant(_: str) -> Any:
    raise ValueError("nonfinite")


def _decode(raw: bytes) -> Any:
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)


def _bytes(path: Path, cap: int) -> bytes:
    _require(
        path.is_file() and not path.is_symlink(),
        "netflow_artifact_integrity_failed",
        409,
    )
    _require(path.stat().st_size <= cap, "netflow_processing_limit", 413)
    with path.open("rb") as stream:
        value = stream.read(cap + 1)
    _require(len(value) <= cap, "netflow_processing_limit", 413)
    return value


def _json(path: Path, cap: int = _MIB) -> Any:
    return _decode(_bytes(path, cap))


def _lines(
    path: Path, cap: int = 100 * _MIB, line_cap: int = 65536
) -> list[dict[str, Any]]:
    _require(path.stat().st_size <= cap, "netflow_processing_limit", 413)
    result: list[dict[str, Any]] = []
    with path.open("rb") as stream:
        while line := stream.readline(line_cap + 1):
            _require(
                len(line) <= line_cap and len(result) < 100000,
                "netflow_processing_limit",
                413,
            )
            result.append(_decode(line))
    return result


def _inventory(root: Path, allowed: set[str], required: set[str]) -> list[str]:
    _require(
        root.is_dir() and not root.is_symlink(),
        "netflow_artifact_integrity_failed",
        409,
    )
    names = []
    size = 0
    for path in root.rglob("*"):
        _require(not path.is_symlink(), "netflow_artifact_integrity_failed", 409)
        if path.is_dir():
            _require(
                any(
                    n.startswith(path.relative_to(root).as_posix() + "/")
                    for n in allowed
                )
            )
            continue
        _require(
            stat.S_ISREG(path.stat().st_mode), "netflow_artifact_integrity_failed", 409
        )
        name = path.relative_to(root).as_posix()
        _require(name in allowed)
        names.append(name)
        size += path.stat().st_size
        _require(
            path.stat().st_size <= 100 * _MIB
            and size <= 320 * _MIB
            and len(names) <= 32,
            "netflow_processing_limit",
            413,
        )
    _require(required <= set(names), "netflow_import_incomplete")
    return sorted(names)


def _artifacts(
    directory: Path, entries: list[dict[str, Any]], expected: set[str], cap: int
) -> None:
    _require(len(entries) == len(expected) and {a["path"] for a in entries} == expected)
    size = 0
    for entry in entries:
        raw = _bytes(directory / entry["path"], min(cap, 100 * _MIB))
        size += len(raw)
        _require(
            len(raw) == entry["bytes"]
            and hashlib.sha256(raw).hexdigest() == entry["sha256"],
            "netflow_artifact_integrity_failed",
            409,
        )
    _require(size <= cap, "netflow_processing_limit", 413)


def default_config() -> dict[str, Any]:
    return asdict(
        contracts.ProcessorConfig(
            input_profile="exposure",
            limits=contracts.DEFAULT_LIMITS
            | {"max_records": 100000, "max_input_bytes": 100 * _MIB},
            rules=dict(contracts.DEFAULT_RULES),
        )
    )


def _config(value: dict[str, Any]) -> Any:
    config = contracts.ProcessorConfig.from_dict(value)
    config.validate()
    _require(
        asdict(config) == value
        and config.mode == "rules"
        and config.laya is None
        and not config.allow_rule_fallback,
        "netflow_context_invalid",
    )
    for name, limit in default_config()["limits"].items():
        _require(config.bounds[name] <= limit, "netflow_processing_limit", 413)
    return config


def _context(value: dict[str, Any], namespace: str, allow_test: bool) -> Any:
    context = contracts.ProcessingContext.from_dict(value)
    context.validate()
    _require(
        re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", context.network_namespace),
        "netflow_context_invalid",
    )
    _require(
        context.network_namespace == namespace
        and context.endpoint_selection == "declared_source"
        and context.scope_confirmation == "confirmed"
        and context.managed_cidrs == [],
        "netflow_context_invalid",
    )
    _require(not context.test_fixture or allow_test, "netflow_test_fixture_forbidden")
    return context


def _refs(row: dict[str, Any], count: int, limit: int, raw_count: int) -> None:
    refs = row["source_refs"]
    _require(
        count <= raw_count
        and len(refs) <= min(20, limit)
        and len(refs) + row["source_refs_omitted"] == count
    )
    for ref in refs:
        _require(
            isinstance(ref, str)
            and 0 < len(ref) <= 256
            and not any(ord(c) < 32 for c in ref)
        )


@_guard
def load_bundle(
    root: Path, *, namespace: str, allow_test: bool = False
) -> ProcessorBundle:
    root = Path(root)
    optional = {
        prefix + "/" + n
        for prefix in ("initial-feedback", "imported-feedback", "feedback")
        for n in _FEEDBACK
    }
    names = _inventory(root, _REQUIRED | optional, _REQUIRED)
    m = _json(root / "analysis/manifest.json")
    contracts.validate_document(m, "manifest")
    for key in (
        "component_version",
        "schema_version",
        "rules_version",
        "feature_template_version",
        "question_template_version",
    ):
        _require(
            m[key] == COMPONENT_IDENTITY[key], "netflow_component_version_unsupported"
        )
    ctx = _context(m["analysis_context"], namespace, allow_test)
    _require(m["context_sha256"] == contracts.digest(asdict(ctx)))
    _require(
        all(
            m[k] == getattr(ctx, k)
            for k in (
                "tenant_id",
                "project_id",
                "dataset_id",
                "network_namespace",
                "test_fixture",
            )
        )
    )
    _require(
        m["status"] in ("success", "success_with_warnings")
        and m["pipeline_complete"]
        and m["exit_code"] == 0
        and not m["errors"]
        and m["mode"] == "rules"
    )
    _require(
        m["model"]["status"] == "skipped" and m["model"]["real_inference_count"] == 0
    )
    for key, limit in default_config()["limits"].items():
        _require(m["limits"][key] <= limit, "netflow_processing_limit", 413)
    _require(
        m["input_bytes"] <= 100 * _MIB and m["counts"]["raw_records"] <= 100000,
        "netflow_processing_limit",
        413,
    )
    _artifacts(
        root / "analysis",
        m["artifacts"],
        set(_ANALYSIS),
        m["limits"]["max_output_bytes"],
    )
    rows = {name: _lines(root / "analysis" / name) for name in _ANALYSIS}
    for artifact in m["artifacts"]:
        _require(artifact["records"] == len(rows[artifact["path"]]))
    for name, kind in _ANALYSIS.items():
        for row in rows[name]:
            contracts.validate_document(row, kind)
    observations = rows["observations.jsonl"]
    peers = rows["peers.jsonl"]
    counts = m["counts"]
    _require(
        len(observations) + len(peers) <= m["limits"]["max_output_items"],
        "netflow_processing_limit",
        413,
    )
    _require(
        len({o["object_key"] for o in observations}) == len(observations)
        and len({p["peer_key"] for p in peers}) == len(peers)
    )
    identity = [m[k] for k in ("tenant_id", "project_id", "network_namespace")]
    for o in observations:
        address = ipaddress.ip_address(o["ip"])
        _require(
            str(address) == o["ip"]
            and address.version == o["ip_version"]
            and getattr(address, "ipv4_mapped", None) is None
        )
        _require(
            o["object_key"]
            == "svc:"
            + contracts.digest(
                identity + [address.version, o["ip"], o["protocol"], o["local_port"]]
            )
        )
        _require(
            all(
                o[k] == m[k]
                for k in (
                    "tenant_id",
                    "project_id",
                    "dataset_id",
                    "network_namespace",
                    "test_fixture",
                )
            )
        )
        _require(
            o["rule_version"] == COMPONENT_IDENTITY["rules_version"]
            and o["model"]["status"] == "skipped"
            and o["model_adopted"] is False
        )
        f = o["features"]
        _require(
            f["source_column_only"] is True
            and f["source_count"] == f["record_count"]
            and f["destination_count"] == 0
            and f["reverse_tuple_count"] == 0
            and o["scope_eligibility"] == "declared_source_position"
        )
        _refs(
            o,
            f["record_count"],
            m["limits"]["max_evidence_refs_per_item"],
            counts["raw_records"],
        )
    for p in peers:
        address = ipaddress.ip_address(p["ip"])
        _require(
            str(address) == p["ip"]
            and address.version == p["ip_version"]
            and getattr(address, "ipv4_mapped", None) is None
        )
        _require(
            p["peer_key"]
            == "peer:"
            + contracts.digest(identity + [p["ip"], p["protocol"], p["peer_port"]])
        )
        _require(
            p["test_fixture"] == m["test_fixture"]
            and p["is_local_candidate"] is False
            and p["role_basis"] == "declared_destination_position"
        )
        _refs(
            p,
            p["record_count"],
            m["limits"]["max_evidence_refs_per_item"],
            counts["raw_records"],
        )
    for name, recommendation in (
        ("candidates.jsonl", "VERIFY_CANDIDATE"),
        ("review.jsonl", "REVIEW_REQUIRED"),
    ):
        _require(
            rows[name]
            == [o for o in observations if o["final_recommendation"] == recommendation]
        )
    _require(
        counts["observations"] == counts["service_hypotheses"] == len(observations)
        and counts["candidates"] == len(rows["candidates.jsonl"])
        and counts["review"] == len(rows["review.jsonl"])
    )
    _require(
        counts["excluded"]
        == sum(o["final_recommendation"] == "EXCLUDE_BY_RULE" for o in observations)
    )
    _require(
        counts["valid_records"]
        == sum(o["features"]["record_count"] for o in observations)
        == sum(p["record_count"] for p in peers)
    )
    _require(
        counts["invalid_records"] == len(rows["invalid-records.jsonl"])
        and counts["raw_records"] == counts["valid_records"] + counts["invalid_records"]
    )
    _require(
        counts["endpoint_count"] == len({o["ip"] for o in observations})
        and counts["peer_addresses"] == len({p["ip"] for p in peers})
        and counts["peer_hypotheses"] == len(peers)
    )
    crossover = {o["ip"] for o in observations} & {p["ip"] for p in peers}
    _require(
        counts["address_side_crossover_count"] == len(crossover)
        and all(
            o["features"]["address_side_crossover"] == (o["ip"] in crossover)
            for o in observations
        )
        and all(p["address_side_crossover"] == (p["ip"] in crossover) for p in peers)
    )
    _require(
        counts["raw_records"] == 0 or counts["valid_records"] > 0,
        "netflow_no_valid_records",
    )
    expected_state = (
        "empty"
        if not counts["raw_records"]
        else "data_with_candidates"
        if counts["candidates"]
        else "data_without_candidates"
    )
    _require(
        m["input_state"] == expected_state
        and m["data_quality"]["input_processing_complete"] is True
    )
    s = _json(root / "review/summary.json")
    triage.validate_review(s, "summary")
    _require(
        s["component_version"] == "0.4.0"
        and s["policy_version"] == triage.POLICY_VERSION
        and s["schema_version"] == triage.TRIAGE_VERSION,
        "netflow_component_version_unsupported",
    )
    _require(
        s["status"] == "success"
        and s["pipeline_complete"]
        and s["model_calls"] == 0
        and not s["model_triage_enabled"]
        and s["original_recommendations_unchanged"]
    )
    _artifacts(
        root / "review", s["artifacts"], _REVIEW, m["limits"]["max_output_bytes"]
    )
    binding, task_map, _ = feedback._source(root / "analysis", root / "review")
    object_map = {o["object_key"]: o for o in observations}
    for task in task_map.values():
        if task["object_key"] is not None:
            _require(
                task["object_key"] in object_map
                and task["source_refs"] == object_map[task["object_key"]]["source_refs"]
            )
        else:
            _require(task["source_refs"] == [])
    enriched = _lines(root / "review/enriched-observations.jsonl")
    _require(len(enriched) == len(observations))
    merged = []
    for original, extra in zip(observations, enriched, strict=True):
        triage.validate_review(extra, "observation")
        _require(
            extra["object_key"] == original["object_key"]
            and extra["source_run_id"] == m["run_id"]
            and extra["test_fixture"] == m["test_fixture"]
        )
        for key in (
            "ip",
            "ip_version",
            "protocol",
            "local_port",
            "source_refs",
            "source_refs_omitted",
            "scope_eligibility",
        ):
            _require(extra[key] == original[key])
        _require(
            extra["facts"] == {key: original["features"][key] for key in extra["facts"]}
        )
        _require(
            extra["original_recommendation"] == original["final_recommendation"]
            and extra["original_rule_role"] == original["rule_role"]
            and extra["original_model_role"] == original["model_role"]
        )
        _require(
            all(extra[k] == v for k, v in triage.describe_observation(original).items())
        )
        _require(
            len(extra["review_task_ids"]) == len(set(extra["review_task_ids"]))
            and set(extra["review_task_ids"]) <= task_map.keys()
        )
        merged.append(
            original
            | extra
            | {
                "schema_version": original["schema_version"],
                "review_schema_version": extra["schema_version"],
            }
        )
    _require(
        s["behavior_counts"]
        == dict(Counter(tag for o in enriched for tag in o["behavior_tags"]))
        and s["category_counts"]
        == dict(Counter(o["review_category"] for o in enriched))
    )
    for task in task_map.values():
        _require(
            task["applies_to_count"]
            == sum(task["task_id"] in o["review_task_ids"] for o in enriched)
        )
    for prefix in ("initial-feedback", "imported-feedback", "feedback"):
        subset = {n for n in names if n.startswith(prefix + "/")}
        if subset:
            _require(
                subset == {prefix + "/" + n for n in _FEEDBACK},
                "netflow_import_incomplete",
            )
            fb = load_feedback(
                root / prefix, namespace=namespace, allow_test=allow_test
            )
            _require(fb.submission["binding"] == binding)
            _require(
                all(
                    r["task"] == task_map.get(r["task"]["task_id"]) for r in fb.progress
                )
            )
            if prefix == "initial-feedback":
                _require(
                    all(
                        r["provided_by"] is None
                        and r["submitted_at"] is None
                        and not r["note_checks"]
                        and all(v is None for v in r["answers"].values())
                        for r in fb.submission["responses"]
                    )
                )
    return ProcessorBundle(root, m, s, merged, peers, list(task_map.values()), names)


def _write_submission(root: Path, submission: dict[str, Any]) -> None:
    feedback.validate_feedback(submission, "submission")
    raw = (
        json.dumps(submission, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    ).encode()
    _require(len(raw) <= feedback.MAX_FEEDBACK_BYTES, "netflow_processing_limit", 413)
    _require(
        len(submission["responses"]) <= feedback.MAX_TASKS,
        "netflow_processing_limit",
        413,
    )
    for response in submission["responses"]:
        _require(
            len(json.dumps(response, ensure_ascii=False).encode())
            <= feedback.MAX_LINE_BYTES,
            "netflow_processing_limit",
            413,
        )
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    (root / "submission.json").write_bytes(raw)


@_guard
def load_feedback(
    root: Path, *, namespace: str, allow_test: bool = False
) -> FeedbackBundle:
    root = Path(root)
    names = _inventory(root, _FEEDBACK, _FEEDBACK)
    submission = _json(root / "submission.json", feedback.MAX_FEEDBACK_BYTES)
    feedback.validate_feedback(submission, "submission")
    summary, progress = feedback.load_feedback_result(
        root / "result", namespace=namespace, allow_test=allow_test
    )
    _require(
        summary["component_version"] == "0.4.0", "netflow_component_version_unsupported"
    )
    _require(
        summary["pipeline_complete"]
        and summary["status"] in ("success", "success_with_warnings")
        and summary["exit_code"] == 0
    )
    _require(
        summary["binding"] == submission["binding"]
        and summary["feedback_sha256"]
        == hashlib.sha256(
            _bytes(root / "submission.json", feedback.MAX_FEEDBACK_BYTES)
        ).hexdigest(),
        "netflow_artifact_integrity_failed",
        409,
    )
    _artifacts(
        root / "result",
        summary["artifacts"],
        {"review-progress.jsonl", "REVIEW.md"},
        feedback.MAX_OUTPUT_BYTES,
    )
    by_id = {r["task"]["task_id"]: r for r in progress}
    seen = set()
    for response in submission["responses"]:
        key = response["task"]["task_id"]
        _require(key in by_id and key not in seen)
        seen.add(key)
        _require(
            len(json.dumps(response, ensure_ascii=False).encode())
            <= feedback.MAX_LINE_BYTES,
            "netflow_processing_limit",
            413,
        )
        _require(
            all(
                response[k] == by_id[key][k]
                for k in (
                    "task",
                    "provided_by",
                    "submitted_at",
                    "answers",
                    "note_checks",
                )
            )
        )
    for key, row in by_id.items():
        if key not in seen:
            _require(
                row["provided_by"] is None
                and row["submitted_at"] is None
                and not row["answers"]
                and not row["note_checks"]
            )
        _require(
            set(row["task"]["depends_on"]) <= by_id.keys()
            and set(row["blocked_by"]) <= set(row["task"]["depends_on"])
        )
    _require(
        summary["submitted_tasks"]
        == sum(r["material_status"] != "AWAITING_FEEDBACK" for r in progress)
    )
    return FeedbackBundle(root, submission, summary, progress, names)


@_guard
def empty_feedback(
    bundle: ProcessorBundle, *, output_dir: Path, allow_test: bool = False
) -> FeedbackBundle:
    with tempfile.TemporaryDirectory(prefix="netflow-template-") as tmp:
        template = Path(tmp) / "template"
        feedback.create_feedback_template(
            bundle.root / "analysis", bundle.root / "review", output_dir=template
        )
        _write_submission(
            output_dir, _json(template / "feedback.json", feedback.MAX_FEEDBACK_BYTES)
        )
    feedback.review_feedback(
        bundle.root / "analysis",
        bundle.root / "review",
        output_dir / "submission.json",
        output_dir=output_dir / "result",
    )
    return load_feedback(
        output_dir,
        namespace=bundle.manifest["network_namespace"],
        allow_test=allow_test,
    )


@_guard
def review_feedback_patch(
    bundle: ProcessorBundle,
    previous: FeedbackBundle,
    responses: list[dict[str, Any]],
    *,
    output_dir: Path,
    allow_test: bool = False,
) -> FeedbackBundle:
    previous = load_feedback(
        previous.root,
        namespace=bundle.manifest["network_namespace"],
        allow_test=allow_test,
    )
    binding, tasks, _ = feedback._source(
        bundle.root / "analysis", bundle.root / "review"
    )
    _require(previous.submission["binding"] == binding)
    _require(isinstance(responses, list) and len(responses) <= 100)
    accepted = {
        r["task"]["task_id"]: copy.deepcopy(r) for r in previous.submission["responses"]
    }
    seen = set()
    for response in responses:
        _require(
            set(response)
            == {"task_id", "provided_by", "submitted_at", "answers", "note_checks"}
        )
        key = response["task_id"]
        _require(key in tasks, "review_task_not_found", 404)
        _require(key not in seen)
        feedback.validate_feedback(
            response["answers"], "answers_" + tasks[key]["task_kind"]
        )
        seen.add(key)
        accepted[key] = {k: v for k, v in response.items() if k != "task_id"} | {
            "task": tasks[key]
        }
    submission = copy.deepcopy(previous.submission)
    submission["responses"] = sorted(
        accepted.values(), key=lambda r: (r["task"]["work_order"], r["task"]["task_id"])
    )
    _write_submission(output_dir, submission)
    feedback.review_feedback(
        bundle.root / "analysis",
        bundle.root / "review",
        output_dir / "submission.json",
        output_dir=output_dir / "result",
    )
    return load_feedback(
        output_dir,
        namespace=bundle.manifest["network_namespace"],
        allow_test=allow_test,
    )


@_guard
def answer_schema(task_kind: str) -> dict[str, Any]:
    _require(task_kind in triage.TASKS)
    schema = feedback.feedback_schema()
    return copy.deepcopy(
        schema["$defs"]["answers_" + task_kind]
        | {"$schema": schema["$schema"], "$defs": schema["$defs"]}
    )


@_guard
def process(
    input_path: Path,
    *,
    context: dict[str, Any],
    config: dict[str, Any],
    output_dir: Path,
    allow_test: bool = False,
) -> ProcessorBundle:
    cfg = _config(config)
    _require(cfg.input_profile == "exposure", "netflow_context_invalid")
    ctx = _context(context, context["network_namespace"], allow_test)
    _require(ctx.input_timezone == "UTC", "netflow_context_invalid")
    output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    result = process_file(
        input_path, context=ctx, config=cfg, output_dir=output_dir / "analysis"
    )
    if result.exit_code:
        _require(
            False,
            "netflow_processing_limit"
            if result.exit_code == 4
            else "netflow_artifact_schema_invalid",
            413 if result.exit_code == 4 else 422,
        )
    triage.triage_result(output_dir / "analysis", output_dir=output_dir / "review")
    bundle = load_bundle(
        output_dir, namespace=ctx.network_namespace, allow_test=allow_test
    )
    empty_feedback(
        bundle, output_dir=output_dir / "initial-feedback", allow_test=allow_test
    )
    return load_bundle(
        output_dir, namespace=ctx.network_namespace, allow_test=allow_test
    )


def _extract(zip_path: Path, output_dir: Path, compressed_cap: int) -> None:
    _require(
        zip_path.stat().st_size <= min(compressed_cap, 50 * _MIB),
        "netflow_import_too_large",
        413,
    )
    _require(zipfile.is_zipfile(zip_path), "netflow_import_media_type", 415)
    allowed = _REQUIRED | {"feedback/" + n for n in _FEEDBACK}
    with zipfile.ZipFile(zip_path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        _require(
            len(infos) <= 32 and sum(i.file_size for i in infos) <= 320 * _MIB,
            "netflow_import_too_large",
            413,
        )
        _require(len(set(names)) == len(names) and set(names) <= allowed)
        _require(_REQUIRED <= set(names), "netflow_import_incomplete")
        feedback_names = set(names) - _REQUIRED
        _require(
            not feedback_names
            or feedback_names == {"feedback/" + n for n in _FEEDBACK},
            "netflow_import_incomplete",
        )
        for info in infos:
            mode = info.external_attr >> 16
            _require(
                not info.is_dir()
                and stat.S_IFMT(mode) in (0, stat.S_IFREG)
                and not info.flag_bits & 1
                and info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
            )
            _require(info.file_size <= 100 * _MIB, "netflow_import_too_large", 413)
        output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
        for info in infos:
            destination = output_dir / info.filename
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            size = 0
            with archive.open(info) as source, destination.open("xb") as target:
                while block := source.read(_MIB):
                    size += len(block)
                    _require(size <= info.file_size, "netflow_import_too_large", 413)
                    target.write(block)
            _require(size == info.file_size, "netflow_artifact_integrity_failed", 409)


def _without_run(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in row.items() if k != "source_run_id"} for row in rows]


@_guard
def import_result(
    zip_path: Path,
    *,
    raw_path: Path,
    canonical_path: Path,
    target_context: dict[str, Any],
    config: dict[str, Any],
    source_manifest_sha256: str,
    output_dir: Path,
    max_compressed_bytes: int,
    allow_test: bool = False,
) -> ProcessorBundle:
    cfg = _config(config)
    target = _context(target_context, target_context["network_namespace"], allow_test)
    _extract(zip_path, output_dir, max_compressed_bytes)
    original = load_bundle(
        output_dir, namespace=target.network_namespace, allow_test=allow_test
    )
    m = original.manifest
    _require(
        hashlib.sha256(_bytes(output_dir / "analysis/manifest.json", _MIB)).hexdigest()
        == source_manifest_sha256,
        "netflow_artifact_integrity_failed",
        409,
    )
    source_context = m["analysis_context"]
    # Identity mapping is authorized by the caller, never written into component bytes.
    identity_fields = {"tenant_id", "project_id", "dataset_id", "input_timezone"}
    _require(
        {k: v for k, v in source_context.items() if k not in identity_fields}
        == {k: v for k, v in asdict(target).items() if k not in identity_fields},
        "netflow_context_invalid",
    )
    _require(
        m["config_sha256"] == contracts.digest(config)
        and m["input_profile"] == cfg.input_profile
        and m["limits"] == cfg.bounds
        and m["policy"] == cfg.policy
    )
    input_path = canonical_path if cfg.input_profile == "exposure" else raw_path
    if cfg.input_profile == "exposure":
        _require(source_context["input_timezone"] == "UTC", "netflow_context_invalid")
    raw = _bytes(input_path, cfg.bounds["max_input_bytes"])
    _require(
        hashlib.sha256(raw).hexdigest() == m["input_sha256"]
        and len(raw) == m["input_bytes"],
        "netflow_import_replay_mismatch",
        409,
    )
    with tempfile.TemporaryDirectory(prefix="netflow-replay-") as tmp:
        replay = Path(tmp)
        process_file(
            input_path,
            context=contracts.ProcessingContext.from_dict(source_context),
            config=cfg,
            output_dir=replay / "analysis",
        )
        triage.triage_result(
            replay / "analysis",
            output_dir=replay / "review",
            context_notes=original.review_summary["context_notes"],
        )
        actual = load_bundle(
            replay, namespace=target.network_namespace, allow_test=allow_test
        )
        ignored = {"run_id", "timings", "peak_rss_mib"}
        _require(
            {k: v for k, v in m.items() if k not in ignored}
            == {k: v for k, v in actual.manifest.items() if k not in ignored},
            "netflow_import_replay_mismatch",
            409,
        )
        _require(
            _without_run(original.observations) == _without_run(actual.observations)
            and original.peers == actual.peers
            and _without_run(original.tasks) == _without_run(actual.tasks),
            "netflow_import_replay_mismatch",
            409,
        )
        review_metadata = {"source_run_id", "artifacts"}
        _require(
            {
                k: v
                for k, v in original.review_summary.items()
                if k not in review_metadata
            }
            == {
                k: v
                for k, v in actual.review_summary.items()
                if k not in review_metadata
            },
            "netflow_import_replay_mismatch",
            409,
        )
        if (output_dir / "feedback").exists():
            imported = load_feedback(
                output_dir / "feedback",
                namespace=target.network_namespace,
                allow_test=allow_test,
            )
            feedback.review_feedback(
                output_dir / "analysis",
                output_dir / "review",
                imported.root / "submission.json",
                output_dir=replay / "feedback-check",
            )
            check_summary, check_rows = feedback.load_feedback_result(
                replay / "feedback-check",
                namespace=target.network_namespace,
                allow_test=allow_test,
            )
            # Experimental historical hints are retained, but never executed or treated as material assessment.
            ignored_progress = {"model_hints"}
            _require(
                [
                    {k: v for k, v in row.items() if k not in ignored_progress}
                    for row in imported.progress
                ]
                == [
                    {k: v for k, v in row.items() if k not in ignored_progress}
                    for row in check_rows
                ]
                and imported.summary["state_counts"] == check_summary["state_counts"],
                "netflow_import_replay_mismatch",
                409,
            )
            shutil.copytree(imported.root, output_dir / "imported-feedback")
    empty_feedback(
        original, output_dir=output_dir / "initial-feedback", allow_test=allow_test
    )
    return load_bundle(
        output_dir, namespace=target.network_namespace, allow_test=allow_test
    )
