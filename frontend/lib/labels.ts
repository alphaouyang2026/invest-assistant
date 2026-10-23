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
  {
    name: "topix_ma_v1",
    label: "TOPIX 均线",
    about:
      "只交易 1306，每个开市日收盘看 TOPIX：收盘高出均线（默认 200 个开市日）超过缓冲带（默认 1%）就买入，低于均线超过缓冲带就全部卖出、持有现金，在缓冲带内（含恰好在门槛上）不改变状态。成交、滑点、拆股和其他策略同一套规则；ETF 分配金不入账",
  },
  {
    name: "topix_momentum_v1",
    label: "TOPIX 动量",
    about:
      "只交易 1306，每月第一个开市日判断，月中建的账户等到下个月才可能买入。判断日收盘看 TOPIX 的过去收益（当天收盘比回看长度个开市日前的收盘涨了多少，默认 252 个开市日，约 12 个月）：为正就买入，为负就全部卖出、持有现金，恰好为 0 不改变状态；月中其他日子不买也不卖。成交、滑点、拆股和其他策略同一套规则；ETF 分配金不入账",
  },
  {
    name: "long_trend_v1",
    label: "长趋势",
    about:
      "05 候选策略，尚未通过研究验证。每月第一个开市日收盘看每只 Prime 股票自己的收盘价和简单均线（默认 200 个开市日）：在均线之上就可买入，离均线越远越优先；持仓收盘不在均线之上就卖出。月中其他日子不买也不卖，月中建的账户等到下个月才可能买入",
  },
  {
    name: "short_reversal_v1",
    label: "短期反转",
    about:
      "05 候选策略，尚未通过研究验证。每个开市日收盘看每只 Prime 股票过去几天的收益（默认 5 个开市日）：下跌的可买入，跌得越多越优先；买入后持满固定天数（默认 5 个开市日）就卖出，不管涨跌。换手高，对成本敏感",
  },
  {
    name: "cross_sectional_momentum_v1",
    label: "横截面动量",
    about:
      "05 候选策略，尚未通过研究验证。每月第一个开市日收盘给所有 Prime 股票按过去收益排名（默认看过去 126 个开市日、跳过最近 21 个，即「6-1」），持有排名最前的几只（最多持有数）；持仓跌出名单就卖出，换成排名更前的，留下的不加不减。月中其他日子不买也不卖",
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
  // TOPIX 均线
  ma_sessions: { label: "均线窗口", hint: "TOPIX 收盘的个数（开市日），含当天；预热期跟着它变" },
  band: { label: "缓冲带", hint: "比例，0.01 表示 1%：TOPIX 高出均线超过它才买入，低于均线超过它才卖出" },
  // TOPIX 动量
  lookback_sessions: {
    label: "回看长度",
    hint: "开市日：TOPIX 当天收盘和这么多个开市日前的收盘相比，就是过去收益；252 约 12 个月。预热期跟着它变，比它多 1（含当天）",
  },
  // 长趋势
  sma_sessions: { label: "均线窗口", hint: "股票收盘的个数（开市日），含当天；预热期跟着它变" },
  // 短期反转（最长持有用上面的 max_holding_sessions）
  return_sessions: {
    label: "回看长度",
    hint: "开市日：股票当天收盘和这么多个开市日前的收盘相比，下跌的才可买入。预热期跟着它变，比它多 1（含当天）",
  },
  // 横截面动量
  momentum_sessions: {
    label: "回看长度",
    hint: "开市日：排名看的是这么多个开市日前到「跳过」那天的收益；126 约 6 个月，252 约 12 个月。预热期跟着它变，比它多 1（含当天）",
  },
  skip_sessions: { label: "跳过最近", hint: "开市日：收益算到这么多个开市日前为止，最近一段不算；21 约 1 个月，0 表示不跳过" },
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
  // TOPIX 均线
  topix_above_ma: "TOPIX 在均线之上",
  topix_near_ma: "TOPIX 在均线附近（缓冲带内）",
  topix_below_ma: "TOPIX 在均线之下",
  // TOPIX 动量
  topix_momentum_up: "TOPIX 过去收益为正",
  topix_momentum_flat: "TOPIX 过去收益为 0",
  topix_momentum_down: "TOPIX 过去收益为负",
  not_check_day: "不是每月判断日",
  // 长趋势
  above_sma: "收盘价在均线之上",
  not_above_sma: "收盘价不在均线之上",
  // 短期反转
  short_term_drop: "过去几天下跌",
  no_short_term_drop: "过去几天没有下跌",
  // 横截面动量
  momentum_rank: "按过去收益排名",
  ranked_out: "跌出持有名单",
};

export const reason = (code: string) => REASONS[code] ?? code;

/** How a reason is coloured: toward buying `up`, toward selling `down`. */
const REASON_TONES: Record<string, string> = {
  strong_buy: "up", buy: "up", sell: "down", strong_sell: "down",
  trailing_stop: "down", trend_broken: "down", overbought_fade: "down", time_exit: "",
  always_hold: "up",
  topix_above_ma: "up", topix_near_ma: "", topix_below_ma: "down",
  topix_momentum_up: "up", topix_momentum_flat: "", topix_momentum_down: "down", not_check_day: "",
  above_sma: "up", not_above_sma: "down",
  short_term_drop: "up", no_short_term_drop: "",
  momentum_rank: "up", ranked_out: "down",
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
  adv20_cap: "按成交额上限压成 0 股",
};

export const outcome = (code: string | null | undefined) => (code ? (OUTCOMES[code] ?? code) : "");

// ---------------------------------------------------------------- model experiments (06a)

/** What score top-N and the portfolio rules say about a holding or an order in a model experiment. */
const EXPERIMENT_REASONS: Record<string, { label: string; tone: string }> = {
  model_rank: { label: "按模型分数排名", tone: "up" },
  not_check_day: { label: "不是决策日", tone: "" },
  model_unavailable: { label: "当天模型没有分数，不开新仓", tone: "" },
  score_missing: { label: "模型可用，但这只没有分数", tone: "down" },
  no_signal: { label: "当天没有可交易日线", tone: "" },
};

export const experimentReason = (code: string) => EXPERIMENT_REASONS[code]?.label ?? reason(code);
export const experimentReasonTone = (code: string) => EXPERIMENT_REASONS[code]?.tone ?? reasonTone(code);

export const DISPOSITIONS: Record<string, string> = { hold: "持有", exit: "卖出" };

/** The kinds of instruction a contract may say its holding rules give: 06a runs the first two and refuses the rest. */
export const ACTIONS: Record<string, string> = {
  disposition: "每只持有还是卖出",
  priority: "排序优先级",
  target_weight: "目标权重",
  gross_exposure: "总敞口",
};

/** What kind of failure stopped a model experiment, and what to do about it. */
export const EXPERIMENT_FAILURES: Record<string, { label: string; hint: string }> = {
  missing_data: { label: "缺数据", hint: "行情、TOPIX 或交易日历还没补齐；补齐后可以重试" },
  input_changed: { label: "行情已变", hint: "读取区间的行情和第一次尝试时不同，重试不会通过；请登记新实验" },
  interrupted: { label: "服务中断", hint: "运行到一半服务停了；可以重试" },
  error: { label: "运行出错", hint: "" },
};

export const EXPERIMENT_EVIDENCE: Record<string, { label: string; tone: string }> = {
  exploratory: { label: "探索性", tone: "warn" },
  insufficient_evidence: { label: "证据不足", tone: "down" },
};

const TRAINERS: Record<string, { label: string; about: string }> = {
  ridge_v1: {
    label: "Ridge 回归",
    about: "用十个特征对未来五日收益做线性回归，每折只在训练段上重新算标准化和系数；分数越高越优先",
  },
  rule_short_reversal_v1: {
    label: "规则：短期反转",
    about: "不训练：分数 = 过去 5 个开市日收益取负，跌得越多越优先，和 05 短期反转的排序一样",
  },
  xgb_rank_ndcg_v1: {
    label: "XGBoost 排序",
    about: "每个交易日的证券算一组，把当天的五日收益分成十档，用梯度提升树学「当天谁排前面」（NDCG 排序）；分数只表示当天的先后，不是收益预测",
  },
};

/** "Ridge 回归（ridge_v1）". */
export const trainerLabel = (name: string) => (TRAINERS[name] ? `${TRAINERS[name].label}（${name}）` : name);
export const trainerAbout = (name: string) => TRAINERS[name]?.about ?? "";

export const TRAINER_PARAMS: Record<string, { label: string; hint: string }> = {
  alpha: { label: "正则强度 alpha", hint: "越大，系数被压得越小；固定一个值，不调参" },
  max_depth: { label: "树的最大深度", hint: "每棵树最多分几层；越深越能刻画特征之间的配合，也越容易记住噪声" },
  n_estimators: { label: "树的棵数", hint: "一共训练多少棵树" },
  learning_rate: { label: "学习率", hint: "每棵树的贡献打多少折；越小越稳，要的树越多" },
  subsample: { label: "每棵树用的样本比例", hint: "每棵树随机抽这么多比例的样本来训练" },
  colsample_bytree: { label: "每棵树用的特征比例", hint: "每棵树随机抽这么多比例的特征" },
  min_child_weight: { label: "叶子最少权重", hint: "一个叶子至少要有这么多样本权重才能再分" },
  pairs_per_sample: { label: "每只比较几对", hint: "排序训练时，每只证券和排在它附近的几只比较先后" },
  seed: { label: "随机种子", hint: "固定它，同样的训练样本才得到同样的模型" },
  threads: { label: "线程数", hint: "固定它，结果才能逐位复现" },
};

/** "树的最大深度 3、树的棵数 100": a parameter set, by its names on screen. */
export const paramSetText = (params: Record<string, unknown>, keys: string[] = Object.keys(params)) =>
  keys.map(key => `${TRAINER_PARAMS[key]?.label ?? key} ${String(params[key])}`).join("、");

export const FEATURES: Record<string, string> = {
  ret_1: "1 日收益",
  ret_5: "5 日收益",
  ret_20: "20 日收益",
  ret_60: "60 日收益",
  dist_sma20: "收盘离 20 日均线多远",
  dist_sma60: "收盘离 60 日均线多远",
  vol_20: "20 日波动率",
  range_20: "20 日平均振幅",
  volume_ratio: "5 日均量 ÷ 20 日均量",
  log_turnover_20: "20 日平均成交额（取对数）",
};

const STAGES: Record<string, string> = {
  fingerprint: "核对研究输入",
  reading: "读取行情",
  features: "计算特征和标签",
  training: "逐折训练、打分",
  replaying: "回放",
  reporting: "生成报告",
};

export const stage = (code: string | undefined) => (code ? (STAGES[code] ?? code) : "等待开始");
