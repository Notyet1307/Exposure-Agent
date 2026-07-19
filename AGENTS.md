# Exposure-Agent 仓库协作契约

## 事实源与读取顺序

规划、实现或审阅前，按顺序读取：

1. 本文件；
2. `README.md`；
3. `CONTEXT.md`（如果存在）；
4. `docs/adr/` 中与当前改动相关的已接受 ADR；
5. `docs/architecture/commercial-function-and-data-architecture-v0.1.md` 的相关章节；
6. 当前已确认的 issue 或 factory `TASK.md`。

Factory 中，人工确认后的 `TASK.md` 是本轮唯一 Spec/AC；本文件、相关 ADR 和架构基线是仓库 Standards。任务与已接受 ADR 冲突时必须停止并显式重开决策，不得静默覆盖。

## 产品硬边界

- PostgreSQL 是唯一权威结构化业务事实库。
- agent-compose 负责调度、隔离和 Session 生命周期，不是业务事实源。
- OctoBus 是客户系统与云图的外部能力边界。
- Python、SQL 和 Polars 生成确定性事实；PI Agent 只基于有界 Evidence 生成结构化报告草稿，不计算权威统计、不修改 Finding。
- 未经新 ADR 明确批准，不引入 Redis、Celery、Kafka、Temporal、第二套调度器、通用规则 DSL 或默认多 Agent 路径。
- 只实现当前已确认任务，不提前推进架构文档中的后续阶段。

## Factory 工作流

- 正式功能、Bug 修复、跨文件改动和 issue 实现默认使用已部署的 `agent-tasks` factory 完成开发与自动审阅。
- 问答、只读分析、状态核查，以及明确要求的微小机械性单文件配置可以直接处理。
- 需求澄清可以使用 `/grill-with-docs`、`/to-spec` 和 `/to-tickets`；形成 agent-ready ticket 后交给 factory，不在宿主会话中用 `/implement` 替代 worker/reviewer。
- Factory 不得创建或改写目标仓的 `AGENTS.md`、`CLAUDE.md`、skills 或其他 agent instruction。本文件由指挥官直接维护，并在派发新任务前提交到预期基线。
- Factory 的具体命令、角色配置、状态机、重试和 review 协议以已部署 runtime 的 canonical contract 为准，不复制到本仓。

## 派发与人工 Gate

- 派发前确认目标仓已 checkout 预期基线、基线已有 commit，并独立检查工作区；未提交改动不会进入 factory worktree。
- 指挥官必须亲自核对 planner 生成的 `TASK.md`：允许改动白名单、全部 AC、现有代码锚点、设计决定、禁止事项和真实可运行的自检命令。
- planner 成功不代表可以放行；人工 gate 通过后才能运行 worker → reviewer 闭环，宿主会话不得直接替代其中任一角色。

## Review 与完成

- Factory reviewer 必须基于 recorded base 的仓库 Standards 和已确认 `TASK.md` 的 Spec/AC 完成双轴审阅；宿主 `/code-review` 不能替代 factory verdict。
- `passed` 只是合并的必要条件。指挥官仍须独立核对累计 diff、白名单、全部 AC、测试证据、目标产物、失败路径和边界行为。
- 只有 factory `passed` 且指挥官复核通过后才可合并；`failed_escalate` 必须交回人工判断。

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
