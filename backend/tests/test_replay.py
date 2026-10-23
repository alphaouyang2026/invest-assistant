"""`replay_range` (spec §7.5) — a whole range on an isolated ledger, one
`replay_day` a session — read back a session at a time, and the ADV20 a
buy may be capped at: the universe's own turnover average (spec §6.1),
read from the replay's prices."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.accounts import Accounts, AccountSpec, Costs, PortfolioRules
from app.accounts import tables
from app.accounts.accounts import Prices, trading_terms
from app.accounts.ledger import Ledger, Position
from app.accounts.records import Record
from app.accounts.replay import NavPoint, Replay, replay_range
from app.market_data import EXEC_CLOSE, TOPIX, MarketData
from app.strategies import Disposition
from tests.account_market import SESSIONS, Script, synced
from tests.fakes import FakeJQuants, bar, listed

PLAN = {SESSIONS[1]: {"13010": Disposition.HOLD}, SESSIONS[4]: {"13010": Disposition.EXIT},
        SESSIONS[5]: {"13020": Disposition.HOLD}}
PRICES = {"13010": ["1000"] * 3 + ["1100", "1200"] + ["1150"] * 5, "13020": ["500"] * 10}


def replayed(market: MarketData, script: Script, rules: PortfolioRules, days: list[date], **kwargs):
    """What a research run reads for `days`, replayed."""
    calendar = market.calendar()
    universes = market.universe(days[0], days[-1], rule=script.universe_rule)
    codes = {code for listed_codes in universes.values() for code in listed_codes}
    prices = Prices(market.read(sorted(codes), SESSIONS[0], days[-1]))
    topix = market.read([TOPIX], days[0], days[-1]).wide(EXEC_CLOSE)[TOPIX]
    return replay_range(prices, script, universes, days, calendar, rules, Costs(), Decimal("10000000"), topix,
                        **kwargs)


def test_a_replay_keeps_the_paper_accounts_books_and_notes_each_closes_cash(migrated_database) -> None:
    """13010 bought on S2, sold on S5; 13020 bought on S6."""
    market = synced(migrated_database, PRICES)
    accounts = Accounts(migrated_database, market, build_strategy=lambda name, params: Script(PLAN))
    account = accounts.create(AccountSpec("对照", "script", SESSIONS[1]))
    accounts.advance(account, through=SESSIONS[6])
    report = accounts.report(account)
    told = []

    replay = replayed(market, Script(PLAN), PortfolioRules(), SESSIONS[1:7],
                      on_session=lambda done, day: told.append((done, day)))

    assert told == list(enumerate(SESSIONS[1:7], 1))
    assert [(p.day, p.nav) for p in replay.points] == list(report.nav.items())
    books = Ledger(Decimal("10000000"), report.orders).by_session(SESSIONS[1:7])
    assert [p.cash for p in replay.points] == [cash for _, cash, _ in books]
    assert replay.points[2].cash == Decimal("10000000") - 900 * Decimal("1001")
    assert [(r.id, r.kind, r.code, r.status, r.filled_quantity) for r in replay.ledger.records] == [
        (n, r.kind, r.code, r.status, r.filled_quantity) for n, r in enumerate(report.orders, 1)]
    assert replay.points[0].as_json() == {"date": SESSIONS[1].isoformat(), "nav": 10_000_000, "nav_curve": 1,
                                          "topix_curve": 1, "drawdown": 0}


def test_a_cap_is_stored_only_when_set_and_cuts_the_buy_through_the_whole_replay(migrated_database) -> None:
    """¥10bn a day from S0: ADV20 on S1 is 2 × 10bn ÷ 20 = ¥1bn. A 0.05% cap
    is ¥500,000 → 500 shares at ¥1,000 instead of 900."""
    market = synced(migrated_database, PRICES)
    accounts = Accounts(migrated_database, market, build_strategy=lambda name, params: Script(PLAN))
    plain = accounts.create(AccountSpec("无上限", "script", SESSIONS[1]))
    capped_rules = PortfolioRules(max_adv20_fraction=Decimal("0.0005"))
    capped = accounts.create(AccountSpec("有上限", "script", SESSIONS[1], rules=capped_rules))
    with migrated_database.connect() as con:
        stored = dict(con.execute(select(tables.paper_accounts.c.id, tables.paper_accounts.c.portfolio_rules)).all())
    assert "max_adv20_fraction" not in stored[plain]
    assert trading_terms({"portfolio_rules": stored[plain], "costs": {}})[0].max_adv20_fraction is None
    assert trading_terms({"portfolio_rules": stored[capped], "costs": {}})[0] == capped_rules

    accounts.advance(capped, through=SESSIONS[3])
    accounts.advance(plain, through=SESSIONS[3])
    replay = replayed(market, Script(PLAN), capped_rules, SESSIONS[1:4])

    buy = accounts.report(capped).orders[0]
    assert (buy.code, buy.planned_quantity, buy.status, buy.reason["capped"]) == ("13010", 500, "filled", "adv20")
    assert accounts.report(plain).orders[0].planned_quantity == 900
    assert [(r.code, r.planned_quantity, r.reason) for r in replay.ledger.records] == [
        (r.code, r.planned_quantity, r.reason) for r in accounts.report(capped).orders]


def test_each_replayed_day_tells_what_was_planned_what_opened_and_what_the_plan_aims_at() -> None:
    """S0's close plans three buys: A is placed and fills at S1's open, B the
    portfolio rules give up on (it was never placed), C is placed but a
    reverse split at S1's open rounds it to no whole lot. A's split on S2
    doubles the holding; S2 plans A's sale (it fills on S3) and a buy of E
    (it expires on S3); S3 plans a buy of F, left pending."""
    s = SESSIONS
    initial = Decimal("1000000")
    records = [
        Record(id=1, kind="buy", code="A", signal_date=s[0], execution_date=s[1], planned_quantity=100,
               status="filled", filled_quantity=100, fill_price=Decimal("1000"), cash_delta=Decimal("-100000")),
        Record(id=2, kind="buy", code="B", signal_date=s[0], execution_date=s[1], status="skipped",
               outcome_reason="lot_unaffordable"),
        Record(id=3, kind="buy", code="C", signal_date=s[0], execution_date=s[1], status="skipped",
               outcome_reason="split_rounding"),
        Record(id=4, kind="split_adjustment", code="A", signal_date=s[2], execution_date=s[2], status="filled",
               filled_quantity=100),
        Record(id=5, kind="sell", code="A", signal_date=s[2], execution_date=s[3], planned_quantity=200,
               status="filled", filled_quantity=200, fill_price=Decimal("600"), cash_delta=Decimal("120000")),
        Record(id=6, kind="buy", code="E", signal_date=s[2], execution_date=s[3], planned_quantity=300,
               status="expired", outcome_reason="limit_up_open"),
        Record(id=7, kind="buy", code="F", signal_date=s[3], execution_date=s[4], planned_quantity=400),
    ]
    cash = [Decimal("1000000"), Decimal("900000"), Decimal("900000"), Decimal("1020000")]
    points = [NavPoint(day, Decimal("1000000"), money, 1.0, 1.0, 0.0) for day, money in zip(s[:4], cash)]

    days = Replay(Ledger(initial, records), points, []).days()

    assert [d.day for d in days] == s[:4] and [d.cash for d in days] == cash
    assert [[r.id for r in d.planned] for d in days] == [[1, 2, 3], [], [5, 6], [7]]
    assert [[r.id for r in d.opened] for d in days] == [[], [1, 3], [4], [5, 6]]
    assert [[r.id for r in d.given_up()] for d in days] == [[2], [], [], []]
    assert [d.target() for d in days] == [{"A": 100}, {"A": 100}, {"E": 300}, {"F": 400}]
    assert days[2].positions == {"A": Position("A", 200, s[1], Decimal("100000"))}


UNIVERSE_SESSIONS = [date(2026, 8, 3) + timedelta(days=n) for n in range(25)]


def test_adv20_is_the_universes_turnover_average(migrated_database) -> None:
    """The data of test_universe's 20-session test: a missing day and an
    untradable one count as nothing, days before the window not at all. The
    codes at ¥500M or more are the universe."""
    day, window = UNIVERSE_SESSIONS[-1], UNIVERSE_SESSIONS[-20:]
    gap_day, halt_day = window[3], window[7]
    yen = lambda amount: Decimal(amount) * 10**8  # noqa: E731

    def bars_for(d):
        bars = [bar("13010", d, turnover=yen(6)), bar("13040", d, turnover=yen(5)),
                bar("13050", d, turnover=yen(5) if d in window else yen(1))]
        if d != gap_day:
            bars.append(bar("13020", d, turnover=yen(5)))
        bars.append(bar("13030", d, close=None if d == halt_day else "100", turnover=yen("5.2")))
        return bars

    client = FakeJQuants(UNIVERSE_SESSIONS, bars={d: bars_for(d) for d in UNIVERSE_SESSIONS},
                         roster=[listed(code) for code in ("13010", "13020", "13030", "13040", "13050")])
    market = MarketData(migrated_database, client, today=lambda: day)
    market.sync()
    codes = ["13010", "13020", "13030", "13040", "13050"]

    adv20 = Prices(market.read(codes, UNIVERSE_SESSIONS[0], day)).adv20(day, codes)

    assert adv20 == {"13010": yen(6), "13020": yen("4.75"), "13030": yen("4.94"), "13040": yen(5),
                     "13050": yen(5)}
    assert sorted(code for code, average in adv20.items() if average >= yen(5)) == market.universe(day)[day]
