"""From one honest snapshot to a whole honest backtest.

The core module answers "what did I know at this instant". A backtest needs that answer
at *every* instant, plus the evidence that the answer is stable. This module supplies
both, and each function exists because of a specific way point-in-time discipline is lost
after the guard is already in place.

**The panel** — :func:`build_panel`
One snapshot per rebalance date, stacked. This is the object a backtest actually
consumes, and building it by looping over ``as_of_snapshot`` is the part teams get right;
what they miss is that the panel should be **built once and reused**, because a panel
rebuilt after a restatement is a different panel.

**What the data said, and what it says now** — :func:`restatement_history`
The revision trail for one series and one observation: every version, when it arrived,
and how far it moved. A feature whose first print is routinely revised by 3% is not the
feature you backtested, whatever the final values say.

**Would this backtest reproduce?** — :func:`vintage_diff`
Run the same query at two different knowledge times and diff the panels. Any series whose
value changed was **restated between the two runs** — which means the backtest you ran in
March cannot be reproduced in June, and neither result is wrong.

**How late is the data, really?** — :func:`publication_lag`
The distribution of ``available_at − observation_time``. The median is the delay you
should be modelling; the maximum is the one that breaks you. A feature with a 2-day
median and a 40-day tail cannot be used on a 3-day rebalance no matter what the median
says.

**How much lookahead did you avoid?** — :func:`leakage_report`
Rolls up :func:`~fintech_point_in_time.core.leakage_audit` by entity and feature, and
reports the share of otherwise-valid records that were correctly withheld. On the
reference fixture that is a large number, which is the point: the guard is doing
something, and this is how you show it.
"""

from __future__ import annotations

from statistics import mean, median
from typing import Any, Iterable, Mapping, Sequence

from .core import (
    as_of_snapshot,
    leakage_audit,
    parse_timestamp_ms,
    validate_records,
)

__all__ = [
    "build_panel",
    "leakage_report",
    "publication_lag",
    "restatement_history",
    "vintage_diff",
]

_MS_PER_DAY = 86_400_000


def build_panel(
    records: Iterable[Mapping[str, Any]],
    knowledge_times: Sequence[str],
    valid_times: Sequence[str] | None = None,
) -> dict[str, Any]:
    """One as-of snapshot per knowledge time, stacked into a point-in-time panel.

    Args:
        records: The bitemporal record set.
        knowledge_times: The rebalance instants, in the order you want them.
        valid_times: Optional per-instant valid-time cutoffs. Must match
            ``knowledge_times`` in length when supplied.

    Returns:
        ``rows`` carries every snapshot record stamped with the ``knowledge_time`` that
        produced it, so the panel remains self-describing after it leaves this function.
        ``coverage`` reports how many series each instant resolved — a falling count is
        a feed going dark, and it is invisible once the rows are concatenated.
    """

    record_list = validate_records(records)
    cutoffs = list(knowledge_times)
    if not cutoffs:
        raise ValueError("knowledge_times must not be empty")
    valid_list = list(valid_times) if valid_times is not None else [None] * len(cutoffs)
    if len(valid_list) != len(cutoffs):
        raise ValueError("valid_times must match knowledge_times in length")

    rows: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    for knowledge_time, valid_time in zip(cutoffs, valid_list):
        snapshot = as_of_snapshot(record_list, knowledge_time, valid_time)
        for record in snapshot:
            rows.append({**record, "knowledge_time": knowledge_time})
        coverage.append(
            {
                "knowledge_time": knowledge_time,
                "valid_time": valid_time or knowledge_time,
                "series": len(snapshot),
                "entities": len({row["entity"] for row in snapshot}),
            }
        )

    series_counts = [point["series"] for point in coverage]
    return {
        "rows": rows,
        "coverage": coverage,
        "knowledge_times": cutoffs,
        "total_rows": len(rows),
        # A falling series count is a feed going dark, and it disappears the moment the
        # rows are concatenated into one frame.
        "min_series": min(series_counts),
        "max_series": max(series_counts),
        "complete": len(set(series_counts)) == 1,
    }


def restatement_history(
    records: Iterable[Mapping[str, Any]],
    entity: str,
    feature: str,
    observation_time: str,
) -> dict[str, Any]:
    """The full revision trail for one observation: every version and when it landed.

    ``total_drift`` is the distance from the first print to the last. A feature whose
    first print is routinely revised is not the feature you backtested, and this is the
    number that says so.
    """

    rows = validate_records(records)
    target = parse_timestamp_ms(observation_time, "observation_time")

    versions = sorted(
        (
            row
            for row in rows
            if row["entity"] == entity
            and row["feature"] == feature
            and parse_timestamp_ms(row["observation_time"]) == target
        ),
        key=lambda row: (parse_timestamp_ms(row["available_at"]), row["revision"], row["record_id"]),
    )

    trail: list[dict[str, Any]] = []
    for index, row in enumerate(versions):
        previous = versions[index - 1] if index else None
        trail.append(
            {
                "record_id": row["record_id"],
                "revision": row["revision"],
                "available_at": row["available_at"],
                "value": row["value"],
                "change_from_previous": (
                    row["value"] - previous["value"] if previous is not None else None
                ),
                "lag_days": (
                    parse_timestamp_ms(row["available_at"]) - target
                ) / _MS_PER_DAY,
            }
        )

    first = versions[0]["value"] if versions else None
    last = versions[-1]["value"] if versions else None
    return {
        "entity": entity,
        "feature": feature,
        "observation_time": observation_time,
        "versions": trail,
        "revision_count": len(trail),
        "first_value": first,
        "final_value": last,
        # How far the number moved after you first acted on it.
        "total_drift": (last - first) if versions else None,
        "was_restated": len(trail) > 1,
    }


def vintage_diff(
    records: Iterable[Mapping[str, Any]],
    earlier_knowledge_time: str,
    later_knowledge_time: str,
    valid_time: str | None = None,
) -> dict[str, Any]:
    """Diff two vintages of the same query: would this backtest reproduce?

    Both snapshots use the **same** ``valid_time`` — defaulting to the earlier knowledge
    time — so the comparison isolates *what you learned in between* rather than mixing in
    new observations. Any series whose value changed was restated between the two runs.

    That is the reproducibility answer: a backtest run in March and re-run in June over
    the identical window can legitimately disagree, and neither result is wrong.
    """

    record_list = validate_records(records)
    earlier_ms = parse_timestamp_ms(earlier_knowledge_time, "earlier_knowledge_time")
    later_ms = parse_timestamp_ms(later_knowledge_time, "later_knowledge_time")
    if later_ms < earlier_ms:
        raise ValueError("later_knowledge_time must not precede earlier_knowledge_time")

    shared_valid = valid_time or earlier_knowledge_time
    earlier = {
        (row["entity"], row["feature"]): row
        for row in as_of_snapshot(record_list, earlier_knowledge_time, shared_valid)
    }
    later = {
        (row["entity"], row["feature"]): row
        for row in as_of_snapshot(record_list, later_knowledge_time, shared_valid)
    }

    changed: list[dict[str, Any]] = []
    appeared: list[dict[str, Any]] = []
    for key in sorted(earlier.keys() | later.keys()):
        before = earlier.get(key)
        after = later.get(key)
        if before is None:
            appeared.append(
                {"entity": key[0], "feature": key[1], "value": after["value"]}
            )
            continue
        if after is None or before["record_id"] == after["record_id"]:
            continue
        changed.append(
            {
                "entity": key[0],
                "feature": key[1],
                "observation_time": before["observation_time"],
                "earlier_record_id": before["record_id"],
                "later_record_id": after["record_id"],
                "earlier_value": before["value"],
                "later_value": after["value"],
                "delta": after["value"] - before["value"],
            }
        )

    return {
        "earlier_knowledge_time": earlier_knowledge_time,
        "later_knowledge_time": later_knowledge_time,
        "valid_time": shared_valid,
        "series_compared": len(earlier.keys() | later.keys()),
        "changed": changed,
        # Series absent at the earlier vintage: data that had not arrived at all yet.
        "appeared": appeared,
        # True when the same window produces the same numbers at both vintages.
        "reproducible": not changed and not appeared,
        "max_abs_delta": (
            max(abs(float(row["delta"])) for row in changed) if changed else None
        ),
    }


def publication_lag(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The distribution of ``available_at − observation_time``, overall and per feature.

    The median is the delay you should be modelling. The **maximum** is the one that
    breaks you: a feature with a two-day median and a forty-day tail cannot be used on a
    three-day rebalance, whatever the median says.

    Only first prints (``revision == 0``) are counted by default in ``first_print``,
    since a later revision's lag measures the restatement, not the publication.
    """

    rows = validate_records(records)
    if not rows:
        raise ValueError("records must not be empty")

    def stats(values: list[float]) -> dict[str, Any]:
        if not values:
            return {"count": 0, "min_days": None, "median_days": None,
                    "mean_days": None, "max_days": None}
        return {
            "count": len(values),
            "min_days": min(values),
            "median_days": median(values),
            "mean_days": mean(values),
            "max_days": max(values),
        }

    def lag(row: Mapping[str, Any]) -> float:
        return (
            parse_timestamp_ms(row["available_at"])
            - parse_timestamp_ms(row["observation_time"])
        ) / _MS_PER_DAY

    all_lags = [lag(row) for row in rows]
    first_prints = [lag(row) for row in rows if row["revision"] == 0]

    by_feature: dict[str, list[float]] = {}
    for row in rows:
        by_feature.setdefault(str(row["feature"]), []).append(lag(row))

    return {
        "overall": stats(all_lags),
        # The lag that decides whether the feature is usable at all.
        "first_print": stats(first_prints),
        "by_feature": {
            feature: stats(values) for feature, values in sorted(by_feature.items())
        },
        "negative_lags": sum(1 for value in all_lags if value < 0),
    }


def leakage_report(
    records: Iterable[Mapping[str, Any]],
    knowledge_time: str,
    valid_time: str | None = None,
) -> dict[str, Any]:
    """Roll up the leakage audit: how much lookahead the guard actually withheld.

    ``withheld_share`` is over the records a valid-time-only filter would have admitted.
    A large number is not a problem — it is the guard working, and it is the figure to
    put in front of anyone who thinks point-in-time filtering is a formality.
    """

    rows = validate_records(records)
    leaked = leakage_audit(rows, knowledge_time, valid_time)
    valid_cutoff = parse_timestamp_ms(valid_time or knowledge_time, "valid_time")
    valid_records = [
        row for row in rows if parse_timestamp_ms(row["observation_time"]) <= valid_cutoff
    ]

    by_entity: dict[str, int] = {}
    by_feature: dict[str, int] = {}
    for row in leaked:
        by_entity[str(row["entity"])] = by_entity.get(str(row["entity"]), 0) + 1
        by_feature[str(row["feature"])] = by_feature.get(str(row["feature"]), 0) + 1

    return {
        "knowledge_time": knowledge_time,
        "valid_time": valid_time or knowledge_time,
        "total_records": len(rows),
        # What a valid-time-only filter would have admitted.
        "valid_time_matches": len(valid_records),
        "withheld": len(leaked),
        "withheld_share": (len(leaked) / len(valid_records)) if valid_records else 0.0,
        "by_entity": dict(sorted(by_entity.items())),
        "by_feature": dict(sorted(by_feature.items())),
        "clean": not leaked,
    }
