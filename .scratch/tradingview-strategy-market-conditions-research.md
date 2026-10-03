# TradingView 策略如何考虑适用的股票市场形势

- 调查日期：2026-09-30
- 目的：在实施 [05 三类 OHLCV 策略候选](invest-assistant-v1/issues/05-three-ohclv-strategy-candidates.md) 前，确认 TradingView 如何表达和检验策略适用的市场形势，并提取可用于本项目的产品与数据模型启示。
- 来源边界：事实依据只采用 TradingView 官方 Pine Script 文档、官方帮助中心和官方内置策略说明。下文把「平台能力」「官方示例」和「本项目建议」明确分开；官方示例只说明可以怎样实现，不证明某项规则在日本股票上有效。

## 1. 结论

TradingView **不会自动识别某个策略适合趋势市、震荡市、高波动市或牛熊市，也不会自动替策略切换形势**。它的工作方式是：作者在 Pine 策略中显式编写条件，策略在当前图表数据上模拟订单，Strategy Report 展示结果。TradingView 官方甚至明确提醒，多数策略只为特定市场形态或条件设计，换到其他数据集可能产生失控亏损；风险控制和跨数据集检验因此很重要。[Pine Strategies：Risk management](https://www.tradingview.com/pine-script-docs/concepts/strategies/#risk-management)

这里应区分三层：

1. **交易规则自身的条件**：例如个股收盘高于 SMA200 才允许买入。这是策略定义的一部分。
2. **可交易的市场过滤器**：例如 TOPIX 上涨且低波动时才允许新开仓。它同样必须由作者显式编码，TradingView 不会自动补上。
3. **研究后的适用性证据**：同一冻结策略在不同日期、标的、时间周期和市场形势下的 OOS 表现。Strategy Report 提供结果和测试工具，但“适用／不适用”的判定仍由研究者负责；官方特别反对只挑表现好的标的、周期或日期范围，并建议跨多个、最好是多样的数据集评估。[Pine Strategies：Selection bias / Overfitting](https://www.tradingview.com/pine-script-docs/concepts/strategies/#selection-bias)

因此，对 05 最有价值的不是复制某个 TradingView 社区脚本，而是采用这套分层：**显式、可版本化的条件 → 保留条件命中轨迹 → 在冻结配置下按形势与样本阶段分组报告 → 人工决定是否晋级**。

## 2. TradingView 怎样把市场形势写进策略

### 2.1 趋势与震荡

Pine 策略本质上是由布尔条件触发 `strategy.entry()` / `strategy.exit()` 等订单命令。TradingView 官方的空白策略示例直接用快慢均线交叉分别触发多头和空头；官方说明均线是滞后、确认型工具，长期均线上行／下行可作为牛／熊趋势确认，快慢均线交叉在强趋势中更有用。[Pine Script structure：blank strategy](https://www.tradingview.com/pine-script-docs/language/script-structure/#scripts)、[TradingView Moving Averages](https://www.tradingview.com/support/solutions/43000502589-moving-averages/)

可用的显式形势条件包括：

- `close > SMA`、均线斜率或快慢均线位置，表达趋势方向；这是解释型、滞后条件，不是平台自动预测。[Moving Averages](https://www.tradingview.com/support/solutions/43000502589-moving-averages/)
- ADX 表达趋势强度，`+DI` / `-DI` 表达方向。TradingView 的官方说明引用 Wilder 的经验分界：ADX 高于 25 表示较强趋势、低于 20 可视为弱趋势／无趋势，但也提醒交叉可能产生假信号、应与其他工具组合；所以这些阈值是作者采用的规则，而非平台普适分类。[Average Directional Index](https://www.tradingview.com/support/solutions/43000589099-average-directional-index-adx/)
- 官方 Trend Strength Index 把接近 `+1` / `-1` 解释为稳定上升／下降，接近 `0` 表示缺乏趋势强度，可作为“趋势／均值回归倾向”的另一种测量，而不是系统级 regime 标签。[Trend Strength Index](https://www.tradingview.com/support/solutions/43000730926-trend-strength-index/)

官方内置策略展示了不同市场假设必须落在不同规则中：

- Channel BreakOut Strategy 根据过去 `X` 根的最高／最低形成通道，向上突破做多、向下突破做空，是趋势／突破型规则的官方实现样本。[Channel BreakOut Strategy](https://www.tradingview.com/support/solutions/43000599828-channel-breakout-strategy/)
- Bollinger Bands Strategy 在跌破下轨的超卖状态中寻找向均值回归的机会；官方同时指出卖压可能持续、反弹可能延迟，因此需要退出保护。这是震荡／均值回归假设的样本，不是“下轨必反弹”的保证。[Bollinger Bands Strategy](https://www.tradingview.com/support/solutions/43000589104-bollinger-bands-strategy/)
- RSI Strategy 在 RSI 从超卖线向上穿越时做多、从超买线向下穿越时反向处理，阈值由策略输入决定。[RSI Strategy](https://www.tradingview.com/support/solutions/43000645066-rsi-strategy/)

**含义**：TradingView 没有一个统一的“趋势／震荡”字段。作者选择测量、窗口和阈值，并把它与入场条件用 `and` 组合，或者用不同分支改变交易方向和风控。

### 2.2 波动率

Pine 可用 OHLC 及 `ta.*` 函数计算波动条件。TradingView 官方把 ATR% 描述为相对当前价格的波动测量，ATR 与只看高低范围的 ADR 不同，它还考虑跳空；官方公式示例使用 `ta.rma(ta.tr(true), 14) / close * 100`。[ADR% / ATR% calculation](https://www.tradingview.com/support/solutions/43000734653-how-are-adr-and-atr-calculated/)

策略作者可以据此显式实现：

- `ATR / close` 高于或低于固定阈值／滚动分位数时允许或禁止入场；
- 用 ATR 缩放止损、止盈或仓位；TradingView 官方策略 FAQ 也给出 `ta.atr(14) * multiplier` 设置动态止损的例子。[Pine Strategies FAQ](https://www.tradingview.com/pine-script-docs/faq/strategies/)
- 用 Bollinger Band 宽度或标准差表达收缩／扩张；官方的 Bollinger 策略说明了上下轨由均值与离散程度形成，但具体“高／低波动”界线仍要由作者定义。[Bollinger Bands Strategy](https://www.tradingview.com/support/solutions/43000589104-bollinger-bands-strategy/)

TradingView 不会因为当前波动升高就自动修改策略参数。若脚本希望“高波动停止入场”或“高波动加宽止损”，该分支必须写在脚本里，并接受独立验证。

### 2.3 成交量与流动性

Pine 的 `volume` 是图表数据中的内置序列；股票通常以成交股数计，期货以合约数计，其他品种单位可能不同，缺少成交量时值为 `na`。官方示例把 `volume > volume[1]` 与价格上涨、价格高于均线组合成一个条件，说明成交量过滤器与其他条件一样由脚本显式构造。[Pine Chart information：Prices and volume](https://www.tradingview.com/pine-script-docs/concepts/chart-information/#prices-and-volume)

对股票策略，作者可编码近期平均量、相对量、成交额近似值或突破放量条件。TradingView 官方对 Volume 指标的解释也把放量突破视作较强确认、缩量突破视作潜在假突破，但强调要和近期历史比较；它是分析原则，不是 Strategy Tester 自动执行的流动性门槛。[TradingView Volume](https://www.tradingview.com/support/solutions/43000591617-volume/)

回测执行层的能力较粗：

- `commission_type` / `commission_value` 模拟每单、每股／合约或成交额百分比费用

- `slippage` 对市价单和止损单按固定 tick 数施加不利滑点。官方明确说真实滑点受波动、流动性、订单规模等影响，动态且不可精确模拟。[Pine Strategies：Slippage and unfilled limits](https://www.tradingview.com/pine-script-docs/concepts/strategies/#slippage-and-unfilled-limits)
- `backtest_fill_limits_assumption` 要求价格越过限价若干 tick 才认为限价单有足够流动性成交；但成交仍按原限价，官方提醒该折衷可能产生现实中不可能的成交时点。[同上](https://www.tradingview.com/pine-script-docs/concepts/strategies/#slippage-and-unfilled-limits)

**含义**：成交量可以成为信号／准入条件，但 TradingView 的默认 broker emulator 不是容量模型，也不会自动检查“订单占 ADV20 比例”。05 已要求的 ADV20 上限、部分成交／拒单和 10/25/50 bps 压力测试应继续由本项目自己的 Execution Model 实现。

### 2.4 牛熊、方向与只做多／只做空

牛熊可以由作者用价格相对长期均线、均线斜率、`+DI/-DI`、指数收益等定义。订单方向则是另一层：`strategy.entry()` 可生成多头或空头，并默认可反转现有仓位；`strategy.risk.allow_entry_in()` 可以把所有 entry 限制为只做多或只做空。Strategy Report 还会把适用指标分别列为 All、Long、Short。[Pine Strategies：Orders and direction](https://www.tradingview.com/pine-script-docs/concepts/strategies/#strategyentry)、[Risk management](https://www.tradingview.com/pine-script-docs/concepts/strategies/#risk-management)

这意味着“熊市”不等于“必须做空”：脚本可以在熊市关闭新多仓、降低仓位、继续持有、平仓或反向做空，语义完全取决于作者。对本项目当前日本股票 long-only 组合，市场形势更适合作为研究分组或“是否允许新开仓”的显式策略政策，不能把 TradingView 的多空反转语义直接搬过来。

### 2.5 多周期与跨标的过滤

`request.security()` 可以请求另一个标的、另一个周期或其他上下文中的序列，也能在请求上下文里运行 `ta.atr()` 等函数。官方示例既有“盘中图取日线 ATR”，也有当前标的收益与用户选择标的收益的相关性计算。[Other data and timeframes FAQ](https://www.tradingview.com/pine-script-docs/faq/other-data-and-timeframes/)、[Other timeframes and data：requesting calculated variables](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/#declared-variables)

典型用途是：

- 个股日线信号再用周线／月线趋势确认；
- 个股入场前读取大盘指数、行业 ETF 或波动率标的作为市场过滤器；
- 用另一个标的的收益、趋势或相关性作为风险条件。

但高周期的未确认值会变化并导致 repaint。官方建议请求最后一个已确认的高周期值，并明确警告：`barmerge.lookahead_on` 若没有对表达式做历史偏移，会把未来数据泄漏到历史中。[Other data and timeframes：Avoiding repainting](https://www.tradingview.com/pine-script-docs/faq/other-data-and-timeframes/#how-to-avoid-repainting-when-using-the-requestsecurity-function)、[Pine Strategies：Lookahead bias](https://www.tradingview.com/pine-script-docs/concepts/strategies/#lookahead-bias)

需要注意平台边界：Strategy Report 描述的是“给定标的、给定期间”的结果；`request.security()` 能把其他标的作为输入，但官方订单 API 是围绕当前策略仓位的 `entry/order/exit/close`，没有横截面股票池、逐日排名和多证券组合账本的概念。[Strategy Report：given symbol and period](https://www.tradingview.com/support/solutions/43000764138-tradingview-strategy-report-how-to-start/)、[Pine Strategies：Order placement commands](https://www.tradingview.com/pine-script-docs/concepts/strategies/#order-placement-and-cancellation) 因此可以合理推断：TradingView 适合演示“指数过滤单一图表标的”，但不是 05 的 `PeriodicTopN` 横截面组合执行器替代品。

### 2.6 交易时段与日期条件

`time()` / `time_close()` 接收 session 字符串；当前 bar 不在指定时段时返回 `na`。`input.session()` 允许用户在 Inputs 页设置时段，默认按交易所时区解释，也可显式指定时区。Pine 还提供 `session.ismarket`、`session.ispremarket`、`session.ispostmarket` 和首末 bar 状态。[Pine Sessions：Using time-based sessions](https://www.tradingview.com/pine-script-docs/concepts/sessions/#using-time-based-sessions)、[Pine Chart information：Session information](https://www.tradingview.com/pine-script-docs/concepts/chart-information/#session-information)

官方策略 FAQ 给出了完整的日期／时段过滤函数：使用 `input.time` 设起止日、`input.session` 设日内排除／允许窗口，再把结果与 RSI 信号用 `and` 组合。这再一次说明日期和交易时段不会由 Strategy Tester 自动加入交易逻辑，而是脚本条件或测试范围的一部分。[Strategies FAQ：filter trades by date or time range](https://www.tradingview.com/pine-script-docs/faq/strategies/#how-do-i-filter-trades-by-a-date-or-time-range)

## 3. TradingView 怎样检验“适用性”

### 3.1 Strategy Report 能回答什么

策略在图表数据上执行后，Strategy Report 提供：

- 净利润、最大回撤、盈利交易比例、profit factor；
- 策略与同期间 buy-and-hold 的对比、outperformance、Sharpe / Sortino；
- 交易收益分布、连续盈亏、逐交易 run-up / drawdown、权益增长／回撤期；
- Long / Short 分列及完整交易清单；
- 初始资金、仓位、杠杆、手续费、滑点等运行属性；
- XLSX 下载用于离线复核。[Pine Strategies：Strategy report](https://www.tradingview.com/pine-script-docs/concepts/strategies/#strategy-report)

这些指标能描述某次运行，却不会自动得出“适合上涨高波动”这样的结论。形势条件若只存在于脚本内部，作者还必须把形势命中、被过滤原因和分组结果另行记录／展示，才能解释为什么某一时期有或没有交易。

### 3.2 日期与标的分段

Deep Backtesting 允许选择具体日期范围，并使用所选标的可用的全部历史，而不是只用当前图表已加载数据；当前官方限制为每次最多 200 万 bars、100 万 trades，结果只在报告中显示。[How Deep Backtesting works](https://www.tradingview.com/support/solutions/43000666265-how-deep-backtesting-works/)

按形势检验通常有两种做法：

1. 在脚本里用日期／形势布尔值限制下单，再运行同一期间；
2. 用 Deep Backtesting 或日期输入逐个运行不同历史窗口，再保存／导出报告。

切换图表标的／周期后可以重跑相同策略。官方明确把只查看少数表现好的标的、周期或日期称为 selection bias，并建议覆盖多个、最好是多样的数据集且不要忽略失败范围。[Pine Strategies：Selection bias](https://www.tradingview.com/pine-script-docs/concepts/strategies/#selection-bias)

但 TradingView 没有替用户定义“2008 熊市”“震荡区间”或自动把多段结果等权汇总成一个适用性结论。04b-B 已实现的固定 TOPIX 定义、区间发现、全部候选保留与逐段等权汇总，比单纯手选 TradingView 日期范围更可复现，也更能抑制挑区间。

### 3.3 样本内、样本外与前向测试

TradingView 最新官方策略文档直接讨论 overfitting：常见做法是把同一标的数据分成 IS 与 OOS，在 IS 上优化参数，然后用冻结配置在 OOS 上测试且不再微调；即使如此也不能保证未来表现。[Pine Strategies：Overfitting](https://www.tradingview.com/pine-script-docs/concepts/strategies/#overfitting)

官方还建议用实时数据 forward testing。它能暴露部分未来数据泄漏问题并反映当下的手续费、滑点和流动性，但样本量有限，不宜单独作为依据。[Pine Strategies：Backtesting and forward testing](https://www.tradingview.com/pine-script-docs/concepts/strategies/#backtesting-and-forward-testing)

官方发布规则要求参数匹配目标市场、说明参数选择、使用现实费用，并至少有约 100 笔交易；不过这是防止发布结果误导的最低规则，不是统计显著性或策略有效性的证明。[TradingView Strategy publishing rules](https://www.tradingview.com/support/solutions/43000764681-strategy-publishing-rules/)

### 3.4 手续费、滑点、成交与未来信息

TradingView 明确指出，不计交易成本会高估历史收益；作者应设置手续费和滑点，并使用现实的资金、杠杆和仓位。官方发布指南还建议默认数据和配置产生合理数量的交易，通常至少约 100 笔。[Pine Publishing：Strategy report](https://www.tradingview.com/pine-script-docs/writing/publishing/#strategy-report)

默认情况下，策略在 bar 收盘计算并创建市价单，broker emulator 在下一可用 tick（通常下一 bar 开盘）成交；开启收盘成交、订单成交后重算或逐 tick 等选项会改变语义，甚至造成历史／实时结果不同。[Pine Strategies：Market orders](https://www.tradingview.com/pine-script-docs/concepts/strategies/#market-orders)、[Strategy properties](https://www.tradingview.com/support/solutions/43000628599-strategy-properties/)

官方把以下情况明确列为 lookahead 风险：高周期请求错误使用 `lookahead_on`、使用会 repaint 的变量，以及在历史 bar 的订单成交后重算时读取该 bar 最终 OHLCV。Forward test 若与历史结果行为不同，是检查此类问题的方法之一。[Pine Strategies：Lookahead bias](https://www.tradingview.com/pine-script-docs/concepts/strategies/#lookahead-bias)

对本项目而言，05 现有要求“t 日收盘信号、t+1 开盘成交”“冻结训练／验证／盲测区间”“保留成本压力和失败 run”与这些官方警告一致，而且比 TradingView 单次报告更严格。

## 4. 对 05 的具体启示

以下是基于上述平台能力作出的本项目设计建议，不是 TradingView 官方规定。

### 4.1 不要新增一个模糊的 `suitable_market` 文本字段

把“适用市场”拆成三类可审计事实：

| 层次 | 建议记录 | 例子 |
|---|---|---|
| 策略固有条件 | `strategy_version` 中冻结、逐日可复算 | `long_trend_sma200_v1` 的个股 `close > SMA200` |
| 外部市场上下文 | 独立、有版本、与交易无关 | 已实现的 `topix_trend_vol_v1`：趋势 × 波动 |
| 研究结论 | 绑定策略版本、形势定义、样本阶段和运行集合 | “在 OOS 的下跌高波动段证据不足”，而非“本策略适合熊市” |

这与当前 [CONTEXT](../CONTEXT.md) 中 `StrategyContext`、`MarketRegime` 的边界一致。尤其不要把单只股票的 `close > SMA200` 当作 TOPIX 市场形势，也不要让市场形势标签自动改写策略阈值。

### 4.2 让每次研究配置完整保存测试上下文

05 的 run / experiment spec 除现有 strategy version、参数、commit、manifest、allocator 和 execution model 外，建议显式保存：

- `sample_stage`: `development | validation | blind_test | forward`；
- `universe_definition_version`、标的／股票池、日线周期；
- `market_regime_definition_version`，以及 discovery / interval IDs（若按 04b-B 形势段运行）；
- `condition_policy`: `diagnostic_only | gate_new_entries | force_exit`，避免把“分组观察”误读成实时形势切换；
- 费用、滑点情景、成交量参与率上限、延迟模型；
- 基准与是否含分红／税；
- 预热范围与计入收益的测试范围。

同一冻结 spec 可生成多个 run，但 OOS / blind run 不允许在结果出来后覆盖参数；调参必须生成新的策略版本和新的实验记录。

### 4.3 每日保留条件轨迹，而不只保留成交

为了回答“为什么某形势没交易”，建议对每个候选至少保存或可复算以下诊断：

- 固有条件值：趋势门槛、过去收益、横截面 rank / percentile；
- 外部上下文：TOPIX 趋势、RV20、标签是否 unknown；
- 流动性：ADV20、计划订单／ADV20、是否因容量被拒绝；
- 资格结果与结构化 reason codes；
- 当日股票池规模、合格候选数、最终入选数。

只从订单反推适用行情会遗漏所有被过滤日期和零交易区间，也是 TradingView 单次交易报告难以直接回答的问题。

### 4.4 UI 显示“证据矩阵”，不要显示自动赢家

建议在现有研究页增加两个互不混淆的视图：

1. **规则卡**：策略固有条件、可选市场 gate、方向、再平衡周期、流动性与成本模型；明确哪些会影响交易，哪些只用于分组。
2. **证据矩阵**：`策略版本 × 样本阶段 × TOPIX 形势`，每格显示覆盖交易日／区间数、成交数、净超额收益中位数、最差段、回撤、换手、成本后结果和失败集中度。

每格标记 `exploratory`、`validation`、`blind_test` 或 `insufficient_evidence`。不要按单一 Sharpe 或某一形势最好表现自动贴“适用”标签，也不要自动切换 champion；这与 05 已规定的人工晋级和 Pareto 比较一致。

### 4.5 三个候选分别怎样看市场形势

先明确现有基线：TradingView 官方 Technical Ratings 对**当前图表证券**在用户选择的一个图表／更高周期上计算均线组、振荡器组和总评分；源码中的 `request.security(syminfo.tickerid, tfInput, ...)` 仍然请求同一证券，只是切换周期。[TradingView Technical Ratings](https://www.tradingview.com/script/Jdw7wW2g-Technical-Ratings/)、[仓库留存的官方源码](invest-assistant-v1/tradingview/Technical-Ratings-indicator-v4.pine) 因此，它内部少量“价格高于均线”“振荡器偏多”等趋势条件是单证券技术信号，不是 TOPIX regime，也不能回答全市场处于上涨／下跌、高／低波动中的哪一格。`technical_rating_v1` 可以作为策略基线，但其评分与 04b-B 的外部市场标签必须继续分开存储和展示。

- **长趋势／绝对动量**：`close > SMA200` 或 12 个月收益为正是个股固有准入，不等于 TOPIX 上涨形势。应另按 TOPIX 六格报告它是否在震荡段频繁反复进出，以及趋势形势中的市场暴露。
- **短期反转**：TradingView 的 Bollinger / RSI 官方样本说明均值回归规则存在，但也明确警告卖压可持续。05 应重点看下跌高波动段的尾部风险、成交率、ADV 占比和成本压力，而不是预设“震荡一定适用”。
- **横截面 6-1 / 12-1 动量**：`request.security()` 展示了跨标的输入能力，但 TradingView Strategy Report 仍以单一图表标的／单一策略仓位为中心。05 的逐日股票池、横截面排序、PeriodicTopN 和多证券组合账本必须留在本项目 SimulationEngine 中，不能用单标的 Pine 回测替代。

### 4.6 04b-B 与 05 的关系

04b-B 已提供的 TOPIX 趋势 × 波动形势、可复算区间、输入指纹、逐段独立空仓回放和“不自动选赢家”，正好可作为 05 的**外部场景研究层**。但 05 还需要补齐：

- 全期连续运行后按当日可知形势归因，回答“实际持仓跨形势延续时怎样”；
- development / validation / blind-test 的冻结与一次性运行语义；
- 多策略家族、月度再平衡和横截面组合；
- 流动性容量与多档成本情景；
- 按策略版本 × fold × regime 汇总且保留失败结果。

不要把 04b-B 的事后完整区间边界当作实时交易 gate。若未来加入“只在某形势开仓”，必须把它建模为新的、有版本的策略政策，并按 t 日收盘可知、最早 t+1 执行的语义重新做 OOS 回测。

## 5. 可直接用于 05 验收的补充检查项

- [ ] 每个策略版本明确列出固有条件、外部形势条件、交易方向、交易时段／再平衡日和是否影响入场／退出。
- [ ] 同一策略能在不过滤形势的全期、按 04b-B 区间独立启动、以及全期连续后按形势归因三种模式中运行，报告明确区分三者。
- [ ] development / validation / blind-test 范围在运行前冻结；blind-test 结果产生后修改任何规则必须创建新策略版本。
- [ ] 至少按年份、fold、TOPIX 六格和成本情景展示覆盖、交易数、净超额收益、回撤、换手和容量；无足够样本显示 `insufficient_evidence`。
- [ ] 多周期／TOPIX 过滤只读取当日已确认值；有黄金测试证明 t 日后的数据不能改变 t 日信号。
- [ ] 费用、滑点、ADV20 限制和拒单／部分成交规则属于 execution model，不藏在 strategy 条件里。
- [ ] 页面不根据最佳形势、最佳参数或最佳标的自动生成“适合”结论；人工晋级决定及理由另存。

## 6. 回答原问题的一句话版本

TradingView 中，策略“考虑适用市场形势”的方式是作者用价格、趋势、波动、成交量、跨周期／跨标的和时段数据显式写过滤条件，再用 Strategy Report 在不同标的和日期范围做成本后、样本外与前向检验；平台本身不会自动发现、认证或切换策略的适用行情。
