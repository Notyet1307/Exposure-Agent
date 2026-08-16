# Exposure-Agent 仓库协作契约

## 事实源与读取顺序

规划、实现或审阅前，按顺序读取：

1. 本文件；
2. `README.md`；
3. `CONTEXT.md`（如果存在）；
4. `docs/adr/` 中与当前改动相关的已接受 ADR；
5. `docs/architecture/commercial-function-and-data-architecture-v0.1.md` 的相关章节；
6. 当前已确认的 GitHub issue 或 PRD。

当前已确认的 GitHub issue 是本轮唯一 Spec/AC；本文件、相关 ADR 和架构基线是仓库 Standards。任务与已接受 ADR 冲突时必须停止并显式重开决策，不得静默覆盖。

## 产品硬边界

- PostgreSQL 是唯一权威结构化业务事实库。
- agent-compose 负责调度、隔离和 Session 生命周期，不是业务事实源。
- OctoBus 是客户系统与云图的外部能力边界。
- Python、SQL 和 Polars 生成确定性事实；PI Agent 只基于有界 Evidence 生成结构化报告草稿，不计算权威统计、不修改 Finding。
- 未经新 ADR 明确批准，不引入 Redis、Celery、Kafka、Temporal、第二套调度器、通用规则 DSL 或默认多 Agent 路径。
- 只实现当前已确认任务，不提前推进架构文档中的后续阶段。

## Harness 工作流

- 只实现当前被 Harness 领取的 GitHub issue；父 Map 仅提供上下文，不是实现范围。
- Implementer 负责修改、验证并提交当前分支；不得 push、创建 PR、merge、修改标签或关闭 issue。
- 独立 Auditor 根据仓库 Standards 和当前 issue 的 Spec/AC 审阅；审计不通过时由 Harness 驱动受控返工。
- Controller 仅在审计通过后发布 PR；默认 wait 模式下最终合并仍由人工控制。
- 可选 auto 模式仅在独立审计通过后运行，并使用 GitHub 原生的 `gh pr merge --auto --match-head-commit <audited-sha>`。
- 所需 CI 与 Review 门禁仍由 GitHub 分支规则负责。

## Fresh worktree 初始化

首次进入新的 worktree 后，按需安装受影响部分的依赖：

- 后端：`cd backend && uv sync`
- 前端：`cd frontend && bun ci`

常用验证命令：

- 后端 lint/typecheck：`cd backend && uv run bash scripts/lint.sh`
- 后端测试：`cd backend && uv run bash scripts/tests-start.sh`
- 前端 lint：`cd frontend && bun run lint`
- 前端 typecheck/build：`cd frontend && bun run build`

后端完整测试需要可用的 PostgreSQL；如果环境未启动，必须明确报告未运行的测试及原因，不得声称验证通过。

## 改动纪律

- 不增加任务未要求的功能、抽象、依赖或顺手重构；先复用仓库现有实现、标准库和已安装依赖。
- Bug 修复定位共享根因，并检查所有调用方；不得只修报告中的单一路径。
- 不覆盖、清理或重置用户已有改动。
- 不简化掉认证、授权、审计、信任边界校验、防数据丢失处理和必要错误处理。
- 非平凡逻辑保留最小可运行检查；未运行或失败的测试必须如实说明。

## Agent skills

### Issue tracker

Issues and PRDs are tracked in this repository's GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the canonical triage labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Use the single-context domain documentation layout. See `docs/agents/domain.md`.

### Delivery gate

候选实现 issue 必须先通过独立 Admission 才能进入执行队列。见 `docs/agents/delivery-gate.md`。
