"""Score top-N v1 through the accounts' daily trading rules (`replay_day`,
spec §7.1–7.3), on synthetic bars and made-up scores — no database: what it
buys, keeps, ranks out and sells, session by session, and that the ledger's
facts, not the strategy's intentions, decide what it holds when an order
cannot fill."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from app.accounts.accounts import Prices, replay_day
from app.accounts.ledger import Ledger
from app.accounts.planning import PortfolioRules
from app.accounts.records import BUY, EXPIRED, FILLED, PENDING, SELL
from app.accounts.session import Costs
from app.market_data import EXEC_HIGH, EXEC_LOW, EXEC_OPEN, LOWER_LIMIT_HIT, UPPER_LIMIT_HIT, MarketFrame
from app.strategies import ScoreTable, ScoreTopN
from tests.frames import frame_of, sessions

DAYS = sessions(14, start=date(2025, 10, 6))
D = dict(enumerate(DAYS))  # D[n]: the n-th session
CODES = ("A", "B", "C", "D")
# Two places, 30% of the NAV each: what a sell brings in is not needed for a buy.
RULES = PortfolioRules(max_positions=2, max_weight=Decimal("0.3"), cash_floor=Decimal("0.05"))
INITIAL = Decimal(10_000_000)


def flat_market(**limits) -> MarketFrame:
    """Every code at 1,000 every session. `limits[code]` are the sessions it
    opens on a limit: ("up", n) at the upper limit, ("down", n) the lower."""
    frame = frame_of({code: [1000.0] * len(DAYS) for code in CODES}, DAYS)
    data = frame.data.copy()
    for code, opens in limits.items():
        for side, n in opens:
            row = (code, D[n])
            flag, price = (UPPER_LIMIT_HIT, EXEC_HIGH) if side == "up" else (LOWER_LIMIT_HIT, EXEC_LOW)
            data.loc[row, flag] = True
            data.loc[row, price] = data.loc[row, EXEC_OPEN]
    return MarketFrame(data)


def strategy(scores: dict, max_holding_sessions: int = 0) -> ScoreTopN:
    """Decision days every three sessions from the second: D[1], D[4], D[7], D[10], D[13]."""
    return ScoreTopN(ScoreTable(frozenset(DAYS[1::3]), scores), {"max_holding_sessions": max_holding_sessions})


def replay(frame: MarketFrame, top_n: ScoreTopN, universes: dict | None = None,
           rules: PortfolioRules = RULES) -> dict[date, tuple[Ledger, list]]:
    """Each session's ledger at the close and the records it wrote, numbered
    the way a research run numbers them."""
    prices, ledger, serial, days = Prices(frame), Ledger(INITIAL), 0, {}
    universes = universes or {day: list(CODES) for day in DAYS}
    for n, day in enumerate(DAYS):
        next_day = D.get(n + 1, day + timedelta(days=3))
        changed, _ = replay_day(ledger, prices, top_n, universes, day, next_day, rules, Costs())
        final = {r.id: r for r in changed if r.id is not None}
        stored = []
        for record in changed:
            if record.id is None:
                serial += 1
                stored.append(replace(record, id=serial))
            elif final[record.id] is record:
                stored.append(record)
        ledger = ledger.apply(stored)
        days[day] = ledger, stored
    return days


def planned(record_of_day: tuple[Ledger, list]) -> list[tuple]:
    """The orders the day's close placed for the next open, with why."""
    _, stored = record_of_day
    return [(r.kind, r.code, *r.reason["reason_codes"], *(["again"] if "replaces" in r.reason else []))
            for r in stored if r.status == PENDING]


def held(record_of_day: tuple[Ledger, list]) -> dict[str, date]:
    ledger, _ = record_of_day
    return {code: position.opened_on for code, position in sorted(ledger.positions.items())}


def test_from_nothing_it_opens_holds_ranks_out_times_out_waits_out_the_model_and_comes_back() -> None:
    scores = {
        D[1]: {"A": 3.0, "B": 2.0, "C": 1.0},
        D[4]: {"C": 5.0, "A": 4.0, "B": 1.0, "D": 0.0},
        # D[7]: the model failed that day
        D[10]: {"A": 6.0, "D": 2.0, "B": 1.0, "C": 0.0},
        D[13]: {"D": 1.0, "B": 2.0, "C": 0.0},             # A left the universe
    }
    universes = {day: list(CODES) for day in DAYS} | {D[13]: ["B", "C", "D"]}
    days = replay(flat_market(), strategy(scores, max_holding_sessions=5), universes)

    expected = {
        0: ([], {}),                                                           # before the anchor
        1: ([(BUY, "A", "model_rank"), (BUY, "B", "model_rank")], {}),         # the top two of three
        2: ([], {"A": D[2], "B": D[2]}),
        3: ([], {"A": D[2], "B": D[2]}),                                       # not a check day
        4: ([(SELL, "B", "ranked_out"), (BUY, "C", "model_rank")], {"A": D[2], "B": D[2]}),
        5: ([], {"A": D[2], "C": D[5]}),
        6: ([(SELL, "A", "time_exit")], {"A": D[2], "C": D[5]}),               # its fifth session
        7: ([], {"C": D[5]}),                  # a place free, the model unavailable: nothing opened, C kept
        8: ([], {"C": D[5]}),
        9: ([(SELL, "C", "time_exit")], {"C": D[5]}),
        10: ([(BUY, "A", "model_rank"), (BUY, "D", "model_rank")], {}),       # A back
        11: ([], {"A": D[11], "D": D[11]}),
        12: ([], {"A": D[11], "D": D[11]}),
        13: ([(SELL, "A", "score_missing"), (BUY, "B", "model_rank")], {"A": D[11], "D": D[11]}),
    }
    assert {n: (planned(days[day]), held(days[day])) for n, day in D.items()} == expected
    last, _ = days[D[13]]
    assert all(r.status == FILLED for r in last.records if r.status != PENDING)  # no limits: every order due filled


def test_a_buy_that_cannot_fill_leaves_the_place_free_for_the_next_check_day() -> None:
    """B's buy meets a limit-up open: the ledger has no B, so the strategy
    is not told it holds B, and on the next check day B is a candidate
    again for the place it left free."""
    scores = {D[1]: {"A": 3.0, "B": 2.0}, D[4]: {"A": 3.0, "B": 2.0, "C": 1.0}}
    days = replay(flat_market(B=[("up", 2)]), strategy(scores))

    _, opened = days[D[2]]
    assert [(r.code, r.status, r.outcome_reason) for r in opened if r.kind == BUY] == [
        ("A", FILLED, None), ("B", EXPIRED, "limit_up_open")]
    assert held(days[D[2]]) == held(days[D[3]]) == {"A": D[2]}
    assert planned(days[D[3]]) == []
    assert planned(days[D[4]]) == [(BUY, "B", "model_rank")]
    assert held(days[D[5]]) == {"A": D[2], "B": D[5]}


def test_a_sell_that_cannot_fill_keeps_the_holding_and_its_place_until_it_does() -> None:
    """B is ranked out on D[4] but opens limit-down three sessions running.
    It stays in the ledger, its sell is placed again each day without the
    strategy (spec §7.1 step 4), and on the check day D[7] it still takes a
    place — whatever its score — so only one of the others is kept."""
    scores = {D[1]: {"A": 3.0, "B": 2.0},
              D[4]: {"C": 5.0, "A": 4.0, "B": 1.0},
              D[7]: {"B": 9.0, "C": 5.0, "A": 4.0, "D": 1.0}}
    days = replay(flat_market(B=[("down", 5), ("down", 6), ("down", 7)]), strategy(scores))

    assert planned(days[D[4]]) == [(SELL, "B", "ranked_out"), (BUY, "C", "model_rank")]
    for n in (5, 6):
        assert held(days[D[n]]) == {"A": D[2], "B": D[2], "C": D[5]}  # three: the ledger's facts
        assert planned(days[D[n]]) == [(SELL, "B", "ranked_out", "again")]
    assert planned(days[D[7]]) == [(SELL, "B", "ranked_out", "again"), (SELL, "A", "ranked_out")]
    assert held(days[D[8]]) == {"C": D[5]}


def test_equal_scores_go_by_code_held_or_not() -> None:
    """Spec §7.2: by priority, then code. One place, B held, A as good: A
    takes it."""
    one_place = PortfolioRules(max_positions=1, max_weight=Decimal("0.3"), cash_floor=Decimal("0.05"))
    scores = {D[1]: {"B": 1.0}, D[4]: {"C": 0.5, "B": 0.5, "A": 0.5}}

    days = replay(flat_market(), strategy(scores), rules=one_place)

    assert held(days[D[4]]) == {"B": D[2]}
    assert planned(days[D[4]]) == [(SELL, "B", "ranked_out"), (BUY, "A", "model_rank")]
