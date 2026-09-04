# ADR-0011：提议 report-v2、三来源 Evidence 与原子 Publish 边界

状态：提议

日期：2026-09-04

## 门禁

本 ADR 是 Issue #166 的候选共享合同，不接受 ADR-0009/0010，不代表独立 Admission，也不授权 R1 实现、迁移或上线。
`IPSourceComparisonFact`、`deterministic-report-v2` 与本 ADR 中的 NetFlow 语义在决策被接受前仍是候选术语。

## 已核对的现状

- 当前 `PinnedTriggerInputs.input_hash()` 不含可选的 report version，而 API 另把它放入 Runner environment（`backend/app/domain/governance_runs.py:161-218`；`backend/app/api/routes/governance_runs.py:503-510,749-755,1068-1074`）。这是后续 R1 必须一次清除的双来源缺口，不是目标合同。
- 当前 Project reservation 三字段由数据库约束为全空或全非空；`reserve_run_launch()` 对同 Trigger replay 核对 trigger/control/input Hash，但 Runner 允许 reservation 为空的 legacy direct-start，并只在 trigger 匹配时条件清理 reservation（`backend/app/domain/models.py:55-60`；`backend/app/domain/governance_runs.py:446-458,619-630,3688-3710`）。
- v1 compiler 只接受 `deterministic-report-v1` 且要求恰好两份完整 Snapshot；selector 与 renderer 也只接受该版本并生成 canonical JSON、HTML、CSV（`backend/app/domain/report_core.py:28,282-302,472-489`；`backend/app/domain/evidence_selector.py:282-305`；`backend/app/domain/report_renderer.py:720-745`）。
- 当前每 Run 最多一个 `GovernanceReport`；list/detail 的外层字段包含存储的 contract version，CSV 使用现有下载路由（`backend/app/domain/models.py:640-744`；`backend/app/api/routes/governance_reports.py:390-471,605-675`；`backend/tests/api/routes/test_governance_report_reads.py:195-215,310-394`）。
- 当前 Evidence 以四个专用可空 FK 表达 exact-one target，并以复合 FK 限制 tenant、Project、Run、report 和 target scope（`backend/app/domain/models.py:755-845`；`backend/tests/migrations/test_evidence_schema.py:216-303`）。
- 当前最终 Publish 在一个 PostgreSQL commit 中写 Finding 生命周期、报告 Artifact 元数据、Report、Evidence、PUBLISH/Run 终态、latest pointer 与审计；Snapshot、Observation、Resource 及其链接已由更早步骤固定（`backend/app/domain/governance_runs.py:2571-3062`）。
- 当前候选文件会在同文件系统临时写入、`fsync`、`os.replace`、设为只读，并在 Publish 前重开和校验 Hash；篡改测试证明无 Report/Artifact 元数据提交。Publish/数据库失败后候选文件留存是当前行为，尚无只在 non-retryable terminal failure 清理的完整合同（`backend/app/domain/governance_runs.py:2081-2215,2421-2451`；`backend/tests/api/routes/test_governance_runs.py:1079-1166`）。
- `COMPLETED_WITH_WARNINGS` 已在 schema 和已发布不可变门禁中存在，但 IP 当前读取兼容性只认 `COMPLETED`；report list/detail 只检查 `completed_at`，CSV route 则直接按 scoped Report + Artifact 读取，未校验 Run 成功终态或 `completed_at`（`backend/app/domain/ip_results.py:56-74`；`backend/app/domain/governance_reports.py:84-115,275-301`；`backend/app/api/routes/governance_reports.py:605-645`；`backend/tests/migrations/test_evidence_schema.py:306-381`）。
- 历史 Run 升级不会补造 report version、Report 或 Evidence（`backend/tests/migrations/test_evidence_schema.py:384-415`）。

## 决策

### 1. 分派与兼容

每个 Run 恰好按其不可变 `report_contract_version` 分派，且最多产生一份 Report：

| Run 状态 | report contract | 行为 |
| --- | --- | --- |
| legacy / unmodeled | 严格使用已存值或 `null` | 读取和 Retry 都不得回填、重算或从 Project 当前选择推断；`null` 继续表示无报告合同 |
| ADR-0011 report-selection cutover 前已建立的 `governance-run-input-v1` Run | 严格使用 Run 已固定值（可为 `null`） | Retry 只从原 Run stored facts 原样重建，不按新策略派生或回填 |
| cutover 后首次创建的新 v1 Trigger + explicit absent NetFlow | `deterministic-report-v1` | 原双来源 compiler/selector/renderer；canonical JSON、HTML、CSV 与 Evidence 字节必须零变化 |
| cutover 后首次创建的新 v1 Trigger + present NetFlow | `deterministic-report-v2` | 必须走 v2；零记录、坏质量或不可用不得降级为 v1 或伪装 absent |

report-selection cutover 只能在协调维护窗口执行。启用前必须停止或拒绝新 Trigger，确认每个 Project 的 launch reservation 三字段均为空，且不存在活跃 Runner 或 GovernanceRun；任何 agent-compose Session 状态未知都必须按 ADR-0004 fail closed。任一门禁失败即中止 cutover；历史已完成或失败的 Run 保持不变。
`governance-run-input-v1` 的精确 schema、canonical bytes、string/null 的 `runner.report_contract_version` 字段及样例 Hash 已由 ADR-0008 冻结，本 ADR 不修改或扩展它；其 explicit-absent 规范样例永久保留 `report_contract_version:null` 与 SHA-256 `0dc5f48d13f4bd65e1b9592a094792c967ef854002b6f78333f30ad2a307b229`。
本提议只决定 cutover 后首次创建的新 Trigger 如何选择既有 report 字段值；不得修改历史 Run，也不得让控制面响应丢失或相同 Trigger replay 套用新策略。未来 report selection policy 变化必须再次执行排空的 cutover，或先接受新的 input contract；不得让未完成 reservation 隐式跨越策略变化。v1/v2 继续复用现有 list、detail、CSV URL 和外层响应字段，不新增 `/v2` URL，HTML Artifact 不提供下载 URL。

### 2. reservation、固定与 Hash

本 ADR 继承 ADR-0008，不取代或改写它：R1 必须完整落实唯一 `governance-run-input-v1` typed builder、精确 schema 与 Hash，禁止新 input contract version。
仅在 cutover 后首次创建新 Trigger 时，API 在 Project 锁内读取 current tri-state，由该唯一 builder 机械派生 absent→report-v1、present→report-v2，构造完整 typed launch inputs 并计算 canonical Hash；API 只持久化既有 reservation 的 Trigger ID、agent-compose control Run identity 和输入 Hash 三字段，并把同一 typed inputs 发送给 agent-compose Runner launch。API/Trigger 不接收 version 或 Dataset override 参数。
comparison schema/algorithm 由 `deterministic-report-v2`、fact canonical key 中的 `ip-source-comparison/v1` 和固定 Runner build 共同约束，不新增或单独固定 `comparison_contract` 字段。
控制面响应丢失后的相同 Trigger replay 若命中 cutover 后 reservation，只能定位并返回既有 reservation/control identity/Hash。reservation 始终只有上述三个持久字段，不是 payload 或 report value 来源；Hash 不能恢复 payload/report，也不得以新的 current selection 重新派生。
Runner 必须使用 agent-compose launch 交付的 typed inputs 重建 canonical payload/Hash，并在 Project 锁内复验 reservation 已存的 Trigger/control identity/Hash 以及 current selection。launch inputs 不可用或任一身份、Hash、选择不匹配时均 fail closed 且不建 Run；验证成功创建 Run 时才原子保存完整固定 facts 并清除 reservation。
所有 cutover 后的新 v1 Run 都要求 reservation 存在；空 reservation 的 legacy direct-start bypass 只兼容历史 legacy/unmodeled。
R1 必须删除当前单独的 `GOVERNANCE_REPORT_CONTRACT_VERSION` 输入来源及未绑定该版本的旧 Hash 路径；不得并存两套构造、来源或优先级。
Retry 只从原 Run stored facts 原样重建同一个 v1 payload/Hash、pin 和 report value；只有 Rerun 以新 Trigger 读取新 current selection 并执行 cutover 后策略。

### 3. 唯一 report seam

一个显式、穷举的 dispatcher 只接受 `deterministic-report-v1` 或 `deterministic-report-v2`。
v1 分支原样调用现有 compiler、Evidence selector、renderer；v2 分支调用独立严格 schema、selector、renderer；未知版本 fail closed。
不建 registry、plugin、Capability 表、来源组合 DSL 或第二套调度器。

### 4. 稳定三来源比较事实与 Evidence

只为客户可见且现有 Finding 生命周期无法表达的三来源 IP 比较持久化窄类型 `IPSourceComparisonFact`；能由现有 Finding 表达的内容必须复用，不复制事实，不改 Finding 类型、去重或开闭规则。
Fact 受 tenant + Project + Run 复合 scope 约束；每个 canonical IP 在同一 Run 恰好一个，Canonical IP 遵守 ADR-0005。
其 canonical key 精确为 `ip-source-comparison/v1/<canonical-ip>`，ID 精确为以 Run ID 作 UUIDv5 namespace、canonical key 作 name 的 UUIDv5；比较结果不进入身份。
完整 typed content 的 canonical Hash/output Hash 只校验完整性；Retry 得到同一 ID，Rerun 因新 Run namespace 得到新 ID。
Evidence 增加专用 `ip_source_comparison_fact_id` FK/target，并继续由数据库强制 exact-one 与 report/tenant/Project/Run 复合 scope；禁止 generic type/string 多态 target。

### 5. NetFlow 质量语义

NetFlow 只凭 activity-valid 行提供正向 activity；每个受质量影响的比较维度只有 `EVALUATED`、`PARTIAL`、`UNAVAILABLE`。
`EVALUATED` 必须有合同允许的 typed value 且 `reason_code=null`；`PARTIAL`/`UNAVAILABLE` 必须有后续 Delivery Spec 冻结的稳定 reason code 且比较 `value=null`。
coverage=`UNKNOWN`，sampling rate、NAT 语义与 observation point 均为未知/null，除非未来另有可验证来源合同。
缺行、零行、invalid/quarantined 行或 null 字段不得推出 `NOT_OBSERVED`、零事件、零风险、无流量或完整覆盖。
只有命名为 `observed_valid_*` 的计数/估算可记录明确正向样本；它们不得填补 null 比较值或成为覆盖声明。
应当存在的 comparison fact 缺失是 compiler/persistence 错误，不得伪装为 `UNAVAILABLE`。

### 6. 原子 Publish 与公开可见性

SourceSnapshot、Observation、Resource、ObservationResourceLink 可由 Publish 前的可重入步骤固定，不在最终事务重复创建；Publish 前必须重验 scope、Hash、合同、必需 fact 集合和候选文件字节。
同一个 PostgreSQL Publish 事务必须包含：现有 Finding mutation，FindingOccurrence/FindingTransition 及其 Observation/Snapshot 链接，v2 comparison facts，GovernanceReport canonical JSONB，Evidence，HTML/CSV Artifact metadata，PUBLISH step success/output Hash，Run 成功终态/completed_at，Project `latest_completed_run_id`，以及 publish-success AuditEvent。
任一项失败则整笔回滚；PostgreSQL 仍是唯一权威结构化业务事实库。
R1 必须建立共享 `published report` predicate：Report 与 Run 的 tenant/Project/Run scope 匹配，Run 状态为 `COMPLETED` 或 `COMPLETED_WITH_WARNINGS`，且 `completed_at` 非空。
list、detail 和 CSV 必须复用该 predicate；CSV 在打开 Artifact 前 fail closed。符合门禁的历史已发布 v1 继续可读，当前结果只经 latest pointer 解析，任何更早步骤的未发布 facts 均不可公开读取。
现有单语句一致性读取性质必须保留（`backend/tests/api/routes/test_governance_report_reads.py:232-307`）。

### 7. Artifact 文件补偿

BUILD/VALIDATE 在 Artifact root 同一文件系统以临时写入并 `fsync`，原子 rename 为唯一、Run-owned、只读且客户路由不可达的 candidate files，随后固定 bytes/size/Hash；不创建第二份 final 文件，也不 copy。
PUBLISH 必须重开并校验 candidate bytes/size/Hash，再以同一 PostgreSQL 事务写 Artifact metadata 使其随 Report 可见。若数据库或审计发生明确瞬时、可 Retry 的 Publish 失败，回滚全部结构化事实但保留已经验证的 candidate，供同 Session 从 PUBLISH 重试，禁止删除或重建。
promotion/验证失败，或 Run 进入 non-retryable terminal failure 时，才对本次已知 candidate paths best-effort cleanup；补偿失败只发脱敏运维告警，始终不得存在 Artifact row 或客户可达路由。commit 成功但响应丢失时按持久化 Run/Report/Artifact facts 恢复，不删除文件、不重复发布。

### 8. 终态

- v2 所有比较维度完整可评估：`COMPLETED`。
- 可合法发布，但至少一个维度因 optional 质量为 `PARTIAL`/`UNAVAILABLE`：`COMPLETED_WITH_WARNINGS`。
- 任一已固定 mandatory source 缺失、完整性不可证明，或 present 的固定 Dataset 为零记录：`FAILED_DATA`，不发布。
- compiler/schema/contract/Hash、数据库或实现失败：`FAILED_PROCESSING`，不发布。

`COMPLETED` 与 `COMPLETED_WITH_WARNINGS` 都是不可 Retry、可读、可成为 latest 且受 late-mutation guard 保护的不可变成功终态；R1 必须一次更新所有 success-status、API/read compatibility、latest 和 late-mutation seams，不能只改 Publish。

### 9. 漂移、Retry、Rerun 与回滚

Run 建立前的 pin/选择漂移 fail closed 且不建 Run；建立后的 fixed source 漂移映射 `FAILED_DATA`。
Runner build、processing/report contract、report-v2 comparison schema/algorithm 漂移或 candidate Hash 不匹配是确定性 `FAILED_PROCESSING`，标记 non-retryable，只允许 Rerun；只有明确分类的瞬时 processing failure 可 Retry。
同 Session Retry 固定原 Run、Trigger、Session、全部 pin、版本、build 与 contracts，重验后复用已成功步骤，从首个失败或未开始步骤继续；任一 pin 漂移拒绝 Retry。ADR-0003/0004 的单活跃 Run 和 Session 终态门禁保持。
Rerun 使用新 Trigger、Run、Session，并读取新的 Project current selection；旧 Run 不变。
Publish 回滚后以独立事务记录 failed step/Run，绝无半发布 facts；可 Retry 的瞬时失败保留 candidate，non-retryable terminal failure 按第 7 节清理。已发布的 `COMPLETED`/`COMPLETED_WITH_WARNINGS` 永不回滚或改写。

### 10. v2 AI Draft

v2 默认在服务端 hard-disabled，且无 feature flag。一个共享 exact allowlist predicate 当前只允许 `deterministic-report-v1`。
detail 对 v2 返回 `can_request_ai_governance_draft=false`；POST 包括幂等 replay 必须在解析 Evidence、建立 draft 或启动模型 Session 前稳定失败为 `draft_report_contract_unsupported`。
ADR-0007 的 v1 边界不变。未来若另立并接受决策，模型仍只能读取有界持久 Evidence 和预计算字段，不读 raw/normalized Artifact，不计算权威统计，不修改 Finding 或事实。

### 11. 依赖、Delivery 冻结与 YAGNI

ADR-0009/0010 都仍是提议；它们及本 ADR 分别通过独立 Admission 前，不得启动依赖这些合同的 R1。
后续 Delivery Spec 必须在实现前冻结 v2 精确 JSON/HTML/CSV 字段与排序、typed value 与 reason-code 枚举、Evidence 上限、report-selection 协调维护窗口的停止/拒绝 Trigger、排空验证、失败中止与回滚操作，以及发布级 golden；这些交付细节不得改变本 ADR 已决定的分派、身份、质量、事务、终态和 AI 边界，本 ADR 本身不授权实现这些操作。
明确不做：新 input contract version、`comparison_contract` pin、v2 URL、HTML 下载、v1 schema/Hash/报告字节变化、通用 Lineage/比较 registry、plugin、Capability 表、规则 DSL、generic Evidence target、新 Finding 规则、新 Artifact 存储或第二份 final 文件、队列、实时流处理、多 Agent 报告或 v2 AI Draft。
