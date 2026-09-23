# 01 — 骨架、行情同步与数据页

**What to build:** 用户在 `.env` 填好 J-Quants Light 的 API key 后，执行 `docker compose up`，就能在数据页一键回填过去 5 年的日线行情、上市名册、交易日历和 TOPIX；之后每个开市日 18:00 自动同步当天数据。数据页显示数据到哪一天、同步进度、最近任务结果和质量警告。中断后重跑同步，结果与一次跑完相同。

**Design:** [invest-assistant v1 系统设计](../spec.md) §2–§4、§8、§9（数据页部分）、§10、附录 A.1 与 A.5

**Blocked by:** —

**Status:** ready-for-agent

- [ ] 项目骨架：`backend/`（uv、FastAPI、SQLAlchemy 2 + Alembic、structlog、pydantic-settings、pytest）、`frontend/`（Next.js 16、React 19、TypeScript、Vitest、openapi-typescript 客户端生成）、`docker-compose.yml`（`backend` + `frontend`，SQLite 在挂载卷的 `var/invest.db`，时区 `Asia/Tokyo`）、`.env.example`；服务只监听本机
- [ ] Alembic 迁移建立行情数据模块的 4 张表 `instruments`、`segment_periods`、`daily_bars`、`trading_calendar`，字段按设计 §3.1–§3.4；金额与价格用 `Decimal`、在库里存文本
- [ ] J-Quants 适配器：`x-api-key`、分页、请求间隔 ≥ 1.1 秒、429 等待 120 秒、超时/网络错误/5xx 指数退避（5 → 10 → 20 → 40 秒，最多 5 次）；另有内存假适配器，能模拟 429、空响应和多页响应；普通测试不打网络
- [ ] 同步按设计 §4.2：日历 → 从最大日期之后逐日（日线 + 名册，每个日期一个事务）→ TOPIX → 拆合股核对 → 结果追加到 `var/jobs.jsonl`；库为空时从 5 年前开始，回填与每日同步是同一个函数
- [ ] 测试证明中断后重跑的结果与一次跑完逐行相同；当天日线返回空时报告「当天数据未出」，过去的开市日返回空时记警告后继续
- [ ] 质量标记按设计 §4.4 在写入时判定（`ok` / `excluded` / `untradable`），停牌日（OHLC 为空）落为 `untradable`
- [ ] 市场分类区间：市场区分、商品类别、33 行业任一变化时关闭旧区间、开新区间；代码在名册中消失时关闭区间；消失后又重新出现时记警告「代码重新出现」；公司名和规模分类只覆盖 `instruments`
- [ ] 研究价格读取按设计 §4.3：由成交价格和之后的调整系数往回连乘得到；配股只调价格不调成交量；测试覆盖一拆二、十合一、配股三种场景，并覆盖「拆股日前后的研究价格连续、没有假暴跌」
- [ ] 拆合股核对：同步中出现调整系数的证券按代码取除权日前 60 个交易日，比对 `AdjC` 与本地研究收盘价，超出误差记警告；回填完成后抽样 20 只核对
- [ ] 行情数据模块只暴露附录 A.1 的 interface；本票实现 `sync` / `read` / `calendar` / `overview`（`universe` 在 02 补上，也放在这个模块里）；`read` 一次取整批证券；其他模块不直接访问这 4 张表，也不自己算研究价格
- [ ] 后台任务按设计 §8 与附录 A.5（`submit` / `current` / `history` 三个方法）：进程内单任务线程与队列、`var/job.lock` 跨进程文件锁、每个开市日 18:00 排入同步、「当天数据未出」时每 30 分钟重试到 21:00；定时逻辑用可替换的时钟测试
- [ ] 命令行 `python -m app.cli sync` 在前台执行同一个同步函数，与服务内任务互斥
- [ ] API：`GET /api/data/status`、`POST /api/data/sync`、`GET /api/data/quality`、`GET /api/jobs/current`；前端客户端由 OpenAPI 生成
- [ ] 中文数据页 `/data`：最大日期、证券数、行数、当前任务进度、「立即同步」按钮、最近任务结果与警告、现算的质量警告（缺交易日、`untradable` 统计）
- [ ] 用真实 key 在 Docker 里完成一次 5 年回填（约 40 分钟），数据页显示的最大日期等于最近一个已发布数据的开市日
