"""Shared fixture access. The same JSON backs the TypeScript suite."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "fixtures.json").read_text(encoding="utf-8")
)
RECORDS = FIXTURE["records"]
QUERY_TIMES = FIXTURE["query_times"]
CASES = FIXTURE["cases"]


def records() -> list[dict]:
    return copy.deepcopy(RECORDS)


def case(knowledge_time: str) -> dict:
    return copy.deepcopy(
        next(row for row in CASES if row["knowledge_time"] == knowledge_time)
    )


def record(
    record_id="R1",
    entity="ALFA",
    feature="weekly_metric",
    observation_time="2026-01-02T00:00:00Z",
    available_at="2026-01-04T00:00:00Z",
    revision=0,
    value=10.0,
) -> dict:
    return {
        "record_id": record_id,
        "entity": entity,
        "feature": feature,
        "observation_time": observation_time,
        "available_at": available_at,
        "revision": revision,
        "value": value,
    }


def snapshot(rows=None, knowledge_time=None, valid_time=None):
    from fintech_point_in_time import as_of_snapshot

    return as_of_snapshot(
        records() if rows is None else rows,
        knowledge_time or QUERY_TIMES[0],
        valid_time,
    )
