# invest-assistant

日本股票的行情同步、技术信号与模拟交易。设计见 [.scratch/invest-assistant-v1/spec.md](.scratch/invest-assistant-v1/spec.md)，术语见 [CONTEXT.md](CONTEXT.md)。

## 运行

```bash
cp .env.example .env     # 填 JQUANTS_API_KEY；没有 key 也能起来
docker compose up
```

前端 <http://127.0.0.1:3000>，后端 <http://127.0.0.1:8000>。两个端口都只绑定本机。
SQLite 落在 `var/invest.db`（宿主机目录），备份就是复制这一个文件。

## 开发

后端的测试和命令都从 `backend/` 下跑——pytest 的配置在 `backend/pyproject.toml` 里：

```bash
uv run --directory backend pytest          # 后端测试
uv run --directory backend python -m app.migrate        # 手动迁移到 head
uv run --directory backend python -m app.openapi_dump   # 刷新根目录的 openapi.json
npm --prefix frontend run test             # 前端测试
npm --prefix frontend run generate:api     # 由 openapi.json 生成前端客户端类型
```

换一个数据库（测试、临时回填）只有一种办法：设 `DATABASE_PATH`。迁移、服务和命令行都从它读。
