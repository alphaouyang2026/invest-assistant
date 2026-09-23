"""Quality status (spec §4.4), judged one row at a time as it is written.

Anything that needs more than one row to see — a missing session, a split
that does not reconcile — is not a status; the data page works it out
when asked.
"""

from __future__ import annotations

from app.market_data.jquants import BarRecord

OK = "ok"
EXCLUDED = "excluded"  # prices are fine, an optional field is missing
UNTRADABLE = "untradable"  # no trustworthy execution price, e.g. a halt


def quality_of(bar: BarRecord, *, has_volume: bool = True) -> str:
    """`has_volume=False` for an index, which has prices and nothing else."""
    prices = (bar.open, bar.high, bar.low, bar.close)
    if any(price is None for price in prices):
        return UNTRADABLE
    if any(price <= 0 for price in prices):
        return UNTRADABLE
    if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close) or bar.high < bar.low:
        return UNTRADABLE
    if has_volume and (bar.volume is None or bar.turnover is None):
        return EXCLUDED
    return OK
