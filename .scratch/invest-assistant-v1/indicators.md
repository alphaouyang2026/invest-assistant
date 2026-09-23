# 03 用到的指标

- 日期：2026-09-23
- 范围：[ticket 03](issues/03-indicators-strategies-signals.md) 的指标模块（设计 [§5](spec.md#5-指标模块)）与两个策略（[§6.3](spec.md#63-trend-pullback-v1)、[§6.4](spec.md#64-技术评级-v1)）
- 用途：实现时逐项对照；「待确认」一节列出的问题要在写代码前查清，查清后改写本文

所有价格都是**研究价格**（`MarketFrame` 的 `OPEN` / `HIGH` / `LOW` / `CLOSE` / `VOLUME`）。每个函数都接受一只证券的 `Series` 或宽表（行是交易日、列是证券代码），按列计算；NaN 当作「这一天没有 K 线」（设计 §5）。

## 1. 总表

指标模块共 19 种对外函数，另有 4 个内部辅助计算。

| # | 指标 | Pine | 输入 | 本系统用到的参数 | Trend-Pullback | 技术评级 |
|---|---|---|---|---|---|---|
| 1 | SMA 简单均线 | `ta.sma` | close | 10/20/30/50/100/200 | | ✓ |
| 2 | EMA 指数均线 | `ta.ema` | close | 20、60；10/20/30/50/100/200 | ✓ | ✓ |
| 3 | RMA Wilder 平滑 | `ta.rma` | 任意序列 | 14（RSI/ATR/DMI 内部） | 间接 | 间接 |
| 4 | RSI | `ta.rsi` | close | 14 | ✓ | ✓ |
| 5 | ATR | `ta.atr` | high, low, close | 14 | ✓ | |
| 6 | DMI：+DI / −DI / ADX | `ta.dmi` | high, low, close | 14, 14 | ✓ | ✓ |
| 7 | Hull MA | `ta.hma` | close | 9 | | ✓ |
| 8 | VWMA 成交量加权均线 | `ta.vwma` | close, volume | 20 | | ✓ |
| 9 | 一目均衡表 | —（Donchian 中值组合） | high, low | 9 / 26 / 52 | | ✓ |
| 10 | Stochastic | `ta.stoch` + `ta.sma` | high, low, close | 14, 3, 3 | | ✓ |
| 11 | CCI | `ta.cci` | 见待确认 | 20 | | ✓ |
| 12 | Awesome Oscillator | — | high, low | 5, 34 | | ✓ |
| 13 | Momentum | `ta.mom` | close | 10 | | ✓ |
| 14 | MACD | `ta.macd` | close | 12, 26, 9 | | ✓ |
| 15 | Stochastic RSI | — | close | 3, 3, 14, 14 | | ✓ |
| 16 | Williams %R | `ta.wpr` | high, low, close | 14 | | ✓ |
| 17 | Bull Bear Power | — | high, low, close | 13 | | ✓ |
| 18 | Ultimate Oscillator | — | high, low, close | 7, 14, 28 | | ✓ |
| 19 | N 日最高收盘价 | `ta.highest` | close | —— | | |

内部辅助（不对外）：WMA（`ta.wma`，Hull MA 用）、N 日最高 / 最低价（`ta.highest` / `ta.lowest`，Stochastic、Williams %R、一目均衡表用）、True Range（`ta.tr`，ATR、DMI、UO 用）、`hl2 = (high + low) / 2`（AO 用）。

第 19 项「N 日最高收盘价」目前两个策略都没有用到——跟踪止损用的是「开仓以来最高收盘价」，由策略按开仓日自己算。见待确认第 7 条。

## 2. 公式

记号：`x[1]` 是前一根 K 线的值；`n` 是周期。

### 平滑类

- **SMA**：最近 n 根的算术平均；不足 n 根为 NaN。
- **EMA**：`α = 2 / (n + 1)`，`EMA[t] = α·x[t] + (1 − α)·EMA[t−1]`。起点见待确认第 1 条。
- **RMA**：`α = 1 / n`，递推同 EMA；起点是前 n 个值的简单平均，之前为 NaN（Pine 参考手册的 `pine_rma` 示例）。
- **WMA**（内部）：权重 n, n−1, …, 1 的加权平均，最新一根权重最大。

### Wilder 系

- **RSI(14)**：`up = RMA(max(Δclose, 0), 14)`，`down = RMA(max(−Δclose, 0), 14)`；`RSI = 100 − 100 / (1 + up/down)`。
  - 分母为零：`down = 0` 时 RSI = 100（包括 up 也为 0 的情形），否则 `up = 0` 时 RSI = 0——按 Pine 手册 `ta.rsi` 示例的判断顺序，实现时再对照一次。
- **True Range**（内部）：`max(high − low, |high − close[1]|, |low − close[1]|)`；第一根没有 `close[1]` 时取 `high − low`。
- **ATR(14)**：`RMA(TR, 14)`。
- **DMI(14, 14)**：
  - `up = high − high[1]`，`down = low[1] − low`；
  - `+DM = up > down 且 up > 0 ? up : 0`，`−DM = down > up 且 down > 0 ? down : 0`；
  - `+DI = 100 · RMA(+DM, 14) / RMA(TR, 14)`，`−DI` 同理；
  - `ADX = 100 · RMA(|+DI − −DI| / s, 14)`，`s = +DI + −DI`，`s = 0` 时按 1 算（Pine `ta.dmi` 示例）。
  - 三次 RMA 叠加，ADX 要约 2n 根之后才有值。

### 均线类（技术评级）

- **Hull MA(9)**：`WMA(2·WMA(close, n/2) − WMA(close, n), √n 取整)`；n = 9 时 n/2 与 √n 的取整见待确认第 5 条。
- **VWMA(20)**：`SMA(close·volume, 20) / SMA(volume, 20)`；20 天成交量全为 0 时为 NaN。
- **一目均衡表(9, 26, 52)**：`中值(k) = (k 日最高价 + k 日最低价) / 2`；
  - 转换线 = 中值(9)，基准线 = 中值(26)；
  - 先行带 A = (转换线 + 基准线) / 2，先行带 B = 中值(52)；
  - 先行带在图上向前平移 26 根；评级比较的是哪一天的先行带见待确认第 4 条。

### 振荡器类（技术评级）

- **Stochastic(14, 3, 3)**：`raw = 100 · (close − 14 日最低) / (14 日最高 − 14 日最低)`；`%K = SMA(raw, 3)`，`%D = SMA(%K, 3)`。14 日最高 = 最低（一字横盘）时 raw 为 NaN——需要显式规定，见待确认第 8 条。
- **CCI(20)**：`tp` 为输入序列，`CCI = (tp − SMA(tp, 20)) / (0.015 · 平均绝对偏差(tp, 20))`；平均绝对偏差为 0 时同上待规定。
- **Awesome Oscillator**：`SMA(hl2, 5) − SMA(hl2, 34)`。
- **Momentum(10)**：`close − close[10]`。
- **MACD(12, 26, 9)**：`MACD = EMA(close, 12) − EMA(close, 26)`，`Signal = EMA(MACD, 9)`。
- **Stochastic RSI(3, 3, 14, 14)**：`r = RSI(close, 14)`，`raw = 100 · (r − 14 日最低 r) / (14 日最高 r − 14 日最低 r)`，`K = SMA(raw, 3)`，`D = SMA(K, 3)`。
- **Williams %R(14)**：`−100 · (14 日最高 − close) / (14 日最高 − 14 日最低)`，取值 −100 到 0。
- **Bull Bear Power(13)**：`Bull = high − EMA(close, 13)`，`Bear = low − EMA(close, 13)`。
- **Ultimate Oscillator(7, 14, 28)**：`BP = close − min(low, close[1])`，`TR` 同上；`A_k = ΣBP / ΣTR`（最近 k 根）；`UO = 100 · (4·A7 + 2·A14 + A28) / 7`。

## 3. Trend-Pullback v1 怎么用

预热期 180（EMA60 的 3 倍）。全部数字都可由账户参数覆盖。

| 用在哪 | 条件 | 用到的指标 |
|---|---|---|
| 入场 ① | `EMA20[t] > EMA60[t]` | EMA 20、60 |
| 入场 ② | `close[t] > EMA60[t]` | EMA 60 |
| 入场 ③ | `+DI14[t] > −DI14[t]` | DMI |
| 入场 ④ | `ADX14[t] > 20` 且 `ADX14[t] ≥ ADX14[t−1]` | DMI |
| 入场 ⑤ | `RSI14[t−1] ≤ 30` 且 `RSI14[t] > 30` | RSI |
| 排序值 | `ADX14[t] / 100` | DMI |
| 退出 1 跟踪止损 | `close[t] ≤ 开仓以来最高收盘 − 2 × ATR14[t]` | ATR、开仓以来最高收盘 |
| 退出 2 趋势失效 | `EMA20 ≤ EMA60` 或 `+DI14 ≤ −DI14` | EMA、DMI |
| 退出 3 超买回落 | `RSI14[t] ≥ 70` 且 `RSI14[t] < RSI14[t−1]` | RSI |
| 退出 4 时间退出 | 已持有 5 个交易日 | 持有天数（不是指标） |

合计 7 条指标线：EMA20、EMA60、+DI14、−DI14、ADX14、RSI14、ATR14。

## 4. 技术评级 v1 怎么用

预热期 260。每项给出 +1（买）、−1（卖）或 0（中性）。以下规则逐字取自 TradingView 官方页面。

### 均线组（15 项）

| 项 | 买 +1 | 卖 −1 |
|---|---|---|
| SMA 10/20/30/50/100/200（6 项） | 均线 < 收盘价 | 均线 > 收盘价 |
| EMA 10/20/30/50/100/200（6 项） | 均线 < 收盘价 | 均线 > 收盘价 |
| Hull MA 9 | 均线 < 收盘价 | 均线 > 收盘价 |
| VWMA 20 | 均线 < 收盘价 | 均线 > 收盘价 |
| 一目均衡表 | 先行带 A > 先行带 B、基准线 > 先行带 A、转换线 > 基准线、收盘价 > 转换线，四条同时成立 | 四条全部反过来 |

均线等于收盘价，或一目均衡表两边都不成立，为 0。

### 振荡器组（11 项）

| 项 | 买 +1 | 卖 −1 |
|---|---|---|
| RSI 14 | RSI < 30 且高于前一天 | RSI > 70 且低于前一天 |
| Stochastic 14,3,3 | %K < 20、%D < 20、%K > %D | %K > 80、%D > 80、%K < %D |
| CCI 20 | CCI < −100 且高于前一天 | CCI > 100 且低于前一天 |
| ADX 14 | +DI > −DI、ADX > 20、ADX 高于前一天 | +DI < −DI、ADX > 20、ADX 低于前一天 |
| AO | 上穿 0；或连续两根在 0 之上且拐头向上 | 下穿 0；或连续两根在 0 之下且拐头向下 |
| Momentum 10 | 高于前一天 | 低于前一天 |
| MACD 12,26,9 | MACD > Signal | MACD < Signal |
| Stoch RSI 3,3,14,14 | 下跌趋势中，K < 20、D < 20、K > D | 上涨趋势中，K > 80、D > 80、K < D |
| Williams %R 14 | %R < −80 且高于前一天 | %R > −20 且低于前一天 |
| Bull Bear Power 13 | 上涨趋势中，Bear < 0 且高于前一天 | 下跌趋势中，Bull > 0 且低于前一天 |
| UO 7,14,28 | UO > 70 | UO < 30 |

其余情况为 0。

### 合成与使用

- 均线评级 = 15 项的平均；振荡器评级 = 11 项的平均；总评 = 两者的平均（TradingView「Technical Ratings」脚本说明：默认两组各占 50%）。
- 五档：`> 0.5` 强烈买入、`(0.1, 0.5]` 买入、`[−0.1, 0.1]` 中性、`[−0.5, −0.1)` 卖出、`< −0.5` 强烈卖出。
- 入场：总评 > 0.5，排序值 = 总评；持仓退出：总评 < −0.1。
- 某一项当天算不出（例如 NaN）时怎么计入平均，见待确认第 3 条。

## 5. 待确认

写代码前要查清的问题。Pine 源码可以在 TradingView 里打开内置「Technical Ratings」脚本或 `TechnicalRating` 库查看——网页上看不到源码。

1. **EMA 的起点**：Pine 参考手册 `ta.ema` 的示例用**第一个值**做起点（`na(sum[1]) ? src : …`），而 `ta.rma` 用前 n 个值的简单平均。设计 §5 原先写两者都用简单平均，这一点与手册示例不符。还要确认内置 `ta.ema` 的实际输出是否与示例一致（例如用 TradingView 图表导出的数值比对一段）。
2. **总评的合成**：说明文字是「两组平均、默认各 50%」，需要在源码里确认，以及某一组整组算不出时怎么处理。
3. **单项算不出时**：某一项因 NaN 没有值时，是按 0 计入平均，还是从分母里去掉。
4. **一目均衡表比较哪一天的先行带**：当天算出的先行带，还是 26 根之前算出、平移到当天的那一条。
5. **Hull MA 9 的取整**：`n/2 = 4.5` 与 `√9 = 3` 在 Pine 里怎么取整。
6. **「上涨趋势 / 下跌趋势」的定义**：Stoch RSI 和 Bull Bear Power 的规则都用到了，官方页面没有写，要看源码。
7. **N 日最高收盘价**：两个策略都没用到，是删掉，还是说明留给谁用。
8. **振荡器的分母为零**：Stochastic、Stoch RSI、Williams %R 的最高 = 最低，CCI 的平均偏差为 0，VWMA 的成交量为 0——各自取什么值，要显式规定并写进测试。
9. **CCI 的输入**：用收盘价还是 `hlc3`。

## 来源

- TradingView，Technical Ratings 说明：<https://www.tradingview.com/support/solutions/43000614331-technical-ratings/>
- TradingView，内置脚本「Technical Ratings」：<https://www.tradingview.com/script/Jdw7wW2g-Technical-Ratings/>
- TradingView，`TechnicalRating` 库：<https://www.tradingview.com/script/jDWyb5PG-TechnicalRating/>
- Pine Script 参考手册（`ta.ema`、`ta.rma`、`ta.rsi`、`ta.dmi` 的示例代码）：<https://www.tradingview.com/pine-script-reference/v5/>
