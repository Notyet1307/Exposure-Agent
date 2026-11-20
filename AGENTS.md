# Exposure-Agent 仓库协作契约

## 默认读取路由

规划、实现或审阅前，按当前任务需要读取：

1. 本文件；
2. 当前工作、候选、下一步或停止：`docs/work/current.md`；
3. 行为、验收标准或批准范围：读取 `current.md` 所指当前 Issue 固定的 Spec 路径与 commit；产品收敛规格落点为 `docs/specs/exposure-focus-release-1.md`，旧 Run/报告及兼容行为按 `docs/specs/asset-governance-release-1.md` 的对应固定合同读取；
4. 任务状态、依赖或授权：当前 GitHub Issue（须引用 Spec 路径与 commit）；
5. 与任务相邻的代码和测试；
6. 仅与任务相关的已接受 ADR；
7. 需要领域术语时再读 `CONTEXT.md`；
8. 涉及部署或系统边界时再读 `docs/architecture/current-state.md` 和相关 Runbook。

Git 中已批准且固定版本的 Spec 定义行为预期。GitHub Issue 是唯一任务状态、依赖与授权表面。本文件和相关已接受 ADR 是仓库 Standards。代码与已接受 ADR 冲突时必须停止并报告，不得静默覆盖。

权威、验收结果、重试：`docs/adr/0016-pin-approved-spec-and-issue-status.md`。
Skill、方法、记忆、单写者：`docs/agents/skill-usage.md`。

## 默认不读取

除非当前任务明确需要，默认不读取：

- `docs/product/target-state.md` 等非规范性目标状态；
- Git 历史材料、关闭 Issue 的验收记录或历史 Evidence；
- 生成客户端、lock files 和二进制截图；
- 与当前任务无关的迁移历史；
- 未来产品实验。

`frontend/src/client/**` 和 `frontend/src/routeTree.gen.ts` 是生成文件，仅在 API Contract 或路由生成相关任务中按需读取，禁止手工编辑。API 变更后使用 `bash scripts/generate-client.sh` 更新客户端。

任务规划、实现、审阅和发布统一通过 Cindy 项目任务入口，在托管 Pi 中按原版 pstack 方法执行，并使用 GitHub 原生能力。仓库内遗留的 pi-ticket-planning、HerdrHarness、Wayfinder、Admission、Delivery Graph、Frontier 和 Controller 材料仅视为历史文档，不作为当前流程入口。

文档事实源索引见 `docs/README.md`。

## 产品硬边界

- PostgreSQL 是唯一权威结构化业务事实库。
- agent-compose 负责调度、隔离和 Session 生命周期，不是业务事实源。
- OctoBus 是客户系统与云图的外部能力边界。
- Python、SQL 和 Polars 生成确定性事实；报告或模型 Agent 只基于有界 Evidence 生成结构化报告草稿，不计算权威统计、不修改 Finding。
- 未经新 ADR 明确批准，不引入 Redis、Celery、Kafka、Temporal、第二套调度器、通用规则 DSL 或默认多 Agent 路径。
- 只实现当前已确认任务，不提前推进目标状态中的能力。

## Cindy + Pi + pstack 工作流

- Exposure 任务从 Cindy 已登记的 Exposure 项目创建，显式选择托管 Pi 与隔离 worktree，标题带 `[#<Issue号>]`。
- 一个已确认的 GitHub Issue 对应一个托管 Pi 任务闭环；同一候选同一时间只有一个源码写入者。开 PR 前按原版 `pstack`（`poteto-mode`，随任务复杂度弹性升级调查/设计/审阅深度）调度原生子代理；开 PR 后交由 Cindy 内置 `cindy-github`（`pr` skill + `pr_card` + `pr-heartbeat-gate.mjs` 后台零空闲 token 巡检）跟进 CI 与评论，禁止前台阻塞运行 `gh pr checks --watch` 或 `babysit`。
- 只实现当前已确认的 GitHub Issue；行为预期以该 Issue 引用的批准固定 Spec 为准。
- 人工门禁收口为两道（只读请求、明确禁止、暂停及既有停止点继续有效）：
  1. **开工授权**：确认 Issue 与固定 Spec（存在产品、UI 或架构歧义时先确认设计），授权范围包含隔离任务分支上的本地候选 commit、运行验证、push 分支、创建附验证摘要卡的 PR 及后台跟进必需 CI。本地提交只纳入本任务范围并保护其他改动。
  2. **落地授权**：默认在必需 CI 全绿且无未决评论后停在 `[ready]`，由人工核对证据后批准 merge、云端部署及关闭 Issue；仅当派单显式预授权自动合并时，后台跟进可在 `pr-snapshot.mjs --expect-head <sha> --strict-exit` 校验通过后锁头 `squash` 合入（保留远端分支）。
- 因 `.claude/skills/verify-exposure2026/SKILL.md` 基于 `git archive HEAD` 验证且拦截未提交产品改动，隔离任务分支须按**先完成 `/deslop` 与 `/no-comments` → 本地候选 commit → 对 `HEAD` 执行 `verify-exposure2026` → 任务内非作者 fresh 只读审阅**顺序推进；`verify-exposure2026` 之后任何改写 `HEAD` 的操作（含 `rebase`、`amend` 及开 PR 后 `cindy-github` 后台修补轮次）均使旧验证证据作废，须按最新 `HEAD` 重跑验证与必要复审。进入 `[ready]` 及门禁 2 合入前，必须核对冻结清单 `frozen-assets.json` 中的 `product_head` 等于 PR 当前 `head_sha`。代码审阅与独立业务验收分开，结果使用 `PASS / FAIL / BLOCKED / NOT_RUN`（见 `docs/adr/0016-pin-approved-spec-and-issue-status.md`）。
- PR 正文、评论与验证摘要卡严禁写入本机路径（含家目录或绝对路径）、云账号/IP 或宿主环境标识，仅记录结构化证据 ID、`product_head` 与四态结论；截图等可视化证据须使用审阅者可访问的持久链接，无法外发时仅保留文字说明与证据 ID。
- PR 后台修补与本地重试统一遵循 `docs/adr/0016-pin-approved-spec-and-issue-status.md`：同一原因连续两轮无新证据即停止循环并转入诊断，不无界重试。
- GitHub 分支保护、必需 CI 和 Review 门禁始终有效；不设置独立 Controller、Admission 或 ready-label 自动授权。

## Fresh worktree 初始化与验证

首次进入新的 worktree 后，先执行一键初始化与预检，或按需安装受影响部分的依赖：

- 一键初始化与验证自检：`bash scripts/wt-bootstrap.sh`

- 后端（仓库根目录）：`uv sync --frozen`
- 前端：`cd frontend && bun install --frozen-lockfile`

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
- 不覆盖、清理或重置用户已有改动；**严禁执行 `git reset --hard`**。对于隔离 worktree 清理，仅放行 `pstack` 底层 `settleWorktree` 自动回收**干净且无任何提交或变更**的空子 worktree，其余目录、非空工作树与旧分支均遵守“归档不删除”。
- 不简化认证、授权、审计、信任边界校验、防数据丢失处理和必要错误处理。
- Alembic revision 一旦进入共享历史（push、PR、main 或部署）即不得删除或重写；从未共享的任务分支 revision 可在首次 push 前修正，其他 Schema 变化必须新增迁移。
- 非平凡逻辑保留最小可运行检查；未运行或失败的测试必须如实说明。

## 仓库工作流入口

- [验证入口](.claude/skills/verify-exposure2026/SKILL.md)与 [Feature Map](.claude/skills/verify-exposure2026/features/README.md)
- Issue tracker：`docs/agents/issue-tracker.md`
- Triage labels：`docs/agents/triage-labels.md`
- Domain docs：`docs/agents/domain.md`
- Skill 与方法：`docs/agents/skill-usage.md`
- Cindy / Pi 升级只读兼容预检：`bash scripts/check-cindy-pi-compat.sh`
- 本地只读工程巡检看板：`node scripts/pstack-ops-dashboard.mjs`
