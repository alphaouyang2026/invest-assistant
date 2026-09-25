# invest-assistant v1 系统设计

- 状态：Proposed
- 日期：2026-09-23
- 术语：[CONTEXT.md](../../CONTEXT.md)——本文所有领域名词都按其中的定义使用
- 架构决定：[ADR-0001](../../docs/adr/0001-store-bars-by-security-and-date-without-point-in-time.md) 覆盖存储、不做时点可复现 · [ADR-0002](../../docs/adr/0002-use-sqlite-single-file.md) SQLite 单文件 · [ADR-0003](../../docs/adr/0003-compute-research-prices-from-adjustment-factors.md) 研究价格本地计算 · [ADR-0004](../../docs/adr/0004-backtest-and-paper-trading-are-one-account.md) 回测与模拟交易是同一个账户
- 来历：my-invest 的简化版。取舍过程见 my-invest 会话中的架构评审与两轮追问（Q1–Q32），结论已全部写进本文、CONTEXT.md 和 ADR。

## 1. 做什么，不做什么

做：

1. 从 J-Quants（Light 套餐）抓取东证全部证券的日线行情、上市名册、交易日历和 TOPIX，存进 6 张 SQLite 表；
2. 用两种借鉴 TradingView / QuantConnect 的技术策略，每个交易日收盘后给出信号；
3. 模拟账户按信号在下一交易日开盘模拟成交，从过去的起始日一路推进到今天（回测），之后随每日同步继续推进（模拟交易）。

不做：时点可复现、原始响应存档、机器学习、Qlib、分红、融资融券、做空、盘中数据、实盘下单、登录。

## 2. 模块与 seam

```text
          J-Quants HTTP 适配器        测试用假数据适配器
                  └────────────┬────────────┘
      ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┼─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   seam：J-Quants 客户端
┌──────────────────────────────────────────────────────┐
│ 行情数据模块  market_data/                             │
│   同步：日历 → 逐日（日线 + 名册）→ TOPIX → 拆合股核对    │
│   读取：研究价格、成交价格、质量标记、市场分类区间         │
└──────────────────────────────────────────────────────┘
                  │
┌──────────────────────────────────────────────────────┐
│ 指标模块  indicators.py（纯 pandas，无数据库）            │
└──────────────────────────────────────────────────────┘
                  │
      ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┼─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   seam：策略
          ┌────────────────────┴────────────────────┐
   Trend-Pullback v1                         技术评级 v1
          └────────────────────┬────────────────────┘
┌──────────────────────────────────────────────────────┐
│ 模拟账户模块  accounts/                                 │
│   推进：拆合股调整 / 退市结清 → 开盘成交 → 收盘出信号 →    │
│         组合规则生成订单                                │
│   统计：净值、回撤、夏普……（读取时计算）                   │
└──────────────────────────────────────────────────────┘
      ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┼─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   驱动方
          ┌────────────────────┴────────────────────┐
   新建账户：从起始日推进到最新交易日        每日同步成功后：所有账户推进
```

规则：

- 只有行情数据模块读写 `instruments`、`segment_periods`、`daily_bars`、`trading_calendar`；别的模块只调用它的读取函数，不写 SQL 访问这四张表。
- 只有模拟账户模块读写 `paper_accounts`、`paper_orders`。
- 指标模块和策略不碰数据库：输入是 DataFrame 和持仓事实，输出是信号。它们的测试只需要合成 K 线。
- 两个 seam 都各有两个真实适配器（J-Quants：HTTP / 假数据；策略：两种策略），不再额外加 seam。

## 3. 数据模型（6 张表）

金额与价格在 Python 中一律用 `Decimal`，在 SQLite 中存成文本；指标计算用 float（pandas）。日期存 ISO 文本 `YYYY-MM-DD`。

### 3.1 `instruments`

| 列 | 说明 |
|---|---|
| `code` PK | J-Quants 的 5 位代码（例如 `72030`、`130A0`）；TOPIX 为 `TOPIX` |
| `kind` | `stock` / `index` |
| `name`、`name_en` | 当前公司名 |
| `scale_category` | 当前规模分类（Core30 … Small 2、`-`） |
| `first_listed_seen`、`last_listed_seen` | 在名册中第一次、最后一次出现的交易日 |

### 3.2 `segment_periods`（市场分类区间）

| 列 | 说明 |
|---|---|
| `code`、`valid_from` PK | 区间起始交易日 |
| `valid_to` | 区间最后一个交易日；`NULL` 表示仍在持续 |
| `market_code` | `Mkt`（0111 Prime、0112 Standard、0113 Growth……） |
| `product_category` | `ProdCat`（011 国内股票……） |
| `sector33` | `S33` |

三项任一变化 → 关闭旧区间（`valid_to` = 前一交易日）并开新区间。某代码在当天名册中消失 → 关闭区间，不开新区间（退市）。

### 3.3 `daily_bars`（日线行情）

| 列 | 说明 |
|---|---|
| `code`、`date` PK | |
| `open`、`high`、`low`、`close` | 成交价格（J-Quants `O/H/L/C`），没成交为 `NULL` |
| `volume`、`turnover` | `Vo`、`Va`（日元） |
| `adjustment_factor` | `AdjFactor`，除权日以外为 1 |
| `ex_rights_type` | `ExRT`：1 拆股 / 2 合股 / 3 配股 / `NULL` |
| `upper_limit_hit`、`lower_limit_hit` | `UL`、`LL`：当天最高价触及涨停 / 最低价触及跌停 |
| `quality_status` | `ok` / `excluded` / `untradable`（见 4.4） |

不存 J-Quants 的 `Adj*` 列（ADR-0003）。TOPIX 也存这里，只有 OHLC。

### 3.4 `trading_calendar`

| 列 | 说明 |
|---|---|
| `date` PK | |
| `holiday_division` | `HolDiv`：0 休市、1 交易日、2 半日交易、3 休市但有节假日交易 |

开市日 = `holiday_division IN (1, 2)`。

### 3.5 `paper_accounts`（模拟账户）

| 列 | 说明 |
|---|---|
| `id` PK | |
| `name` | |
| `strategy` | `trend_pullback_v1` / `technical_rating_v1` |
| `strategy_params` | JSON，缺省项用策略默认值 |
| `portfolio_rules` | JSON：`initial_cash`（默认 10,000,000）、`max_positions`（10）、`max_weight`（0.10）、`cash_floor`（0.05） |
| `costs` | JSON：`commission_rate`（0）、`commission_min`（0）、`slippage`（0.001，每边） |
| `start_date` | 起始交易日 |
| `advanced_through` | 已推进到的交易日；`NULL` 表示尚未推进 |
| `status` | `active` / `stopped`；`stopped` 不再随同步推进 |
| `backtest_data_mark` | JSON：回测追上最新交易日那一刻的 `daily_bars` 行数与最大日期（ADR-0001） |
| `created_at` | |

### 3.6 `paper_orders`（订单及账户事件）

| 列 | 说明 |
|---|---|
| `id` PK | |
| `account_id` | |
| `kind` | `buy` / `sell` / `split_adjustment` / `delisting_settlement` |
| `code` | |
| `signal_date` | 生成订单的交易日（账户事件为发生日） |
| `execution_date` | 计划成交的交易日（信号日的下一开市日） |
| `planned_quantity` | 计划股数（100 的整数倍） |
| `priority` | 生成时的候选排序值 |
| `reason` | JSON：处置、理由代码、关键指标值 |
| `status` | `pending` / `filled` / `expired` / `skipped` |
| `outcome_reason` | 过期或放弃的原因代码（见 7.3） |
| `filled_quantity` | 成交股数；拆合股调整为持仓股数的变化量（可为负） |
| `fill_price` | 含滑点的成交价 |
| `fees` | 手续费 |
| `cash_delta` | 本记录对现金的影响（买为负、卖为正、合股零股折现为正） |

**持仓、现金、净值都不单独存**：持仓 = 按时间累加已成交和已记账的记录；现金 = `initial_cash + Σ cash_delta`；每日净值 = 现金 + Σ 持仓股数 × 当日收盘成交价格（当天无收盘价则用最近一个）。

## 4. 行情数据模块

### 4.1 J-Quants 适配器

- V2 API，请求头 `x-api-key`，key 来自环境变量 `JQUANTS_API_KEY`。
- 用到的接口：`GET /markets/calendar`、`GET /equities/bars/daily?date=`、`GET /equities/bars/daily?code=&from=&to=`、`GET /equities/master?date=`、`GET /indices/bars/daily/topix?from=&to=`。
- 分页：响应带 `pagination_key` 时原样带上继续请求，直到没有。
- 限速：Light 每账户每分钟 60 次，按滑动窗口计算，被拒的请求也计数。请求之间至少间隔 1.1 秒。
- 429 不带 `Retry-After`：等待 120 秒后重试。超时、网络错误、5xx：指数退避（5 → 10 → 20 → 40 秒），最多 5 次。my-invest 的退避公式底数等于上限、每次都等 60 秒，不要照抄。
- 可以从 my-invest `backend/app/integrations/jquants.py` 复制后改写。

适配器的 interface 只暴露「按日期取日线 / 按代码取区间日线 / 按日期取名册 / 取日历 / 取 TOPIX 区间」，返回已解析的记录。测试用的假适配器读内存数据，并能模拟 429、空响应和分页。

### 4.2 同步流程

一次同步（每日同步和 5 年回填是同一个函数）：

1. 取交易日历，覆盖写入 `trading_calendar`。
2. 目标日期 = 库里股票日线的最大日期之后、到今天为止的所有开市日；库为空时从「今天往前 5 年」的第一个开市日开始。
3. 按日期从早到晚，每个日期：取当天全部日线（分页）与当天名册 → 在**一个事务**里覆盖写入 `daily_bars`、更新 `segment_periods` 和 `instruments` → 提交。
   - 某日期日线返回空：如果是今天，说明数据还没出，结束本次同步并报告「当天数据未出」；如果是过去的开市日，记警告后继续。
4. 取 TOPIX 覆盖同一日期范围，写入 `daily_bars`（代码 `TOPIX`）。
5. 拆合股核对（4.3）。
6. 把本次结果（日期范围、写入行数、警告）追加到 `var/jobs.jsonl`。

中断后直接重跑：已提交的日期会被重新覆盖一次，结果不变，所以不需要记录进度。

名册处理的附加规则：

- 代码在名册中消失后又重新出现 → 记警告「代码重新出现」，照常开新区间（Q30）。
- 名册的公司名、规模分类变化只覆盖 `instruments`，不开新区间。

### 4.3 研究价格与拆合股核对

对某证券，交易日 `d` 的研究价格：

```text
累计系数(d) = Π 调整系数(e)，e 取 d 之后（不含 d）的所有除权日
研究价格(d) = 成交价格(d) × 累计系数(d)
研究成交量(d) = 成交量(d) ÷ Π 调整系数(e)，只取除权类型为 1（拆股）或 2（合股）的 e
```

配股（类型 3）只调价格、不调成交量。实现前对照官方计算说明 <https://jpx-jquants.com/ja/spec/eq-bars-daily/adj>。研究价格在读取时计算，不落表。

拆合股核对：本次同步中出现调整系数 ≠ 1 的每只证券，用「按代码取区间日线」取它除权日前 60 个交易日，逐日比对 J-Quants 的 `AdjC` 与本地研究收盘价；相对误差超过 0.1% 或绝对误差超过 0.1 日元（J-Quants 只保留 1 位小数）就记警告。回填完成后，从 5 年内有除权的证券里抽 20 只做同样核对。

### 4.4 质量标记

写入时逐行判定，结果取最坏的一档：

| 条件 | 标记 |
|---|---|
| `close` 为空（包括全天无成交） | `untradable` |
| 任一价格 ≤ 0，或 `high < max(open, close)`、`low > min(open, close)`、`high < low` | `untradable` |
| 价格齐全但 `volume` 或 `turnover` 为空 | `excluded` |
| 其余 | `ok` |

`untradable` 的日线不参与股票池、不产生信号、不能成交。缺交易日（开市日却没有日线）、复权对不上这类要跨行才能看出的问题，只在数据页查询时现算（行内规则可参考 my-invest `backend/app/services/quality_rules.py`）。

### 4.5 读取

interface 见[附录 A](#附录-a模块-interface)。要点：一次查询取整批证券，不逐只查询；研究价格、质量过滤、日历对齐都在模块内部完成，调用方拿到的是已经对齐好的行情。市场分类区间和成交额门槛不外露，收在 `universe()` 后面。

## 5. 指标模块

纯函数。输入是一只证券的 `Series`，或「行是交易日、列是证券代码」的宽表 `DataFrame`（由 `MarketFrame.wide(列名)` 得到），输出同形状的指标；所有计算都按列进行，所以全股票池约 1,600 只证券一次调用就算完，不逐只循环。公式按 TradingView Pine 的内置函数实现，并在代码注释中标明对应的 `ta.*`：

- SMA、EMA（`ta.ema`）、Wilder RMA（`ta.rma`）：EMA 和 RMA 都以前 n 个值的简单平均为起点，之前为 NaN——参考手册 `ta.ema` 的示例代码以第一个值为起点，但与 TradingView 实际数值比对，内置函数用的是简单平均（[indicators.md](indicators.md) §5 第 1 条）；每一列按它自己的前 n 个有效值计算（新上市的证券前面是 NaN）；
- RSI（RMA 平滑）、ATR（RMA 平滑的 True Range）、+DI / −DI / ADX（`ta.dmi`）；
- Hull MA、VWMA、一目均衡表（9/26/52）、Stochastic（14,3,3）、CCI（20）、Awesome Oscillator、Momentum（10）、MACD（12,26,9）、Stochastic RSI（3,3,14,14）、Williams %R（14）、Bull Bear Power（13）、Ultimate Oscillator（7,14,28）。

逐项公式、参数与取整见 [indicators.md](indicators.md)。

分母为零时的结果要显式规定并写进测试，不依赖 pandas 默认行为：RSI 平均损失为 0 时取 100、否则平均收益为 0 时取 0，DMI 的 `+DI + −DI` 为 0 时按 1 算（都照 Pine 手册示例）；其余指标（Stochastic、Stoch RSI、Williams %R 的最高等于最低，CCI 的平均偏差为 0，VWMA 的成交量全为 0，UO 的 True Range 之和为 0）结果为 NaN，之后含 NaN 的比较一律不成立。

NaN 的处理也要显式规定并写进测试：宽表对齐后，某证券当天没有日线的格子和停牌日一样是 NaN。规则是**把这一天当作没有 K 线**——TradingView 在无成交的日子本来就没有 K 线：递推类指标（EMA、RMA 及由它们组成的指标）跳过这一天、保留之前的平滑状态；窗口类指标（SMA、N 日最高价等）的「最近 n 根」跳过这一天往前数；这一天本身输出 NaN。停牌不多，实现上可以只对中间有 NaN 的列单独处理。

指标是因果的：某一天的值只用到这一天及以前的数据。递推类指标的值取决于输入从哪天开始（见 6.2「frame 的起点」）。

## 6. 信号

### 6.1 股票池

交易日 `t` 的股票池 = 同时满足：

- `t` 所在的市场分类区间：`market_code = 0111`（Prime）且 `product_category = 011`；
- 最近 20 个开市日（含 `t`）的成交额平均 ≥ 5 亿日元，缺失或 `untradable` 的日子按 0 计；
- `t` 的日线不是 `untradable`。

股票池只决定能否**新开仓**；已持仓证券离开股票池不会被卖出，仍由策略的退出规则管理（Q26）。

### 6.2 策略 seam

策略是一个声明了名称、默认参数、预热期和图上画哪些指标的对象，只有一个方法 `evaluate(frame, day, holdings)`（[附录 A](#附录-a模块-interface)）。`frame` 里每只**能判断**的证券（预热期够、当天不是 `untradable`）都得到一条信号，处置可以是「不参与」，信号里带着这一天的指标值。它对两类证券给出信号：

- **未持仓**：从空仓角度判断「可持有」还是「不参与」，给出理由；「可持有」的带候选排序值。`holdings` 传空时，其中「可持有」的就是信号页的入场候选，与任何账户无关。
- **持仓**：结合持仓事实判断「可持有」还是「必须清仓」，给出理由。持仓只传代码、股数和开仓成交日；持有天数和开仓以来最高研究收盘价由策略自己从行情算出，不由调用方传入——否则这条规则会散到每个调用方去。
  - 持有天数 = `frame` 里这只证券从开仓成交日到 `day`（含两端）的日线条数：停牌日库里有一条 `untradable` 日线，算一天；完全没有日线的开市日不算。
  - `frame` 里这只证券的日线晚于开仓成交日才开始时，直接报错，不静默计算——否则开仓以来最高收盘价会被算低，跟踪止损无声地算错。

返回「不参与」也是为了证券详情页：按日循环调用 `evaluate`，就同时得到指标曲线（每天信号里的指标值）和历史入场点，不需要为画图另加方法。

策略不查数据库、不筛股票池：`frame` 里有什么就评价什么，股票池由调用方先问行情数据模块。预热期不足的证券没有信号；持仓证券当天 `untradable`（例如停牌）时也没有信号，持仓维持原状。

**frame 的起点**：递推类指标的值取决于输入从哪天开始。策略对整个 `frame` 把指标算一次，按 `frame` 对象缓存（缓存不属于 interface），之后每次 `evaluate` 只按日取值，所以按日循环调用的开销与只调用一次相近。代价是：同一证券同一交易日，`frame` 起点不同，指标值会略有不同（见第 12 节）。调用方至少要从第一个评价日往前读预热期那么多个开市日；`frame` 传入后不得再修改。一条测试守住「不看未来」：用整个 `frame` 在 `t` 日评价，结果等于把 `frame` 截到 `t` 日再评价。

「往前读多少、先取股票池、再补上证券名称」这套组装只写在一处：`strategies` 模块的 `entry_candidates` 和 `history`（附录 A.3），信号页和证券详情页的 API 只调用它们。

### 6.3 Trend-Pullback v1

照搬 my-invest `docs/design/daily-investment-timing.md` §5，所有数字都是可覆盖的参数。预热期 180 个交易日（EMA60 的 3 倍）。

入场（`t` 日收盘全部成立）：

```text
EMA20[t] > EMA60[t]  且  close[t] > EMA60[t]
+DI14[t] > −DI14[t]  且  ADX14[t] > 20  且  ADX14[t] ≥ ADX14[t−1]
RSI14[t−1] ≤ 30      且  RSI14[t] > 30
排序值 = ADX14[t] / 100
```

持仓退出（任一成立即「必须清仓」，理由按以下优先级取第一个）：

1. 跟踪止损：`close[t] ≤ 开仓以来最高收盘 − 2 × ATR14[t]`；
2. 趋势失效：`EMA20[t] ≤ EMA60[t]` 或 `+DI14[t] ≤ −DI14[t]`；
3. 超买回落：`RSI14[t] ≥ 70` 且 `RSI14[t] < RSI14[t−1]`；
4. 时间退出：已持有 5 个交易日（开仓成交日收盘算第 1 天）。

退出当天不重新入场。以上价格都用研究价格。

**已知问题**：按这组规则，02 回填的三年数据上一次都不会入场——RSI14 ≤ 30 与「趋势完好」几乎不会同一天成立。失败记录与 v2 的方向见[策略研究](strategy-research.md) §2；v1 保留原样，作为系统中「没有交易」这条路径的检验对象。

### 6.4 技术评级 v1

按 TradingView `TechnicalRating` 库 v3 的 Pine 源码复刻 26 项——内置「Technical Ratings」指标、筛选器和个股页仪表盘用的都是它；源码存在 [tradingview/](tradingview/) 下，逐项规则见 [indicators.md](indicators.md) §4：

- 均线组 15 项：SMA、EMA 各取 10/20/30/50/100/200，Hull MA 9，VWMA 20，一目均衡表；
- 振荡器组 11 项：RSI 14、Stochastic 14,3,3、CCI 20、ADX 14、AO、Momentum 10、MACD 12,26,9、Stoch RSI 3,3,14,14、Williams %R 14、Bull Bear Power 13、UO 7,14,28。

每项给出 −1/0/+1；当天算不出的项不计入平均。组内取平均，总评是两组的平均（各占 50%）。官方说明页 <https://www.tradingview.com/support/solutions/43000614331-technical-ratings/> 的文字与源码有一处不一致（ADX 的卖出条件），按源码。五档：`> 0.5` 强烈买入、`(0.1, 0.5]` 买入、`[−0.1, 0.1]` 中性、`[−0.5, −0.1)` 卖出、`< −0.5` 强烈卖出。

- 入场：总评 > 0.5；排序值 = 总评。
- 持仓退出：总评 < −0.1。
- 预热期 260 个交易日。长周期 EMA 的数值会因起算点不同与 TradingView 页面略有差异，属于已知局限。

## 7. 模拟账户

### 7.1 推进一个交易日 `t`

对一个账户，严格按以下顺序：

1. **拆合股调整**：持仓证券在 `t` 除权（类型 1 或 2）→ 持仓股数 ÷ 调整系数（由成交记录推出的成本价随之 × 调整系数），记一条 `split_adjustment`；合股后不足 1 股的部分折成现金，金额 = 不足 1 股的新股数 × `t` 前一交易日收盘成交价格 × 调整系数。同一证券 `t` 日待成交的订单按同样比例调整股数：卖单改为全部新持仓，买单向下取整到 100 股（为 0 则放弃）。配股（类型 3）不调整持仓，记警告。
2. **退市结清**：持仓证券在 `t` 的名册中消失 → 按它最后一个收盘成交价格结清，记一条 `delisting_settlement`；它的待成交订单改为 `expired`（原因 `delisted`）。
3. **开盘成交**：执行日为 `t` 的待成交订单，先卖后买，买单按排序值从高到低（7.3）。
4. **重下卖单**：`t` 开盘过期的卖单，在 `t` 收盘重新下一张同样的卖单（执行日为下一开市日），直到成交或退市结清——不需要策略再次给出信号（Q26）。
5. **收盘出信号并生成订单**（7.2）。
6. `advanced_through = t`。

每个交易日在**一个事务**里提交：这一天写下的全部记录和 `advanced_through = t` 一起提交或一起放弃，所以推进中途被打断，重跑会从断点接着推进，不会多写或漏写一天。同一账户、同一份数据推进两次，得到逐行相同的记录：记录里不写墙上时间，金额全用 `Decimal`，同分按代码排序。

回测 = 从 `start_date` 到最新交易日逐日推进；追上后写 `backtest_data_mark`。之后每次同步成功，每个 `active` 账户推进新出现的交易日。已成交记录不因日线后来被修正而改写（ADR-0004）。

新建账户时校验：`start_date` 必须是开市日，且之前至少有该策略预热期那么多个开市日的数据。

### 7.2 组合规则：从信号到订单

在 `t` 收盘：

1. 持仓中得到「必须清仓」的 → 卖单，股数为全部持仓。已在 7.1 第 4 步重下卖单的持仓不再评价。
2. 空位 = `max_positions` − （持仓数 − 本次卖出数）。
3. 候选 = 入场评价「可持有」且未持仓的证券，按排序值降序、代码升序，取前「空位」个。
4. 每只候选的目标金额 = `t` 收盘净值 × `min(max_weight, (1 − cash_floor) / max_positions)`；计划股数 = ⌊目标金额 ÷ `t` 收盘成交价格 ÷ 100⌋ × 100。
5. 预算 = 当前现金 + 本次卖单按 `t` 收盘价估算的所得 − `cash_floor` × 净值。按顺序分配，超出预算的候选记为 `skipped`（原因 `insufficient_cash`）；计划股数为 0 的记为 `skipped`（原因 `lot_unaffordable`）。
6. 开仓后不调仓、不加仓；持仓股数只因卖出、拆合股调整和退市结清而变化。

### 7.3 开盘成交规则

对执行日为 `t` 的每张订单，用 `t` 的成交价格：

| 情形 | 结果 |
|---|---|
| `t` 日线为 `untradable` 或 `open` 为空 | `expired`，原因 `untradable` |
| 卖单，`lower_limit_hit` 且 `open = low` | `expired`，原因 `limit_down_open` |
| 买单，`upper_limit_hit` 且 `open = high` | `expired`，原因 `limit_up_open` |
| 卖单，其余 | 全部成交，价 = `open × (1 − slippage)` |
| 买单，其余 | 价 = `open × (1 + slippage)`；股数 = min(计划股数, 可用现金扣除手续费后能买的整手数)；为 0 则 `expired`，原因 `insufficient_cash` |

- 手续费 = max(`commission_min`, 成交额 × `commission_rate`)，默认 0。
- 卖出所得在成交当时就计入可用现金，同一开盘后面的买单可以使用。
- 成交时不再检查 `cash_floor`，它只在生成订单时起作用。
- 不做部分成交、不限制成交量占比；成交价不按呼值取整。

### 7.4 统计（读取时计算）

由逐日净值序列与成交记录计算：总收益、年化收益、最大回撤、夏普比率（日收益均值 ÷ 标准差 × √245，无风险利率 0）、胜率（已结束的持仓里扣除费用后盈利的比例）、平均持有交易日数、年化换手率（（买入成交额 + 卖出成交额）÷ 2 ÷ 平均净值，按年折算）、相对 TOPIX 的超额年化收益；净值曲线与 TOPIX 曲线在起始日归一为 1 后对比。报表注明「不含分红、不含税」。

## 8. 后台任务

- FastAPI 进程内一个任务线程、一个任务队列，同一时刻只执行一个任务（同步 / 账户推进）。SQLite 只允许一个写入者（ADR-0002），这条规则由此而来。
- 跨进程互斥：任务开始前取得 `var/job.lock` 文件锁；命令行入口也取这把锁，因此命令行回填与服务里的同步不会同时写库。
- 定时器（按日本时间）：每个开市日 18:00 排入同步；同步报告「当天数据未出」时，30 分钟后再排一次，最晚到 21:00。同步成功后，排入「推进所有 active 账户」。
- 新建账户后立即排入「推进该账户」。
- 当前任务的进度保存在内存；每个任务结束时把结果追加到 `var/jobs.jsonl`。服务重启时丢失进行中的任务可以接受——重跑即可。
- 命令行：`python -m app.cli sync`（前台执行同一个同步函数，用于首次回填）、`python -m app.cli advance [--account ID]`。

## 9. 界面与 API

中文界面，不做登录，服务只监听本机。前端通过 openapi-typescript 生成的客户端访问后端。

| 页面 | 内容 |
|---|---|
| 数据页 `/data` | 最大日期、证券数、行数；当前任务进度；「立即同步」按钮；最近任务结果与警告；现算的质量警告 |
| 信号页 `/signals` | 选择策略和日期（默认最新交易日），列出入场候选（代码、名称、市场、排序值、理由）；搜索证券 |
| 证券详情 `/signals/[code]` | lightweight-charts 画 K 线（研究价格）、成交量、所选策略的指标，以及历史入场点 |
| 账户列表 `/accounts` | 各账户的策略、起始日、推进到哪天、总收益、最大回撤、状态 |
| 新建账户 `/accounts/new` | 名称、策略、策略参数、组合规则、费用、起始日；提交后开始推进 |
| 账户详情 `/accounts/[id]` | 统计指标；净值 vs TOPIX 曲线；回撤曲线；当前持仓；明天开盘要执行的订单与理由；历史订单与账户事件；停用 / 删除 |

API（前缀 `/api`）：

- `GET /data/status`、`POST /data/sync`、`GET /data/quality`
- `GET /instruments?q=`、`GET /instruments/{code}/bars?from=&to=&strategy=`（研究价格 + 所选策略的指标 + 历史入场点）
- `GET /signals?strategy=&date=`
- `GET /accounts`、`POST /accounts`、`GET /accounts/{id}`、`GET /accounts/{id}/nav`、`GET /accounts/{id}/orders`、`POST /accounts/{id}/stop`、`DELETE /accounts/{id}`
- `GET /jobs/current`

## 10. 工程与运行

- 后端：Python 3.12、uv、FastAPI、SQLAlchemy 2 + Alembic、httpx、structlog、pydantic-settings、pandas、pytest。
- 前端：Next.js 16、React 19、TypeScript、Vitest、openapi-typescript、lightweight-charts。可以从 my-invest 复制前端骨架（配置、样式、API 客户端生成脚本）。
- 运行：Docker Compose 两个服务 `backend`、`frontend`；SQLite 文件为挂载卷上的 `var/invest.db`；`JQUANTS_API_KEY` 放在 `.env`；容器时区 `Asia/Tokyo`。
- 测试：普通测试不打网络，用假 J-Quants 适配器 + 临时 SQLite 文件 + 合成 K 线；指标用手算样例做黄金测试。

目录：

```text
backend/
  app/
    main.py            # FastAPI 应用；启动任务线程与定时器
    config.py
    db.py
    cli.py
    jobs.py            # 任务队列、文件锁、定时器、jobs.jsonl
    market_data/       # 4 张行情表、J-Quants 适配器、同步、研究价格、质量标记、读取
    indicators.py
    strategies/        # 策略 seam、entry_candidates / history、trend_pullback.py、technical_rating.py
    accounts/          # 2 张账户表、组合规则、开盘成交、推进、统计
    api/
  migrations/
  tests/
frontend/
docker-compose.yml
```

## 11. 交付顺序

每张票都要端到端可验证：

1. [01 项目骨架与运行环境](issues/01-skeleton-and-runtime.md)
2. [02 J-Quants 行情同步与数据页](issues/02-jquants-market-data-sync.md)——依赖 01
3. [03 指标、两个策略与信号页](issues/03-indicators-strategies-signals.md)——依赖 02
4. [04 模拟账户：回测、模拟交易与账户页](issues/04-paper-accounts.md)——依赖 03

## 12. 已知局限

- 不可复现：J-Quants 修正历史数据后，新建的同参数账户可能和旧账户结果不同；`backtest_data_mark` 只用于发现这种差异（ADR-0001）。
- 不含分红和税，高股息股的收益被低估（ADR-0003）。
- 只用日线：跟踪止损是「收盘确认、次日开盘卖出」，跳空时按真实开盘价成交，不按止损线成交。
- 开盘即涨停的买单一律视为买不到，现实中可能在收盘按比例分到少量；开盘即跌停的卖单同理。
- 技术评级的长周期 EMA 与 TradingView 页面的数值可能略有差异。
- 同一证券同一交易日，信号页（从当天往前读预热期）和回测中的账户（从起始日往前读，frame 更长）算出的 EMA 类指标不完全相同，偶尔会给出不同的处置——主要是技术评级：EMA200 只往前读 260 天时，当天的值里还有约 55% 来自起点的简单平均，信号页上的入场候选因此可能和回测账户那天的买入对不上。Trend-Pullback 读 180 天，EMA60 里起点只占约 2%，RSI、ATR、ADX 基本不受影响。这是为了让回测只算一次指标而接受的代价（6.2「frame 的起点」）。
- 证券代码被重复使用时只记警告，不拆分两家公司的历史。

## 附录 A：模块 interface

用 Python 伪代码写出每个模块**对外**的全部内容。调用方需要知道的仅限于此；括号里是这个 interface 背后藏着的东西。

### A.1 行情数据模块 `market_data`

```python
class MarketData:
    def __init__(self, session_factory, client: JQuantsClient): ...

    def sync(self, *, until: date | None = None,
             on_progress: Callable[[SyncProgress], None] | None = None) -> SyncReport: ...
    def read(self, codes: Sequence[str] | None, start: date, end: date) -> MarketFrame: ...
    def universe(self, start: date, end: date | None = None) -> dict[date, list[str]]: ...  # end 缺省为 start
    def instruments(self, *, query: str | None = None,
                    codes: Sequence[str] | None = None) -> list[Instrument]: ...
    def calendar(self) -> Calendar: ...      # sessions()/next()/prev()/offset()，纯内存
    def overview(self) -> DataOverview: ...  # 最大日期、行数、最近任务结果、现算的质量警告

@dataclass(frozen=True)
class Instrument:   code: str; name: str; name_en: str; market: str | None   # 当前市场区分；已退市为 None
```

藏在后面：J-Quants 分页与限速、逐日覆盖写入、市场分类区间的开闭、研究价格的累计系数、质量标记、拆合股核对、股票池的市场分类区间与成交额门槛、4 张表的全部 SQL。

`universe` 不带参数表：规则只有一套（6.1），门槛是模块内部的常量——只有一种取值的参数就是一个还用不上的 seam。它一次给出一段日期里每个开市日的股票池：信号页只问一天，回测要问几百天，逐日调用时每天约 0.25 秒（02 回填数据实测），3 年的回测光股票池就要 3 分钟，一次查询算完整段则只读一次成交额和市场分类区间。`instruments` 给信号页补证券名称与市场、给 `GET /api/instruments?q=` 做搜索（按代码前缀或名称包含）；只有这个模块能读 `instruments` 表，所以由它提供。

`MarketFrame` 是一个很薄的包装：内部是以 (证券, 交易日) 为索引的 DataFrame，列名由模块给出的常量声明（研究价格 OHLCV、成交价格 OHLC、成交额、涨跌停标志、质量标记、调整系数、除权类型），另带 `listed_through`（证券代码 → 它在名册中的最后一个交易日，仍在名册中为 `None`，由市场分类区间推出），并提供宽表访问器 `wide(列名)`（行是交易日、列是证券代码，没有日线的格子为 NaN），指标模块直接吃这种宽表。它是 interface 的一部分，列名和空值语义都要写进文档——这是选择用 pandas 换来的代价。调整系数、除权类型和 `listed_through` 是给模拟账户的——拆合股调整和退市结清（7.1）要用，而账户模块不能直接查这四张表；回测时账户按「那一天」判断在不在名册，不能用 `instruments` 给出的当前市场区分。

`client` 从构造函数传入，这就是 J-Quants seam：生产用 HTTP 适配器，测试用内存假适配器。

**删除测试**：删掉它，累计系数、质量判定、日历对齐和 4 张表的 SQL 会散到策略、账户、API 和命令行里。复杂度是被它集中住的。

### A.2 指标模块 `indicators`

```python
Prices = Series | DataFrame   # 一只证券，或宽表（行是交易日、列是证券代码）

def sma(s: Prices, n: int) -> Prices: ...
def ema(s: Prices, n: int) -> Prices: ...
def rma(s: Prices, n: int) -> Prices: ...
def rsi(...), atr(...), dmi(...), adx(...), hull_ma(...), vwma(...), ichimoku(...),
    stochastic(...), cci(...), awesome_oscillator(...), momentum(...), macd(...),
    stoch_rsi(...), williams_r(...), bull_bear_power(...), ultimate_oscillator(...)
```

一组纯函数，没有 seam，也不需要适配器。输入输出同形状，按列计算，所以全股票池一次调用。它的价值不在于藏住编排，而在于藏住正确性规则：Wilder 平滑的起点、分母为零时的取值、NaN 当作「这一天没有 K 线」（第 5 节）。两个策略共用这一份，否则 RMA 会被各写一遍。

### A.3 策略 seam `strategies`

```python
class Strategy(Protocol):
    name: str
    warmup_sessions: int
    plots: tuple[Plot, ...]          # 图上画哪些指标：指标名 → 叠在价格上，还是单独一栏

    def evaluate(self, frame: MarketFrame, day: date,
                 holdings: Sequence[Holding]) -> list[Signal]: ...

def build_strategy(name: str, params: Mapping[str, Any]) -> Strategy: ...
STRATEGY_DEFAULTS: Mapping[str, Mapping[str, Any]]   # 供新建账户页展示

def entry_candidates(market: MarketData, strategy: Strategy, day: date) -> list[Candidate]: ...
def history(market: MarketData, strategy: Strategy, code: str,
            start: date, end: date) -> SecurityHistory: ...

@dataclass(frozen=True)
class Holding:      code: str; quantity: int; opened_on: date
@dataclass(frozen=True)
class Signal:       code: str; disposition: Disposition; reason_codes: tuple[str, ...]
                    indicators: Mapping[str, float]; priority: float | None
@dataclass(frozen=True)
class Plot:         indicator: str; pane: Literal["price", "separate"]
@dataclass(frozen=True)
class Candidate:    signal: Signal; instrument: Instrument          # 已按排序值降序、代码升序
@dataclass(frozen=True)
class SecurityHistory:
                    frame: MarketFrame                              # 研究价格与成交量
                    indicators: DataFrame                           # 行是交易日、列是 plots 里的指标
                    entries: list[date]                             # 未持仓角度得到「可持有」的交易日
```

只有一个方法：`frame` 里每只能判断的证券都得到一条信号（含「不参与」，带当天指标值）；`holdings` 传空，其中「可持有」的就是入场候选；传账户持仓，就同时得到该账户的清仓信号。参数在构造时就固定在策略对象里，不出现在方法签名上。指标对整个 `frame` 只算一次、按 `frame` 缓存，缓存不属于 interface（6.2「frame 的起点」）。

两个适配器：Trend-Pullback v1 和技术评级 v1。

`entry_candidates` 和 `history` 不是 seam，是写在 seam 之上的两个普通函数：它们藏住「先取股票池、从第一个评价日往前读预热期那么多个开市日、调用 `evaluate`、补上证券名称」这套组装。`history` 按日循环调用同一个 `evaluate`，从每天的信号里收集指标曲线和入场点，不为画图另加方法。**删除测试**：删掉它们，「预热期决定往前读多远」会同时出现在信号页和证券详情页两个 API 处理函数里，而 A.6 规定 API 里不写业务规则。账户模块读的是覆盖整段回测的长 `frame`，不经过它们，直接调用 `evaluate`。

**删除测试**：删掉这个 seam，入场和退出规则会长进账户推进的循环里，信号页也就没法在不建账户的情况下显示候选。

### A.4 模拟账户模块 `accounts`

```python
class Accounts:
    def __init__(self, session_factory, market: MarketData): ...

    def create(self, spec: AccountSpec) -> AccountId: ...          # 校验起始日与预热期
    def advance(self, account_id: AccountId, *, through: date | None = None) -> AdvanceReport: ...
    def report(self, account_id: AccountId) -> AccountReport: ...  # 统计、净值序列、持仓、明日订单、历史订单
    def list(self, *, active_only: bool = False) -> list[AccountSummary]: ...
    def stop(self, account_id: AccountId) -> None: ...
    def delete(self, account_id: AccountId) -> None: ...
```

`advance` 是这个模块的全部分量：拆合股调整、退市结清、开盘成交、卖单重下、出信号、组合规则、写订单，全在它后面。它从 `advanced_through` 的下一个开市日推进到 `through`（默认最新交易日）；重复调用不会重复推进。回测和模拟交易都是它（ADR-0004），没有第二个入口。

`advance` 自己只做读库、写库和逐日循环：一次读出整段所需的行情（`MarketData.read` 取整段股票池的并集加上持仓）和整段股票池（`MarketData.universe(start, end)`），然后每个交易日分开盘、收盘两段——收盘段要先拿到开盘成交之后的持仓，才能问策略 `evaluate(frame, t, holdings)`。

内部的 seam 只给自己的测试用，不对外；全部不碰数据库、不产生副作用，所以「开盘涨停买不到」「卖出所得当场可用」「现金不够减手数」「十合一的零股折现」这类规则可以用几行合成数据测，而不必造一个账户再推进一年：

```python
class Ledger:                     # 由订单记录推出持仓（股数、开仓成交日、成本）、现金、待成交订单
    def apply(self, records) -> Ledger: ...                       # advance 与 report 共用这一份推算

def corporate_actions(ledger, day) -> list[Record]                # 拆合股调整、零股折现、退市结清（7.1 第 1–2 步）
def open_session(orders, day, cash, costs) -> list[Record]        # 一次开盘的全部订单：先卖后买、买单按排序值、
                                                                  # 卖出所得当场可用、逐单按 7.3 成交或过期
def replace_sells(expired, day) -> list[Record]                   # 7.1 第 4 步
def plan_orders(exits, candidates, closes, cash, nav, rules) -> list[Record]   # 7.2；含被放弃的订单
```

`day` 是账户看到的 `t` 日行情：当天的成交价格、涨跌停标志、质量标记、调整系数与除权类型，前一交易日收盘成交价格，以及哪些证券已不在名册中。`plan_orders` 收到的是 `advance` 过滤好的信号：`exits` 是持仓（未重下卖单的）得到的判断，`candidates` 是当天在股票池内、未持仓、「可持有」的入场候选；`closes` 是 `t` 日收盘成交价格，用来算计划股数和预估卖出所得。

**删除测试**：删掉 `Ledger`，「持仓、现金由订单记录推出」会在 `advance` 和 `report` 里各写一份，迟早不一致；把 `open_session` 拆回逐单的 `fill`，先卖后买与现金流转就只能经由 `advance` 测。

### A.5 任务模块 `jobs`

```python
class Jobs:
    def submit(self, job: Job) -> JobId: ...
    def current(self) -> JobStatus | None: ...
    def history(self, limit: int = 20) -> list[JobResult]: ...
```

藏住单线程队列、`var/job.lock` 文件锁、定时器和 `var/jobs.jsonl`。API、定时器和命令行都只看见这三个方法。

### A.6 调用关系

```text
API / 命令行 / 定时器
        │            └── Jobs.submit ── 任务线程 ──┐
        ├── MarketData.overview / instruments     │
        ├── Accounts.report / list / create ──────┤
        └── entry_candidates / history（信号页）   │
              └─ MarketData · Strategy.evaluate   │
                                                  ▼
                              MarketData.sync · Accounts.advance
                                                  │
                        Accounts.advance ── MarketData.read/calendar
                                         └─ Strategy.evaluate
                                         └─ Ledger · plan_orders · open_session（内部）
```

规则：API 处理函数里不写业务规则，只调用上面这些方法并把结果转成 JSON；策略不碰数据库；`Ledger`、`plan_orders`、`open_session` 等内部函数不越过账户模块被别处调用。
