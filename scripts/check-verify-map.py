#!/usr/bin/env python3
"""Project-agnostic verification skill & feature-map hygiene checker.

Uses only Python 3.9+ standard library. Auto-discovers `.pi/skills/verify*` or
`.claude/skills/verify*` inside a repository and verifies:
  1. `SKILL.md` and `features/README.md` exist.
  2. Bi-directional index coverage between `features/README.md` and `features/*.md`.
  3. Relative markdown links inside `SKILL.md` and `features/*.md` resolve on disk.
  4. Backticked repository file paths in `features/*.md` still exist on disk.
  5. Advisory drift stats: `NOT_RUN` counts and product commits since last skill edit.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
CODE_PATH_RE = re.compile(
    r"`((?:src|app|apps|packages|backend|frontend|scripts|docs|tests|test|\.pi|\.claude|\.pstack)/[A-Za-z0-9_./:-]+)`"
)
NOT_RUN_RE = re.compile(r"\bNOT_RUN\b")


def _out(line: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    stream.write(line + "\n")


def _git_top_level(start: Path) -> Path | None:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return Path(out).resolve() if out else None
    except Exception:
        return None


def resolve_default_repo() -> Path:
    script_repo = _git_top_level(Path(__file__).resolve().parent)
    if script_repo is not None:
        return script_repo
    cwd_repo = _git_top_level(Path.cwd())
    if cwd_repo is not None:
        return cwd_repo
    return Path.cwd().resolve()


def discover_skill_dirs(repo: Path) -> list[Path]:
    candidates: list[Path] = []
    for parent_rel in (".pi/skills", ".claude/skills"):
        parent = repo / parent_rel
        if not parent.is_dir():
            continue
        for child in sorted(parent.iterdir()):
            if not child.is_dir():
                continue
            if child.name == "verify" or child.name.startswith("verify-"):
                if (child / "SKILL.md").is_file() or (child / "features").is_dir():
                    candidates.append(child)
    return candidates


def _check_relative_links(md_path: Path, repo: Path) -> list[dict[str, str]]:
    broken: list[dict[str, str]] = []
    text = md_path.read_text(encoding="utf-8")
    for m in LINK_RE.finditer(text):
        raw_target = m.group(1).strip()
        target = raw_target.split("#", 1)[0].strip()
        if not target or target.startswith(
            ("http://", "https://", "mailto:", "file://")
        ):
            continue
        resolved = (md_path.parent / target).resolve()
        if not resolved.exists():
            broken.append(
                {
                    "file": str(md_path.relative_to(repo)),
                    "link": raw_target,
                }
            )
    return broken


def _check_backtick_paths(md_path: Path, repo: Path) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    seen: set[str] = set()
    text = md_path.read_text(encoding="utf-8")
    for m in CODE_PATH_RE.finditer(text):
        raw = m.group(1)
        clean = raw.split("::", 1)[0]
        if any(ch in clean for ch in ("*", "<", ">", "{", "}")):
            continue
        if clean.endswith("/"):
            continue
        if clean in seen:
            continue
        seen.add(clean)
        if not (repo / clean).exists():
            missing.append(
                {
                    "file": str(md_path.relative_to(repo)),
                    "path": clean,
                }
            )
    return missing


def _git_drift_info(repo: Path, skill_dir: Path) -> dict[str, Any]:
    rel_skill = str(skill_dir.relative_to(repo))
    try:
        last_line = subprocess.check_output(
            ["git", "-C", str(repo), "log", "-1", "--format=%H %cI", "--", rel_skill],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return {"git_available": False}
    if not last_line:
        return {
            "git_available": True,
            "last_skill_commit": None,
            "commits_since": None,
        }
    parts = last_line.split(" ", 1)
    commit_sha = parts[0]
    commit_date = parts[1] if len(parts) > 1 else ""
    try:
        count_raw = subprocess.check_output(
            [
                "git",
                "-C",
                str(repo),
                "rev-list",
                "--count",
                f"{commit_sha}..HEAD",
                "--",
                ".",
                f":(exclude){rel_skill}",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        commits_since: int | None = int(count_raw)
    except Exception:
        commits_since = None
    return {
        "git_available": True,
        "last_skill_commit": commit_sha,
        "last_skill_date": commit_date,
        "non_skill_commits_since": commits_since,
    }


def inspect_skill(
    repo: Path, skill_dir: Path, check_code_paths: bool = True
) -> dict[str, Any]:
    errors: list[str] = []
    skill_md = skill_dir / "SKILL.md"
    features_dir = skill_dir / "features"
    readme_md = features_dir / "README.md"

    if not skill_md.is_file():
        errors.append(f"Missing SKILL.md at {skill_md.relative_to(repo)}")
    if not features_dir.is_dir():
        errors.append(
            f"Missing features/ directory at {features_dir.relative_to(repo)}"
        )
    if not readme_md.is_file():
        errors.append(f"Missing features/README.md at {readme_md.relative_to(repo)}")

    disk_features: list[str] = []
    linked_features: list[str] = []
    duplicate_links: list[str] = []
    unindexed: list[str] = []
    missing_from_disk: list[str] = []
    broken_links: list[dict[str, str]] = []
    missing_code_paths: list[dict[str, str]] = []
    not_run_by_file: dict[str, int] = {}

    if skill_md.is_file():
        broken_links.extend(_check_relative_links(skill_md, repo))

    if features_dir.is_dir():
        disk_features = sorted(
            p.name for p in features_dir.glob("*.md") if p.name != "README.md"
        )
        if readme_md.is_file():
            readme_text = readme_md.read_text(encoding="utf-8")
            seen_links: set[str] = set()
            for m in LINK_RE.finditer(readme_text):
                target = m.group(1).strip().split("#", 1)[0]
                if not target.endswith(".md") or "/" in target:
                    continue
                if target == "README.md":
                    continue
                if target in seen_links and target not in duplicate_links:
                    duplicate_links.append(target)
                seen_links.add(target)
                linked_features.append(target)

            disk_set = set(disk_features)
            link_set = set(linked_features)
            unindexed = sorted(disk_set - link_set)
            missing_from_disk = sorted(link_set - disk_set)

            if unindexed:
                errors.append(f"Unindexed feature files: {', '.join(unindexed)}")
            if missing_from_disk:
                errors.append(
                    f"README links missing on disk: {', '.join(missing_from_disk)}"
                )
            if duplicate_links:
                errors.append(
                    f"Duplicate feature links in README.md: {', '.join(duplicate_links)}"
                )

        for md_file in sorted(features_dir.glob("*.md")):
            broken_links.extend(_check_relative_links(md_file, repo))
            if check_code_paths:
                missing_code_paths.extend(_check_backtick_paths(md_file, repo))
            cnt = len(NOT_RUN_RE.findall(md_file.read_text(encoding="utf-8")))
            not_run_by_file[md_file.name] = cnt

    if broken_links:
        errors.append(f"Broken relative markdown links: {len(broken_links)}")
    if missing_code_paths:
        errors.append(f"Missing referenced repo paths: {len(missing_code_paths)}")

    drift = _git_drift_info(repo, skill_dir)
    return {
        "status": "PASS" if not errors else "FAIL",
        "repo": str(repo),
        "skill_dir": str(skill_dir.relative_to(repo)),
        "feature_count": len(disk_features),
        "features": disk_features,
        "unindexed": unindexed,
        "missing_from_disk": missing_from_disk,
        "duplicate_links": duplicate_links,
        "broken_links": broken_links,
        "missing_code_paths": missing_code_paths,
        "not_run_total": sum(not_run_by_file.values()),
        "not_run_by_file": not_run_by_file,
        "drift": drift,
        "errors": errors,
    }


def run_self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="check-verify-map-selftest-") as tmp:
        root = Path(tmp).resolve()
        (root / "src").mkdir(parents=True)
        (root / "src/app.ts").write_text("export const ok = true;\n", encoding="utf-8")
        skill = root / ".pi/skills/verify"
        features = skill / "features"
        features.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "# Verify\nSee [features](features/README.md).\n", encoding="utf-8"
        )
        (features / "README.md").write_text(
            "# Features\n- [Home](home.md)\n", encoding="utf-8"
        )
        (features / "home.md").write_text(
            "# Home\nSource: `src/app.ts`. Status: NOT_RUN.\n", encoding="utf-8"
        )

        r1 = inspect_skill(root, skill)
        if r1["status"] != "PASS" or r1["not_run_total"] != 1:
            raise AssertionError(f"Expected PASS with 1 NOT_RUN, got {r1}")

        (features / "extra.md").write_text("# Extra\n", encoding="utf-8")
        r2 = inspect_skill(root, skill)
        if r2["status"] != "FAIL" or r2["unindexed"] != ["extra.md"]:
            raise AssertionError(f"Expected unindexed failure, got {r2}")
        (features / "extra.md").unlink()

        (features / "home.md").write_text(
            "# Home\nSee [missing](nope.md).\n", encoding="utf-8"
        )
        r3 = inspect_skill(root, skill)
        if r3["status"] != "FAIL" or len(r3["broken_links"]) != 1:
            raise AssertionError(f"Expected broken_links failure, got {r3}")

        (features / "home.md").write_text(
            "# Home\nSource: `src/deleted.ts`.\n", encoding="utf-8"
        )
        r4 = inspect_skill(root, skill)
        if r4["status"] != "FAIL" or len(r4["missing_code_paths"]) != 1:
            raise AssertionError(f"Expected missing_code_paths failure, got {r4}")

    _out("SELF_TEST PASS (4/4 cases)")
    return 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check verification skill feature-map hygiene and referenced paths."
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="Target repository root (defaults to git root of script or cwd).",
    )
    parser.add_argument(
        "--skill-dir",
        type=Path,
        default=None,
        help="Explicit verification skill directory (relative to --repo or absolute).",
    )
    parser.add_argument(
        "--no-code-paths",
        action="store_true",
        help="Skip verifying backticked repository file paths in features/*.md.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit full JSON report.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run built-in unit checks on a temporary synthetic repository.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    if args.self_test:
        return run_self_test()

    repo = args.repo.resolve() if args.repo else resolve_default_repo()
    if args.skill_dir:
        sd = args.skill_dir if args.skill_dir.is_absolute() else (repo / args.skill_dir)
        skill_dirs = [sd.resolve()]
    else:
        skill_dirs = discover_skill_dirs(repo)

    if not skill_dirs:
        _out(
            f"BLOCKED: No verification skill found under {repo}/(.pi|.claude)/skills/verify*",
            err=True,
        )
        return 2
    if len(skill_dirs) > 1:
        rels = [str(d.relative_to(repo)) for d in skill_dirs]
        _out(
            f"BLOCKED: Multiple verification skills found ({', '.join(rels)}); pass --skill-dir",
            err=True,
        )
        return 2

    report = inspect_skill(repo, skill_dirs[0], check_code_paths=not args.no_code_paths)
    if args.json:
        _out(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _out(
            f"STATUS={report['status']} skill={report['skill_dir']} "
            f"features={report['feature_count']} not_run={report['not_run_total']}"
        )
        drift = report["drift"]
        if isinstance(drift, dict) and drift.get("git_available"):
            _out(
                f"DRIFT last_skill_commit={drift.get('last_skill_commit')} "
                f"date={drift.get('last_skill_date')} "
                f"non_skill_commits_since={drift.get('non_skill_commits_since')}"
            )
        for item in report["broken_links"]:
            _out(f"  BROKEN_LINK {item['file']} -> {item['link']}")
        for item in report["missing_code_paths"]:
            _out(f"  MISSING_PATH {item['file']} -> {item['path']}")
        for err in report["errors"]:
            _out(f"  ERROR {err}")

    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
