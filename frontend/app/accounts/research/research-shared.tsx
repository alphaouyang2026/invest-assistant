import type { Schemas } from "@/lib/api/client";
import { yen } from "@/lib/format";

/** What the manual runs and the market-interval batches both show. */
export const STATES = { queued: "排队中", running: "运行中", completed: "已完成", failed: "失败" };
export const BATCH_STATES = { ...STATES, partial: "部分完成" };

export const message = (error: unknown) => {
  if (error && typeof error === "object" && "detail" in error && typeof error.detail === "string") return error.detail;
  return "请求失败，请检查网络和后端服务后重试";
};

type Config = Pick<Schemas["ResearchConfig"], "name" | "portfolio_rules" | "costs">;

export function Configuration({ config }: { config: Config }) {
  const rules = config.portfolio_rules;
  return <p className="meta">来源：{config.name} · 初始资金 ¥{yen(Number(rules.initial_cash))} ·
    最多 {String(rules.max_positions)} 只 · 单股上限 {Number(rules.max_weight) * 100}% ·
    现金底线 {Number(rules.cash_floor) * 100}% · 手续费率 {Number(config.costs.commission_rate) * 100}% ·
    最低手续费 ¥{config.costs.commission_min} · 每边滑点 {Number(config.costs.slippage) * 100}%</p>;
}
