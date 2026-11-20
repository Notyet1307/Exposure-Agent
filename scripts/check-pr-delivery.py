#!/usr/bin/env python3
"""Deterministic PR delivery guardrail checks (project-agnostic, Python 3.9+ stdlib only).

Checks:
1. PR body / comment text contains no host local paths, Cindy host identifiers, or private env paths.
2. Frozen verification manifest (`frozen-assets.json`) matches the target HEAD SHA and has intact asset hashes.

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


def check_frozen_manifest(manifest_path: Path, expected_head: str) -> list[str]:
    errors: list[str] = []
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return ["Manifest root must be a JSON object"]

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
    return errors


def run_self_test() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        clean_body = "## Why\nFix flow.\n\n## Verification\n- Evidence ID: run-20261120T000000Z (`PASS`)\n"
        leaky_body = (
            "Screenshot at ~/ops/tasks/demo/run-1/ and /Users/alice/dev/app/foo.png\n"
        )
        cindy_body = "Bot bot_1794477732137_7pjsr4 in CindyGlobal\n"

        clean_ok = len(check_pr_body_text(clean_body)) == 0
        leaky_caught = len(check_pr_body_text(leaky_body)) >= 2
        cindy_caught = len(check_pr_body_text(cindy_body)) >= 2

        head_a = "a" * 40
        head_b = "b" * 40
        manifest = root / "frozen-assets.json"
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
        manifest_match_ok = len(check_frozen_manifest(manifest, head_a)) == 0
        manifest_stale_caught = len(check_frozen_manifest(manifest, head_b)) == 1

    passed = all(
        (
            clean_ok,
            leaky_caught,
            cindy_caught,
            manifest_match_ok,
            manifest_stale_caught,
        )
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "clean_body_pass": clean_ok,
        "local_path_leak_caught": leaky_caught,
        "cindy_id_leak_caught": cindy_caught,
        "manifest_head_match_pass": manifest_match_ok,
        "manifest_stale_head_caught": manifest_stale_caught,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check PR delivery body for host-path leaks and verify frozen manifest HEAD binding."
    )
    parser.add_argument(
        "--pr-body",
        help="Path to PR body/comment text file, or '-' to read from stdin.",
    )
    parser.add_argument(
        "--frozen-manifest",
        type=Path,
        help="Path to frozen-assets.json produced by runtime verification.",
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
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "PASS" else 1

    if not args.pr_body and not args.frozen_manifest:
        parser.error(
            "Specify at least one of --pr-body, --frozen-manifest, or --self-test"
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
            print(json.dumps({"status": "BLOCKED", "error": str(exc)}, indent=2))
            return 2

        try:
            findings = check_pr_body_text(body_text, args.extra_forbidden_regex)
        except re.error as exc:
            print(
                json.dumps(
                    {"status": "BLOCKED", "error": f"Invalid regex: {exc}"}, indent=2
                )
            )
            return 2

        checks["pr_body"] = {
            "status": "PASS" if not findings else "FAIL",
            "findings": findings,
        }
        if findings:
            failed = True

    if args.frozen_manifest:
        if not args.frozen_manifest.is_file():
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "error": f"Manifest not found: {args.frozen_manifest}",
                    },
                    indent=2,
                )
            )
            return 2
        try:
            expected_head = resolve_head_sha(args.head, args.repo)
            manifest_errors = check_frozen_manifest(args.frozen_manifest, expected_head)
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            subprocess.CalledProcessError,
        ) as exc:
            print(json.dumps({"status": "BLOCKED", "error": str(exc)}, indent=2))
            return 2

        checks["frozen_manifest"] = {
            "status": "PASS" if not manifest_errors else "FAIL",
            "expected_head": expected_head,
            "errors": manifest_errors,
        }
        if manifest_errors:
            failed = True

    report["checks"] = checks
    report["status"] = "FAIL" if failed else "PASS"
    print(json.dumps(report, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
