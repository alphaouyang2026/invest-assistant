import type { Schemas } from "@/lib/api/client";
import { yen } from "@/lib/format";

/** What the manual runs and the market-interval batches both show. */
export const STATES = { queued: "排队中", running: "运行中", completed: "已完成", failed: "失败" };
export const BATCH_STATES = { ...STATES, partial: "部分完成" };

const FIELDS: Record<string, string> = {
  source_account_id: "来源账户", start_date: "起始日", end_date: "结束日", entry_above: "入场阈值", exit_below: "退出阈值",
  search_from: "搜索起始日", search_to: "搜索结束日", trend: "TOPIX 趋势", volatility: "波动水平",
  discovery_id: "区间发现", interval_ids: "所选区间", request_key: "请求标识",
};

type FieldError = { type?: string; loc?: unknown[]; msg?: string; ctx?: Record<string, unknown> };

/** One of the checks the server's request models make, in words; the server's own text when it is not one of these. */
function fieldMessage({ type, loc, msg, ctx }: FieldError) {
  const path = (loc ?? []).filter(part => part !== "body").map(String);
  const field = FIELDS[path[0]] ?? path.join(".");
  const said = type === "less_than_equal" ? `不能大于 ${ctx?.le}`
    : type === "greater_than_equal" ? `不能小于 ${ctx?.ge}`
    : type === "greater_than" ? `必须大于 ${ctx?.gt}`
    : type === "finite_number" ? "必须是有限数值"
    : type === "float_parsing" || type === "int_parsing" ? "必须是数字"
    : type?.startsWith("date") ? "日期格式不对"
    : type === "too_short" ? "至少要有一项"
    : type === "missing" ? "必须填写"
    : msg ?? "不合规";
  return field ? `${field}：${said}` : said;
}

/** What to tell the user about a failed request: the server's reason, field by field for a 422 from its request models. */
export const message = (error: unknown) => {
  if (error && typeof error === "object" && "detail" in error) {
    const { detail } = error;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      return "输入有误：" + detail.map(item => fieldMessage(item && typeof item === "object" ? item : { msg: String(item) })).join("；");
    }
  }
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
