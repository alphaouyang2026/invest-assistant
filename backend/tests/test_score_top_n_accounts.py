"""A paper account on score top-N (ticket 06a), advanced through the fake
J-Quants market: built round its table of scores by the caller — it is not
in the new-account registry — and advanced in two goes, the second reading
a frame that starts after the first decision day, as a paper account
advancing day by day does. It trades exactly as one advanced in one go."""

from __future__ import annotations

from decimal import Decimal

from app.accounts import Accounts, AccountSpec, PortfolioRules
from app.strategies import ScoreTable, ScoreTopN
from tests.account_market import SESSIONS, synced

S = SESSIONS
TABLE = ScoreTable(frozenset({S[1], S[4], S[7]}), {
    S[1]: {"13010": 2.0, "13020": 1.0},
    S[4]: {"13030": 3.0, "13010": 2.0, "13020": 1.0},
    S[7]: {"13020": 5.0, "13030": 4.0},  # 13010 has none: sold
})
RULES = PortfolioRules(max_positions=2, max_weight=Decimal("0.3"))


def comparable(orders) -> list[tuple]:
    """Everything but the row ids, which differ between accounts."""
    return [tuple(value for key, value in vars(order).items() if key != "id") for order in orders]


def built_round(table: ScoreTable, frame_starts: dict):
    """An `Accounts` strategy builder: score top-N round `table`, noting in
    `frame_starts` where the frame it is given on each day starts."""
    class Watched(ScoreTopN):
        def evaluate(self, frame, day, holdings):
            frame_starts[day] = min(frame.data.index.get_level_values("date"))
            return super().evaluate(frame, day, holdings)

    return lambda name, params: Watched(table, params)


def test_an_account_advanced_in_two_goes_trades_as_one_advanced_in_one(migrated_database) -> None:
    market = synced(migrated_database, {code: ["1000"] * 10 for code in ("13010", "13020", "13030")})
    two_goes, one_go = {}, {}
    in_two = Accounts(migrated_database, market, build_strategy=built_round(TABLE, two_goes))
    in_one = Accounts(migrated_database, market, build_strategy=built_round(TABLE, one_go))
    stepwise = in_two.create(AccountSpec(name="分两次", strategy="score_top_n_v1", start_date=S[1], rules=RULES))
    whole = in_one.create(AccountSpec(name="一次", strategy="score_top_n_v1", start_date=S[1], rules=RULES))

    in_two.advance(stepwise, through=S[5])
    in_two.advance(stepwise, through=S[9])
    in_one.advance(whole, through=S[9])

    # The second go reads from the oldest holding's opening: after the first decision day.
    assert (two_goes[S[7]], one_go[S[7]]) == (S[2], S[0])
    orders = in_two.report(stepwise).orders
    assert [(o.kind, o.code, o.signal_date, o.execution_date, o.status, o.reason["reason_codes"])
            for o in orders] == [
        ("buy", "13010", S[1], S[2], "filled", ["model_rank"]),
        ("buy", "13020", S[1], S[2], "filled", ["model_rank"]),
        ("sell", "13020", S[4], S[5], "filled", ["ranked_out"]),
        ("buy", "13030", S[4], S[5], "filled", ["model_rank"]),
        ("sell", "13010", S[7], S[8], "filled", ["score_missing"]),
        ("buy", "13020", S[7], S[8], "filled", ["model_rank"]),
    ]
    assert comparable(orders) == comparable(in_one.report(whole).orders)
