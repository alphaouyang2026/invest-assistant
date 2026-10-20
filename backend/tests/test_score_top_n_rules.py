"""Score top-N v1 (ticket 06a): on its check days — every few sessions from
an anchor — every stock with a score from the model can be held, ranked by
it, held or not; a stock without one stays out or is sold; on a day the
model has nothing for nothing is opened and holdings stay; a holding held
long enough is sold whatever the day. Which are bought and which are ranked
out is the portfolio rules' doing (test_score_top_n_replay). Judged through
`evaluate` on synthetic bars and made-up scores — no database."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from app.market_data import MarketFrame, UniverseRule
from app.strategies import (
    STRATEGY_DEFAULTS, Disposition, Holding, ScoreTable, ScoreTopN, build_strategy, strategy_infos,
)
from tests.frames import NO_BAR, frame_of, sessions, weekdays_through

HOLD, EXIT, STAY_OUT = Disposition.HOLD, Disposition.EXIT, Disposition.STAY_OUT
RANKED, NOT_CHECK_DAY, MODEL_UNAVAILABLE, SCORE_MISSING, TIME_EXIT = (
    ("model_rank",), ("not_check_day",), ("model_unavailable",), ("score_missing",), ("time_exit",))

DAY = date(2025, 10, 15)  # a Wednesday


def top_n(scores: dict | None = None, unavailable=(), **params) -> ScoreTopN:
    return ScoreTopN(ScoreTable(scores or {}, frozenset(unavailable)), {"anchor": DAY.isoformat(), **params})


def judged(signals) -> list[tuple]:
    """What a signal says, its readings with NaN as None — NaN is not equal
    to itself, and a reading the table has no score for is NaN."""
    return [(s.code, s.disposition, s.reason_codes, s.priority,
             {name: None if math.isnan(value) else value for name, value in s.indicators.items()})
            for s in signals]


def test_it_ranks_prime_stocks_holdings_among_them_draws_nothing_and_is_not_offered_for_new_accounts() -> None:
    strategy = top_n()

    assert (strategy.name, strategy.universe_rule, strategy.reference_series) == (
        "score_top_n_v1", UniverseRule.PRIME_COMMON_STOCK, ())
    assert strategy.params == {"anchor": "2025-10-15", "rebalance_sessions": 5, "max_holding_sessions": 0,
                               "warmup_sessions": 1}
    assert strategy.warmup_sessions == 1
    assert strategy.warmup_follows is None
    assert strategy.plots == ()
    assert strategy.ranks_holdings is True

    assert "score_top_n_v1" not in STRATEGY_DEFAULTS
    assert "score_top_n_v1" not in [info.name for info in strategy_infos()]
    with pytest.raises(ValueError, match="没有这个策略"):
        build_strategy("score_top_n_v1", {"anchor": "2025-10-15"})


def test_the_check_days_are_every_rebalance_sessions_counted_on_the_frame_s_sessions_from_the_anchor() -> None:
    days = sessions(12, start=date(2025, 10, 6))  # Monday 6 to Tuesday 21 October
    frame = frame_of({"A": [100.0] * 12}, days)

    def check_days(anchor: date, **params) -> list[date]:
        strategy = ScoreTopN(ScoreTable({}), {"anchor": anchor.isoformat(), **params})
        return [day for day in days if strategy.evaluate(frame, day, [])[0].indicators["check_day"] == 1.0]

    assert check_days(days[2], rebalance_sessions=3) == [days[2], days[5], days[8], days[11]]
    assert check_days(days[2]) == [days[2], days[7]]  # every 5 by default
    assert check_days(days[0], rebalance_sessions=1) == days
    # A Saturday anchor: the first session after it is the first check day.
    assert check_days(date(2025, 10, 11), rebalance_sessions=4) == [days[5], days[9]]


def test_on_a_check_day_every_stock_with_a_score_is_ranked_by_it_held_or_not() -> None:
    days = weekdays_through(DAY, 3)
    frame = frame_of({"A": [100.0, 101.0, 102.0], "B": [50.0, 49.0, 48.0]}, days)
    strategy = top_n({DAY: {"A": 0.012, "B": -0.3}})

    for holdings in ([], [Holding("A", 100, days[0])], [Holding("A", 100, days[0]), Holding("B", 100, days[1])]):
        assert judged(strategy.evaluate(frame, DAY, holdings)) == [
            ("A", HOLD, RANKED, 0.012, {"score": 0.012, "check_day": 1.0}),
            ("B", HOLD, RANKED, -0.3, {"score": -0.3, "check_day": 1.0}),
        ]


def test_on_any_other_session_nothing_changes_whatever_the_table_holds() -> None:
    days = weekdays_through(DAY, 3)
    frame = frame_of({"A": [100.0, 101.0, 102.0]}, days)
    anchor = days[0].isoformat()
    scores = ScoreTable({days[0]: {"A": 0.5}, DAY: {"A": 0.7}})
    strategy = ScoreTopN(scores, {"anchor": anchor, "rebalance_sessions": 5})

    assert judged(strategy.evaluate(frame, DAY, [])) == [
        ("A", STAY_OUT, NOT_CHECK_DAY, None, {"score": 0.7, "check_day": 0.0})]
    assert judged(strategy.evaluate(frame, DAY, [Holding("A", 100, days[0])])) == [
        ("A", HOLD, NOT_CHECK_DAY, None, {"score": 0.7, "check_day": 0.0})]
    # Before the anchor too.
    early = ScoreTopN(scores, {"anchor": DAY.isoformat()})
    assert judged(early.evaluate(frame, days[1], [])) == [
        ("A", STAY_OUT, NOT_CHECK_DAY, None, {"score": None, "check_day": 0.0})]


def test_on_a_check_day_the_model_has_nothing_for_nothing_is_opened_and_holdings_keep_their_place() -> None:
    """Unavailable, missing from the table, or there with no score that is
    not NaN: the same. No score of an earlier day is used instead."""
    days = weekdays_through(DAY, 6)
    frame = frame_of({"A": [100.0] * 6, "B": [50.0] * 6}, days)
    earlier = {days[0]: {"A": 0.5, "B": 0.4}}
    held = [Holding("A", 100, days[1])]

    for strategy in (top_n({**earlier, DAY: {"A": 0.9, "B": 0.8}}, unavailable={DAY}),
                     top_n(earlier),
                     top_n({**earlier, DAY: {}}),
                     top_n({**earlier, DAY: {"A": float("nan")}})):
        assert judged(strategy.evaluate(frame, DAY, held)) == [
            ("A", HOLD, MODEL_UNAVAILABLE, None, {"score": None, "check_day": 1.0}),
            ("B", STAY_OUT, MODEL_UNAVAILABLE, None, {"score": None, "check_day": 1.0}),
        ]


def test_on_a_check_day_with_scores_a_stock_without_one_stays_out_or_is_sold() -> None:
    """It left the universe, or a feature was missing: no score, or NaN."""
    days = weekdays_through(DAY, 3)
    frame = frame_of({"A": [100.0] * 3, "B": [50.0] * 3, "C": [10.0] * 3}, days)
    strategy = top_n({DAY: {"A": 0.1, "C": float("nan")}})

    for holdings, b, c in (([], STAY_OUT, STAY_OUT),
                           ([Holding("B", 100, days[0]), Holding("C", 100, days[1])], EXIT, EXIT)):
        assert judged(strategy.evaluate(frame, DAY, holdings)) == [
            ("A", HOLD, RANKED, 0.1, {"score": 0.1, "check_day": 1.0}),
            ("B", b, SCORE_MISSING, None, {"score": None, "check_day": 1.0}),
            ("C", c, SCORE_MISSING, None, {"score": None, "check_day": 1.0}),
        ]


def test_a_holding_held_the_holding_sessions_is_sold_whatever_the_day_or_its_score() -> None:
    """Bought on the second of six sessions: on the last it has been held
    for five, the day it was bought counting as the first."""
    days = weekdays_through(DAY, 6)
    frame = frame_of({"A": [100.0] * 6}, days)
    held = [Holding("A", 100, days[1])]
    scored = {DAY: {"A": 9.0}}

    def disposition(scores=scored, unavailable=(), **params) -> tuple:
        [signal] = top_n(scores, unavailable, **params).evaluate(frame, DAY, held)
        return signal.disposition, signal.reason_codes, signal.priority

    assert disposition(max_holding_sessions=5) == (EXIT, TIME_EXIT, None)        # the best score
    assert disposition(max_holding_sessions=4) == (EXIT, TIME_EXIT, None)
    assert disposition(max_holding_sessions=6) == (HOLD, RANKED, 9.0)
    assert disposition(max_holding_sessions=0) == (HOLD, RANKED, 9.0)            # never
    assert disposition(max_holding_sessions=5, unavailable={DAY}) == (EXIT, TIME_EXIT, None)
    assert disposition({}, max_holding_sessions=5) == (EXIT, TIME_EXIT, None)    # model unavailable
    not_a_check_day = {"anchor": days[0].isoformat(), "rebalance_sessions": 4}
    assert disposition(max_holding_sessions=5, **not_a_check_day) == (EXIT, TIME_EXIT, None)
    assert disposition(max_holding_sessions=6, **not_a_check_day) == (HOLD, NOT_CHECK_DAY, None)


def test_the_holding_sessions_count_its_bars_a_halt_s_included() -> None:
    """A halt is a bar (untradable); a session with no bar at all is not."""
    days = weekdays_through(DAY, 6)
    frame = frame_of({"A": [100.0, 100.0, NO_BAR, None, 100.0, 100.0], "B": [50.0] * 6}, days)
    held = [Holding("A", 100, days[1])]

    def a(**params):
        return next(s for s in top_n({DAY: {"A": 1.0}}, **params).evaluate(frame, DAY, held) if s.code == "A")

    assert (a(max_holding_sessions=4).disposition, a(max_holding_sessions=5).disposition) == (EXIT, HOLD)


def test_equal_scores_rank_equal_the_portfolio_rules_break_the_tie() -> None:
    days = weekdays_through(DAY, 2)
    frame = frame_of({"A": [100.0] * 2, "B": [50.0] * 2}, days)

    a, b = top_n({DAY: {"A": 0.25, "B": 0.25}}).evaluate(frame, DAY, [Holding("B", 100, days[0])])

    assert (a.disposition, a.priority) == (b.disposition, b.priority) == (HOLD, 0.25)


def test_no_signal_on_a_halt_on_a_session_without_a_bar_or_before_the_warm_up() -> None:
    days = weekdays_through(DAY, 3)
    frame = frame_of({"listed_today": [100.0], "halted": [100.0, 100.0, None], "gone": [100.0, 100.0, NO_BAR],
                      "B": [50.0] * 3}, days)
    scores = {DAY: {"listed_today": 1.0, "halted": 1.0, "gone": 1.0, "B": 1.0}}

    assert [s.code for s in top_n(scores).evaluate(frame, DAY, [Holding("halted", 100, days[0])])] == [
        "B", "listed_today"]
    assert [s.code for s in top_n(scores, warmup_sessions=2).evaluate(frame, DAY, [])] == ["B"]


def test_a_frame_that_starts_after_the_anchor_is_refused() -> None:
    days = weekdays_through(DAY, 3)
    frame = frame_of({"A": [100.0] * 3}, days)

    assert top_n(anchor=days[0].isoformat()).evaluate(frame, DAY, [])
    with pytest.raises(ValueError, match="晚于锚点"):
        top_n(anchor=(days[0] - timedelta(days=1)).isoformat()).evaluate(frame, DAY, [])


def test_nothing_after_the_day_is_seen_in_the_bars_or_the_scores() -> None:
    days = sessions(60, start=date(2025, 1, 6))
    whole = frame_of({"A": [100 + 10 * math.sin(n / 3) for n in range(60)],
                      "B": [100 + 10 * math.cos(n / 2) for n in range(60)],
                      "C": [50 + 5 * math.sin(n / 5) for n in range(60)]}, days)
    anchor, every = days[6], 3
    check = days[6::every]
    scores = {day: {"A": math.sin(n), "B": math.cos(n), "C": math.sin(2 * n)} for n, day in enumerate(check)}
    del scores[check[2]]["A"]                     # A has no score: sold if held
    del scores[check[4]]["C"]                     # C has no score: stays out
    unavailable = frozenset({check[6]})          # the model failed: nothing that day
    params = {"anchor": anchor.isoformat(), "rebalance_sessions": every, "max_holding_sessions": 4}
    seen = set()

    for n, day in enumerate(days[4:], 4):
        cut = MarketFrame(whole.data[whole.data.index.get_level_values("date") <= day])
        so_far = ScoreTable({d: s for d, s in scores.items() if d <= day}, frozenset(d for d in unavailable if d <= day))
        # A bought the session before (held two), B four before (held five: sold).
        for holdings in ([], [Holding("A", 100, days[n - 1]), Holding("B", 100, days[n - 4])]):
            judged_whole = ScoreTopN(ScoreTable(scores, unavailable), params).evaluate(whole, day, holdings)
            assert judged(judged_whole) == judged(ScoreTopN(ScoreTable(scores, unavailable), params).evaluate(
                cut, day, holdings))
            assert judged(judged_whole) == judged(ScoreTopN(so_far, params).evaluate(cut, day, holdings))
            seen.update((signal.disposition, signal.reason_codes) for signal in judged_whole)

    assert seen == {(HOLD, RANKED), (STAY_OUT, NOT_CHECK_DAY), (HOLD, NOT_CHECK_DAY), (STAY_OUT, MODEL_UNAVAILABLE),
                    (HOLD, MODEL_UNAVAILABLE), (STAY_OUT, SCORE_MISSING), (EXIT, SCORE_MISSING), (EXIT, TIME_EXIT)}


def test_an_unknown_parameter_a_missing_or_bad_anchor_or_a_window_that_cannot_be_is_refused() -> None:
    table = ScoreTable({})
    with pytest.raises(ValueError, match="sma_sessions"):
        ScoreTopN(table, {"anchor": "2025-10-15", "sma_sessions": 5})
    with pytest.raises(ValueError, match="锚点"):
        ScoreTopN(table, {})
    with pytest.raises(ValueError, match="锚点"):
        ScoreTopN(table, {"anchor": "15/10/2025"})
    for every in (0, 2.5):
        with pytest.raises(ValueError, match="调仓间隔"):
            top_n(rebalance_sessions=every)
    for holding in (-1, 2.5):
        with pytest.raises(ValueError, match="最长持有"):
            top_n(max_holding_sessions=holding)
    with pytest.raises(ValueError, match="预热期"):
        top_n(warmup_sessions=0)
    strategy = ScoreTopN(table, {"anchor": date(2025, 10, 15), "rebalance_sessions": 10, "max_holding_sessions": 20,
                                 "warmup_sessions": 61})
    assert strategy.warmup_sessions == 61
