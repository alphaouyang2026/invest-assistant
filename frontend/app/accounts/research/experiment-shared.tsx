import type { Schemas } from "@/lib/api/client";
import { experimentReason, experimentReasonTone, trainerLabel } from "@/lib/labels";

/** What the model experiment's views share: how its models, replays and hashes are named on screen. */

type Contract = Schemas["ExperimentContract"];
type Replay = Pick<Schemas["ReplaySummary"], "model" | "scenario" | "costs">;

/** "model" → 主模型, "baseline_2" → 基线 2. */
export const modelName = (key: string) => (key === "model" ? "主模型" : key.startsWith("baseline_") ? `基线 ${key.slice(9)}` : key);

/** The trainer a model key stands for, from the contract. */
export const trainerOf = (contract: Contract, key: string) =>
  key === "model" ? contract.model.trainer : contract.baselines[Number(key.slice(9)) - 1]?.trainer ?? key;

/** "主模型 · Ridge 回归（ridge_v1）". */
export const modelLabel = (contract: Contract, key: string) => `${modelName(key)} · ${trainerLabel(trainerOf(contract, key))}`;

/** "0.0025" → "25 bps". */
export const bps = (slippage: string | number) => `${Number((Number(slippage) * 10000).toPrecision(12))} bps`;

/** "主模型 · 基础成本" / "主模型 · 压力 25 bps". */
export const replayName = (r: Replay) =>
  `${modelName(r.model)} · ${r.scenario === "base" ? "基础成本" : `压力 ${bps(r.costs.slippage)}`}`;

/** The first twelve hex digits, enough to tell two apart on screen. */
export const shortHash = (hash: string | null | undefined) => (hash ? hash.replace(/^sha256:/, "").slice(0, 12) : "—");

export const minute = (iso: string) => iso.slice(0, 16).replace("T", " ");

/** Why a holding or an order is what it is, as badges; `capped` marks a buy cut down to the ADV20 cap. */
export function Reasons({ codes, capped }: { codes: unknown; capped?: unknown }) {
  const list = Array.isArray(codes) ? codes.map(String) : [];
  return <span className="badges">
    {list.map(code => <span key={code} className={`badge ${experimentReasonTone(code)}`}>{experimentReason(code)}</span>)}
    {capped === "adv20" && <span className="badge warn">按成交额上限压缩</span>}
  </span>;
}

/** 0.000384 → "0.038%": order sizes against ADV20 are small. */
export const smallPercent = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : `${Number((value * 100).toPrecision(3))}%`;
