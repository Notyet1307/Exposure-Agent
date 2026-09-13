# 当前工作

- 正式任务：[EXP-UX-02 #232：产品模型连接的安全版本与实际启用](https://github.com/Notyet1307/Exposure-Agent/issues/232)。状态、依赖与授权以 GitHub Issue 为准。
- 固定批准 Spec：[asset-governance-release-1.md@058b65f](https://github.com/Notyet1307/Exposure-Agent/blob/058b65f883c829d20b0dd522df1d1476b2f52650/docs/specs/asset-governance-release-1.md)，EXP-UX-02 节；配套 [ADR-0017](../adr/0017-product-model-connection-lifecycle.md)。
- 分支 `codex/exp-ux-02`；代码基线 `fcee9faec2135eea52127dd18eeeaa44e1c41d74`。模型连接版本/Secret、管理接口、受限代理及独立 AI 设置已形成本地候选；旧 governance draft 的占位会话行为保留，新记录固定版本，不新增模型生成。
- 发布前 Standards/Spec 总审发现的 draft 功能退回已修复并复审；当前无代码 blocker。完整后端回归 1089 项通过，前后端 lint/typecheck/build、迁移及静态 Compose 检查通过；真实隔离 Pi 的 A/B、故障恢复、撤销及 draft 零模型请求检查通过。详细证据和未运行项以 [Issue 验收记录](https://github.com/Notyet1307/Exposure-Agent/issues/232#issuecomment-5646459059)及后续进度为准，本地临时回执/机制 probe 不进入 main。
- 维护者已授权按明确提交清单提交、推送并创建草稿 PR；提交、PR 与 CI 的最新状态以正式 Issue 为准。合并、部署和关闭仍未授权。真实 Provider 的目的地/材料、生产部署/CORS和维护者体验仍需分别验收，本地合成不替代完整 AC02。
- 部署准备：[模型连接部署与恢复说明](../runbooks/model-connections.md)及可选 `compose.model-connections.yml`；默认 Compose 不自动挂载主密钥或接管旧连接。
- 保护当前8080、原模型与Runner、B0/400及EXP-UX-01结果、其他工作树和WIP。前一切片 [#230](https://github.com/Notyet1307/Exposure-Agent/issues/230) 已经 [PR #231](https://github.com/Notyet1307/Exposure-Agent/pull/231) 合并、本机部署、维护者体验确认并关闭；不提前扩展03/04。权威规则：[ADR-0016](../adr/0016-pin-approved-spec-and-issue-status.md)。
