"""Offline sealing, deterministic synthetic generation and bounded benchmarks."""

import argparse
import csv
import json
import os
import platform
import random
import resource
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any

import duckdb
import pyarrow  # type: ignore[import-untyped]

from app.netflow_bulk.contracts import Budget, BulkError, Filter, Member
from app.netflow_bulk.engine import compute, normalize_file
from app.netflow_bulk.storage import atomic_json, file_hash, seal

HEADER = [
    "IP_SRC_ADDR",
    "IP_DST_ADDR",
    "PROTOCOL",
    "L4_SRC_PORT",
    "L4_DST_PORT",
    "start_time",
    "end_time",
    "EXPORTER",
    "OBSERVATION_POINT",
    "OBSERVATION_DOMAIN_ID",
    "SAMPLING_MODE",
    "SAMPLING_RATE",
    "NAT",
    "note",
]


def generate(
    root: Path,
    *,
    byte_target: int,
    files: int,
    seed: int,
    width: int,
    ipv6: float,
    duplicate: float,
    objects: int,
    peers: int,
    hotspot: float,
    overlap: float,
) -> dict[str, Any]:
    if root.exists() and any(root.iterdir()):
        raise BulkError("bulk_generator_destination_not_empty")
    if not (
        1 <= files <= 4096
        and 256 <= width <= 32000
        and byte_target > 0
        and objects > 0
        and peers > 0
        and all(0 <= rate < 1 for rate in (ipv6, duplicate, hotspot, overlap))
    ):
        raise BulkError("bulk_generator_invalid_options")
    root.mkdir(parents=True, exist_ok=True)
    count = size = 0
    per_file = max(1, byte_target // files)
    results: list[dict[str, Any]] = []
    for number in range(files):
        path = root / f"synthetic-{number:04d}.csv"
        rows = 0
        written = 0
        offset = int(number * per_file / width * (1 - overlap))
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            written += writer.writerow(HEADER)
            while written < per_file:
                event = int((offset + rows) * (1 - duplicate))
                rng = random.Random(seed + event)
                local = 1 if rng.random() < hotspot else event % objects + 1
                peer = (event * 104729) % peers + 1
                v6 = rng.random() < ipv6
                src = (
                    f"2001:db8:{local >> 32:x}:{(local >> 16) & 65535:x}::{local & 65535:x}"
                    if v6
                    else f"198.18.{(local // 254) % 256}.{local % 254 + 1}"
                )
                dst = f"2001:db8:ffff:{peer >> 16:x}::{peer & 65535:x}"
                # Random payload makes capacity evidence insensitive to implausible
                # all-equal rows or exceptional compression; duplicates reuse it.
                payload = rng.randbytes(max(1, (width - 210) // 2)).hex()
                row = [
                    src,
                    dst,
                    "6" if event % 3 else "17",
                    str(1 + event % 65535),
                    str(1 + peer % 65535),
                    f"2026-01-01T00:{event // 60 % 60:02d}:{event % 60:02d}Z",
                    f"2026-01-01T01:{event // 60 % 60:02d}:{event % 60:02d}Z",
                    f"exporter-{event % 4}",
                    f"point-{event % 3}",
                    str(event % 4),
                    "unsampled",
                    "1",
                    "unknown",
                    payload,
                ]
                written += writer.writerow(row)
                rows += 1
        actual = path.stat().st_size
        results.append(
            {
                "name": path.name,
                "bytes": actual,
                "rows": rows,
                "sha256": file_hash(path),
            }
        )
        size += actual
        count += rows
    return {
        "seed": seed,
        "bytes": size,
        "rows": count,
        "row_width_target": width,
        "ipv6_rate": ipv6,
        "duplicate_rate": duplicate,
        "objects_target": objects,
        "peers_target": peers,
        "hotspot_rate": hotspot,
        "overlap_rate": overlap,
        "files": results,
    }


def benchmark(
    root: Path, *, byte_target: int, limits: Budget, options: dict[str, Any]
) -> dict[str, Any]:
    if root.exists() and any(root.iterdir()):
        raise BulkError("bulk_benchmark_destination_not_empty")
    root.mkdir(parents=True, exist_ok=True)
    # Raw + duplicated normalization fields + work DB + worst-case spill/results.
    # This is a conservative admission estimate, not a measured amplification.
    required = byte_target * 10 + limits.temp_bytes + limits.disk_reserve_bytes
    free = shutil.disk_usage(root).free
    if free < required:
        preflight = {
            "status": "NOT_RUN",
            "reason": "disk_preflight",
            "target_bytes": byte_target,
            "free_bytes": free,
            "estimated_required_bytes": required,
            "TB_acceptance": "TB 验收未执行",
        }
        atomic_json(root / "benchmark.json", preflight)
        return preflight
    started = time.monotonic()
    metrics: dict[str, Any] = {
        "peak_rss_bytes": 0,
        "sampled_peak_temp_bytes": 0,
        "peak_work_bytes": 0,
    }
    stopped = threading.Event()
    errors: list[str] = []

    def pulse() -> None:
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss = int(value if sys.platform == "darwin" else value * 1024)
        metrics["peak_rss_bytes"] = max(metrics["peak_rss_bytes"], rss)
        if rss > limits.rss_bytes:
            raise BulkError("bulk_rss_budget")
        if time.monotonic() - started > limits.timeout_seconds:
            raise BulkError("bulk_timeout")
        if shutil.disk_usage(root).free < limits.disk_reserve_bytes:
            raise BulkError("bulk_disk_budget")
        if errors:
            raise BulkError(errors[0])

    def monitor() -> None:
        while not stopped.wait(0.5):
            try:
                pulse()
                sizes = [
                    (p, p.stat().st_size)
                    for p in (root / "result").rglob("*")
                    if p.is_file()
                ]
                metrics["sampled_peak_temp_bytes"] = max(
                    metrics["sampled_peak_temp_bytes"],
                    sum(size for path, size in sizes if "spill" in path.parts),
                )
                metrics["peak_work_bytes"] = max(
                    metrics["peak_work_bytes"], sum(size for _, size in sizes)
                )
            except FileNotFoundError:
                continue  # Spill files may disappear between readdir and stat.
            except BulkError as error:
                errors.append(error.code)
                return

    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    report: dict[str, Any] = {
        "status": "RUNNING",
        "target_bytes": byte_target,
        "hardware": {
            "machine": platform.machine(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
        },
        "versions": {
            "python": platform.python_version(),
            "duckdb": duckdb.__version__,
            "pyarrow": pyarrow.__version__,
        },
        "budget": limits.model_dump(),
        "TB_acceptance": "TB 验收未执行",
        "scope": "offline engine; PostgreSQL/API publication measured separately",
        "code_sha256": {
            name: file_hash(Path(__file__).parent / name)
            for name in ("__main__.py", "engine.py", "contracts.py", "storage.py")
        },
    }
    try:
        generated = generate(root / "input", byte_target=byte_target, **options)
        report["input"] = generated
        report["generation_seconds"] = time.monotonic() - started
        parsed = time.monotonic()
        parsed_rows = read_bytes = 0
        for item in generated["files"]:
            member = Member(
                sha256=item["sha256"], size=item["bytes"], name=item["name"]
            )

            def checkpoint(
                value: dict[str, Any], member_id: str = member.sha256
            ) -> None:
                target = root / "checkpoints" / member_id
                target.mkdir(parents=True, exist_ok=True)
                atomic_json(target / f"{value['ordinal']:08d}.json", value)

            result = normalize_file(
                root / "input" / item["name"],
                member,
                root / "normalized" / member.sha256,
                limits,
                checkpoint=checkpoint,
                committed=lambda _: None,
                pulse=pulse,
            )
            parsed_rows += result["raw"]
            read_bytes += result["read_bytes"]
        report["normalization_seconds"] = time.monotonic() - parsed
        report["read_bytes"], report["parsed_rows"] = read_bytes, parsed_rows
        report["result"] = compute(
            root / "normalized", root / "result", Filter(), limits, pulse=pulse
        )
        refilter = time.monotonic()
        # A changed filter only receives the Parquet location, never input paths.
        zero = compute(
            root / "normalized",
            root / "refilter",
            Filter(protocols=[1]),
            limits,
            pulse=pulse,
        )
        report["refilter_seconds"] = time.monotonic() - refilter
        report["refilter"] = {
            "counts": zero["counts"],
            "raw_csv_read_bytes": 0,
            "csv_parser_calls": 0,
        }
        report["status"] = "PASS"
        report["processing_seconds"] = time.monotonic() - parsed
        report["rows_per_second"] = parsed_rows / report["processing_seconds"]
        report["normalized_bytes"] = sum(
            path.stat().st_size for path in (root / "normalized").rglob("*.parquet")
        )
        report["result_bytes"] = sum(
            item["size"] for item in report["result"]["files"].values()
        )
    except Exception as error:
        report["status"] = "FAIL"
        report["error"] = (
            error.code if isinstance(error, BulkError) else type(error).__name__
        )
        raise
    finally:
        stopped.set()
        watcher.join(timeout=2)
        report["metrics"] = metrics
        report["end_to_end_seconds_including_generation"] = time.monotonic() - started
        atomic_json(root / "benchmark.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sealing = sub.add_parser("seal")
    sealing.add_argument("--source", type=Path, required=True)
    sealing.add_argument("--root", type=Path, required=True)
    sealing.add_argument("--tenant", required=True)
    sealing.add_argument("--project", required=True)
    sealing.add_argument("--source-id", required=True)
    sealing.add_argument(
        "--encoding", choices=["utf-8-sig", "gb18030"], default="utf-8-sig"
    )
    sealing.add_argument("--timezone", default="UTC")
    for command in ("generate", "benchmark"):
        child = sub.add_parser(command)
        child.add_argument("--output", type=Path, required=True)
        child.add_argument("--bytes", type=int, required=True)
        child.add_argument("--files", type=int, default=4)
        child.add_argument("--seed", type=int, default=304)
        child.add_argument("--width", type=int, default=1024)
        child.add_argument("--ipv6", type=float, default=0.35)
        child.add_argument("--duplicate", type=float, default=0.1)
        child.add_argument("--objects", type=int, default=100000)
        child.add_argument("--peers", type=int, default=500000)
        child.add_argument("--hotspot", type=float, default=0.1)
        child.add_argument("--overlap", type=float, default=0.1)
        if command == "benchmark":
            child.add_argument("--memory-mb", type=int, default=256)
            child.add_argument("--threads", type=int, default=1)
            child.add_argument("--rss-mb", type=int, default=1024)
            child.add_argument("--temp-gb", type=int, default=8)
            child.add_argument("--reserve-gb", type=int, default=20)
    args = parser.parse_args()
    if args.command == "seal":
        identity, ready = seal(
            args.source,
            args.root,
            tenant=args.tenant,
            project=args.project,
            source_id=args.source_id,
            encoding=args.encoding,
            timezone=args.timezone,
        )
        print(  # noqa: T201 - CLI result
            json.dumps(
                {
                    "ready_id": identity,
                    "source_id": ready.source_id,
                    "files": len(ready.files),
                }
            )
        )
        return 0
    options = {
        name: getattr(args, name)
        for name in (
            "files",
            "seed",
            "width",
            "ipv6",
            "duplicate",
            "objects",
            "peers",
            "hotspot",
            "overlap",
        )
    }
    if args.command == "generate":
        result = generate(args.output, byte_target=args.bytes, **options)
        print(json.dumps(result))  # noqa: T201 - CLI result
        return 0
    result = benchmark(
        args.output,
        byte_target=args.bytes,
        limits=Budget(
            memory_mb=args.memory_mb,
            threads=args.threads,
            rss_bytes=args.rss_mb * 1024**2,
            temp_bytes=args.temp_gb * 1024**3,
            disk_reserve_bytes=args.reserve_gb * 1024**3,
        ),
        options=options,
    )
    print(  # noqa: T201 - CLI result
        json.dumps(
            {"status": result["status"], "report": str(args.output / "benchmark.json")}
        )
    )
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
