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
