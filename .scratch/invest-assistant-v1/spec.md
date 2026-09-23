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

纯函数，输入研究价格 DataFrame（单证券或按证券分组），输出同索引的指标列。公式按 TradingView Pine 的内置函数实现，并在代码注释中标明对应的 `ta.*`：

- SMA、EMA（`ta.ema`）、Wilder RMA（`ta.rma`）：EMA 与 RMA 以前 n 个值的简单平均为起点——实现时对照 Pine 文档确认起点规则；
- RSI（RMA 平滑）、ATR（RMA 平滑的 True Range）、+DI / −DI / ADX（`ta.dmi`）；
- Hull MA、VWMA、一目均衡表（9/26/52）、Stochastic（14,3,3）、CCI（20）、Awesome Oscillator、Momentum（10）、MACD（12,26,9）、Stochastic RSI（3,3,14,14）、Williams %R（14）、Bull Bear Power（13）、Ultimate Oscillator（7,14,28）；
- N 日最高收盘价。

分母为零时的结果（例如 RSI 平均收益与平均损失同时为 0）要显式规定并写进测试，不依赖 pandas 默认行为。

## 6. 信号

### 6.1 股票池

交易日 `t` 的股票池 = 同时满足：

- `t` 所在的市场分类区间：`market_code = 0111`（Prime）且 `product_category = 011`；
- 最近 20 个开市日（含 `t`）的成交额平均 ≥ 5 亿日元，缺失或 `untradable` 的日子按 0 计；
- `t` 的日线不是 `untradable`。

股票池只决定能否**新开仓**；已持仓证券离开股票池不会被卖出，仍由策略的退出规则管理（Q26）。

### 6.2 策略 seam

策略是一个声明了名称、默认参数、预热期的对象，只有一个方法 `evaluate(frame, day, holdings)`（[附录 A](#附录-a模块-interface)）。它对两类证券给出信号：

- **未持仓**：从空仓角度判断是否「可持有」，给出理由和候选排序值。`holdings` 传空时得到的就是信号页的入场候选，与任何账户无关。
- **持仓**：结合持仓事实判断「可持有」还是「必须清仓」，给出理由。持仓只传代码、股数和开仓成交日；持有天数和开仓以来最高研究收盘价由策略自己从行情算出，不由调用方传入——否则这条规则会散到每个调用方去。

策略不查数据库、不筛股票池：`frame` 里有什么就评价什么，股票池由调用方先问行情数据模块。预热期不足的证券没有信号；持仓证券当天 `untradable`（例如停牌）时也没有信号，持仓维持原状。

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

### 6.4 技术评级 v1

按 TradingView Technical Ratings 官方页面 <https://www.tradingview.com/support/solutions/43000614331-technical-ratings/> 复刻 26 项：

- 均线组 15 项：SMA、EMA 各取 10/20/30/50/100/200，Hull MA 9，VWMA 20，一目均衡表；
- 振荡器组 11 项：RSI 14、Stochastic 14,3,3、CCI 20、ADX 14、AO、Momentum 10、MACD 12,26,9、Stoch RSI 3,3,14,14、Williams %R 14、Bull Bear Power 13、UO 7,14,28。

每项按官方规则给出 −1/0/+1，组内取平均。总评如何由两组合成，官方页面没有写，实现时对照 TradingView 公开的 Pine 源码确认，并写进测试。五档：`> 0.5` 强烈买入、`(0.1, 0.5]` 买入、`[−0.1, 0.1]` 中性、`[−0.5, −0.1)` 卖出、`< −0.5` 强烈卖出。

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
    strategies/        # 策略 seam、股票池、trend_pullback.py、technical_rating.py
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
    def universe(self, day: date, policy: UniversePolicy = DEFAULT_POLICY) -> list[str]: ...
    def calendar(self) -> Calendar: ...      # sessions()/next()/prev()/offset()，纯内存
    def overview(self) -> DataOverview: ...  # 最大日期、行数、最近任务结果、现算的质量警告
```

藏在后面：J-Quants 分页与限速、逐日覆盖写入、市场分类区间的开闭、研究价格的累计系数、质量标记、拆合股核对、4 张表的全部 SQL。

`MarketFrame` 是一个很薄的包装：内部是以 (证券, 交易日) 为索引的 DataFrame，列名由模块给出的常量声明（研究价格 OHLCV、成交价格 OHLC、成交额、涨跌停标志、质量标记），并提供 `closes()` 这类宽表访问器。它是 interface 的一部分，列名和空值语义都要写进文档——这是选择用 pandas 换来的代价。

`client` 从构造函数传入，这就是 J-Quants seam：生产用 HTTP 适配器，测试用内存假适配器。

**删除测试**：删掉它，累计系数、质量判定、日历对齐和 4 张表的 SQL 会散到策略、账户、API 和命令行里。复杂度是被它集中住的。

### A.2 指标模块 `indicators`

```python
def sma(s: Series, n: int) -> Series: ...
def ema(s: Series, n: int) -> Series: ...
def rma(s: Series, n: int) -> Series: ...
def rsi(...), atr(...), dmi(...), adx(...), hull_ma(...), vwma(...), ichimoku(...),
    stochastic(...), cci(...), awesome_oscillator(...), momentum(...), macd(...),
    stoch_rsi(...), williams_r(...), bull_bear_power(...), ultimate_oscillator(...)
```

一组纯函数，没有 seam，也不需要适配器。它的价值不在于藏住编排，而在于藏住正确性规则：Wilder 平滑的起点、分母为零时的取值、NaN 的传播。两个策略共用这一份，否则 RMA 会被各写一遍。

### A.3 策略 seam `strategies`

```python
class Strategy(Protocol):
    name: str
    warmup_sessions: int

    def evaluate(self, frame: MarketFrame, day: date,
                 holdings: Sequence[Holding]) -> list[Signal]: ...

def build_strategy(name: str, params: Mapping[str, Any]) -> Strategy: ...
STRATEGY_DEFAULTS: Mapping[str, Mapping[str, Any]]   # 供新建账户页展示

@dataclass(frozen=True)
class Holding:      code: str; quantity: int; opened_on: date
@dataclass(frozen=True)
class Signal:       code: str; disposition: Disposition; reason_codes: tuple[str, ...]
                    indicators: Mapping[str, float]; priority: float | None
```

只有一个方法：`holdings` 传空就是入场候选，传账户持仓就同时得到该账户的清仓信号。参数在构造时就固定在策略对象里，不出现在方法签名上。

两个适配器：Trend-Pullback v1 和技术评级 v1。证券详情页要画历史入场点时，按日循环调用同一个方法，不为此另加方法。

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

内部还有两个 seam，只给自己的测试用，不对外：

```python
def plan_orders(signals, holdings, cash, nav, rules) -> list[PlannedOrder]   # 纯函数
def fill(order, bar, cash, costs) -> FillResult                              # 纯函数
```

两者都不碰数据库、不产生副作用，所以「开盘涨停买不到」「现金不够减手数」这类规则可以用几行合成数据测，而不必造一个账户再推进一年。

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
        ├── MarketData.overview / read / universe │
        ├── Accounts.report / list / create ──────┤
        └── Strategy.evaluate（信号页）            │
                                                  ▼
                              MarketData.sync · Accounts.advance
                                                  │
                        Accounts.advance ── MarketData.read/calendar
                                         └─ Strategy.evaluate
                                         └─ plan_orders / fill（内部）
```

规则：API 处理函数里不写业务规则，只调用上面这些方法并把结果转成 JSON；策略不碰数据库；`plan_orders` 和 `fill` 不越过账户模块被别处调用。
