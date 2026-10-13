"""Opt-in extension of a rendered agent-compose project, preserving other agents.

Supply a rendered config and an output path; this never applies it to a daemon.
The caller owns those files, which may contain rendered secrets: output is 0600.
"""

import argparse
import os
from pathlib import Path

import yaml

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--input", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--snapshot-root", type=Path, required=True)
parser.add_argument("--memory-mb", type=int, default=512)
parser.add_argument("--rss-mb", type=int, default=2048)
parser.add_argument("--temp-gb", type=int, default=8)
args = parser.parse_args()
if args.input.resolve() == args.output.resolve() or args.output.exists():
    parser.error("output must be a new file")
if not args.snapshot_root.is_absolute() or not args.snapshot_root.is_dir() or args.snapshot_root.is_symlink():
    parser.error("snapshot-root must be an existing absolute operator-owned directory")
if args.memory_mb < 64 or args.rss_mb < args.memory_mb or args.temp_gb < 1:
    parser.error("invalid resource budget")
project = yaml.safe_load(args.input.read_text())
agent = project["agents"]["netflow-processor"]
agent.setdefault("env", {}).update({"NETFLOW_BULK_ROOT": "/app/netflow-bulk-inputs", "NETFLOW_BULK_MEMORY_MB": str(args.memory_mb), "NETFLOW_BULK_THREADS": "1", "NETFLOW_BULK_RSS_BYTES": str(args.rss_mb * 1024**2), "NETFLOW_BULK_TEMP_BYTES": str(args.temp_gb * 1024**3), "NETFLOW_BULK_DISK_RESERVE_BYTES": str(2 * 1024**3)})
if any(mount.get("target") == "/app/netflow-bulk-inputs" for mount in agent.get("volumes", [])):
    parser.error("bulk target is already mounted")
agent.setdefault("volumes", []).append({"type": "bind", "source": str(args.snapshot_root), "target": "/app/netflow-bulk-inputs", "read_only": True})
fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as stream:
    yaml.safe_dump(project, stream, allow_unicode=True, sort_keys=False)
