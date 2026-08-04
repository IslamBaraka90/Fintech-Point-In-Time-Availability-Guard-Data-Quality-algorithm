/** Tests for panels, restatement history, vintage diffs and publication lag. */

import assert from "node:assert/strict";
import { test } from "node:test";

import { asOfSnapshot, leakageAudit } from "../src/core.ts";
import {
  buildPanel,
  leakageReport,
  publicationLag,
  restatementHistory,
  vintageDiff,
} from "../src/backtest.ts";
import { QUERY_TIMES, RECORDS, record } from "./fixtures.ts";

const close = (a: number, b: number, tol = 1e-9) => Math.abs(a - b) < tol;

// --- buildPanel ------------------------------------------------------------------ //
test("a panel stacks one snapshot per knowledge time", () => {
  const panel = buildPanel(RECORDS, QUERY_TIMES);
  assert.equal(panel.coverage.length, 3);
  assert.equal(panel.total_rows, 9); // 3 series x 3 instants
});

test("every row carries the instant that produced it", () => {
  const panel = buildPanel(RECORDS, QUERY_TIMES);
  assert.deepEqual(
    [...new Set(panel.rows.map((row) => row.knowledge_time))].sort(),
    [...QUERY_TIMES].sort(),
  );
});

test("panel rows match the individual snapshots", () => {
  const panel = buildPanel(RECORDS, QUERY_TIMES);
  for (const knowledgeTime of QUERY_TIMES) {
    const rows = panel.rows.filter((row) => row.knowledge_time === knowledgeTime);
    const direct = asOfSnapshot(RECORDS, knowledgeTime);
    assert.deepEqual(rows.map((r) => r.record_id), direct.map((r) => r.record_id));
  }
});

test("coverage counts the series at each instant", () => {
  // A falling count is a feed going dark, invisible once rows are concatenated.
  const panel = buildPanel(RECORDS, QUERY_TIMES);
  assert.ok(panel.coverage.every((point) => point.series === 3));
  assert.equal(panel.complete, true);
  assert.equal(panel.min_series, 3);
  assert.equal(panel.max_series, 3);
});

test("an incomplete panel is flagged", () => {
  const panel = buildPanel(RECORDS, ["2020-01-01T00:00:00Z", QUERY_TIMES[0]!]);
  assert.equal(panel.min_series, 0);
  assert.equal(panel.complete, false);
});

test("per-instant valid times are honoured", () => {
  const panel = buildPanel(RECORDS, [QUERY_TIMES[2]!], [QUERY_TIMES[0]!]);
  assert.equal(panel.coverage[0]!.valid_time, QUERY_TIMES[0]);
});

test("mismatched valid times throw", () => {
  assert.throws(
    () => buildPanel(RECORDS, QUERY_TIMES, [QUERY_TIMES[0]!]),
    /must match knowledge_times/,
  );
});

test("an empty knowledge time list throws", () => {
  assert.throws(() => buildPanel(RECORDS, []), /must not be empty/);
});

// --- restatementHistory ------------------------------------------------------------ //
test("the revision trail is ordered by arrival", () => {
  const history = restatementHistory(RECORDS, "ALFA", "weekly_metric", "2026-01-02T00:00:00Z");
  const stamps = history.versions.map((row) => row.available_at);
  assert.deepEqual(stamps, [...stamps].sort());
  assert.equal(history.revision_count, 3);
});

test("the trail reports each step and the total drift", () => {
  const history = restatementHistory(RECORDS, "ALFA", "weekly_metric", "2026-01-02T00:00:00Z");
  assert.equal(history.first_value, 10.0);
  assert.equal(history.was_restated, true);
  assert.ok(close(history.total_drift!, history.final_value! - history.first_value!));
  assert.equal(history.versions[0]!.change_from_previous, null);
  assert.notEqual(history.versions[1]!.change_from_previous, null);
});

test("the lag is reported in days from the observation", () => {
  const history = restatementHistory(RECORDS, "ALFA", "weekly_metric", "2026-01-02T00:00:00Z");
  assert.ok(close(history.versions[0]!.lag_days, 2 + 14 / 24));
});

test("an unrestated observation says so", () => {
  const history = restatementHistory([record({ record_id: "only", value: 5 })],
    "ALFA", "weekly_metric", "2026-01-02T00:00:00Z");
  assert.equal(history.revision_count, 1);
  assert.equal(history.was_restated, false);
  assert.equal(history.total_drift, 0);
});

test("an unknown series has an empty trail", () => {
  const history = restatementHistory(RECORDS, "NOPE", "weekly_metric", "2026-01-02T00:00:00Z");
  assert.deepEqual(history.versions, []);
  assert.equal(history.total_drift, null);
  assert.equal(history.was_restated, false);
});

// --- vintageDiff -------------------------------------------------------------------- //
test("two vintages of the same window can disagree", () => {
  const diff = vintageDiff(RECORDS, QUERY_TIMES[0]!, QUERY_TIMES[2]!);
  assert.equal(diff.reproducible, false);
  assert.ok(diff.changed.length > 0 || diff.appeared.length > 0);
});

test("a change names both record ids and the delta", () => {
  const diff = vintageDiff(RECORDS, QUERY_TIMES[0]!, QUERY_TIMES[2]!);
  if (diff.changed.length) {
    const row = diff.changed[0]!;
    assert.notEqual(row.earlier_record_id, row.later_record_id);
    assert.ok(close(row.delta, row.later_value - row.earlier_value));
  }
});

test("both vintages share one valid time", () => {
  // So the diff isolates what you LEARNED, not what newly happened.
  assert.equal(vintageDiff(RECORDS, QUERY_TIMES[0]!, QUERY_TIMES[2]!).valid_time, QUERY_TIMES[0]);
});

test("an explicit valid time is honoured", () => {
  const diff = vintageDiff(RECORDS, QUERY_TIMES[0]!, QUERY_TIMES[2]!, "2026-01-15T00:00:00Z");
  assert.equal(diff.valid_time, "2026-01-15T00:00:00Z");
});

test("the same vintage twice is reproducible", () => {
  const diff = vintageDiff(RECORDS, QUERY_TIMES[1]!, QUERY_TIMES[1]!);
  assert.equal(diff.reproducible, true);
  assert.deepEqual(diff.changed, []);
  assert.equal(diff.max_abs_delta, null);
});

test("series absent at the earlier vintage are listed separately", () => {
  const rows = [record({ record_id: "late", available_at: "2026-03-01T00:00:00Z" })];
  const diff = vintageDiff(rows, "2026-01-10T00:00:00Z", "2026-04-01T00:00:00Z");
  assert.deepEqual(diff.appeared.map((row) => row.entity), ["ALFA"]);
  assert.equal(diff.reproducible, false);
});

test("an inverted vintage pair throws", () => {
  assert.throws(
    () => vintageDiff(RECORDS, QUERY_TIMES[2]!, QUERY_TIMES[0]!),
    /must not precede/,
  );
});

// --- publicationLag ------------------------------------------------------------------ //
test("the lag distribution is reported in days", () => {
  const lag = publicationLag(RECORDS);
  assert.equal(lag.overall.count, 180);
  assert.ok(lag.overall.min_days! > 0);
  assert.ok(lag.overall.min_days! <= lag.overall.median_days!);
  assert.ok(lag.overall.median_days! <= lag.overall.max_days!);
});

test("first prints are measured separately", () => {
  // A later revision's lag measures the restatement, not the publication.
  const lag = publicationLag(RECORDS);
  assert.equal(lag.first_print.count, 60);
  assert.ok(lag.first_print.max_days! < lag.overall.max_days!);
});

test("the tail is what decides usability", () => {
  const lag = publicationLag(RECORDS);
  assert.ok(lag.overall.max_days! > lag.overall.median_days!);
});

test("lags are broken down by feature", () => {
  const lag = publicationLag(RECORDS);
  assert.deepEqual(Object.keys(lag.by_feature), ["weekly_metric"]);
  assert.equal(lag.by_feature.weekly_metric!.count, 180);
});

test("a negative lag would be counted", () => {
  // available_at before observation_time is a pipeline bug, not a fast feed.
  const rows = [record({
    record_id: "odd",
    observation_time: "2026-01-10T00:00:00Z",
    available_at: "2026-01-04T00:00:00Z",
  })];
  assert.equal(publicationLag(rows).negative_lags, 1);
});

test("an empty record set throws", () => {
  assert.throws(() => publicationLag([]), /must not be empty/);
});

// --- leakageReport --------------------------------------------------------------------- //
test("the report quantifies what the guard withheld", () => {
  const report = leakageReport(RECORDS, QUERY_TIMES[0]!);
  assert.equal(report.withheld, 21);
  assert.ok(report.withheld_share > 0);
  assert.equal(report.clean, false);
});

test("the share is over the valid-time matches", () => {
  const report = leakageReport(RECORDS, QUERY_TIMES[0]!);
  assert.ok(close(report.withheld_share, report.withheld / report.valid_time_matches));
});

test("withholding is broken down by entity and feature", () => {
  const report = leakageReport(RECORDS, QUERY_TIMES[0]!);
  assert.deepEqual(Object.keys(report.by_entity).sort(), ["ALFA", "BETA", "GAMM"]);
  assert.equal(
    Object.values(report.by_entity).reduce((a, b) => a + b, 0),
    report.withheld,
  );
  assert.equal(
    Object.values(report.by_feature).reduce((a, b) => a + b, 0),
    report.withheld,
  );
});

test("a late enough cutoff withholds nothing", () => {
  const report = leakageReport(RECORDS, "2027-01-01T00:00:00Z");
  assert.equal(report.withheld, 0);
  assert.equal(report.clean, true);
  assert.equal(report.withheld_share, 0);
});

test("the report agrees with the raw audit", () => {
  for (const knowledgeTime of QUERY_TIMES) {
    assert.equal(
      leakageReport(RECORDS, knowledgeTime).withheld,
      leakageAudit(RECORDS, knowledgeTime).length,
    );
  }
});
