"""Tests for panels, restatement history, vintage diffs and publication lag."""

from __future__ import annotations

import pytest
from conftest import QUERY_TIMES, RECORDS, record, records

from fintech_point_in_time import (
    as_of_snapshot,
    build_panel,
    leakage_report,
    publication_lag,
    restatement_history,
    vintage_diff,
)


# --- build_panel ------------------------------------------------------------------ #
def test_a_panel_stacks_one_snapshot_per_knowledge_time():
    panel = build_panel(RECORDS, QUERY_TIMES)
    assert len(panel["coverage"]) == 3
    assert panel["total_rows"] == 9  # 3 series x 3 instants


def test_every_row_carries_the_instant_that_produced_it():
    """The panel stays self-describing after it leaves this function."""

    panel = build_panel(RECORDS, QUERY_TIMES)
    assert {row["knowledge_time"] for row in panel["rows"]} == set(QUERY_TIMES)


def test_panel_rows_match_the_individual_snapshots():
    panel = build_panel(RECORDS, QUERY_TIMES)
    for knowledge_time in QUERY_TIMES:
        rows = [r for r in panel["rows"] if r["knowledge_time"] == knowledge_time]
        direct = as_of_snapshot(RECORDS, knowledge_time)
        assert [r["record_id"] for r in rows] == [r["record_id"] for r in direct]


def test_coverage_counts_the_series_at_each_instant():
    """A falling count is a feed going dark, invisible once rows are concatenated."""

    panel = build_panel(RECORDS, QUERY_TIMES)
    assert all(point["series"] == 3 for point in panel["coverage"])
    assert panel["complete"] is True
    assert panel["min_series"] == panel["max_series"] == 3


def test_an_incomplete_panel_is_flagged():
    panel = build_panel(RECORDS, ["2020-01-01T00:00:00Z", QUERY_TIMES[0]])
    assert panel["min_series"] == 0
    assert panel["complete"] is False


def test_per_instant_valid_times_are_honoured():
    panel = build_panel(RECORDS, [QUERY_TIMES[2]], [QUERY_TIMES[0]])
    assert panel["coverage"][0]["valid_time"] == QUERY_TIMES[0]


def test_mismatched_valid_times_raise():
    with pytest.raises(ValueError, match="must match knowledge_times"):
        build_panel(RECORDS, QUERY_TIMES, [QUERY_TIMES[0]])


def test_an_empty_knowledge_time_list_raises():
    with pytest.raises(ValueError, match="must not be empty"):
        build_panel(RECORDS, [])


# --- restatement_history ------------------------------------------------------------ #
def test_the_revision_trail_is_ordered_by_arrival():
    history = restatement_history(RECORDS, "ALFA", "weekly_metric", "2026-01-02T00:00:00Z")
    stamps = [row["available_at"] for row in history["versions"]]
    assert stamps == sorted(stamps)
    assert history["revision_count"] == 3


def test_the_trail_reports_each_step_and_the_total_drift():
    history = restatement_history(RECORDS, "ALFA", "weekly_metric", "2026-01-02T00:00:00Z")
    assert history["first_value"] == 10.0
    assert history["was_restated"] is True
    assert history["total_drift"] == pytest.approx(
        history["final_value"] - history["first_value"]
    )
    assert history["versions"][0]["change_from_previous"] is None
    assert history["versions"][1]["change_from_previous"] is not None


def test_the_lag_is_reported_in_days_from_the_observation():
    history = restatement_history(RECORDS, "ALFA", "weekly_metric", "2026-01-02T00:00:00Z")
    assert history["versions"][0]["lag_days"] == pytest.approx(2 + 14 / 24)


def test_an_unrestated_observation_says_so():
    rows = [record("only", value=5.0)]
    history = restatement_history(rows, "ALFA", "weekly_metric", "2026-01-02T00:00:00Z")
    assert history["revision_count"] == 1
    assert history["was_restated"] is False
    assert history["total_drift"] == 0


def test_an_unknown_series_has_an_empty_trail():
    history = restatement_history(RECORDS, "NOPE", "weekly_metric", "2026-01-02T00:00:00Z")
    assert history["versions"] == []
    assert history["total_drift"] is None
    assert history["was_restated"] is False


# --- vintage_diff -------------------------------------------------------------------- #
def test_two_vintages_of_the_same_window_can_disagree():
    """A backtest run in February and re-run in May over the identical window."""

    diff = vintage_diff(RECORDS, QUERY_TIMES[0], QUERY_TIMES[2])
    assert diff["reproducible"] is False
    assert diff["changed"] or diff["appeared"]


def test_a_change_names_both_record_ids_and_the_delta():
    diff = vintage_diff(RECORDS, QUERY_TIMES[0], QUERY_TIMES[2])
    if diff["changed"]:
        row = diff["changed"][0]
        assert row["earlier_record_id"] != row["later_record_id"]
        assert row["delta"] == pytest.approx(row["later_value"] - row["earlier_value"])


def test_both_vintages_share_one_valid_time():
    """So the diff isolates what you LEARNED, not what newly happened."""

    diff = vintage_diff(RECORDS, QUERY_TIMES[0], QUERY_TIMES[2])
    assert diff["valid_time"] == QUERY_TIMES[0]


def test_an_explicit_valid_time_is_honoured():
    diff = vintage_diff(RECORDS, QUERY_TIMES[0], QUERY_TIMES[2], "2026-01-15T00:00:00Z")
    assert diff["valid_time"] == "2026-01-15T00:00:00Z"


def test_the_same_vintage_twice_is_reproducible():
    diff = vintage_diff(RECORDS, QUERY_TIMES[1], QUERY_TIMES[1])
    assert diff["reproducible"] is True
    assert diff["changed"] == []
    assert diff["max_abs_delta"] is None


def test_series_absent_at_the_earlier_vintage_are_listed_separately():
    rows = [
        record("late", observation_time="2026-01-02T00:00:00Z",
               available_at="2026-03-01T00:00:00Z"),
    ]
    diff = vintage_diff(rows, "2026-01-10T00:00:00Z", "2026-04-01T00:00:00Z")
    assert [row["entity"] for row in diff["appeared"]] == ["ALFA"]
    assert diff["reproducible"] is False


def test_an_inverted_vintage_pair_raises():
    with pytest.raises(ValueError, match="must not precede"):
        vintage_diff(RECORDS, QUERY_TIMES[2], QUERY_TIMES[0])


# --- publication_lag ------------------------------------------------------------------ #
def test_the_lag_distribution_is_reported_in_days():
    lag = publication_lag(RECORDS)
    assert lag["overall"]["count"] == 180
    assert lag["overall"]["min_days"] > 0
    assert lag["overall"]["min_days"] <= lag["overall"]["median_days"] <= lag["overall"]["max_days"]


def test_first_prints_are_measured_separately():
    """A later revision's lag measures the restatement, not the publication."""

    lag = publication_lag(RECORDS)
    assert lag["first_print"]["count"] == 60
    assert lag["first_print"]["max_days"] < lag["overall"]["max_days"]


def test_the_tail_is_what_decides_usability():
    lag = publication_lag(RECORDS)
    assert lag["overall"]["max_days"] > lag["overall"]["median_days"]


def test_lags_are_broken_down_by_feature():
    lag = publication_lag(RECORDS)
    assert list(lag["by_feature"]) == ["weekly_metric"]
    assert lag["by_feature"]["weekly_metric"]["count"] == 180


def test_a_negative_lag_would_be_counted():
    """available_at before observation_time is a pipeline bug, not a fast feed."""

    rows = [record("odd", observation_time="2026-01-10T00:00:00Z",
                   available_at="2026-01-04T00:00:00Z")]
    assert publication_lag(rows)["negative_lags"] == 1


def test_an_empty_record_set_raises():
    with pytest.raises(ValueError, match="must not be empty"):
        publication_lag([])


# --- leakage_report --------------------------------------------------------------------- #
def test_the_report_quantifies_what_the_guard_withheld():
    report = leakage_report(RECORDS, QUERY_TIMES[0])
    assert report["withheld"] == 21
    assert report["withheld_share"] > 0
    assert report["clean"] is False


def test_the_share_is_over_the_valid_time_matches():
    report = leakage_report(RECORDS, QUERY_TIMES[0])
    assert report["withheld_share"] == pytest.approx(
        report["withheld"] / report["valid_time_matches"]
    )


def test_withholding_is_broken_down_by_entity_and_feature():
    report = leakage_report(RECORDS, QUERY_TIMES[0])
    assert sorted(report["by_entity"]) == ["ALFA", "BETA", "GAMM"]
    assert sum(report["by_entity"].values()) == report["withheld"]
    assert sum(report["by_feature"].values()) == report["withheld"]


def test_a_late_enough_cutoff_withholds_nothing():
    report = leakage_report(RECORDS, "2027-01-01T00:00:00Z")
    assert report["withheld"] == 0
    assert report["clean"] is True
    assert report["withheld_share"] == 0.0


def test_the_report_agrees_with_the_raw_audit():
    from fintech_point_in_time import leakage_audit

    for knowledge_time in QUERY_TIMES:
        assert leakage_report(RECORDS, knowledge_time)["withheld"] == len(
            leakage_audit(RECORDS, knowledge_time)
        )
