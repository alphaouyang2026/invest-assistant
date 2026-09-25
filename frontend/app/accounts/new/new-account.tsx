"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api, type Schemas } from "@/lib/api/client";
import { DEFAULT_STRATEGY, strategyLabel } from "@/lib/labels";

type StrategyInfo = Schemas["StrategyOut"];

/** Portfolio rules and costs (spec §3.5), with their defaults. */
const RULES = [
  { key: "initial_cash", label: "初始资金", value: 10_000_000, step: 100_000 },
  { key: "max_positions", label: "最多持有只数", value: 10, step: 1 },
  { key: "max_weight", label: "单只上限", value: 0.1, step: 0.01 },
  { key: "cash_floor", label: "现金下限", value: 0.05, step: 0.01 },
  { key: "commission_rate", label: "手续费率", value: 0, step: 0.0001 },
  { key: "commission_min", label: "最低手续费", value: 0, step: 1 },
  { key: "slippage", label: "滑点（每边）", value: 0.001, step: 0.0001 },
] as const;

export function NewAccount() {
  const router = useRouter();
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [strategy, setStrategy] = useState<string>(DEFAULT_STRATEGY);
  const [params, setParams] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  const [start, setStart] = useState("");
  const [rules, setRules] = useState<Record<string, string>>(
    Object.fromEntries(RULES.map((rule) => [rule.key, String(rule.value)])),
  );
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

  const submit = async () => {
    const changed = Object.fromEntries(
      Object.entries(params)
        .filter(([key, value]) => Number(value) !== Number(defaults[key]))
        .map(([key, value]) => [key, Number(value)]),
    );
    const { data, error: refused } = await api.POST("/api/accounts", {
      body: {
        name, strategy, start_date: start, strategy_params: changed,
        initial_cash: Number(rules.initial_cash), max_positions: Number(rules.max_positions),
        max_weight: Number(rules.max_weight), cash_floor: Number(rules.cash_floor),
        commission_rate: Number(rules.commission_rate), commission_min: Number(rules.commission_min),
        slippage: Number(rules.slippage),
      },
    });
    if (refused) {
      setError(typeof refused.detail === "string" ? refused.detail : "新建失败：请检查填写的内容");
      return;
    }
    router.push(`/accounts/${data.id}`);
  };

  return (
    <section>
      <h1>新建账户</h1>
      {error && <p role="alert">{error}</p>}
      <form
        className="controls"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label>
          名称
          <input value={name} required onChange={(event) => setName(event.target.value)} />
        </label>
        <label>
          策略
          <select value={strategy} onChange={(event) => setStrategy(event.target.value)}>
            {strategies.map((s) => (
              <option key={s.name} value={s.name}>
                {strategyLabel(s.name)}
              </option>
            ))}
          </select>
        </label>
        <label>
          起始日
          <input type="date" value={start} required onChange={(event) => setStart(event.target.value)} />
        </label>

        <fieldset>
          <legend>策略参数</legend>
          {Object.keys(params).map((key) => (
            <label key={key}>
              {key}
              <input type="number" step="any" value={params[key]}
                     onChange={(event) => setParams({ ...params, [key]: event.target.value })} />
            </label>
          ))}
        </fieldset>

        <fieldset>
          <legend>组合规则与费用</legend>
          {RULES.map((rule) => (
            <label key={rule.key}>
              {rule.label}
              <input type="number" step={rule.step} value={rules[rule.key]}
                     onChange={(event) => setRules({ ...rules, [rule.key]: event.target.value })} />
            </label>
          ))}
        </fieldset>

        <button type="submit">新建并开始回测</button>
      </form>
    </section>
  );
}
