import csv
from pathlib import Path

import pytest

from app.domain.netflow_activity import (
    NetFlowActivityContractError,
    aggregate_netflow_ip_activity,
)
from app.domain.netflow_datasets import CANONICAL_COLUMNS, parse_netflow_dataset


def test_managed_activity_is_deterministic_positive_evidence(tmp_path: Path) -> None:
    raw = tmp_path / "flows.csv"
    raw.write_text(
        "IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n"
        "::ffff:192.0.2.10,198.51.100.20,6,53000,443\n"
        "198.51.100.20,192.0.2.10,6,443,53000\n"
        "198.51.100.20,192.0.2.10,6,443,53000\n"
        "192.0.2.10,192.0.2.10,1,0,2048\n"
        "2001:db8::1,192.0.2.10,17,53,50000\n"
        "203.0.113.8,203.0.113.9,6,443,443\n"
    )
    parsed = parse_netflow_dataset(raw)
    managed = ["192.0.2.10", "2001:db8::1"]
    result = aggregate_netflow_ip_activity(parsed.normalized_path, managed)
    assert [item.as_dict() for item in result.activities] == [
        {
            "canonical_ip": "192.0.2.10",
            "flow_count": 5,
            "peer_ips": ["198.51.100.20", "2001:db8::1"],
            "protocols": [1, 6, 17],
            "first_seen_utc": None,
            "last_seen_utc": None,
        },
        {
            "canonical_ip": "2001:db8::1",
            "flow_count": 1,
            "peer_ips": ["192.0.2.10"],
            "protocols": [17],
            "first_seen_utc": None,
            "last_seen_utc": None,
        },
    ]
    with parsed.normalized_path.open(newline="") as source:
        rows = list(csv.reader(source))
    with parsed.normalized_path.open("w", newline="") as target:
        csv.writer(target, lineterminator="\n").writerows(
            [rows[0], *reversed(rows[1:])]
        )
    assert (
        aggregate_netflow_ip_activity(parsed.normalized_path, list(reversed(managed)))
        == result
    )
    assert aggregate_netflow_ip_activity(parsed.normalized_path, []).activities == ()


@pytest.mark.parametrize(
    "row",
    [
        ["row:1", "bad", "192.0.2.10", "6", "", "", "", "", "", "", ""],
        ["row:1", "192.0.2.10", "192.0.2.20", "256", "", "", "", "", "", "", ""],
        ["row:1", "192.0.2.10", "192.0.2.20", "6"],
    ],
)
def test_invalid_normalized_activity_fails_closed(
    tmp_path: Path, row: list[str]
) -> None:
    path = tmp_path / "normalized.csv"
    with path.open("w", newline="") as target:
        csv.writer(target).writerows([CANONICAL_COLUMNS, row])
    with pytest.raises(NetFlowActivityContractError):
        aggregate_netflow_ip_activity(path, ["192.0.2.10"])
