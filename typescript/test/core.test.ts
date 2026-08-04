/**
 * Contract tests for the point-in-time guard.
 *
 * The fixture is the cross-language acceptance anchor: 180 bitemporal records (3
 * entities × 20 observations × 3 releases) with the complete snapshot and leakage audit
 * frozen at three query times. Every field is asserted verbatim by this suite and by the
 * Python one.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  REQUIRED_FIELDS,
  asOfSnapshot,
  leakageAudit,
  parseTimestampMs,
  validateRecords,
} from "../src/core.ts";
import { CASES, QUERY_TIMES, RECORDS, record, records, testCase } from "./fixtures.ts";

// --- the shared fixture ------------------------------------------------------- //
test("every query time reproduces the reference snapshot", () => {
  for (const row of CASES) {
    assert.deepEqual(asOfSnapshot(RECORDS, row.knowledge_time), row.expected_snapshot);
  }
});

test("every query time reproduces the reference leakage audit", () => {
  for (const row of CASES) {
    assert.deepEqual(leakageAudit(RECORDS, row.knowledge_time), row.expected_leakage);
  }
});

test("each snapshot holds one row per series", () => {
  for (const row of CASES) {
    const keys = row.expected_snapshot.map((item) => `${item.entity} ${item.feature}`);
    assert.equal(keys.length, 3);
    assert.equal(new Set(keys).size, 3);
  }
});

test("the guard withholds a lot at the first query time", () => {
  // 21 records that a valid-time-only filter would have admitted.
  assert.equal(testCase(QUERY_TIMES[0]!).expected_leakage.length, 21);
});

test("later query times withhold less", () => {
  const withheld = QUERY_TIMES.map((qt) => testCase(qt).expected_leakage.length);
  assert.ok(withheld.at(-1)! < withheld[0]!);
});

test("series come back in sorted key order", () => {
  for (const row of CASES) {
    const keys = row.expected_snapshot.map((item) => `${item.entity} ${item.feature}`);
    assert.deepEqual(keys, [...keys].sort());
  }
});

// --- the two clocks ----------------------------------------------------------- //
test("a record that has not arrived is excluded", () => {
  const rows = [
    record({ record_id: "A", observation_time: "2026-01-02T00:00:00Z", available_at: "2026-01-04T00:00:00Z" }),
    record({ record_id: "B", observation_time: "2026-01-09T00:00:00Z", available_at: "2026-02-01T00:00:00Z", value: 99 }),
  ];
  assert.deepEqual(
    asOfSnapshot(rows, "2026-01-10T00:00:00Z").map((r) => r.record_id),
    ["A"],
  );
});

test("the excluded record shows up in the leakage audit", () => {
  const rows = [
    record({ record_id: "A", observation_time: "2026-01-02T00:00:00Z", available_at: "2026-01-04T00:00:00Z" }),
    record({ record_id: "B", observation_time: "2026-01-09T00:00:00Z", available_at: "2026-02-01T00:00:00Z" }),
  ];
  const leaked = leakageAudit(rows, "2026-01-10T00:00:00Z");
  assert.deepEqual(leaked.map((r) => r.record_id), ["B"]);
  assert.equal(leaked[0]!.reason, "available_after_query_time");
});

test("valid time defaults to knowledge time", () => {
  const rows = records();
  assert.deepEqual(
    asOfSnapshot(rows, QUERY_TIMES[0]!),
    asOfSnapshot(rows, QUERY_TIMES[0]!, QUERY_TIMES[0]),
  );
});

test("an earlier valid time asks a different question", () => {
  // More knowledge over the same window can reach a LATER observation: one inside the
  // window may simply not have arrived by the earlier cutoff.
  const late = asOfSnapshot(records(), QUERY_TIMES[2]!, QUERY_TIMES[0]);
  const early = asOfSnapshot(records(), QUERY_TIMES[0]!, QUERY_TIMES[0]);
  assert.equal(late.length, 3);
  assert.equal(early.length, 3);
  late.forEach((later, index) => {
    assert.equal(later.entity, early[index]!.entity);
    assert.ok(later.observation_time >= early[index]!.observation_time);
  });
  assert.ok(late[0]!.observation_time > early[0]!.observation_time);
});

test("the boundary instants are inclusive", () => {
  const rows = [record({ record_id: "A", available_at: "2026-01-04T00:00:00Z" })];
  assert.equal(asOfSnapshot(rows, "2026-01-04T00:00:00Z").length, 1);
  assert.equal(asOfSnapshot(rows, "2026-01-03T23:59:59Z").length, 0);
});

test("an empty result is the answer not a null", () => {
  assert.deepEqual(asOfSnapshot(records(), "2020-01-01T00:00:00Z"), []);
});

// --- revision resolution ------------------------------------------------------ //
test("the latest knowable revision wins", () => {
  const rows = [
    record({ record_id: "r0", revision: 0, available_at: "2026-01-04T00:00:00Z", value: 10 }),
    record({ record_id: "r1", revision: 1, available_at: "2026-01-11T00:00:00Z", value: 10.5 }),
    record({ record_id: "r2", revision: 2, available_at: "2026-01-30T00:00:00Z", value: 11 }),
  ];
  assert.equal(asOfSnapshot(rows, "2026-01-12T00:00:00Z")[0]!.record_id, "r1");
  assert.equal(asOfSnapshot(rows, "2026-02-01T00:00:00Z")[0]!.record_id, "r2");
});

test("a later observation beats an older revision", () => {
  const rows = [
    record({ record_id: "old-r2", observation_time: "2026-01-02T00:00:00Z", revision: 2,
             available_at: "2026-01-20T00:00:00Z", value: 10 }),
    record({ record_id: "new-r0", observation_time: "2026-01-09T00:00:00Z", revision: 0,
             available_at: "2026-01-11T00:00:00Z", value: 20 }),
  ];
  assert.equal(asOfSnapshot(rows, "2026-01-25T00:00:00Z")[0]!.record_id, "new-r0");
});

test("the record_id tiebreak makes it deterministic", () => {
  // Without it, two records sharing an arrival and revision resolve by input order.
  const rows = [
    record({ record_id: "bbb", available_at: "2026-01-04T00:00:00Z", value: 1 }),
    record({ record_id: "aaa", available_at: "2026-01-04T00:00:00Z", value: 2 }),
  ];
  const forward = asOfSnapshot(rows, "2026-01-10T00:00:00Z");
  const backward = asOfSnapshot([...rows].reverse(), "2026-01-10T00:00:00Z");
  assert.deepEqual(forward, backward);
  assert.equal(forward[0]!.record_id, "bbb");
});

test("input order never changes the snapshot", () => {
  const rows = records();
  assert.deepEqual(
    asOfSnapshot(rows, QUERY_TIMES[1]!),
    asOfSnapshot([...rows].reverse(), QUERY_TIMES[1]!),
  );
});

test("series are resolved independently", () => {
  const rows = [
    record({ record_id: "a", entity: "ALFA", value: 1 }),
    record({ record_id: "b", entity: "BETA", value: 2 }),
    record({ record_id: "c", entity: "ALFA", feature: "other", value: 3 }),
  ];
  assert.equal(asOfSnapshot(rows, "2026-01-10T00:00:00Z").length, 3);
});

// --- validation ---------------------------------------------------------------- //
for (const field of [...REQUIRED_FIELDS].sort()) {
  test(`a missing ${field} throws`, () => {
    const row = record() as unknown as Record<string, unknown>;
    delete row[field];
    assert.throws(() => validateRecords([row]), /missing fields/);
  });
}

for (const field of ["entity", "feature", "record_id"]) {
  for (const value of ["", 7, null] as unknown[]) {
    test(`a bad ${field} throws (${String(value)})`, () => {
      const row = record() as unknown as Record<string, unknown>;
      row[field] = value;
      assert.throws(() => validateRecords([row]), new RegExp(`invalid ${field}`));
    });
  }
}

test("a duplicate record_id throws", () => {
  // It is the final tiebreak; duplicates make the answer order-dependent.
  assert.throws(
    () => validateRecords([record({ record_id: "X" }), record({ record_id: "X", value: 2 })]),
    /duplicate record_id/,
  );
});

for (const bad of [-1, 1.5, "0", true, null] as unknown[]) {
  test(`a bad revision throws (${String(bad)})`, () => {
    const row = record() as unknown as Record<string, unknown>;
    row.revision = bad;
    assert.throws(() => validateRecords([row]), /invalid revision/);
  });
}

for (const bad of ["10", null, true, NaN, Infinity] as unknown[]) {
  test(`a bad value throws (${String(bad)})`, () => {
    const row = record() as unknown as Record<string, unknown>;
    row.value = bad;
    assert.throws(() => validateRecords([row]), /invalid value/);
  });
}

test("a non-mapping record throws", () => {
  assert.throws(() => validateRecords(["nope"]), /must be a mapping/);
});

test("input rows are never mutated", () => {
  const rows = records();
  const before = JSON.stringify(rows);
  asOfSnapshot(rows, QUERY_TIMES[0]!);
  leakageAudit(rows, QUERY_TIMES[0]!);
  assert.equal(JSON.stringify(rows), before);
});

test("the leakage audit does not mutate the originals", () => {
  const rows = [record({ record_id: "A", available_at: "2026-02-01T00:00:00Z" })];
  leakageAudit(rows, "2026-01-10T00:00:00Z");
  assert.ok(!("reason" in rows[0]!));
});

// --- timestamps ----------------------------------------------------------------- //
test("a naive timestamp is refused not assumed UTC", () => {
  // Guessing a zone here shifts the cutoff.
  assert.throws(() => parseTimestampMs("2026-01-02T00:00:00"), /must include a UTC offset/);
});

test("an impossible calendar date is rejected", () => {
  assert.throws(() => parseTimestampMs("2026-02-30T00:00:00Z"), /invalid/);
});

test("an offset is normalised to UTC", () => {
  assert.equal(
    parseTimestampMs("2026-01-02T05:00:00+05:00"),
    parseTimestampMs("2026-01-02T00:00:00Z"),
  );
});

test("a negative offset is normalised too", () => {
  assert.equal(
    parseTimestampMs("2026-01-01T19:00:00-05:00"),
    parseTimestampMs("2026-01-02T00:00:00Z"),
  );
});

for (const timestamp of [
  "not-a-time", "", null, 0, "2026-13-02T00:00:00Z", "2026-01-02",
] as unknown[]) {
  test(`a malformed timestamp is rejected (${JSON.stringify(timestamp)})`, () => {
    assert.throws(() => parseTimestampMs(timestamp));
  });
}

test("fractional seconds are kept", () => {
  assert.equal(
    parseTimestampMs("2026-01-02T00:00:00.250Z") - parseTimestampMs("2026-01-02T00:00:00Z"),
    250,
  );
});
