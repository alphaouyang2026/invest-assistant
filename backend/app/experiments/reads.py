"""What a model experiment read, and when (ticket 06a) — a fact of the run,
kept beside its contract, never in it or its hash.

The database keeps no time each row became known: a bar is stored once
per code and date, a later restatement overwriting it (ADR-0001), and the
roster periods likewise. So nothing here claims when a row first arrived.
What is recorded is when this experiment read the data (`observed_at`, the
wall clock), what each kind of data it read covered — the daily bars, the
roster's market segment periods, TOPIX and the trading calendar, with the
research input fingerprint's own row counts where it has them — and the
rule by which each kind is available to a decision (`available_from`).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import pandas as pd

from app.market_data import MarketFrame
from app.market_data.frame import CODE, DATE

NOTE = ("库里没有逐行的历史可得时间：日线和上市名册按证券和日期只存一份，后来的修正会覆盖原值（ADR-0001）。"
        "这里只记录本次实验什么时候读到数据、读到的各类数据覆盖哪些日子和多少行，以及每类数据按什么规则可以用于决策；"
        "它说明这次实验看到了什么，不说明每一行当初是哪天入库的。")
AVAILABLE_FROM = {
    "daily_bars": "t 日的日线在 t 收盘后同步，只用于 t 收盘及以后的决策，最早 t+1 开盘成交；特征和标签用研究价格，"
                  "成交和估值用成交价格",
    "segment_periods": "t 日的上市名册随 t 日的日线一起同步；t 日的股票池只看那天有效的市场分类区间，"
                       "之后名单的变化不改变之前的股票池",
    "topix": "t 日的 TOPIX 收盘在 t 收盘后同步，只用于回放里的基准对比，不进特征",
    "trading_calendar": "交易日历提前同步（含之后的开市日），只用来按开市日数窗口和找下一个开市日，不含价格",
}


def data_read(*, observed_at: str, fingerprint: Mapping[str, Any], frame: MarketFrame,
              universes: Mapping[date, Sequence[str]], topix: pd.Series, calendar: Sequence[date]) -> dict:
    """The record of one read: `fingerprint` the research input fingerprint
    taken over it, `frame` the bars read, `universes` the universe worked
    out each day, `topix` TOPIX's closes over the test span and `calendar`
    the sessions from the read's first through the one after its last."""
    rows = fingerprint["rows"]
    days = sorted(frame.data.index.unique(DATE))
    codes = frame.data.index.unique(CODE)
    listed = sorted(universes)
    closes = topix.dropna()
    return {
        "observed_at": observed_at,
        "note": NOTE,
        "sources": [
            _source("daily_bars", "日线", days, len(frame.data),
                    f"读入 {len(codes):,} 只证券（读取区间里进过股票池的全部）的 {len(frame.data):,} 行；"
                    f"研究输入指纹覆盖同一区间的全部股票和 TOPIX，共 {rows['bars']:,} 行"),
            _source("segment_periods", "上市名册与市场分类区间", listed, rows["segments"],
                    f"按 {len(listed):,} 个开市日各自有效的市场分类区间定股票池；"
                    f"研究输入指纹里与读取区间重叠的区间共 {rows['segments']:,} 段"),
            _source("topix", "TOPIX", sorted(closes.index), len(closes), "测试区间每个开市日的收盘"),
            _source("trading_calendar", "交易日历", list(calendar), rows["calendar"],
                    "读取区间的开市日，加上测试终点之后的下一个开市日（末日订单的执行日）"),
        ],
    }


def _source(kind: str, name: str, days: Sequence[date], rows: int, detail: str) -> dict:
    return {"kind": kind, "name": name, "start": days[0].isoformat() if days else None,
            "end": days[-1].isoformat() if days else None, "rows": int(rows), "detail": detail,
            "available_from": AVAILABLE_FROM[kind]}
