"""`MarketData` — the market data module's whole public face (spec A.1)."""

from __future__ import annotations

import random
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import Connection, Engine, Float, cast, delete, func, insert, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.market_data import split_check, tables
from app.market_data.calendar import Calendar
from app.market_data.frame import MarketFrame, build_frame
from app.market_data.jquants import BarRecord, IndexBar, JQuantsClient, RosterEntry
from app.market_data.quality import UNTRADABLE, quality_of
from app.market_data.segments import OpenSegment, compare_roster

BACKFILL_YEARS = 5
OPEN_DIVISIONS = (1, 2)  # HolDiv: a full or a half trading day
STOCK, INDEX = "stock", "index"
TOPIX = "TOPIX"
# The universe (spec §6.1). One rule set, so constants rather than a policy
# argument (spec A.1).
PRIME, COMMON_STOCK = "0111", "011"
TURNOVER_SESSIONS = 20
MIN_AVERAGE_TURNOVER = Decimal("500000000")  # yen


@dataclass(frozen=True)
class QualityReport:
    """Problems that take more than one row to see (spec §4.4)."""

    # Sessions inside the stored range with no stock bar at all.
    missing_sessions: list[date]
    # code → sessions it has no bar on, between its first and last bar,
    # among sessions the rest of the market does have.
    gaps: dict[str, int]
    untradable_rows: int
    untradable_on_latest: int


@dataclass(frozen=True)
class Instrument:
    code: str
    name: str
    name_en: str
    market: str | None  # its market code now; None once it has left the roster


@dataclass(frozen=True)
class DataOverview:
    latest_date: date | None  # of stock bars; TOPIX does not count
    securities: int
    bar_rows: int
    quality: QualityReport


@dataclass(frozen=True)
class SyncProgress:
    sessions_done: int
    sessions_total: int
    current_session: date


@dataclass
class SyncReport:
    """What one sync did: the session range it covered, how many rows it
    wrote, and anything worth a human's attention."""

    first_session: date | None = None
    last_session: date | None = None
    rows_written: int = 0
    warnings: list[str] = field(default_factory=list)
    # Today is a session but J-Quants has nothing for it yet (it publishes
    # in the evening); the sync stopped there and should be tried again.
    not_published_yet: bool = False


def _tokyo_today() -> date:
    return datetime.now(ZoneInfo("Asia/Tokyo")).date()


class MarketData:
    def __init__(
        self,
        engine: Engine,
        client: JQuantsClient,
        *,
        today: Callable[[], date] = _tokyo_today,
        rng: random.Random | None = None,
    ) -> None:
        self._engine = engine
        self._client = client
        self._today = today
        self._rng = rng or random.Random()

    def sync(
        self,
        *,
        until: date | None = None,
        on_progress: Callable[[SyncProgress], None] | None = None,
    ) -> SyncReport:
        """Calendar → each session after the latest stored one (bars and
        roster, one transaction per session) → TOPIX → split check.

        Backfill and the daily sync are this one function. Nothing records
        progress: an interrupted run is rerun, and committed sessions are
        simply not fetched again.
        """
        today = self._today()
        until = until or today
        report = SyncReport()
        self._store_calendar()
        sessions = self._sessions()
        previous = dict(zip(sessions[1:], sessions))
        is_backfill = self._date_span(stocks=True)[1] is None
        ex_dates: dict[str, date] = {}  # code → its latest ex-rights day in this run
        targets = self._target_sessions(sessions, today, until)
        for done, day in enumerate(targets, start=1):
            bars = self._client.daily_bars_on(day)
            if not bars and day == today:
                report.not_published_yet = True
                report.warnings.append(f"{day.isoformat()} 当天数据未出，稍后再同步")
                break
            roster = self._client.roster_on(day)
            with self._engine.begin() as connection:
                report.warnings.extend(_write_session(connection, day, previous.get(day), bars, roster))
            if bars:
                report.first_session = report.first_session or day
                report.last_session = day
                report.rows_written += len(bars)
                ex_dates.update((record.code, day) for record in bars if record.adjustment_factor != 1)
            else:
                report.warnings.append(f"{day.isoformat()} 是开市日，但 J-Quants 没有返回日线")
            if on_progress is not None:
                on_progress(SyncProgress(done, len(targets), day))
        # TOPIX catches up from its own latest date, not this run's first
        # session: a run interrupted after some sessions committed left
        # TOPIX behind for those, and the rerun will not revisit them.
        stocks_from, stocks_through = self._date_span(stocks=True)
        if stocks_through is not None:
            _, topix_through = self._date_span(stocks=False)
            topix_from = stocks_from if topix_through is None else topix_through + timedelta(days=1)
            if topix_from <= stocks_through:
                report.rows_written += self._store_topix(topix_from, stocks_through)

        # A backfill brings in five years of splits — hundreds of codes — so
        # it checks a sample; a daily sync checks every one it brought in.
        to_check = sorted(ex_dates)
        if is_backfill:
            to_check = sorted(self._rng.sample(to_check, min(split_check.BACKFILL_SAMPLE, len(to_check))))
        for code in to_check:
            report.warnings.extend(self._check_split(code, ex_dates[code], sessions))
        return report

    def _check_split(self, code: str, ex_date: date, sessions: list[date]) -> list[str]:
        before = [day for day in sessions if day < ex_date][-split_check.SESSIONS_BEFORE:]
        if not before:
            return []
        bars = tables.daily_bars
        with self._engine.connect() as connection:
            stored = connection.execute(
                select(bars.c.date, bars.c.close, bars.c.adjustment_factor)
                .where(bars.c.code == code, bars.c.date >= before[0])
            ).all()
        local = split_check.research_closes(stored)
        found = split_check.disagreements(local, self._client.daily_bars_for(code, before[0], before[-1]))
        return [split_check.warning_for(code, ex_date, found)] if found else []

    def overview(self) -> DataOverview:
        bars = tables.daily_bars
        stocks = bars.c.code != TOPIX
        untradable = bars.c.quality_status == UNTRADABLE
        with self._engine.connect() as connection:
            bar_rows = connection.execute(select(func.count()).select_from(bars)).scalar_one()
            stock_dates = list(connection.execute(
                select(bars.c.date).where(stocks).distinct().order_by(bars.c.date)
            ).scalars())
            spans = connection.execute(
                select(bars.c.code, func.min(bars.c.date), func.max(bars.c.date), func.count())
                .where(stocks).group_by(bars.c.code)
            ).all()
            untradable_rows = connection.execute(
                select(func.count()).select_from(bars).where(stocks, untradable)
            ).scalar_one()
            untradable_on_latest = 0 if not stock_dates else connection.execute(
                select(func.count()).select_from(bars).where(stocks, untradable, bars.c.date == stock_dates[-1])
            ).scalar_one()

        missing: list[date] = []
        if stock_dates:
            stored = set(stock_dates)
            missing = [day for day in self._sessions() if stock_dates[0] <= day <= stock_dates[-1] and day not in stored]
        gaps = {}
        for code, first, last, count in spans:
            expected = bisect_right(stock_dates, last) - bisect_left(stock_dates, first)
            if count < expected:
                gaps[code] = expected - count
        return DataOverview(
            latest_date=stock_dates[-1] if stock_dates else None,
            securities=len(spans),
            bar_rows=bar_rows,
            quality=QualityReport(missing, gaps, untradable_rows, untradable_on_latest),
        )

    def universe(self, start: date, end: date | None = None) -> dict[date, list[str]]:
        """Each session from `start` to `end` (default: `start` alone) → the
        codes that may be newly bought on it (spec §6.1): Prime common stock
        that day, averaging ¥500M turnover over the last 20 sessions with a
        missing or untradable day counting as nothing, and with a bar that
        day that is not untradable. One read for the whole range."""
        end = end or start
        sessions = [session for session in self._sessions() if session <= end]
        days = [session for session in sessions if session >= start]
        if not days:
            return {}
        window = sessions[max(0, sessions.index(days[0]) - (TURNOVER_SESSIONS - 1)):]
        segments, bars = tables.segment_periods, tables.daily_bars
        with self._engine.connect() as connection:
            periods = connection.execute(
                select(segments.c.code, segments.c.valid_from, segments.c.valid_to).where(
                    segments.c.market_code == PRIME, segments.c.product_category == COMMON_STOCK,
                    segments.c.valid_from <= end, segments.c.valid_to.is_(None) | (segments.c.valid_to >= start),
                )
            ).all()
            codes = sorted({period.code for period in periods})
            rows = connection.execute(
                select(bars.c.code, bars.c.date, bars.c.turnover, bars.c.quality_status).where(
                    bars.c.code.in_(codes), bars.c.date.between(window[0], end),
                )
            ).all()

        table = pd.DataFrame(rows, columns=["code", "date", "turnover", "quality"])
        tradable = table["quality"] != UNTRADABLE
        table["counted"] = [float(amount or 0) if ok else 0.0 for amount, ok in zip(table["turnover"], tradable)]
        table["tradable"] = tradable
        counted = table.pivot(index="date", columns="code", values="counted").reindex(index=window, columns=codes)
        averaged = counted.fillna(0.0).rolling(TURNOVER_SESSIONS, min_periods=1).sum() / TURNOVER_SESSIONS
        can_trade = table.pivot(index="date", columns="code", values="tradable").reindex(index=window, columns=codes)
        can_trade = can_trade.fillna(False).astype(bool)

        in_segment = pd.DataFrame(False, index=days, columns=codes)
        for period in periods:
            in_segment.loc[period.valid_from:period.valid_to or end, period.code] = True
        chosen = (in_segment & can_trade.loc[days] & (averaged.loc[days] >= float(MIN_AVERAGE_TURNOVER))).to_numpy()
        return {day: [codes[i] for i in chosen[row].nonzero()[0]] for row, day in enumerate(days)}

    def instruments(self, *, query: str | None = None, codes: Sequence[str] | None = None) -> list[Instrument]:
        """Stocks by code, or searched: `query` matches the start of a code
        or any part of either name (the English one in any case)."""
        instruments, segments = tables.instruments, tables.segment_periods
        now = segments.c.valid_to.is_(None)
        statement = (
            select(instruments.c.code, instruments.c.name, instruments.c.name_en, segments.c.market_code)
            .join(segments, (segments.c.code == instruments.c.code) & now, isouter=True)
            .where(instruments.c.kind == STOCK)
            .order_by(instruments.c.code)
        )
        if query is not None:
            statement = statement.where(
                instruments.c.code.startswith(query, autoescape=True)
                | instruments.c.name.contains(query, autoescape=True)
                | instruments.c.name_en.icontains(query, autoescape=True)
            )
        if codes is not None:
            statement = statement.where(instruments.c.code.in_(list(codes)))
        with self._engine.connect() as connection:
            return [Instrument(*row) for row in connection.execute(statement)]

    def calendar(self) -> Calendar:
        return Calendar(self._sessions())

    def read(self, codes: Sequence[str] | None, start: date, end: date) -> MarketFrame:
        """Every bar of `codes` (all securities when None) from `start` to
        `end`, in one query, with research prices worked out."""
        bars = tables.daily_bars
        in_range = select(bars).where(bars.c.date.between(start, end))
        # Only ex-rights days after the range matter to it; every other
        # later bar has a factor of 1.
        later = select(bars.c.code, bars.c.date, bars.c.adjustment_factor, bars.c.ex_rights_type).where(
            bars.c.date > end, cast(bars.c.adjustment_factor, Float) != 1.0,
        )
        if codes is None:
            in_range = in_range.where(bars.c.code != TOPIX)
            later = later.where(bars.c.code != TOPIX)
        else:
            in_range = in_range.where(bars.c.code.in_(list(codes)))
            later = later.where(bars.c.code.in_(list(codes)))
        with self._engine.connect() as connection:
            rows = connection.execute(in_range).mappings().all()
            later_factors = connection.execute(later).mappings().all()
            frame = build_frame(rows, later_factors)
            frame.listed_through = self._listed_through(connection, frame.data.index.unique("code"))
        return frame

    @staticmethod
    def _listed_through(connection: Connection, codes) -> dict[str, date | None]:
        """A code's last session on the roster: the end of its last segment
        period, or None while one is still open."""
        segments = tables.segment_periods
        last: dict[str, date | None] = {code: None for code in codes}
        ended: dict[str, date] = {}
        still_listed: set[str] = set()
        for code, valid_to in connection.execute(
            select(segments.c.code, segments.c.valid_to).where(segments.c.code.in_(list(codes)))
        ):
            if valid_to is None:
                still_listed.add(code)
            else:
                ended[code] = max(valid_to, ended.get(code, valid_to))
        last.update({code: day for code, day in ended.items() if code not in still_listed})
        return last

    def _store_calendar(self) -> None:
        days = self._client.calendar()
        with self._engine.begin() as connection:
            connection.execute(delete(tables.trading_calendar))
            if days:
                connection.execute(
                    insert(tables.trading_calendar),
                    [{"date": day.date, "holiday_division": day.holiday_division} for day in days],
                )

    def _store_topix(self, start: date, end: date) -> int:
        index_bars = self._client.topix(start, end)
        daily_bars, instruments = tables.daily_bars, tables.instruments
        with self._engine.begin() as connection:
            connection.execute(
                sqlite_insert(instruments)
                .values(code=TOPIX, kind=INDEX, name="TOPIX", name_en="TOPIX", scale_category="-")
                .on_conflict_do_nothing()
            )
            connection.execute(
                delete(daily_bars).where(daily_bars.c.code == TOPIX, daily_bars.c.date.between(start, end))
            )
            if index_bars:
                connection.execute(insert(daily_bars), [_index_row(record) for record in index_bars])
        return len(index_bars)

    def _date_span(self, *, stocks: bool) -> tuple[date | None, date | None]:
        """The earliest and latest stored dates of stock bars, or of TOPIX's."""
        bars = tables.daily_bars
        which = bars.c.code != TOPIX if stocks else bars.c.code == TOPIX
        with self._engine.connect() as connection:
            earliest, latest = connection.execute(
                select(func.min(bars.c.date), func.max(bars.c.date)).where(which)
            ).one()
        return earliest, latest

    def _sessions(self) -> list[date]:
        calendar = tables.trading_calendar
        with self._engine.connect() as connection:
            return list(connection.execute(
                select(calendar.c.date)
                .where(calendar.c.holiday_division.in_(OPEN_DIVISIONS))
                .order_by(calendar.c.date)
            ).scalars())

    def _target_sessions(self, sessions: list[date], today: date, until: date) -> list[date]:
        """Open days after the latest stored stock bar — or, on an empty
        database, from five years back — through `until`."""
        _, latest = self._date_span(stocks=True)
        if latest is None:
            return [day for day in sessions if _years_before(today, BACKFILL_YEARS) <= day <= until]
        return [day for day in sessions if latest < day <= until]


def _write_session(
    connection: Connection,
    day: date,
    previous_session: date | None,
    bars: list[BarRecord],
    roster: list[RosterEntry],
) -> list[str]:
    """One session's bars and roster, overwriting whatever was there."""
    daily_bars, segment_periods, instruments = tables.daily_bars, tables.segment_periods, tables.instruments

    connection.execute(delete(daily_bars).where(daily_bars.c.date == day, daily_bars.c.code != TOPIX))
    if bars:
        connection.execute(insert(daily_bars), [_bar_row(record) for record in bars])

    running = [
        OpenSegment(row.code, row.valid_from, row.market_code, row.product_category, row.sector33)
        for row in connection.execute(select(segment_periods).where(segment_periods.c.valid_to.is_(None)))
    ]
    known = set(connection.execute(select(instruments.c.code).where(instruments.c.kind == STOCK)).scalars())
    changes = compare_roster(running, known, roster, day=day, previous_session=previous_session)
    for code, valid_from, valid_to in changes.closed:
        connection.execute(
            update(segment_periods)
            .where(segment_periods.c.code == code, segment_periods.c.valid_from == valid_from)
            .values(valid_to=valid_to)
        )
    if changes.opened:
        connection.execute(insert(segment_periods), [vars(segment) for segment in changes.opened])

    if roster:
        upsert = sqlite_insert(instruments)
        # Name and scale are only ever current; the first sighting stays put.
        upsert = upsert.on_conflict_do_update(
            index_elements=[instruments.c.code],
            set_={
                "name": upsert.excluded.name,
                "name_en": upsert.excluded.name_en,
                "scale_category": upsert.excluded.scale_category,
                "last_listed_seen": upsert.excluded.last_listed_seen,
            },
        )
        # One row per execution: ~4,400 rows in a single VALUES list would
        # run into SQLite's limit on bound parameters.
        connection.execute(upsert, [
            {
                "code": entry.code, "kind": STOCK, "name": entry.name, "name_en": entry.name_en,
                "scale_category": entry.scale_category, "first_listed_seen": day, "last_listed_seen": day,
            }
            for entry in roster
        ])
    return changes.warnings


def _years_before(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 29 February, and the earlier year has none
        return day.replace(year=day.year - years, day=28)


def _bar_row(record: BarRecord) -> dict:
    return {
        "code": record.code,
        "date": record.date,
        "open": record.open,
        "high": record.high,
        "low": record.low,
        "close": record.close,
        "volume": record.volume,
        "turnover": record.turnover,
        "adjustment_factor": record.adjustment_factor,
        "ex_rights_type": record.ex_rights_type,
        "upper_limit_hit": record.upper_limit_hit,
        "lower_limit_hit": record.lower_limit_hit,
        "quality_status": quality_of(record),
    }


def _index_row(record: IndexBar) -> dict:
    """TOPIX has prices only: no volume, turnover, factor or limits."""
    as_bar = BarRecord(
        code=TOPIX, date=record.date, open=record.open, high=record.high, low=record.low, close=record.close,
        volume=None, turnover=None, adjustment_factor=Decimal(1), ex_rights_type=None,
        upper_limit_hit=False, lower_limit_hit=False, adjusted_close=record.close,
    )
    return _bar_row(as_bar) | {"quality_status": quality_of(as_bar, has_volume=False)}
