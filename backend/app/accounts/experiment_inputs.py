"""What a model experiment (ticket 06a) reads from the accounts module, and
nothing more: a source account's trading terms — its initial capital,
portfolio rules and costs — and how far history has already been looked
at through paper accounts and research runs. Reads only; neither the
source nor any run is written to.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import Engine, func, select

from app.accounts import research_tables, tables
from app.accounts.research_jobs import COMPLETED

TERMS = ("initial_cash", "max_positions", "max_weight", "cash_floor", "commission_rate", "commission_min",
         "slippage")


def source_terms(engine: Engine, account_id: int) -> dict:
    """The account's initial capital, portfolio rules and costs under the
    names of `TERMS`, as stored (decimal strings); LookupError if there is
    no such account."""
    with engine.connect() as con:
        row = con.execute(select(tables.paper_accounts.c.portfolio_rules, tables.paper_accounts.c.costs)
                          .where(tables.paper_accounts.c.id == account_id)).one_or_none()
    if row is None:
        raise LookupError("来源账户不存在")
    rules, costs = row.portfolio_rules, row.costs
    return {"initial_cash": rules["initial_cash"], "max_positions": rules["max_positions"],
            "max_weight": rules["max_weight"], "cash_floor": rules["cash_floor"],
            **{key: costs[key] for key in ("commission_rate", "commission_min", "slippage")}}


def viewed_through(engine: Engine) -> date | None:
    """The latest session whose results could already have been seen here:
    the last day any paper account has been advanced through, or any
    completed research run (a batch segment's included) ended on."""
    with engine.connect() as con:
        advanced = con.execute(select(func.max(tables.paper_accounts.c.advanced_through))).scalar_one()
        configs = con.execute(select(research_tables.runs.c.config)
                              .where(research_tables.runs.c.status == COMPLETED)).scalars().all()
    seen = [date.fromisoformat(c["end_date"]) for c in configs if c.get("end_date")]
    if advanced is not None:
        seen.append(advanced if isinstance(advanced, date) else date.fromisoformat(advanced))
    return max(seen, default=None)
