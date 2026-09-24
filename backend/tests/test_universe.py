"""The universe (spec §6.1): who may be newly bought on a session — Prime
common stock that day, ¥500M average turnover over the last 20 sessions,
and not untradable that day."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.market_data import MarketData
from tests.fakes import FakeJQuants, bar, listed

SESSIONS = [date(2026, 8, 3) + timedelta(days=n) for n in range(25)]
DAY = SESSIONS[-1]
PRIME, STANDARD, COMMON_STOCK = "0111", "0112", "011"
LIQUID = Decimal("600000000")


def market_with(engine, bars_for, roster) -> MarketData:
    """`bars_for(day)` gives each session's bars; `roster` is fixed or a
    function of the date, as `FakeJQuants` takes it."""
    client = FakeJQuants(SESSIONS, bars={day: bars_for(day) for day in SESSIONS}, roster=roster)
    market = MarketData(engine, client, today=lambda: DAY)
    market.sync()
    return market


def test_only_prime_common_stock_is_in_the_universe(migrated_database) -> None:
    market = market_with(
        migrated_database,
        lambda day: [bar(code, day, turnover=LIQUID) for code in ("13010", "13020", "13030")],
        [listed("13010", PRIME), listed("13020", STANDARD), listed("13030", PRIME, product="012")],
    )

    assert market.universe(DAY) == ["13010"]


def test_the_last_20_sessions_must_average_500_million_yen_counting_missing_and_untradable_days_as_nothing(
    migrated_database,
) -> None:
    window = SESSIONS[-20:]
    gap_day, halt_day = window[3], window[7]

    def bars_for(day):
        yen = lambda amount: Decimal(amount) * 10**8  # noqa: E731
        bars = [
            bar("13010", day, turnover=yen(6)),
            bar("13040", day, turnover=yen(5)),                                   # exactly the line
            bar("13050", day, turnover=yen(5) if day in window else yen(1)),      # thin only before the window
        ]
        if day != gap_day:
            bars.append(bar("13020", day, turnover=yen(5)))                       # 19 × 5 / 20 < 5
        bars.append(bar("13030", day, close=None, turnover=yen("5.2")) if day == halt_day
                    else bar("13030", day, turnover=yen("5.2")))                  # 19 × 5.2 / 20 < 5
        return bars

    market = market_with(migrated_database, bars_for, [listed(code, PRIME) for code in
                                                       ("13010", "13020", "13030", "13040", "13050")])

    assert market.universe(DAY) == ["13010", "13040", "13050"]


def test_a_code_needs_a_tradable_bar_that_day(migrated_database) -> None:
    def bars_for(day):
        bars = [bar("13010", day, turnover=LIQUID)]
        if day == DAY:
            bars += [
                bar("13020", day, close=None, turnover=LIQUID),        # untradable, e.g. halted
                bar("13040", day, volume=None, turnover=LIQUID),       # excluded: prices fine, volume missing
            ]
        else:
            bars += [bar(code, day, turnover=LIQUID) for code in ("13020", "13030", "13040")]  # 13030 has no bar that day
        return bars

    market = market_with(migrated_database, bars_for, [listed(code, PRIME) for code in ("13010", "13020", "13030", "13040")])

    assert market.universe(DAY) == ["13010", "13040"]


def test_the_segment_is_the_one_that_day_not_todays(migrated_database) -> None:
    moved_on = SESSIONS[-3]

    def roster(day):
        return [listed("13010", PRIME if day >= moved_on else STANDARD),     # moved up
                listed("13020", STANDARD if day >= moved_on else PRIME)]     # moved down

    market = market_with(migrated_database, lambda day: [bar(code, day, turnover=LIQUID) for code in ("13010", "13020")], roster)

    assert market.universe(DAY) == ["13010"]
    assert market.universe(SESSIONS[-4]) == ["13020"]
