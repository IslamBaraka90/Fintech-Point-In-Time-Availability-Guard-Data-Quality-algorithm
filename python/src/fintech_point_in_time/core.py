"""Point-in-time filtering that keeps valid time separate from knowledge time.

The two clocks, and why one is not enough
------------------------------------------
Every record carries **two** timestamps that mean completely different things:

``observation_time``
    *Valid time.* When the thing was true in the world — the week the metric covers, the
    quarter the earnings describe.
``available_at``
    *Knowledge time.* When your system could first have used it.

A backtest that filters on only the first is not a backtest. It is a report on what you
would have earned knowing things you did not know. On the reference fixture, filtering by
observation time alone at the first query instant admits **21 records** whose data had
not been published yet.

The two cutoffs are separate arguments
---------------------------------------
:func:`as_of_snapshot` takes ``knowledge_time`` — the information cutoff — and an
optional ``valid_time`` for the latest observation you want. They default to the same
instant, which is the common case, but they are genuinely independent:

* Same instant: "what did I know, right now, about now."
* ``valid_time`` earlier: "what do I know *today* about last month" — the revised view,
  used deliberately rather than by accident.

Making them separate parameters means the second case has to be asked for. It cannot
happen because someone passed one timestamp to a function expecting another.

Revisions, resolved in a stated order
--------------------------------------
Data gets restated. Within one series the guard takes the **latest observation** that is
valid, and then among records for that same observation the latest **knowable** revision
— ordered by ``available_at``, then ``revision``, then ``record_id``.

That final tiebreak on ``record_id`` is not decoration. Without it two records sharing an
arrival instant and a revision number would resolve by input order, and the same query
would return different answers on different days.

``available_at`` is a declared boundary, not an inference
----------------------------------------------------------
It must already represent your system's own feature-ready instant. It is **not** the
issuer's filing date and **not** the vendor's publication schedule — both of those are
upstream of the delay that actually matters, which includes your ingestion, validation
and feature build. Substituting either is the most common way a "point-in-time" pipeline
still leaks.

:func:`leakage_audit` is the counterpart: it returns the records that *would* have been
admitted by valid time alone but were not yet knowable. Run it in tests, not just in
research — it is the only way to see the lookahead you are **not** taking.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any, Iterable, Mapping

__all__ = [
    "REQUIRED_FIELDS",
    "as_of_snapshot",
    "leakage_audit",
    "parse_timestamp_ms",
    "validate_records",
]

REQUIRED_FIELDS = frozenset(
    {
        "entity",
        "feature",
        "observation_time",
        "available_at",
        "revision",
        "value",
        "record_id",
    }
)

#: ISO-8601 with a mandatory offset — ``Z`` or ``±HH:MM``. A naive timestamp is refused
#: rather than assumed to be UTC, because guessing a zone here shifts the cutoff.
_TIMESTAMP = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?"
    r"(Z|[+-]\d{2}:\d{2})$"
)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def parse_timestamp_ms(value: Any, field: str = "timestamp") -> int:
    """Parse an offset-bearing ISO-8601 timestamp to integer milliseconds.

    Strict on the calendar date: ``2026-02-30`` is rejected rather than rolled over,
    which is what keeps this port and the TypeScript one agreeing on the same input.
    """

    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 string")
    match = _TIMESTAMP.match(value)
    if match is None:
        # Either unparseable or missing the offset. Both are refusals.
        if re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", value):
            raise ValueError(f"{field} must include a UTC offset")
        raise ValueError(f"invalid {field}: {value}")

    year, month, day, hour, minute, second = (int(part) for part in match.groups()[:6])
    fraction = match.group(7) or ""
    microsecond = int(fraction.ljust(6, "0")) if fraction else 0
    offset = match.group(8)

    try:
        moment = datetime(
            year, month, day, hour, minute, second, microsecond, tzinfo=timezone.utc
        )
    except ValueError as error:
        raise ValueError(f"invalid {field}: {value}") from error

    if offset != "Z":
        sign = 1 if offset[0] == "+" else -1
        offset_minutes = int(offset[1:3]) * 60 + int(offset[4:6])
        moment -= timedelta(minutes=sign * offset_minutes)

    delta: timedelta = moment - _EPOCH
    return delta.days * 86_400_000 + delta.seconds * 1000 + delta.microseconds // 1000


def validate_records(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Reject a record set that cannot be filtered honestly.

    ``record_id`` uniqueness is enforced because it is the final tiebreak in revision
    resolution — duplicates would make the answer depend on input order.
    """

    rows = [dict(row) if isinstance(row, Mapping) else row for row in records]
    seen: set[str] = set()

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"record {index} must be a mapping")
        missing = REQUIRED_FIELDS.difference(row)
        if missing:
            raise ValueError(
                f"record {index} missing fields: {', '.join(sorted(missing))}"
            )
        for field in ("entity", "feature", "record_id"):
            if not isinstance(row[field], str) or not row[field]:
                raise ValueError(f"record {index} has invalid {field}")
        if row["record_id"] in seen:
            raise ValueError(f"duplicate record_id: {row['record_id']}")
        seen.add(row["record_id"])

        parse_timestamp_ms(row["observation_time"], "observation_time")
        parse_timestamp_ms(row["available_at"], "available_at")

        if (
            isinstance(row["revision"], bool)
            or not isinstance(row["revision"], int)
            or row["revision"] < 0
        ):
            raise ValueError(f"record {index} has invalid revision")
        if (
            isinstance(row["value"], bool)
            or not isinstance(row["value"], (int, float))
            or not isfinite(row["value"])
        ):
            raise ValueError(f"record {index} has invalid value")
    return rows


def _cutoffs(knowledge_time: str, valid_time: str | None) -> tuple[int, int]:
    knowledge_cutoff = parse_timestamp_ms(knowledge_time, "knowledge_time")
    valid_cutoff = parse_timestamp_ms(valid_time or knowledge_time, "valid_time")
    return knowledge_cutoff, valid_cutoff


def as_of_snapshot(
    records: Iterable[Mapping[str, Any]],
    knowledge_time: str,
    valid_time: str | None = None,
) -> list[dict[str, Any]]:
    """Select the latest valid observation and its latest knowable revision.

    Args:
        records: Bitemporal feature records.
        knowledge_time: The system's information cutoff — nothing that arrived after
            this instant may be used.
        valid_time: The latest observation time requested. Defaults to
            ``knowledge_time``. Setting it earlier asks the deliberately different
            question "what do I know *now* about *then*".

    Returns:
        One record per ``(entity, feature)`` series, in sorted key order. A series with
        nothing both valid and knowable simply does not appear — its absence is the
        answer, not a null.
    """

    rows = validate_records(records)
    knowledge_cutoff, valid_cutoff = _cutoffs(knowledge_time, valid_time)

    eligible = [
        record
        for record in rows
        if parse_timestamp_ms(record["observation_time"]) <= valid_cutoff
        and parse_timestamp_ms(record["available_at"]) <= knowledge_cutoff
    ]

    by_series: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in eligible:
        by_series.setdefault((record["entity"], record["feature"]), []).append(record)

    selected: list[dict[str, Any]] = []
    for key in sorted(by_series):
        series = by_series[key]
        latest_observation = max(
            parse_timestamp_ms(row["observation_time"]) for row in series
        )
        same_observation = [
            row
            for row in series
            if parse_timestamp_ms(row["observation_time"]) == latest_observation
        ]
        selected.append(
            # The record_id tiebreak makes this deterministic. Without it two records
            # sharing an arrival instant and revision would resolve by input order.
            max(
                same_observation,
                key=lambda row: (
                    parse_timestamp_ms(row["available_at"]),
                    row["revision"],
                    row["record_id"],
                ),
            )
        )
    return selected


def leakage_audit(
    records: Iterable[Mapping[str, Any]],
    knowledge_time: str,
    valid_time: str | None = None,
) -> list[dict[str, Any]]:
    """Return the records a valid-time-only filter would have wrongly admitted.

    These are records whose ``observation_time`` is within the requested window but
    whose ``available_at`` is **after** the knowledge cutoff — data about the past that
    had not been published yet.

    Run this in tests rather than only in research. A backtest that silently uses these
    reports a strategy nobody could have run, and the failure is invisible in its output.
    """

    rows = validate_records(records)
    knowledge_cutoff, valid_cutoff = _cutoffs(knowledge_time, valid_time)

    return [
        {**record, "reason": "available_after_query_time"}
        for record in rows
        if parse_timestamp_ms(record["observation_time"]) <= valid_cutoff
        and knowledge_cutoff < parse_timestamp_ms(record["available_at"])
    ]
