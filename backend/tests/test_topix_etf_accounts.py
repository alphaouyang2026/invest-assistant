"""Accounts on the TOPIX ETF strategies (.scratch/topix-etf-strategies spec):
the real strategies, advanced through the fake J-Quants market with 1306
listed as an ETF (0109 / 014) beside a Prime stock. Fills, lots, splits and
valuation are the rules every account has (spec §7)."""

from __future__ import annotations

from decimal import Decimal

from app.accounts import Accounts, AccountSpec, PortfolioRules
from app.strategies import Disposition
from tests.account_market import ETF_LISTINGS, SESSIONS, TOPIX_ETF, Script, synced

# What the new-account page suggests for a TOPIX ETF strategy: about 95% of
# the NAV in 1306.
ONE_ETF = PortfolioRules(max_positions=1, max_weight=Decimal(1), cash_floor=Decimal("0.05"))
TEN_FOR_ONE = {"adjustment_factor": Decimal("0.1"), "ex_rights_type": 1}


def summary(orders) -> list[tuple]:
    return [(o.kind, o.code, o.signal_date, o.execution_date, o.planned_quantity, o.status, o.filled_quantity,
             o.fill_price) for o in orders]


def buy_and_hold(engine, prices: dict, **market) -> tuple[Accounts, int]:
    accounts = Accounts(engine, synced(engine, prices, listings=ETF_LISTINGS, **market))
    account = accounts.create(AccountSpec(name="一直持有", strategy="topix_buy_and_hold_v1",
                                          start_date=SESSIONS[1], rules=ONE_ETF))
    return accounts, account


def test_the_control_group_buys_1306_at_the_next_open_with_95_percent_of_the_nav(migrated_database) -> None:
    """⌊10,000,000 × 95% ÷ 3,000 ÷ 100⌋ × 100 = ⌊31.67⌋ × 100 = 3,100 shares,
    at the open plus 0.1% slippage. The Prime stock is not touched."""
    accounts, account = buy_and_hold(migrated_database, {"13010": ["1000"] * 10, TOPIX_ETF: ["3000"] * 10})

    accounts.advance(account, through=SESSIONS[2])

    [bought] = accounts.report(account).orders
    assert summary([bought]) == [("buy", TOPIX_ETF, SESSIONS[1], SESSIONS[2], 3100, "filled", 3100, Decimal("3003.000"))]
    assert (bought.priority, bought.reason) == (1.0, {"disposition": "hold", "reason_codes": ["always_hold"]})


def test_the_control_group_buys_once_and_never_sells(migrated_database) -> None:
    """Through a 1306 down 1/6 after the purchase."""
    accounts, account = buy_and_hold(migrated_database, {TOPIX_ETF: ["3000"] * 3 + ["2500"] * 7})

    accounts.advance(account)

    report = accounts.report(account)
    assert [(o.kind, o.execution_date, o.status) for o in report.orders] == [("buy", SESSIONS[2], "filled")]
    assert [(h.code, h.quantity, h.opened_on) for h in report.holdings] == [(TOPIX_ETF, 3100, SESSIONS[2])]
    assert report.pending == []


def test_a_ten_for_one_split_makes_the_holding_ten_times_larger_and_leaves_the_nav_whole(migrated_database) -> None:
    """Cash after the purchase 10,000,000 − 3,100 × 3,003 = 690,700: the NAV is
    690,700 + 3,100 × 3,000 the day before the split and 690,700 + 31,000 × 300
    on it — the same 9,990,700."""
    accounts, account = buy_and_hold(migrated_database, {TOPIX_ETF: ["3000"] * 5 + ["300"] * 5},
                                     extra={(TOPIX_ETF, 5): TEN_FOR_ONE})

    accounts.advance(account, through=SESSIONS[7])

    report = accounts.report(account)
    [split] = [o for o in report.orders if o.kind == "split_adjustment"]
    assert (split.execution_date, split.filled_quantity, split.cash_delta) == (SESSIONS[5], 27900, Decimal(0))
    assert [(h.code, h.quantity) for h in report.holdings] == [(TOPIX_ETF, 31000)]
    assert list(report.nav[SESSIONS[2]:SESSIONS[7]]) == [Decimal("9990700")] * 6
    assert [o.kind for o in report.orders] == ["buy", "split_adjustment"]  # nothing bought or sold after


def test_a_stock_account_trades_and_values_as_before_with_1306_in_the_market(migrated_database) -> None:
    """1306 never enters the Prime common stock universe, even for a
    strategy that would hold it: the stock alone is bought and sold, worked
    by hand as in test_accounts_advance — bought 900 at 1,001, sold at 999."""
    market = synced(migrated_database, {"13010": ["1000"] * 10, TOPIX_ETF: ["3000"] * 10}, listings=ETF_LISTINGS)
    plan = {SESSIONS[1]: {"13010": Disposition.HOLD, TOPIX_ETF: Disposition.HOLD},
            SESSIONS[4]: {"13010": Disposition.EXIT}}
    accounts = Accounts(migrated_database, market, build_strategy=lambda name, params: Script(plan))
    account = accounts.create(AccountSpec(name="个股", strategy="script", start_date=SESSIONS[1]))

    accounts.advance(account, through=SESSIONS[6])

    report = accounts.report(account)
    assert summary(report.orders) == [
        ("buy", "13010", SESSIONS[1], SESSIONS[2], 900, "filled", 900, Decimal("1001.000")),
        ("sell", "13010", SESSIONS[4], SESSIONS[5], 900, "filled", 900, Decimal("999.000")),
    ]
    assert list(report.nav) == [Decimal("10000000"), Decimal("9999100"), Decimal("9999100"), Decimal("9999100"),
                                Decimal("9998200"), Decimal("9998200")]
