import json
import shutil
import sys
from collections import namedtuple
from pathlib import Path
from typing import Any

import pytest

from app.netflow_bulk import __main__ as cli
from app.netflow_bulk.contracts import Budget, BulkError

OPTIONS: dict[str, Any] = {
    "files": 2,
    "seed": 304,
    "width": 256,
    "ipv6": 0.25,
    "duplicate": 0.1,
    "objects": 20,
    "peers": 30,
    "hotspot": 0.1,
    "overlap": 0.1,
}


def test_generate_is_deterministic_and_rejects_nonempty_destination(
    tmp_path: Path,
) -> None:
    first = cli.generate(tmp_path / "first", byte_target=2048, **OPTIONS)
    second = cli.generate(tmp_path / "second", byte_target=2048, **OPTIONS)
    assert first["rows"] == second["rows"] > 0
    assert [item["sha256"] for item in first["files"]] == [
        item["sha256"] for item in second["files"]
    ]
    with pytest.raises(BulkError, match="bulk_generator_destination_not_empty"):
        cli.generate(tmp_path / "first", byte_target=2048, **OPTIONS)


@pytest.mark.parametrize("field,value", [("files", 0), ("width", 255), ("ipv6", 1)])
def test_generate_rejects_invalid_bounds(
    tmp_path: Path, field: str, value: int
) -> None:
    with pytest.raises(BulkError, match="bulk_generator_invalid_options"):
        cli.generate(tmp_path / field, byte_target=1024, **(OPTIONS | {field: value}))


def test_benchmark_runs_real_small_normalization_and_refilter(tmp_path: Path) -> None:
    result = cli.benchmark(
        tmp_path / "benchmark",
        byte_target=4096,
        limits=Budget(
            memory_mb=64,
            threads=1,
            temp_bytes=1024**2,
            disk_reserve_bytes=0,
            rss_bytes=4 * 1024**3,
            timeout_seconds=30,
            shard_rows=2,
        ),
        options=OPTIONS,
    )
    assert result["status"] == "PASS"
    assert result["parsed_rows"] == result["result"]["counts"]["raw"]
    assert result["refilter"]["counts"]["unique"] == 0
    assert (
        json.loads((tmp_path / "benchmark" / "benchmark.json").read_text())["status"]
        == "PASS"
    )


def test_benchmark_records_preflight_and_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    usage = namedtuple("usage", "total used free")
    original_disk_usage = shutil.disk_usage
    module_shutil: Any = cli.__dict__["shutil"]
    monkeypatch.setattr(module_shutil, "disk_usage", lambda _: usage(1, 1, 0))
    skipped = cli.benchmark(
        tmp_path / "skipped",
        byte_target=1024,
        limits=Budget(temp_bytes=1024**2, disk_reserve_bytes=0),
        options=OPTIONS,
    )
    assert skipped["status"] == "NOT_RUN"
    assert (
        json.loads((tmp_path / "skipped" / "benchmark.json").read_text())["reason"]
        == "disk_preflight"
    )
    monkeypatch.setattr(module_shutil, "disk_usage", original_disk_usage)
    monkeypatch.setattr(
        cli,
        "generate",
        lambda *args, **kwargs: (_ for _ in ()).throw(BulkError("synthetic_no_space")),
    )
    with pytest.raises(BulkError, match="synthetic_no_space"):
        cli.benchmark(
            tmp_path / "failed",
            byte_target=1024,
            limits=Budget(temp_bytes=1024**2, disk_reserve_bytes=0),
            options=OPTIONS,
        )
    failed = json.loads((tmp_path / "failed" / "benchmark.json").read_text())
    assert failed["status"] == "FAIL" and failed["error"] == "synthetic_no_space"


def test_main_dispatches_generate_seal_and_not_run_benchmark(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    generated = tmp_path / "generated"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bulk",
            "generate",
            "--output",
            str(generated),
            "--bytes",
            "1024",
            "--files",
            "1",
            "--width",
            "256",
        ],
    )
    assert cli.main() == 0
    assert (
        json.loads(capsys.readouterr().out)["files"][0]["name"] == "synthetic-0000.csv"
    )
    source, root = tmp_path / "source", tmp_path / "snapshots"
    source.mkdir()
    (source / "input.csv").write_text(
        "IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n192.0.2.1,2001:db8::1,6,443,443\n"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bulk",
            "seal",
            "--source",
            str(source),
            "--root",
            str(root),
            "--tenant",
            "00000000-0000-0000-0000-000000000001",
            "--project",
            "00000000-0000-0000-0000-000000000002",
            "--source-id",
            "fixture",
        ],
    )
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)["files"] == 1
    monkeypatch.setattr(cli, "benchmark", lambda *args, **kwargs: {"status": "NOT_RUN"})
    monkeypatch.setattr(
        sys,
        "argv",
        ["bulk", "benchmark", "--output", str(tmp_path / "not-run"), "--bytes", "1024"],
    )
    assert cli.main() == 2
    assert json.loads(capsys.readouterr().out)["status"] == "NOT_RUN"


def test_benchmark_samples_work_files_and_rejects_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import resource
    import threading

    sampled = threading.Event()
    probe_ready = threading.Event()
    calls = 0
    original_usage = resource.getrusage
    from app.netflow_bulk.engine import compute as original_compute

    def usage(who: int) -> Any:
        nonlocal calls
        if (
            probe_ready.is_set()
            and threading.current_thread() is not threading.main_thread()
        ):
            calls += 1
            if calls >= 2:
                sampled.set()  # The first sampling cycle has finished.
        return original_usage(who)

    def measured(root: Path, output: Path, *args: Any, **kwargs: Any) -> Any:
        if output.name == "result":
            spill = output / "spill"
            spill.mkdir(parents=True)
            (spill / "synthetic-probe.tmp").write_bytes(b"x" * 128)
            probe_ready.set()
            assert sampled.wait(5), "resource sampler never ran"
        return original_compute(root, output, *args, **kwargs)

    monkeypatch.setattr(resource, "getrusage", usage)
    monkeypatch.setattr(cli, "compute", measured)
    root = tmp_path / "monitored"
    limits = Budget(
        memory_mb=64,
        threads=1,
        temp_bytes=1024**2,
        disk_reserve_bytes=0,
        rss_bytes=4 * 1024**3,
    )
    result = cli.benchmark(root, byte_target=2048, limits=limits, options=OPTIONS)
    assert result["status"] == "PASS"
    assert result["metrics"]["sampled_peak_temp_bytes"] >= 128
    assert result["metrics"]["peak_rss_bytes"] > 0
    with pytest.raises(BulkError, match="bulk_benchmark_destination_not_empty"):
        cli.benchmark(root, byte_target=2048, limits=limits, options=OPTIONS)


def test_benchmark_propagates_resource_monitor_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import resource
    import threading
    from types import SimpleNamespace

    entered = threading.Event()
    watcher: list[threading.Thread] = []
    original_usage = resource.getrusage
    original_generate = cli.generate

    def over_budget(who: int) -> Any:
        if threading.current_thread() is not threading.main_thread():
            watcher.append(threading.current_thread())
            entered.set()
            return SimpleNamespace(
                ru_maxrss=8 * 1024**3 if sys.platform == "darwin" else 8 * 1024**2
            )
        return original_usage(who)

    def wait_for_monitor(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original_generate(*args, **kwargs)
        assert entered.wait(5), "resource sampler never ran"
        watcher[0].join(5)
        assert not watcher[0].is_alive()
        return result

    monkeypatch.setattr(resource, "getrusage", over_budget)
    monkeypatch.setattr(cli, "generate", wait_for_monitor)
    root = tmp_path / "over-budget"
    with pytest.raises(BulkError, match="bulk_rss_budget"):
        cli.benchmark(
            root,
            byte_target=2048,
            limits=Budget(
                memory_mb=64,
                threads=1,
                temp_bytes=1024**2,
                disk_reserve_bytes=0,
                rss_bytes=4 * 1024**3,
            ),
            options=OPTIONS,
        )
    report = json.loads((root / "benchmark.json").read_text())
    assert report["status"] == "FAIL" and report["error"] == "bulk_rss_budget"
    assert "result" not in report


def test_benchmark_disk_depletion_is_a_failed_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_generate = cli.generate
    usage = namedtuple("usage", "total used free")

    def depleted(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original_generate(*args, **kwargs)
        monkeypatch.setattr(shutil, "disk_usage", lambda _: usage(1, 1, 0))
        return result

    monkeypatch.setattr(cli, "generate", depleted)
    root = tmp_path / "disk-depleted"
    with pytest.raises(BulkError, match="bulk_disk_budget"):
        cli.benchmark(
            root,
            byte_target=2048,
            limits=Budget(
                temp_bytes=1024**2, disk_reserve_bytes=1024, rss_bytes=4 * 1024**3
            ),
            options=OPTIONS,
        )
    report = json.loads((root / "benchmark.json").read_text())
    assert report["status"] == "FAIL" and report["error"] == "bulk_disk_budget"


def test_seal_replay_and_failed_batch_preserve_published_snapshot(
    tmp_path: Path,
) -> None:
    from app.netflow_bulk.storage import read_ready, seal

    source, root = tmp_path / "source", tmp_path / "snapshots"
    source.mkdir()
    raw = b"IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n192.0.2.1,2001:db8::1,6,443,443\n"
    (source / "a.csv").write_bytes(raw)
    tenant = "00000000-0000-0000-0000-000000000001"
    project = "00000000-0000-0000-0000-000000000002"
    options: dict[str, Any] = {
        "tenant": tenant,
        "project": project,
        "source_id": "fixture",
        "reserve_bytes": 0,
    }
    identity, ready = seal(source, root, **options)
    assert seal(source, root, **options) == (identity, ready)
    parent = root / tenant / project / "fixture"
    (source / "b.csv").write_bytes(raw)
    with pytest.raises(BulkError, match="bulk_duplicate_file"):
        seal(source, root, **options)
    assert {p.name for p in parent.iterdir()} == {identity}
    assert read_ready(root, tenant, project, "fixture", identity) == ready
    assert (parent / identity / ready.files[0].sha256).read_bytes() == raw
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(BulkError, match="bulk_file_limit"):
        seal(empty, root, **options)
    assert {p.name for p in parent.iterdir()} == {identity}
