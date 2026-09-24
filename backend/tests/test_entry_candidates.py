"""`entry_candidates` and `history` (spec A.3): the assembly between the
market data module and a strategy — universe, how far back to read, names.
A stand-in strategy is used: the rules are tested elsewhere, and a strategy
is a seam with room for another adapter.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.market_data import CLOSE, MarketData
from app.strategies import Disposition, Plot, Signal, entry_candidates, history
from tests.fakes import FakeJQuants, bar, listed

SESSIONS = [date(2026, 8, 3) + timedelta(days=n) for n in range(30)]
DAY = SESSIONS[-1]
PRIME, STANDARD = "0111", "0112"
LIQUID = Decimal("600000000")


class StandIn:
    """Holds whatever codes it is told to, ranked as it is told; records
    the frame and day it was asked about."""

    name = "stand_in"
    warmup_sessions = 5
    plots = (Plot("close", "price"),)

    def __init__(self, holdable: dict[str, float], on: set[date] | None = None) -> None:
        self.holdable, self.on = holdable, on
        self.asked: list[tuple] = []

    def evaluate(self, frame, day, holdings):
        closes = frame.wide(CLOSE)
        self.asked.append((sorted(closes.columns), closes.index.min(), day))
        return [
            Signal(code, Disposition.HOLD if code in self.holdable and (self.on is None or day in self.on)
                   else Disposition.STAY_OUT, (),
                   {"close": float(closes[code][day])}, self.holdable.get(code))
            for code in sorted(closes.columns)
        ]


def synced(engine, roster) -> MarketData:
    codes = [entry.code for entry in roster]
    client = FakeJQuants(SESSIONS, bars={day: [bar(code, day, str(100 + n), turnover=LIQUID) for code in codes]
                                         for n, day in enumerate(SESSIONS)},
                         roster=roster)
    market = MarketData(engine, client, today=lambda: DAY)
    market.sync()
    return market


def test_candidates_come_from_the_universe_best_first_with_their_names(migrated_database) -> None:
    market = synced(migrated_database, [
        listed("13010", PRIME, name="甲"), listed("13020", PRIME, name="乙"), listed("13030", PRIME, name="丙"),
        listed("13040", PRIME, name="丁"), listed("13050", STANDARD, name="戊"),
    ])
    strategy = StandIn({"13010": 0.3, "13030": 0.7, "13040": 0.3, "13050": 0.9})

    candidates = entry_candidates(market, strategy, DAY)

    assert [(c.instrument.code, c.instrument.name, c.signal.priority) for c in candidates] == [
        ("13030", "丙", 0.7), ("13010", "甲", 0.3), ("13040", "丁", 0.3),  # ties by code
    ]
    [(codes, first_day, day)] = strategy.asked
    assert codes == ["13010", "13020", "13030", "13040"]  # 13050 is not Prime: never read
    assert (first_day, day) == (SESSIONS[-5], DAY)         # the warm-up, the day included


def test_history_gives_the_bars_the_plotted_lines_and_the_days_it_would_have_been_bought(migrated_database) -> None:
    market = synced(migrated_database, [listed("13010", PRIME)])
    start = SESSIONS[-10]
    strategy = StandIn({"13010": 0.5}, on={SESSIONS[-8], SESSIONS[-3]})

    past = history(market, strategy, "13010", start, DAY)

    assert list(past.frame.wide(CLOSE).index) == SESSIONS[-10:]
    assert list(past.indicators.columns) == ["close"]
    assert list(past.indicators["close"]) == [100.0 + n for n in range(20, 30)]
    assert past.entries == [SESSIONS[-8], SESSIONS[-3]]
    assert {first_day for _, first_day, _ in strategy.asked} == {SESSIONS[-14]}  # one frame, warm-up included


def test_history_may_start_on_a_day_the_market_was_closed(migrated_database) -> None:
    """`from=` comes from the page: a weekend reads back from the session before it."""
    open_days = [day for day in SESSIONS if day.weekday() < 5]
    client = FakeJQuants(open_days, bars={day: [bar("13010", day, turnover=LIQUID)] for day in open_days},
                         roster=[listed("13010", PRIME)])
    market = MarketData(migrated_database, client, today=lambda: DAY)
    market.sync()
    saturday = next(day for day in SESSIONS[10:] if day.weekday() == 5)
    strategy = StandIn({})

    past = history(market, strategy, "13010", saturday, DAY)

    before = [day for day in open_days if day < saturday]
    assert {first_day for _, first_day, _ in strategy.asked} == {before[-5]}
    assert past.frame.wide(CLOSE).index.min() > saturday
