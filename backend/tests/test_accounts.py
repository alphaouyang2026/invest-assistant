"""`Accounts` besides `advance` (spec §7.1, A.4): creating an account and
what is checked then; listing, stopping and deleting."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

import pytest

from app.accounts import Accounts, AccountSpec
from app.strategies import Disposition, build_strategy
from tests.account_market import SESSIONS, Script, synced


class NeedsThree(Script):
    warmup_sessions = 3


def test_the_start_must_be_a_session_with_the_warm_up_behind_it(migrated_database) -> None:
    market = synced(migrated_database, {"13010": ["1000"] * 10})
    accounts = Accounts(migrated_database, market, build_strategy=lambda name, params: NeedsThree({}))

    with pytest.raises(ValueError, match="开市日"):
        accounts.create(AccountSpec(name="休市", strategy="script", start_date=SESSIONS[0] - timedelta(days=1)))
    with pytest.raises(ValueError, match="预热期"):
        accounts.create(AccountSpec(name="太早", strategy="script", start_date=SESSIONS[2]))  # two sessions behind it
    assert accounts.create(AccountSpec(name="刚好", strategy="script", start_date=SESSIONS[3]))


def test_a_misspelt_strategy_parameter_is_refused_when_the_account_is_created(migrated_database) -> None:
    market = synced(migrated_database, {"13010": ["1000"] * 10})
    accounts = Accounts(migrated_database, market, build_strategy=build_strategy)

    with pytest.raises(ValueError, match="rsi_oversld"):
        accounts.create(AccountSpec(name="错", strategy="trend_pullback_v1", start_date=SESSIONS[5],
                                    strategy_params={"rsi_oversld": 25}))


def test_the_report_gives_the_daily_nav_the_figures_the_holdings_and_tomorrows_orders(migrated_database) -> None:
    """Worked by hand (initial 10,000,000; slippage 0.1% a side):
    S2 buy 900 × 13010 at 1,001 → cash 9,099,100, NAV 9,999,100 (close 1,000)
    S3 NAV 9,099,100 + 900 × 1,100 = 10,089,100
    S4 buy 1,100 × 13030 at 800.8 → cash 8,218,220; NAV + 900 × 1,200 + 1,100 × 800 = 10,178,220
    S5 sell 900 × 13010 at 1,148.85 → cash 9,252,185; NAV + 1,100 × 820 = 10,154,185
    and at S5's close 13020 is held: 10,154,185 × 9.5% ÷ 500 → 1,900 shares tomorrow."""
    market = synced(migrated_database, {
        "13010": ["1000"] * 3 + ["1100", "1200"] + ["1150"] * 5,
        "13020": ["500"] * 10,
        "13030": ["800"] * 5 + ["820"] * 5,
    })
    plan = {SESSIONS[1]: {"13010": Disposition.HOLD}, SESSIONS[3]: {"13030": Disposition.HOLD},
            SESSIONS[4]: {"13010": Disposition.EXIT}, SESSIONS[5]: {"13020": Disposition.HOLD}}
    accounts = Accounts(migrated_database, market, build_strategy=lambda name, params: Script(plan))
    account = accounts.create(AccountSpec(name="报", strategy="script", start_date=SESSIONS[1]))
    accounts.advance(account, through=SESSIONS[5])

    report = accounts.report(account)

    assert list(report.nav.index) == SESSIONS[1:6]
    assert list(report.nav) == [Decimal("10000000"), Decimal("9999100"), Decimal("10089100"),
                                Decimal("10178220"), Decimal("10154185")]
    assert report.figures.total_return == pytest.approx(0.0154185)
    assert report.figures.win_rate == 1.0 and report.figures.average_holding_sessions == 3.0
    assert [(h.code, h.quantity, h.opened_on, h.cost, h.close, h.value) for h in report.holdings] == [
        ("13030", 1100, SESSIONS[4], Decimal("880880.000"), Decimal("820"), Decimal("902000")),
    ]
    assert [(o.kind, o.code, o.execution_date, o.planned_quantity) for o in report.pending] == [
        ("buy", "13020", SESSIONS[6], 1900),
    ]


def test_listing_stopping_and_deleting(migrated_database) -> None:
    market = synced(migrated_database, {"13010": ["1000"] * 5 + ["1100"] * 5})
    plan = {SESSIONS[1]: {"13010": Disposition.HOLD}}
    accounts = Accounts(migrated_database, market, build_strategy=lambda name, params: Script(plan))
    kept = accounts.create(AccountSpec(name="留", strategy="script", start_date=SESSIONS[1]))
    stopped = accounts.create(AccountSpec(name="停", strategy="script", start_date=SESSIONS[1]))
    gone = accounts.create(AccountSpec(name="删", strategy="script", start_date=SESSIONS[1]))
    for account in (kept, stopped, gone):
        accounts.advance(account, through=SESSIONS[6])

    accounts.stop(stopped)
    accounts.delete(gone)

    listed = accounts.list()
    assert [(a.id, a.name, a.status, a.advanced_through) for a in listed] == [
        (kept, "留", "active", SESSIONS[6]), (stopped, "停", "stopped", SESSIONS[6]),
    ]
    assert listed[0].total_return == pytest.approx(accounts.report(kept).figures.total_return)
    assert [a.id for a in accounts.list(active_only=True)] == [kept]
    with pytest.raises(LookupError):
        accounts.report(gone)


def test_catching_up_with_the_latest_session_marks_the_data_it_was_backtested_on(migrated_database) -> None:
    """ADR-0001: bars are overwritten when re-fetched, so the account notes
    how much data there was when its backtest caught up."""
    market = synced(migrated_database, {"13010": ["1000"] * 10})
    accounts = Accounts(migrated_database, market, build_strategy=lambda name, params: Script({}))
    account = accounts.create(AccountSpec(name="标", strategy="script", start_date=SESSIONS[1]))

    accounts.advance(account, through=SESSIONS[5])
    assert accounts.report(account).account["backtest_data_mark"] is None

    accounts.advance(account)
    assert accounts.report(account).account["backtest_data_mark"] == {
        "latest_date": SESSIONS[-1].isoformat(), "bar_rows": 20,  # 10 × 13010 + 10 × TOPIX
    }


def counting_reads(market):
    """How many times the report reads market data — its costly part."""
    reads = []
    real = market.read
    market.read = lambda *args, **kwargs: reads.append(args) or real(*args, **kwargs)
    return reads


def test_a_report_is_worked_out_once_until_the_account_changes(migrated_database) -> None:
    """The account page asks for the detail, the NAV and the orders at once;
    the report behind them is worked out once, and again only after the
    account moves on."""
    market = synced(migrated_database, {"13010": ["1000"] * 5 + ["1100"] * 5})
    accounts = Accounts(migrated_database, market,
                        build_strategy=lambda name, params: Script({SESSIONS[1]: {"13010": Disposition.HOLD}}))
    account = accounts.create(AccountSpec(name="缓", strategy="script", start_date=SESSIONS[1]))
    accounts.advance(account, through=SESSIONS[5])
    reads = counting_reads(market)

    first = accounts.report(account)
    assert accounts.report(account) is first and len(reads) == 1

    accounts.advance(account, through=SESSIONS[8])
    moved_on = accounts.report(account)
    assert moved_on.nav.index[-1] == SESSIONS[8]


def test_reports_asked_for_together_are_worked_out_once(migrated_database) -> None:
    market = synced(migrated_database, {"13010": ["1000"] * 5 + ["1100"] * 5})
    accounts = Accounts(migrated_database, market,
                        build_strategy=lambda name, params: Script({SESSIONS[1]: {"13010": Disposition.HOLD}}))
    account = accounts.create(AccountSpec(name="并", strategy="script", start_date=SESSIONS[1]))
    accounts.advance(account, through=SESSIONS[8])
    reads = counting_reads(market)

    with ThreadPoolExecutor(max_workers=3) as pool:
        reports = list(pool.map(lambda _: accounts.report(account), range(3)))

    assert len(reads) == 1 and all(report is reports[0] for report in reports)
