"use client";

import { useEffect, useState } from "react";
import { api, type Schemas } from "@/lib/api/client";
import { fraction, percentText, yen } from "@/lib/format";
import { ACTIONS, EXPERIMENT_EVIDENCE, FEATURES, TRAINER_PARAMS, trainerAbout, trainerLabel } from "@/lib/labels";
import { Pager } from "../../pager";
import { ExperimentView } from "./experiment-view";
import { bps } from "./experiment-shared";
import { message, STATES, useSubmit } from "./research-shared";

type Defaults = Schemas["ExperimentDefaults"];
type Body = Omit<Schemas["ExperimentIn"], "request_key">;
type SourceDetail = Schemas["AccountDetailOut"];

const HISTORY_SIZE = 10;

/** The numbers the form takes. A `percent` one is typed as a percentage and sent as a fraction. */
type Field = { key: string; label: string; unit: string; min?: number; max?: number; step?: number | "any"; percent?: boolean; hint?: string };

const SPAN: Field[] = [
  { key: "train_sessions", label: "训练窗", unit: "开市日", min: 7, step: 1, hint: "每折只用测试段之前这么多个开市日的样本训练" },
  { key: "test_sessions", label: "每折测试段", unit: "开市日", min: 1, step: 1, hint: "测试段按这个长度切成首尾相接的折，最后一折可以短些" },
  { key: "rebalance_sessions", label: "调仓间隔", unit: "开市日", min: 1, step: 1, hint: "从测试起点起，每隔这么多个开市日决策一次" },
  { key: "max_holding_sessions", label: "最长持有", unit: "开市日", min: 0, step: 1, hint: "0 表示不限；到期卖出" },
];
const TRADING: Field[] = [
  { key: "initial_cash", label: "初始资金", unit: "日元", min: 0, step: 100_000 },
  { key: "max_positions", label: "最多持有", unit: "只", min: 1, step: 1 },
  { key: "max_weight", label: "单只上限", unit: "%", min: 0, max: 100, percent: true, hint: "占净值的比例" },
  { key: "cash_floor", label: "现金下限", unit: "%", min: 0, max: 100, percent: true, hint: "下单时至少留下的现金，占净值的比例" },
  { key: "commission_rate", label: "手续费率", unit: "%", min: 0, max: 10, percent: true, hint: "按成交额" },
  { key: "commission_min", label: "最低手续费", unit: "日元", min: 0, step: 1, hint: "每笔" },
  { key: "slippage", label: "滑点", unit: "% 每边", min: 0, max: 10, percent: true, hint: "基础成本：成交价比开盘价差这么多" },
];
const OTHER: Field[] = [
  { key: "max_adv20_fraction", label: "成交额上限", unit: "% ADV20", min: 0, max: 100, percent: true,
    hint: "每笔买单金额不超过前 20 个开市日平均成交额的这个比例" },
  { key: "min_coverage", label: "最低覆盖率", unit: "%", min: 0, max: 100, percent: true, hint: "决策日有分数的证券占当天股票池的比例，平均低于它算证据不足" },
  { key: "min_trades", label: "最少成交", unit: "笔", min: 0, step: 1, hint: "主模型基础成本回放的成交笔数少于它算证据不足" },
];
const FIELDS = [...SPAN, ...TRADING, ...OTHER];

type Form = {
  name: string; testFrom: string; testTo: string; expanding: boolean; trainer: string; params: Record<string, string>;
  baselines: string[]; source: string; numbers: Record<string, string>; noCap: boolean; stress: string;
};

const shown = (field: Field, value: unknown) =>
  typeof value === "number" ? (field.percent ? percentText(value) : String(value)) : "";

const paramsText = (params: Record<string, unknown> | undefined) =>
  Object.fromEntries(Object.entries(params ?? {}).map(([key, value]) => [key, String(value)]));

function initialForm({ defaults: v, trainers }: Defaults): Form {
  const trainer = String(v.trainer);
  return {
    name: String(v.name ?? ""), testFrom: "", testTo: "", expanding: Boolean(v.expanding), trainer,
    params: paramsText(trainers[trainer]), baselines: (v.baselines as string[]) ?? [], source: "",
    numbers: Object.fromEntries(FIELDS.map(f => [f.key, shown(f, v[f.key])])),
    noCap: v.max_adv20_fraction === null, stress: ((v.stress_slippages as number[]) ?? []).map(percentText).join(", "),
  };
}

const stressList = (text: string) => text.split(/[\s,，、]+/).filter(Boolean).map(fraction);

/** What the form registers. The trading terms are left out (null) when a source account lends its own. */
function requestBody(form: Form, defaults: Defaults): Body {
  const number = (key: string) => {
    const field = FIELDS.find(f => f.key === key)!;
    return field.percent ? fraction(form.numbers[key]) : Number(form.numbers[key]);
  };
  const fromSource = form.source !== "";
  const trading = (key: string) => (fromSource ? null : number(key));
  return {
    name: form.name.trim(), test_from: form.testFrom, test_to: form.testTo,
    train_sessions: number("train_sessions"), test_sessions: number("test_sessions"), expanding: form.expanding,
    rebalance_sessions: number("rebalance_sessions"), max_holding_sessions: number("max_holding_sessions"),
    trainer: form.trainer, trainer_params: Object.fromEntries(Object.entries(form.params).map(([k, v]) => [k, Number(v)])),
    baselines: form.baselines, source_account_id: fromSource ? Number(form.source) : null,
    initial_cash: trading("initial_cash"), max_positions: trading("max_positions"), max_weight: trading("max_weight"),
    cash_floor: trading("cash_floor"), commission_rate: trading("commission_rate"),
    commission_min: trading("commission_min"), slippage: trading("slippage"),
    max_adv20_fraction: form.noCap ? null : number("max_adv20_fraction"),
    stress_slippages: stressList(form.stress), min_coverage: number("min_coverage"), min_trades: number("min_trades"),
    actions: defaults.supported_actions,
  };
}

function setQuery(experiment: string) {
  const url = new URL(window.location.href);
  url.searchParams.set("mode", "experiment");
  if (experiment) url.searchParams.set("experiment", experiment); else url.searchParams.delete("experiment");
  window.history.replaceState(null, "", url);
}

/** Model experiments (06a): register a frozen contract, follow it while it runs, browse every attempt. */
export function ExperimentWorkspace({ initialExperiment = "" }: { initialExperiment?: string }) {
  const [defaults, setDefaults] = useState<Defaults | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [accounts, setAccounts] = useState<Schemas["AccountSummaryOut"][]>([]);
  const [source, setSource] = useState<SourceDetail | null>(null);
  const [selected, setSelected] = useState(initialExperiment);
  const [version, setVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const { busy, send } = useSubmit(setError);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const [d, a] = await Promise.all([
          api.GET("/api/experiments/defaults", { signal: controller.signal }),
          api.GET("/api/accounts", { signal: controller.signal }),
        ]);
        if (!d.data) throw d.error ?? new Error("读取实验默认值失败");
        setDefaults(d.data);
        setForm(current => current ?? initialForm(d.data));
        if (a.data) setAccounts(a.data);
      } catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    })();
    return () => controller.abort();
  }, [version]);

  // The chosen source's terms, so the form can say what it will copy.
  const sourceId = form?.source ?? "";
  useEffect(() => {
    setSource(null);
    if (!sourceId) return;
    const controller = new AbortController();
    void api.GET("/api/accounts/{account_id}", { params: { path: { account_id: Number(sourceId) } }, signal: controller.signal })
      .then(r => { if (r.data && !controller.signal.aborted) setSource(r.data); }).catch(() => null);
    return () => controller.abort();
  }, [sourceId]);

  function open(id: string) {
    setSelected(id);
    setQuery(id);
  }

  function submit() {
    if (!form || !defaults) return;
    setError(null);
    const body = requestBody(form, defaults);
    return send(body, async key => {
      const response = await api.POST("/api/experiments", { body: { ...body, request_key: key } });
      if (response.error) throw response.error;
      open(response.data.id);
      setVersion(v => v + 1);
    });
  }

  const update = (change: Partial<Form>) => setForm(current => (current ? { ...current, ...change } : current));
  const setNumber = (key: string, value: string) => setForm(current => (current ? { ...current, numbers: { ...current.numbers, [key]: value } } : current));

  return <>
    <p className="meta">先登记一份冻结的实验契约，再按日期折逐折训练、只用折外分数选股，用同一套账户成交规则回放。Ridge 冒烟只证明这套框架能跑通，不代表模型有效。</p>
    {error && <div role="alert">{error} <button type="button" className="btn" onClick={() => { setError(null); setVersion(v => v + 1); }}>重新读取</button></div>}
    {!defaults && !error && <p role="status">正在读取实验默认值…</p>}
    {defaults && form && <form className="card" aria-label="登记模型实验" onSubmit={e => { e.preventDefault(); void submit(); }}>
      <div className="card-h"><h2>登记模型实验</h2><span>{defaults.task.name} · {defaults.features.version}</span></div>
      <div className="form three">
        <div className="field wide"><label htmlFor="experiment-name">实验名称</label>
          <input id="experiment-name" className="input" maxLength={100} placeholder="可留空" value={form.name}
            onChange={e => update({ name: e.target.value })} /></div>
        <div className="field"><label htmlFor="experiment-from">测试起点</label>
          <input id="experiment-from" className="input" type="date" required max={form.testTo || undefined} value={form.testFrom}
            onChange={e => update({ testFrom: e.target.value })} />
          <div className="hint">须是开市日；之前要有训练窗那么多个开市日，再加 61 个开市日算特征</div></div>
        <div className="field"><label htmlFor="experiment-to">测试终点</label>
          <input id="experiment-to" className="input" type="date" required min={form.testFrom || undefined} value={form.testTo}
            onChange={e => update({ testTo: e.target.value })} />
          <div className="hint">须是有 TOPIX 收盘的开市日；之后的行情一概不读</div></div>
        <label className="field"><span className="label">扩展训练窗</span>
          <span><input type="checkbox" checked={form.expanding} onChange={e => update({ expanding: e.target.checked })} /> 从最早可用的日子起训练（不只用训练窗）</span></label>
        {SPAN.map(f => <NumberField key={f.key} field={f} value={form.numbers[f.key]} onChange={v => setNumber(f.key, v)} />)}
        <div className="field"><label htmlFor="experiment-trainer">主模型</label>
          <select id="experiment-trainer" className="input" value={form.trainer}
            onChange={e => update({ trainer: e.target.value, params: paramsText(defaults.trainers[e.target.value]) })}>
            {Object.keys(defaults.trainers).map(name => <option key={name} value={name}>{trainerLabel(name)}</option>)}
          </select>
          <div className="hint">{trainerAbout(form.trainer) && `${trainerAbout(form.trainer)}。`}搜索预算 1：参数登记时固定，不在测试段上调</div></div>
        {Object.keys(form.params).map(key => <div className="field" key={key}>
          <label htmlFor={`experiment-param-${key}`}>{TRAINER_PARAMS[key]?.label ?? key}</label>
          <input id={`experiment-param-${key}`} className="input" type="number" step="any" required value={form.params[key]}
            onChange={e => update({ params: { ...form.params, [key]: e.target.value } })} />
          {TRAINER_PARAMS[key] && <div className="hint">{TRAINER_PARAMS[key].hint}</div>}</div>)}
        <fieldset className="choice wide"><legend>规则基线（1 到 3 个，用同样的折、股票池和成交规则回放）</legend>
          {Object.keys(defaults.trainers).map(name => <label key={name} className="opt">
            <input type="checkbox" checked={form.baselines.includes(name)} onChange={() => update({
              baselines: form.baselines.includes(name) ? form.baselines.filter(b => b !== name) : [...form.baselines, name] })} />
            <div><div className="t">{trainerLabel(name)}</div><div className="d">{trainerAbout(name)}</div></div>
          </label>)}</fieldset>
        <div className="field wide"><label htmlFor="experiment-source">来源账户</label>
          <select id="experiment-source" className="input" value={form.source} onChange={e => update({ source: e.target.value })}>
            <option value="">不用（按下面填的资金、组合规则和费用）</option>
            {accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <div className="hint">只复制初始资金、组合规则和费用；来源账户本身不会被读写别的内容</div></div>
        {TRADING.map(f => <NumberField key={f.key} field={f} value={form.numbers[f.key]} disabled={form.source !== ""}
          onChange={v => setNumber(f.key, v)} />)}
        {form.source !== "" && <p className="wide meta">{source ? <SourceTerms source={source} /> : "正在读取来源账户的规则…"}</p>}
        <div className="field">
          <NumberField field={OTHER[0]} value={form.numbers.max_adv20_fraction} disabled={form.noCap}
            onChange={v => setNumber("max_adv20_fraction", v)} bare />
          <label><input type="checkbox" checked={form.noCap} onChange={e => update({ noCap: e.target.checked })} /> 不设上限</label></div>
        <div className="field"><label htmlFor="experiment-stress">压力场景滑点</label>
          <div className="affix"><input id="experiment-stress" className="input" required value={form.stress}
            onChange={e => update({ stress: e.target.value })} /><span>% 每边</span></div>
          <div className="hint">至多 5 个，用逗号隔开；只换主模型回放的滑点，手续费不变</div></div>
        {OTHER.slice(1).map(f => <NumberField key={f.key} field={f} value={form.numbers[f.key]} onChange={v => setNumber(f.key, v)} />)}
      </div>
      <Consequences defaults={defaults} form={form}
        maxPositions={form.source ? source?.rules.max_positions : form.numbers.max_positions} />
      <div className="foot"><span>登记后契约冻结；运行要读全市场行情，真实数据上约 3 分钟。</span>
        <button className="btn primary" disabled={busy || form.baselines.length === 0}>{busy ? "提交中…" : "登记并运行"}</button></div>
    </form>}

    {selected && <ExperimentView key={selected} id={selected} onOpen={open} onStatus={() => setVersion(v => v + 1)} />}

    <ExperimentHistory version={version} onOpen={open} />

    <section className="card" aria-label="模型实验解读须知"><div className="card-h"><h2>解读须知</h2></div>
      <ul className="list">
        <li>每折只用测试段之前、标签已经结束的样本训练；同一天的所有证券在同一折。分数只在决策日保存，回放只用这些折外分数。</li>
        <li>「已看过」的折在登记前就可能被看到过结果，换一种切分也不是盲测；本步只给出「探索性」或「证据不足」，不会判定通过。</li>
        <li>合格池等权和 TOPIX 是参照，不是可成交的账户：合格池不扣费用、不受整手和现金约束，TOPIX 是价格指数，都不含分红。</li>
        <li>压力场景只换滑点，逐日决定只为基础成本的回放保存；结果不含税，不代表未来有效。</li>
      </ul></section>
  </>;
}

function NumberField({ field: f, value, onChange, disabled = false, bare = false }: {
  field: Field; value: string; onChange: (value: string) => void; disabled?: boolean; bare?: boolean;
}) {
  const id = `experiment-${f.key}`;
  const inner = <>
    <label htmlFor={id}>{f.label}</label>
    <div className="affix">
      <input id={id} className="input" type="number" required={!disabled} disabled={disabled} min={f.min} max={f.max}
        step={f.step ?? "any"} value={value} onChange={e => onChange(e.target.value)} />
      <span>{f.unit}</span>
    </div>
    {f.hint && <div className="hint">{f.hint}</div>}
  </>;
  return bare ? inner : <div className="field">{inner}</div>;
}

function SourceTerms({ source: s }: { source: SourceDetail }) {
  const r = s.rules, c = s.costs;
  return <>将从「{s.name}」复制：初始资金 ¥{yen(r.initial_cash)} · 最多 {r.max_positions} 只 · 单只上限 {percentText(r.max_weight)}% ·
    现金下限 {percentText(r.cash_floor)}% · 手续费率 {percentText(c.commission_rate)}% · 最低手续费 ¥{yen(c.commission_min)} ·
    每边滑点 {percentText(c.slippage)}%</>;
}

/** What registering commits to, worked out from the form before anything is sent. */
function Consequences({ defaults: d, form, maxPositions }: { defaults: Defaults; form: Form; maxPositions?: number | string }) {
  const stress = stressList(form.stress);
  const replays = 1 + stress.length + form.baselines.length;
  const unsupported = d.unsupported_actions.map(a => ACTIONS[a] ?? a).join("、");
  return <section className="card-body" aria-label="登记后冻结的内容">
    <p><b>登记即冻结，之后不能修改。</b>改任何一项都要登记新实验；失败后重试沿用同一份契约，研究输入（行情）变了就不能重试。</p>
    <ul>
      <li>任务 {d.task.name}：{d.task.decision}。标签：{d.task.label}。</li>
      <li>特征 {d.features.version}：{d.features.names.map(n => FEATURES[n] ?? n).join("、")}。都只用当天收盘前已知的日线；缺任何一项的证券当天不打分。</li>
      <li>股票池：每个决策日当天的 Prime 普通股（20 日平均成交额 ≥ 5 亿日元），只给它们打分。</li>
      <li>政策：从测试起点起每 {form.numbers.rebalance_sessions || "—"} 个开市日决策一次，持有分数最高的前 {maxPositions || "—"} 只；
        决策日模型没有分数时不开新仓、已有持仓保留，不沿用旧分数。</li>
      <li>共 {replays} 个回放：主模型 × 基础成本和 {stress.length} 个压力场景（每边滑点 {stress.map(bps).join("、") || "—"}），
        每个规则基线 × 基础成本；对照 TOPIX 价格指数和合格池等权。</li>
      <li>动作能力：只支持{d.supported_actions.map(a => ACTIONS[a] ?? a).join("和")}；{unsupported}尚未实现，契约里声明了会被拒绝登记，不会悄悄忽略。</li>
      <li>证据：本步只给出「{EXPERIMENT_EVIDENCE.exploratory.label}」或「{EXPERIMENT_EVIDENCE.insufficient_evidence.label}」，不会判定通过。</li>
    </ul>
    <Viewed through={d.viewed_through} from={form.testFrom} to={form.testTo} />
  </section>;
}

function Viewed({ through, from, to }: { through: string | null; from: string; to: string }) {
  if (!through) return <p>还没有看过任何历史结果（没有推进过的模拟账户，也没有完成的研究运行或实验），各折都不会标「已看过」。</p>;
  const seen = `截至 ${through} 的历史已经看过：模拟账户推进到的日子、已完成的研究运行和实验的区间都算，登记时冻结这个日期。`;
  if (!from) return <p>{seen}测试段第一天不晚于这天的折会标「探索性（已看过）」。</p>;
  if (from > through) return <p>{seen}所选测试段从 {from} 开始，在这之后，折不会标「已看过」。</p>;
  return <p className="notice">{seen}所选测试段从 {from} 开始，不晚于 {through}：
    {to && to <= through ? "整个测试段都已看过，" : "前面的折已看过，"}这些折会标「探索性（已看过）」，结果只能算探索性；换一种切分也不会变成盲测。</p>;
}

function ExperimentHistory({ version, onOpen }: { version: number; onOpen: (id: string) => void }) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Schemas["ExperimentHistory"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await api.GET("/api/experiments", {
          params: { query: { page, page_size: HISTORY_SIZE } }, signal: controller.signal,
        });
        if (response.error) throw response.error;
        setData(response.data);
      } catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    })();
    return () => controller.abort();
  }, [page, version]);
  return <section className="card"><div className="card-h"><h2>全部模型实验</h2>{data && <span>共 {data.total} 次（每次重试也单独一条）</span>}</div>
    {error && <p role="alert">{error}</p>}
    <div className="scroll"><table aria-label="模型实验历史"><thead><tr><th>实验</th><th>名称</th><th>测试段</th><th>主模型 / 基线</th><th>状态</th><th>证据</th><th>登记时间</th></tr></thead>
      <tbody>{data?.experiments.map(x => {
        const evidence = x.evidence_status ? EXPERIMENT_EVIDENCE[x.evidence_status] : null;
        return <tr key={x.id}>
          <td><button type="button" className="btn" onClick={() => onOpen(x.id)}>{x.id.slice(0, 8)}</button>
            {x.retry_of && <span className="sub"> 重试自 {x.retry_of.slice(0, 8)}</span>}</td>
          <td className="wrap">{x.name || "—"}</td>
          <td>{x.test_from} — {x.test_to}</td>
          <td>{trainerLabel(x.trainer)} / {x.baselines.map(trainerLabel).join("、")}</td>
          <td>{STATES[x.status]}</td>
          <td>{evidence ? <span className={`badge ${evidence.tone}`}>{evidence.label}</span> : "—"}</td>
          <td>{x.created_at.slice(0, 16).replace("T", " ")}</td>
        </tr>;
      })}</tbody></table></div>
    {data?.total === 0 && <p className="empty">还没有模型实验</p>}
    <Pager page={page} pages={Math.max(1, Math.ceil((data?.total ?? 0) / HISTORY_SIZE))} onPage={setPage} />
  </section>;
}
