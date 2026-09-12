# 当前工作

- 正式任务：[EXP-UX-02 #232：产品模型连接的安全版本与实际启用](https://github.com/Notyet1307/Exposure-Agent/issues/232)。任务状态、依赖与授权以 GitHub Issue 为准。
- 固定批准 Spec：[asset-governance-release-1.md@058b65f](https://github.com/Notyet1307/Exposure-Agent/blob/058b65f883c829d20b0dd522df1d1476b2f52650/docs/specs/asset-governance-release-1.md)，EXP-UX-02 节；配套 [ADR-0017](../adr/0017-product-model-connection-lifecycle.md)。
- 分支：`codex/exp-ux-02`，代码基线 `fcee9faec2135eea52127dd18eeeaa44e1c41d74`。
- 当前已完成规格、ADR、领域术语与正式任务衔接；文档审阅和上下文检查通过，产品实现与运行时试验未因此成为 PASS。
- 首个技术步骤：独立数据库、Artifact、agent-compose 与本地固定响应端点的 A/B 版本绑定试验。证明 B 接收新任务，未撤销 A 的旧任务仍用 A，显式撤销 A 后阻断其后续请求；核对凭据不泄露。安全绑定未证实前不接完整设置 UI，不宣称实际启用。
- 机制成立后在同一任务内接版本/Secret存储、权限/审计、验证/启用/接管与独立AI设置。真实 Provider 的目的地、材料和调用另行固定授权；本地固定响应不代替真实模型能力验收。
- 保护当前8080、模型与Runner绑定、B0/400及EXP-UX-01合成结果、其他工作树和WIP。当前授权不自动包含业务代码发布、PR、合并、正式部署或关闭Issue。
- 前一切片：[EXP-UX-01 #230](https://github.com/Notyet1307/Exposure-Agent/issues/230) 已经 [PR #231](https://github.com/Notyet1307/Exposure-Agent/pull/231) 合并、本机部署、维护者体验确认并关闭；历史结果和未运行项保留，不重做01，不提前扩展03/04。
- 权威规则：[ADR-0016](../adr/0016-pin-approved-spec-and-issue-status.md)。
