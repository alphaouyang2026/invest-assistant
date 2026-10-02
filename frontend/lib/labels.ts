/** What the backend's codes mean on screen. */

export const STRATEGIES = [
  {
    name: "trend_pullback_v1",
    label: "Trend-Pullback v1",
    about: "上升趋势中 RSI 从超卖回升就买入，默认最多持有 5 个交易日。按默认参数在历史数据上几乎不会入场",
  },
  {
    name: "technical_rating_v1",
    label: "技术评级 v1",
    about: "复刻 TradingView 技术评级：26 项指标的总评高于入场线就买入，持仓的总评低于退出线就卖出",
  },
  {
    name: "topix_buy_and_hold_v1",
    label: "TOPIX ETF 一直持有",
    about:
      "对照组：只交易 1306（NEXT FUNDS TOPIX 連動型上場投信），能买就买入，之后一直持有、从不卖出。成交、滑点、拆股和其他策略同一套规则；ETF 分配金不入账，每年 7 月落权那天约少算 2%",
  },
] as const;

export type StrategyName = (typeof STRATEGIES)[number]["name"];

export const DEFAULT_STRATEGY: StrategyName = "trend_pullback_v1";

/** Each strategy parameter's name on screen, and what it does. */
export const PARAMS: Record<string, { label: string; hint: string }> = {
  warmup_sessions: { label: "预热期", hint: "交易日；指标需要的历史长度" },
  // Trend-Pullback v1
  ema_fast: { label: "快线 EMA", hint: "周期，交易日" },
  ema_slow: { label: "慢线 EMA", hint: "周期，交易日" },
  di_length: { label: "DI 周期", hint: "+DI / −DI 的周期" },
  adx_length: { label: "ADX 周期", hint: "交易日" },
  adx_min: { label: "ADX 下限", hint: "趋势强度至少要高于它" },
  rsi_length: { label: "RSI 周期", hint: "交易日" },
  rsi_oversold: { label: "RSI 超卖线", hint: "RSI 从它下方回升才入场" },
  rsi_overbought: { label: "RSI 超买线", hint: "RSI 高于它后回落就卖出" },
  atr_length: { label: "ATR 周期", hint: "交易日" },
  atr_multiple: { label: "止损 ATR 倍数", hint: "收盘价跌到最高收盘价减几倍 ATR 就卖出" },
  max_holding_sessions: { label: "最长持有", hint: "交易日，到期卖出" },
  // 技术评级 v1
  entry_above: { label: "入场线", hint: "总评高于它才买入" },
  exit_below: { label: "退出线", hint: "持仓的总评低于它就卖出" },
};

/** J-Quants' market codes; ETFs such as 1306 are listed under その他. */
const MARKETS: Record<string, string> = { "0109": "その他", "0111": "Prime", "0112": "Standard", "0113": "Growth" };

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
  // TOPIX ETF 一直持有
  always_hold: "一直持有（对照组）",
};

export const reason = (code: string) => REASONS[code] ?? code;

/** How a reason is coloured: toward buying `up`, toward selling `down`. */
const REASON_TONES: Record<string, string> = {
  strong_buy: "up", buy: "up", sell: "down", strong_sell: "down",
  trailing_stop: "down", trend_broken: "down", overbought_fade: "down", time_exit: "",
  always_hold: "up",
};

export const reasonTone = (code: string) => REASON_TONES[code] ?? "up";

export const strategyLabel = (name: string) => STRATEGIES.find((s) => s.name === name)?.label ?? name;

/** 0.24918 → "24.92%"; null → "—". */
export const percent = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : `${(value * 100).toFixed(2)}%`;

export const ACCOUNT_STATUSES: Record<string, { label: string; tone: string }> = {
  active: { label: "运行中", tone: "ok" },
  stopped: { label: "已停用", tone: "" },
};

export const ORDER_KINDS: Record<string, string> = {
  buy: "买入",
  sell: "卖出",
  split_adjustment: "拆合股调整",
  delisting_settlement: "退市结清",
};

export const ORDER_STATUSES: Record<string, { label: string; tone: string }> = {
  pending: { label: "待成交", tone: "up" },
  filled: { label: "成交", tone: "ok" },
  expired: { label: "过期", tone: "warn" },
  skipped: { label: "放弃", tone: "" },
};

/** The order history's groups, as `/orders?kind=` takes them. */
export const ORDER_GROUPS = [
  { kind: "all", label: "全部" },
  { kind: "buy", label: "买入" },
  { kind: "sell", label: "卖出" },
  { kind: "skipped", label: "放弃" },
  { kind: "events", label: "账户事件" },
] as const;

export type OrderGroup = (typeof ORDER_GROUPS)[number]["kind"];

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
