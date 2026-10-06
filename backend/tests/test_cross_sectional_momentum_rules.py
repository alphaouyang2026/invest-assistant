"""Cross-sectional momentum v1 (ticket 05 C, spec §6.6): on the first
session of each month — its check day — every Prime stock it can judge is
ranked by its past return, the last few sessions skipped, held or not; on
every other session nothing changes. Which are bought and which are ranked
out is the portfolio rules' doing (test_plan_orders). Judged through
`evaluate` on synthetic bars — no database."""

from __future__ import annotations

import math
from datetime import date

import pytest

from app.market_data import MarketFrame, UniverseRule
from app.strategies import STRATEGY_DEFAULTS, Disposition, Holding, Plot, WarmupFollows, build_strategy
from tests.frames import NO_BAR, frame_of, sessions, weekdays_through

HOLD, STAY_OUT = Disposition.HOLD, Disposition.STAY_OUT
RANKED, NOT_CHECK_DAY = ("momentum_rank",), ("not_check_day",)

CHECK_DAY = date(2025, 10, 1)   # a Wednesday, the first session of October
MID_MONTH = date(2025, 10, 15)  # a Wednesday


def momentum(**params):
    return build_strategy("cross_sectional_momentum_v1", params)


def test_it_ranks_prime_stocks_on_their_own_bars_holdings_among_them() -> None:
    strategy = momentum()

    assert STRATEGY_DEFAULTS["cross_sectional_momentum_v1"] == {
        "momentum_sessions": 126, "skip_sessions": 21, "warmup_sessions": 127}
    assert (strategy.universe_rule, strategy.reference_series) == (UniverseRule.PRIME_COMMON_STOCK, ())
    assert strategy.warmup_sessions == 127
    assert strategy.warmup_follows == WarmupFollows("momentum_sessions", 1)
    assert strategy.plots == (Plot("momentum", "separate"),)
    assert strategy.ranks_holdings is True


def test_on_the_check_day_every_stock_is_ranked_by_its_return_up_to_the_skipped_sessions() -> None:
    """Four sessions back to one back: A rose 20%, B fell 10%. The day's own
    close — a jump for B — is skipped. Held or not, each is ranked."""
    days = weekdays_through(CHECK_DAY, 5)
    frame = frame_of({"A": [100.0, 0.0, 0.0, 120.0, 90.0], "B": [50.0, 0.0, 0.0, 45.0, 99.0]}, days)
    strategy = momentum(momentum_sessions=4, skip_sessions=1, warmup_sessions=5)

    for holdings in ([], [Holding("A", 100, days[0])]):
        a, b = strategy.evaluate(frame, CHECK_DAY, holdings)

        assert [(s.code, s.disposition, s.reason_codes) for s in (a, b)] == [("A", HOLD, RANKED), ("B", HOLD, RANKED)]
        assert (a.priority, b.priority) == (pytest.approx(0.20), pytest.approx(-0.10))
    assert a.indicators == {"close": 90.0, "from_close": 100.0, "to_close": 120.0,
                            "momentum": pytest.approx(0.20), "check_day": 1.0}


def test_with_nothing_skipped_the_day_s_own_close_ends_the_return() -> None:
    days = weekdays_through(CHECK_DAY, 3)
    frame = frame_of({"A": [100.0, 0.0, 110.0]}, days)

    [a] = momentum(momentum_sessions=2, skip_sessions=0, warmup_sessions=3).evaluate(frame, CHECK_DAY, [])

    assert (a.indicators["to_close"], a.priority) == (110.0, pytest.approx(0.10))


def test_on_any_other_session_nothing_changes() -> None:
    days = weekdays_through(MID_MONTH, 5)
    frame = frame_of({"A": [100.0, 0.0, 0.0, 120.0, 90.0]}, days)
    strategy = momentum(momentum_sessions=4, skip_sessions=1, warmup_sessions=5)

    [flat] = strategy.evaluate(frame, MID_MONTH, [])
    [held] = strategy.evaluate(frame, MID_MONTH, [Holding("A", 100, days[0])])

    assert (flat.disposition, flat.reason_codes, flat.priority) == (STAY_OUT, NOT_CHECK_DAY, None)
    assert (held.disposition, held.reason_codes, held.priority) == (HOLD, (), None)
    assert flat.indicators["momentum"] == pytest.approx(0.20)  # worked out every session


def test_the_returns_count_back_over_the_sessions_the_stock_has_a_bar() -> None:
    days = weekdays_through(CHECK_DAY, 5)
    frame = frame_of({"A": [80.0, 100.0, NO_BAR, 110.0, 120.0]}, days)

    [a] = momentum(momentum_sessions=3, skip_sessions=1, warmup_sessions=4).evaluate(frame, CHECK_DAY, [])

    assert (a.indicators["from_close"], a.indicators["to_close"]) == (80.0, 110.0)


def test_no_signal_until_the_stock_has_the_momentum_sessions_and_the_day_s_own_close() -> None:
    days = weekdays_through(CHECK_DAY, 127)
    frame = frame_of({"short": [100.0] * 126, "enough": [100.0] * 127}, days)

    assert [s.code for s in momentum().evaluate(frame, CHECK_DAY, [])] == ["enough"]
    assert momentum(warmup_sessions=128).evaluate(frame, CHECK_DAY, []) == []


def test_nothing_after_the_day_is_seen() -> None:
    days = sessions(200, start=date(2025, 1, 6))
    whole = frame_of({"A": [100 + 10 * math.sin(n / 15) for n in range(200)],
                      "B": [100 + 10 * math.cos(n / 9) for n in range(200)]}, days)
    seen = set()

    for day in days[30:]:
        cut = MarketFrame(whole.data[whole.data.index.get_level_values("date") <= day])
        for holdings in ([], [Holding("A", 100, days[0])]):
            strategy = momentum(momentum_sessions=20, skip_sessions=5, warmup_sessions=21)
            judged_whole = strategy.evaluate(whole, day, holdings)
            assert judged_whole == momentum(momentum_sessions=20, skip_sessions=5, warmup_sessions=21).evaluate(
                cut, day, holdings)
            seen.update((signal.disposition, signal.reason_codes) for signal in judged_whole)

    assert seen == {(HOLD, RANKED), (STAY_OUT, NOT_CHECK_DAY), (HOLD, ())}


def test_an_unknown_parameter_a_warm_up_short_of_the_momentum_or_a_skip_that_cannot_be_is_refused() -> None:
    with pytest.raises(ValueError, match="return_sessions"):
        momentum(return_sessions=5)
    with pytest.raises(ValueError, match="预热期"):
        momentum(warmup_sessions=126)
    with pytest.raises(ValueError, match="预热期"):
        momentum(momentum_sessions=252)  # the warm-up left at 127
    with pytest.raises(ValueError, match="回看长度"):
        momentum(momentum_sessions=0, warmup_sessions=1)
    for skip in (-1, 2.5, 126):
        with pytest.raises(ValueError, match="跳过"):
            momentum(skip_sessions=skip)
    assert momentum(momentum_sessions=252, warmup_sessions=253).warmup_sessions == 253
    assert momentum(skip_sessions=0).warmup_sessions == 127
