"""Build a point-in-time panel, then prove it did not cheat.

Run:  python examples/quickstart.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fintech_point_in_time import (  # noqa: E402
    as_of_snapshot,
    build_panel,
    leakage_report,
    publication_lag,
    restatement_history,
    vintage_diff,
)

FIXTURE = json.loads(
    (ROOT / "tests" / "fixtures" / "fixtures.json").read_text(encoding="utf-8")
)
RECORDS = FIXTURE["records"]
QUERY_TIMES = FIXTURE["query_times"]


def rule(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


# --- 1. what the guard withholds --------------------------------------------- #
rule("1. The lookahead you are NOT taking")

for knowledge_time in QUERY_TIMES:
    report = leakage_report(RECORDS, knowledge_time)
    print(f"  as of {knowledge_time[:10]}: "
          f"{report['valid_time_matches']:>3} records match by observation time, "
          f"{report['withheld']:>2} withheld ({report['withheld_share']:.0%})")
print("  Those withheld records are data about the past that had not been published.")

# --- 2. the snapshot --------------------------------------------------------- #
rule("2. One row per series, latest observation, latest knowable revision")

for row in as_of_snapshot(RECORDS, QUERY_TIMES[0]):
    print(f"  {row['entity']:<6} obs={row['observation_time'][:10]} "
          f"rev={row['revision']} value={row['value']:<7} "
          f"(known since {row['available_at'][:10]})")

# --- 3. the same window, more knowledge -------------------------------------- #
rule("3. More knowledge about the SAME window")

early = as_of_snapshot(RECORDS, QUERY_TIMES[0], QUERY_TIMES[0])
late = as_of_snapshot(RECORDS, QUERY_TIMES[2], QUERY_TIMES[0])
for a, b in zip(early, late):
    print(f"  {a['entity']:<6} at {QUERY_TIMES[0][:10]}: obs={a['observation_time'][:10]} "
          f"value={a['value']:<7} -> at {QUERY_TIMES[2][:10]}: "
          f"obs={b['observation_time'][:10]} value={b['value']}")
print("  A later observation appears — it was valid all along, it just had not arrived.")

# --- 4. would the backtest reproduce? ---------------------------------------- #
rule("4. Vintage diff: same query, two run dates")

diff = vintage_diff(RECORDS, QUERY_TIMES[0], QUERY_TIMES[2])
print(f"  reproducible: {diff['reproducible']}   "
      f"{len(diff['changed'])} changed, {len(diff['appeared'])} appeared")
for row in diff["changed"][:3]:
    print(f"    {row['entity']:<6} {row['earlier_value']} -> {row['later_value']} "
          f"(delta {row['delta']:+.2f})")
print("  A run in February and a re-run in May over the identical window disagree.")
print("  Neither is wrong. That is what restatement means.")

# --- 5. the revision trail ---------------------------------------------------- #
rule("5. What one number did after you acted on it")

history = restatement_history(RECORDS, "ALFA", "weekly_metric", "2026-01-02T00:00:00Z")
for version in history["versions"]:
    change = ("" if version["change_from_previous"] is None
              else f"  ({version['change_from_previous']:+.2f})")
    print(f"  rev {version['revision']}  arrived {version['available_at'][:10]} "
          f"(+{version['lag_days']:.1f}d)  value {version['value']}{change}")
print(f"  total drift from first print: {history['total_drift']:+.2f}")

# --- 6. how late is the data? ------------------------------------------------- #
rule("6. Publication lag")

lag = publication_lag(RECORDS)
print(f"  first prints: median {lag['first_print']['median_days']:.1f}d  "
      f"max {lag['first_print']['max_days']:.1f}d")
print(f"  all records:  median {lag['overall']['median_days']:.1f}d  "
      f"max {lag['overall']['max_days']:.1f}d")
print("  Model the median. The maximum is the one that breaks a short rebalance.")

# --- 7. the panel ------------------------------------------------------------- #
rule("7. The panel a backtest actually consumes")

panel = build_panel(RECORDS, QUERY_TIMES)
for point in panel["coverage"]:
    print(f"  {point['knowledge_time'][:10]}: {point['series']} series, "
          f"{point['entities']} entities")
print(f"  {panel['total_rows']} rows total, complete={panel['complete']}")
print("  Each row carries the knowledge_time that produced it, so the panel stays")
print("  self-describing after it leaves this function.")
