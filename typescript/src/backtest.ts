/**
 * From one honest snapshot to a whole honest backtest.
 *
 * **The panel** — {@link buildPanel}
 * One snapshot per rebalance date, stacked. `coverage` reports how many series each
 * instant resolved — a falling count is a feed going dark, and it is invisible once the
 * rows are concatenated.
 *
 * **What the data said, and what it says now** — {@link restatementHistory}
 * The revision trail for one observation. A feature whose first print is routinely
 * revised is not the feature you backtested.
 *
 * **Would this backtest reproduce?** — {@link vintageDiff}
 * The same query at two knowledge times. Any series whose value changed was restated in
 * between — which means the run you did in March cannot be reproduced in June, and
 * neither result is wrong.
 *
 * **How late is the data, really?** — {@link publicationLag}
 * The median is the delay you should be modelling; the maximum is the one that breaks
 * you.
 *
 * **How much lookahead did you avoid?** — {@link leakageReport}
 * A large `withheld_share` is not a problem — it is the guard working.
 */

import {
  type LeakedRecord,
  type PitRecord,
  asOfSnapshot,
  leakageAudit,
  parseTimestampMs,
  validateRecords,
} from "./core.ts";

const MS_PER_DAY = 86_400_000;

export interface CoveragePoint {
  knowledge_time: string;
  valid_time: string;
  series: number;
  entities: number;
}

export interface Panel {
  rows: Array<PitRecord & { knowledge_time: string }>;
  coverage: CoveragePoint[];
  knowledge_times: string[];
  total_rows: number;
  min_series: number;
  max_series: number;
  complete: boolean;
}

export interface RevisionStep {
  record_id: string;
  revision: number;
  available_at: string;
  value: number;
  change_from_previous: number | null;
  lag_days: number;
}

export interface RestatementHistory {
  entity: string;
  feature: string;
  observation_time: string;
  versions: RevisionStep[];
  revision_count: number;
  first_value: number | null;
  final_value: number | null;
  total_drift: number | null;
  was_restated: boolean;
}

export interface VintageDiff {
  earlier_knowledge_time: string;
  later_knowledge_time: string;
  valid_time: string;
  series_compared: number;
  changed: Array<{
    entity: string;
    feature: string;
    observation_time: string;
    earlier_record_id: string;
    later_record_id: string;
    earlier_value: number;
    later_value: number;
    delta: number;
  }>;
  appeared: Array<{ entity: string; feature: string; value: number }>;
  reproducible: boolean;
  max_abs_delta: number | null;
}

export interface LagStats {
  count: number;
  min_days: number | null;
  median_days: number | null;
  mean_days: number | null;
  max_days: number | null;
}

export interface PublicationLag {
  overall: LagStats;
  first_print: LagStats;
  by_feature: Record<string, LagStats>;
  negative_lags: number;
}

export interface LeakageReport {
  knowledge_time: string;
  valid_time: string;
  total_records: number;
  valid_time_matches: number;
  withheld: number;
  withheld_share: number;
  by_entity: Record<string, number>;
  by_feature: Record<string, number>;
  clean: boolean;
}

const compare = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

const median = (values: number[]): number => {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[middle - 1]! + sorted[middle]!) / 2
    : sorted[middle]!;
};

const sortedRecord = <T>(record: Record<string, T>): Record<string, T> =>
  Object.fromEntries(Object.entries(record).sort(([a], [b]) => compare(a, b)));

/** One as-of snapshot per knowledge time, stacked into a point-in-time panel. */
export function buildPanel(
  records: Iterable<unknown>,
  knowledgeTimes: readonly string[],
  validTimes?: readonly (string | null)[] | null,
): Panel {
  const recordList = validateRecords(records);
  const cutoffs = [...knowledgeTimes];
  if (cutoffs.length === 0) throw new Error("knowledge_times must not be empty");
  const validList = validTimes ? [...validTimes] : cutoffs.map(() => null);
  if (validList.length !== cutoffs.length) {
    throw new Error("valid_times must match knowledge_times in length");
  }

  const rows: Array<PitRecord & { knowledge_time: string }> = [];
  const coverage: CoveragePoint[] = [];

  cutoffs.forEach((knowledgeTime, index) => {
    const validTime = validList[index] ?? null;
    const snapshot = asOfSnapshot(recordList, knowledgeTime, validTime);
    for (const record of snapshot) rows.push({ ...record, knowledge_time: knowledgeTime });
    coverage.push({
      knowledge_time: knowledgeTime,
      valid_time: validTime || knowledgeTime,
      series: snapshot.length,
      entities: new Set(snapshot.map((row) => row.entity)).size,
    });
  });

  const seriesCounts = coverage.map((point) => point.series);
  return {
    rows,
    coverage,
    knowledge_times: cutoffs,
    total_rows: rows.length,
    // A falling series count is a feed going dark, and it disappears the moment the
    // rows are concatenated into one frame.
    min_series: Math.min(...seriesCounts),
    max_series: Math.max(...seriesCounts),
    complete: new Set(seriesCounts).size === 1,
  };
}

/**
 * The full revision trail for one observation: every version and when it landed.
 *
 * `total_drift` is the distance from the first print to the last — the number that says
 * whether the feature you backtested is the feature you have.
 */
export function restatementHistory(
  records: Iterable<unknown>,
  entity: string,
  feature: string,
  observationTime: string,
): RestatementHistory {
  const rows = validateRecords(records);
  const target = parseTimestampMs(observationTime, "observation_time");

  const versions = rows
    .filter(
      (row) =>
        row.entity === entity &&
        row.feature === feature &&
        parseTimestampMs(row.observation_time) === target,
    )
    .sort((a, b) => {
      const arrival = parseTimestampMs(a.available_at) - parseTimestampMs(b.available_at);
      if (arrival !== 0) return arrival;
      if (a.revision !== b.revision) return a.revision - b.revision;
      return compare(a.record_id, b.record_id);
    });

  const trail: RevisionStep[] = versions.map((row, index) => {
    const previous = index ? versions[index - 1]! : null;
    return {
      record_id: row.record_id,
      revision: row.revision,
      available_at: row.available_at,
      value: row.value,
      change_from_previous: previous ? row.value - previous.value : null,
      lag_days: (parseTimestampMs(row.available_at) - target) / MS_PER_DAY,
    };
  });

  const first = versions.length ? versions[0]!.value : null;
  const last = versions.length ? versions.at(-1)!.value : null;
  return {
    entity,
    feature,
    observation_time: observationTime,
    versions: trail,
    revision_count: trail.length,
    first_value: first,
    final_value: last,
    // How far the number moved after you first acted on it.
    total_drift: versions.length ? last! - first! : null,
    was_restated: trail.length > 1,
  };
}

/**
 * Diff two vintages of the same query: would this backtest reproduce?
 *
 * Both snapshots use the **same** `validTime`, so the comparison isolates *what you
 * learned in between* rather than mixing in new observations.
 */
export function vintageDiff(
  records: Iterable<unknown>,
  earlierKnowledgeTime: string,
  laterKnowledgeTime: string,
  validTime?: string | null,
): VintageDiff {
  const recordList = validateRecords(records);
  const earlierMs = parseTimestampMs(earlierKnowledgeTime, "earlier_knowledge_time");
  const laterMs = parseTimestampMs(laterKnowledgeTime, "later_knowledge_time");
  if (laterMs < earlierMs) {
    throw new Error("later_knowledge_time must not precede earlier_knowledge_time");
  }

  const sharedValid = validTime || earlierKnowledgeTime;
  const keyOf = (row: PitRecord) => `${row.entity} ${row.feature}`;
  const earlier = new Map(
    asOfSnapshot(recordList, earlierKnowledgeTime, sharedValid).map((r) => [keyOf(r), r]),
  );
  const later = new Map(
    asOfSnapshot(recordList, laterKnowledgeTime, sharedValid).map((r) => [keyOf(r), r]),
  );

  const changed: VintageDiff["changed"] = [];
  const appeared: VintageDiff["appeared"] = [];
  const keys = [...new Set([...earlier.keys(), ...later.keys()])].sort(compare);

  for (const key of keys) {
    const before = earlier.get(key);
    const after = later.get(key);
    if (!before) {
      appeared.push({ entity: after!.entity, feature: after!.feature, value: after!.value });
      continue;
    }
    if (!after || before.record_id === after.record_id) continue;
    changed.push({
      entity: before.entity,
      feature: before.feature,
      observation_time: before.observation_time,
      earlier_record_id: before.record_id,
      later_record_id: after.record_id,
      earlier_value: before.value,
      later_value: after.value,
      delta: after.value - before.value,
    });
  }

  return {
    earlier_knowledge_time: earlierKnowledgeTime,
    later_knowledge_time: laterKnowledgeTime,
    valid_time: sharedValid,
    series_compared: keys.length,
    changed,
    // Series absent at the earlier vintage: data that had not arrived at all yet.
    appeared,
    // True when the same window produces the same numbers at both vintages.
    reproducible: changed.length === 0 && appeared.length === 0,
    max_abs_delta: changed.length
      ? Math.max(...changed.map((row) => Math.abs(row.delta)))
      : null,
  };
}

/**
 * The distribution of `available_at − observation_time`, overall and per feature.
 *
 * The median is the delay you should be modelling. The **maximum** is the one that
 * breaks you. Only first prints are counted in `first_print`, since a later revision's
 * lag measures the restatement, not the publication.
 */
export function publicationLag(records: Iterable<unknown>): PublicationLag {
  const rows = validateRecords(records);
  if (rows.length === 0) throw new Error("records must not be empty");

  const stats = (values: number[]): LagStats =>
    values.length === 0
      ? { count: 0, min_days: null, median_days: null, mean_days: null, max_days: null }
      : {
          count: values.length,
          min_days: Math.min(...values),
          median_days: median(values),
          mean_days: values.reduce((a, b) => a + b, 0) / values.length,
          max_days: Math.max(...values),
        };

  const lag = (row: PitRecord) =>
    (parseTimestampMs(row.available_at) - parseTimestampMs(row.observation_time)) / MS_PER_DAY;

  const allLags = rows.map(lag);
  const firstPrints = rows.filter((row) => row.revision === 0).map(lag);

  const byFeature: Record<string, number[]> = {};
  for (const row of rows) (byFeature[row.feature] ??= []).push(lag(row));

  return {
    overall: stats(allLags),
    // The lag that decides whether the feature is usable at all.
    first_print: stats(firstPrints),
    by_feature: sortedRecord(
      Object.fromEntries(Object.entries(byFeature).map(([k, v]) => [k, stats(v)])),
    ),
    negative_lags: allLags.filter((value) => value < 0).length,
  };
}

/**
 * Roll up the leakage audit: how much lookahead the guard actually withheld.
 *
 * A large `withheld_share` is not a problem — it is the guard working, and it is the
 * figure to put in front of anyone who thinks point-in-time filtering is a formality.
 */
export function leakageReport(
  records: Iterable<unknown>,
  knowledgeTime: string,
  validTime?: string | null,
): LeakageReport {
  const rows = validateRecords(records);
  const leaked: LeakedRecord[] = leakageAudit(rows, knowledgeTime, validTime);
  const validCutoff = parseTimestampMs(validTime || knowledgeTime, "valid_time");
  const validRecords = rows.filter(
    (row) => parseTimestampMs(row.observation_time) <= validCutoff,
  );

  const byEntity: Record<string, number> = {};
  const byFeature: Record<string, number> = {};
  for (const row of leaked) {
    byEntity[row.entity] = (byEntity[row.entity] ?? 0) + 1;
    byFeature[row.feature] = (byFeature[row.feature] ?? 0) + 1;
  }

  return {
    knowledge_time: knowledgeTime,
    valid_time: validTime || knowledgeTime,
    total_records: rows.length,
    // What a valid-time-only filter would have admitted.
    valid_time_matches: validRecords.length,
    withheld: leaked.length,
    withheld_share: validRecords.length ? leaked.length / validRecords.length : 0,
    by_entity: sortedRecord(byEntity),
    by_feature: sortedRecord(byFeature),
    clean: leaked.length === 0,
  };
}
