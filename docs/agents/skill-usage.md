# Skill 与方法

复用现有入口：领域阅读见 [domain.md](domain.md)；任务状态与 GitHub 关系见 [issue-tracker.md](issue-tracker.md)。

## 方法

默认入口是 Codync。总管持有目标、设计、路线与验收；项目工匠执行获派的实现、普通测试与证据交回。实现使用 pstack；运行引擎与入口范围遵循 [AGENTS.md](../../AGENTS.md#claude-code--pstack-工作流)。任务状态与协作使用 GitHub 原生 Issue/PR/CI。`/to-spec` 与 `/to-tickets` 仍可作为方法使用；所选 pstack 步骤要求的验证与独立审阅照常执行，不省略。[delivery-gate.md](delivery-gate.md) 是历史说明，不是当前入口，也不自动授权实施。

模型分工由部署环境的项目工匠与总管配置决定；本仓库不固定 provider 映射。

## 默认动作

获派的项目工匠负责已确认 Issue 的修改、验证、普通测试与证据交回。生命周期、授权、单写者与审阅边界以 [AGENTS.md](../../AGENTS.md#claude-code--pstack-工作流) 为准；结果标签、重试与人工风险接受以 [ADR-0016](../adr/0016-pin-approved-spec-and-issue-status.md) 为准。只读核对可并行。

## 记忆

仓库正式文档优先于任何 Agent 记忆。记忆可作线索，不恢复授权、不覆盖批准 Spec，也不证明运行结果。`memory.backend` 数据策略未决定。项目 `.omp/config.yml` 是旧 OMP 设置，原样保留，其中请求 `autolearn.enabled: false` 与 `autoContinue: false`；它不是 Claude Code 配置，相对全局配置的实际优先级也未核验，不证明任何策略已经生效。不把某次会话的 CLI 覆盖写成项目策略。
