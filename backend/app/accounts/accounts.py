"""`Accounts` — the accounts module's whole public face (spec §7, A.4).

`advance` does only the reading, the writing and the day-by-day loop: the
day itself is worked out by the pure functions in `session`, `planning`
and `ledger`.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlalchemy import Engine, delete, insert, select, update

from app.accounts import tables
from app.accounts.ledger import Ledger
from app.accounts.planning import PortfolioRules, plan_orders
from app.accounts.statistics import Figures, statistics
from app.accounts.records import BUY, FILLED, SELL, Record
from app.accounts.session import Bar, Costs, Session, corporate_actions, open_session, replace_sells
from app.market_data import (
    ADJUSTMENT_FACTOR, EX_RIGHTS_TYPE, EXEC_CLOSE, EXEC_HIGH, EXEC_LOW, EXEC_OPEN, LOWER_LIMIT_HIT, QUALITY,
    UPPER_LIMIT_HIT, MarketData, MarketFrame,
)
from app.strategies import Disposition, Holding, Strategy, build_strategy

UNTRADABLE = "untradable"
TOPIX = "TOPIX"


@dataclass(frozen=True)
class AccountSpec:
    name: str
    strategy: str
    start_date: date
    strategy_params: Mapping[str, Any] = field(default_factory=dict)
    initial_cash: Decimal = Decimal("10000000")
    rules: PortfolioRules = PortfolioRules()
    costs: Costs = Costs()


@dataclass(frozen=True)
class AdvanceReport:
    name: str             # the account's
    sessions: list[date]  # advanced through this time, oldest first
    warnings: list[str]


@dataclass(frozen=True)
class AccountSummary:
    id: int
    name: str
    strategy: str
    start_date: date
    advanced_through: date | None
    status: str                    # "active" / "stopped"
    total_return: float | None
    max_drawdown: float | None


@dataclass(frozen=True)
class HoldingLine:
    code: str
    quantity: int
    opened_on: date
    cost: Decimal   # fees included
    close: Decimal  # the latest execution close
    value: Decimal


@dataclass(frozen=True)
class AccountReport:
    """Dividends and tax are in none of it (spec §7.4)."""

    account: dict[str, Any]     # the stored account: name, strategy, rules, dates, status
    nav: pd.Series              # net asset value at each session's close, from the start
    topix: pd.Series            # TOPIX's close on the same sessions
    figures: Figures | None     # None before the account has been advanced
    holdings: list[HoldingLine]
    pending: list[Record]       # the orders for the next open
    orders: list[Record]        # every record, oldest first


class Accounts:
    def __init__(
        self,
        engine: Engine,
        market: MarketData,
        *,
        build_strategy: Callable[[str, Mapping[str, Any]], Strategy] = build_strategy,
    ) -> None:
        self._engine = engine
        self._market = market
        self._build_strategy = build_strategy
        # The latest report of each account, worked out once however many ask
        # at the same time: the account page asks three times at once.
        self._reports: dict[int, tuple[tuple, AccountReport]] = {}
        self._report_locks: dict[int, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def create(self, spec: AccountSpec) -> int:
        """Refused unless the strategy knows every parameter given, the start
        is a session, and there are as many sessions of data before it as
        the strategy's warm-up (spec §7.1)."""
        strategy = self._build_strategy(spec.strategy, spec.strategy_params)
        calendar = self._market.calendar()
        if not calendar.is_session(spec.start_date):
            raise ValueError(f"起始日 {spec.start_date.isoformat()} 不是开市日")
        behind = self._sessions_of_data_before(spec.start_date)
        if behind < strategy.warmup_sessions:
            raise ValueError(
                f"起始日 {spec.start_date.isoformat()} 之前只有 {behind} 个开市日的数据，"
                f"{spec.strategy} 的预热期要 {strategy.warmup_sessions} 个"
            )
        with self._engine.begin() as connection:
            return connection.execute(insert(tables.paper_accounts).values(
                name=spec.name, strategy=spec.strategy, strategy_params=dict(spec.strategy_params),
                portfolio_rules={"initial_cash": str(spec.initial_cash), "max_positions": spec.rules.max_positions,
                                 "max_weight": str(spec.rules.max_weight), "cash_floor": str(spec.rules.cash_floor)},
                costs={"commission_rate": str(spec.costs.commission_rate),
                       "commission_min": str(spec.costs.commission_min), "slippage": str(spec.costs.slippage)},
                start_date=spec.start_date, status="active",
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )).inserted_primary_key[0]

    def advance(self, account_id: int, *, through: date | None = None) -> AdvanceReport:
        """From the session after `advanced_through` (or the start date) to
        `through` (default: the latest session with data), one session and
        one transaction at a time; nothing to do if already there."""
        account = self._account(account_id)
        overview = self._market.overview()
        through = through or overview.latest_date
        calendar = self._market.calendar()
        done = account["advanced_through"]
        days = [d for d in calendar.sessions()
                if account["start_date"] <= d <= through and (done is None or d > done)]
        if not days:
            return AdvanceReport(account["name"], [], [])

        rules, costs, initial_cash = _rules(account)
        ledger = Ledger(initial_cash, self._records(account_id))
        strategy = self._build_strategy(account["strategy"], account["strategy_params"])
        universes = self._market.universe(days[0], days[-1])
        prices = self._prices(strategy, ledger, universes, days)

        warnings: list[str] = []
        for day in days:
            session = prices.session(day)
            next_day = calendar.next(day)

            events, found = corporate_actions(ledger, session)
            warnings += found
            after_events = ledger.apply(events)
            fills = open_session(after_events.pending, session, cash=after_events.cash, costs=costs)
            again = replace_sells(fills, day=day, execution_day=next_day)
            morning = after_events.apply(fills).apply(again)

            holdings = [Holding(p.code, p.quantity, p.opened_on) for p in morning.positions.values()]
            signals = strategy.evaluate(prices.frame, day, holdings)
            selling_again = {record.code for record in again}
            exits = [s for s in signals if s.disposition is Disposition.EXIT
                     and s.code in morning.positions and s.code not in selling_again]
            candidates = [s for s in signals if s.disposition is Disposition.HOLD
                          and s.code not in morning.positions and s.code in set(universes.get(day, []))]
            closes = prices.closes(day, [*morning.positions, *(s.code for s in candidates)])
            nav = morning.cash + sum((Decimal(p.quantity) * closes[p.code] for p in morning.positions.values()),
                                     Decimal(0))
            orders = plan_orders(day=day, execution_day=next_day, positions=morning.positions, exits=exits,
                                 candidates=candidates, closes=closes, cash=morning.cash, nav=nav, rules=rules)

            stored = self._store(account_id, day, [*events, *fills, *again, *orders])
            ledger = ledger.apply(stored)

        if days[-1] == overview.latest_date and account["backtest_data_mark"] is None:
            self._set(account_id, backtest_data_mark={"latest_date": overview.latest_date.isoformat(),
                                                      "bar_rows": overview.bar_rows})
        return AdvanceReport(account["name"], days, warnings)

    def report(self, account_id: int) -> AccountReport:
        """Worked out when read (spec §7.4) — once, until the account moves
        on, is stopped or gains a record."""
        with self._locks_guard:
            lock = self._report_locks.setdefault(account_id, threading.Lock())
        with lock:
            account = self._account(account_id)
            records = self._records(account_id)
            version = (account["advanced_through"], account["status"], str(account["backtest_data_mark"]),
                       len(records), records[-1].id if records else None)
            cached = self._reports.get(account_id)
            if cached is None or cached[0] != version:
                self._reports[account_id] = (version, self._work_out_report(account, records))
            return self._reports[account_id][1]

    def _work_out_report(self, account: dict, records: list[Record]) -> AccountReport:
        _, _, initial_cash = _rules(account)
        ledger = Ledger(initial_cash, records)
        through = account["advanced_through"]
        if through is None:
            return AccountReport(account, pd.Series(dtype=object), pd.Series(dtype=float), None, [],
                                 ledger.pending, records)

        sessions = [d for d in self._market.calendar().sessions() if account["start_date"] <= d <= through]
        traded = sorted({record.code for record in records if record.status == FILLED})
        closes = self._market.read([*traded, TOPIX], account["start_date"], through).wide(EXEC_CLOSE).ffill()
        closes = closes.reindex(sessions).ffill()

        nav = pd.Series({
            day: cash + sum((Decimal(p.quantity) * closes.at[day, code] for code, p in held.items()), Decimal(0))
            for day, cash, held in ledger.by_session(sessions)
        })
        topix = closes[TOPIX].astype(float) if TOPIX in closes else pd.Series(dtype=float)
        amounts = {kind: sum((r.fill_price * r.filled_quantity for r in records if r.kind == kind and r.status == FILLED),
                             Decimal(0)) for kind in (BUY, SELL)}
        figures = statistics(nav.astype(float), topix, ledger.closed, bought=amounts[BUY], sold=amounts[SELL])
        last = closes.iloc[-1]
        holdings = [HoldingLine(p.code, p.quantity, p.opened_on, p.cost, last[p.code], p.quantity * last[p.code])
                    for p in sorted(ledger.positions.values(), key=lambda p: p.code)]
        return AccountReport(account, nav, topix, figures, holdings, ledger.pending, records)

    def list(self, *, active_only: bool = False) -> list[AccountSummary]:
        accounts = tables.paper_accounts
        statement = select(accounts.c.id).order_by(accounts.c.id)
        if active_only:
            statement = statement.where(accounts.c.status == "active")
        with self._engine.connect() as connection:
            ids = list(connection.execute(statement).scalars())
        summaries = []
        for account_id in ids:
            report = self.report(account_id)
            account, figures = report.account, report.figures
            summaries.append(AccountSummary(
                account_id, account["name"], account["strategy"], account["start_date"], account["advanced_through"],
                account["status"], figures.total_return if figures else None, figures.max_drawdown if figures else None,
            ))
        return summaries

    def stop(self, account_id: int) -> None:
        """A stopped account is no longer advanced after each sync."""
        self._account(account_id)
        self._set(account_id, status="stopped")

    def delete(self, account_id: int) -> None:
        self._account(account_id)
        with self._engine.begin() as connection:
            connection.execute(delete(tables.paper_orders).where(tables.paper_orders.c.account_id == account_id))
            connection.execute(delete(tables.paper_accounts).where(tables.paper_accounts.c.id == account_id))
        self._reports.pop(account_id, None)

    # --- reading and writing ---------------------------------------------

    def _set(self, account_id: int, **values) -> None:
        with self._engine.begin() as connection:
            connection.execute(update(tables.paper_accounts).where(tables.paper_accounts.c.id == account_id)
                               .values(**values))

    def _sessions_of_data_before(self, day: date) -> int:
        """Counted on TOPIX, synced over the same dates as the stocks: one
        code's bars rather than the whole market's."""
        sessions = self._market.calendar().sessions()
        if not sessions or sessions[0] >= day:
            return 0
        frame = self._market.read([TOPIX], sessions[0], day - timedelta(days=1))
        return len(frame.dates(TOPIX))

    def _account(self, account_id: int) -> dict:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(tables.paper_accounts).where(tables.paper_accounts.c.id == account_id)
            ).mappings().one_or_none()
        if row is None:
            raise LookupError(f"没有这个账户：{account_id}")
        return dict(row)

    def _records(self, account_id: int) -> list[Record]:
        orders = tables.paper_orders
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(orders).where(orders.c.account_id == account_id).order_by(orders.c.id)
            ).mappings().all()
        return [Record(**{key: value for key, value in row.items() if key != "account_id"}) for row in rows]

    def _store(self, account_id: int, day: date, records: list[Record]) -> list[Record]:
        """The session's records and `advanced_through = day`, together or
        not at all. A record met twice (changed before the open, then filled)
        is stored as it ended."""
        orders = tables.paper_orders
        final: dict[int, Record] = {}
        for record in records:
            if record.id is not None:
                final[record.id] = record
        stored = []
        with self._engine.begin() as connection:
            for record in records:
                values = {key: value for key, value in vars(record).items() if key != "id"}
                if record.id is None:
                    new_id = connection.execute(insert(orders).values(account_id=account_id, **values)).inserted_primary_key[0]
                    stored.append(replace(record, id=new_id))
                elif final.get(record.id) is record:
                    connection.execute(update(orders).where(orders.c.id == record.id).values(**values))
                    stored.append(record)
            connection.execute(update(tables.paper_accounts).where(tables.paper_accounts.c.id == account_id)
                               .values(advanced_through=day))
        return stored

    def _prices(self, strategy: Strategy, ledger: Ledger, universes: Mapping[date, list[str]],
                days: list[date]) -> _Prices:
        """One read for the whole run: every code that could be bought or is
        held, from far enough back for the strategy's warm-up and for the
        oldest holding's opening."""
        codes = set(ledger.positions) | {order.code for order in ledger.pending}
        for listed in universes.values():
            codes.update(listed)
        sessions = [d for d in self._market.calendar().sessions() if d < days[0]]
        start = sessions[max(0, len(sessions) - strategy.warmup_sessions)] if sessions else days[0]
        opened = [p.opened_on for p in ledger.positions.values()]
        start = min([start, *opened])
        return _Prices(self._market.read(sorted(codes), start, days[-1]))


class _Prices:
    """The account's view of the run's market data, looked up only as
    needed — a three-year run spans more than a million bars."""

    def __init__(self, frame: MarketFrame) -> None:
        self.frame = frame
        self._rows = frame.data
        self._last_close = frame.wide(EXEC_CLOSE).ffill()

    def session(self, day: date) -> Session:
        previous = self._last_close.loc[:day].iloc[:-1] if day in self._last_close.index else self._last_close.loc[:day]
        previous_closes = {} if previous.empty else {
            code: value for code, value in previous.iloc[-1].items() if value is not None and not pd.isna(value)
        }
        delisted = frozenset(code for code, last in self.frame.listed_through.items() if last is not None and last < day)
        return Session(day, _Bars(self._rows, day), previous_closes, delisted)

    def closes(self, day: date, codes) -> dict[str, Decimal]:
        """Each code's execution close that day, or its latest before."""
        codes = list(codes)
        if not codes:
            return {}
        row = self._last_close.loc[:day].iloc[-1]
        return {code: row[code] for code in codes}


class _Bars(Mapping):
    def __init__(self, rows: pd.DataFrame, day: date) -> None:
        self._rows, self._day = rows, day

    def __getitem__(self, code: str) -> Bar:
        try:
            row = self._rows.loc[(code, self._day)]
        except KeyError:
            raise KeyError(code) from None
        return Bar(open=row[EXEC_OPEN], high=row[EXEC_HIGH], low=row[EXEC_LOW], close=row[EXEC_CLOSE],
                   upper_limit_hit=bool(row[UPPER_LIMIT_HIT]), lower_limit_hit=bool(row[LOWER_LIMIT_HIT]),
                   untradable=row[QUALITY] == UNTRADABLE, adjustment_factor=Decimal(row[ADJUSTMENT_FACTOR]),
                   ex_rights_type=row[EX_RIGHTS_TYPE])

    def __iter__(self):
        return iter(())

    def __len__(self) -> int:
        return 0


def _rules(account: Mapping[str, Any]) -> tuple[PortfolioRules, Costs, Decimal]:
    portfolio, costs = account["portfolio_rules"], account["costs"]
    rules = PortfolioRules(max_positions=portfolio["max_positions"], max_weight=Decimal(portfolio["max_weight"]),
                           cash_floor=Decimal(portfolio["cash_floor"]))
    return rules, Costs(**{key: Decimal(value) for key, value in costs.items()}), Decimal(portfolio["initial_cash"])
