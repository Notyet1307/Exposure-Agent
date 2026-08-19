#!/usr/bin/env python3
"""Fail when repository context regresses into known stale states."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve().relative_to(ROOT)
FORBIDDEN_DIRS = ("investigations", "docs/research", "docs/acceptance")
ATTRIBUTION_FILES = {
    Path("docs/adr/0001-use-full-stack-fastapi-template.md"),
    Path("THIRD_PARTY_NOTICES"),
    Path("LICENSE"),
}
TEMPLATE_IDENTITIES = (
    "Full Stack FastAPI Project",
    "FastAPI Project",
    "fastapi-full-stack-template",
    "Full Stack FastAPI Template",
    "FastAPI Template",
)
BAD_MIGRATION_GUIDANCE = (
    "If you don't want to use migrations",
    "remove the revision files",
    "delete the Alembic revisions",
)
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\n]+)\)")
MARKDOWN_REFERENCE = re.compile(r"^\s*\[[^\]]+\]:\s*(\S+)", re.MULTILINE)
OLD_COMPOSE_COMMAND = re.compile(r"(?<![-\w])docker-compose(?=\s|$)")


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [Path(os.fsdecode(item)) for item in result.stdout.split(b"\0") if item]


def text_content(path: Path) -> str | None:
    data = (ROOT / path).read_bytes()
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def markdown_target(raw: str) -> str:
    target = raw.strip()
    if target.startswith("<") and ">" in target:
        return target[1 : target.index(">")]
    return target.split(maxsplit=1)[0]


def is_external(target: str) -> bool:
    return target.startswith(("#", "http://", "https://", "mailto:", "tel:"))


def check_markdown_links(path: Path, text: str, errors: list[str]) -> None:
    matches = list(MARKDOWN_LINK.finditer(text)) + list(
        MARKDOWN_REFERENCE.finditer(text)
    )
    for match in matches:
        target = markdown_target(match.group(1))
        if not target or is_external(target):
            continue
        local = unquote(target.split("#", 1)[0].split("?", 1)[0])
        if not local:
            continue
        resolved = (
            ROOT / local.lstrip("/")
            if local.startswith("/")
            else ROOT / path.parent / local
        )
        if not resolved.exists():
            line = text.count("\n", 0, match.start()) + 1
            errors.append(f"{path}:{line}: missing Markdown target {target}")


def main() -> int:
    errors: list[str] = []
    files = tracked_files()
    text_files: dict[Path, str] = {}

    for path in files:
        name = path.name
        if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
            errors.append(f"{path}: tracked runtime environment file")
        path_text = path.as_posix()
        for forbidden in FORBIDDEN_DIRS:
            if path_text == forbidden or path_text.startswith(f"{forbidden}/"):
                errors.append(f"{path}: historical process material is forbidden")

        text = text_content(path)
        if text is not None:
            text_files[path] = text

    for path, text in text_files.items():
        if path != SELF and path not in ATTRIBUTION_FILES:
            for identity in TEMPLATE_IDENTITIES:
                if identity in text:
                    errors.append(f"{path}: template identity remains: {identity}")
        if path != SELF and OLD_COMPOSE_COMMAND.search(text):
            errors.append(f"{path}: legacy docker-compose command remains")
        if path != SELF:
            for guidance in BAD_MIGRATION_GUIDANCE:
                if guidance in text:
                    errors.append(f"{path}: Alembic history deletion guidance remains")
        if path.suffix.lower() == ".md":
            check_markdown_links(path, text, errors)

    agents = text_files.get(Path("AGENTS.md"), "")
    default_exclusions = re.search(
        r"^## 默认不读取\s*$\n(.*?)(?=^## |\Z)", agents, re.MULTILINE | re.DOTALL
    )
    if default_exclusions is None:
        errors.append("AGENTS.md: missing default context exclusions")
    else:
        section = default_exclusions.group(1)
        for required in ("docs/product/target-state.md", "历史 Evidence"):
            if required not in section:
                errors.append(f"AGENTS.md: default exclusions omit {required}")

    if errors:
        print("context hygiene failed:")
        for error in sorted(set(errors)):
            print(f"- {error}")
        return 1

    print(f"context hygiene passed ({len(files)} tracked files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
