# AI 量化对话与 Claude 研究：一手资料复核及路线比较

- 核查日期：2026-10-18（日本时间）
- 对象：[对话导出](59300645-chat_quant_investing.html)、[Claude 研究](oss-refs-relevance-research.md)、项目 [README](../README.md)、[领域模型](../CONTEXT.md)、[v1 设计](invest-assistant-v1/spec.md)。
- 方法：以下外部事实只依据数据供应商官方文档、开源项目官方仓库的配置与源码。仓库 `main`/`master` 可继续变化；价格、套餐及使用条件是核查当日状态。没有运行外部框架或验证任何策略收益。
- 本轮补充：按用户修正，调查对象是市场上可用的多类 AI 方法，而非以 Qlib + LightGBM 为中心。下述项目证明能力或接口存在，不证明在日本股票上获利。
- 阅读方式：§1 复核的是原文提出的具体事实，篇幅集中于 Qlib 是因为原文在此着墨最多，**不是候选路线的权重或推荐顺序**。§2 按相同维度比较可行路线。下文“工程成本”和适用条件是基于本仓库现状的判断，未经工时或收益实测。

## 1. 直接影响项目选择的核查结果

| 原文或隐含判断 | 核查结论 | 对本项目的含义 |
|---|---|---|
| 聊天将 Qlib + LightGBM 作为常见实现，Claude 建议先做横截面打分 | **这是一个可实施示例，不是已经验证的日本股票 alpha。** Qlib 的 Alpha158 官方示例以 CSI300 为股票池，2008–2014 训练、2015–2016 验证、2017–2020 测试；LightGBM 使用 `loss: mse` 回归未来收益，按预测分数排序的是 `TopkDropoutStrategy`，示例持有前 50、每次换 5。[Qlib 示例配置](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml) | 相同特征和标签可交给规则分数、线性与不同树模型比较；再单独试 `lambdarank` 等排序损失。不能把“回归分数用于排序”和“训练排序模型”混称。 |
| Claude 称 Qlib 基准中树模型 IC 高于各种深度模型 | **表述过满。** 官方表确有 LightGBM 优于若干模型的结果，但 CSI300 Alpha158 表里的 XGBoost、CatBoost 和 DoubleEnsemble 的 IC 分别约 0.0498、0.0481、0.0521，高于 LightGBM 的 0.0448；若干深度或混合模型也有接近的表现。Qlib 明言这是整个 workflow 的结果、不同模型调参资源有限，而且数据是中国市场。[Qlib benchmark 表及说明](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md) | 这些数字支持纳入多类候选，不支持预选 LightGBM，也不能据此否定深度模型在其他数据或目标上的价值。 |
| Claude 称 Qlib 默认标签要改为开盘到开盘 | **核对成立，但要按实际持有期定义。** 官方 Alpha158 标签为 `Ref($close,-2)/Ref($close,-1)-1`；上述示例回测 `deal_price: close`。[Alpha158 源码](https://github.com/microsoft/qlib/blob/main/qlib/contrib/data/handler.py)、[示例配置](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml) | 若在 `t` 收盘形成分数、`t+1` 开盘买入、`t+h+1` 开盘卖出，研究标签应先明确为 `O(t+h+1)/O(t+1)-1`，并处理拆合股、分红缺失、费用及无法成交的股票。不同持有期分别建标签；与 Qlib 默认收盘收益不能直接对照。 |
| Claude 建议 Light 套餐已有估值、财务摘要等数据 | **属实，但遗漏数据“何时可用于信号”。** 官方套餐表：Light 五年，含估值、财务摘要、决算日期、投资者类别买卖与 TOPIX；Standard 十年，含融资融券、卖空、EDINET；Premium 至多二十年并含分红和完整财务报表。当前标价分别是每月 ¥1,650、¥3,300、¥16,500；TDnet 加购 ¥11,000。[套餐页](https://jpx-jquants.com/ja)、[套餐/API/历史表](https://jpx-jquants.com/ja/spec/data-spec) | 可先评估 Light 现成数据的边际价值，再决定是否升级。任何成本收益判断须按购买时重新确认套餐。 |
| 财务摘要有开示日期和时刻；次交易日使用较保守 | **还需要考虑 API 入库延迟。** 官方明确 `DiscDate`/`DiscTime` 是开示时刻，**不提供数据在 J-Quants 实际可取得的时刻**；非 Premium 的财务摘要 API 按日约 18:00/24:30 更新，拥堵时可能延迟。更正开示单独保留 `DiscNo`，但供应商自身的数据修正可能追加或覆盖且无旧版。[财务摘要规格](https://jpx-jquants.com/ja/spec/fin-summary)、[更新时间](https://jpx-jquants.com/ja/spec/data-update)、[数据 FAQ](https://jpx-jquants.com/ja/help/data) | 历史模拟若用开示日 `t` 数据在 `t` 收盘出信号，可能偷看 API 当时尚未取得的数据。Light 研究至少从 `t+1` 收盘后的信号开始使用；对延迟敏感的事件策略要保存真实抓取时间，历史数据无法完全还原供应商当时的可用性。 |
| 估值指标可直接作为日级特征 | **基本可行，但有明确时点、空值和修正限制。** 估值用当日收盘价计算，财务开示不论时刻原则上从下一个营业日的估值数据开始反映；ETF 等常为 Null。供应商修正不会提供旧值。[估值指标规格](https://jpx-jquants.com/ja/spec/eq-valuation) | `t` 日估值只能参与 `t` 收盘后、`t+1` 开盘的决策；不能提前用于 `t` 开盘或盘中。要保留缺失状态，不能把现今已修订的历史估值当作精确可重放的历史快照。 |
| 决算计划和投资者类别买卖能作为特征 | **数据存在，但日期字段不等于可用日。** 决算计划 API 保留每次公布/修改的 `PubDate`，查询 `scheduled_date` 返回的是最后公布的记录，做历史研究应按 `PubDate` 复原当时已知计划。投资者类别买卖每周约第四营业日 16:30 更新。[决算予定日规格](https://jpx-jquants.com/ja/spec/fin-earnings-date)、[更新时间](https://jpx-jquants.com/ja/spec/data-update) | 不能按目标决算日直接查出历史当时的日历，也不能按交易发生周直接用投资者流向；两者都要按公布时点滞后。 |
| Claude 仅把对外持续提供分析结果列为 J-Quants 授权问题 | **限制更具体，现有研究低估了设计约束。** 官方 FAQ 称个人 API 仅限个人私用；向他人提供应用可行的列明条件是每个用户分别签约、用自己的 API key 获取数据，数据及结果仅本人可见。运营者服务器集中蓄积或中继 J-Quants 数据、用户间共享数据或分析结果是禁止案例。个人将数据输入生成 AI 须满足不被二次训练、不可由第三者阅览、生成结果不公开等条件；退订/降级后原数据及可还原原数据的派生物须删除。[使用目的与许可 FAQ](https://jpx-jquants.com/ja/help/usage) | 目前单人本地研究可继续；若产品目标转为多用户托管或将日常信号交付他人，需要先设计逐用户私有数据与密钥隔离，或洽谈合适的专业数据许可。LLM 输入原始行情与财务时还要符合 FAQ 条件。 |
| Claude 称 FinRL 教学代码有数据泄漏和成交口径问题 | **源码支持，且应限于所指实现。** `FeatureEngineer.clean_data` 按整段数据透视后删去任何缺失收盘价的股票，造成历史股票池的事后筛选；`preprocess_data` 最后全表 `ffill().bfill()`，会把未来值回填到前面的空值。股票交易环境的状态包含当日收盘价，`_buy_stock`/`_sell_stock` 用同一状态价格结算，和本项目收盘信号、次日开盘成交不一致。[FinRL 预处理器](https://github.com/AI4Finance-Foundation/FinRL/blob/master/finrl/meta/preprocessor/preprocessors.py)、[交易环境源码](https://github.com/AI4Finance-Foundation/FinRL/blob/master/finrl/meta/env_stock_trading/env_stocktrading.py) | 这些是对该教学实现的反例，不能外推“强化学习必然泄漏”。若将来实验 RL，要在现有交易引擎上建环境，不能直接拿该环境的成绩作日本股票策略证据。 |
| Claude 建议借鉴 TradingAgents 的逐决策评分，并认为历史 LLM 回测不可信 | **逐决策评分属实；“所有 LLM 历史回测必然无效”过于绝对。** 官方源码明确逐 `(ticker,date)` 评价评级，不模拟资金账本；从分析日后首个收盘开始算固定持有期的相对基准收益，并承认文本源没有归档、每格只采样一次，结果仅有提示性、不可精确复现。[TradingAgents backtest](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/backtest.py)、[settlement](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/memory/settlement.py) | 可借“信号质量”和“组合净值”分开评价的结构，但项目实际回放应从次日开盘起计收益。模型权重形成于历史测试期之后且文本未归档时，无法证明点时有效；事先冻结模型与资料后做前瞻模拟更可信。 |

## 2. 同口径比较可行路线

先区分**研究问题**与**实现工具**：规则、回归/排序、时序预测、文本事件和动态仓位解决的任务不同；Qlib 是研究平台，LightGBM 是其中可用的一种模型，两者不构成必须绑定的路线。Qlib 官方自身支持监督学习、市场动态建模和强化学习；其示例基准没有对日本股票、当前股票池及次日开盘成交做比较。[Qlib 项目说明](https://github.com/microsoft/qlib)、[基准说明](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md)

比较口径：每条路线都记录 (1) 数据来源、时间戳和可用时点，(2) 具体预测或决策对象，(3) 是否能接入同一股票池、组合规则、次日开盘成交和成本压力测试，(4) 可解释和审计的内容，(5) 依赖、算力、试验次数与维护成本，(6) 拟解决的目标。以下“较低/较高”仅是相对当前仓库的实施成本判断，不能代替原型实测或样本外成绩。

| 路线及适用目标 | 数据与点时前提 | 模型或规则、解释性 | 回测/执行接入与主要成本 | 现阶段待证实之处 |
|---|---|---|---|---|
| 已有 OHLCV 规则及新规则：可解释的选股/择时基线 | 现有日线、历史股票池；逐项审计调整价和预热窗口 | 固定动量、反转、趋势等，阈值与每笔理由可复查；迭代过多仍会过拟合。[本项目 05 候选](invest-assistant-v1/issues/05-three-ohclv-strategy-candidates.md) | 已接现有策略与账户；补周期再平衡、容量与成本场景，新增外部依赖少 | 三类策略已被看过全样本，尚缺真正未见区间的证据 |
| 线性/稀疏模型：检验少量特征的增量与方向 | 与树模型使用相同的点时价量或估值特征、标签及日期折 | Ridge 等带正则化的回归可输出系数；系数依赖特征尺度与共线性，不等于因果解释。[scikit-learn Ridge](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html) | 可用独立训练器输出分数到现有 `priority`；须保存各折预处理器和模型；工程成本相对较低 | 是否比固定规则带来净收益增量，而非仅提高拟合或 IC |
| 树模型：表格特征非线性/交互 | 同上；类别特征另需历史分类、缺失与时点处理 | LightGBM、XGBoost、CatBoost 均可做回归或排序；特征重要性是诊断而非因果说明。[LightGBM 参数](https://lightgbm.readthedocs.io/en/latest/Parameters.html)、[XGBoost 排序](https://xgboost.readthedocs.io/en/stable/tutorials/learning_to_rank.html)、[CatBoost 回归](https://catboost.ai/docs/en/concepts/python-reference_catboostregressor)与[排序](https://catboost.ai/docs/en/concepts/python-reference_catboostranker) | 与线性路线共用特征、标签和执行；增加依赖、调参自由度和训练/推断记录；Qlib 可做离线对照，也可不用 | 哪一种库、哪一种损失在日本样本的**净组合结果**更稳健；Qlib 中国市场表不能回答 |
| 深度时序：检验跨日期序列结构是否有增益 | 连续且有覆盖记录的时序、严格训练截止日；若预测股票收益，仍需对齐每天可交易的截面 | Time-Series-Library 提供多类时序模型；解释和诊断需另设计。[官方仓库](https://github.com/thuml/Time-Series-Library) | 可输出同样的候选分数后接共同账本；训练、种子、硬件与监控成本较高 | 在当前约五年日线下能否超过简单模型；不能凭 Qlib 中某个中国市场模型的单项 IC 预先否决 |
| 图模型：检验公司/行业关系的增量 | 需历史时点有效的边和节点；行业归属可作简单起点，持股等关系需另取数且记录公布时点 | PyG 的 GATConv 明确接受节点特征、边索引及可选边特征；注意力权重不自动等于投资因果解释。[PyG 文档](https://pytorch-geometric.readthedocs.io/en/latest/generated/torch_geometric.nn.conv.GATConv.html) | 个股分数可进入共同账本；构造点时图、消融无边模型和维护关系数据的成本较高 | 关系信息在日本股票样本是否提供超出同样输入特征的净增益 |
| 概率预测/市场形势：估计风险或状态 | TOPIX、行业或组合序列；滚动拟合，状态概率只用当时可见数据 | GluonTS 支持概率预测与区间；statsmodels 提供 Markov switching，状态解释与稳定性要单独检验。[GluonTS](https://github.com/awslabs/gluonts)、[statsmodels](https://www.statsmodels.org/stable/generated/statsmodels.tsa.regime_switching.markov_regression.MarkovRegression.html) | 先检验概率校准、覆盖率和风险决策增益；若用于限仓，再走共同成交账本；中等到较高成本 | 风险预测是否改善回撤/效用，不能拿选股 Rank IC 当同一目标比较 |
| 扩散/生成情景：概率路径或压力试验 | 多变量历史序列与冻结训练期；生成样本仍源于所用历史，不能充当新的独立市场证据 | TimeGrad 原始论文研究多变量概率时序预测；它与通用图像/视频 Diffusers 框架不是同一件事。[TimeGrad 论文](https://proceedings.mlr.press/v139/rasul21a/rasul21a.pdf)、[Diffusers 项目](https://github.com/huggingface/diffusers) | 先比较预测分布校准或压力场景覆盖；如据此调仓，再通过共同成交账本；训练与验证成本较高 | 合成路径是否覆盖真实尾部风险，是否改善风险决策，而非只是生成看似真实的图表 |
| 日文开示/文本事件与 LLM 复核：发现事件、补解释 | 需有可用时刻、归档文本、模型版本/训练截止与合法使用范围；J-Quants 财务 API 不提供实际入库时刻。[财务规格](https://jpx-jquants.com/ja/spec/fin-summary)、[使用 FAQ](https://jpx-jquants.com/ja/help/usage) | 先比较关键词/结构化事件与日文模型或通用 LLM；逐决策理由可审查，但须核验引用和日文任务表现。[TradingAgents 代码](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/backtest.py) | 事件信号可进共同账本；文本存档、许可、调用费用和重复性成本较高 | 对净收益、风险提示或解释质量是否有独立增益；不能由英文模型卡推定日文效果 |
| 强化学习/动态调仓：优化连续仓位决策 | 需定义历史可见状态、动作、奖励和足够多样的独立市场情境 | FinRL 给出训练环境范例；所核查的教学环境与本项目成交口径不同。[FinRL 环境源码](https://github.com/AI4Finance-Foundation/FinRL/blob/master/finrl/meta/env_stock_trading/env_stocktrading.py) | 若尝试，应把现有模拟引擎包装为环境，并在同样约束下与固定组合规则比较；训练和评估成本高 | 现有历史长度、成本与市场状态是否足以支持可迁移策略；教学实现的问题不构成对 RL 方法的否定 |
| 自动因子发现：扩大候选来源 | 与被发现因子的点时数据前提相同；须记录所有尝试 | RD-Agent 提供量化因子/模型研发流程，生成表达式后仍可独立审查。[官方仓库](https://github.com/microsoft/RD-Agent) | 生成器可接任一模型家族；大量搜索增加多重试验与复现负担 | 是否能在完整记录搜索次数后优于少量预先声明的因子 |

这些路线拥有**同等进入候选池的资格**，不是同等成熟度或预计收益。近期可并行验证“规则、线性、树”三种选股假设；风险预测、文本事件和动态调仓各有独立评价目标，达到其数据与审计前提后也可提出预注册实验。平台选择另行比较：现有内核、Qlib 离线研究或其他工具必须按日本数据接入、时点语义、账本一致性和维护工作量评估，不能把平台 benchmark 当策略胜负。[Qlib 项目说明](https://github.com/microsoft/qlib)、[现有领域模型](../CONTEXT.md)

### 2.1 新补查的两条独立路线

这两类不能被“LightGBM 的另一个超参数”或“Qlib 的另一个示例”替代，应各自定义任务和比较基线；它们也不因新颖而自动优先。

| 路线 | 一手资料所能证明 | 本项目可检验的具体问题 | 主要防错条件 |
|---|---|---|---|
| **自动集成／模型组合** | AutoGluon-TimeSeries 的官方示例同时拟合统计、树、预训练模型，再用留出的验证窗口组合预测；这是预测工作流的能力示例，不是日股收益结果。[AutoGluon 入门](https://auto.gluon.ai/stable/tutorials/timeseries/forecasting-quick-start.html)、[集成文档](https://auto.gluon.ai/dev/tutorials/timeseries/forecasting-ensembles.html) | 对相同选股任务，先比较预注册的单模型与等权分数，再用早期验证折学习组合权重；所有分数进入同一成交账本。另可用预测波动的多个模型集成检验风险决策。 | 基模型须对每个决策日有真正折外预测；成员选择与权重拟合只能用更早数据。保留所有基模型、折、权重和搜索次数，否则集成会叠加选择偏差。 |
| **预训练时序基础模型／零样本迁移** | Chronos-2 提供单／多变量及协变量预测接口；TimesFM 提供预训练预测接口及分位数输出。它们是时序预测器，不是已经验证的股票买卖策略。[Chronos-2 官方接口](https://github.com/amazon-science/chronos-forecasting/blob/main/src/chronos/chronos2/pipeline.py)、[TimesFM 官方接口](https://github.com/google-research/timesfm/blob/master/timesfm-forecasting/references/api_reference.md) | 冻结模型版本与输入，在相同日股数据上分别比较下一期收益、波动或风险预测相对简单统计／规则及从头训练模型的增量；若转为选股或限仓，再经同一交易账本验证。 | 必须核实预训练语料及模型发布时间。若历史测试期早于发布且无法排除训练数据重叠，不能宣称严格点时样本外；可标为探索性并优先开展冻结权重后的前瞻观察。未来协变量只可填当时已知值。 |

这些是基于官方接口提出的实验设计推论，不是官方声称有日本股票 alpha。若平台层需要比较，现有内核、Qlib、AutoGluon、Darts／NeuralForecast 等各有不同覆盖：例如 Darts 提供统计到神经网络的共同预测 API 与历史预测工具，NeuralForecast 提供多类神经预测模型；平台“能跑通预测”不等于满足本项目的历史股票池、次日开盘成交和授权要求。[Darts 官方仓库](https://github.com/unit8co/darts)、[NeuralForecast 官方仓库](https://github.com/Nixtla/neuralforecast)

## 3. 进一步研究与实施边界

1. **先固定任务与共同评估口径。** 项目策略在收盘给出信号，次日开盘尝试成交；选股实验需按持有期、股票池和开盘成交条件定义标签。用个股预测误差或 IC 不能替代含成本、容量、持仓限制、退市与拆合股的组合净值。风险预测另看区间覆盖和真实风险决策结果，文本复核另看事件识别和解释质量，不能强迫所有路线只争一个 IC。[Qlib benchmark 说明](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md)、[TradingAgents backtest](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/backtest.py)、[GluonTS](https://github.com/awslabs/gluonts)
2. **让第一轮候选的比较小而完整。** 按现有 `CONTEXT.md` 的股票池与策略接口，在相同日期、点时价量特征、持有期、组合和费用下比较已有规则、新规则、Ridge、LightGBM、XGBoost 或 CatBoost 的有限预注册版本。各方法可输出分数用于候选排序；记录每个版本、训练截止日、输入副本/指纹、模型文件及研究配置。树模型之间与线性/规则之间均没有预定赢家。是否加入估值或财务应作为另一个可检验的数据增量问题，取决于时点数据是否合格。这是实施建议，不是外部来源已证明的收益。
3. **示例结果仅作机制证据。** TradingAgents 的逐格评级、FinRL 所核查环境的同日收盘结算、Qlib 中国股票示例的收盘成交，均与本项目账本和日本交易制度不一致；没有一项能够证明其他路线在本项目无效。[TradingAgents backtest](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/backtest.py)、[FinRL 交易环境](https://github.com/AI4Finance-Foundation/FinRL/blob/master/finrl/meta/env_stock_trading/env_stocktrading.py)、[Qlib 示例配置](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml)

## 4. 未经本次验证的事项

- 聊天里的“AI 能做八大应用”是功能分类，不是这些应用能产生可交易超额收益的证据；所列模型/项目是实现线索，不是日本市场的实证结果。
- Claude 文档中仓库最新版本号、维护状态和许可证逐项未在本次复核，属于容易变化的信息；实现前应按锁定提交再检查。本文仅核查对当前路线影响最大的源代码行为和供应商条款。
- 尚无日本股票的模型训练或样本外比较；因此不能把 Qlib 官方中国市场 benchmark 的 IC 或收益数字外推到本项目。
- 也没有在本项目中测量规则、线性、三种树、深度时序、风险预测、文本或 RL 路线的准确率、净收益、风险改善、资源消耗与维护工时；§2 成本等级只是实施估计，不能据此形成排序。

## 5. 对话内容审查

这份 HTML 自述「部分较长回答为内容摘要，不是逐字原文」，且有两次空白用户消息。因此只能审查导出文件中**实际可见的主张**，不能推断原对话遗漏了什么。FinGPT、FinBERT 的 Hugging Face 链接被导出为 `https://hu` 加剩余文字，点击会去错误地址；原址应分别为 `https://huggingface.co/FinGPT` 与 `https://huggingface.co/ProsusAI/finbert`。这些是导出质量问题，不是投资研究结论。

| 对话中的说法 | 审查 | 对项目的处理 |
|---|---|---|
| 「想法→特征→信号→回测→风控→组合→实盘」 | 教学概括基本成立，但此项目没有实盘下单，回测也不能独自证明可交易的超额收益。 | 保持项目的「研究运行→前瞻模拟」边界；收益论断以含成交约束的账本为准。 |
| AI 的「八大应用」、七组技术路线 | 是功能清单。清单混放了模型（XGBoost）、框架（Qlib、LangGraph）、研究原型（TradingAgents）和商用模型（GPT、Claude），没有给出日本股票有效性的证据。 | 先按项目的具体任务筛选：可得数据、当时可用时间、是否改变候选排序、能否用现有账本检验。 |
| Qlib + LightGBM 是一种实现，树模型适合表格特征 | 它提供一条可实施路线，但对话连续几轮锚定平台和单个模型，没有解释与规则、线性、其他树库和其他研究任务的比较；Claude 又把 Qlib 的回归示例称为排序模型；见 §1。 | 平台与模型分别选；同一选股任务共用数据、标签、日期切分和执行，其他任务使用事先声明的专属指标；候选条件见 §2。 |
| 深度时序、RL、多智能体、GNN、扩散模型都有开源实现 | 「有代码」大体成立，但训练数据、模型权重、许可证、日文能力和日股适配要逐项核验；GPT/Claude 主模型闭源，对话对此已有提示。 | 不把 GitHub 仓库清单当成实施路线或收益证据。 |
| FinBERT/FinGPT 可分析财报、新闻 | 对英语或特定训练任务有实现；对话没有提供日文开示的评测。Claude 的「读不了日文」也说得太绝对，准确说法是**所列模型没有经核验的日文金融开示能力**。 | 只有取得带可用时点的日文语料后，才比较通用模型、日文模型和关键词基线。 |

日本市场也不宜照搬美国或中国动量研究结论。原始日本市场研究报告过平均动量收益偏低，也有研究找到特定条件下的动量效应；两者都不足以判定本项目的 Prime、流动性门槛、次日开盘执行策略会盈利。[日本动量与市场动态研究](https://onlinelibrary.wiley.com/doi/10.1111/irfi.12024)、[日本残差动量研究](https://www.sciencedirect.com/science/article/abs/pii/S0927539817301093)。

## 6. 对 Claude 研究的修订意见

原研究最有价值的是按用途指出若干框架的边界、Qlib/FinRL/TradingAgents 的成交口径差异，以及把数据与检验放在模型之前。它的 §5 第 1 步「先补检验管线」应保留；原文 §2 表格的「Qlib + LightGBM 现在做」和 §5 将其他路线排在它之后，是**未用同一日本数据与实验契约比较就预设次序**。应改为：检验管线完成后，按 §2 将规则、线性和多个树模型作为同一选股任务的候选；其他目标路线在满足各自数据前提后独立提案。具体修订如下。

| 优先级 | 原研究位置 | 需要修订的地方 |
|---|---|---|
| 高 | §1、§2、§5 第 3/6 步 | 以中国 CSI300 的 Qlib 示例、仓库存在与接入容易为依据，将 Qlib + LightGBM 排为首选，并把深度模型、文本、RL 等排到它成功之后。来源只能证明能力或示例结果，没有同口径日本样本外净收益、风险改善、工程成本实测。Qlib 是平台选择，LightGBM 是模型选择，须分别决策；路线比较见本文 §2。 |
| 高 | §4.2 `TimeSeriesSplit`、§5 第 3 步 | `gap` 单位是**样本行**，而日股面板一天有许多证券行。直接对按 `(date, code)` 排序的长表调用 `TimeSeriesSplit(gap=5)`，只会跳过 5 只股票附近的行，无法留出 5 个交易日。应先按**交易日**生成滚动训练/验证窗口，再映射到当日全部证券；按每个标签的实际结束时间剔除跨越边界的训练样本。scikit-learn 文档也要求时间样本等间隔才能使折间指标可比。[官方文档](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html) |
| 高 | §4.1、§5 第 3 步 | 「开盘到开盘」仍缺持有期、退市和未成交定义。若在 `t` 收盘打分、`t+1` 开盘买入、持有 `h` 个交易日到 `t+h+1` 开盘，标签才是相应的开盘收益；若实际按月换仓或提前退出，单一固定标签和组合收益不同。先锁定交易策略，再定训练目标。 |
| 高 | §5 第 3 步 | ADR-0005 的研究输入指纹只能发现输入变了，**不能在行情覆盖更正后恢复训练数据**。模型比较还需保留实验用不可变输入副本、特征与标签生成版本、股票池、每折训练截止日、模型文件和依赖版本。现有 [ADR-0005](../docs/adr/0005-freeze-data-per-research-experiment.md) 已明确此限制；长期保留的方式另做设计决定，并遵守 J-Quants 的退订/降级删除要求。 |
| 高 | §3、§5 第 2/5 步 | J-Quants 使用许可及 API 发布时间约束比原文写得具体；见 §1 的官方 FAQ 与更新时刻。尤其不能把 `DiscTime` 直接视为 API 当时已经可抓到，更不能默认个人套餐支持多用户托管或把原始数据送入任意 LLM 服务。 |
| 中 | §4.1、§5 第 3 步 | 「Alpha158 特征清单可以直接当日本股票第一批特征」缺逐项时点审计。本项目 [MarketFrame](../backend/app/market_data/frame.py) 的研究价格和成交量会受**查询时已知、但历史信号日尚未发生**的拆合股系数重标定；相对比率类特征通常可抵消共同缩放，绝对价格/成交量特征不能直接假设无泄漏。先审计公式及供数时点，再选少量尺度无关特征；相同特征应向线性与树候选开放。 |
| 中 | §4.1、§5 第 1 步 | 逐决策收益、IC/Rank IC 是诊断预测排序；它们与 100 股整手、仓位、现金、成本、涨跌停、退市后的**可执行净收益**不是同一个指标。Qlib 与 TradingAgents 自己也把信号评价和组合回测分开；见 §1。 |
| 中 | §4.1、§5 第 5 步 | 「LLM 只能从今天往后跑」过于绝对。训练期与回测期重叠会污染结果；若模型版本/训练截止日、当时文本及工具输出可证明均早于测试区间，之后的严格历史样本外评估也有意义。公开商用模型的训练组成往往无法充分审计，因此**本项目优先前瞻验证**是审慎的实施判断。[原始研究：LLM 回测中的前视偏差](https://arxiv.org/abs/2309.17322) |
| 中 | §4.4 FinRL | 所列四个坑经所指教学源码核实，但不等于强化学习方法本身不成立。「百万次交互」指优化训练交互次数，不等于百万个独立市场日；反复回放 1,237 天也不会生成新的市场历史。是否研究 RL 应由动态仓位任务是否必要、可用的独立市场状态和真实成交约束决定，不能以 LightGBM 先成功为前置条件。 |
| 低 | §4 的版本、最新提交、许可证 | 这些信息可能快速变化；模型卡、具体文件或某次 GitHub API 查询不能概括全部同名模型。选型时锁定仓库提交和模型卡，再复核许可证；此报告没有逐项复验原表的全部 28 个项目。 |

## 7. 与当前仓库相符的下一轮研究实验

仓库截至核查时的只读查询：`var/invest.db` 有 5,350,731 条日线记录，2021-09-24 至 2026-10-16，共 1,237 个有股票日线的交易日。代码中股票池是当天 Prime 普通股、20 日平均成交额至少 ¥5 亿，并要求当天可交易；策略在收盘评估，订单下一开市日开盘尝试执行。[股票池代码](../backend/app/market_data/market.py)、[策略接口](../backend/app/strategies/base.py)、[模拟成交](../backend/app/accounts/session.py)。这些数字只是本地数据库现状，不代表全时段完整可用的独立样本数。

1. **先修好现有候选的评估。** [05 号任务及其 2026-10-06 评论](invest-assistant-v1/issues/05-three-ohclv-strategy-candidates.md) 记载：三类 OHLCV 策略已接入模拟账户，但 `PeriodicTopN`、ADV20 成交容量、10/25/50 bps 成本情景、分阶段检验和报告均未完成；而且这些策略的全样本结果已经被看过。同一段历史以后仍可用于诊断和开发，不能再称为这些现有版本的一次真正盲测。对冻结版本的前瞻模拟要另记起始日与判定门槛。
2. **冻结可比较的实验契约。** 固定每日还是每月决策、股票池、预测持有期、权重/退出规则、整手与未成交处理、基准、成本是单边总成本还是额外滑点、ADV20 上限；同一契约运行现有规则与模型。报告每个交易日的横截面 Rank IC、分组收益和覆盖率，同时给出净值、相对 TOPIX 与同池等权收益、换手、回撤、成交率和容量。单个 IC 数值不能作为晋级门槛。
3. **预注册同任务挑战集和资源预算。** 先固定少量经时点审计的价量比率特征与一个主要持有期：已有规则、新 OHLCV 规则、Ridge、LightGBM 回归，以及 XGBoost/CatBoost 中至少一个预先选定的其他树模型，各给相近的调参预算；排序损失如 `lambdarank`/`rank:ndcg` 可作为后续独立问题，不能与回归目标混称。若计算预算不足，分批试验但锁定同一输入、窗口、执行口径，记录未运行的候选，而不是先宣布某一库胜出。用**按日期**滚动窗口：所有同日证券在同一折；训练只用标签结束时间早于训练截止的记录；参数只在验证折选择；各训练折内拟合标准化和缺失处理。预先登记所有尝试、失败结果、数据窗口和选型规则。搜索越多，偶然找到好看的回测越容易；[回测过拟合原始研究](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253) 与 [Deflated Sharpe 原始研究](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551) 均支持披露搜索强度。
4. **把数据扩展和其他目标路线独立成实验。** 保留同一已冻结模型或规则与验证方法，仅增加 Light 估值来测数据增量；财务摘要、决算计划和投资者流向先建 `available_from`/抓取时间层，再分别测覆盖率与增益。历史修正及 API 可用时刻不能还原时标明探索性。若目标是风险决策，先比较固定 TOPIX 波动/形势规则与概率预测的校准及限仓效果；若目标是文本事件，先比较关键词和模型/LLM 在已归档日文开示上的识别效果及成本。动态仓位或自动因子发现可在状态/动作语义与完整试验记录具备后提出实验，不依赖树模型先获得好成绩。数据需求明确时再决定是否订阅更高套餐。
5. **按目标决定是否采用，而不只看一个胜负指标。** 选股路线在冻结的前瞻观察期内，需要足够交易样本、合格数据/成交质量和相对简单基线的稳健含成本收益；风险路线要证明风险指标与净组合结果改善；文本复核需证明事件质量或审计价值，并度量费用。结果不足标 `insufficient_evidence`；复杂路线若不能补足证据，继续研究而不因示例框架或高 IC 晋级。人工确认常用模拟账户的采用范围。

**仍未解决的研究问题：** 按 100 股整手及现有流动性门槛，实际可参与排序的日均证券数、各持有期有效标签比例、退市/停牌造成的删失、行情修正频率、不同基准的分红处理，以及 Light 财务历史能否满足预期的点时精度，均需在训练前做数据剖面。还需明确各路线的计算与维护预算、风险目标、日文开示样本和审查标准、以及是否值得接 Qlib 离线工具。此次审查没有训练模型，也没有对日本市场策略收益作新测算。
