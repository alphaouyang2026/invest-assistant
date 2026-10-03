"""TOPIX ETF strategies on real data, through the HTTP API on a copy of the
database — never the real one (.scratch/topix-etf-strategies, tickets 01–03).

Run from backend:
    uv run python scripts/demo_topix_accounts.py ../var/invest.db /root/topix-acceptance/01 [strategy ...]

Copies the database with SQLite's backup API into the target directory
(unless a copy is already there) and migrates the copy. Then, for each
strategy (default: topix_buy_and_hold_v1), creates an account from
2022-10-17 with the portfolio rules /api/strategies suggests, advances it
to the latest session, and prints JSON lines: its fills with their reasons,
the switches in and out of 1306 and the share of sessions it held 1306,
its holdings and figures; the NAV either side of 1306's 10-for-1 split;
whether it held 1306 on each distribution day, with that day's return
beside TOPIX's; whether it held 1306 at every close of the year from
2025-09-30 to 2026-09-29, and its return over that year; and the signal
page's candidates. With topix_ma_v1 or topix_momentum_v1, also the
switches TOPIX alone calls for — the spec's read-only count, taken from the
lines 1306's security page draws (the TOPIX close and its average; the past
return, judged on the first session of each month) — to set beside the
account's. Last, a side-by-side summary of the accounts, and 1306's own
price return against TOPIX over each year from the start. The copy is kept
for a page session against it.

    uv run python scripts/demo_topix_accounts.py ../var/invest.db /root/topix-acceptance/03 \
        topix_buy_and_hold_v1 topix_ma_v1 topix_momentum_v1
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.migrate import upgrade_to_head

# The first start all three TOPIX ETF strategies can warm up for: the warm-up
# check counts TOPIX bars from the first calendar day (2021-10-04), and
# momentum's 253 are there from 2022-10-17. (Counting from TOPIX's first bar,
# 2021-09-24, the spec put it at 2022-10-06.)
START = "2022-10-17"
TOPIX_ETF = "13060"
SPLIT = ("2026-03-27", "2026-03-30")  # the session before 1306's 10-for-1 split, and its ex-date
DISTRIBUTION_DAYS = ["2023-07-07", "2024-07-09", "2025-07-09", "2026-07-09"]  # 1306 goes ex-distribution
# Every session of it was an up-trend session: the spec expects the moving
# average account to hold all year, no different from the control group.
UP_YEAR = ("2025-09-30", "2026-09-29")


def show(value) -> None:
    print(json.dumps(value, ensure_ascii=False), flush=True)


def copy_of(source: Path, directory: Path) -> Path:
    target = directory / "invest.db"
    if not target.exists():
        directory.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as original, sqlite3.connect(target) as copy:
            original.backup(copy)
    return target


def main() -> None:
    source, directory = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    strategies = sys.argv[3:] or ["topix_buy_and_hold_v1"]
    target = copy_of(source, directory)
    assert target != source, "the demo never touches the real database"
    os.environ["DATABASE_PATH"] = str(target)
    upgrade_to_head()
    app = create_app(Settings(_env_file=None))

    def idle() -> None:
        while not app.state.jobs.wait_until_idle(timeout=1):
            pass

    with TestClient(app) as client:
        latest = client.get("/api/data/status").json()["latest_date"]
        show({"isolated_database": str(target), "latest_session": latest})
        listed = {s["name"]: s for s in client.get("/api/strategies").json()}
        accounts = []
        for name in strategies:
            accounts.append(demo(client, idle, listed[name]))
            show({"account": name, **accounts[-1]})
        if "topix_ma_v1" in strategies:
            show({"topix_alone": topix_alone(client, latest, listed["topix_ma_v1"]["defaults"]["band"])})
        if "topix_momentum_v1" in strategies:
            show({"topix_alone_momentum": momentum_alone(client, latest)})
        show({"side_by_side": [{"account": name, "trades": account["trades"], "held_share": account["held_share"],
                                **{key: account["figures"][key] for key in (
                                    "total_return", "annualised_return", "max_drawdown", "sharpe",
                                    "excess_annualised_return")}, "topix_return": account["topix_return"],
                                "held_on_distribution_days": {day: held["shares"] > 0 for day, held in
                                                              account["distribution_days"].items()},
                                "up_year": account["up_year"]}
                               for name, account in zip(strategies, accounts)]})
        show({"etf_against_topix": yearly(client, latest, accounts[0]["id"])})


def demo(client: TestClient, idle, strategy: dict) -> dict:
    created = client.post("/api/accounts", json={
        "name": f"{strategy['name']} {START}", "strategy": strategy["name"], "start_date": START,
        **strategy["suggested_rules"]})
    assert created.status_code == 201, created.text
    account = created.json()["id"]
    idle()
    detail = client.get(f"/api/accounts/{account}").json()
    assert detail["advanced_through"], f"account {account} was not advanced: {created.json()}"
    nav = {point["date"]: point for point in client.get(f"/api/accounts/{account}/nav").json()}
    orders = client.get(f"/api/accounts/{account}/orders", params={"page_size": 200}).json()["orders"][::-1]
    fills = [o for o in orders if o["status"] == "filled"]
    days = sorted(nav)

    def held_on(day: str) -> int:
        """1306 shares held at that day's close, from the fills and events up to it
        (a split adjustment's quantity is the shares it adds)."""
        return sum(o["filled_quantity"] * (-1 if o["kind"] in ("sell", "delisting_settlement") else 1)
                   for o in fills if o["code"] == TOPIX_ETF and o["execution_date"] <= day)

    def day_return(day: str, curve: str) -> float:
        before = days[days.index(day) - 1]
        return round(nav[day][curve] / nav[before][curve] - 1, 4)

    figures = {key: None if value is None else round(value, 4) for key, value in detail["figures"].items()}
    return {
        "id": account, "rules": detail["rules"], "start": detail["start_date"],
        "advanced_through": detail["advanced_through"],
        "fills": [{key: o[key] for key in ("kind", "code", "signal_date", "execution_date", "planned_quantity",
                                          "filled_quantity", "fill_price", "cash_delta")}
                  | {"reasons": o["reason"].get("reason_codes", [])} for o in fills],
        "trades": sum(o["kind"] in ("buy", "sell") for o in fills),
        "held_share": round(sum(held_on(day) > 0 for day in days) / len(days), 4),
        "holdings": [{key: h[key] for key in ("code", "quantity", "opened_on", "close", "value")}
                     for h in detail["holdings"]],
        "pending": [(o["kind"], o["code"], o["execution_date"]) for o in detail["pending"]],
        "split": {day: {"nav": nav[day]["nav"], "shares": held_on(day), "account": day_return(day, "nav_curve"),
                        "topix": day_return(day, "topix_curve")} for day in SPLIT if day in nav and day != days[0]},
        "distribution_days": {day: {"shares": held_on(day), "account": day_return(day, "nav_curve"),
                                    "topix": day_return(day, "topix_curve")} for day in DISTRIBUTION_DAYS if day in nav},
        "up_year": {"held_every_close": all(held_on(day) > 0 for day in days if UP_YEAR[0] <= day <= UP_YEAR[1]),
                    "return": round(nav[UP_YEAR[1]]["nav_curve"] / nav[UP_YEAR[0]]["nav_curve"] - 1, 4),
                    "topix": round(nav[UP_YEAR[1]]["topix_curve"] / nav[UP_YEAR[0]]["topix_curve"] - 1, 4)}
                   if UP_YEAR[1] in nav else None,
        "figures": figures,
        "topix_return": round(nav[days[-1]]["topix_curve"] - 1, 4),
        "signals": client.get("/api/signals", params={"strategy": strategy["name"]}).json(),
    }


def topix_alone(client: TestClient, latest: str, band: float) -> dict:
    """The moving average rule run on TOPIX's close and average alone, as
    1306's security page draws them from the start: the day each switch is
    called (an account fills it at the next open), the number of switches,
    and the share of sessions held. 1306's own bars play no part."""
    bars = client.get(f"/api/instruments/{TOPIX_ETF}/bars",
                      params={"strategy": "topix_ma_v1", "from": START, "to": latest}).json()
    closes, averages = ({point["date"]: point["value"] for point in bars["lines"][name]} for name in ("topix_close", "topix_ma"))
    held, switches, sessions_held = False, [], 0
    for day in sorted(closes):
        close, average = closes[day], averages.get(day)
        if close is None or average is None:
            continue
        if not held and close > average * (1 + band):
            held = True
            switches.append((day, "buy"))
        elif held and close < average * (1 - band):
            held = False
            switches.append((day, "sell"))
        sessions_held += held
    return {"switches": len(switches), "called_on": switches, "held_share": round(sessions_held / len(closes), 4)}


def momentum_alone(client: TestClient, latest: str) -> dict:
    """The momentum rule run on the past return alone, as 1306's security
    page draws it from the start: judged on each session that opens a month
    (the previous session falls in an earlier one), a session without a
    value not judged and its month left as it is. 1306's own bars play no
    part beyond giving the sessions."""
    bars = client.get(f"/api/instruments/{TOPIX_ETF}/bars",
                      params={"strategy": "topix_momentum_v1", "from": START, "to": latest}).json()
    past = {point["date"]: point["value"] for point in bars["lines"]["past_return"]}
    days = sorted(past)
    held, switches, sessions_held, check_days = False, [], 0, []
    for n, day in enumerate(days):
        if n > 0 and days[n - 1][:7] != day[:7]:
            check_days.append(day)
            value = past[day]
            if value is not None and not held and value > 0:
                held = True
                switches.append((day, "buy", round(value, 4)))
            elif value is not None and held and value < 0:
                held = False
                switches.append((day, "sell", round(value, 4)))
        sessions_held += held
    turns = [day for n, day in enumerate(days[1:], 1)
             if past[day] is not None and past[days[n - 1]] is not None and (past[day] > 0) != (past[days[n - 1]] > 0)]
    return {"switches": len(switches), "called_on": switches, "held_share": round(sessions_held / len(days), 4),
            "check_days": len(check_days), "entries_on_check_days_only": set(bars["entries"]) <= set(check_days),
            "past_return_turns_daily": len(turns),
            "past_return_on_check_days": {day: None if past[day] is None else round(past[day], 4) for day in check_days}}


def yearly(client: TestClient, latest: str, account: int) -> list[dict]:
    """1306's research price (comparable across the split) against TOPIX's
    close — taken from `account`'s NAV page — from the start to each
    anniversary and then to the latest session."""
    bars = client.get(f"/api/instruments/{TOPIX_ETF}/bars",
                      params={"strategy": "topix_buy_and_hold_v1", "from": START, "to": latest}).json()["bars"]
    etf = {bar["date"]: bar["close"] for bar in bars if bar["close"] is not None}
    topix = {point["date"]: point["topix_curve"] for point in client.get(f"/api/accounts/{account}/nav").json()}
    days = sorted(set(etf) & set(topix))
    marks = [day for year in range(2023, 2027) for day in [next((d for d in days if d >= f"{year}{START[4:]}"), None)]
             if day] + [days[-1]]
    rows, previous = [], days[0]
    for day in dict.fromkeys(marks):
        mine, theirs = etf[day] / etf[previous] - 1, topix[day] / topix[previous] - 1
        rows.append({"from": previous, "to": day, "etf": round(mine, 4), "topix": round(theirs, 4),
                     "difference": round(mine - theirs, 4)})
        previous = day
    return rows


if __name__ == "__main__":
    main()
