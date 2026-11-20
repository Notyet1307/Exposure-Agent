# Skill 与方法

复用现有入口：领域阅读见 [domain.md](domain.md)；任务状态与 GitHub 关系见 [issue-tracker.md](issue-tracker.md)。

## 派工与开工

1. 从 Cindy 新建任务时显式传 `project_path="/Users/yet/Developer/exposure2026"`、`agent_kind="pi"` 并启用隔离 worktree，标题前缀带 `[#<Issue号>]`。
2. 进入工作树后先运行 `bash scripts/wt-bootstrap.sh`（对应 `[bootstrap]` 工序），完成 `.venv`、前端依赖与 `verify --doctor` 预检。
3. 任务内读取原版 `poteto-mode/SKILL.md` 与同目录 `references/pi-tools.md`，按任务规模选择对应 playbook 和 skill；模型角色按仓库 [pstack-models.md](../../.pstack/pi-home/pstack-models.md) 执行。
4. 项目运行验证读取工作树的 [verify-exposure2026](../../.claude/skills/verify-exposure2026/SKILL.md)（不依赖非交互子代理目录发现）。因验证脚本归档已提交 `HEAD` 并豁免 `.agents/skills/` 注入软链，完成实现与单测后须**先在隔离任务分支完成本地候选 commit，再对 `HEAD` 执行运行验证**。

## 方法与看板工序

- 所选原版 `pstack` 步骤要求的验证与独立审阅照常执行，不省略。`/to-spec` 与 `/to-tickets` 仍可作为方法使用；[delivery-gate.md](delivery-gate.md) 是历史说明，不是当前入口，也不自动授权实施。
- Pi 主代理在会话 checklist 中使用固定工序前缀维护当前进度：`[bootstrap]` → `[design]` → `[implement]` → `[verify]` → `[review]` → `[pr-follow]` → `[ready]`，供 `cindy-task-board` 与 `get_task_digest` 读取当前工序。
- **开 PR 前归 `pstack`，开 PR 后归 Cindy `cindy-github`**：创建附验证摘要卡的 PR 后，使用 `cindy-github`（`pr` skill + `pr_card` + `pr-heartbeat-gate.mjs`）挂载后台变更/CI 跟进（无变化 0 模型唤醒），**取消前台阻塞 `gh pr checks --watch` 与 `pstack` `babysit`**。
- 任务内部子代理多轮协作保持过程静默；未获自动合并预授权时在必需 CI 全绿后停在 `[ready]` 并向派单会话回报一次摘要与证据链接，获显式预授权时按 `pr-snapshot.mjs --expect-head <sha> --strict-exit` 锁头 `squash` 合入（保留分支）。

## 边界与审阅

生命周期、两道人工门禁、单写者与任务内 fresh 只读审阅遵循 [AGENTS.md](../../AGENTS.md#cindy--pi--pstack-工作流)；结果四态（`PASS / FAIL / BLOCKED / NOT_RUN`）、重试与人工风险接受遵循 [ADR-0016](../adr/0016-pin-approved-spec-and-issue-status.md)。只读核对可并行。

## 记忆

仓库正式文档优先于任何 Agent 记忆。记忆可作线索，不恢复授权、不覆盖批准 Spec，也不证明运行结果。`memory.backend` 数据策略未决定。项目 `.omp/config.yml` 是旧 OMP 设置，原样保留，其中请求 `autolearn.enabled: false` 与 `autoContinue: false`；它不是 Cindy 托管 Pi 的配置，相对全局配置的实际优先级也未核验，不证明任何策略已经生效。不把某次会话的 CLI 覆盖写成项目策略。
