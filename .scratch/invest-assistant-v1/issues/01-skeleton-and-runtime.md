# 01 — 项目骨架与运行环境

**What to build:** 克隆仓库、复制 `.env.example` 为 `.env`、执行 `docker compose up`，前后端两个服务就在本机起来：浏览器打开中文界面外壳，看到数据 / 信号 / 账户三个入口；挂载卷上的 `var/invest.db` 已经由 Alembic 建好，等着 02 往里加表。后端和前端各自的测试都能跑，后面每张票直接往上加。

**Design:** [invest-assistant v1 系统设计](../spec.md) §10，附录 A.1（目录结构）

**Blocked by:** —

**Status:** ready-for-agent

- [x] 后端骨架：uv、FastAPI、SQLAlchemy 2 + Alembic、structlog、pydantic-settings、pytest；`app/` 按设计 §10 的目录结构建好，`market_data/`、`strategies/`、`accounts/` 先是空模块
- [x] 配置用 pydantic-settings 从环境变量读取（数据库路径、`JQUANTS_API_KEY`、时区）；缺 key 时服务照常启动，只在真要抓数据时才报错
- [x] Alembic 接好线：`alembic.ini`、`env.py` 指向配置里的 SQLite 路径、一个空的初始迁移；`upgrade head` 和 `downgrade base` 都跑得通。表本身在 02 起建
- [x] 前端骨架：Next.js 16、React 19、TypeScript、Vitest；中文界面外壳与导航（数据 / 信号 / 账户三个入口，页面本身先留空）；openapi-typescript 的客户端生成脚本就位并能跑通（此时后端还没有业务端点）
- [x] `docker-compose.yml`：`backend` + `frontend` 两个服务，SQLite 在挂载卷的 `var/invest.db`，容器时区 `Asia/Tokyo`，端口只绑定 `127.0.0.1`；`.env.example` 含 `JQUANTS_API_KEY`
- [x] 测试基架：pytest 有一个「建临时 SQLite 文件并跑 `alembic upgrade head`」的 fixture，供后面每张票复用；前端 Vitest 跑通一个冒烟测试
- [x] `docker compose up` 后两个服务都起来、`var/invest.db` 建好、浏览器能打开中文外壳页

## Comments

**2026-09-23** — 做完。两处值得记下来的决定：

- 迁移不接受数据库参数。`migrations/env.py` 自己从环境变量构造 `Settings`，`app/migrate.py` 也一样，所以指向另一个数据库只有 `DATABASE_PATH` 一条路——容器、测试和命令行走的是同一条。
- 前端客户端从仓库里的 `openapi.json` 生成，不从运行中的后端拉。`python -m app.openapi_dump` 刷新它，于是 API 的变化会出现在 diff 里，`npm run generate:api` 也不需要先把服务起起来。

测试：后端 8 个、前端 1 个。`docker compose up` 两个服务起来，`var/invest.db` 由启动时的迁移建出，容器时间是 JST。
