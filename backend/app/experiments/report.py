"""A model experiment's report (ticket 06a), apart from the replays it
comes from. Pure — scores, labels, universes and replays in, JSON-ready
dicts out.

- Which out-of-fold scores are kept: the decision days' alone, each with
  the fold and the artifact that scored it.
- Prediction diagnostics, kept apart from the portfolio's: on each
  decision day the rank IC of the scores against the labels, the coverage
  — codes scored over the day's universe — and (06b) how the top N the
  policy can hold did: how many of them were among the day's N best labels
  (the hit rate) and how far their labels beat the scored codes' mean.
- The benchmarks besides TOPIX: the eligible universe held equally weighted,
  each decision period's label averaged over it — no costs.
- Each replay's figures, all the accounts module's: what it ended with (as
  a research run's result), spec §7.4's statistics, and the replay metrics
  (fill rate, cash held, turnover, orders against ADV20, returns by fold
  and by year).
- The evidence status: 06a only ever says `exploratory` or
  `insufficient_evidence`, with every reason — a failed fold, too few
  training samples, too little coverage, too few decision days with labels,
  too few trades, each on its own.
"""
from __future__ import annotations

import statistics as stats
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd

from app.accounts.replay import Replay
from app.accounts.replay_metrics import (
    PeriodReturn, adv20_usage, annual_turnover, average_cash_share, end_state, fill_rate, period_returns,
    replay_statistics, yearly_returns,
)
from app.experiments.features import AS_OF
from app.experiments.folds import Fold
from app.experiments.oof import top_n_excess
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
                           folds: Sequence[Fold], *, top_n: int) -> dict:
    """Each decision day's coverage, rank IC and top-`top_n` hit rate and
    excess, summed up over all of them and fold by fold. A day the model
    has no scores counts as coverage 0 and has none of the rest."""
    days = []
    for day in decision_days:
        pool = universes.get(day, [])
        entry = kept.get(day)
        scored = entry["scores"] if entry else {}
        known = labels.get(day)
        ic, pairs = rank_ic(scored, known)
        days.append({"date": day.isoformat(), "fold": entry["fold"] if entry else _fold_of(day, folds),
                     "available": entry is not None, "universe": len(pool), "scored": len(scored),
                     "coverage": len(scored) / len(pool) if pool else None, "labelled": pairs, "rank_ic": ic,
                     "top_n_hit": top_n_hit(scored, known, top_n),
                     "top_n_excess": None if known is None or not scored else
                     top_n_excess(pd.Series(scored, dtype=float), known, top_n)})
    by_fold = [{"fold": fold.number, **_summary([d for d in days if d["fold"] == fold.number])} for fold in folds]
    return {**_summary(days), "days": days, "folds": by_fold}


def top_n_hit(scores: Mapping[str, float], labels: pd.Series | None, top_n: int) -> float | None:
    """Of the day's `top_n` best-scored codes with a label, the share among
    its `top_n` best labels; None when fewer than `top_n` codes have both.
    Ties go by code, as the portfolio rules break them."""
    if labels is None or not scores or top_n < 1:
        return None
    both = pd.DataFrame({"score": pd.Series(scores, dtype=float), "label": labels}).dropna()
    if len(both) < top_n:
        return None
    both = both.rename_axis("code").reset_index()
    picked = set(both.sort_values(["score", "code"], ascending=[False, True]).head(top_n)["code"])
    best = set(both.sort_values(["label", "code"], ascending=[False, True]).head(top_n)["code"])
    return len(picked & best) / top_n


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


def replay_figures(replay: Replay, folds: Sequence[Fold], *, cap: Decimal | None,
                   adv20: Mapping[tuple[date, str], Decimal], closes: Mapping[str, Decimal]) -> dict:
    """A replay's report: its NAV (with the cash) at each close, what it
    ended with (the accounts module's `end_state`, holdings by code), and
    every figure. `adv20` holds each filled order's ADV20 on its signal day,
    `closes` the last day's closes of the holdings."""
    points, records = replay.points, replay.ledger.records
    ended = end_state(replay, closes)
    figures = replay_statistics(replay)
    usage = adv20_usage(records, adv20, cap=cap)
    by_fold = period_returns(points, [(fold.test_from, fold.test_to) for fold in folds])
    metrics = {
        "sessions": len(points),
        **{key: ended[key] for key in ("total_return", "topix_return", "excess_return")},
        "annualised_return": figures.annualised_return, "excess_annualised_return": figures.excess_annualised_return,
        "max_drawdown": ended["max_drawdown"], "sharpe": figures.sharpe,
        "win_rate": figures.win_rate, "closed_positions": figures.closed_positions,
        "average_holding_sessions": figures.average_holding_sessions,
        "annual_turnover": annual_turnover(points, records),
        **{key: ended[key] for key in ("trades", "fees", "cash")},
        "average_cash_share": average_cash_share(points),
        **{key: ended[key] for key in ("realised_pnl", "unrealised_pnl")},
        "fill_rate": asdict(fill_rate(records)),
        "adv20": {**asdict(usage), "cap": None if cap is None else float(cap)},
    }
    return {
        "nav": [{**p.as_json(), "cash": float(p.cash)} for p in points],
        "holdings": sorted(ended["holdings"], key=lambda holding: holding["code"]),
        "pending": ended["pending"],
        "warnings": ended["warnings"],
        "metrics": metrics,
        "folds": [None if found is None else {"fold": fold.number, **_period_json(found)}
                  for fold, found in zip(folds, by_fold)],
        "years": [{"year": year, **_period_json(found)} for year, found in yearly_returns(points).items()
                  if found is not None],
    }


def evidence(*, folds: Sequence[Fold], viewed_through: date | None, failed: Mapping[str, Sequence[int]],
             samples: Mapping[int, int], min_samples: int, coverage: float | None, min_coverage: float,
             ic_days: int, min_labelled_days: int, trades: int, min_trades: int) -> dict:
    """06a's verdict: `insufficient_evidence` when a fold failed, a fold of
    the model trained on too few samples, coverage falls short, too few
    decision days had labels to judge the scores by, or too few trades
    filled — else `exploratory`, never passed. `failed` is each model's (by
    its label) failed folds, `samples` the model's training samples by fold,
    `ic_days` its decision days with a rank IC (labels known for at least
    three codes it scored). Every reason found is listed, the history
    already seen first."""
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
    short = [number for number, count in sorted(samples.items()) if count < min_samples]
    if short:
        fewest = min(samples[number] for number in short)
        insufficient.append(_reason("too_few_training_samples",
                                    f"主模型第 {_numbers(short)} 折的训练样本少于最低要求 {min_samples:,} 个"
                                    f"（最少的一折 {fewest:,} 个）：训练窗太短，或大半落在还没有股票池的日子"))
    if coverage is None or coverage < min_coverage:
        shown = "无" if coverage is None else f"{coverage:.1%}"
        insufficient.append(_reason("coverage_below_minimum", f"决策日平均覆盖率 {shown}，低于最低要求 {min_coverage:.1%}"))
    if ic_days == 0:
        insufficient.append(_reason("no_prediction_diagnostics", "没有标签已知的决策日，算不出 Rank IC"))
    elif ic_days < min_labelled_days:
        insufficient.append(_reason("too_few_labelled_days",
                                    f"只有 {ic_days} 个决策日的标签已知、算得出 Rank IC，少于最低要求 "
                                    f"{min_labelled_days} 天：测试区间太短，看不出分数排得准不准"))
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
            "coverage_min": min(coverage) if coverage else None,
            "top_n_hit_mean": _mean([d.get("top_n_hit") for d in days]),
            "top_n_excess_mean": _mean([d.get("top_n_excess") for d in days])}


def _mean(values: Sequence[float | None]) -> float | None:
    known = [value for value in values if value is not None]
    return stats.fmean(known) if known else None


def _fold_of(day: date, folds: Sequence[Fold]) -> int | None:
    return next((fold.number for fold in folds if fold.test_from <= day <= fold.test_to), None)


def _period_json(period: PeriodReturn) -> dict:
    """A fold's or a year's return, JSON-ready, with its excess over TOPIX."""
    return {"start": period.start.isoformat(), "end": period.end.isoformat(), "sessions": period.sessions,
            "net_return": period.net_return, "topix_return": period.topix_return,
            "excess_return": period.net_return - period.topix_return}


def _reason(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def _numbers(numbers: Sequence[int]) -> str:
    return "、".join(str(n) for n in numbers)
