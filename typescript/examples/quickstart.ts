/**
 * Build a point-in-time panel, then prove it did not cheat.
 *
 * Run:  npm run example
 */

import { createRequire } from "node:module";

import {
  type PitRecord,
  asOfSnapshot,
  buildPanel,
  leakageReport,
  publicationLag,
  restatementHistory,
  vintageDiff,
} from "../src/index.ts";

const require = createRequire(import.meta.url);
const FIXTURE = require("../test/fixtures/fixtures.json") as {
  records: PitRecord[];
  query_times: string[];
};
const { records: RECORDS, query_times: QUERY_TIMES } = FIXTURE;

const rule = (title: string) => console.log(`\n${title}\n${"-".repeat(title.length)}`);
const pad = (value: unknown, width: number) => String(value).padEnd(width);
const padStart = (value: unknown, width: number) => String(value).padStart(width);
const pct = (value: number) => `${Math.round(value * 100)}%`;

// --- 1. what the guard withholds --------------------------------------------- //
rule("1. The lookahead you are NOT taking");

for (const knowledgeTime of QUERY_TIMES) {
  const report = leakageReport(RECORDS, knowledgeTime);
  console.log(
    `  as of ${knowledgeTime.slice(0, 10)}: ` +
      `${padStart(report.valid_time_matches, 3)} records match by observation time, ` +
      `${padStart(report.withheld, 2)} withheld (${pct(report.withheld_share)})`,
  );
}
console.log("  Those withheld records are data about the past that had not been published.");

// --- 2. the snapshot --------------------------------------------------------- //
rule("2. One row per series, latest observation, latest knowable revision");

for (const row of asOfSnapshot(RECORDS, QUERY_TIMES[0]!)) {
  console.log(
    `  ${pad(row.entity, 6)} obs=${row.observation_time.slice(0, 10)} ` +
      `rev=${row.revision} value=${pad(row.value, 7)} ` +
      `(known since ${row.available_at.slice(0, 10)})`,
  );
}

// --- 3. the same window, more knowledge -------------------------------------- //
rule("3. More knowledge about the SAME window");

const early = asOfSnapshot(RECORDS, QUERY_TIMES[0]!, QUERY_TIMES[0]);
const late = asOfSnapshot(RECORDS, QUERY_TIMES[2]!, QUERY_TIMES[0]);
early.forEach((a, index) => {
  const b = late[index]!;
  console.log(
    `  ${pad(a.entity, 6)} at ${QUERY_TIMES[0]!.slice(0, 10)}: ` +
      `obs=${a.observation_time.slice(0, 10)} value=${pad(a.value, 7)} ` +
      `-> at ${QUERY_TIMES[2]!.slice(0, 10)}: obs=${b.observation_time.slice(0, 10)} value=${b.value}`,
  );
});
console.log("  A later observation appears - it was valid all along, it just had not arrived.");

// --- 4. would the backtest reproduce? ---------------------------------------- //
rule("4. Vintage diff: same query, two run dates");

const diff = vintageDiff(RECORDS, QUERY_TIMES[0]!, QUERY_TIMES[2]!);
console.log(
  `  reproducible: ${diff.reproducible}   ` +
    `${diff.changed.length} changed, ${diff.appeared.length} appeared`,
);
for (const row of diff.changed.slice(0, 3)) {
  const sign = row.delta >= 0 ? "+" : "";
  console.log(
    `    ${pad(row.entity, 6)} ${row.earlier_value} -> ${row.later_value} ` +
      `(delta ${sign}${row.delta.toFixed(2)})`,
  );
}
console.log("  A run in February and a re-run in May over the identical window disagree.");
console.log("  Neither is wrong. That is what restatement means.");

// --- 5. the revision trail ---------------------------------------------------- //
rule("5. What one number did after you acted on it");

const history = restatementHistory(RECORDS, "ALFA", "weekly_metric", "2026-01-02T00:00:00Z");
for (const version of history.versions) {
  const change =
    version.change_from_previous === null
      ? ""
      : `  (${version.change_from_previous >= 0 ? "+" : ""}${version.change_from_previous.toFixed(2)})`;
  console.log(
    `  rev ${version.revision}  arrived ${version.available_at.slice(0, 10)} ` +
      `(+${version.lag_days.toFixed(1)}d)  value ${version.value}${change}`,
  );
}
console.log(
  `  total drift from first print: ${history.total_drift! >= 0 ? "+" : ""}${history.total_drift!.toFixed(2)}`,
);

// --- 6. how late is the data? ------------------------------------------------- //
rule("6. Publication lag");

const lag = publicationLag(RECORDS);
console.log(
  `  first prints: median ${lag.first_print.median_days!.toFixed(1)}d  ` +
    `max ${lag.first_print.max_days!.toFixed(1)}d`,
);
console.log(
  `  all records:  median ${lag.overall.median_days!.toFixed(1)}d  ` +
    `max ${lag.overall.max_days!.toFixed(1)}d`,
);
console.log("  Model the median. The maximum is the one that breaks a short rebalance.");

// --- 7. the panel ------------------------------------------------------------- //
rule("7. The panel a backtest actually consumes");

const panel = buildPanel(RECORDS, QUERY_TIMES);
for (const point of panel.coverage) {
  console.log(
    `  ${point.knowledge_time.slice(0, 10)}: ${point.series} series, ${point.entities} entities`,
  );
}
console.log(`  ${panel.total_rows} rows total, complete=${panel.complete}`);
console.log("  Each row carries the knowledge_time that produced it, so the panel stays");
console.log("  self-describing after it leaves this function.");
