/** Shared fixture access. The same JSON backs the Python suite. */

import { createRequire } from "node:module";

import { type LeakedRecord, type PitRecord, asOfSnapshot } from "../src/core.ts";

const require = createRequire(import.meta.url);
const FIXTURE = require("./fixtures/fixtures.json") as {
  records: PitRecord[];
  query_times: string[];
  cases: Array<{
    knowledge_time: string;
    valid_time: string | null;
    expected_snapshot: PitRecord[];
    expected_leakage: LeakedRecord[];
  }>;
};

export const RECORDS = FIXTURE.records;
export const QUERY_TIMES = FIXTURE.query_times;
export const CASES = FIXTURE.cases;

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

export const records = (): PitRecord[] => clone(RECORDS);

export const testCase = (knowledgeTime: string) =>
  clone(CASES.find((row) => row.knowledge_time === knowledgeTime)!);

export const record = (overrides: Partial<PitRecord> = {}): PitRecord => ({
  record_id: "R1",
  entity: "ALFA",
  feature: "weekly_metric",
  observation_time: "2026-01-02T00:00:00Z",
  available_at: "2026-01-04T00:00:00Z",
  revision: 0,
  value: 10.0,
  ...overrides,
});

export const snapshot = (
  rows?: unknown[] | null,
  knowledgeTime?: string,
  validTime?: string | null,
): PitRecord[] =>
  asOfSnapshot(rows ?? records(), knowledgeTime ?? QUERY_TIMES[0]!, validTime);
