"""A market for the model experiment tests, synced through the fake
J-Quants: 140 weekday sessions from 2026-01-05, a dozen Prime stocks on
seeded random walks, each liquid enough for the universe from the first
session, and TOPIX on a walk of its own. Enough history for the features
(61 bars), a short training window and three ten-session test folds."""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np

from app.market_data import MarketData
from tests.account_market import synced

SESSIONS = [day for day in (date(2026, 1, 5) + timedelta(days=n) for n in range(200)) if day.weekday() < 5][:140]
CODES = [f"{1301 + n}0" for n in range(12)]
TEST_FROM, TEST_TO = SESSIONS[100], SESSIONS[129]


def walks(codes=CODES, sessions=SESSIONS, seed: int = 7) -> dict[str, list[str]]:
    """A close per code per session, to one decimal place."""
    rng = np.random.default_rng(seed)
    out = {}
    for code in codes:
        price, closes = float(rng.uniform(800, 3000)), []
        for _ in sessions:
            price *= math.exp(rng.normal(0, 0.025))
            closes.append(f"{price:.1f}")
        out[code] = closes
    return out


def topix_walk(sessions=SESSIONS, seed: int = 11) -> list[str]:
    rng = np.random.default_rng(seed)
    level, out = 2700.0, []
    for _ in sessions:
        level *= math.exp(rng.normal(0, 0.01))
        out.append(f"{level:.2f}")
    return out


def experiment_market(engine, prices: dict[str, list[str | None]] | None = None, **kwargs) -> MarketData:
    return synced(engine, prices or walks(), topix=topix_walk(), sessions=SESSIONS, **kwargs)


def request(**changes) -> dict:
    """A small contract: three folds of ten test sessions on a 30-session
    rolling window, three positions, decisions every five sessions."""
    return {"test_from": TEST_FROM.isoformat(), "test_to": TEST_TO.isoformat(), "train_sessions": 30,
            "test_sessions": 10, "max_positions": 3, "max_weight": 0.3, "min_trades": 1, **changes}
