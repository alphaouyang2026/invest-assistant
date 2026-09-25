/** What the backend's codes mean on screen. */

export const STRATEGIES = [
  { name: "trend_pullback_v1", label: "Trend-Pullback v1" },
  { name: "technical_rating_v1", label: "技术评级 v1" },
] as const;

export type StrategyName = (typeof STRATEGIES)[number]["name"];

export const DEFAULT_STRATEGY: StrategyName = "trend_pullback_v1";

const MARKETS: Record<string, string> = { "0111": "Prime", "0112": "Standard", "0113": "Growth" };

export const market = (code: string | null | undefined) => (code ? (MARKETS[code] ?? code) : "已退市");

const REASONS: Record<string, string> = {
  // Trend-Pullback v1
  ema_uptrend: "EMA20 在 EMA60 之上，收盘价在 EMA60 之上",
  dmi_positive: "+DI 高于 −DI",
  adx_strengthening: "ADX 高于 20 且没有走弱",
  rsi_recovery: "RSI 从 30 以下回升",
  trailing_stop: "跟踪止损",
  trend_broken: "趋势失效",
  overbought_fade: "超买回落",
  time_exit: "持有期满",
  // 技术评级 v1
  strong_buy: "强烈买入",
  buy: "买入",
  neutral: "中性",
  sell: "卖出",
  strong_sell: "强烈卖出",
};

export const reason = (code: string) => REASONS[code] ?? code;

export const strategyLabel = (name: string) => STRATEGIES.find((s) => s.name === name)?.label ?? name;

/** 0.24918 → "24.92%"; null → "—". */
export const percent = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : `${(value * 100).toFixed(2)}%`;

export const ORDER_KINDS: Record<string, string> = {
  buy: "买入",
  sell: "卖出",
  split_adjustment: "拆合股调整",
  delisting_settlement: "退市结清",
};

export const ORDER_STATUSES: Record<string, string> = {
  pending: "待成交",
  filled: "成交",
  expired: "过期",
  skipped: "放弃",
};

const OUTCOMES: Record<string, string> = {
  untradable: "停牌或无成交",
  limit_down_open: "开盘跌停，卖不掉",
  limit_up_open: "开盘涨停，买不到",
  insufficient_cash: "现金不足",
  lot_unaffordable: "买不起一手",
  delisted: "已退市",
  split_rounding: "拆合股后不足一手",
};

export const outcome = (code: string | null | undefined) => (code ? (OUTCOMES[code] ?? code) : "");
