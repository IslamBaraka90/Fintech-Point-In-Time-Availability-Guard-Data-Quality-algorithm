"""Contract tests for the point-in-time guard.

The fixture is the cross-language acceptance anchor: 180 bitemporal records (3 entities
× 20 observations × 3 releases) with the complete snapshot and leakage audit frozen at
three query times. Every field is asserted verbatim by this suite and by the TypeScript
one.
"""

from __future__ import annotations

import pytest
from conftest import CASES, QUERY_TIMES, RECORDS, case, record, records, snapshot

from fintech_point_in_time import (
    REQUIRED_FIELDS,
    as_of_snapshot,
    leakage_audit,
    parse_timestamp_ms,
    validate_records,
)

# --- the shared fixture ------------------------------------------------------- #
def test_every_query_time_reproduces_the_reference_snapshot():
    for row in CASES:
        assert as_of_snapshot(RECORDS, row["knowledge_time"]) == row["expected_snapshot"]


def test_every_query_time_reproduces_the_reference_leakage_audit():
    for row in CASES:
        assert leakage_audit(RECORDS, row["knowledge_time"]) == row["expected_leakage"]


def test_each_snapshot_holds_one_row_per_series():
    for row in CASES:
        result = row["expected_snapshot"]
        keys = [(item["entity"], item["feature"]) for item in result]
        assert len(keys) == len(set(keys)) == 3


def test_the_guard_withholds_a_lot_at_the_first_query_time():
    """21 records that a valid-time-only filter would have admitted."""

    assert len(case(QUERY_TIMES[0])["expected_leakage"]) == 21


def test_later_query_times_withhold_less():
    withheld = [len(case(qt)["expected_leakage"]) for qt in QUERY_TIMES]
    assert withheld[-1] < withheld[0]


def test_series_come_back_in_sorted_key_order():
    for row in CASES:
        keys = [(item["entity"], item["feature"]) for item in row["expected_snapshot"]]
        assert keys == sorted(keys)


# --- the two clocks ----------------------------------------------------------- #
def test_a_record_that_has_not_arrived_is_excluded():
    rows = [
        record("A", observation_time="2026-01-02T00:00:00Z", available_at="2026-01-04T00:00:00Z"),
        record("B", observation_time="2026-01-09T00:00:00Z", available_at="2026-02-01T00:00:00Z", value=99.0),
    ]
    result = as_of_snapshot(rows, "2026-01-10T00:00:00Z")
    assert [row["record_id"] for row in result] == ["A"]


def test_the_excluded_record_shows_up_in_the_leakage_audit():
    """Valid by observation time, not yet knowable."""

    rows = [
        record("A", observation_time="2026-01-02T00:00:00Z", available_at="2026-01-04T00:00:00Z"),
        record("B", observation_time="2026-01-09T00:00:00Z", available_at="2026-02-01T00:00:00Z"),
    ]
    leaked = leakage_audit(rows, "2026-01-10T00:00:00Z")
    assert [row["record_id"] for row in leaked] == ["B"]
    assert leaked[0]["reason"] == "available_after_query_time"


def test_valid_time_defaults_to_knowledge_time():
    rows = records()
    assert as_of_snapshot(rows, QUERY_TIMES[0]) == as_of_snapshot(
        rows, QUERY_TIMES[0], QUERY_TIMES[0]
    )


def test_an_earlier_valid_time_asks_a_different_question():
    """What do I know NOW about THEN — the revised view, asked for deliberately.

    More knowledge over the *same* valid window does not just pick up revisions: it can
    reach a LATER observation, because an observation inside the window may not have
    arrived by the earlier cutoff. The early view was incomplete about its own window,
    and that is exactly the gap a backtest silently inherits.
    """

    late_knowledge = as_of_snapshot(records(), QUERY_TIMES[2], QUERY_TIMES[0])
    early_knowledge = as_of_snapshot(records(), QUERY_TIMES[0], QUERY_TIMES[0])
    assert len(late_knowledge) == len(early_knowledge) == 3

    for later, earlier in zip(late_knowledge, early_knowledge):
        assert later["entity"] == earlier["entity"]
        # Never earlier, and here genuinely later: 01-30 was valid all along but had
        # not been published by 02-01.
        assert later["observation_time"] >= earlier["observation_time"]
    assert late_knowledge[0]["observation_time"] > early_knowledge[0]["observation_time"]


def test_the_boundary_instants_are_inclusive():
    rows = [record("A", observation_time="2026-01-02T00:00:00Z", available_at="2026-01-04T00:00:00Z")]
    assert len(as_of_snapshot(rows, "2026-01-04T00:00:00Z")) == 1
    assert len(as_of_snapshot(rows, "2026-01-03T23:59:59Z")) == 0


def test_an_empty_result_is_the_answer_not_a_null():
    assert as_of_snapshot(records(), "2020-01-01T00:00:00Z") == []


# --- revision resolution ------------------------------------------------------ #
def test_the_latest_knowable_revision_wins():
    rows = [
        record("r0", revision=0, available_at="2026-01-04T00:00:00Z", value=10.0),
        record("r1", revision=1, available_at="2026-01-11T00:00:00Z", value=10.5),
        record("r2", revision=2, available_at="2026-01-30T00:00:00Z", value=11.0),
    ]
    assert as_of_snapshot(rows, "2026-01-12T00:00:00Z")[0]["record_id"] == "r1"
    assert as_of_snapshot(rows, "2026-02-01T00:00:00Z")[0]["record_id"] == "r2"


def test_a_later_observation_beats_an_older_revision():
    rows = [
        record("old-r2", observation_time="2026-01-02T00:00:00Z", revision=2,
               available_at="2026-01-20T00:00:00Z", value=10.0),
        record("new-r0", observation_time="2026-01-09T00:00:00Z", revision=0,
               available_at="2026-01-11T00:00:00Z", value=20.0),
    ]
    assert as_of_snapshot(rows, "2026-01-25T00:00:00Z")[0]["record_id"] == "new-r0"


def test_the_record_id_tiebreak_makes_it_deterministic():
    """Without it, two records sharing an arrival and revision resolve by input order."""

    rows = [
        record("bbb", available_at="2026-01-04T00:00:00Z", revision=0, value=1.0),
        record("aaa", available_at="2026-01-04T00:00:00Z", revision=0, value=2.0),
    ]
    forward = as_of_snapshot(rows, "2026-01-10T00:00:00Z")
    backward = as_of_snapshot(list(reversed(rows)), "2026-01-10T00:00:00Z")
    assert forward == backward
    assert forward[0]["record_id"] == "bbb"


def test_input_order_never_changes_the_snapshot():
    rows = records()
    assert as_of_snapshot(rows, QUERY_TIMES[1]) == as_of_snapshot(
        list(reversed(rows)), QUERY_TIMES[1]
    )


def test_series_are_resolved_independently():
    rows = [
        record("a", entity="ALFA", value=1.0),
        record("b", entity="BETA", value=2.0),
        record("c", entity="ALFA", feature="other", value=3.0),
    ]
    result = as_of_snapshot(rows, "2026-01-10T00:00:00Z")
    assert len(result) == 3


# --- validation ---------------------------------------------------------------- #
@pytest.mark.parametrize("field", sorted(REQUIRED_FIELDS))
def test_a_missing_field_raises(field):
    row = record()
    del row[field]
    with pytest.raises(ValueError, match="missing fields"):
        validate_records([row])


@pytest.mark.parametrize("field", ["entity", "feature", "record_id"])
@pytest.mark.parametrize("value", ["", 7, None])
def test_a_bad_identity_field_raises(field, value):
    row = record()
    row[field] = value
    with pytest.raises(ValueError, match=f"invalid {field}"):
        validate_records([row])


def test_a_duplicate_record_id_raises():
    """It is the final tiebreak; duplicates make the answer order-dependent."""

    with pytest.raises(ValueError, match="duplicate record_id"):
        validate_records([record("X"), record("X", value=2.0)])


@pytest.mark.parametrize("bad", [-1, 1.5, "0", True, None])
def test_a_bad_revision_raises(bad):
    row = record()
    row["revision"] = bad
    with pytest.raises(ValueError, match="invalid revision"):
        validate_records([row])


@pytest.mark.parametrize("bad", ["10", None, True, float("nan"), float("inf")])
def test_a_bad_value_raises(bad):
    row = record()
    row["value"] = bad
    with pytest.raises(ValueError, match="invalid value"):
        validate_records([row])


def test_a_non_mapping_record_raises():
    with pytest.raises(ValueError, match="must be a mapping"):
        validate_records(["nope"])


def test_input_rows_are_never_mutated():
    rows = records()
    before = [dict(row) for row in rows]
    as_of_snapshot(rows, QUERY_TIMES[0])
    leakage_audit(rows, QUERY_TIMES[0])
    assert rows == before


def test_the_leakage_audit_does_not_mutate_the_originals():
    rows = [record("A", observation_time="2026-01-02T00:00:00Z",
                   available_at="2026-02-01T00:00:00Z")]
    leakage_audit(rows, "2026-01-10T00:00:00Z")
    assert "reason" not in rows[0]


# --- timestamps ----------------------------------------------------------------- #
def test_a_naive_timestamp_is_refused_not_assumed_utc():
    """Guessing a zone here shifts the cutoff."""

    with pytest.raises(ValueError, match="must include a UTC offset"):
        parse_timestamp_ms("2026-01-02T00:00:00")


def test_an_impossible_calendar_date_is_rejected():
    with pytest.raises(ValueError, match="invalid"):
        parse_timestamp_ms("2026-02-30T00:00:00Z")


def test_an_offset_is_normalised_to_utc():
    assert parse_timestamp_ms("2026-01-02T05:00:00+05:00") == parse_timestamp_ms(
        "2026-01-02T00:00:00Z"
    )


def test_a_negative_offset_is_normalised_too():
    assert parse_timestamp_ms("2026-01-01T19:00:00-05:00") == parse_timestamp_ms(
        "2026-01-02T00:00:00Z"
    )


@pytest.mark.parametrize(
    "timestamp", ["not-a-time", "", None, 0, "2026-13-02T00:00:00Z", "2026-01-02"]
)
def test_a_malformed_timestamp_is_rejected(timestamp):
    with pytest.raises(ValueError):
        parse_timestamp_ms(timestamp)


def test_fractional_seconds_are_kept():
    assert parse_timestamp_ms("2026-01-02T00:00:00.250Z") - parse_timestamp_ms(
        "2026-01-02T00:00:00Z"
    ) == 250
