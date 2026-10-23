# 聊天记录里全部 AI 量化项目对 invest-assistant 的用处

- 调查日期：2026-10-18（第三版：保留聊天中的仓库调查，扩展市场上其他 AI 路线）
- 范围：聊天记录 `chat_quant_investing.html`（以下简称「聊天」）里提到的 7 组 28 个仓库／模型，加上 Qlib、自动因子路线，以及另行核查的表格 AutoML、时序基础模型、日文金融 NLP、FinRL-X 和时间序列生成模型。不是市场产品的穷尽清单。
- 评判标准：**这个项目能不能帮软件给日本股票提供更好的投资策略，帮在哪个环节**。环节包括数据和特征、因子挖掘、信号或预测模型、组合与仓位、风控、回测评估、解释和交付给用户。[spec.md](invest-assistant-v1/spec.md) §1 的「不做机器学习」、只用 J-Quants 日线，以及 [CONTEXT.md](../CONTEXT.md) 里「策略 = 固定规则」，都只是现状和改动成本，不当否决理由。真正的障碍照实写：样本量、过拟合、未来数据泄漏、大模型训练数据里带着「未来」、算力、数据和 API 成本、对日本市场是否适用。
- 来源：`oss-refs/` 下 6 个已克隆仓库读源码；其余项目读官方 README、文档、原作者论文或发布者的 Hugging Face 模型卡，原版版本和许可证查 GitHub API（`api.github.com/repos/<名字>`，2026-10-18）。本次**没有新克隆仓库**：Qlib 的几个源码文件是从 `raw.githubusercontent.com` 单独下载阅读的。没有安装或运行任何候选，也没有对日本股票作收益验证。下文把「项目事实」与「本项目判断／假设」分开。

## 1. 结论

1. **没有证据能预先选定 Qlib + LightGBM。** Qlib 是可运行多种模型的研究平台，不是一种策略；LightGBM 是候选学习器，不是完整的信号、组合和成交规则。其[官方模型榜单](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md)在中国 CSI300 的 Alpha158 表中，XGBoost、CatBoost、DoubleEnsemble 的 IC 都高于 LightGBM；不同模型还使用 Alpha158 或 Alpha360、部分只取 20 个特征，不能据此排出日本股票的优劣。横截面打分确实容易通过现有 `Judgement.priority` 接入，但线性／稀疏模型、树模型、神经网络、自动因子生成都应在相同任务和点时数据下竞争。时序预测、文本事件、风控、动态调仓则是**不同任务**，先定义各自成功指标，不能只按选股 IC 排名。
2. **数据比模型更卡脖子，而且比原先以为的宽。** 现在用的 J-Quants Light 套餐其实已经包含每日估值指标（PER、PBR、ROE、市值）、财务摘要（带开示日期和时刻）、决算发表预定日和投资者类别买卖。升级到 Standard（每月 3,300 日元）可以把历史从 5 年拉到 10 年，并加上融资融券和卖空数据（见 §3）。原来 [strategy-research.md](invest-assistant-v1/strategy-research.md) §4「是否在 Light 套餐内待确认」这一条，现在已经有答案。
3. **文本／LLM 不应只限于“解释层”，也不能拿普通历史回放直接证明交易有效。** 可检验的任务包括从日文开示抽取事件、实体和数值，形成开示后才生效的特征，以及固定输入快照、模型版本和提示词的候选评级。已有[日文金融预训练 BERT](https://huggingface.co/izumi-lab/bert-small-japanese-fin)和[日文金融情绪分类器](https://huggingface.co/bardsai/finance-sentiment-ja-base)，所以原先“现成模型读不了日文”的笼统断言不成立；但它们也未经本项目的 TDnet 文本、延迟和收益检验。对事后训练的通用 LLM，历史决策是否泄漏训练期未来事实通常难以审计；真正的交易效果以事先冻结的前瞻 paper 记录为强证据。
4. **深度时序／时序基础模型、图关系、强化学习、概率预测和生成式情景同等进入候选池，但所需前提不同。** 例如 Chronos-2、TimesFM、Moirai 输出的是预测或分布，并不自动构成选股；PyG 只是图学习库，若无点时关系边就没有可检验的持股图假设；FinRL/FinRL-X 是环境／架构示例，不能替代本项目的日本市场成交模型；TimeGAN 生成的是合成序列，宜先考察压力测试覆盖率而非当作真实样本。[Chronos](https://github.com/amazon-science/chronos-forecasting)、[TimesFM](https://github.com/google-research/timesfm)、[Moirai](https://github.com/SalesforceAIResearch/uni2ts)、[PyG](https://github.com/pyg-team/pytorch_geometric)、[FinRL-X](https://github.com/AI4Finance-Foundation/FinRL-Trading)、[TimeGAN](https://github.com/jsyoon0823/TimeGAN) 均是相关的一手项目说明；它们都不是日本股票超额收益的证据。

## 2. 按研究任务分的候选池（不是效用排名）

| 要验证的假设／输出 | 可比的模型或方案（一手入口） | 日本股票的最低输入／检验边界 | 现阶段状态 |
|---|---|---|---|
| 同日横截面排序分数 | 线性／Elastic Net、随机森林；[LightGBM](https://lightgbm.readthedocs.io/en/latest/Parameters.html)、[XGBoost](https://xgboost.readthedocs.io/en/stable/tutorials/learning_to_rank.html)、[CatBoost](https://catboost.ai/docs/en/concepts/python-reference_catboostranker)；[AutoGluon Tabular](https://auto.gluon.ai/stable/api/autogluon.tabular.models.html) 集成；MLP、Qlib 的 TRA／HIST | 同一历史成分股、同一特征和 t+1 开盘可实现标签；按时间滚动重训，比较 Rank IC 与扣费后净值 | 所有模型未在本项目验证；Qlib 只是可选实验平台 |
| 单只／多只价格、波动或风险分布 | [Time-Series-Library](https://github.com/thuml/Time-Series-Library)、TFT／DeepAR；预训练 [Chronos-2](https://github.com/amazon-science/chronos-forecasting)、[TimesFM](https://github.com/google-research/timesfm)、[Moirai](https://github.com/SalesforceAIResearch/uni2ts)；托管 API [TimeGPT](https://github.com/Nixtla/nixtla) | 预测目标、频率和 horizon 必须与可成交价格匹配；先同朴素预测比较校准、分位损失和尾部风险，再检验交易效益。API 路线另核费用、输入数据使用权和可复现快照 | 通用时序榜单不能直接转为日股选股证据 |
| 开示／新闻引发的事件信号 | [日文金融 BERT](https://huggingface.co/izumi-lab/bert-small-japanese-fin)、[日文情绪分类器](https://huggingface.co/bardsai/finance-sentiment-ja-base)、通用日文 LLM、FinGPT／FinBERT；独立决策工作流 [TradingAgents](https://github.com/TauricResearch/TradingAgents)、[FinRobot](https://github.com/AI4Finance-Foundation/FinRobot) | 需有文本取得／开示时间、修订历史、证券映射与合法使用权；先测事件抽取正确率，再测事件后净收益。Agent 工作流须记录工具响应和所有数字来源 | 日文现成模型存在；对本项目语料及交易无验证 |
| 股票之间的传播或关联 | [PyG](https://github.com/pyg-team/pytorch_geometric) 的 GAT／异构图模型、Qlib HIST／IGMTF；行业分组的非图基线 | 点时行业、持股／供应链等边；不得把未来关系补回历史 | Standard 的 EDINET 数据可能支持探索；现无可用点时关系图 |
| 仓位、换手与执行时序 | FinRL／[FinRL-X](https://github.com/AI4Finance-Foundation/FinRL-Trading)、SB3／RLlib；也可用规则与优化器 | 同一日本股环境、一手、成本、停牌、拆合股、退市、容量约束；多随机种子与样本外 | 环境先要等价；RL 不是默认劣于树模型，而是比较任务不同 |
| 因子、模型或实验自动发现 | [RD-Agent(Q)](https://github.com/microsoft/RD-Agent)、AutoML／AutoGluon、符号回归／遗传编程 | 试验预算和搜索轨迹完整登记；一次性盲测，防反复试出幸运因子 | 生成候选的工具，不提供有效性的证明 |
| 合成情景与压力测试 | [TimeGAN](https://github.com/jsyoon0823/TimeGAN)、时序扩散研究原型 | 只用训练期拟合生成器；先看联合分布、极端情形及相较历史／bootstrap 的增量 | 合成路径不是独立历史样本，也非直接买卖策略 |

**分类轴不能混用。** Qlib、FinRL-X、AutoGluon、LangGraph、FinRobot 是平台／框架；LightGBM、Chronos、GAT、日文 BERT 是模型；J-Quants／TDnet 是数据来源，TimeGPT 是外部预测服务；“按分数买前 N 只”“开示后事件交易”“概率预测控制仓位”才是可检验的策略假设。同一平台可以装多种模型，同一模型也可以服务不同任务；仓库存在、官方自报榜单和回测胜出是三个不同层级的证据。[Qlib 模型目录](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md)、[FinRL-X 组件说明](https://github.com/AI4Finance-Foundation/FinRL-Trading)、[AutoGluon 集成文档](https://auto.gluon.ai/stable/api/autogluon.tabular.models.html)。

## 3. J-Quants 能补什么数据（官方页面，2026-10-18）

| 套餐（月费） | 历史 | 比下一档多出的数据 |
|---|---|---|
| Light（1,650 日元，现用） | 5 年 | 日线、上市名册、**估值指标**、**财务摘要**、**决算发表预定日**、交易日历、**投资者类别买卖**、TOPIX |
| Standard（3,300 日元） | 10 年 | 其他指数、日经 225 期权、融资融券余额、行业卖空比例、卖空余额报告、EDINET 大股东／**交叉持股**／大量持有报告 |
| Premium（16,500 日元） | 20 年（自 2008 年） | 前场行情、**分红**、**财务报表（BS/PL/CF）**、期货期权、买卖明细 |
| 加购 | 5 年 | TDnet 适时开示（每月 11,000 日元）；分钟线和逐笔数据（2 年，每月 5,500 日元） |

出处：[J-Quants 首页套餐表](https://jpx-jquants.com/?lang=ja)，[各套餐可用 API 与数据期间](https://jpx-jquants.com/ja/spec/data-spec)。

和「不偷看未来」有关的官方说明：

- 财务摘要带开示日 `DiscDate` 和开示时刻 `DiscTime`。更正开示会拿到新编号，旧记录保留。但官方**不提供**「这条数据在 J-Quants 上可以取到的时间」（[fin-summary](https://jpx-jquants.com/ja/spec/fin-summary)）。判断：保守起见，开示日的下一个交易日才开始用。
- 估值指标用当天收盘价计算，财务开示原则上从下一个营业日起反映（[eq-valuation](https://jpx-jquants.com/ja/spec/eq-valuation)）。
- **使用限制**：「本データを用いて投資分析した結果を継続反復して第三者に提供・配信する行為も禁止」（用这些数据做的投资分析结果，不能持续反复提供给第三方；出处同首页 FAQ）。同一条 FAQ 也说，公开自己的分析结果或分析方法是可以的，禁止的是分发数据本身，以及持续反复地向第三方提供分析结果。只要软件以后要把策略持续交付给作者本人以外的人，这一条必须先解决。

## 4. 逐路线说明（不对应高低优先级）

### 4.1 横截面排序：Qlib 是平台，树模型只是一个家族

**Qlib 示例：有用的设计参考，不是默认产品栈**

事实：

- Qlib：MIT，v0.9.8（2026-10-08），由微软维护。
- 示例流程 `examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml`：
  - 特征是 Alpha158，即 158 个人工设计的价量特征；
  - 用 2008–2014 年训练、2015–2016 年验证、2017–2020 年测试；
  - 组合用 `TopkDropoutStrategy`，持有前 50 只，每次最多换掉 5 只。
- 成交模型 `qlib/backtest/exchange.py` 支持：一手股数 `trade_unit`、用表达式判断涨跌停 `limit_threshold`、成交量上限 `volume_threshold`、买卖费率和最低费用。
- 内置市场只有中国、美国、台湾（`qlib/config.py`）。
- 官方数据集「disabled temporarily」，暂停提供（README）。

能借鉴（判断）：

- Alpha158 的特征清单（`qlib/contrib/data/handler.py`）可作为**候选库**，但要逐项核对日本股停牌、拆合股、缺字段与信号日可得性；不能未经核验直接照搬。
- 「每次最多换几只」能控制换手。05 的横截面动量现在是「只换进换出」（[issue 05 评论](invest-assistant-v1/issues/05-three-ohclv-strategy-candidates.md)），可以再加上这个上限。
- `volume_threshold` 的写法，可以参考来实现 05 要的 ADV20 容量上限。

要改的地方：

- Qlib 默认的预测目标是 `Ref($close,-2)/Ref($close,-1)-1`（`handler.py:152`），也就是 t+1 收盘到 t+2 收盘的收益，示例里也按收盘价成交。本项目在 t+1 开盘成交，**预测目标要改成开盘到开盘**，否则模型学到的收益在实际成交时拿不到。
- 判断：不要直接用 Qlib 示例回测替换现有模拟账户；如选 Qlib 做研究编排，也要核对日本的价格限制档位、拆合股、退市结清与本项目账本。任何模型的分数可尝试通过现有策略接口进入系统，但持仓重排、模型版本和特征 manifest 仍需单独设计。

三个梯度提升树库都能直接做「排序」，彼此是竞争性候选而非 LightGBM 的替补：

| 库 | 许可证与最新版本 | 怎样做排序 |
|---|---|---|
| [LightGBM](https://github.com/lightgbm-org/LightGBM) | MIT，v4.7.0（仓库已迁到 lightgbm-org） | `lambdarank`、`rank_xendcg`（[参数文档](https://lightgbm.readthedocs.io/en/latest/Parameters.html)） |
| [XGBoost](https://github.com/dmlc/xgboost) | Apache-2.0，v3.4.2 | `rank:ndcg`、`rank:pairwise`，用 `qid` 分组（[排序教程](https://xgboost.readthedocs.io/en/stable/tutorials/learning_to_rank.html)） |
| [CatBoost](https://github.com/catboost/catboost) | Apache-2.0，v1.2.10 | `CatBoostRanker`，默认损失 YetiRank（[文档](https://catboost.ai/docs/en/concepts/python-reference_catboostranker)） |

三者都可以在 CPU 上运行。另需纳入廉价且可解释的[线性／Elastic Net](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.ElasticNet.html)与[随机森林](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestRegressor.html)；[AutoGluon Tabular](https://auto.gluon.ai/stable/api/autogluon.tabular.models.html) 可试多模型与加权集成，但其自动 bagging／stacking／调参的内部切分不能未经审查地当作金融时间序列的样本外验证。比较需固定同一特征、标签、训练日历、成本和模型选择预算。[Qlib 榜单](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md)仅是别的市场上的参考结果。

**Alpha Discovery（遗传编程、符号回归、AutoML、LLM 挖因子）**

事实：聊天里没给仓库；Qlib README 推荐微软的 [RD-Agent](https://github.com/microsoft/RD-Agent)（MIT，v1.0.0）。RD-Agent(Q) 自称用 LLM 交替优化因子和模型，只支持 Linux，需要 Docker 和 LLM API。

判断：这条路线能批量生成候选因子，价值在「供给想法」。但试验次数越多，越容易碰巧找到回测好看的因子。必须先有 05 的版本记录、试验计数和一次性盲测，再接上它，否则产出的东西无法判断真假。

**TradingAgents 与 LLM 决策（可产出信号，但证据边界最难审计）**

事实：Apache-2.0，v0.7.0（2026-10-16）。多个 LLM 角色辩论后给出五档评级（`oss-refs/TradingAgents/README.md`），日本股走 Yahoo 的 `.T` 代码，基准默认日经 225（`tradingagents/default_config.py:185`）。

判断：

- 对现成通用 LLM，训练截点、预训练语料及提示词中的外部数据往往无法逐条重建成回测日的可得集；仓库把提示词日期固定到运行日（`CHANGELOG.md` #836）并不能消除这些风险。其历史回测可作软件诊断，不能仅凭该结果判定投资优势。
- 若模型权重、输入快照、工具响应、提示词及费用可冻结，可先评价结构化决策一致性；交易优势仍以**从现在往后记录**的 paper challenger 与同输入基线相比为强证据。
- “复核前几名”只是节省 API 成本的一种产品设定，不排除把 LLM 用作事件提取器、独立候选评分器或策略生成器；每种任务都要单独对照。

另一个值得并列调查的是 [FinRobot](https://github.com/AI4Finance-Foundation/FinRobot)：其当前文档把 agent 的研究／叙述与可追溯的确定性财务计算分开，并公开旧版 AutoGen、研究报告服务和新桌面工作流。它主要展示**研究流程、估值与报告的可信边界**，不是已证明可在日股获利的交易策略；现成数据适配器偏美国市场，日文开示、J-Quants 和本项目模拟成交均需重做。若要比较 TradingAgents 与 FinRobot，应在同一输入快照下先比数值出处、事件抽取和决策稳定性，而非比较仓库星数。[FinRobot README](https://github.com/AI4Finance-Foundation/FinRobot)、[旧版适用范围说明](https://github.com/AI4Finance-Foundation/FinRobot/blob/master/finrobot_autogen/README.md)。

**深度时序和预训练时序模型（独立任务线）**

事实：

- PatchTST、TimesNet、iTransformer 三个仓库最后一次更新在 2024–2025 年，代码都已经收进 Time-Series-Library（`oss-refs/Time-Series-Library/models/`）。
- Time-Series-Library 的维护者 2026-04 起不再加新功能（README）。
- Qlib 的[官方表](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md)在 CSI300、Alpha158 的部分配置中报告 TCN／Transformer 的 IC 低于 LightGBM，但榜单还有其他深度模型、Alpha360 和特征数量不一的配置；单挑两个数不能推断“深度模型总体较差”，更不能推断日本股票结果。
- 市场上不止上述三个架构：[Chronos-2](https://github.com/amazon-science/chronos-forecasting)、[TimesFM 2.5](https://github.com/google-research/timesfm)、[Moirai／uni2ts](https://github.com/SalesforceAIResearch/uni2ts) 均给出预测接口；[TimeGPT](https://github.com/Nixtla/nixtla)另提供托管 API。它们的预训练时间和所见金融序列需逐模型核查；API 还需保存响应版本。所谓零样本预测也不能自动视作历史交易回测的时间安全证据。

判断：时序预测可服务 TOPIX 风险、个股预期收益或波动，也可把每只证券的预测转成横截面分数；是否值得这样转，应与相同输入的朴素预测、线性模型和树模型比较。先明确目标是点预测、分位预测还是交易净值，再选合适架构。

### 4.2 文本、分布预测和评估组件

| 项目 | 事实 | 判断 |
|---|---|---|
| [FinBERT](https://huggingface.co/ProsusAI/finbert) | 英文金融情绪三分类；该模型卡标 `cc-by-nc-sa-4.0` | 这个具体权重不宜直接处理日文或商用；不能据此否定文本路线 |
| [FinGPT 模型](https://huggingface.co/FinGPT) | 原调查的 11 个 LoRA 适配器面向英文／中文金融语境（Hugging Face API 列表） | 应按具体权重、语料、许可证核查；不把 FinGPT 品牌当作单一模型 |
| 日文文本路线 | [Izumi Lab 金融 BERT](https://huggingface.co/izumi-lab/bert-small-japanese-fin)在日文金融语料上预训练，**不是**现成交易分类器；[bards.ai 日文金融情绪模型](https://huggingface.co/bardsai/finance-sentiment-ja-base)以翻译版 Financial PhraseBank 训练并自报 F1；[JPX 说明](https://jpx-jquants.com/en/spec/data-update) TDnet 开示逐条反映 | 可试业绩修正、回购、增资等事件抽取；翻译语料上的情绪分数不能代替本地 TDnet 测试。按开示时刻和数据可得时刻决定最早可交易日 |
| [pytorch-forecasting](https://github.com/sktime/pytorch-forecasting)（TFT）、[GluonTS](https://github.com/awslabs/gluonts)（DeepAR） | 两者提供概率／分位预测工具；原调查记录的版本为 v1.8.0、v0.17.0；GluonTS 的 README 引向 Chronos | 可检验 TOPIX、行业或个股收益／风险分布；先看覆盖率、分位损失与尾部校准，不能仅凭预测图转为仓位优势 |
| FinRL 的动荡指数 | 用过去 252 天的收益协方差，算当天截面收益偏离平常多远，只用过去的数据（`oss-refs/FinRL/finrl/meta/preprocessor/preprocessors.py:282-330`） | 可以作为市场形势的新维度；对上千只个股算协方差不稳定，判断：改用 33 行业等权序列 |
| [LangGraph](https://github.com/langchain-ai/langgraph)、[CrewAI](https://github.com/crewAIInc/crewAI) | 都是 MIT；LangGraph 支持中断后续跑、中途让人检查，可以不依赖 LangChain，TradingAgents 就基于它；CrewAI 自带股票分析示例 | 只是编排选择，做事件抽取、LLM 独立评分或复核都可不采用它们 |
| [scikit-learn](https://github.com/scikit-learn/scikit-learn) `TimeSeriesSplit` | 按时间顺序切分，`gap` 在训练段和测试段之间留空（[文档](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)） | 适合按日滚动切分；若标签横跨多日，还须按每个样本的标签结束日检查重叠，`gap` 本身不保证充分防泄漏 |

### 4.3 底层工具

PyTorch（v2.14.1）、Transformers（v5.20.1）、scikit-learn（1.9.1）、Gymnasium（v1.4.0，强化学习环境接口）、Ray／RLlib（2.59.0，分布式和强化学习）。版本来自原调查的 GitHub API 查询。它们使某些实验可实现，但本身不是策略效力证据。

### 4.4 特定仓库的复用风险，不是整个方法家族的淘汰理由

| 项目 | 理由 |
|---|---|
| FinRL 示例（含 SB3 训练） | SB3 官方提醒 RL 常需大量交互、多个随机种子（`oss-refs/stable-baselines3/docs/guide/rl_tips.md:35,53`）；日线 10 年约 2,400 个交易日（估算），不能把重复仿真当新市场样本。原 FinRL 教学流程有 4 个数据／成交坑（见下），自带股票列表无日本（`finrl/config_tickers.py`）；官方另有[FinRL-X](https://github.com/AI4Finance-Foundation/FinRL-Trading) 的模块化、权重接口。**这限制的是示例直接复用，不是否定 RL 配置／仓位研究。** |
| PyTorch Geometric、PyG Temporal | [PyG](https://github.com/pyg-team/pytorch_geometric) 确有 GAT 和异构图能力；当前 Light 的 33 行业可先做行业分组基线，Standard 的 EDINET 交叉持股（原调查：2020 年起）才可能提供有意义的历史关系边。Qlib 榜单的 GATs 只用 20 特征，和 LightGBM 不同配方，不能作为排除图方法的证据。**瓶颈是点时图数据，不是先要树模型胜出。** |
| [AutoGen](https://github.com/microsoft/autogen) | README：「Project archived and no longer maintained」（项目已归档、不再维护），新项目改用 Microsoft Agent Framework |
| [GAT](https://github.com/PetarV-/GAT) 原始代码 | 基于 TensorFlow 1.6 的论文参考实现，最后更新 2022 年；PyG 里已有 `GATConv`（`torch_geometric/nn/conv/gat_conv.py`） |
| [DGL](https://github.com/dmlc/dgl) | 最后发布 v2.4.0 是 2024-09，最后提交 2025-07；功能和 PyG 重叠 |
| [pytorch-ts](https://github.com/zalandoresearch/pytorch-ts)（TimeGrad） | 最后发布 2022-04，最后提交 2024-06；GluonTS 已经覆盖同类模型 |
| [Diffusers](https://github.com/huggingface/diffusers) | 这是通用生成库而非现成金融时序情景方案；若研究合成路径，原作者的 [TimeGAN](https://github.com/jsyoon0823/TimeGAN) 或[时序扩散论文 TSDiff](https://arxiv.org/abs/2307.11494)更直接。合成数据仅用于压力场景或训练期内增强，不能混入真实盲测期 |
| FinGPT 仓库 | Forecaster **这一子项目**的训练答案把真实下周涨跌告知 GPT-4 再让它写理由（`fingpt/FinGPT_Forecaster/prompt.py:104`、`data.py:276-283`），不宜把该结果当独立预测证据；`finogrid/` 是稳定币支付平台。这个问题不等于否定其他 FinGPT 模型或文本因子任务 |

**FinRL 的四个坑**，对照 05 自查：

1. 全期间缺过任何一天收盘价的股票，整只删掉（幸存者偏差，`preprocessors.py:173-190`）。
2. 最后 `ffill().bfill()`，开头的空值用后面的值回填（`preprocessors.py:170`）。
3. 智能体看到当天收盘价，又按同一个收盘价成交（`env_stocktrading.py` 的 `_sell_stock`／`_buy_stock`）。
4. 成交没有一手和涨跌停的限制。

**TradingAgents 值得照搬的评估思路**：每个决策单独按固定持有期（默认 5 天）和基准比较，从决策日之后第一个收盘开始算，不经过组合（`tradingagents/backtest.py` 文件头、`memory/settlement.py`、`CHANGELOG.md` 0.7.0）。用到本项目，就是给入场候选或模型分数单独打分，相当于 Qlib 的 IC 和 Rank IC。

## 5. 公平调查与落地方案

### 5.1 先建立所有路线共用的证据底座

这一步是**评价基础设施**，不是为某一种模型铺路。05 已实现三类 OHLCV 策略，但[该 issue 的评论](invest-assistant-v1/issues/05-three-ohclv-strategy-candidates.md)明确开发／验证／盲测、版本谱系、成本与容量情景、门槛尚未实现。研究应先为每个候选登记任务、可得数据时间、标签起止日、训练／验证／一次性盲测、模型或提示词版本、所有试验次数；固定历史股票池、t 日收盘决策、最早 t+1 开盘成交、一手、停牌、拆合股、退市、费用和 ADV20 容量口径。`TimeSeriesSplit(gap=...)` 是帮助切分的工具，不取代逐样本检查跨期标签是否和验证期重叠。[scikit-learn 文档](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)、[项目策略与成交定义](../CONTEXT.md)。

同一任务内用**同一输入和资金／成交约束**比较：（a）05 已有规则策略、股票池等权及 TOPIX；（b）简单模型或朴素预测；（c）各 AI 候选。排序同时报告 Rank IC／分数分桶和扣费后的组合净值；概率预测看校准、分位损失和实际风险控制；文本任务先看人工标注事件的精确率／召回率，再看事件交易；仓位算法比较相同信号输入下的净收益、回撤、换手、容量与尾部损失。跨任务最终可比较投资效用、成本、证据质量和运维复杂度，**不能把 IC、文本 F1 和预测误差直接放在同一榜单。** Qlib 的[信号／组合分析示例](https://github.com/microsoft/qlib)与 TradingAgents 的逐决策评估仅可借鉴报表结构，不能替代本项目 SimulationEngine 的成交。

### 5.2 多路线小规模试验；进入顺序由数据就绪度决定，不预设胜者

| 候选试验（可并行设计） | 最小可验证版本 | 开始条件／需特别审计 |
|---|---|---|
| 横截面价量排序 | 同一组点时 OHLCV 特征下，对照线性／Elastic Net、随机森林、三种 GBDT、轻量 MLP；Qlib 与 AutoGluon 仅是可选编排器 | 当前日线可设计；先完成冻结标签和模型 artifact。若 AutoML 自行切分数据，必须重配为时间切分。试验次数与算力预算一致 |
| 时序深度与基础模型 | TOPIX／行业／个股收益或波动预测；朴素预测、TFT／PatchTST、Chronos／TimesFM／Moirai 各取一个可复现版本 | 当前日线可先做点预测或分位预测；预训练模型的发布版本、训练数据截止日期若无法审计，历史交易主张降级为前瞻 paper 评估 |
| 风控与动态仓位 | 固定同一选股信号，比较等权、规则化风险上限、概率预测仓位和 RL 代理 | 先保证 RL 环境复用项目成交事实；多随机种子、同成本／容量及与规则仓位对照。FinRL-X 可参考模块接口，不必迁移整个平台 |
| 基本面／日文开示事件 | 接入 Light 套餐估值与财务摘要后比较线性、树、文本事件特征；如获取 TDnet，比较规则事件抽取、日文 BERT、日文 LLM | 财务记录按开示时刻生效，保留更正历史；TDnet 权益和费用、文本取得时间、公司映射先落实。英语 FinBERT 不是默认基线 |
| 关系图预测 | 行业分组基线 vs PyG GAT／异构图；只有拿到可信的历史关系边再测持股／供应链图 | 点时边、边生效时间及历史覆盖率是门槛；不能因为 GBDT 实验未完成就禁止图路线，也不能靠未来图回填 |
| 自动因子／模型发现 | 固定有限搜索预算和候选登记，比较人工因子、符号发现、RD-Agent(Q) 等 | 共用盲测管线先到位；生成了更多候选需披露多重试验，不可只呈现“最佳”模型 |
| 合成市场情景 | 历史块 bootstrap 等简单基线 vs TimeGAN／时序扩散生成的联合收益路径，检验策略在压力情景下的失败模式 | 生成器只拟合训练期；检查横截面相关、尾部和停牌／跳空的保真度；合成路径不计作新的真实 OOS 天数 |

价量路线无需等待 J-Quants 升级；文本／关系路线的数据采购也无需等待价量模型胜出。Light 套餐尚未接入的估值指标、财务摘要、决算预定日和投资者类别买卖值得作为跨模型的**同一新增数据实验**，而非 LightGBM 专属输入。财务摘要要保留每次开示和更正，不可像日线一样覆盖存储；这可能需要调整 ADR-0001 的当前规则。升级 Standard 或 Premium 仅在相应实验能说明额外历史／关系数据价值、使用权与成本时再决策。[J-Quants 数据目录](https://jpx-jquants.com/ja/spec/data-spec)、[财务摘要字段](https://jpx-jquants.com/ja/spec/fin-summary)。

### 5.3 决策门槛与当前系统接口

为每项实验记录“可运行 / 数据不足 / 技术验证通过 / 样本外不通过 / 前瞻观察中”，不能把“尚无数据”误记成“方法无效”。同任务内用预注册主指标、最低交易数／覆盖率、逐年稳定性、10／25／50 bps 成本与延迟一天成交压力检查；公布所有尝试和失败，盲测只在候选冻结后使用。通过离线测试仅获得 paper challenger 资格，是否替换现有规则策略仍须前瞻表现、维护成本及人工决定。[05 的研究与晋级要求](invest-assistant-v1/issues/05-three-ohclv-strategy-candidates.md)。

在当前代码中，`Judgement.priority` 是入场候选排序值；一个 AI 输出要成为策略，还须定义 `Disposition`、持仓是否参与重排、模型／特征版本、缺数据时的处置、更新频率和组合规则。概率分布、文本事件或 RL 目标权重不能未经转换直接塞进 `priority`；模型在离线研究训练，实际成交仍走现有 SimulationEngine。Qlib、AutoGluon、FinRL-X 采用与否另行按复现能力、接入成本和许可证决定，不与模型／策略晋级绑定。[策略接口](../backend/app/strategies/base.py)、[项目术语与成交口径](../CONTEXT.md)。

## 6. 不确定的地方

- Qlib 的公开模型对比主要是中国 A 股等指定市场和不同特征配方，不能直接推断日本市场的效果；本项目未复现实验，也未比较任一 AI 路线的日本股净收益。
- 已核查至少两个日文金融模型卡，但它们分别是预训练表征与基于翻译文本的情绪分类；哪个适合 TDnet 事件、与通用日文 LLM 比如何，仍需日文人工标注集、点时文本与前瞻／真实回测验证。
- Chronos、TimesFM、Moirai、AutoGluon、FinRL-X、TimeGAN 等新增项目仅核查发布方 README／文档／模型卡或原论文，未审查全部源码、预训练语料、许可细节和日本股票适配；原调查的版本号是查询时快照，不代表后续仍为最新。
- J-Quants 各数据集的实际覆盖、限流、费用和使用权需以拟订阅时的官方条款重新核实；文中套餐与价格只反映 2026-10-18 调查快照。
- J-Quants 的「不能持续向第三方提供分析结果」具体管到哪种使用方式，需要看完整的使用条款，这里只引用了 FAQ。
- 除 `oss-refs/` 下的 6 个仓库和 Qlib 的几个源码文件外，多数项目只看了 README、文档、模型卡或论文，没读源码；这里是候选调查，不是性能复核或安全审计。
- 「10 年约 2,400 个交易日」是估算。
