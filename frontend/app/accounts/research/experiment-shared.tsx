import type { Schemas } from "@/lib/api/client";
import { experimentReason, experimentReasonTone, trainerLabel } from "@/lib/labels";

/** What the model experiment's views share: how its models, replays and hashes are shown. The models' names
 * (主模型, 规则基线 1, …) come from the API, never from their keys. */

type Report = Schemas["ExperimentReport"];
type Replay = Pick<Schemas["ReplaySummary"], "model" | "model_label" | "scenario" | "extra_bps">;

/** "主模型 · Ridge 回归（ridge_v1）": the API's name for a model and what it was trained with. */
export const withTrainer = (label: string, trainer: string | undefined) => (trainer ? `${label} · ${trainerLabel(trainer)}` : label);

/** The trainer behind a replay's model, as the report lists the models. */
export const trainerOf = (report: Report, model: string) => report.models.find(m => m.key === model)?.trainer;

/** "0.0025" → "25 bps". */
export const bps = (slippage: string | number) => `${Number((Number(slippage) * 10000).toPrecision(12))} bps`;

/** "基础成本" / "压力 +25 bps": a replay's cost scenario, a stress one by what it adds to the base slippage. */
export const scenarioName = (r: Pick<Replay, "scenario" | "extra_bps">) =>
  r.scenario === "base" ? "基础成本" : `压力 +${r.extra_bps ?? "?"} bps`;

/** "主模型 · 基础成本" / "主模型 · 压力 +25 bps". */
export const replayName = (r: Replay) => `${r.model_label} · ${scenarioName(r)}`;

/** The first twelve hex digits, enough to tell two apart on screen. */
export const shortHash = (hash: string | null | undefined) => (hash ? hash.replace(/^sha256:/, "").slice(0, 12) : "—");

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
