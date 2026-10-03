"""What the TOPIX ETF strategies' rule tests share: 1306 beside TOPIX, its
reference series, on synthetic bars — no database."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from app.market_data import TOPIX
from app.strategies import Holding, Signal, Strategy
from tests.frames import frame_of

ETF = "13060"  # 1306


def etf_signal(strategy: Strategy, topix: Sequence[float], days: Sequence[date], *, held: bool = False) -> Signal:
    """1306's one signal on the last of `days`, `topix` being TOPIX's closes
    on them and 1306 flat at 2,000; held from the first day when `held`."""
    frame = frame_of({TOPIX: topix, ETF: [2000.0] * len(topix)}, days)
    [signal] = strategy.evaluate(frame, days[-1], [Holding(ETF, 4700, days[0])] if held else [])
    return signal


def outcome(signal: Signal) -> tuple:
    """What a signal says: its disposition and its reasons."""
    return signal.disposition, signal.reason_codes
