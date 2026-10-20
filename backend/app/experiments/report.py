"""A model experiment's report (ticket 06a), apart from the replays it
comes from. Pure — scores, labels, universes and replays in, JSON-ready
dicts out.

- Which out-of-fold scores are kept: the decision days' alone, each with
  the fold and the artifact that scored it.
- Prediction diagnostics, kept apart from the portfolio's: on each
  decision day the rank IC of the scores against the labels, and the
  coverage — codes scored over the day's universe.
- The benchmarks besides TOPIX: the eligible universe held equally weighted,
  each decision period's label averaged over it — no costs.
- Each replay's figures: spec §7.4's, the research report's, and the
  replay metrics (fill rate, cash held, turnover, orders against ADV20,
  returns by fold and by year).
- The evidence status: 06a only ever says `exploratory` or
  `insufficient_evidence`, with every reason.
"""
from __future__ import annotations

import statistics as stats
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd

from app.accounts.records import BUY, FILLED, SELL
from app.accounts.replay import Replay
from app.accounts.replay_metrics import (
    adv20_usage, annual_turnover, average_cash_share, fill_rate, period_returns, yearly_returns,
)
from app.accounts.statistics import statistics
from app.experiments.features import AS_OF
from app.experiments.folds import Fold
from app.market_data.frame import CODE
from app.strategies import ScoreTable

EXPLORATORY, INSUFFICIENT = "exploratory", "insufficient_evidence"
POOL_BASIS = ("每个决策日当天股票池里有标签的证券等权：研究价格 t+1 开盘到 t+6 开盘的收益取平均，逐期连乘；"
              "不扣费用、不含分红，不受整手、现金和成交规则约束；标签越过测试终点的决策日不计")
TOPIX_BASIS = "TOPIX 价格指数，测试首日收盘到末日收盘，不含分红"


def kept_scores(scores: pd.DataFrame, decision_days: Sequence[date]) -> dict[date, dict[str, Any]]:
    """Out-of-fold scores (`SCORE_COLUMNS`) on the decision days alone:
    day → {"fold", "artifact_hash", "scores": {code: score}}. A decision day
    no fold scored (its fold failed) is not there."""
    wanted = scores[scores[AS_OF].isin(set(decision_days))]
    kept = {}
    for day, rows in wanted.groupby(AS_OF, sort=True):
        kept[day] = {"fold": int(rows["fold"].iloc[0]), "artifact_hash": str(rows["artifact_hash"].iloc[0]),
                     "scores": {str(code): float(score) for code, score in zip(rows[CODE], rows["score"])}}
    return kept


def score_table(kept: Mapping[date, Mapping[str, Any]], decision_days: Sequence[date]) -> ScoreTable:
    return ScoreTable(frozenset(decision_days), {day: entry["scores"] for day, entry in kept.items()})


def labels_by_day(labels: pd.Series) -> dict[date, pd.Series]:
    """Labels indexed (as_of, code) as day → code → label."""
    return {day: rows.droplevel(AS_OF) for day, rows in labels.groupby(level=AS_OF, sort=True)}


def rank_ic(scores: Mapping[str, float], labels: pd.Series | None) -> tuple[float | None, int]:
    """Spearman's correlation of the scores with the labels over the codes
    with both, and how many those are; None under three, or when either
    side does not vary."""
    if labels is None or not scores:
        return None, 0
    both = pd.DataFrame({"score": pd.Series(scores, dtype=float), "label": labels}).dropna()
    if len(both) < 3:
        return None, len(both)
    ranked = both.rank()
    if ranked["score"].nunique() < 2 or ranked["label"].nunique() < 2:
        return None, len(both)
    return float(ranked["score"].corr(ranked["label"])), len(both)


def prediction_diagnostics(kept: Mapping[date, Mapping[str, Any]], labels: Mapping[date, pd.Series],
                           universes: Mapping[date, Sequence[str]], decision_days: Sequence[date],
                           folds: Sequence[Fold]) -> dict:
    """Each decision day's coverage and rank IC, summed up over all of
    them and fold by fold. A day the model has no scores counts as
    coverage 0 and has no IC."""
    days = []
    for day in decision_days:
        pool = universes.get(day, [])
        entry = kept.get(day)
        scored = entry["scores"] if entry else {}
        ic, pairs = rank_ic(scored, labels.get(day))
        days.append({"date": day.isoformat(), "fold": entry["fold"] if entry else _fold_of(day, folds),
                     "available": entry is not None, "universe": len(pool), "scored": len(scored),
                     "coverage": len(scored) / len(pool) if pool else None, "labelled": pairs, "rank_ic": ic})
    by_fold = [{"fold": fold.number, **_summary([d for d in days if d["fold"] == fold.number])} for fold in folds]
    return {**_summary(days), "days": days, "folds": by_fold}


def eligible_equal_weight(labels: Mapping[date, pd.Series], universes: Mapping[date, Sequence[str]],
                          decision_days: Sequence[date]) -> dict:
    """The eligible universe held equally weighted from each decision day's
    next open to the open five sessions later: its labels averaged, the
    periods chained. No costs; days without labels are left out."""
    periods, growth = [], 1.0
    for day in decision_days:
        known = labels.get(day)
        known = None if known is None else known[known.index.isin(set(universes.get(day, [])))]
        if known is None or known.empty:
            continue
        average = float(known.mean())
        growth *= 1 + average
        periods.append({"date": day.isoformat(), "codes": int(len(known)), "mean_return": average})
    return {"basis": POOL_BASIS, "periods": periods, "total_return": growth - 1 if periods else None}


def replay_figures(replay: Replay, initial: Decimal, folds: Sequence[Fold], *, cap: Decimal | None,
                   adv20: Mapping[tuple[date, str], Decimal], closes: Mapping[str, Decimal]) -> dict:
    """A replay's report: its NAV (with the cash) at each close, its end
    holdings and pending orders, and every figure. `adv20` holds each filled
    order's ADV20 on its signal day, `closes` the last day's closes of the
    holdings."""
    ledger, points = replay.ledger, replay.points
    records = ledger.records
    nav = pd.Series([float(p.nav) for p in points], index=[p.day for p in points])
    topix = pd.Series([p.topix_curve for p in points], index=nav.index)
    amounts = {kind: sum((r.fill_price * r.filled_quantity for r in records if r.kind == kind and r.status == FILLED),
                         Decimal(0)) for kind in (BUY, SELL)}
    figures = statistics(nav, topix, ledger.closed, bought=amounts[BUY], sold=amounts[SELL])
    last = points[-1]
    unrealised = sum((p.quantity * closes[p.code] - p.cost for p in ledger.positions.values()), Decimal(0))
    total, baseline = last.nav_curve - 1, last.topix_curve - 1
    usage = adv20_usage(records, adv20, cap=cap)
    by_fold = period_returns(points, [(fold.test_from, fold.test_to) for fold in folds])
    metrics = {
        "sessions": len(points),
        "total_return": total, "topix_return": baseline, "excess_return": total - baseline,
        "annualised_return": figures.annualised_return, "excess_annualised_return": figures.excess_annualised_return,
        "max_drawdown": max(p.drawdown for p in points), "sharpe": figures.sharpe,
        "win_rate": figures.win_rate, "closed_positions": figures.closed_positions,
        "average_holding_sessions": figures.average_holding_sessions,
        "annual_turnover": annual_turnover(points, records),
        "trades": sum(r.status == FILLED and r.kind in (BUY, SELL) for r in records),
        "fees": float(sum((r.fees for r in records), Decimal(0))),
        "cash": float(ledger.cash), "average_cash_share": average_cash_share(points),
        "realised_pnl": float(last.nav - initial - unrealised), "unrealised_pnl": float(unrealised),
        "fill_rate": asdict(fill_rate(records)),
        "adv20": {**asdict(usage), "cap": None if cap is None else float(cap)},
    }
    return {
        "nav": [{**p.as_json(), "cash": float(p.cash)} for p in points],
        "holdings": [{"code": p.code, "quantity": p.quantity, "opened_on": p.opened_on.isoformat(),
                      "cost": float(p.cost), "close": float(closes[p.code]),
                      "value": float(p.quantity * closes[p.code])}
                     for p in sorted(ledger.positions.values(), key=lambda p: p.code)],
        "warnings": sorted(set(replay.warnings)),
        "metrics": metrics,
        "folds": [None if r is None else {"fold": fold.number, **_period(r)} for fold, r in zip(folds, by_fold)],
        "years": [{"year": year, **_period(r)} for year, r in yearly_returns(points).items() if r is not None],
    }


def evidence(*, folds: Sequence[Fold], viewed_through: date | None, failed: Mapping[str, Sequence[int]],
             coverage: float | None, min_coverage: float, ic_days: int, trades: int, min_trades: int) -> dict:
    """06a's verdict: `insufficient_evidence` when a fold failed, coverage or
    trades fall short or nothing could be diagnosed, else `exploratory` —
    never passed. `failed` is each model's (by its label) failed folds.
    Every reason found is listed, the history already seen first."""
    reasons = []
    seen = [fold.number for fold in folds if viewed_through is not None and fold.test_from <= viewed_through]
    if seen and len(seen) == len(folds):
        reasons.append(_reason("history_viewed", f"全部 {len(folds)} 折的测试段在登记前已被查看过"
                               f"（截至 {viewed_through}），重新切分也不是盲测，结果只能算探索性"))
    elif seen:
        reasons.append(_reason("history_partly_viewed", f"第 {_numbers(seen)} 折的测试段在登记前已被查看过"
                               f"（截至 {viewed_through}），这几折只能算探索性"))
    insufficient = []
    for label, numbers in failed.items():
        if numbers:
            insufficient.append(_reason("fold_failed", f"{label} 第 {_numbers(numbers)} 折训练或打分失败："
                                        "这些折的决策日没有分数，不开新仓"))
    if coverage is None or coverage < min_coverage:
        shown = "无" if coverage is None else f"{coverage:.1%}"
        insufficient.append(_reason("coverage_below_minimum", f"决策日平均覆盖率 {shown}，低于最低要求 {min_coverage:.1%}"))
    if ic_days == 0:
        insufficient.append(_reason("no_prediction_diagnostics", "没有标签已知的决策日，算不出 Rank IC"))
    if trades == 0:
        insufficient.append(_reason("zero_trades", "主模型基础成本回放零成交"))
    elif trades < min_trades:
        insufficient.append(_reason("too_few_trades", f"主模型基础成本回放只有 {trades} 笔成交，少于最低要求 {min_trades} 笔"))
    reasons += insufficient
    if not reasons:
        reasons.append(_reason("framework_only", "06a 只验证评测框架，结论最多是探索性，不出「通过」"))
    return {"status": INSUFFICIENT if insufficient else EXPLORATORY, "reasons": reasons,
            "viewed_folds": seen}


def _summary(days: Sequence[Mapping[str, Any]]) -> dict:
    ics = [d["rank_ic"] for d in days if d["rank_ic"] is not None]
    coverage = [d["coverage"] for d in days if d["coverage"] is not None]
    return {"decision_days": len(days), "unavailable_days": sum(not d["available"] for d in days),
            "ic_days": len(ics), "ic_mean": stats.fmean(ics) if ics else None,
            "ic_std": stats.stdev(ics) if len(ics) > 1 else None,
            "coverage_mean": stats.fmean(coverage) if coverage else None,
            "coverage_min": min(coverage) if coverage else None}


def _fold_of(day: date, folds: Sequence[Fold]) -> int | None:
    return next((fold.number for fold in folds if fold.test_from <= day <= fold.test_to), None)


def _period(found) -> dict:
    return {"start": found.start.isoformat(), "end": found.end.isoformat(), "sessions": found.sessions,
            "net_return": found.net_return, "topix_return": found.topix_return,
            "excess_return": found.net_return - found.topix_return}


def _reason(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def _numbers(numbers: Sequence[int]) -> str:
    return "、".join(str(n) for n in numbers)
