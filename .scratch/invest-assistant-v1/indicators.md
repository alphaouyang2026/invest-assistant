# 03 用到的指标

- 日期：2026-09-23，2026-09-24 查清待确认问题后改写
- 范围：[ticket 03](issues/03-indicators-strategies-signals.md) 的指标模块（设计 [§5](spec.md#5-指标模块)）与两个策略（[§6.3](spec.md#63-trend-pullback-v1)、[§6.4](spec.md#64-技术评级-v1)）
- 用途：实现时逐项对照。技术评级以 TradingView 的 Pine 源码为准，源码存在 [tradingview/](tradingview/) 下；§5 记录每个问题的结论和依据

所有价格都是**研究价格**（`MarketFrame` 的 `OPEN` / `HIGH` / `LOW` / `CLOSE` / `VOLUME`）。每个函数都接受一只证券的 `Series` 或宽表（行是交易日、列是证券代码），按列计算；NaN 当作「这一天没有 K 线」（设计 §5）。

## 1. 总表

指标模块共 18 种对外函数，另有 4 个内部辅助计算。

| # | 指标 | Pine | 输入 | 本系统用到的参数 | Trend-Pullback | 技术评级 |
|---|---|---|---|---|---|---|
| 1 | SMA 简单均线 | `ta.sma` | close | 10/20/30/50/100/200 | | ✓ |
| 2 | EMA 指数均线 | `ta.ema` | close | 20、60；10/20/30/50/100/200；13（Bull Bear Power）、50（趋势） | ✓ | ✓ |
| 3 | RMA Wilder 平滑 | `ta.rma` | 任意序列 | 14（RSI/ATR/DMI 内部） | 间接 | 间接 |
| 4 | RSI | `ta.rsi` | close | 14 | ✓ | ✓ |
| 5 | ATR | `ta.atr` | high, low, close | 14 | ✓ | |
| 6 | DMI：+DI / −DI / ADX | `ta.dmi` | high, low, close | 14, 14 | ✓ | ✓ |
| 7 | Hull MA | `ta.hma` | close | 9 | | ✓ |
| 8 | VWMA 成交量加权均线 | `ta.vwma` | close, volume | 20 | | ✓ |
| 9 | 一目均衡表 | `ta.ichimoku`（ta 库） | high, low | 9 / 26 / 52 | | ✓ |
| 10 | Stochastic | `ta.stochFull`（ta 库） | high, low, close | 14, 3, 3 | | ✓ |
| 11 | CCI | `ta.cci` | close | 20 | | ✓ |
| 12 | Awesome Oscillator | `ta.ao`（ta 库） | high, low | 5, 34 | | ✓ |
| 13 | Momentum | `ta.mom` | close | 10 | | ✓ |
| 14 | MACD | `ta.macd` | close | 12, 26, 9 | | ✓ |
| 15 | Stochastic RSI | `ta.stochRsi`（ta 库） | close | RSI 14、%K 14、平滑 3、%D 3 | | ✓ |
| 16 | Williams %R | `ta.wpr` | high, low, close | 14 | | ✓ |
| 17 | Bull Bear Power | —（库里直接写） | high, low, close | 13 | | ✓ |
| 18 | Ultimate Oscillator | `ta.uo`（ta 库） | high, low, close | 7, 14, 28 | | ✓ |

标「ta 库」的来自 TradingView 官方的 `TradingView/ta` 库 v9，源码见 [tradingview/ta-library-v9.pine](tradingview/ta-library-v9.pine)；其余是 Pine 内置函数，源码不公开，结论靠与 TradingView 实际数值比对（§5）。

内部辅助（不对外）：WMA（`ta.wma`，Hull MA 用）、N 日最高 / 最低价（`ta.highest` / `ta.lowest`，Stochastic、Williams %R、一目均衡表用）、True Range（`ta.tr`，ATR、DMI、UO 用）、`hl2 = (high + low) / 2`（AO 用）。

## 2. 公式

记号：`x[1]` 是前一根 K 线的值；`n` 是周期。

**分母为零的统一规则**：结果为 NaN。之后用到它的比较一律不成立（Pine v6 里含 na 的比较结果是 false），技术评级里这一项按 §4「算不出」的规则处理。RSI 和 DMI 例外，按下面各自写明的取值。这类情况对成交额 5 亿日元以上的 Prime 股票几乎不会出现，但每一处都要有测试。

### 平滑类

- **SMA**：最近 n 根的算术平均；不足 n 根为 NaN。
- **EMA**：`α = 2 / (n + 1)`，`EMA[t] = α·x[t] + (1 − α)·EMA[t−1]`；**起点是前 n 个值的简单平均**，之前为 NaN。Pine 参考手册 `ta.ema` 的示例代码用第一个值做起点，但内置函数的实际输出不是这样（§5 第 1 条）。
- **RMA**：`α = 1 / n`，递推同 EMA；起点同样是前 n 个值的简单平均，之前为 NaN。
- **WMA**（内部）：权重 n, n−1, …, 1 的加权平均，最新一根权重最大。

### Wilder 系

- **RSI(14)**：`up = RMA(max(Δclose, 0), 14)`，`down = RMA(max(−Δclose, 0), 14)`；`RSI = 100 − 100 / (1 + up/down)`。
  - 分母为零：`down = 0` 时 RSI = 100（包括 up 也为 0 的情形），否则 `up = 0` 时 RSI = 0（Pine 手册 `ta.rsi` 示例的判断顺序）。
- **True Range**（内部）：`max(high − low, |high − close[1]|, |low − close[1]|)`；第一根没有 `close[1]` 时取 `high − low`。
- **ATR(14)**：`RMA(TR, 14)`。
- **DMI(14, 14)**：
  - `up = high − high[1]`，`down = low[1] − low`；
  - `+DM = up > down 且 up > 0 ? up : 0`，`−DM = down > up 且 down > 0 ? down : 0`；
  - `+DI = 100 · RMA(+DM, 14) / RMA(TR, 14)`，`−DI` 同理；这里的 TR 从第二根 K 线才有值（Pine `ta.dmi` 示例用的是 `ta.tr`，第一根没有前一天收盘价就是 na），和 ATR 第一根取 `high − low` 不同，这样 TR 与 ±DM 从同一根开始平滑；
  - `ADX = 100 · RMA(|+DI − −DI| / s, 14)`，`s = +DI + −DI`，`s = 0` 时按 1 算（Pine `ta.dmi` 示例）。
  - 三次 RMA 叠加，ADX 要约 2n 根之后才有值。

### 均线类（技术评级）

- **Hull MA(9)**：`WMA(2·WMA(close, 4) − WMA(close, 9), 3)`，即 n/2 向下取整为 4、√n 向下取整为 3（§5 第 5 条）。
- **VWMA(20)**：`SMA(close·volume, 20) / SMA(volume, 20)`；20 天成交量全为 0 时为 NaN。
- **一目均衡表(9, 26, 52)**：`中值(k) = (k 日最高价 + k 日最低价) / 2`；
  - 转换线 = 中值(9)，基准线 = 中值(26)；
  - 先行带 A = (转换线 + 基准线) / 2，先行带 B = 中值(52)；
  - 评级用的是 **26 根之前算出的先行带**（`A[26]`、`B[26]`），也就是图上平移后正好落在当天的那片云（§5 第 4 条）。

### 振荡器类（技术评级）

- **Stochastic(14, 3, 3)**：`raw = 100 · (close − 14 日最低价) / (14 日最高价 − 14 日最低价)`；`%K = SMA(raw, 3)`，`%D = SMA(%K, 3)`。最高 = 最低时 raw 为 NaN。
- **CCI(20)**：输入是 **close**；`CCI = (close − SMA(close, 20)) / (0.015 · 平均绝对偏差(close, 20))`；平均绝对偏差为 0 时为 NaN。
- **Awesome Oscillator**：`SMA(hl2, 5) − SMA(hl2, 34)`。
- **Momentum(10)**：`close − close[10]`。
- **MACD(12, 26, 9)**：`MACD = EMA(close, 12) − EMA(close, 26)`，`Signal = EMA(MACD, 9)`。
- **Stochastic RSI**：`r = RSI(close, 14)`，`raw = 100 · (r − 14 日最低 r) / (14 日最高 r − 14 日最低 r)`，`K = SMA(raw, 3)`，`D = SMA(K, 3)`。最高 = 最低时 raw 为 NaN。
- **Williams %R(14)**：`−100 · (14 日最高价 − close) / (14 日最高价 − 14 日最低价)`，取值 −100 到 0；最高 = 最低时为 NaN。
- **Bull Bear Power(13)**：`Bull = high − EMA(close, 13)`，`Bear = low − EMA(close, 13)`。
- **Ultimate Oscillator(7, 14, 28)**：`BP = close − min(low, close[1])`，`TR = max(high, close[1]) − min(low, close[1])`；`A_k = ΣBP / ΣTR`（最近 k 根）；`UO = 100 · (4·A7 + 2·A14 + A28) / 7`。任一 ΣTR 为 0 时为 NaN。

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

预热期 260。每项给出 +1（买）、−1（卖）或 0（中性）。规则以 TradingView `TechnicalRating` 库 v3 的源码为准（[tradingview/TechnicalRating-library-v3.pine](tradingview/TechnicalRating-library-v3.pine) 第 50–128 行），它就是内置「Technical Ratings」指标、筛选器和个股页仪表盘用的那一份。官方说明页的文字与源码有一处不一致（ADX 的卖出条件），按源码。

**趋势**：`close > EMA(close, 50)` 为上涨趋势，`close < EMA(close, 50)` 为下跌趋势，相等时两者都不是。Stoch RSI 和 Bull Bear Power 用到。

**算不出**：每一项有一个「检查值」（下表最后一列）。检查值为 NaN 时，这一项**算不出**，不计入平均（既不进分子也不进分母）；检查值不是 NaN、但条件里别的值是 NaN 时，那个条件按不成立算，这一项照样计入平均（多半得 0）。

### 均线组（15 项）

| 项 | 买 +1 | 卖 −1 | 检查值 |
|---|---|---|---|
| SMA 10/20/30/50/100/200（6 项） | 均线 < 收盘价 | 均线 > 收盘价 | 该均线 |
| EMA 10/20/30/50/100/200（6 项） | 均线 < 收盘价 | 均线 > 收盘价 | 该均线 |
| Hull MA 9 | 均线 < 收盘价 | 均线 > 收盘价 | Hull MA |
| VWMA 20 | 均线 < 收盘价 | 均线 > 收盘价 | VWMA |
| 一目均衡表 | `A[26] > B[26]`、基准线 > `A[26]`、转换线 > 基准线、收盘价 > 转换线，四条同时成立 | `A[26] < B[26]`、基准线 < `A[26]`、转换线 < 基准线、收盘价 < 转换线，四条同时成立 | 当天的先行带 B |

均线等于收盘价，或一目均衡表两边都不成立，为 0。

### 振荡器组（11 项）

| 项 | 买 +1 | 卖 −1 | 检查值 |
|---|---|---|---|
| RSI 14 | RSI < 30 且高于前一天 | RSI > 70 且低于前一天 | 前一天的 RSI |
| Stochastic 14,3,3 | %K < 20、%D < 20、%K > %D | %K > 80、%D > 80、%K < %D | 前一天的 %D |
| CCI 20 | CCI < −100 且高于前一天 | CCI > 100 且低于前一天 | 前一天的 CCI |
| ADX 14 | ADX > 20、**ADX 高于前一天**、+DI > −DI | ADX > 20、**ADX 高于前一天**、+DI < −DI | 当天的 ADX |
| AO | 上穿 0；或连续两根在 0 之上且拐头向上（`AO > AO[1]` 且 `AO[2] > AO[1]`） | 下穿 0；或连续两根在 0 之下且拐头向下（`AO < AO[1]` 且 `AO[2] < AO[1]`） | 前一天的 AO |
| Momentum 10 | 高于前一天 | 低于前一天 | 前一天的 Momentum |
| MACD 12,26,9 | MACD > Signal | MACD < Signal | Signal |
| Stoch RSI | 下跌趋势中，K < 20、D < 20、K > D | 上涨趋势中，K > 80、D > 80、K < D | EMA50 |
| Williams %R 14 | %R < −80 且高于前一天 | %R > −20 且低于前一天 | 前一天的 %R |
| Bull Bear Power 13 | 上涨趋势中，Bear < 0 且高于前一天 | 下跌趋势中，Bull > 0 且低于前一天 | EMA50 |
| UO 7,14,28 | UO > 70 | UO < 30 | UO |

其余情况为 0。

ADX 一行与官方说明页不同：说明页写卖出要「ADX 低于前一天」，源码买卖都要求 ADX 上升，方向只由 +DI、−DI 决定。Stochastic 和 Stoch RSI 不要求前一天刚交叉——网上流传的旧版（Pine v4）源码有这个条件，现行版本已去掉，不要照抄旧版。

### 合成与使用

- 均线评级 = 均线组里算得出的各项的平均；振荡器评级 = 振荡器组里算得出的各项的平均；某组全部算不出时该组为 NaN。
- 总评 = 两组评级的平均（各占 50%）；一组为 NaN 时，总评就是另一组；两组都是 NaN 时总评为 NaN，不给出信号。预热期 260 足够让 26 项都算得出，后两种情况只在测试里出现。
- 五档：`> 0.5` 强烈买入、`(0.1, 0.5]` 买入、`[−0.1, 0.1]` 中性、`[−0.5, −0.1)` 卖出、`< −0.5` 强烈卖出。
- 入场：总评 > 0.5，排序值 = 总评；持仓退出：总评 < −0.1。

## 5. 已查清的问题

原先列在「待确认」里的 9 个问题，2026-09-24 查清如下。

| # | 问题 | 结论 | 依据 |
|---|---|---|---|
| 1 | EMA 的起点 | 前 n 个值的简单平均，与 RMA 相同 | 与 TradingView 实际数值比对：18 只 2025 年后上市、只有约 270–320 根 K 线的证券，简单平均起点算出的 EMA200 有 15 只与 TradingView 完全一致，另 3 只差 < 0.5%（大概是上市初期的数据差异）；第一个值做起点的 18 只全部差 1–3%。参考手册 `ta.ema` 的示例代码与内置函数的实际输出不一致 |
| 2 | 总评的合成 | 两组平均，各占 50%；一组 NaN 时取另一组 | `TechnicalRating` 库第 122–126 行；内置指标用可调权重 `MA × w + 振荡器 × (1 − w)`，默认 w = 50% |
| 3 | 单项算不出时 | 不计入平均 | 库把各项放进数组后用 `array.avg`，官方文档说数组统计函数跳过 na，全部为 na 时才返回 na |
| 4 | 一目均衡表比较哪一天的先行带 | 26 根之前算出的 `A[26]`、`B[26]` | 库第 84–86 行 |
| 5 | Hull MA 9 的取整 | n/2 向下取整为 4，√9 = 3 | 与 TradingView 实际数值比对：8 只大盘股（7203、6758、9984、8306、6861、4063、9432、8035）按 4 算与 TradingView 的 HullMA9 到小数点后 4 位完全一致，按 5 算全部不一致 |
| 6 | 上涨 / 下跌趋势 | 收盘价与 EMA50 比较 | 库第 61–63 行 |
| 7 | N 日最高收盘价 | 删掉 | 两个策略都没用到；跟踪止损用的「开仓以来最高收盘价」由策略按开仓日自己算 |
| 8 | 振荡器的分母为零 | 结果为 NaN，含 NaN 的比较不成立（§2 开头） | TradingView 内置函数这时返回什么没有公开，这是本系统的规定 |
| 9 | CCI 的输入 | 收盘价 | 库第 59 行 `ta.cci(close, 20)` |

**本系统复刻的是评级库，不是筛选器**（2026-09-24 决定）。TradingView 有两套技术评级：图表上的「Technical Ratings」指标用 `TechnicalRating` 库，源码公开；筛选器和个股页的仪表盘由服务器端计算，源码不公开，两者并不完全一致。在 150 只成交额最大的 Prime 股票上（2026-09-18）黑盒比对筛选器：

- 它逐项公开的 7 项里，Stoch RSI、Williams %R、Bull Bear Power、UO、VWMA、Hull MA 与评级库 150/150 一致；一目均衡表按评级库只有 120/150 一致，按库的旧版（Pine v4）规则——先行带不平移，买入要先行带 A 高于 B、收盘价在 A 之上、在基准线之下、当天刚上穿转换线，卖出反过来——有 149/150 一致；
- 振荡器组按评级库有 134/150 一致，不一致的都差一票；把 CCI 换成 hlc3、Stochastic 加上「前一天刚交叉」后到 143/150，其余 7 只找不出统一规律。这两处是从 12 种组合里挑出来的推断，没有源码依据；
- 总评按评级库与筛选器一致的是 112/150。

所以本系统的评级和个股页仪表盘会有约 1/4 的股票差一票左右，这是已知的、有意的差异，不要照着仪表盘去「修正」。黄金测试 `test_technical_rating_against_tradingview.py` 把冻结数据里唯一受影响的 9020（一目均衡表：库判 −1，筛选器判 0）单独写明。

「与 TradingView 实际数值比对」用的是 TradingView 筛选器的查询接口 `POST https://scanner.tradingview.com/japan/scan`（不用登录），它对每只东证股票返回最新一根 K 线的 EMA10–200、HullMA9、RSI、ADX、CCI20、UO，以及三个评级 `Recommend.All` / `Recommend.MA` / `Recommend.Other`。实现完成后可以用它对全股票池做一次端到端核对。这是非公开接口，只用于一次性核对，不要让系统依赖它。比对时用的是 02 回填到 `var/invest.db` 的数据（最新到 2026-09-18），研究收盘价与 TradingView 的收盘价逐只一致。

## 来源

- TradingView，`TechnicalRating` 库 v3（2024-11-29）：<https://www.tradingview.com/script/jDWyb5PG-TechnicalRating/>，源码 [tradingview/TechnicalRating-library-v3.pine](tradingview/TechnicalRating-library-v3.pine)
- TradingView，内置指标「Technical Ratings」v4（2026-04-15）：<https://www.tradingview.com/script/Jdw7wW2g-Technical-Ratings/>，源码 [tradingview/Technical-Ratings-indicator-v4.pine](tradingview/Technical-Ratings-indicator-v4.pine)
- TradingView，`ta` 库 v9（2024-11-26）：<https://www.tradingview.com/script/BICzyhq0-ta/>，源码 [tradingview/ta-library-v9.pine](tradingview/ta-library-v9.pine)
- 以上三份源码取自 TradingView 的 pine-facade 接口（`https://pine-facade.tradingview.com/pine-facade/get/<脚本 ID>/<版本>`，脚本 ID 在脚本页面 HTML 的 `script_id_part` 里），按 MPL 2.0 许可保存
- TradingView，Technical Ratings 说明页：<https://www.tradingview.com/support/solutions/43000614331-technical-ratings/>
- Pine Script 文档，数组统计函数对 na 的处理：<https://www.tradingview.com/pine-script-docs/language/arrays/>
- Pine Script 参考手册（`ta.rsi`、`ta.dmi` 的示例代码）：<https://www.tradingview.com/pine-script-reference/v6/>
