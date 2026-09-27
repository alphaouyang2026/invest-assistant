"""`Accounts.advance` (spec §7.1, A.4): the account moved a session at a
time through the real market data module. A stand-in strategy says what to
hold and when to sell, so these tests are about the day's order of things,
not about any strategy's rules."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.accounts import Accounts, AccountSpec
from app.strategies import Disposition
from tests.account_market import SESSIONS, Script, synced

def summary(orders) -> list[tuple]:
    return [(o.kind, o.code, o.signal_date, o.execution_date, o.planned_quantity, o.status, o.filled_quantity,
             o.fill_price) for o in orders]


def test_held_at_one_close_bought_at_the_next_open_sold_the_same_way(migrated_database) -> None:
    market = synced(migrated_database, {"13010": ["1000"] * 10})
    script = Script({SESSIONS[1]: {"13010": Disposition.HOLD}, SESSIONS[4]: {"13010": Disposition.EXIT}})
    accounts = Accounts(migrated_database, market, build_strategy=lambda name, params: script)
    account = accounts.create(AccountSpec(name="试", strategy="script", start_date=SESSIONS[1]))

    accounts.advance(account, through=SESSIONS[6])

    assert summary(accounts.report(account).orders) == [
        ("buy", "13010", SESSIONS[1], SESSIONS[2], 900, "filled", 900, Decimal("1001.000")),
        ("sell", "13010", SESSIONS[4], SESSIONS[5], 900, "filled", 900, Decimal("999.000")),
    ]
    assert script.asked[3] == (SESSIONS[4], [("13010", 900, SESSIONS[2])])  # the strategy sees the holding


def comparable(orders) -> list[tuple]:
    """Everything but the row ids, which differ between accounts."""
    return [tuple(value for key, value in vars(order).items() if key != "id") for order in orders]


PLAN = {SESSIONS[1]: {"13010": Disposition.HOLD, "13020": Disposition.HOLD},
        SESSIONS[3]: {"13010": Disposition.EXIT}, SESSIONS[6]: {"13020": Disposition.EXIT}}


def test_advancing_again_does_nothing_and_advancing_further_carries_on(migrated_database) -> None:
    market = synced(migrated_database, {"13010": ["1000"] * 10, "13020": ["2000"] * 10})
    accounts = Accounts(migrated_database, market, build_strategy=lambda name, params: Script(PLAN))
    account = accounts.create(AccountSpec(name="试", strategy="script", start_date=SESSIONS[1]))

    accounts.advance(account, through=SESSIONS[4])
    first = comparable(accounts.report(account).orders)
    assert accounts.advance(account, through=SESSIONS[4]).sessions == []
    assert comparable(accounts.report(account).orders) == first

    assert accounts.advance(account, through=SESSIONS[8]).sessions == SESSIONS[5:9]
    once = Accounts(migrated_database, market, build_strategy=lambda name, params: Script(PLAN))
    whole = once.create(AccountSpec(name="一次", strategy="script", start_date=SESSIONS[1]))
    once.advance(whole, through=SESSIONS[8])
    assert comparable(accounts.report(account).orders) == comparable(once.report(whole).orders)


class Interrupted(Script):
    """Fails once, on one session — as a killed process would."""

    def __init__(self, plan, fail_on: date) -> None:
        super().__init__(plan)
        self.fail_on = fail_on

    def evaluate(self, frame, day, holdings):
        if day == self.fail_on:
            self.fail_on = None
            raise RuntimeError("interrupted")
        return super().evaluate(frame, day, holdings)


def test_an_interrupted_advance_resumes_where_it_stopped(migrated_database) -> None:
    market = synced(migrated_database, {"13010": ["1000"] * 10, "13020": ["2000"] * 10})
    flaky = Interrupted(PLAN, fail_on=SESSIONS[5])
    accounts = Accounts(migrated_database, market, build_strategy=lambda name, params: flaky)
    account = accounts.create(AccountSpec(name="断", strategy="script", start_date=SESSIONS[1]))

    with pytest.raises(RuntimeError):
        accounts.advance(account, through=SESSIONS[8])
    accounts.advance(account, through=SESSIONS[8])

    steady = Accounts(migrated_database, market, build_strategy=lambda name, params: Script(PLAN))
    reference = steady.create(AccountSpec(name="稳", strategy="script", start_date=SESSIONS[1]))
    steady.advance(reference, through=SESSIONS[8])
    assert comparable(accounts.report(account).orders) == comparable(steady.report(reference).orders)


def test_a_sell_halted_for_three_sessions_is_placed_again_each_day_until_it_fills(migrated_database) -> None:
    """Told to sell at SESSIONS[3]'s close; SESSIONS[4–6] halted; sold at
    SESSIONS[7]'s open. Told again while halted, it still makes one sell a day."""
    market = synced(migrated_database, {"13010": ["1000"] * 4 + [None] * 3 + ["900"] * 3})
    plan = {SESSIONS[1]: {"13010": Disposition.HOLD}}
    plan |= {SESSIONS[n]: {"13010": Disposition.EXIT} for n in (3, 4, 5, 6)}
    accounts = Accounts(migrated_database, market, build_strategy=lambda name, params: Script(plan))
    account = accounts.create(AccountSpec(name="停", strategy="script", start_date=SESSIONS[1]))

    accounts.advance(account, through=SESSIONS[8])

    assert [(o.kind, o.execution_date, o.status, o.outcome_reason, o.filled_quantity)
            for o in accounts.report(account).orders if o.kind == "sell"] == [
        ("sell", SESSIONS[4], "expired", "untradable", 0),
        ("sell", SESSIONS[5], "expired", "untradable", 0),
        ("sell", SESSIONS[6], "expired", "untradable", 0),
        ("sell", SESSIONS[7], "filled", None, 900),
    ]


def test_a_split_on_a_held_code_doubles_the_shares_it_holds(migrated_database) -> None:
    market = synced(migrated_database, {"13010": ["1000"] * 5 + ["500"] * 5},
                    extra={("13010", 5): {"adjustment_factor": Decimal("0.5"), "ex_rights_type": 1}})
    accounts = Accounts(migrated_database, market,
                        build_strategy=lambda name, params: Script({SESSIONS[1]: {"13010": Disposition.HOLD}}))
    account = accounts.create(AccountSpec(name="拆", strategy="script", start_date=SESSIONS[1]))

    accounts.advance(account, through=SESSIONS[6])

    [split] = [o for o in accounts.report(account).orders if o.kind == "split_adjustment"]
    assert (split.execution_date, split.filled_quantity, split.cash_delta) == (SESSIONS[5], 900, Decimal(0))


def test_a_holding_gone_from_the_roster_is_settled_at_its_last_close(migrated_database) -> None:
    market = synced(migrated_database, {"13010": ["1000"] * 4 + ["950", "940"] + ["930"] * 4}, gone={"13010": 6})
    accounts = Accounts(migrated_database, market,
                        build_strategy=lambda name, params: Script({SESSIONS[1]: {"13010": Disposition.HOLD}}))
    account = accounts.create(AccountSpec(name="退", strategy="script", start_date=SESSIONS[1]))

    accounts.advance(account, through=SESSIONS[8])

    [settled] = [o for o in accounts.report(account).orders if o.kind == "delisting_settlement"]
    assert (settled.execution_date, settled.filled_quantity, settled.fill_price, settled.cash_delta) == (
        SESSIONS[6], 900, Decimal("940"), Decimal("846000"))
