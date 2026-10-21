"""A model experiment's frozen contract (ticket 06a): everything it is held
to, fixed when it is registered and never edited — a change is a new
experiment, a retry runs the same contract.

It names the task and its label, where the data come from and when they
are known, the features' version, the universe
rule, the test span and the folds cut from it, the policy (score top-N:
its first decision day, how many sessions apart its decision days are,
how long it may hold), the portfolio rules with the ADV20 cap, the base
costs and the stress scenarios (the base slippage plus a few basis points
a side, fees as they are), the model's trainer with its parameters and
search budget, the rule baselines, the minimums its evidence needs
(coverage, training samples a fold, decision days with labels, trades),
how far history had already been seen when it was registered
(`viewed_through`), and the kinds of instruction its policy gives. 06a's
policy says what to hold and in which order (`disposition`, `priority`); a
contract declaring target weights or a total exposure is refused, not run
without them.

`plan` works out what the contract implies on the trading calendar: the
folds, the replay days, the decision days and how far back to read;
`models` and `replays` the models it scores with and the replays it runs,
under the keys and positions its records are stored by.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.experiments.features import FEATURE_NAMES, FEATURES_V1, HORIZON, label_sessions
from app.experiments.folds import Fold, make_folds
from app.experiments.trainers import Trainer
from app.market_data import UniverseRule
from app.strategies import ScoreTopN

VERSION = "model_experiment_v1"
TASK = {
    "name": "prime_open_to_open_5d_v1",
    "decision": "t 收盘决策，最早 t+1 开盘成交",
    "label": "研究价格开盘 O(t+6) ÷ O(t+1) − 1：t+1 开盘到 t+6 开盘的五个开市日收益，按交易日历数开市日",
    "horizon": HORIZON,
    "label_sessions": label_sessions(HORIZON),
}
# Where the inputs come from and when they are known (ADR-0001, ADR-0005).
DATA = {
    "source": "J-Quants 日线（daily_bars）、交易日历、市场分类区间与 TOPIX",
    "prices": "特征与标签用研究价格，成交与记账用成交价格",
    "available": "t 日的日线在 t 收盘后同步，t 收盘决策时可得；最早 t+1 开盘成交",
    "point_in_time": "行情按证券和日期只存一份，后来的修正会覆盖原值；输入指纹只证明两次输入是否相同，不能恢复被覆盖的行情，"
                     "所以只声称保存下来的运行结果可审计",
    "universe": "当天的历史 Prime 普通股，20 日平均成交额 ≥ 5 亿日元，当天有可交易日线",
}
SUPPORTED_ACTIONS = ("disposition", "priority")
# Declared by a later step's policies (06c), not run by this one.
UNSUPPORTED_ACTIONS = {"target_weight": "目标权重", "gross_exposure": "总敞口"}
BENCHMARKS = ("topix_price", "eligible_equal_weight")
FEATURE_BARS = 61  # bars ret_60 needs, the day's own included
TRADING_TERMS = ("initial_cash", "max_positions", "max_weight", "cash_floor", "commission_rate", "commission_min",
                 "slippage")
MAX_BASELINES = 3
MAX_STRESS = 5
MAX_SLIPPAGE = Decimal("0.1")  # each side, exclusive: the base's and every stress scenario's
STRESS_BASIS = ("压力场景只回放主模型：每边滑点 = 基础滑点 + 登记时声明的加成；手续费率和最低手续费沿用基础成本，"
                "不加压")

# The keys a model's folds, scores and replays are stored under, and a replay's cost scenarios.
MAIN = "model"
BASELINE = "baseline_{}"  # numbered from 1, in the contract's order
BASE, STRESS = "base", "stress"

DEFAULTS: Mapping[str, Any] = {
    "name": "",
    "train_sessions": 250,
    "test_sessions": 60,
    "expanding": False,
    "rebalance_sessions": 5,
    "max_holding_sessions": 0,
    "trainer": "ridge_v1",
    "trainer_params": {},
    "baselines": ["rule_short_reversal_v1"],
    "source_account_id": None,
    "initial_cash": 10_000_000,
    "max_positions": 10,
    "max_weight": 0.10,
    "cash_floor": 0.05,
    "max_adv20_fraction": 0.05,
    "commission_rate": 0.0,
    "commission_min": 0.0,
    "slippage": 0.001,
    "stress_bps": [10, 25, 50],
    "min_coverage": 0.8,
    "min_training_samples": 20_000,
    "min_labelled_days": 24,
    "min_trades": 30,
    "actions": list(SUPPORTED_ACTIONS),
}


@dataclass(frozen=True)
class ExperimentPlan:
    """What a contract implies on the trading calendar."""

    sessions: list[date]       # the calendar through the test end
    folds: list[Fold]
    test_days: list[date]      # replayed, the first test day to the last
    decision_days: list[date]  # the anchor, then every `rebalance_sessions` sessions
    feature_days: list[date]   # the first fold's training start to the test end
    read_from: date            # a feature's worth of bars before that, as far as the calendar goes


@dataclass(frozen=True)
class ExperimentModel:
    """One of the models an experiment scores with: the model, or a rule baseline."""

    key: str                   # MAIN, or BASELINE numbered
    role: str                  # "model" / "baseline"
    label: str                 # its name on screen: 主模型, 规则基线 1, …
    trainer: str
    params: Mapping[str, Any]


@dataclass(frozen=True)
class PlannedReplay:
    """One of an experiment's replays, in the order they run and are stored."""

    position: int              # from 1
    model: ExperimentModel
    scenario: str              # BASE or STRESS
    slippage: Decimal          # each side
    extra_bps: Decimal | None  # a stress scenario's addition to the base slippage, in basis points


def freeze(request: Mapping[str, Any], *, sessions: Sequence[date], source: Mapping[str, Any] | None,
           viewed_through: date | None, trainers: Callable[[str, Mapping[str, Any]], Trainer]) -> dict:
    """The contract `request` registers, on the calendar `sessions`.
    `source` is the source account's trading terms when the request names
    one (only those are copied); `viewed_through` the latest session seen
    before. ValueError, in Chinese, for anything that cannot run."""
    unknown = sorted(set(request) - set(DEFAULTS) - {"test_from", "test_to"})
    if unknown:
        raise ValueError(f"不认识这些实验参数：{', '.join(unknown)}")
    given = {key: value for key, value in request.items() if value is not None}
    if source is not None:
        clash = [key for key in TRADING_TERMS if key in given]
        if clash:
            raise ValueError("已选来源账户，初始资金、组合规则和费用都从来源复制，不能另填：" + ", ".join(clash))
    values = {**DEFAULTS, **(dict(source) if source is not None else {}), **given}

    _check_actions(values["actions"])
    test_from, test_to = _session(values.get("test_from"), "测试起点", sessions), \
        _session(values.get("test_to"), "测试终点", sessions)
    if test_from > test_to:
        raise ValueError("测试起点不能晚于测试终点")
    folds = {"train_sessions": _whole(values["train_sessions"], "训练窗", label_sessions() + 1),
             "test_sessions": _whole(values["test_sessions"], "测试段", 1),
             "expanding": _flag(values["expanding"], "扩展训练窗")}
    policy = {"strategy": ScoreTopN.name, "anchor": test_from.isoformat(),
              "rebalance_sessions": _whole(values["rebalance_sessions"], "决策日间隔（每隔几个开市日一个决策日）", 1),
              "max_holding_sessions": _whole(values["max_holding_sessions"], "最长持有", 0),
              "warmup_sessions": 1,
              "missing_scores": "决策日模型没有分数（某折训练失败等）：不开新仓，已有持仓保留，不沿用旧分数",
              "score_missing": "模型可用但某只没有分数（离开股票池、特征缺失）：空仓不买，持仓卖出"}
    # Never the source's: null here means no cap, not "take it from elsewhere".
    cap = request["max_adv20_fraction"] if "max_adv20_fraction" in request else DEFAULTS["max_adv20_fraction"]
    rules = {"initial_cash": _decimal(values["initial_cash"], "初始资金", low=0, open_low=True),
             "max_positions": _whole(values["max_positions"], "最多持有只数", 1),
             "max_weight": _decimal(values["max_weight"], "单只上限", low=0, high=1, open_low=True),
             "cash_floor": _decimal(values["cash_floor"], "现金下限", low=0, high=1, open_high=True)}
    if cap is not None:
        rules["max_adv20_fraction"] = _decimal(cap, "ADV20 上限", low=0, high=1, open_low=True)
    costs = {"commission_rate": _decimal(values["commission_rate"], "手续费率", low=0, high=Decimal("0.1"),
                                         open_high=True),
             "commission_min": _decimal(values["commission_min"], "最低手续费", low=0),
             "slippage": _decimal(values["slippage"], "滑点", low=0, high=MAX_SLIPPAGE, open_high=True)}
    stress = _stress(values["stress_bps"], Decimal(costs["slippage"]))

    model = _model(values["trainer"], values["trainer_params"], trainers)
    baselines = values["baselines"]
    if not isinstance(baselines, list) or not 1 <= len(baselines) <= MAX_BASELINES:
        raise ValueError(f"规则基线要有 1 到 {MAX_BASELINES} 个")
    baselines = [{k: v for k, v in _model(name, {}, trainers).items() if k != "search_budget"} for name in baselines]

    name = values["name"]
    if not isinstance(name, str) or len(name) > 100:
        raise ValueError("实验名称要是不超过 100 字的文字")
    source_id = values["source_account_id"]
    contract = {
        "version": VERSION,
        "name": name,
        "task": dict(TASK),
        "data": dict(DATA),
        "features": {"version": FEATURES_V1, "names": list(FEATURE_NAMES)},
        "universe_rule": UniverseRule.PRIME_COMMON_STOCK.value,
        "test_from": test_from.isoformat(),
        "test_to": test_to.isoformat(),
        "folds": folds,
        "policy": policy,
        "portfolio_rules": rules,
        "costs": costs,
        "stress": {"basis": STRESS_BASIS, "scenarios": stress},
        "model": model,
        "baselines": baselines,
        "benchmarks": list(BENCHMARKS),
        "minimums": {"coverage": _fraction(values["min_coverage"], "最低覆盖率"),
                     "training_samples": _whole(values["min_training_samples"], "每折最少训练样本数", 0),
                     "labelled_days": _whole(values["min_labelled_days"], "最少有标签的决策日", 0),
                     "trades": _whole(values["min_trades"], "最低成交数", 0)},
        "viewed_through": None if viewed_through is None else viewed_through.isoformat(),
        "actions": list(values["actions"]),
        "source_account_id": source_id,
    }
    plan(contract, sessions)  # enough history for the folds
    return json.loads(json.dumps(contract, allow_nan=False))


def plan(contract: Mapping[str, Any], sessions: Sequence[date]) -> ExperimentPlan:
    """The folds, replay days, decision days and read start `contract`
    implies on the calendar `sessions`; ValueError if there is not enough
    history before the test span for the training window."""
    test_from, test_to = date.fromisoformat(contract["test_from"]), date.fromisoformat(contract["test_to"])
    calendar = [day for day in sorted(set(sessions)) if day <= test_to]
    folds = make_folds(calendar, test_from=test_from, test_to=test_to, **contract["folds"])
    test_days = [day for day in calendar if day >= test_from]
    anchor = date.fromisoformat(contract["policy"]["anchor"])
    decision_days = [day for day in test_days if day >= anchor][::contract["policy"]["rebalance_sessions"]]
    first = calendar.index(folds[0].train_from)
    return ExperimentPlan(calendar, folds, test_days, decision_days, calendar[first:],
                          calendar[max(0, first - FEATURE_BARS)])


def models(contract: Mapping[str, Any]) -> list[ExperimentModel]:
    """The model first, then each rule baseline in the contract's order."""
    return [ExperimentModel(MAIN, "model", "主模型", contract["model"]["trainer"], contract["model"]["params"])] + [
        ExperimentModel(BASELINE.format(n), "baseline", f"规则基线 {n}", baseline["trainer"], baseline["params"])
        for n, baseline in enumerate(contract["baselines"], 1)]


def replays(contract: Mapping[str, Any]) -> list[PlannedReplay]:
    """The model at the base costs, then at each stress scenario, then each
    rule baseline at the base costs."""
    main, *baselines = models(contract)
    base = Decimal(contract["costs"]["slippage"])
    runs = [(main, BASE, base, None)] + [
        (main, STRESS, Decimal(scenario["slippage"]), Decimal(scenario["extra_bps"]))
        for scenario in contract["stress"]["scenarios"]] + [(model, BASE, base, None) for model in baselines]
    return [PlannedReplay(position, *run) for position, run in enumerate(runs, 1)]


def contract_hash(contract: Mapping[str, Any]) -> str:
    """sha256 of the contract's canonical JSON."""
    canonical = json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _check_actions(actions: Any) -> None:
    """The kinds of instruction the policy gives (`actions`): 06a's only
    ever says whether to hold each code and in which order."""
    if not isinstance(actions, list) or not all(isinstance(a, str) for a in actions):
        raise ValueError("持有规则能下达的指令种类要是文字列表")
    declared = [UNSUPPORTED_ACTIONS[a] + f"（{a}）" for a in actions if a in UNSUPPORTED_ACTIONS]
    if declared:
        raise ValueError("本步的持有规则只能下达 disposition、priority 两种指令（每只持有还是卖出、排序优先级），"
                         "契约声明了尚未实现的指令种类：" + "、".join(declared) + "，拒绝登记，不会忽略它们照常运行")
    unknown = [a for a in actions if a not in SUPPORTED_ACTIONS]
    if unknown:
        raise ValueError("不认识这些指令种类：" + ", ".join(unknown))
    if set(actions) != set(SUPPORTED_ACTIONS):
        raise ValueError("指令种类必须声明 disposition 和 priority：分数只决定持有和排序")


def _stress(extras: Any, base: Decimal) -> list[dict]:
    """Each stress scenario: what it adds to the base slippage each side, in
    basis points (more than 0, no two the same), and the slippage that
    makes."""
    if not isinstance(extras, list) or len(extras) > MAX_STRESS:
        raise ValueError(f"压力场景要是至多 {MAX_STRESS} 个滑点加成（bps）的列表")
    scenarios, seen = [], set()
    for extra in extras:
        bps = Decimal(_decimal(extra, "压力场景的滑点加成（bps）", low=0, open_low=True))
        if bps in seen:
            raise ValueError(f"压力场景的滑点加成不能重复：{_plain(bps)} bps 出现了两次")
        seen.add(bps)
        slippage = base + bps / 10_000
        if slippage >= MAX_SLIPPAGE:
            raise ValueError(f"压力场景每边滑点 = 基础 {_plain(base)} + {_plain(bps)} bps = {_plain(slippage)}，"
                             f"要小于 {MAX_SLIPPAGE}")
        scenarios.append({"extra_bps": _plain(bps), "slippage": _plain(slippage)})
    return scenarios


def _plain(number: Decimal) -> str:
    """10.0 → "10", 0.0020 → "0.002": one text for one number."""
    return format(number.normalize(), "f")


def _model(name: Any, params: Any, trainers: Callable[[str, Mapping[str, Any]], Trainer]) -> dict:
    if not isinstance(name, str) or not isinstance(params, Mapping):
        raise ValueError("训练器要给名字和参数表")
    trainer = trainers(name, params)  # refuses a name or parameter it does not know
    return {"trainer": trainer.name, "params": dict(getattr(trainer, "params", params)), "search_budget": 1}


def _session(value: Any, what: str, sessions: Sequence[date]) -> date:
    if value is None:
        raise ValueError(f"缺少{what}")
    day = value if isinstance(value, date) else date.fromisoformat(str(value))
    if day not in set(sessions):
        raise ValueError(f"{what} {day} 不是已知开市日")
    return day


def _whole(value: Any, what: str, low: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float) or not float(value).is_integer() \
            or value < low:
        raise ValueError(f"{what}要是不小于 {low} 的整数，收到 {value}")
    return int(value)


def _flag(value: Any, what: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{what}要是 true 或 false")
    return value


def _fraction(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) \
            or not 0 <= value <= 1:
        raise ValueError(f"{what}要在 0 到 1 之间，收到 {value}")
    return float(value)


def _decimal(value: Any, what: str, *, low: Decimal | int | None = None, high: Decimal | int | None = None,
             open_low: bool = False, open_high: bool = False) -> str:
    """A finite number in range, as the decimal text the trading terms keep."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValueError(f"{what}要是数值，收到 {value}")
    try:
        number = Decimal(str(value))
    except ArithmeticError:
        raise ValueError(f"{what}要是数值，收到 {value}") from None
    if not number.is_finite():
        raise ValueError(f"{what}必须是有限数值")
    if low is not None and (number < low or (open_low and number == low)) \
            or high is not None and (number > high or (open_high and number == high)):
        lower = "" if low is None else f"{'大于' if open_low else '不小于'} {low}"
        upper = "" if high is None else f"{'小于' if open_high else '不大于'} {high}"
        raise ValueError(f"{what}要{lower}{'、' if lower and upper else ''}{upper}，收到 {value}")
    return str(number)
