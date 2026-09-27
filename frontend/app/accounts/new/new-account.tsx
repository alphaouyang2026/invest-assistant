"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useState } from "react";

import { api, type Schemas } from "@/lib/api/client";
import { DEFAULT_STRATEGY, PARAMS, STRATEGIES } from "@/lib/labels";

type StrategyInfo = Schemas["StrategyOut"];

/** Portfolio rules and costs (spec §3.5), with their defaults. A `percent`
 * one is typed as a percentage and sent as a fraction. */
const RULES = [
  { key: "initial_cash", label: "初始资金", value: "10000000", unit: "日元", step: 100_000 },
  { key: "max_positions", label: "最多持有", value: "10", unit: "只", step: 1 },
  { key: "max_weight", label: "单只上限", value: "10", unit: "%", percent: true, hint: "占净值的比例" },
  { key: "cash_floor", label: "现金下限", value: "5", unit: "%", percent: true, hint: "下单时至少留下的现金，占净值的比例" },
  { key: "commission_rate", label: "手续费率", value: "0", unit: "%", percent: true, hint: "按成交额" },
  { key: "commission_min", label: "最低手续费", value: "0", unit: "日元", step: 1, hint: "每笔" },
  { key: "slippage", label: "滑点", value: "0.1", unit: "% 每边", percent: true, hint: "成交价比开盘价差这么多" },
] as const;

type RuleKey = (typeof RULES)[number]["key"];

/** "0.1" (%) → 0.001, without 0.1 / 100's floating-point tail. */
const fraction = (text: string) => Number((Number(text) / 100).toPrecision(12));

export function NewAccount() {
  const router = useRouter();
  const id = useId();
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [strategy, setStrategy] = useState<string>(DEFAULT_STRATEGY);
  const [params, setParams] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  const [start, setStart] = useState("");
  const [rules, setRules] = useState<Record<string, string>>(
    Object.fromEntries(RULES.map((rule) => [rule.key, rule.value])),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const defaults = strategies.find((s) => s.name === strategy)?.defaults ?? {};

  useEffect(() => {
    void (async () => {
      const { data } = await api.GET("/api/strategies");
      if (data) setStrategies(data);
    })();
  }, []);

  useEffect(() => {
    setParams(Object.fromEntries(Object.entries(defaults).map(([key, value]) => [key, String(value)])));
    // a new strategy starts from its own defaults
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strategy, strategies]);

  const rule = (key: RuleKey) => {
    const found = RULES.find((r) => r.key === key)!;
    return "percent" in found ? fraction(rules[key]) : Number(rules[key]);
  };

  const submit = async () => {
    setBusy(true);
    const changed = Object.fromEntries(
      Object.entries(params)
        .filter(([key, value]) => Number(value) !== Number(defaults[key]))
        .map(([key, value]) => [key, Number(value)]),
    );
    const { data, error: refused } = await api.POST("/api/accounts", {
      body: {
        name, strategy, start_date: start, strategy_params: changed,
        initial_cash: rule("initial_cash"), max_positions: rule("max_positions"),
        max_weight: rule("max_weight"), cash_floor: rule("cash_floor"),
        commission_rate: rule("commission_rate"), commission_min: rule("commission_min"),
        slippage: rule("slippage"),
      },
    });
    setBusy(false);
    if (refused) {
      setError(typeof refused.detail === "string" ? refused.detail : "新建失败：请检查填写的内容");
      return;
    }
    router.push(`/accounts/${data.id}`);
  };

  const warmup = params.warmup_sessions ?? String(defaults.warmup_sessions ?? "");

  return (
    <section className="page narrow">
      <div className="crumb">
        <Link href="/accounts">账户</Link> / 新建
      </div>
      <div>
        <h1>新建账户</h1>
        <div className="meta">
          <span>建好后立刻在后台从起始日回测到最新交易日，三年约 1 分钟</span>
        </div>
      </div>
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <section className="card">
          <div className="card-h">
            <h2>策略与起始日</h2>
          </div>
          <div className="form">
            <div className="field wide">
              <label htmlFor={`${id}-name`}>账户名称</label>
              <input id={`${id}-name`} className="input" value={name} required
                     onChange={(event) => setName(event.target.value)} />
            </div>
            <fieldset className="choice wide">
              <legend>策略</legend>
              {strategies.map((s) => {
                const known = STRATEGIES.find((k) => k.name === s.name);
                return (
                  <label key={s.name} className="opt">
                    <input type="radio" name="strategy" value={s.name} checked={s.name === strategy}
                           onChange={() => setStrategy(s.name)} />
                    <div>
                      <div className="t">{known?.label ?? s.name}</div>
                      {known && <div className="d">{known.about}</div>}
                    </div>
                  </label>
                );
              })}
            </fieldset>
            <div className="field">
              <label htmlFor={`${id}-start`}>起始日</label>
              <input id={`${id}-start`} className="input" type="date" value={start} required
                     onChange={(event) => setStart(event.target.value)} />
              <div className="hint">须是开市日，之前至少有 {warmup || "预热期"} 个交易日的数据</div>
            </div>
          </div>
        </section>

        <section className="card">
          <div className="card-h">
            <h2>策略参数</h2>
            <span className="aside">改过的才会随账户保存，其余用默认值</span>
          </div>
          <div className="form three">
            {Object.keys(params).map((key) => (
              <div className="field" key={key}>
                <div className="label">
                  <label htmlFor={`${id}-${key}`}>{PARAMS[key]?.label ?? key}</label>
                  {PARAMS[key] && <span className="mono sub"> {key}</span>}
                </div>
                <input id={`${id}-${key}`} className="input" type="number" step="any" value={params[key]}
                       onChange={(event) => setParams({ ...params, [key]: event.target.value })} />
                {PARAMS[key] && <div className="hint">{PARAMS[key].hint}</div>}
              </div>
            ))}
          </div>
        </section>

        <section className="card">
          <div className="card-h">
            <h2>组合规则与费用</h2>
          </div>
          <div className="form three">
            {RULES.map((r) => (
              <div className="field" key={r.key}>
                <label htmlFor={`${id}-${r.key}`}>{r.label}</label>
                <div className="affix">
                  <input id={`${id}-${r.key}`} className="input" type="number" min={0}
                         step={"step" in r ? r.step : "any"} value={rules[r.key]}
                         onChange={(event) => setRules({ ...rules, [r.key]: event.target.value })} />
                  <span>{r.unit}</span>
                </div>
                {"hint" in r && <div className="hint">{r.hint}</div>}
              </div>
            ))}
          </div>
          <div className="submit">
            <span className="note">策略和规则建好后不能再改；想比较不同设置，就多建几个账户</span>
            <div className="actions">
              <Link href="/accounts" className="btn">
                取消
              </Link>
              <button type="submit" className="btn primary lg" disabled={busy}>
                新建并开始回测
              </button>
            </div>
          </div>
        </section>
        {error && <p role="alert">{error}</p>}
      </form>
    </section>
  );
}
