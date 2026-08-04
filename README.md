# Fintech Point-in-Time Availability Guard — Data Quality Algorithm

> A canonical, well-specified, **cross-language (Python + TypeScript)** reference
> implementation of bitemporal point-in-time filtering. Every record carries **two**
> timestamps that mean different things — `observation_time` (when it was true) and
> `available_at` (when you could first have used it) — and a backtest filtering on only
> the first is not a backtest. It is a report on what you would have earned knowing
> things you did not know. The two cutoffs are **separate arguments**, revisions resolve
> in a stated deterministic order, and a `leakage_audit` shows you the lookahead you are
> *not* taking. On the reference fixture that is **47% of otherwise-matching records**.

<p>
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-blue">
  <img alt="TypeScript" src="https://img.shields.io/badge/typescript-5.7%2B-3178c6">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
  <img alt="Tests" src="https://img.shields.io/badge/tests-89%20py%20%2F%2089%20ts-brightgreen">
</p>

**📖 Full article (canonical):** **[Point-in-Time Availability Guard — The Fintech Builder](https://thefintechbuilder.com/market-data-engineering/data-quality/point-in-time-availability-guard/)**

This repository is the runnable, production-oriented companion to that article.
The article teaches the concept; this repo is the code you install and build on.

🧭 **Browse all algorithms:** [Awesome FinTech Algorithms](https://github.com/IslamBaraka90/Fintech-Algorithms-Awesome) — the full index of the library.
🗂️ **This algorithm's domain:** [Market Data Engineering](https://thefintechbuilder.com/domains/market-data-engineering/) › **Data Quality**
📥 **Just want to call it?** It also ships in the [`fintech-algorithms`](https://www.npmjs.com/package/fintech-algorithms) npm package — see [Two ways to use this](#two-ways-to-use-this).

| | |
|---|---|
| **Catalog topic** | `D01-F04-A05` |
| **Domain** | D01 — Market Data Engineering |
| **Family** | D01-F04 — Data Quality |
| **Difficulty** | 3 / 5 |
| **Languages** | Python, TypeScript |
| **Completes** | every live D01-F04 topic |

---

## Table of contents

- [The two clocks](#the-two-clocks)
- [The two cutoffs are separate arguments](#the-two-cutoffs-are-separate-arguments)
- [Revisions, resolved in a stated order](#revisions-resolved-in-a-stated-order)
- [`available_at` is a declared boundary](#available_at-is-a-declared-boundary)
- [Two ways to use this](#two-ways-to-use-this)
- [Install](#install)
- [Quickstart](#quickstart)
- [Worked example (exact)](#worked-example-exact)
- [Backtest: panels, vintages and lag](#backtest-panels-vintages-and-lag)
- [Record shape](#record-shape)
- [API reference](#api-reference)
- [Edge cases & limitations](#edge-cases--limitations)
- [Testing](#testing)
- [Related algorithms](#related-algorithms)
- [License](#license)

---

## The two clocks

| Field | Meaning |
|---|---|
| `observation_time` | **Valid time** — when the thing was true in the world |
| `available_at` | **Knowledge time** — when your system could first have used it |

Filter on only the first and you get a strategy nobody could have run. The failure is
completely invisible in the output: the numbers are real, the dates are real, and the
result is fiction.

`leakage_audit` makes it visible instead:

```
as of 2026-02-01:  45 records match by observation time, 21 withheld (47%)
as of 2026-03-15:  99 records match by observation time, 21 withheld (21%)
as of 2026-05-31: 180 records match by observation time,  6 withheld (3%)
```

**47%** of the records a naive filter would have admitted at the first query instant had
not been published yet. Run this in tests, not just in research — it is the only way to
see the lookahead you are *not* taking.

---

## The two cutoffs are separate arguments

`as_of_snapshot(records, knowledge_time, valid_time=None)`.

They default to the same instant, which is the common case, but they are genuinely
independent:

- **Same instant** — "what did I know, right now, about now."
- **`valid_time` earlier** — "what do I know *today* about last month", the revised
  view, used deliberately.

Making them separate parameters means the second case has to be *asked for*. It cannot
happen because someone passed one timestamp to a function expecting another.

And the second case is more interesting than it looks:

```
ALFA at 2026-02-01: obs=2026-01-23 value=10.75
ALFA at 2026-05-31: obs=2026-01-30 value=11.14   <- same valid window
```

More knowledge over the *same window* does not just pick up revisions — it reaches a
**later observation**. The 01-30 observation was valid all along; it simply had not
arrived by 02-01. The early view was incomplete about its own window, and that is the gap
a backtest silently inherits.

---

## Revisions, resolved in a stated order

Within one `(entity, feature)` series the guard takes the **latest observation** that is
valid, and then among records for that same observation the latest **knowable** revision
— ordered by `available_at`, then `revision`, then `record_id`.

That final tiebreak on `record_id` is not decoration. Without it, two records sharing an
arrival instant and a revision number would resolve by **input order**, and the same query
would return different answers on different days. Both suites assert that reversing the
input changes nothing.

A series with nothing both valid and knowable simply does not appear. **Its absence is
the answer**, not a null to be filled in downstream.

---

## `available_at` is a declared boundary

It must already represent your system's own **feature-ready** instant.

It is **not** the issuer's filing date and **not** the vendor's publication schedule.
Both of those sit upstream of the delay that actually matters — which includes your
ingestion, your validation and your feature build. Substituting either is the most common
way a pipeline that calls itself point-in-time still leaks.

---

## Two ways to use this

**📥 The fast path — one call, TypeScript only:**

```bash
npm install fintech-algorithms
```

```ts
import { asOfSnapshot } from "fintech-algorithms/market-data-engineering/data-quality/point-in-time-availability-guard";
```

That package is the breadth option: 271 algorithms, one install, the tutorial-level
kernel for each.

**🔬 This repo — the depth option.** Python *and* TypeScript, the `backtest` surface
(panel building, restatement history, vintage diffs, publication-lag analysis, leakage
reporting), and 178 tests pinning both languages to one shared fixture of 180 bitemporal
records with the complete snapshot and audit frozen at three query times.

---

## Install

**Python** (3.10+, no dependencies):

```bash
git clone https://github.com/IslamBaraka90/Fintech-Point-In-Time-Availability-Guard-Data-Quality-algorithm.git
cd Fintech-Point-In-Time-Availability-Guard-Data-Quality-algorithm/python
pip install -e ".[dev]"
```

**TypeScript** (Node 20+, no runtime dependencies):

```bash
cd Fintech-Point-In-Time-Availability-Guard-Data-Quality-algorithm/typescript
npm install
npm run build
```

---

## Quickstart

**Python**

```python
from fintech_point_in_time import as_of_snapshot, leakage_audit

rows = as_of_snapshot(records, knowledge_time="2026-02-01T12:00:00Z")

# Put this in your test suite, not just your notebook.
withheld = leakage_audit(records, "2026-02-01T12:00:00Z")
print(f"{len(withheld)} records correctly withheld")
```

**TypeScript**

```ts
import { asOfSnapshot, leakageAudit } from "fintech-point-in-time";

const rows = asOfSnapshot(records, "2026-02-01T12:00:00Z");
console.log(leakageAudit(records, "2026-02-01T12:00:00Z").length);
```

---

## Worked example (exact)

180 bitemporal records — 3 entities × 20 observations × 3 releases — with the complete
snapshot and leakage audit frozen at three query times. Asserted verbatim by both suites.

```
2. One row per series, latest observation, latest knowable revision

ALFA   obs=2026-01-23 rev=0 value=10.75   (known since 2026-01-25)
BETA   obs=2026-01-23 rev=0 value=13.75   (known since 2026-01-25)
GAMM   obs=2026-01-23 rev=0 value=16.75   (known since 2026-01-25)
```

**The revision trail for a single observation:**

```
rev 0  arrived 2026-01-04 (+2.6d)   value 10.0
rev 1  arrived 2026-01-11 (+9.6d)   value 10.07  (+0.07)
rev 2  arrived 2026-01-30 (+28.6d)  value 10.14  (+0.07)
total drift from first print: +0.14
```

The number you acted on was 10.0. The number in the final dataset is 10.14. Both are
correct; only one of them was knowable when the decision was made.

---

## Backtest: panels, vintages and lag

This is the surface that does not fit in a tutorial, and the reason to install the repo
rather than copy the snippet.

### `vintage_diff` — would this backtest reproduce?

```
reproducible: False   3 changed, 0 appeared
ALFA   10.75 -> 11.14 (delta +0.39)
BETA   13.75 -> 14.14 (delta +0.39)
GAMM   16.75 -> 17.14 (delta +0.39)
```

Run the same query at two knowledge times, holding `valid_time` fixed so the comparison
isolates **what you learned in between** rather than what newly happened.

A backtest run in February and re-run in May over the identical window disagrees. Neither
result is wrong. That is what restatement means, and it is why "just re-run it" is not a
reproducibility strategy.

### `restatement_history` — what one number did after you acted on it

Every version, when it arrived, how far it moved, and the `total_drift` from first print
to final. A feature whose first print is routinely revised is **not the feature you
backtested**, whatever the final values say.

### `publication_lag` — how late is the data, really?

```
first prints: median 2.6d  max  2.7d
all records:  median 9.6d  max 28.7d
```

The median is the delay you should be modelling. The **maximum** is the one that breaks
you — a feature with a 2-day median and a 40-day tail cannot be used on a 3-day rebalance
whatever the median says.

First prints are measured separately, because a later revision's lag measures the
*restatement*, not the publication.

### `build_panel` — the object a backtest actually consumes

One snapshot per rebalance date, stacked, with every row stamped with the
`knowledge_time` that produced it so the panel stays self-describing after it leaves the
function.

`coverage` reports how many series each instant resolved. A falling count is a feed going
dark — and it is completely invisible once the rows are concatenated into one frame.

### `leakage_report` — the number to show a sceptic

Rolls up the audit by entity and feature. A large `withheld_share` is not a problem; it
is the guard working, and it is the figure to put in front of anyone who thinks
point-in-time filtering is a formality.

---

## Record shape

`entity`, `feature`, `record_id` (non-empty strings), `observation_time`, `available_at`
(ISO-8601 with a **mandatory** offset), `revision` (integer ≥ 0), `value` (finite
number).

A naive timestamp is **refused**, not assumed to be UTC — guessing a zone here shifts the
cutoff, which is the entire quantity being measured. Offsets like `+05:00` are accepted
and normalised.

`record_id` uniqueness is enforced because it is the final tiebreak in revision
resolution; duplicates would make the answer order-dependent.

Timestamps are validated by explicit civil arithmetic rather than `Date.parse`, which
rolls `2026-02-30` over to March 2.

---

## API reference

| Python | TypeScript | Purpose |
|---|---|---|
| `as_of_snapshot(records, knowledge_time, valid_time=None)` | `asOfSnapshot(...)` | The point-in-time view |
| `leakage_audit(records, knowledge_time, valid_time=None)` | `leakageAudit(...)` | What was withheld |
| `validate_records(records)` | `validateRecords(...)` | Reject an unfilterable set |
| `build_panel(records, knowledge_times, valid_times=None)` | `buildPanel(...)` | Stacked snapshots + coverage |
| `restatement_history(records, entity, feature, observation_time)` | `restatementHistory(...)` | The revision trail |
| `vintage_diff(records, earlier, later, valid_time=None)` | `vintageDiff(...)` | Reproducibility |
| `publication_lag(records)` | `publicationLag(...)` | Lag distribution |
| `leakage_report(records, knowledge_time, valid_time=None)` | `leakageReport(...)` | Withholding roll-up |
| `parse_timestamp_ms(value)` | `parseTimestampMs(...)` | Strict ISO-8601 → milliseconds |

---

## Edge cases & limitations

- **`available_at` is your input to get right.** The whole guarantee rests on it being
  your genuine feature-ready instant. This package cannot detect a filing date wearing
  that field's name.
- **One value per series per snapshot.** This resolves *which* record is knowable; it
  does not aggregate, interpolate or carry forward — see [Previous-Tick Interpolation](https://github.com/IslamBaraka90/Fintech-Previous-Tick-Interpolation-Time-Synchronization-algorithm) for the carry-forward question.
- **An absent series is absent.** No null row is emitted, because a null and "we had
  nothing" are different facts and downstream code treats them differently.
- **Restatements are surfaced, not resolved.** `vintage_diff` tells you two runs
  disagree; deciding which vintage your research should quote is yours.
- **No entity survivorship handling.** A universe that only lists entities alive today is
  a different bias, upstream of this one, and this guard cannot see it.
- **Panels are built in memory.** For a large universe crossed with many rebalance dates
  this is the wrong shape; the per-instant `as_of_snapshot` is the piece to push into
  your query layer.

---

## Testing

```bash
cd python && pytest -q          # 89 tests
cd typescript && npm test       # 89 tests
```

Both suites read the **same** `fixtures.json` and assert the complete snapshot and the
complete leakage audit at all three query times, record for record, in each language.

The suites also pin the behaviours most likely to drift: the `record_id` tiebreak making
resolution order-independent, a later observation beating an older revision, the
inclusive boundary instants, a naive timestamp being refused rather than assumed UTC, and
`leakage_audit` never mutating the records it reports on.

---

## Related algorithms

**Same family — D01-F04 Data Quality** *(every live topic now has a repo)*

- **[Missing-Bar Gap Classifier](https://github.com/IslamBaraka90/Fintech-Missing-Bar-Gap-Classifier-algorithm)** · **[Feed Latency Monitor](https://github.com/IslamBaraka90/Fintech-Feed-Latency-Monitor-Data-Quality-algorithm)** · **[Price-Source Consensus Check](https://github.com/IslamBaraka90/Fintech-Price-Source-Consensus-Check-Data-Quality-algorithm)** · **[Schema Drift Detector](https://github.com/IslamBaraka90/Fintech-Schema-Drift-Detector-Data-Quality-algorithm)**

**Related — D01-F03 Time Synchronization**

- **[Previous-Tick Interpolation](https://github.com/IslamBaraka90/Fintech-Previous-Tick-Interpolation-Time-Synchronization-algorithm)** — the same two clocks applied to sampling a series onto a grid.
- **[Linear Quote Interpolation](https://github.com/IslamBaraka90/Fintech-Linear-Quote-Interpolation-Time-Synchronization-algorithm)** — what happens when a method needs the future.

🧭 **[Browse all algorithms →](https://github.com/IslamBaraka90/Fintech-Algorithms-Awesome)**

---

## License

MIT — see [LICENSE](LICENSE).

The synthetic fixture data is CC0-1.0. No market data is redistributed.
