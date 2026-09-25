# 04 — 模拟账户：回测、模拟交易与账户页

**What to build:** 用户新建一个模拟账户（选策略、参数、组合规则、费用和过去的起始日），系统立刻把它从起始日逐个交易日推进到最新交易日——这段就是回测；之后每次同步成功，账户自动再推进一天——这就是模拟交易。账户页显示收益、回撤、夏普等统计和与 TOPIX 的对比曲线、当前持仓、明天开盘要执行的订单及理由，以及全部历史订单。

**Design:** [invest-assistant v1 系统设计](../spec.md) §3.5–§3.6、§7、§8、§9（账户页）、附录 A.4

**Blocked by:** 03 — 指标、两个策略与信号页

**Status:** ready-for-agent

- [ ] 行情数据模块补上账户要用的读取（附录 A.1）：`MarketFrame` 增加调整系数、除权类型两列和 `listed_through`（按那一天判断在不在名册）；`universe(start, end)` 一次给出一段日期的股票池，03 的 `entry_candidates` 与测试随之改用新签名
- [ ] Alembic 迁移建立 `paper_accounts`、`paper_orders`，字段按设计 §3.5–§3.6；持仓、现金、净值不单独存，全部由订单记录推出
- [ ] 账户模块只暴露附录 A.4 的 `create` / `advance` / `report` / `list` / `stop` / `delete`；`advance` 从 `advanced_through` 的下一个开市日推进到指定日期（默认最新交易日），重复调用不重复推进；每个交易日一个事务，推进中途被打断后重跑从断点接着推进（有测试）
- [ ] 账户模块的内部 seam 按附录 A.4：`Ledger`（由订单记录推出持仓、现金、待成交订单，`advance` 与 `report` 共用）、`corporate_actions`、`open_session`（一次开盘的全部订单）、`replace_sells`、`plan_orders`，都不碰数据库，用合成数据直接测试，不经由建账户再推进
- [ ] 推进一个交易日严格按设计 §7.1 的顺序：拆合股调整 → 退市结清 → 开盘成交（先卖后买、买单按排序值）→ 重下过期卖单 → 收盘出信号并生成订单 → 更新 `advanced_through`
- [ ] 组合规则按设计 §7.2：卖出全部持仓、空位计算、候选按排序值降序与代码升序、目标金额与计划股数取整到 100 股、预算扣除 `cash_floor`、`insufficient_cash` 与 `lot_unaffordable` 记为 `skipped`、开仓后不调仓不加仓
- [ ] 开盘成交按设计 §7.3：`untradable`、`limit_down_open`、`limit_up_open` 过期；滑点每边 0.1%；手续费 = max(最低金额, 比例)，默认 0；卖出所得当场可用；现金不足时减少整手数，为 0 则过期
- [ ] 拆合股调整：持仓股数 ÷ 调整系数、零股折现、同日待成交订单按比例调整；配股不调整持仓并记警告；测试覆盖一拆二、十合一（含零股）
- [ ] 退市结清：持仓证券从名册消失时按最后一个收盘成交价格结清，待成交订单过期（`delisted`）
- [ ] 卖单过期后每天重下，直到成交或退市结清；测试覆盖「连续停牌 3 天后恢复交易才卖出」
- [ ] 新建账户校验起始日是开市日且之前有足够的预热期数据，策略参数里出现策略不认识的名字时拒绝（`build_strategy` 随之校验参数名，免得拼错的参数悄悄用了默认值）；创建后立即排入推进任务；每次同步成功后推进所有 `active` 账户；追上最新交易日时写 `backtest_data_mark`
- [ ] 同一账户、同一数据下推进两次（从头重跑）得到逐行相同的订单记录
- [ ] 统计按设计 §7.4 在读取时计算：总收益、年化、最大回撤、夏普（√245）、胜率、平均持有交易日数、年化换手率、相对 TOPIX 的超额年化收益；用一个手算的小账户验证每一项
- [ ] 命令行 `python -m app.cli advance [--account ID]`，与服务内任务共用文件锁
- [ ] API：`GET /api/accounts`、`POST /api/accounts`、`GET /api/accounts/{id}`、`GET /api/accounts/{id}/nav`、`GET /api/accounts/{id}/orders`、`POST /api/accounts/{id}/stop`、`DELETE /api/accounts/{id}`
- [ ] 中文账户页：列表 `/accounts`、新建 `/accounts/new`、详情 `/accounts/[id]`（统计、净值 vs TOPIX、回撤曲线、持仓、明日订单与理由、历史订单与账户事件、停用 / 删除）；报表注明「不含分红、不含税」
- [ ] 在 02 回填的真实数据上，两个策略各建一个从 3 年前开始的账户，推进到最新交易日在几分钟内完成，账户页数字与 `paper_orders` 手工核对一致。Trend-Pullback v1 在这段数据上不会入场（[策略研究](../strategy-research.md) §2），它的账户用来核对「没有交易」时账户页的各项是否正确；有交易的核对用技术评级 v1。两者的回测结果只用来检验系统，不据此改动本 issue 的规则——要调整的是策略
