# Exposure-Agent 文档索引

| 问题类型 | 权威来源 |
|---|---|
| 当前行为预期 | `work/current.md` 所指 Issue 固定的批准 Spec；产品收敛为 [exposure-focus-release-1.md](specs/exposure-focus-release-1.md)，旧 Run/报告及兼容行为为 [asset-governance-release-1.md](specs/asset-governance-release-1.md) |
| 当前任务状态与授权 | 引用该 Spec 的 GitHub Issue；一页导航 `work/current.md` |
| 既有已实现产品范围 | `product/current-scope.md`；新方向及未实现目标按当前固定Spec区分 |
| 产品收敛接管与阶段定义 | [EXP-FOCUS-00 接管回执](work/exp-focus-00-takeover-20260923.md)、[00—05阶段路线](plans/exposure-focus-20260923.md)；回执为历史核对，路线不承载任务状态 |
| 云图完整阅读合同与替代边界 | [字段覆盖矩阵](plans/exposure-focus-cloudatlas-coverage-20260923.md)、[ADR-0021](adr/0021-independent-cloudatlas-local-read-model.md)、[ADR-0022 有界批次可读](adr/0022-bounded-external-asset-publication.md)；非全量批次不冒充完整同步，未知项不是已验证能力 |
| 其他既有交接 | `handoff-receipt.md`；不覆盖当前 Issue 的授权 |
| 当前实现行为 | 代码、测试、迁移和 Compose |
| 稳定架构约束 | `docs/adr/` 中已接受 ADR 与 `architecture/constraints.md` |
| 领域词汇 | `../CONTEXT.md` |
| 开发与部署 | `../development.md`、`../deployment.md` 和当前 Runbook（[模型连接部署与恢复准备](runbooks/model-connections.md)） |
| 未来目标 | `product/target-state.md`；非规范性且不是实现范围 |
| 历史证据 | Git 历史、关闭的 Issue / PR；不进入默认上下文 |

当前代码与已接受 ADR 冲突时必须停止并报告。目标架构不能证明功能已经实现。历史文档（含旧 REL-003）不能充当当前 Spec。过程证据由 Git 历史保存。Issue 不是第二份可漂移的完整 Spec。

main 不接受 Issue 专属 probe、临时 Evidence 或固定 Run 验收快照。

待确认的产品实施规格：[三源比对工作台 V1（A 方案）](specs/three-source-workbench-v1.md)、[结果留存 ADR-0023 提案](adr/0023-versioned-result-retention.md)及[拟发布任务拆分](plans/three-source-workbench-tickets-20261004.md)。它们不替代当前 Issue 的固定行为或任务状态；获准发布后由新 Issue 固定实际版本。

静态交接：[NetFlow 首次使用 #279](work/netflow-usability-handoff.md) 记录本轮提交和合成验收；[历史接管回执](handoff-receipt.md) 仅对应其旧 SHA。它们均不替代 GitHub Issue 的当前状态与授权。
