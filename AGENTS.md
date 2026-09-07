# Exposure-Agent 仓库协作契约

## 默认读取路由

规划、实现或审阅前，按当前任务需要读取：

1. 本文件；
2. 当前已领取的 GitHub Issue / PRD；
3. 与任务相邻的代码和测试；
4. 仅与任务相关的已接受 ADR；
5. 需要领域术语时再读 `CONTEXT.md`；
6. 涉及部署或系统边界时再读 `docs/architecture/current-state.md` 和相关 Runbook。

当前已确认的 GitHub Issue 是本轮唯一 Spec/AC；本文件和相关已接受 ADR 是仓库 Standards。代码与已接受 ADR 冲突时必须停止并报告，不得静默覆盖。

## 默认不读取

除非当前任务明确需要，默认不读取：

- `docs/product/target-state.md` 等非规范性目标状态；
- Git 历史材料、关闭 Issue 的验收记录或历史 Evidence；
- 生成客户端、lock files 和二进制截图；
- 与当前任务无关的迁移历史；
- 未来产品实验。

`frontend/src/client/**` 和 `frontend/src/routeTree.gen.ts` 是生成文件，仅在 API Contract 或路由生成相关任务中按需读取，禁止手工编辑。API 变更后使用 `bash scripts/generate-client.sh` 更新客户端。

任务规划、实现、审阅和发布只使用当前 OMP 的原生工具与 GitHub 原生能力。仓库内遗留的 pi-ticket-planning、HerdrHarness、Wayfinder、Admission、Delivery Graph、Frontier 和 Controller 材料仅视为历史文档，不作为当前流程入口。

文档事实源索引见 `docs/README.md`。

## 产品硬边界

- PostgreSQL 是唯一权威结构化业务事实库。
- agent-compose 负责调度、隔离和 Session 生命周期，不是业务事实源。
- OctoBus 是客户系统与云图的外部能力边界。
- Python、SQL 和 Polars 生成确定性事实；报告或模型 Agent 只基于有界 Evidence 生成结构化报告草稿，不计算权威统计、不修改 Finding。
- 未经新 ADR 明确批准，不引入 Redis、Celery、Kafka、Temporal、第二套调度器、通用规则 DSL 或默认多 Agent 路径。
- 只实现当前已确认任务，不提前推进目标状态中的能力。

## OMP 原生工作流

- 只实现当前对话已确认的 GitHub Issue；该 Issue 是本轮唯一 Spec/AC。
- 当前 OMP 会话负责修改、验证和提交；用户明确要求远端操作后，同一会话可继续 push、创建 PR、观察 CI、merge，并按验收状态更新或关闭 Issue。
- 实现完成后使用 OMP 原生 reviewer，分别按仓库 Standards 与当前 Issue Spec/AC 独立审阅；发现 blocker 时修复并重新审阅。
- 远端生命周期逐项验收：push 前确认本地提交和验证结果，merge 前确认所需 CI/Review，关闭 Issue 前确认 PR 已合并且任务要求的部署验收已完成或明确不适用。
- GitHub 分支保护、必需 CI 和 Review 门禁始终有效。
- 不设置独立 Controller、Admission 或外部 planning handoff。

## Fresh worktree 初始化与验证

首次进入新的 worktree 后，按需安装受影响部分的依赖：

- 后端：`cd backend && uv sync`
- 前端：`cd frontend && bun ci`

常用验证命令：

- 上下文门禁：`python3 scripts/check-context-hygiene.py`
- 后端 lint/typecheck：`cd backend && uv run bash scripts/lint.sh`
- 后端测试：`cd backend && uv run bash scripts/tests-start.sh`
- 前端 lint：`cd frontend && bun run lint`
- 前端 typecheck/build：`cd frontend && bun run build`

后端完整测试需要可用的 PostgreSQL；如果环境未启动，必须明确报告未运行的测试及原因，不得声称验证通过。

## 改动纪律

- 不增加任务未要求的功能、抽象、依赖或顺手重构；先复用仓库现有实现、标准库和已安装依赖。
- Bug 修复定位共享根因，并检查所有调用方；不得只修报告中的单一路径。
- 不覆盖、清理或重置用户已有改动。
- 不简化认证、授权、审计、信任边界校验、防数据丢失处理和必要错误处理。
- Alembic revision 一旦进入共享历史（push、PR、main 或部署）即不得删除或重写；从未共享的任务分支 revision 可在首次 push 前修正，其他 Schema 变化必须新增迁移。
- 非平凡逻辑保留最小可运行检查；未运行或失败的测试必须如实说明。

## 仓库工作流入口

- Issue tracker：`docs/agents/issue-tracker.md`
- Triage labels：`docs/agents/triage-labels.md`
- Domain docs：`docs/agents/domain.md`
