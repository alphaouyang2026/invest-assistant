---
status: accepted
date: 2026-09-23
---

# 使用 SQLite 单文件，不用 PostgreSQL

my-invest 依赖 PostgreSQL 的 advisory lock、JSONB、DISTINCT ON 和部分唯一索引来实现并发同步与快照可见性。invest-assistant 只有一个用户、几张表、几百万行日线，且行情按（证券, 交易日）覆盖写入（ADR-0001），用不到这些能力，所以用 SQLite 单文件：不需要单独的数据库服务，备份就是复制一个文件。代价是同一时刻只能有一个写入者，同步、回测和模拟交易的写入必须排队进行。
