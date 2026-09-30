# 策略扩展、精细回测与策略选定方案

> 调查日期：2026-09-28
> 范围：当前 invest-assistant 日频日本股票系统
> 性质：可行性调查与实施建议，不是投资建议

## 结论先行

当前项目已经具备质量不错的事件驱动、逐交易日、次日开盘成交内核，但它还是“模拟账户/纸面交易系统”，不是完整的“策略研究平台”。下一步最有价值的工作不是直接堆更多策略，而是先补一层可复现的研究实验与选定机制，并继续复用现有账户推进、成交和账本逻辑。

建议顺序：

1. 抽出统一 SimulationEngine，让固定区间研究和持续 paper account 共用同一内核。
2. 增加 experiment、run、数据指纹、训练/验证/盲测区间和失败记录。
3. 先加入三个只依赖现有 OHLCV 的低参数策略。
4. 用滚动样本外、成本压力和最低交易数淘汰，不按全样本最高 Sharpe 选冠军。
5. 通过后以 champion–challenger 晋级到纸面账户。
6. 价值/质量策略等 point-in-time 财务数据接入后再做。

当前数据库约 529 万根日线，覆盖 2021-09-24 至 2026-09-25，只有约五年历史。足够搭研究管线和做初筛，不足以在大量参数搜索后声称长期统计显著。

## 1. 当前项目理解

### 1.1 已有能力

| 能力 | 当前实现 | 评价 |
|---|---|---|
| 策略 seam | backend/app/strategies/base.py 的 Strategy.evaluate | 简洁、可测，适合单策略日线信号 |
| 策略注册 | backend/app/strategies/__init__.py 的注册表和 defaults | 两个策略时够用，扩展后需要版本和 typed 参数 schema |
| 指标 | backend/app/indicators.py | 纯 pandas/NumPy、宽表计算、处理停牌/缺 bar；基础很好 |
| 股票池 | backend/app/market_data/market.py::universe | 使用历史市场区间、流动性和质量选 Prime 普通股 |
| 模拟推进 | backend/app/accounts/accounts.py::advance | 同一内核覆盖历史回测和纸面交易，确定且可续跑 |
| 成交 | backend/app/accounts/session.py | 次日开盘、固定滑点/佣金、涨跌停/不可交易、拆合股、退市 |
| 组合 | backend/app/accounts/planning.py | 候选排序、整手、持仓数/权重/现金上限 |
| 统计 | backend/app/accounts/statistics.py | 收益、年化、MDD、Sharpe、胜率、持有期、换手、TOPIX 超额 |
| 审计 | paper_orders 和 reason codes | 决策与成交可追踪 |
| 测试 | backend/tests 下策略、账户、成交和公司行动测试 | 因果、账本和规则已有较好基础 |

数据库现状：

- daily_bars：5,288,517 行。
- 行情范围：2021-09-24 至 2026-09-25。
- instruments：5,036 条。
- 仅一个 technical_rating_v1 模拟账户。

### 1.2 两个现有策略

trend_pullback_v1 的既有调查已经证明三年数据中零次入场。原因不是实现错误，而是 RSI14 深度超卖和中期趋势完好在同一天互相冲突。它应该保留为失败基线，不能原地反复调参直到盈利。

technical_rating_v1 平均每日约 88 个候选、最多 356 个，远多于十个持仓位。最终业绩高度依赖 priority=rating 的横截面排序，而不只是入场阈值。需要分别评估：

- 信号 coverage 与后续收益。
- 排序的 rank IC 和分组收益。
- 组合约束和成本对结果的贡献。
- MA 组、振荡器组和总评分的少量预注册消融。

### 1.3 关键缺口

| 缺口 | 影响 |
|---|---|
| 回测和长期 paper account 是同一对象 | 不能自然表达固定训练/验证/测试区间 |
| 无 Experiment / Run | 没有预注册、代码/数据指纹、试验总数和淘汰原因 |
| 行情覆盖更新且不版本化 | 同配置重跑可能改变 |
| 只有一个 priority | 无法区分 alpha、置信度、风险和流动性 |
| 组合只开仓不再平衡 | 不适合月度动量、低波或策略组合 |
| 固定比例滑点 | 忽略价差、成交量占比、冲击和部分成交 |
| 不含现金分红和税 | 高股息策略与基准比较会偏 |
| 指标起点依赖 | 信号页与账户可能得到不同 EMA |
| 基准只有 TOPIX | 无法区分策略有效还是股票池整体上涨 |
| 统计较少 | 缺少下行风险、信息比率、暴露和容量 |
| 约五年历史 | 复杂策略、regime 和大规模选参极易偶然成功 |

## 2. 目标架构

不要引入第二套成交逻辑。推荐数据流：

MarketData + immutable DataView
→ Strategy + Allocator + Execution
→ SimulationEngine.run(spec, period)
→ NAV / signals / orders / fills / diagnostics
→ 分别适配 ResearchExperiment 与 PaperAccount

成熟事件驱动引擎也通过模拟时间只暴露当时已知数据，并把 fill、slippage、fee、buying power 和 settlement 分成可替换模型。[LEAN 时间模型](https://www.quantconnect.com/docs/v1/key-concepts/understanding-time) · [LEAN reality model](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/key-concepts)

建议新增：

- app/simulation/engine.py：从 Accounts.advance 抽出纯逐日循环；输入 SimulationSpec 和只读 DataView，输出 SimulationResult。
- app/research/experiments.py：experiment、run、fold、baseline 和 selection policy。
- app/research/metrics.py：总体、逐年、逐 fold、逐状态和相对基准指标。
- app/research/selection.py：硬门槛、Pareto 比较、champion–challenger。
- app/allocators：把策略信号与如何形成组合分开；当前规则成为 RankedEqualWeightAllocator。
- app/execution：当前成交成为 NextOpenExecutionModel；费用、滑点和容量以接口注入。

策略负责预期和退出，allocator 负责目标持仓，execution 负责可成交数量和价格。不要让策略直接决定股数。

信号可逐步增加 score、rank_hint、confidence、target_horizon 和 as_of。不同策略的原始 score 不可直接相加；confidence 不是校准概率时不得命名 probability。

## 3. 候选策略

### 3.1 第一批：只使用现有 OHLCV/成交额

| 优先级 | 候选 | 固定规则方向 | 主要风险 |
|---|---|---|---|
| P0 | 横截面 6-1 / 12-1 动量 | 月末按过去 126/252 日收益、跳过最近 21 日排序；月度再平衡 | 日本历史动量较弱；五年样本短 |
| P0 | 短期反转 | 五或二十日收益最低分位，附流动性过滤，持有五至十日 | 换手高、价差和冲击敏感 |
| P0 | 长趋势/绝对动量 | close>SMA200 或十二月收益为正；月度检查 | 震荡期来回损耗 |
| P1 | Trend Pullback v2 | 长趋势过滤；RSI(2/3) 短回调；重新站回短均线确认 | 原始证据多来自美国市场 |
| P1 | 低波/防御 | 六十至一百二十日波动率最低分位，月度等权 | 行业、规模和利率暴露 |
| P1 | 突破加波动定仓 | 五十/一百日高点突破，ATR 或波动率定仓 | 跳空、假突破 |
| P2 | 技术评级校准版 | 固定阈值；预注册比较总评、MA 组和振荡组 | 变体过多产生多重试验偏差 |

Jegadeesh 与 Titman 的原始研究记录了三至十二个月相对强弱效应，但它只是候选来源，不代表日本样本必然有效：[原论文 DOI](https://doi.org/10.1111/j.1540-6261.1993.tb04702.x)。French 日度动量因子使用 prior 2–12 month return，可作为时间窗参考：[French 动量定义](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/det_mom_factor_daily.html)。

组合基线必须保留 1/N，并把逆波动、等风险贡献视为 challenger。ERC 让组件风险贡献相等，但仍需与简单 1/N 比较，防止优化器拟合噪声：[ERC 原论文](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1271972) · [1/N 研究稿](https://users.nber.org/~confer/2006/si2006/ap/uppal.pdf)。

### 3.2 第二批：先接入 point-in-time 财务数据

价值、质量、盈利能力、投资强度、盈利修正和股息策略必须满足：

- 使用披露日/可得日，而不是财报期末日连接行情。
- 能确定修订前当时可见的版本。
- 区分合并/非合并、会计准则、单位、币种和缺失。
- 历史上市公司集合仍按时点构建。
- 对 publication lag 有显式安全边界。

JPX 官方说明 J-Quants 提供历史股价、季度财务信息、历史上市公司和股息数据，范围取决于订阅计划：[JPX J-Quants API](https://www.jpx.co.jp/english/markets/other-data-services/j-quants-api/)。财务明细源自 EDINET XBRL taxonomy，字段和准则差异不能当普通宽表处理：[财务明细说明](https://jpx.gitbook.io/j-quants-pro/api-reference/statements_details)。

在 point-in-time 财务层完成前，不应实现价值/质量回测。

### 3.3 暂不建议

- 机器学习选股：证券截面让样本数看似巨大，实际独立时间样本仍约五年。
- 自动搜索指标表达式/遗传编程：试验次数爆炸，难以计入选择偏差。
- regime 自动切换：先让至少两个策略各自通过 OOS。
- 高频/日内：日线无法得知 OHLC 内部路径或盘口成交。
- 另接通用回测框架替换内核：会产生两套成交语义。

## 4. 精细回测

### 4.1 数据复现

每个 run 至少绑定 DataManifest：

- provider/query/config version。
- min_date/max_date/row_count。
- 分表和分日期/分块 hash。
- instrument、segment、corporate-action checksum。
- created_at。
- git commit 和 dirty flag。

下一阶段选择：冻结 SQLite 快照、保存追加式原始响应，或按 run 导出不可变 Parquet/SQLite 快照。

现有 ADR-0001 接受日常行情不可复现，适合日常信号，但不适合自动策略选定。应新增 ADR：生产行情仍可覆盖，研究 run 必须绑定不可变快照或强数据指纹。

MVP 可写 SHA-256 manifest；扩大后再考虑 DVC/lakeFS。[DVC](https://doc.dvc.org/user-guide/data-management/discovering-and-accessing-data) · [lakeFS](https://docs.lakefs.io/datasets/)

### 4.2 因果和时点

- t 日收盘信号只在 t+1 开盘成交。
- 财务信息只在真实披露并可取得后使用。
- 历史分类和退市不能用今天状态回填。
- 滚动窗口只能访问当前 fold 截止日前数据。
- 选择 champion 只能使用选择日以前完成的 run。
- 特征连接使用 backward as-of join 并设置 tolerance，不使用 nearest/forward。

[pandas merge_asof](https://pandas.pydata.org/docs/reference/api/pandas.merge_asof.html) 可支持上述连接。现有 test_nothing_after_the_day_is_seen 应提升为全部 feature/strategy 的共同契约测试。

### 4.3 成交与成本

保留当前模型作 simple 基线，再增加 conservative：

fill price = next open ± half-spread proxy ± base slippage ± impact coefficient × volatility × sqrt(order value / ADV20)

没有真实 bid/ask 时不应假装精确估计，而应提供场景：

- base：每边 10 bps。
- stress-1：每边 25 bps。
- stress-2：每边 50 bps。
- 单日订单默认不超过 ADV20 的 1%，可配置。
- 超限分别测试部分成交并结转、整单拒绝。
- 佣金、最低费、价差、滑点和冲击独立记账。

Zipline 官方 API 也将 commission、slippage 和 bar 流动性耗尽分开建模：[Zipline API](https://zipline.ml4trading.io/api-reference.html)。LEAN 明确指出默认模型偏向高流动性，大额或低流动性交易需要自定义现实模型：[LEAN reality model](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/key-concepts)。

J-Quants 行情提供 OHLCV、成交额、涨跌停和调整因子，同时说明无成交日字段为 null，且调整只覆盖部分公司行动：[J-Quants Daily Quotes](https://jpx.gitbook.io/j-quants-pro/api-reference/daily_quotes)。

### 4.4 公司行动和收益口径

现有拆合股处理继续复用，但需增加：

- 现金分红入账。
- 配股、合并、换股、分拆和代码复用政策。
- 退市收益/结清价格缺失时的保守规则。
- 基准使用 price return 还是 total return 的明确标注。

NYSE 列出的事件也包括拆股、分红、配股和分拆：[NYSE Corporate Actions](https://www.nyse.com/market-data/corporate-actions)。分红未实现前必须继续标注“不含分红”，不能与含分红基准直接比较。

### 4.5 组合构建

从 plan_orders 演进为：

Allocator.allocate(day, signals, positions, prices, risk) → TargetPortfolio
Rebalancer.orders(target, current, constraints, costs) → Orders

首批：

1. RankedEqualWeightAllocator：兼容当前行为。
2. PeriodicTopNAllocator：周/月再平衡，支持动量和低波。
3. VolatilityScaledAllocator：逆波动率并设单股/行业上限。
4. StrategySleeveAllocator：多个已通过策略占固定资金/风险 sleeve。

先使用固定权重或逆波动率，不直接做均值—方差最优权重。

### 4.6 基准、归因和指标

每个 run 至少比较：

- 同口径 TOPIX。
- 当日合格股票池等权、月度再平衡。
- 相同 allocator 下的简单排序诊断基线。
- 当前 technical_rating_v1。
- 少量事先声明的 ablation。

报告应分解 gross return、commission、spread/slippage、impact 和 net return，并报告选股、仓位、现金、行业暴露、每年/每 fold、entry cohort、持有期、换手、coverage、成交率、拒单率和容量。

新增指标：年化波动、Sortino、Calmar、下行偏差、active return、tracking error、information ratio、经验 CVaR、回撤持续/恢复期、最差月/年、集中度、profit factor、成本占 gross alpha，以及 fold 中位数和最差值。

Sharpe 不是唯一标准。样本短、偏态厚尾和多个试验会夸大最高值。Deflated Sharpe Ratio 可作为高级诊断：[Bailey & López de Prado](https://doi.org/10.2139/ssrn.2460551)。

## 5. 样本划分和稳健性

### 5.1 当前五年历史

第一阶段建议：

- 开发期：最早约三年。
- 验证期：随后约一年。
- 最终盲测：最近约一年，只运行一次。
- 区间前允许读取 warm-up，但交易和收益不计入本区间。
- 不足预注册最低交易数时标为 insufficient_evidence，而非通过或失败。

扩到十年以上历史后，使用 anchored walk-forward：train 5y → validate 1y；train 6y → validate 1y；最后保留一至两年 holdout。

不能随机 K-fold；相邻收益和持仓标签有时间依赖。

### 5.2 预注册

看收益前保存：

- 假设和来源。
- universe。
- 特征、参数和允许的极少变体。
- 入场、退出、再平衡和持有期。
- allocator、execution 和成本情景。
- train/validation/holdout 边界。
- primary metric 和淘汰门槛。
- 已尝试 trial 数。
- 修改触发条件；修改后必须升版本。

既有 .scratch/invest-assistant-v1/strategy-research.md 的“规则先冻结、留盲测、失败版本化”应成为可执行约束。

### 5.3 稳健性清单

1. 因果/前视测试。
2. 股票池、退市和公司行动测试。
3. 参数邻域不应悬崖式翻转。
4. 10/25/50 bps 成本压力。
5. 延迟一天成交和下一开盘缺失压力。
6. 排除最好五/十笔交易后不过度依赖异常值。
7. 分年、行业、市值和流动性 bucket。
8. 多数 walk-forward fold 为正，而不是只靠一个时期。
9. 同时比较股票池等权和 TOPIX。
10. 保留全部失败变体和试验总数。

PBO/CSCV 可在更长历史和较多候选时使用；当前五年数据不应把它当精确答案：[PBO 原论文](https://papers.ssrn.com/sol3/Papers.cfm?abstract_id=2326253)。数据窥探和多重检验也会抬高偶然赢家：[Lo–MacKinlay](https://www.nber.org/papers/w3001) · [White Reality Check 综述](https://www.nber.org/system/files/working_papers/w22989/w22989.pdf)。

## 6. 策略选定

### 6.1 硬门禁和 Pareto 比较

先做硬门禁：

- 数据和代码可复现。
- 因果/质量测试通过。
- 达到最低交易数和 coverage。
- 成本压力下不过度崩塌。
- 最大回撤和容量符合账户约束。
- holdout 未用于修改同一版本。

通过后比较 OOS 净超额收益、OOS Sharpe/Sortino、最大回撤、fold 稳定性、turnover/成本、与 champion 的 OOS 相关性、容量、复杂度和可解释性。

不要用随意加权的超级分数。优先选择 Pareto 前沿中的简单策略；表现相近时，参数少、交易少、解释清楚者胜出。

### 6.2 Champion–Challenger

状态建议：

draft → feasible → validated → holdout_passed → paper_challenger → champion → retired

规则：

- 同一家族的参数变体按一次搜索族处理。
- holdout 失败后修改必须创建 v2；没有新数据时只能标探索性。
- challenger 至少经历预定 paper 观察期。
- 自动系统只能推荐晋级，最终 champion 人工确认。
- champion 不因一个月落后就切换。

MLflow Registry 的不可变版本和 champion/challenger alias 值得借鉴，并不要求引入 MLflow：[MLflow Registry](https://mlflow.org/docs/latest/ml/model-registry/tutorial)。

### 6.3 多策略组合

若多个策略分别通过验证且收益来源不同，优先固定 sleeve：

- 初始等资金或等风险。
- 策略级最大权重。
- 组合层统一执行单股、行业和换手约束。
- 相关性只用过去窗口估计，定期而非每日更新。
- regime 只做保守风险缩放，不全仓从 A 跳到 B。

第一版可先离线合成各策略 OOS 日收益验证互补性，之后再演进为多 strategy sleeves。

## 7. 数据模型与 API

建议最小表：

- research_experiments：hypothesis、universe、period、benchmark、primary metric、gates、holdout lock。
- research_runs：strategy/version/params、allocator、execution、manifest、commit、fold、状态和失败原因。
- research_metrics：overall/year/fold/regime/cost scenario 指标。
- research_artifacts：curve、trades、signals、exposure、diagnostics 的路径和 checksum。
- strategy_promotions：状态迁移、evidence run、人工决定和说明。
- data_manifests：日期、行数、checksum 和 provider metadata。

大结果可写 gzip CSV/Parquet artifact，SQLite 保存索引和 checksum。当前没有 pyarrow，MVP 用 gzip CSV 即可。

API 草案：

- POST /api/research/experiments
- POST /api/research/experiments/{id}/runs
- GET /api/research/experiments/{id}
- GET /api/research/runs/{id}
- GET /api/research/runs/{id}/metrics
- GET /api/research/runs/{id}/curve
- GET /api/research/compare
- POST /api/strategies/{version}/promotions

批量运行继续走现有单写者 job 队列；模拟尽量只读，完成后一次写结果。比较 API 必须校验数据快照、股票池、区间、执行模型和基准相同。

策略元数据应包含 name/version/family、parameter type/bounds/default、required fields、warmup rule、rebalance frequency、plots、reason catalog 和来源。参数 bounds 用于语义和安全校验，不是给优化器无限搜索。

## 8. 测试与验收

内核契约：

- 同一 manifest/spec 两次 run 的订单、成交、NAV 和指标逐行相同。
- 固定区间与更长区间切片一致，允许 warm-up。
- 修改 t 以后数据不改变 t 以前信号。
- paper adapter 和 research engine 同区间记录相同。
- 拆合股、配股、分红、退市、停牌、涨跌停、缺 open、整手和现金边界有 golden tests。
- 提高成本不能提高净收益。
- 容量上限不被成交突破。
- fold 边界 feature 只读允许历史。
- 信号页与账户在相同 as_of、lookback 和版本下一致。

策略验收：

- 候选分布、交易数和覆盖证券数不过稀/过密。
- 手工构造序列和至少一个外部黄金样本。
- 订单可追到 strategy version、signal、reason、allocator 和 cost model。
- 预注册 fold 和 holdout 独立。
- 参数邻域、成本、延迟和异常交易剔除报告齐全。
- TOPIX 与股票池等权口径一致。
- 显示全部 trials，包括失败和取消 run。

## 9. 实施路线

### Phase 0：研究规矩结构化

- 新增策略版本、experiment spec 和 data manifest。
- 固定 train/validation/holdout。
- 增加股票池等权 benchmark。
- 为现有两个策略生成诊断基线。
- 暂不做参数优化 UI。

退出条件：任何结果都能回答哪份数据、哪段时间、哪个 commit、试过多少变体。

### Phase 1：抽 SimulationEngine

- 从 Accounts.advance 提取共享纯内核。
- 保证 paper account 行为零变化。
- 支持固定 end_date 的只读 research run。
- 返回日净值、信号、订单、成交和诊断。

退出条件：同 spec 新旧路径逐行一致，现有测试通过。

### Phase 2：指标和成本压力

- 加逐 fold/逐年指标、股票池等权和成本分解。
- 加 10/25/50 bps、ADV 容量和部分成交情景。
- 先输出 CLI/Markdown 报告，再决定 UI。

### Phase 3：首批三个策略

- 6-1/12-1 动量：一个主版本，一个预注册变体。
- 5/20 日短期反转：同样限制变体。
- 长趋势/绝对动量。
- 加 PeriodicTopNAllocator 和月度再平衡。

先 feasibility，再冻结参数，最后 OOS；失败也完整入库。

### Phase 4：选择和晋级

- 门禁、Pareto comparison 和 champion–challenger。
- paper challenger、人工批准和回退。
- 多策略 OOS 相关性和 sleeve 报告。

### Phase 5：扩数据后的基本面策略

- point-in-time 财务、分红和完整公司行动。
- 财务字段标准化。
- 价值、质量和盈利能力。
- 更长历史或外部归档。

## 10. 明确不建议

1. 不在五年全样本上大规模搜索后选择最高 Sharpe。
2. 不删除失败 run；试验次数本身就是统计信息。
3. 不在看过 holdout 后修改同一版本并继续称为盲测。
4. 不复制一套快速 vectorized 回测，让其与 paper account 语义不同。
5. 不在没有披露时点字段时回测财务因子。
6. 不把固定十 bps 滑点结果表述为精确可交易收益。
7. 不用今日上市名单、行业或 Prime 成分回填历史。
8. 不把不同策略 raw score 直接相加。
9. 不用复杂 regime/ML 掩盖基础策略没有独立 OOS 证据。
10. 不自动替换 champion；晋级和退役保留人工决定。

对外展示时不能把回测当实际业绩。SEC 对假设业绩要求适用性政策、底层信息和净业绩等披露；即使本个人项目不直接适用，也值得采用相同纪律：[SEC Investment Adviser Marketing](https://www.sec.gov/resources-small-businesses/small-business-compliance-guides/investment-adviser-marketing)。

## 11. 推荐的第一个切片

1. 定义 ResearchRunSpec(start, end, strategy, params, allocator, costs, manifest)。
2. 共用现有逐日推进内核，但不写 paper_orders。
3. 输出 TOPIX、股票池等权和策略三条曲线。
4. 输出逐年、成本情景和交易覆盖报告。
5. 用 technical_rating_v1 跑通。
6. 再加入一个低参数长趋势策略。
7. 固定区间比较完成后，再做自动门禁。

这个切片会同时验证研究架构、基准、成本、可复现和策略接入，不会过早引入优化器。

## 12. 主要来源

来源只用于提出可检验假设或方法，不表示在本项目日本样本中已经有效。

- [JPX J-Quants API](https://www.jpx.co.jp/english/markets/other-data-services/j-quants-api/)
- [J-Quants Stock Prices](https://jpx.gitbook.io/j-quants-pro/api-reference/daily_quotes)
- [J-Quants Financial Statement Data](https://jpx.gitbook.io/j-quants-pro/api-reference/statements_details)
- [Jegadeesh & Titman 1993](https://doi.org/10.1111/j.1540-6261.1993.tb04702.x)
- [Deflated Sharpe Ratio](https://doi.org/10.2139/ssrn.2460551)
- [Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/Papers.cfm?abstract_id=2326253)
- [Harvey, Liu & Zhu 2016](https://doi.org/10.1093/rfs/hhv059)
- [White 2000 Reality Check](https://doi.org/10.1111/1468-0262.00152)
- [Lo–MacKinlay data snooping](https://www.nber.org/papers/w3001)
- [LEAN Time](https://www.quantconnect.com/docs/v1/key-concepts/understanding-time)
- [LEAN Reality Modeling](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/key-concepts)
- [Zipline API](https://zipline.ml4trading.io/api-reference.html)

## 13. 待决策问题

1. 每次研究保存完整 SQLite/Parquet 快照，还是只做强 checksum？
2. 当前 J-Quants 计划能否取得十年以上历史、股息和财务数据？
3. 目标是选一个日常策略，还是多个策略 sleeve 的组合？
4. 可接受的最大回撤、年换手和单日 ADV 占比是多少？
5. holdout 多长，失败后等待多少新数据才允许新版本再次盲测？
6. 是否需要税务口径，还是只比较税前策略质量？

暂定默认：研究快照、10/25/50 bps 三成本情景、ADV 1% 容量、最近一年盲测、人工 champion 晋级、税前但包含佣金和滑点。
