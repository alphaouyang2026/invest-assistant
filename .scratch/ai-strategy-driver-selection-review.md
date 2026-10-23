# AI 策略驱动选型复核：CatBoost、MLP、GRU 是否最合适？

**核查日期：**2026-10-19。**范围：**本项目日本 Prime 普通股、J-Quants Light 现已入库的日频 OHLCV、`t` 收盘形成信号／最早 `t+1` 开盘成交、约每五个开市日调仓、开盘至开盘约五日持有的研究设想。本文只复核选型，不训练模型、不运行新的日本股票回测，也不宣布预期收益排名。

## 结论

**不能确认 CatBoostRegressor、scikit-learn MLPRegressor、PyTorch GRU 是目前最合适的三种“策略驱动”。** 它们能检验表格树、表格神经网络、序列神经网络三个训练器能否接入共同管线，但现 [06b](invest-assistant-v1/issues/06b-cross-sectional-ai-challenge.md) 让三者预测同一五日收益、使用同一入场／退出／仓位政策，本质上是**同一个策略假设之下的模型消融**，不是三种独立的交易策略假设。即使三者都生成独立订单与净值，也不能由此证明“多路线策略研究”已覆盖排序目标、风险限仓或其他策略行为。[项目 06b 契约](invest-assistant-v1/issues/06b-cross-sectional-ai-challenge.md)、[Qlib 对预测分数与 Topk-Drop 交易政策的区分](https://github.com/microsoft/qlib/blob/main/docs/component/strategy.rst)。

综合当前数据与任务，**优先级应是：可靠的线性／规则基线；至少一种梯度提升树回归；直接优化横截面排序的 ranker；再以独立实验检验风险预测是否值得改变仓位**。CatBoost 可保留为第一种树模型或与 LightGBM/XGBoost 的预注册同预算对照；MLP 宜作为低成本神经基线，GRU 宜作为有条件的时序 challenger，而非未验证即锁定的两套必交核心策略。这里的“优先”是研究设计与工程适配判断，**不是日本股票收益的实证结论**。[Qlib 作者维护的多模型基准及其中国市场范围](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md)、[XGBoost 官方排序教程](https://xgboost.readthedocs.io/en/stable/tutorials/learning_to_rank.html)、[LightGBM 排序接口](https://lightgbm.readthedocs.io/en/stable/pythonapi/lightgbm.LGBMRanker.html)。

## 证据与选型评估

| 路线 | 在本项目能回答的研究问题 | 适配与限制 | 本轮建议 |
|---|---|---|---|
| CatBoostRegressor：表格特征预测五日收益 | 非线性价量特征是否比 Ridge／规则更能产生可执行的 top-N 收益？ | 有成熟的回归、早停与模型保存接口；但它优化的是回归损失，不是 top-N 排序或成本后效用。当前 OHLCV 数值特征也尚未证明 CatBoost 相对 LightGBM/XGBoost 的特有优势。[CatBoost 回归接口](https://catboost.ai/docs/en/concepts/python-reference_catboostregressor) | **保留为候选，不预授冠军**；树族选择需与替代树同预算、同样本比较。 |
| LightGBMRegressor／XGBRegressor：其他 GBDT | 树族的结果是否依赖 CatBoost 的实现？ | 可作为必要的强表格对照；Qlib 的跨模型表包含这些模型，但用的是中国 A 股、不同特征配方和回测设置，不能移植成日本市场排序。[Qlib 官方基准](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md) | **至少纳入一个预注册对照**；不是要回到“Qlib+LightGBM 预设赢家”。 |
| XGBRanker／LGBMRanker／CatBoostRanker：按决策日分组学习排序 | 回归分数排序是否劣于直接学习同一决策日的可买候选相对次序？ | 排序器原生使用 query/group；`rank:ndcg`、`lambdarank` 等需预先定义日期组、收益到相关度的映射和 top-N 指标。NDCG 不是净收益，也不会自动决定“全都不值得买时留现金”；现金门槛须另立可审计规则。[XGBoost 排序教程](https://xgboost.readthedocs.io/en/stable/tutorials/learning_to_rank.html)、[LightGBM 排序接口](https://lightgbm.readthedocs.io/en/stable/pythonapi/lightgbm.LGBMRanker.html)、[CatBoost 排序目标](https://catboost.ai/docs/en/concepts/loss-functions-ranking?lang=en) | **比 MLP 或 GRU 更直接对应 top-N 决策的首轮独立模型目标**；不保证交易结果更好。 |
| 小型 MLPRegressor：表格神经网络 | 神经非线性是否在同样工程特征上增量有用？ | 是合适的神经网络**基线**，但与 CatBoost 输入和回归任务重叠；官方指出 MLP 对缩放敏感、损失非凸、随机初始化会改变验证结果，且 scikit-learn 实现不支持 GPU。[scikit-learn MLP 说明](https://scikit-learn.org/stable/modules/neural_networks_supervised.html) | 降为可运行的对照或后续 challenger；仅为凑齐“三个 AI 名字”而强制实施的边际价值低。 |
| 小型 PyTorch GRU：原始价量序列 | 从过去一段相对变化序列自动提取特征，能否比汇总价量特征提供增量？ | 是合理的时序对照，但并非“时序主流唯一代表”；Qlib 同时列出 LSTM、TCN、Transformer 等。序列完整性会改变证券覆盖；训练成本、初始化和 CPU/GPU 算法需要额外控制。Qlib 结果不能证明 GRU 在此市场／任务胜出。[PyTorch GRU 接口](https://docs.pytorch.org/docs/stable/generated/torch.nn.GRU.html)、[Qlib 官方基准](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md)、[PyTorch 复现性说明](https://docs.pytorch.org/docs/stable/notes/randomness.html) | 作为**有条件的时序 challenger**：先报告序列覆盖、训练资源与独立验证结果，再决定是否进入完整策略回放。 |
| 概率／分位风险模型 + 限仓政策 | 预测未来波动或下行风险，是否能让既有选股策略降低尾部损失／回撤？ | 这是与“换个选股预测器”不同的完整策略假设。LightGBM 提供分位回归目标，但其有无投资价值只能与固定规则风险 gate、无 gate 版本在相同账本上比较，且五年历史可能不足以覆盖足够市场状态。[LightGBM 目标函数](https://lightgbm.readthedocs.io/en/stable/Parameters.html)、[Qlib 将信号与组合优化分开的示例](https://github.com/microsoft/qlib/blob/main/examples/portfolio/README.md) | 设为**独立策略实验**；不把波动误差改善误称为策略净收益改善。 |
| 更复杂的 TCN／Transformer／时序基础模型，或 RL 仓位 | 有无更适合长序列、市场状态或动态仓位的结构？ | 技术路线确实存在；当前日线五年、点时数据与计算预算下，尚无本地证据支撑优先实现。预训练模型还要审计权重发布日期与历史训练语料；RL 在同一段历史反复训练不产生独立市场日。[Qlib 模型目录](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md)、[FinRL 官方项目](https://github.com/AI4Finance-Foundation/FinRL) | 保留同等**提出和受控测试资格**，但不因“更新”而预设比树／排序路线收益高。 |

上述经验性提醒也有跨领域一手基准支持：NeurIPS 作者的常规表格数据研究发现树模型在其测试的中等规模数据上仍非常有竞争力，但该研究**不是证券市场实验**，只能支撑“不可跳过强树基线”，不能推出“树模型必胜 GRU／MLP”。[原论文](https://papers.nips.cc/paper_files/paper/2022/hash/0378c7692da36807bdec87ab043cdadc-Abstract.html)。

## 当前 06 方案与前次调查为何不同

[此前的一手资料复核 §7](ai-quant-primary-research.md) 建议首轮固定规则／Ridge、LightGBM 回归，以及 XGBoost/CatBoost 中至少一种同预算树对照；排序损失另列问题。[现 06b](invest-assistant-v1/issues/06b-cross-sectional-ai-challenge.md) 改成 CatBoost + MLP + GRU，理由是三个不同模型家族的工程挑战与避免 Qlib/LightGBM 成为前置条件。**工程覆盖理由成立，但没有新的日本股票样本外结果、数据剖面或计算成本测量足以把它提升为“最合适的三项投资研究”。** 具体缺口是：删去 LightGBM/XGBoost 表格对照后无法判断 CatBoost 的相对地位；删去 ranker 后没有直接对准横截面 top-N 目标的模型；把 MLP、GRU 绑定同一交易政策只扩大模型家族，未扩大策略行为。[Qlib 的中国市场基准边界](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md)、[XGBoost 排序目标定义](https://xgboost.readthedocs.io/en/stable/tutorials/learning_to_rank.html)。

因此建议不要用一份三模型排行榜同时回答两个问题：

1. **同任务公平模型比较：**固定股票池、历史折、特征可得时点、五日开盘到开盘标签、同一入场／退出／仓位／成交／成本、近似搜索预算；Ridge、至少两种 GBDT 实现、MLP、GRU 等可作为模型消融。若比较 ranker，需承认损失与标签相关度不同，但冻结相同可交易候选和交易政策后仍可比较实际组合结果。[XGBoost 排序教程](https://xgboost.readthedocs.io/en/stable/tutorials/learning_to_rank.html)、[项目 06a 契约](invest-assistant-v1/issues/06a-research-evidence-contract.md)。
2. **多种完整策略假设：**例如“按预测五日超额收益选 top-N”、“按同日相对收益排序选 top-N”、“预测未来风险后限制总体敞口”。每个假设独立冻结入场、留现金、调仓、退出、仓位、风险、异常与成本；风险 gate 与原策略成对比较。它们的预测损失／Rank IC／分位校准不能混为同一榜，最后只能按相同成交账本下的净效用、风险、证据质量及运维成本来审议。[Qlib 策略与交易政策说明](https://github.com/microsoft/qlib/blob/main/docs/component/strategy.rst)、[项目 06d 准入要求](invest-assistant-v1/issues/06d-strategy-selection-and-paper-challenger.md)。

## 本项目的验证门槛

- **历史长度不是“数百万独立样本”。**此前对本地库的只读核查得到 2021-09-24 至 2026-10-16 共 1,237 个有股票日线的交易日，详见[原调查 §7](ai-quant-primary-research.md)。若约五日调仓，名义上仅约 247 个决策横截面；每个截面可能有许多股票，但它们共享市场冲击，相邻五日标签和滚动特征又会相关。这是基于本项目任务的数量级推断，**并非已完成的有效样本量估计**。先测每天合格股票数、可交易率、预热与标签覆盖、年度／形势分布，再决定神经模型和风险 gate 的预算。[J-Quants 官方 Light 五年期限](https://jpx-jquants.com/ja/spec/data-spec)、[项目股票池规则](invest-assistant-v1/spec.md)。
- **日期和标签必须严格折外。**同日股票不得拆进训练与验证两边；训练样本的收益标签截止必须早于训练截止；缩放、缺失处理、特征筛选和阈值选择都只能在训练／验证阶段完成。`TimeSeriesSplit(gap=...)` 提供时间间隔工具，但不会自动理解每个股票样本的五日标签结束时点，需要逐条校验。[scikit-learn 时间序列切分](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)、[项目 06a 契约](invest-assistant-v1/issues/06a-research-evidence-contract.md)。
- **当前历史已被看过。**原调查记载 05 候选的全样本结果已经被查看；之后在相同历史上试更多模型与规则，不能重新包装成一次真正盲测。记录所有尝试、失败、搜索预算与版本，保留尚未揭示的未来观察；如果无法留出有效未见区间，结论只能是探索性／`insufficient_evidence`。多策略选择的回测过拟合风险见[原始研究](https://escholarship.org/uc/item/4w1110bb)；[项目 05 任务](invest-assistant-v1/issues/05-three-ohclv-strategy-candidates.md)。
- **复杂度和复现成本也要计分。**MLP 需要训练折内缩放与多随机种子；GRU 还须固定张量表示、序列覆盖、硬件／库版本、确定性设置、训练时间和内存。PyTorch 明确说不同版本／平台／CPU-GPU 即使同 seed 也不保证完全复现。树模型也需要记录版本、线程、早停与完整工件，而不是仅保存一个分数。[scikit-learn MLP 文档](https://scikit-learn.org/stable/modules/neural_networks_supervised.html)、[PyTorch 复现性说明](https://docs.pytorch.org/docs/stable/notes/randomness.html)、[项目 06a 工件要求](invest-assistant-v1/issues/06a-research-evidence-contract.md)。
- **完整交易策略才是最终比较对象。**模型分数需转成逐日买／持／卖／留现金与目标权重，纳入整手、停牌、拒单、部分成交、ADV20、费用、延迟一日成交和异常降级；最终对照规则、Ridge、同池等权与 TOPIX，并保留预测诊断和实际净值两个层级。任何官方示例的回测净值都不能替换本项目账本。[Qlib 的信号—策略—回测分层](https://github.com/microsoft/qlib/blob/main/docs/component/strategy.rst)、[项目 06a/06d](invest-assistant-v1/issues/06a-research-evidence-contract.md)。

## 可执行的选型建议

1. **如果目标是先证明通用评测框架：**三种家族覆盖仍可作为工程验收，但应明确它只证明“能接入并运行”，不能宣称是最合适的策略组合；CatBoost、MLP、GRU 的实际投资地位保持未定。
2. **如果目标是 06 本轮研究最有信息量的三套完整策略：**建议把候选设计改为：A. GBDT 回归驱动的五日 top-N 策略（CatBoost 与 LightGBM/XGBoost 先做有限树族选型）；B. 按决策日分组的 GBDT 排序驱动 top-N 策略（XGBRanker 或 LGBMRanker，加入独立现金门槛）；C. 在 A 的同一入场分数上叠加概率／分位风险限仓的完整策略，并与无 gate 版本配对。A/B 的主要差异是学习目标，C 的主要差异是组合／风险决策；三者都须经过完整账本。C 若数据剖面显示市场状态过少，应标证据不足，不强制宣称有效。MLP、GRU 则进显式 challenger 队列，不失去测试资格。[XGBoost 排序](https://xgboost.readthedocs.io/en/stable/tutorials/learning_to_rank.html)、[LightGBM 分位回归](https://lightgbm.readthedocs.io/en/stable/Parameters.html)、[Qlib 组合例子](https://github.com/microsoft/qlib/blob/main/examples/portfolio/README.md)。
3. **两种目标不要混成一张榜。**A/B 可以固定同一组合政策评价模型任务差异；C 必须与同信号、同历史的 A 进行 gate 消融。最后的策略选定按预注册的成本后净收益／回撤／容量／可靠性门槛和前瞻证据决定，允许“全部暂不采用”。本笔记不构成对任何模型未来表现或实际投资的保证。[项目 06d](invest-assistant-v1/issues/06d-strategy-selection-and-paper-challenger.md)。

**未决事实：**尚无本项目对上述任何 AI 模型的实测 OOS 收益、训练耗时、内存、实际 eligible universe 覆盖或风险状态独立样本数。完成这些检查前，任何“最合适”都只能是可证伪的研究优先级，而不能是已证实的投资结论。
