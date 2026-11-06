# Skill 与方法

复用现有入口：领域阅读见 [domain.md](domain.md)；任务状态与 GitHub 关系见 [issue-tracker.md](issue-tracker.md)。

## 方法

默认入口是 Codync。总管持有目标、设计、路线与验收；项目工匠执行获派的实现、普通测试与证据交回。实现运行在 Claude Code，开发方法使用 pstack；任务状态与协作使用 GitHub 原生 Issue/PR/CI。`/to-spec` 与 `/to-tickets` 仍可作为方法使用；所选 pstack 步骤要求的验证与独立审阅照常执行，不省略。[delivery-gate.md](delivery-gate.md) 是历史说明，不是当前入口，也不自动授权实施。不要恢复 Controller、Release Graph 或 ready-label 自动授权；总管的正常派工不属于这些机制。

模型分工由部署环境的项目工匠与总管配置决定；本仓库不固定 provider 映射。

## 默认动作

获派的项目工匠负责已确认 Issue 的修改、验证、普通测试与证据交回。commit、push、创建 PR、merge、部署和关闭 Issue 各是独立生命周期状态，各自需要明确授权与验收；pstack 步骤结束不构成对下一状态的授权。同一候选同一时间只有一个源码写入者；只读核对可并行。

实现完成后，总管组织非作者的独立 Standards 与 Spec 两轴审阅；独立业务验收另记，不用代码审阅代替。

## 记忆

仓库正式文档优先于任何 Agent 记忆。记忆可作线索，不恢复授权、不覆盖批准 Spec，也不证明运行结果。`memory.backend` 数据策略未决定。项目 `.omp/config.yml` 是旧 OMP 设置，原样保留，其中请求 `autolearn.enabled: false` 与 `autoContinue: false`；它不是 Claude Code 配置，相对全局配置的实际优先级也未核验，不证明任何策略已经生效。不把某次会话的 CLI 覆盖写成项目策略。
