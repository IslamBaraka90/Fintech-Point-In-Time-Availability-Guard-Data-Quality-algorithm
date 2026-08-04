"""Point-in-time filtering that keeps valid time separate from knowledge time.

Every record carries two timestamps that mean different things: ``observation_time``
(when it was true) and ``available_at`` (when you could first have used it). A backtest
filtering on only the first is a report on what you would have earned knowing things you
did not know.

Quickstart::

    from fintech_point_in_time import as_of_snapshot, leakage_audit

    rows = as_of_snapshot(records, knowledge_time="2026-02-01T12:00:00Z")
    assert not leakage_audit(records, "2026-02-01T12:00:00Z") or True  # see what was withheld

See :mod:`fintech_point_in_time.core` for the guard and
:mod:`fintech_point_in_time.backtest` for panels, restatement history, vintage diffs and
publication-lag analysis.

Article: https://thefintechbuilder.com/market-data-engineering/data-quality/point-in-time-availability-guard/
"""

from .backtest import (
    build_panel,
    leakage_report,
    publication_lag,
    restatement_history,
    vintage_diff,
)
from .core import (
    REQUIRED_FIELDS,
    as_of_snapshot,
    leakage_audit,
    parse_timestamp_ms,
    validate_records,
)

__version__ = "0.1.0"

__all__ = [
    "REQUIRED_FIELDS",
    "__version__",
    "as_of_snapshot",
    "build_panel",
    "leakage_audit",
    "leakage_report",
    "parse_timestamp_ms",
    "publication_lag",
    "restatement_history",
    "validate_records",
    "vintage_diff",
]
