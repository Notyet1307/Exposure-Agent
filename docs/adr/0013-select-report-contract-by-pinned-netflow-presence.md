# ADR-0013：按固定 NetFlow 输入选择生产报告合同

状态：已接受

日期：2026-09-07

## 背景

ADR-0008 已接受 `governance-run-input-v1` 的 NetFlow explicit absent / present / legacy 三态、固定输入和 Hash 合同，但明确没有决定 report-v2。随后 #176、#177 已分别实现严格的 `deterministic-report-v2` candidate 和事务内三来源比较事实绑定；生产 Runner 仍对 absent 与 present 都固定并发布 `deterministic-report-v1`，这些能力尚未进入客户可见 Publish。

报告合同是 Run 的固定输入。若在存在 launch reservation 或活跃 Runner 时改变选择规则，同一个已保留 Hash 可能在不同部署版本中被解释为不同报告，且 reservation 本身不能恢复完整输入 payload。因此生产分派必须是机械、单一并在排空后切换。

Issue #179 已确认本决策及其 Delivery Spec。ADR-0011 仍为提议；本 ADR 不接受其中与本决策冲突的零记录失败或 warning 终态规则。

## 决策

### 新 Run 的机械分派

完成协调切换后，所有新建且 `input_contract_version=governance-run-input-v1` 的 Run 按其固定 NetFlow 三态选择报告合同：

- explicit absent：`deterministic-report-v1`；
- present：`deterministic-report-v2`。

报告合同版本必须由唯一 typed `PinnedTriggerInputs` builder 生成，并进入 canonical input vector 与 `input_hash`。API、Runner、GovernanceRun 持久字段和 Retry 重建不得存在第二个版本来源或优先级。

Retry 只复用原 Run 的固定 NetFlow 输入、报告合同和 Hash；Rerun 用新 Trigger 读取 Project 当前选择并建立新 Run。切换前已建立的 Run 与 legacy / unmodeled Run 按已存值执行，不回填，也不得从当前 Project 选择重新推断。

### 发布与终态

Absent/v1 保持既有 canonical JSON、HTML、CSV、四类 Evidence 和 Finding 语义，不持久化 `IPSourceComparisonFact`。

Present/v2 在既有最终 PostgreSQL Publish 事务中一并提交完整 `IPSourceComparisonFact`、comparison Evidence、NetFlow activity、Finding lifecycle、Report/Artifact metadata、治理 Evidence、Run 完成、Project latest pointer 和 audits。SourceSnapshot、Observation、Resource 等上游运行事实仍在既有可重入步骤中提前固定，不在最终事务重建。

固定 Dataset 和 Artifact 完整时，即使 raw record 为 0、有效 activity 为 0、没有正向活动或 Dataset 带既有 warning，Run 仍以 `COMPLETED` 发布。数据限制由 `UNKNOWN`、`no_positive_activity_evidence` 等确定性事实表达，不得把未观察到解释为不存在。本决策不新增 `COMPLETED_WITH_WARNINGS` 生产规则；已发布读取、不可变门禁和 Retry 终态判断继续兼容已有的 `COMPLETED_WITH_WARNINGS`。

### 协调切换

生产启用只能执行一次排空后的单路径切换：

1. 暂停或拒绝新 Trigger；
2. 确认所有 Project 无 launch reservation；
3. 确认无 RUNNING GovernanceRun、活跃 Runner 或状态未知的 agent-compose Session；
4. 部署统一版本后恢复 Trigger。

任一检查无法证明安全即中止切换。代码不增加 feature flag、版本策略表，也不支持新旧 Runner 混合选择报告合同。

## 后果

- 新 present Run 不得降级为 v1；v2 candidate、比较事实和 Report 必须作为同一已发布事实集合原子提交。
- v1 历史字节与语义稳定；迁移不更新历史 Run。
- reservation 仍只保存身份和 Hash，不扩展成第二套 payload 事实源。
- 后续报告选择策略若变化，必须再次执行排空切换或先接受新的输入合同。
- 三来源显式 Run API、矩阵 UI、Lineage 与 v2 AI draft 不由本 ADR 授权，分别留给后续 Issue。

## 被拒方案

### Present 继续发布 v1

拒绝。它会让已经完成的 v2 candidate 与比较绑定永久停留在测试 seam，无法形成 #180–#183 所需的生产发布基线。

### 用 feature flag 或混合滚动切换

拒绝。reservation 无法恢复完整 payload；引入第二个策略状态只会扩大重放和跨版本歧义，没有已确认的长期双策略需求。

### 零记录或低质量输入自动进入失败 / warning 终态

拒绝。本轮保持 ADR-0008 和现有生产合同：存在且完整的零记录 Dataset 与 absent 不同，但仍可成功发布；其证据边界由 UNKNOWN 表达。

### 为 absent/v1 持久化比较事实

拒绝。双来源比较可从既有不可变事实确定性读取，新增无当前消费者的持久副本会改变 v1 发布集合而没有收益。
