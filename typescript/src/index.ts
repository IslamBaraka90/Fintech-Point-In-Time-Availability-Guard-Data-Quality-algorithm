/**
 * Point-in-time filtering that keeps valid time separate from knowledge time.
 *
 * Every record carries two timestamps that mean different things: `observation_time`
 * (when it was true) and `available_at` (when you could first have used it). A backtest
 * filtering on only the first is a report on what you would have earned knowing things
 * you did not know.
 *
 * ```ts
 * import { asOfSnapshot, leakageAudit } from "fintech-point-in-time";
 *
 * const rows = asOfSnapshot(records, "2026-02-01T12:00:00Z");
 * const withheld = leakageAudit(records, "2026-02-01T12:00:00Z");
 * ```
 *
 * Article: https://thefintechbuilder.com/market-data-engineering/data-quality/point-in-time-availability-guard/
 */

export {
  type LeakedRecord,
  type PitRecord,
  REQUIRED_FIELDS,
  asOfSnapshot,
  leakageAudit,
  parseTimestampMs,
  validateRecords,
} from "./core.ts";

export {
  type CoveragePoint,
  type LagStats,
  type LeakageReport,
  type Panel,
  type PublicationLag,
  type RestatementHistory,
  type RevisionStep,
  type VintageDiff,
  buildPanel,
  leakageReport,
  publicationLag,
  restatementHistory,
  vintageDiff,
} from "./backtest.ts";
