# AI 驱动的完整交易策略：方向、代表方案与本项目可检验路径

**调查日：**2026-10-19。**适用边界：**invest-assistant 当前以日本 Prime 普通股为个股股票池，已接入 J-Quants Light 的日频 OHLCV、上市信息、日历与 TOPIX；在交易日 `t` 收盘后决定，最早 `t+1` 开盘执行，复用现有模拟账户的整手、现金、费用、不可交易及订单账本。本文是路线调查与实验设计，**未训练新模型、未运行日本股票 AI 策略回测，也不主张任何外部回测收益可迁移**。项目边界见 [spec §6–7](invest-assistant-v1/spec.md)、[策略接口](../backend/app/strategies/base.py)、[组合规划](../backend/app/accounts/planning.py)；Light 可取得的数据类别与年限见 [J-Quants 套餐数据表](https://jpx-jquants.com/ja/spec/data-spec)。

## 先界定：什么才是一套策略

`CatBoost`、`GRU`、`Chronos`、`HIST` 等是模型；Qlib、FinRL-X、Cvxportfolio、TradingAgents 等是框架或研究工作流。**模型输出不能等同于策略。**策略版本至少固定：可用数据及其时点、股票池、决策频率、买/持/卖/留现金条件、目标仓位和总敞口、退出与风险上限、缺数/停牌/拒单时行为、`t+1` 开盘成交政策及成本、重训/提示词/模型版本。最终必须产出逐日信号、计划单、成交/拒单、持仓、现金、净值和可复验工件。Qlib 官方把预测分数与 `TopkDropoutStrategy` 的组合/订单生成分开；FinRL-X 更明确用「选股→分配→择时→风险覆盖」生成目标权重，但其例子也不能直接替换本项目账本。[Qlib 策略文档](https://github.com/microsoft/qlib/blob/main/docs/component/strategy.rst)、[FinRL-X 官方架构](https://github.com/AI4Finance-Foundation/FinRL-Trading/blob/master/README.md)。

**当前接口约束：**`Judgement`/`Signal` 只有 `Disposition` 与 `priority`；`PortfolioRules` 的持股数、单股上限、现金底线固定，`plan_orders` 按固定目标金额买入。因此「按分数择股并按固定规则持有」较易接入；逐日变动的目标权重、风险降敞口、组合优化、RL 动作和策略间资金调度都**不是现成功能**，须扩展策略→组合接口，但继续使用唯一原账本，而非另造一个乐观成交器。[策略接口](../backend/app/strategies/base.py)、[规划源码](../backend/app/accounts/planning.py)。下文的政策均是**拟议的待检验契约**，不是这些外部项目已经针对日股交付的成品。

## 1. 横截面 AI 选股：预测/排序 → Top-N 持仓

- **一手代表：**[XGBoost Learning to Rank](https://xgboost.readthedocs.io/en/stable/tutorials/learning_to_rank.html) 的按查询组排序、[CatBoostRanker](https://catboost.ai/docs/en/concepts/python-reference_catboostranker) 或 [LightGBM 排序目标](https://lightgbm.readthedocs.io/en/latest/Parameters.html)；Qlib 的 [`TopkDropoutStrategy`](https://github.com/microsoft/qlib/blob/main/docs/component/strategy.rst) 展示分数如何变为每日卖出/买入列表。前几项只是学习器；Topk-Drop 是具体组合政策，不是 AI 模型。没有证据说明哪个树库在日本本项目最好。
- **数据/行动：**以 `t` 可知的调整后价量、流动性、历史 Prime 资格做特征；标签按实际可买的 `t+1` 开盘至预设退出开盘收益定义。每个决策日单独做排序组，选合格前 N 只；是否开仓还需独立的、仅用训练期确定的现金/净优势门槛——ranker 原始分数仅表相对次序，不可直接当预期净收益。持仓在重排后跌出阈值/到期/风控触发则卖，否则持；固定单股权重、最多 N 只、现金底线、换手上限，`t+1` 开盘执行，未成交保持现有真实持仓。这是一种策略假设，可用回归、ranker、线性模型分别驱动，不应把换训练器误称为三种独立策略。
- **独立对照/风险：**同一股票池/时间折/政策下比规则、Ridge、不同树族及 ranker；模型层看 Rank IC/Top-N 命中，策略层看成本后净值、超额、回撤、换手和可成交率。排名高不表示绝对收益为正；现金门槛校准、幸存者偏差和相邻持有期标签重叠是重点。**近期可行性：高**，最贴合现有 `priority`，但要补可靠折外分数及版本记录。[Qlib 策略文档](https://github.com/microsoft/qlib/blob/main/docs/component/strategy.rst)、[XGBoost 排序分组](https://xgboost.readthedocs.io/en/stable/tutorials/learning_to_rank.html)。

## 2. AI 时序趋势/择时：历史路径 → 入场、退场或现金

- **一手代表：**原作者的 [Deep Momentum Networks (DMN) 论文](https://arxiv.org/abs/1904.04912) 直接学习趋势和头寸大小、可用 Sharpe/换手目标训练；[Chronos 官方项目](https://github.com/amazon-science/chronos-forecasting) 则提供分位预测，**本身不是交易政策**。DMN 原实验是期货，不是日本 Prime 股票；不能移植其业绩。
- **数据/行动：**对单股或 TOPIX/行业，用 `t` 以前价量序列推断下一持有窗口的方向、下侧风险或趋势置信度；长-only 版本只在方向和净优势超过阈值时开仓，转弱/到期则退出，其余留现金。市场级信号可决定「允许/禁止新开仓」；若控制总仓位，还需动态目标敞口接口。每个动作用 `t+1` 开盘价与随后实际可执行价格结算，不能把已观察的 `t` 收盘价同时用作成交价。
- **独立对照/风险：**对照固定均线/动量规则、同输入的线性/树模型、始终开仓和留现金基线；看净值、回撤、空仓占比、错误退场代价。预训练权重若可能见过测试时期的市场数据，只能将历史回放视为探索性，需冻结版本后前瞻 paper 检验。**近期可行性：中**：长/现金或单股进出可沿现有 disposition；直接学习连续仓位的版本需要接口扩展。DMN 的期货多空与本项目长-only 不同，先验证可改造性。[DMN 原论文](https://arxiv.org/abs/1904.04912)、[Chronos 官方](https://github.com/amazon-science/chronos-forecasting)。

## 3. 预测风险/市场状态 → 风险条件仓位

- **一手代表：**[LightGBM 官方 `quantile` 目标](https://lightgbm.readthedocs.io/en/latest/Parameters.html) 可估计下侧收益分位；[Moreira–Muir 原论文](https://www.nber.org/papers/w22208) 是波动调仓的规则基准，**不是 AI 策略**；[FinRL 的动荡阈值源码](https://github.com/AI4Finance-Foundation/FinRL/blob/master/finrl/meta/env_stock_trading/env_stocktrading.py) 展示市场风险指标触发限买/清仓的政策原型。
- **数据/行动：**固定一套入场信号，另用仅截至 `t` 的 OHLCV/TOPIX/行业数据估未来波动、尾部损失或风险状态。预注册映射如「高风险：目标总敞口从 95% 降至 45%；极端风险：停止新买、能成交的持仓逐步退出」；低风险再恢复，但受每股/行业/换手上限与冷却期约束。不得把不可成交卖单当已避险，也不得根据事后定义的整段熊市标签做实时 gate。
- **独立对照/风险：**同一基础选股策略配对比较无 gate、固定波动阈值、AI gate；同时报告风险预测校准、尾部损失、净收益、回撤、被迫空仓/未能卖出比例。五年日线的极端状态样本有限，阈值调参极易过拟合。**近期可行性：中**：数据现有，但连续降仓需要扩展目标权重/减仓订单；仅停止新买不等于风险降仓。[LightGBM 目标](https://lightgbm.readthedocs.io/en/latest/Parameters.html)、[原波动调仓研究](https://www.nber.org/papers/w22208)。

## 4. 财报/日文开示事件：已披露信息 → 限时事件交易

- **一手代表：**J-Quants [财务摘要](https://jpx-jquants.com/ja/spec/fin-summary) 含开示日/时刻，可先做结构化的业绩修正/盈利质量事件；[TDnet 索引](https://jpx-jquants.com/ja/spec/td-list) 与 [文件](https://jpx-jquants.com/ja/spec/td-files) 是文本、标题、PDF 的一手源但需加购；[日文金融 BERT 模型卡](https://huggingface.co/izumi-lab/bert-small-japanese-fin) 是预训练语言模型而非已验证交易分类器。[TradingAgents 的 trader](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/agents/trader/trader.py) 会产生 Buy/Hold/Sell 建议，但其 [`backtest.py`](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/backtest.py) 明说只评决策质量，**不是持仓/成交/现金模拟器**。
- **数据/行动：**先在 Light 可用但当前未入库的结构化财务摘要上做「业绩预想上修/下修、业绩变化等事件→未来可交易日持有 H 日」；回购等公告需 TDnet 标题/PDF，文本版才加上事件类别、方向、置信度与原文证据。只有确实在 `t` 收盘前已公开、已被系统捕获的事件能在 `t` 决策、`t+1` 开盘买卖；收盘后开示在当前系统应至少等下一次收盘决策，不能假装上一收盘已知。单事件资金上限、同一公司冲突事件/更正处理、时效到期退出和低置信度留现金必须预先定义。
- **独立对照/风险：**同事件样本的确定性关键字/数值阈值、事件方向 AI、无事件匹配股票对照；先评人工标注精确率/召回率，再评迟延后净收益、事件覆盖、拥挤/跳空损耗。J-Quants 不给每条数据在其平台的实际可取时间，且修正可能覆盖，历史点时重建需保守；LLM 历史知识污染与输出不稳定使前瞻冻结尤为重要。**近期可行性：结构化版本中（需入库及点时处理）；TDnet/LLM 版本低（需数据权利、存档和版本审计）**。[J-Quants 财务时点](https://jpx-jquants.com/ja/spec/fin-summary)、[TDnet 时点/修订](https://jpx-jquants.com/ja/spec/td-list)。

## 5. 图关系/行业传播：点时关系 → 关联股买卖

- **一手代表：**[HIST 作者论文](https://arxiv.org/abs/2110.13716) 与 [Qlib HIST 实现说明](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/HIST/README.md) 研究概念/关系共享信息来预测股票趋势；它输出分数，**并不单独定义本项目订单策略**。J-Quants Standard 有 [EDINET 政策持股/大股东数据](https://jpx-jquants.com/ja/spec/data-spec)，Light 仅有行业分类等较粗关系。
- **数据/行动：**对每个 `t` 构建当时已知行业、持股或供应链边，不得用今天的关系倒填旧日。模型给受关联事件或领先股变动影响的候选打分；仅超阈值且仍合格的 Prime 股票进入前 N，旧持仓失去信号/期限届满则退出，组合要限制同一关系簇集中度并处理无边股票。执行仍是 `t+1` 开盘。
- **独立对照/风险：**同特征的非图模型、行业哑变量/行业动量，以及打乱但保持度数的图消融；比较净收益与跨行业/关系簇风险。点时边、证券实体映射、低覆盖和较少独立历史是主要障碍。**近期可行性：低**；可先用行业基线检验问题价值，真实图须数据采购/版本化。[HIST 论文](https://arxiv.org/abs/2110.13716)、[数据可得性](https://jpx-jquants.com/ja/spec/data-spec)。

## 6. 强化学习/直接政策学习：账户状态 → 动作或目标权重

- **一手代表：**[FinRL 股票环境源码](https://github.com/AI4Finance-Foundation/FinRL/blob/master/finrl/meta/env_stock_trading/env_stocktrading.py) 把资产、现金、价量与技术指标组成状态，动作转买卖并扣交易成本；[FinRL-X 官方说明](https://github.com/AI4Finance-Foundation/FinRL-Trading/blob/master/README.md) 给出目标权重为统一策略接口及 DRL 分配器。它们是环境/架构样例，不是适配本项目日股开盘成交的可直接复用策略。
- **数据/行动：**可先限定少量 Prime 股票和现金，`t` 状态包含截至收盘的特征及真实持仓/现金；政策输出目标权重或有限动作，投影到长-only、整手、单股/总仓上限、容量和冷却约束，`t+1` 开盘按现有账本卖后买。奖励必须按实际成交后的净值变化并扣成本/风险惩罚；停牌/涨跌停/拒单作为环境事实反馈，不能视为策略想卖就卖。
- **独立对照/风险：**同一环境比等权/固定再平衡、规则风险 gate、监督式分数+优化器；多随机种子、按时间真正折外和前瞻 paper。重复训练于相同五年历史不等于取得更多独立市场样本；环境与生产账本不一致会制造虚假优势。**近期可行性：低**，须先有目标权重接口及环境-账本等价测试，再谈 PPO/SAC 等算法选择。[FinRL 环境](https://github.com/AI4Finance-Foundation/FinRL/blob/master/finrl/meta/env_stock_trading/env_stocktrading.py)、[FinRL-X](https://github.com/AI4Finance-Foundation/FinRL-Trading/blob/master/README.md)。

## 7. AI 预测 + 成本/风险意识组合优化：分数 → 权重/订单

- **一手代表：**[Cvxportfolio 官方示例](https://github.com/cvxgrp/cvxportfolio) 把收益预测、协方差/风险预测、交易成本及约束组装成优化政策并回测；[PyPortfolioOpt 官方文档](https://github.com/PyPortfolio/PyPortfolioOpt/blob/main/docs/UserGuide.rst) 允许替换预期收益和风险模型；[Qlib 组合示例](https://github.com/microsoft/qlib/blob/main/examples/portfolio/README.md) 明确指出简单 Topk-Drop 难控制相关/波动风险。优化器本身一般不是 AI，AI 可以提供收益、波动、协方差或成交成本预测。
- **数据/行动：**每个 `t` 对已有/候选股估可实现净收益及风险，优化长-only 目标权重，显式惩罚从当前实际持仓到目标的换手与估计成本，附单股、行业、现金、ADV 容量约束；无法求解或输入缺失时退回冻结的等权政策。把权重转 100 股整手订单、在 `t+1` 开盘用原账本执行，并记录优化前后以及拒单后实际权重。
- **独立对照/风险：**固定同一预测信号，比等权、逆波动、最小方差、成本无感优化与成本敏感优化；净收益/回撤/换手/容量、解的稳定性和集中度都要看。预测误差易使最优权重剧烈变化；Cvxportfolio 示例成本默认偏美国市场，不能照搬为东京成本/成交事实。**近期可行性：中偏低**：当前 OHLCV 可做首轮，但必须扩展目标权重与持续再平衡，先用可解释约束。[Cvxportfolio 官方](https://github.com/cvxgrp/cvxportfolio)、[本项目规划源码](../backend/app/accounts/planning.py)。

## 8. 策略选择/元控制器：多个冻结策略 → 当日哪套/各占多少

- **一手代表：**[Online Portfolio Selection 原作者综述](https://arxiv.org/abs/1212.2129) 概括在线配置专家策略的研究；[FinRL-X Adaptive Rotation 官方实例](https://github.com/AI4Finance-Foundation/FinRL-Trading/blob/master/README.md) 将分组选择、动量、市场状态、风控与现金缓冲组合成较完整政策。该实例的资产/美股情境与项目不同，公开报告不构成日股证据。Qlib 的 [TRA](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/TRA/README.md) 是预测模式路由器，不要误称为现成的策略级资金调度器。
- **数据/行动：**先冻结若干完整基础策略（如横截面、趋势、事件），元层在 `t` 只能读其**当时已结算**的折外表现和市场特征，决定全选一套、现金或为各 sleeve 设权重；分歧时合并目标持仓并再次施加全账户风险/容量上限。元层也要冻结更新频率、转场冷却、坏数据时退回基准、`t+1` 开盘执行。不能拿当天才知道的未来胜者做状态标签。
- **独立对照/风险：**与长期固定最佳（只在训练期选）、等权混合、简单过去收益加权和留现金比较；看切换次数/成本、不同年份表现以及每层选择试验数。候选策略若已在同一历史反复筛选，再加元层会放大多重检验风险。**近期可行性：低**：先有可靠独立策略的折外决策记录与权重接口；短历史不支持复杂状态切换先验。[在线组合选择论文](https://arxiv.org/abs/1212.2129)、[回测过拟合原论文](https://escholarship.org/uc/item/4w1110bb)。

## 不是独立完整策略，但值得做的辅助路线

- [RD-Agent(Q)](https://github.com/microsoft/RD-Agent) 及 AutoML/自动因子发现可生成特征、模型和候选，**不自动证明交易政策有效**；每个生成候选仍须走同一策略契约、记录所有失败与试验预算。[RD-Agent 官方](https://github.com/microsoft/RD-Agent)、[回测过拟合原论文](https://escholarship.org/uc/item/4w1110bb)。
- 时序基础模型、语言模型、图神经网络可嵌入上述多种策略，不能仅按模型名建「策略排行榜」。生成式合成行情可用于压力测试，但合成路径不是新增真实样本外交易日。[Chronos 官方](https://github.com/amazon-science/chronos-forecasting)、[TimeGAN 作者仓库](https://github.com/jsyoon0823/TimeGAN)。
- 配对/统计套利是另一条可研究路线，但若要求做空、借券或日内配对执行，就超出现有长-only Prime 账户和日线开盘成交契约；仅研究「相对价值长仓」时可纳入第 1 类而不宣称已实现市场中性。[项目账户约束](invest-assistant-v1/spec.md)。

## 共用评测契约与分阶段建议

**所有路线共用的最终证据：**固定历史 Prime 成分与股票池资格、特征实际可得时点、`t+1` 开盘可交易标签、整手/停牌/价格限制/费用/滑点/现金/容量规则；逐样本检查标签结束早于下一训练边界；同日股票不能拆到训练与测试两侧。按时间滚动训练与折外回放，阈值/模型/提示词只用训练-验证定，记录数据快照、所有尝试、种子、失败订单和独立持仓账本。报告至少含成本后收益与 TOPIX/股票池等权/05 规则策略对照、回撤、波动、换手、容量压力、覆盖率及按年份/市场状态切片。模型指标（IC、F1、分位校准）只能作中间诊断，不替代成交后净值；同历史多试版本会过拟合，已看过的历史不能重新称作盲测。`TimeSeriesSplit(gap=...)` 提供空档但不自动解决跨期标签；统计警告见 [scikit-learn 原文档](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)、[Bailey 等原论文](https://escholarship.org/uc/item/4w1110bb)。

1. **阶段 0 — 证据与动作底座。**先实现策略版本登记、点时特征/标签、滚动折外、同批账本比较、容量/成本压力和「未成交仍持仓」测试。检查策略→组合接口：排序型先用 `priority`；若要风险 gate/优化/RL/meta，设计可审计的目标权重/敞口指令，并保持唯一成交账本。这一阶段不把任何训练器指定为赢家。[本地策略接口](../backend/app/strategies/base.py)、[本地规划源码](../backend/app/accounts/planning.py)。
2. **阶段 1 — 现有价量可启动的两条独立交易假设与一项配对增强。**（A）横截面前 N 买/卖/留现金；（B）时序趋势/择时长仓或空仓；（A+R）在固定 A 上叠加预测风险后的敞口限制，必须与无 gate 的 A 成对消融，**不计为第三条独立假设**。回归与 ranker、CatBoost/LightGBM/XGBoost、GRU/Chronos 是各假设内部的模型竞争者，不是用名称凑多套独立策略；若 A+R 所需的动态仓位接口未到位，可先仅做离线诊断，不宣称策略已交付。[Qlib 策略文档](https://github.com/microsoft/qlib/blob/main/docs/component/strategy.rst)、[DMN 原论文](https://arxiv.org/abs/1904.04912)、[风险目标接口](../backend/app/accounts/planning.py)。
3. **阶段 2 — 数据和权重能力成熟后。**入库 Light 可取得的结构化财务摘要与估值，做点时财报事件；实现目标权重后做成本/风险感知组合，同 A 的等权版配对。二者可独立于某一种模型胜负推进。[J-Quants 套餐表](https://jpx-jquants.com/ja/spec/data-spec)、[Cvxportfolio 官方](https://github.com/cvxgrp/cvxportfolio)。
4. **阶段 3 — 需要新增证据/采购的候选。**TDnet 文本/LLM、点时关系图、RL/元控制器均保留平等提出与受控检验资格；但分别以数据权利和时点存档、关系边覆盖、环境-账本等价及足够独立前瞻样本为启动条件。未满足则标 `数据不足/证据不足`，不是宣称路线无效。任何候选仅可在成本后、折外及前瞻 paper 证据足够时申请准入，并允许**全部暂不采用**。[TDnet 条件](https://jpx-jquants.com/ja/spec/td-list)、[FinRL 环境](https://github.com/AI4Finance-Foundation/FinRL/blob/master/finrl/meta/env_stock_trading/env_stocktrading.py)、[HIST 论文](https://arxiv.org/abs/2110.13716)。

**结论：**应选的是可证伪的**交易假设及其完整动作政策**，再在每个假设内比较 AI 驱动；不能先钉死三个模型，再把共用的入场/仓位/退出政策包装成「多策略」。这里给的是研究优先级与工程可行性判断，不是投资建议，也没有任何一条路线已在本项目通过收益检验。
