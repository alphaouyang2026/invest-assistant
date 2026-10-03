"use client";

import Link from "next/link";
import { useState } from "react";
import { PrototypeSwitcher } from "../../../prototype-switcher";
import styles from "./prototype.module.css";

export type PrototypeVariant = "A" | "B" | "C";
export type PrototypeStep = "draft" | "development" | "validation" | "blind" | "challenger";

const VARIANTS = [
  { key: "A", name: "逐步向导" },
  { key: "B", name: "实验流水线" },
  { key: "C", name: "证据驾驶舱" },
];

const STEPS: Array<{ key: PrototypeStep; short: string; title: string; editable: string; revealed: string }> = [
  { key: "draft", short: "草稿", title: "建立研究草稿", editable: "全部研究参数", revealed: "尚未查看收益" },
  { key: "development", short: "开发", title: "开发期与版本化调整", editable: "创建新版本后可调", revealed: "开发期已揭示" },
  { key: "validation", short: "验证", title: "锁定候选并查看验证", editable: "仅展示筛选", revealed: "开发期、验证期已揭示" },
  { key: "blind", short: "盲测", title: "决定是否开启最终盲测", editable: "仅展示筛选", revealed: "盲测仍封存" },
  { key: "challenger", short: "晋级", title: "结论与人工晋级", editable: "仅模拟账户起始日", revealed: "全部样本已揭示" },
];

const REGIMES = [
  ["上涨 · 低波", "418 日 / 8 段", "+4.8%", "84", "通过"],
  ["上涨 · 高波", "347 日 / 11 段", "+2.1%", "57", "通过"],
  ["中性 · 低波", "98 日 / 9 段", "−0.6%", "19", "观察"],
  ["中性 · 高波", "106 日 / 16 段", "+0.3%", "22", "观察"],
  ["下跌 · 低波", "13 日 / 4 段", "—", "1", "证据不足"],
  ["下跌 · 高波", "21 日 / 1 段", "—", "3", "证据不足"],
];

const VERSIONS = [
  { version: "v1", strategy: "short_reversal_5d_v1", status: "未入选", detail: "50 bps 后 −1.8% · 换手过高" },
  { version: "v2", strategy: "short_reversal_20d_v1", status: "验证候选", detail: "25 bps 后 +3.4% · 238 笔成交" },
];

export function CandidateResearchPrototype({ initialVariant, initialStep }: {
  initialVariant: PrototypeVariant; initialStep: PrototypeStep;
}) {
  const [step, setStepState] = useState(initialStep);
  const current = STEPS.find(item => item.key === step)!;

  function setStep(next: PrototypeStep) {
    setStepState(next);
    const url = new URL(window.location.href);
    url.searchParams.set("step", next);
    window.history.replaceState(null, "", url);
  }

  const props = { step, current, setStep };
  return <>
    {initialVariant === "A" && <VariantA {...props} />}
    {initialVariant === "B" && <VariantB {...props} />}
    {initialVariant === "C" && <VariantC {...props} />}
    <PrototypeSwitcher variants={VARIANTS} current={initialVariant} />
  </>;
}

type VariantProps = {
  step: PrototypeStep;
  current: (typeof STEPS)[number];
  setStep: (step: PrototypeStep) => void;
};

function PrototypeHead({ title }: { title: string }) {
  return <>
    <div className="crumb"><Link href="/accounts/research">指定区间回测</Link> / 05 候选策略研究 Mock</div>
    <div className="head">
      <div><h1>{title} <span className="badge warn">PROTOTYPE</span></h1>
        <div className="meta"><span>示例数据，不调用 API，不会创建实验或账户</span><span>实验 EXP-05-017</span></div>
      </div>
      <Link className="btn" href="/accounts/research">返回 04 研究页</Link>
    </div>
  </>;
}

function StageTabs({ step, setStep }: Pick<VariantProps, "step" | "setStep">) {
  return <div className={styles.stageTabs} role="group" aria-label="查看研究阶段">
    {STEPS.map((item, index) => <button type="button" key={item.key} aria-pressed={item.key === step}
      onClick={() => setStep(item.key)}><span>{index + 1}</span>{item.short}</button>)}
  </div>;
}

function VariantA({ step, current, setStep }: VariantProps) {
  return <section className="page">
    <PrototypeHead title="候选策略研究 · 逐步向导" />
    <StageTabs step={step} setStep={setStep} />
    <div className={styles.guideGrid}>
      <aside className={styles.rail}>
        <p className={styles.eyebrow}>研究进度</p>
        {STEPS.map((item, index) => <button type="button" key={item.key} className={item.key === step ? styles.activeRail : ""}
          onClick={() => setStep(item.key)}><i>{index + 1}</i><span><b>{item.short}</b><small>{item.title}</small></span></button>)}
      </aside>
      <main className={styles.workspace}>
        <div className={styles.workspaceHead}><div><p className={styles.eyebrow}>当前任务</p><h2>{current.title}</h2></div>
          <span className={`badge ${step === "draft" || step === "development" ? "warn" : "ok"}`}>{current.editable}</span></div>
        {step === "draft" && <DraftForm />}
        {step === "development" && <DevelopmentVersions />}
        {step === "validation" && <ValidationEvidence compact />}
        {step === "blind" && <BlindGate />}
        {step === "challenger" && <Promotion />}
        <StepAction step={step} setStep={setStep} />
      </main>
      <aside className={styles.summary}>
        <p className={styles.eyebrow}>研究契约</p>
        <SummaryRows step={step} />
        <div className={styles.lockBox}><b>{step === "draft" ? "尚未锁定" : "配置指纹 7f2a…91c4"}</b>
          <span>{current.revealed}</span></div>
        <StateInspector step={step} />
      </aside>
    </div>
  </section>;
}

function VariantB({ step, current, setStep }: VariantProps) {
  return <section className={`page ${styles.pipelinePage}`}>
    <PrototypeHead title="候选策略研究 · 实验流水线" />
    <div className={styles.pipelineIntro}>
      <div><p className={styles.eyebrow}>策略谱系</p><h2>短期反转 · EXP-05-017</h2></div>
      <div className="badges"><span className="badge">2 个版本</span><span className="badge down">1 个淘汰</span><span className="badge ok">1 个验证候选</span></div>
    </div>
    <div className={styles.pipeline}>
      {STEPS.map((item, index) => <button type="button" key={item.key} onClick={() => setStep(item.key)}
        className={item.key === step ? styles.pipelineActive : ""}>
        <span>{String(index + 1).padStart(2, "0")}</span><b>{item.short}</b><small>{item.key === step ? "正在查看" : stageStatus(item.key, step)}</small>
      </button>)}
    </div>
    <div className={styles.board}>
      <section className={styles.lineage}>
        <div className={styles.sectionTitle}><div><p className={styles.eyebrow}>所有尝试均保留</p><h2>版本谱系</h2></div><button className="btn" disabled={step !== "development"}>＋ 从 v2 创建新版本</button></div>
        <DevelopmentVersions />
        <div className={styles.audit}><span>实验次数</span><b>2 / 2</b><span>验证数据</span><b>{step === "draft" || step === "development" ? "封存" : "已揭示"}</b><span>盲测数据</span><b>{step === "challenger" ? "已揭示" : "封存"}</b></div>
      </section>
      <section className={styles.gatePanel}>
        <p className={styles.eyebrow}>当前 Gate</p><h2>{current.title}</h2>
        <p className={styles.bigCopy}>{gateCopy(step)}</p>
        {step === "validation" && <ValidationMini />}
        {step === "blind" && <BlindGate />}
        {step === "challenger" && <Promotion />}
        {(step === "draft" || step === "development") && <SummaryRows step={step} />}
        <StepAction step={step} setStep={setStep} />
      </section>
    </div>
    <StateInspector step={step} />
  </section>;
}

function VariantC({ step, current, setStep }: VariantProps) {
  return <section className={`page ${styles.cockpitPage}`}>
    <PrototypeHead title="候选策略研究 · 证据驾驶舱" />
    <StageTabs step={step} setStep={setStep} />
    <div className={styles.cockpit}>
      <aside className={styles.candidates}>
        <p className={styles.eyebrow}>候选家族</p>
        <Candidate name="短期反转" version="20d v1" status="验证候选" selected />
        <Candidate name="长趋势" version="SMA200 v1" status="开发中" />
        <Candidate name="横截面动量" version="6-1 v1" status="尚未运行" />
        <button className="btn">＋ 新建候选研究</button>
      </aside>
      <main className={styles.evidence}>
        <div className={styles.sectionTitle}><div><p className={styles.eyebrow}>{current.revealed}</p><h2>短期反转 · 证据矩阵</h2></div>
          <div className="badges"><span className="badge ok">验证门槛通过</span><span className="badge">形势仅诊断</span></div></div>
        <div className="kpis three">
          <div className="kpi"><div className="l">25 bps 后超额</div><div className="v up">+3.4%</div><div className="s">验证期</div></div>
          <div className="kpi"><div className="l">最大回撤</div><div className="v down">−8.7%</div><div className="s">门槛 −12%</div></div>
          <div className="kpi"><div className="l">成交数</div><div className="v">238</div><div className="s">最低 100</div></div>
        </div>
        <RegimeMatrix />
        <div className={styles.disclaimer}>市场形势只用于分组观察，不会阻止开仓；下跌形势样本不足，不能据此声明策略适合或不适合熊市。</div>
      </main>
      <aside className={styles.decision}>
        <p className={styles.eyebrow}>决策面板</p><h2>{current.title}</h2>
        <SummaryRows step={step} />
        <StepAction step={step} setStep={setStep} />
        <StateInspector step={step} />
      </aside>
    </div>
  </section>;
}

function DraftForm() {
  return <div className={styles.mockForm}>
    <label>策略家族<select className="input" defaultValue="reversal"><option value="reversal">短期反转</option><option>长趋势／绝对动量</option><option>横截面动量</option></select></label>
    <label>预注册版本<select className="input" defaultValue="20d"><option value="5d">short_reversal_5d_v1</option><option value="20d">short_reversal_20d_v1</option></select></label>
    <label>排序窗口<div className="affix"><input className="input" type="number" defaultValue="20"/><span>交易日</span></div></label>
    <label>目标持有期<div className="affix"><input className="input" type="number" defaultValue="10"/><span>交易日</span></div></label>
    <label>选择弱势分位<div className="affix"><input className="input" type="number" defaultValue="10"/><span>%</span></div></label>
    <label>目标持仓数<div className="affix"><input className="input" type="number" defaultValue="20"/><span>只</span></div></label>
    <label>开发／验证／盲测<select className="input"><option>3 年 / 1 年 / 最近 1 年</option></select></label>
    <label>TOPIX 形势<select className="input"><option>仅用于诊断，不干预交易</option><option>禁止某些形势开仓（新策略版本）</option></select></label>
  </div>;
}

function DevelopmentVersions() {
  return <div className={styles.versionList}>{VERSIONS.map((item, index) => <article key={item.version}>
    <div className={styles.versionNode}>{item.version}</div><div><div className={styles.versionTitle}><b>{item.strategy}</b>
      <span className={`badge ${index ? "ok" : "down"}`}>{item.status}</span></div><p>{item.detail}</p>
      <small>{index ? "父版本 v1 · 只使用开发期" : "最初冻结版本"}</small></div>
  </article>)}</div>;
}

function ValidationEvidence({ compact = false }: { compact?: boolean }) {
  return <div className={styles.validationBlock}>
    <div className="kpis three">
      <div className="kpi"><div className="l">净超额收益</div><div className="v up">+3.4%</div><div className="s">25 bps 后</div></div>
      <div className="kpi"><div className="l">最大回撤</div><div className="v down">−8.7%</div><div className="s">门槛 −12%</div></div>
      <div className="kpi"><div className="l">成交数</div><div className="v">238</div><div className="s">最低 100</div></div>
    </div>
    {!compact && <RegimeMatrix />}
    <div className={styles.checks}><span>✓ 成本压力通过</span><span>✓ 延迟一天仍为正</span><span>✓ 非少数交易驱动</span><span>△ 熊市证据不足</span></div>
  </div>;
}

function ValidationMini() {
  return <div className={styles.miniMetrics}><div><span>25 bps 后</span><b className="up">+3.4%</b></div><div><span>最大回撤</span><b className="down">−8.7%</b></div><div><span>成交数</span><b>238</b></div></div>;
}

function BlindGate() {
  return <div className={styles.blindGate}>
    <span className={styles.seal}>封</span><div><b>2025-09-30 — 2026-09-29</b><p>该区间尚未计算、查看或导出。开启后，本策略版本不能再次运行正式盲测。</p></div>
    <ul><li>验证硬门槛全部通过</li><li>配置指纹已锁定</li><li>没有未处理的数据警告</li></ul>
  </div>;
}

function Promotion() {
  return <div className={styles.promotion}><div className={styles.verdict}>PASS</div><div><h3>盲测通过预注册门槛</h3>
    <p>25 bps 后净超额 +2.2%，最大回撤 −9.4%，143 笔成交。下跌形势仍为证据不足。</p></div></div>;
}

function RegimeMatrix() {
  return <div className="scroll"><table aria-label="TOPIX 市场形势证据矩阵"><thead><tr><th>TOPIX 形势</th><th>覆盖</th><th>净超额</th><th>成交</th><th>结论</th></tr></thead>
    <tbody>{REGIMES.map(row => <tr key={row[0]}>{row.map((cell, index) => <td key={cell} className={index === 2 ? (cell.startsWith("+") ? "up" : cell.startsWith("−") ? "down" : "") : ""}>{cell}</td>)}</tr>)}</tbody></table></div>;
}

function Candidate({ name, version, status, selected = false }: { name: string; version: string; status: string; selected?: boolean }) {
  return <button type="button" className={selected ? styles.selectedCandidate : ""}><span><b>{name}</b><small>{version}</small></span><em>{status}</em></button>;
}

function SummaryRows({ step }: { step: PrototypeStep }) {
  const locked = step !== "draft";
  return <dl className={styles.summaryRows}>
    <div><dt>策略版本</dt><dd>{step === "draft" ? "草稿" : "short_reversal_20d_v1"}</dd></div>
    <div><dt>组合</dt><dd>PeriodicTopN · 等权 20</dd></div>
    <div><dt>执行</dt><dd>次日开盘 · ADV20 1%</dd></div>
    <div><dt>成本</dt><dd>10 / 25 / 50 bps</dd></div>
    <div><dt>TOPIX 形势</dt><dd>仅诊断</dd></div>
    <div><dt>参数状态</dt><dd>{locked ? "已锁定" : "可编辑"}</dd></div>
  </dl>;
}

function StepAction({ step, setStep }: Pick<VariantProps, "step" | "setStep">) {
  const actions: Record<PrototypeStep, { label: string; next?: PrototypeStep; note: string }> = {
    draft: { label: "检查并冻结开发方案", next: "development", note: "尚未查看任何收益，可修改全部字段" },
    development: { label: "锁定 v2 进入验证", next: "validation", note: "调整参数会创建 v3，不会覆盖失败版本" },
    validation: { label: "验证通过，前往盲测决策", next: "blind", note: "正式候选已经锁定，不能再调参" },
    blind: { label: "开启一次性最终盲测", next: "challenger", note: "不可逆：将首次揭示最近一年结果" },
    challenger: { label: "人工晋级为 Paper Challenger", note: "创建独立模拟账户，不替换 champion" },
  };
  const action = actions[step];
  return <div className={styles.primaryAction}><span>{action.note}</span><button type="button" className="btn primary lg" onClick={() => action.next && setStep(action.next)}>{action.label}</button></div>;
}

function StateInspector({ step }: { step: PrototypeStep }) {
  const index = STEPS.findIndex(item => item.key === step);
  const state = {
    stage: step,
    experiment: "EXP-05-017",
    selected_version: step === "draft" ? null : "short_reversal_20d_v1",
    parameters_editable: step === "draft" || step === "development",
    development_revealed: index >= 1,
    validation_revealed: index >= 2,
    blind_test_revealed: index >= 4,
    regime_policy: "diagnostic_only",
  };
  return <details className={styles.inspector}><summary>查看 Mock 状态</summary><pre>{JSON.stringify(state, null, 2)}</pre></details>;
}

function stageStatus(item: PrototypeStep, current: PrototypeStep) {
  const itemIndex = STEPS.findIndex(step => step.key === item);
  const currentIndex = STEPS.findIndex(step => step.key === current);
  return itemIndex < currentIndex ? "已完成" : itemIndex > currentIndex ? "未开始" : "正在查看";
}

function gateCopy(step: PrototypeStep) {
  return ({
    draft: "先把规则、样本和通过门槛写清楚，再看第一条收益曲线。",
    development: "允许迭代，但每次修改都产生新版本，失败结果同样进入谱系。",
    validation: "候选已经锁定。验证数据只能用于筛选，不能再用于调整这个版本。",
    blind: "这是最后一道不可逆的门：最近一年结果只为冻结版本揭示一次。",
    challenger: "通过只代表可以开始纸面观察；是否晋级仍由人决定。",
  } as const)[step];
}
