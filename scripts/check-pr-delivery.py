#!/usr/bin/env python3
"""Deterministic PR delivery guardrail checks (project-agnostic, Python 3.9+ stdlib only).

Checks:
1. PR body / comment text contains no host local paths, Cindy host identifiers, or private env paths.
2. Verification manifest/receipt (`frozen-assets.json` or minimal `{"product_head": "<sha>", "status": "PASS"}`)
   matches the target HEAD SHA and has intact asset hashes.
3. Optional `--require-pass`: verifies that the receipt proves a real PASS verdict (not just a
   pre-run `MODE=prepare` manifest or a failed/unrun verification).

Exit codes: 0 = PASS, 1 = FAIL, 2 = BLOCKED (invalid input / missing file).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HOST_LEAK_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "macos-or-linux-home-path",
        re.compile(r"(?<![A-Za-z0-9_])(?:/Users/|/home/)[A-Za-z0-9._-]+/"),
    ),
    (
        "windows-home-path",
        re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:\\Users\\[A-Za-z0-9._-]+\\"),
    ),
    (
        "tilde-local-ops-path",
        re.compile(r"(?<![A-Za-z0-9_])~/(?:ops|Library|Developer|Archive)/"),
    ),
    (
        "cindy-host-data-dir",
        re.compile(r"CindyGlobal|cindy-[a-z0-9]{16,}\.db"),
    ),
    (
        "cindy-owner-or-bot-id",
        re.compile(r"owners/[0-9a-f]{16,}|bot_[0-9]{10,}_[a-z0-9]+"),
    ),
    (
        "private-runtime-env-path",
        re.compile(r"/srv/[A-Za-z0-9._-]+/private/runtime\.env"),
    ),
)

HEX_SHA_40 = re.compile(r"^[0-9a-fA-F]{40}$")
PASS_LOG_RE = re.compile(r'"status"\s*:\s*"PASS"')


def check_pr_body_text(
    text: str, extra_patterns: list[str] | None = None
) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    rules: list[tuple[str, re.Pattern[str]]] = list(HOST_LEAK_RULES)
    for idx, raw in enumerate(extra_patterns or []):
        rules.append((f"extra-rule-{idx + 1}", re.compile(raw)))

    for lineno, line in enumerate(text.splitlines(), start=1):
        for rule_name, pattern in rules:
            for match in pattern.finditer(line):
                findings.append(
                    {
                        "rule": rule_name,
                        "line": lineno,
                        "match": match.group(0),
                    }
                )
    return findings


def resolve_head_sha(head: str | None, repo: Path | None) -> str:
    if head:
        cleaned = head.strip()
        if not HEX_SHA_40.match(cleaned):
            raise ValueError(f"Expected 40-char hex SHA for --head, got: {cleaned!r}")
        return cleaned.lower()
    if repo is None:
        raise ValueError(
            "Provide --head <40-char-sha> or --repo <path> with --frozen-manifest"
        )
    out = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    if not HEX_SHA_40.match(out):
        raise ValueError(f"Unexpected git HEAD SHA: {out!r}")
    return out.lower()


def _read_exit_code(path: Path) -> str | None:
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").strip()


def _check_frozen_bundle_pass(
    run_root: Path, expected_head: str
) -> tuple[list[str], list[str]]:
    """Verify sibling lifecycle exits and passing run evidence beside frozen-assets.json."""
    errors: list[str] = []
    verified_runs: list[str] = []

    prep_exit = _read_exit_code(run_root / "prepare.exit")
    if prep_exit != "0":
        errors.append(
            f"Missing or non-zero prepare.exit beside frozen manifest (got {prep_exit!r})"
        )

    chk_exit = _read_exit_code(run_root / "check.exit")
    if chk_exit != "0":
        errors.append(
            f"Missing or non-zero check.exit beside frozen manifest (got {chk_exit!r}); "
            "run MODE=check after verification completes"
        )

    evidence_results = sorted(run_root.glob("evidence*/result.json"))
    for res_path in evidence_results:
        ev_dir = res_path.parent.name
        if ev_dir.startswith("evidence-negative"):
            continue
        try:
            res_data = json.loads(res_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"Unreadable evidence result {ev_dir}/result.json: {exc}")
            continue
        if not isinstance(res_data, dict):
            errors.append(f"Invalid evidence result root in {ev_dir}/result.json")
            continue

        status = str(res_data.get("status", "")).strip().upper()
        if status != "PASS":
            errors.append(
                f"Evidence {ev_dir}/result.json did not PASS (status={status!r})"
            )
            continue

        cleanup = res_data.get("cleanup")
        if cleanup is not None and str(cleanup).strip().upper() != "PASS":
            errors.append(
                f"Evidence {ev_dir}/result.json cleanup did not PASS (cleanup={cleanup!r})"
            )
            continue

        ev_head = str(res_data.get("head", "")).strip().lower()
        if ev_head and ev_head != expected_head.lower():
            errors.append(
                f"Evidence {ev_dir}/result.json head={ev_head} != target head={expected_head.lower()}"
            )
            continue

        verified_runs.append(f"{ev_dir}/result.json")

    for exit_path in sorted(run_root.glob("*.exit")):
        stem = exit_path.stem
        if stem in ("prepare", "check") or stem.startswith("negative"):
            continue
        code = _read_exit_code(exit_path)
        if code != "0":
            errors.append(f"Verification step {exit_path.name} failed (exit={code!r})")
            continue
        log_path = run_root / f"{stem}.log"
        if log_path.is_file() and PASS_LOG_RE.search(
            log_path.read_text(encoding="utf-8", errors="replace")
        ):
            verified_runs.append(f"{stem}.exit")

    if not verified_runs and not errors:
        errors.append(
            "No passing verification run found beside frozen manifest "
            "(expected passing evidence*/result.json or passing <step>.exit with PASS log; "
            "prepare/check alone is not a verification PASS)"
        )
    elif not verified_runs:
        errors.append("No passing verification run confirmed beside frozen manifest")

    return errors, verified_runs


def check_frozen_manifest(
    manifest_path: Path, expected_head: str, *, require_pass: bool = False
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    verified_runs: list[str] = []
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return ["Manifest root must be a JSON object"], verified_runs

    product_head = str(data.get("product_head", "")).strip().lower()
    if not HEX_SHA_40.match(product_head):
        errors.append(f"Invalid or missing product_head in manifest: {product_head!r}")
    elif product_head != expected_head.lower():
        errors.append(
            f"Stale verification evidence: manifest product_head={product_head} != target head={expected_head.lower()}"
        )

    assets = data.get("assets")
    if isinstance(assets, list):
        for item in assets:
            if not isinstance(item, dict):
                errors.append("Manifest asset entry is not an object")
                continue
            live_sha = item.get("live_sha256")
            frozen_sha = item.get("frozen_sha256")
            if live_sha and frozen_sha and live_sha != frozen_sha:
                errors.append(
                    f"Asset hash mismatch for {item.get('path', '<unknown>')}: live != frozen"
                )

    if require_pass:
        if "status" in data:
            receipt_status = str(data.get("status", "")).strip().upper()
            if receipt_status != "PASS":
                errors.append(
                    f"Verification receipt status must be PASS (got {receipt_status!r})"
                )
            else:
                verified_runs.append(f"{manifest_path.name}:status=PASS")
            checks = data.get("checks")
            if isinstance(checks, list):
                for idx, entry in enumerate(checks):
                    if isinstance(entry, dict) and "status" in entry:
                        c_status = str(entry["status"]).strip().upper()
                        if c_status in ("FAIL", "BLOCKED"):
                            name = entry.get("name", f"check[{idx}]")
                            errors.append(
                                f"Receipt check {name!r} has failing status {c_status!r}"
                            )
        else:
            bundle_errors, bundle_runs = _check_frozen_bundle_pass(
                manifest_path.parent, expected_head
            )
            errors.extend(bundle_errors)
            verified_runs.extend(bundle_runs)

    return errors, verified_runs


def run_self_test() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        clean_body = "## Why\nFix flow.\n\n## Verification\n- Evidence ID: run-20261120T000000Z (`PASS`)\n"
        leaky_body = (
            "Screenshot at ~/ops/tasks/demo/run-1/ and /Users/alice/dev/app/foo.png\n"
        )
        cindy_body = "Bot bot_0000000000000_demo01 in CindyGlobal\n"

        clean_ok = len(check_pr_body_text(clean_body)) == 0
        leaky_caught = len(check_pr_body_text(leaky_body)) >= 2
        cindy_caught = len(check_pr_body_text(cindy_body)) >= 2

        head_a = "a" * 40
        head_b = "b" * 40

        # 1. Frozen manifest HEAD match / stale check (without --require-pass)
        frozen_dir = root / "frozen-pass"
        frozen_dir.mkdir()
        manifest = frozen_dir / "frozen-assets.json"
        manifest.write_text(
            json.dumps(
                {
                    "product_head": head_a,
                    "assets": [
                        {
                            "path": "SKILL.md",
                            "live_sha256": "1" * 64,
                            "frozen_sha256": "1" * 64,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        manifest_match_ok = len(check_frozen_manifest(manifest, head_a)[0]) == 0
        manifest_stale_caught = len(check_frozen_manifest(manifest, head_b)[0]) == 1

        # 2. P0-1: prepare-only frozen manifest MUST FAIL under --require-pass
        (frozen_dir / "prepare.exit").write_text("0\n", encoding="utf-8")
        prepare_only_caught = (
            len(check_frozen_manifest(manifest, head_a, require_pass=True)[0]) >= 1
        )

        # 3. P0-1: prepare+check with FAIL result.json MUST FAIL under --require-pass
        (frozen_dir / "check.exit").write_text("0\n", encoding="utf-8")
        ev_dir = frozen_dir / "evidence"
        ev_dir.mkdir()
        (ev_dir / "result.json").write_text(
            json.dumps({"status": "FAIL", "cleanup": "PASS", "head": head_a}),
            encoding="utf-8",
        )
        failed_evidence_caught = (
            len(check_frozen_manifest(manifest, head_a, require_pass=True)[0]) >= 1
        )

        # 4. P0-1: prepare+check with PASS result.json MUST PASS under --require-pass
        (ev_dir / "result.json").write_text(
            json.dumps({"status": "PASS", "cleanup": "PASS", "head": head_a}),
            encoding="utf-8",
        )
        passed_evidence_ok = (
            len(check_frozen_manifest(manifest, head_a, require_pass=True)[0]) == 0
        )

        # 5. P0-1: doctor-only frozen bundle (doctor.exit=0 + PASS log) MUST PASS
        doc_dir = root / "frozen-doctor"
        doc_dir.mkdir()
        doc_manifest = doc_dir / "frozen-assets.json"
        doc_manifest.write_text(
            json.dumps({"product_head": head_a, "assets": []}), encoding="utf-8"
        )
        (doc_dir / "prepare.exit").write_text("0\n", encoding="utf-8")
        (doc_dir / "check.exit").write_text("0\n", encoding="utf-8")
        (doc_dir / "doctor.exit").write_text("0\n", encoding="utf-8")
        (doc_dir / "doctor.log").write_text(
            '{"status": "PASS", "reason": ""}\n', encoding="utf-8"
        )
        passed_doctor_ok = (
            len(check_frozen_manifest(doc_manifest, head_a, require_pass=True)[0]) == 0
        )

        # 6. Minimal greenfield receipt with explicit status=PASS vs status=FAIL vs missing status
        min_pass = root / "receipt-pass.json"
        min_pass.write_text(
            json.dumps(
                {
                    "product_head": head_a,
                    "status": "PASS",
                    "checks": [{"name": "smoke", "status": "PASS"}],
                }
            ),
            encoding="utf-8",
        )
        min_fail = root / "receipt-fail.json"
        min_fail.write_text(
            json.dumps({"product_head": head_a, "status": "FAIL"}), encoding="utf-8"
        )
        min_nostatus = root / "receipt-nostatus.json"
        min_nostatus.write_text(json.dumps({"product_head": head_a}), encoding="utf-8")

        minimal_pass_ok = (
            len(check_frozen_manifest(min_pass, head_a, require_pass=True)[0]) == 0
        )
        minimal_fail_caught = (
            len(check_frozen_manifest(min_fail, head_a, require_pass=True)[0]) >= 1
        )
        minimal_nostatus_caught = (
            len(check_frozen_manifest(min_nostatus, head_a, require_pass=True)[0]) >= 1
        )

    passed = all(
        (
            clean_ok,
            leaky_caught,
            cindy_caught,
            manifest_match_ok,
            manifest_stale_caught,
            prepare_only_caught,
            failed_evidence_caught,
            passed_evidence_ok,
            passed_doctor_ok,
            minimal_pass_ok,
            minimal_fail_caught,
            minimal_nostatus_caught,
        )
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "clean_body_pass": clean_ok,
        "local_path_leak_caught": leaky_caught,
        "cindy_id_leak_caught": cindy_caught,
        "manifest_head_match_pass": manifest_match_ok,
        "manifest_stale_head_caught": manifest_stale_caught,
        "prepare_only_pass_blocked": prepare_only_caught,
        "failed_evidence_pass_blocked": failed_evidence_caught,
        "passed_evidence_pass": passed_evidence_ok,
        "passed_doctor_bundle_pass": passed_doctor_ok,
        "minimal_receipt_pass": minimal_pass_ok,
        "minimal_receipt_fail_blocked": minimal_fail_caught,
        "minimal_receipt_nostatus_blocked": minimal_nostatus_caught,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check PR delivery body for host-path leaks and verify HEAD/PASS-bound receipts."
    )
    parser.add_argument(
        "--pr-body",
        help="Path to PR body/comment text file, or '-' to read from stdin.",
    )
    parser.add_argument(
        "--frozen-manifest",
        type=Path,
        help=(
            "Path to verification receipt JSON "
            "(e.g. frozen-assets.json or minimal {'product_head': '<sha>', 'status': 'PASS'})."
        ),
    )
    parser.add_argument(
        "--require-manifest",
        action="store_true",
        help="Fail if --frozen-manifest is omitted (enforces HEAD-bound verification receipt).",
    )
    parser.add_argument(
        "--require-pass",
        action="store_true",
        help=(
            "Implies --require-manifest and additionally requires proof of a PASS verdict "
            "(explicit receipt status=='PASS' or frozen-bundle check.exit==0 + passing run)."
        ),
    )
    parser.add_argument(
        "--head",
        help="Expected 40-char PR head commit SHA (used with --frozen-manifest).",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="Git repo path to read HEAD when --head is omitted.",
    )
    parser.add_argument(
        "--extra-forbidden-regex",
        action="append",
        default=[],
        help="Additional regex pattern(s) forbidden in PR body text.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run built-in positive and negative self-tests.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        result = run_self_test()
        sys.stdout.write(json.dumps(result, indent=2) + "\n")
        return 0 if result["status"] == "PASS" else 1

    need_manifest = args.require_manifest or args.require_pass
    if not args.pr_body and not args.frozen_manifest and not need_manifest:
        parser.error(
            "Specify at least one of --pr-body, --frozen-manifest, --require-manifest, --require-pass, or --self-test"
        )

    report: dict[str, object] = {"status": "PASS", "checks": {}}
    checks: dict[str, object] = {}
    failed = False

    if args.pr_body:
        try:
            if args.pr_body == "-":
                body_text = sys.stdin.read()
            else:
                body_text = Path(args.pr_body).read_text(encoding="utf-8")
        except OSError as exc:
            sys.stdout.write(
                json.dumps({"status": "BLOCKED", "error": str(exc)}, indent=2) + "\n"
            )
            return 2

        try:
            findings = check_pr_body_text(body_text, args.extra_forbidden_regex)
        except re.error as exc:
            sys.stdout.write(
                json.dumps(
                    {"status": "BLOCKED", "error": f"Invalid regex: {exc}"}, indent=2
                )
                + "\n"
            )
            return 2

        checks["pr_body"] = {
            "status": "PASS" if not findings else "FAIL",
            "findings": findings,
        }
        if findings:
            failed = True

    if need_manifest and not args.frozen_manifest:
        checks["frozen_manifest"] = {
            "status": "FAIL",
            "errors": [
                "Missing required verification receipt: pass --frozen-manifest <path> with --require-manifest / --require-pass"
            ],
        }
        failed = True
    elif args.frozen_manifest:
        if not args.frozen_manifest.is_file():
            sys.stdout.write(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "error": f"Manifest not found: {args.frozen_manifest}",
                    },
                    indent=2,
                )
                + "\n"
            )
            return 2
        try:
            expected_head = resolve_head_sha(args.head, args.repo)
            manifest_errors, verified_runs = check_frozen_manifest(
                args.frozen_manifest, expected_head, require_pass=args.require_pass
            )
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            subprocess.CalledProcessError,
        ) as exc:
            sys.stdout.write(
                json.dumps({"status": "BLOCKED", "error": str(exc)}, indent=2) + "\n"
            )
            return 2

        checks["frozen_manifest"] = {
            "status": "PASS" if not manifest_errors else "FAIL",
            "expected_head": expected_head,
            "require_pass": args.require_pass,
            "verified_runs": verified_runs,
            "errors": manifest_errors,
        }
        if manifest_errors:
            failed = True

    report["checks"] = checks
    report["status"] = "FAIL" if failed else "PASS"
    sys.stdout.write(json.dumps(report, indent=2) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
