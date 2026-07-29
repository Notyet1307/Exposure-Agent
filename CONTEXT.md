# Exposure-Agent

本文件记录 Exposure-Agent 已确认的领域词汇，不替代实现规格或 ADR。

## Language

**Project**:
一个长期、可重复运行的资产一致性治理范围，绑定客户自有系统、暴露面系统及其资产范围，保存成员、策略和多轮对账历史；目标是持续维护跨系统资产事实的一致性。同一客户可以有多个 Project；当资产范围需要独立的成员授权、策略或一致性历史时才拆分 Project，而不是按对账或扫描次数拆分。全局 Admin 是该授权边界的显式例外。以不可变内部 ID 作为事实锚点，名称可修改。
_Avoid_: 租户、工作区、单次对账、Run 分组

**SourceInstance**:
Project 对一个外部系统 OctoBus Instance 的业务引用，标明其为客户系统来源或暴露面来源，并记录启用状态及当前连接配置是否通过读取验证；凭据仍由 OctoBus 管理。同一 Project 每类外部来源最多启用一个 SourceInstance，可以保留已停用的历史引用；验证在绑定或连接配置变化后失效，配置不变时不按时间自动过期。初期测试只有云图 SourceInstance；客户系统可达后最终也通过 SourceInstance 接入。
_Avoid_: Connector、凭据副本、SourceSnapshot、CustomerUpload

**CustomerUpload**:
客户系统不可达期间用于初期测试的客户侧输入文件版本，由授权用户上传并经过确定性校验，以不可变内容 Hash 标识并归属于一个 Project；GovernanceRun 明确固定其中一个版本。它是过渡输入，不冒充 SourceInstance，也不改变客户系统最终经 OctoBus 接入的目标。
_Avoid_: 客户系统、SourceInstance、可变附件路径、最终集成方式

**GovernanceRun**:
在一个 Project 内由 Runner 实际开始执行的一次有边界的对账周期，固定客户侧输入、暴露面 SourceInstance、已验证连接配置版本和实际参与计算的 Runner 版本，并记录本轮各数据源的快照、观察结果和差异。初期测试的客户侧输入是一个 CustomerUpload 内容 Hash；客户系统可达后的最终输入是客户 SourceInstance。同一 Project 可以持续产生多轮 GovernanceRun，但同一时间最多执行一轮；尚未启动 Runner 的触发请求不是 GovernanceRun。规范化、字段映射或 Policy 功能引入后，其实际版本也随 Run 固定。
_Avoid_: Project、长期资产范围、排队中的触发请求

**GovernanceRun Status**:
v0.1 只使用 `RUNNING`、`FAILED_DATA`、`FAILED_PROCESSING`、`COMPLETED` 和 `COMPLETED_WITH_WARNINGS`。失败状态表示执行已停止且可能 Retry；完成状态不可变。
_Avoid_: PENDING、QUEUED、RETRYING、CANCELLED、PAUSED、SUPERSEDED

**RunStep**:
GovernanceRun 中一个确定性处理步骤的持久化执行状态，在步骤第一次真正开始时才创建，并在 Retry 时沿用同一记录增加尝试。v0.1 只使用 `RUNNING`、`SUCCEEDED` 和 `FAILED`；没有记录表示尚未开始。
_Avoid_: 预创建的 PENDING 步骤、独立 agent-compose Session

**Run Publish**:
GovernanceRun 的最终原子动作，同时写入完成状态并更新 Project 的最新完整 Run 指针；只有 Publish 成功后，Run 才算完成并对默认客户视图可见。
_Avoid_: COMPLETE RunStep、部分发布

**Run Retry**:
对一个未成功完成的 GovernanceRun 再次执行，沿用同一 Run、触发标识和 agent-compose Session，并在 RunStep 中增加尝试；它不创建新的治理周期。只有 Project 中不存在更新 Run、原 Session 可恢复，且该 Run 固定的客户侧输入、暴露面来源绑定、已验证连接配置与实际参与计算的版本均未变化时才可 Retry；更新 Run 一旦创建，旧 Run 永久成为历史记录。
_Avoid_: Rerun、新 GovernanceRun

**Run Rerun**:
明确发起一个新的治理周期，使用新的触发标识并创建新的 GovernanceRun 和 agent-compose Session，即使它与旧 Run 来自同一 Project。
_Avoid_: Retry、恢复旧 Run

**Trigger ID**:
一次治理触发在同一 Project 内唯一且稳定的幂等标识；相同值只能定位原 GovernanceRun，Rerun 必须使用新值。定时触发沿用 agent-compose 的计划执行标识，手动或 API 触发沿用调用方提供的 `Idempotency-Key`。
_Avoid_: trigger_key、GovernanceRun ID、Session ID

**未报备资产**:
暴露面系统已经观测到、但客户自有系统没有对应记录的资产类 Finding；后续处置方向是向客户系统补充资产记录。
_Avoid_: 自动写回结果

**未观测资产**:
客户自有系统存在记录、但暴露面系统在本轮没有对应观测的资产类 Finding；不等于资产不存在，后续处置方向是补充扫描目标并重新扫描。
_Avoid_: 不存在的资产、自动写回结果

**Finding**:
跨 GovernanceRun 持续存在的治理问题；同一差异复现时沿用原 Finding 并增加 FindingOccurrence。后续完整成功的 GovernanceRun 只有在两边正向匹配到同一资产时，才可作为复测证据自动关闭该 Finding；数据源失败、单纯未再次发现或两边都未观测到都不能自动关闭。
_Avoid_: 单次 Run 差异记录、缺失即关闭

**FindingOccurrence**:
某个 Finding 在一次 GovernanceRun 中再次出现的记录。
_Avoid_: 新 Finding

**Evidence**:
某个用户可见治理结论对特定 GovernanceRun 中来源事实和确定性判断依据的结构化引用；用于追溯结论，不复制原始 Artifact，也不记录操作者行为。
_Avoid_: 原始数据副本、AuditEvent、独立证据平台

**Archived Project**:
不再接受新的项目内操作或授权变更、但保留数据源绑定、策略、成员关系、治理事实和审计记录的 Project；有执行中 GovernanceRun 时不能归档，可由 Admin 在 Run 停止后归档或重新启用，且两个动作都必须审计。重新启用不改变既有 Run；此前确认的 Retry 条件仍全部成立时，最新失败 Run 可以恢复。Project 不被硬删除。
_Avoid_: 已删除 Project

**ProjectMembership**:
用户与 Project 的唯一成员关系，承载一个或多个可独立授予的项目角色；被撤销后立即失去该项目授权但保留历史，重新授予时必须显式设置角色；全局 Admin 不是成员关系。
_Avoid_: 单一角色绑定、Admin Membership

**Project Role**:
Viewer、Operator 与 Approver 是可组合的项目职责。三者都有项目基础读取能力；Operator 与 Approver 的操作权限彼此独立。
_Avoid_: 角色等级、单一角色绑定

**Admin**:
不属于任何 ProjectMembership 的全局身份，自动拥有所有 Project 的项目角色与管理权限；仍受“不能审批自己创建的 Plan”、审计和审计快照脱敏约束。
_Avoid_: Admin Membership、仅管理面 Admin

**Inactive User**:
被 Admin 停用的用户，不能认证或获得项目授权；其 ProjectMembership 保留，Admin 仍可授予、改角色、撤销或重新授予，但这些权限只在重新启用账号后生效。
_Avoid_: 已删除用户、已移除成员

**AuditEvent**:
对受治理操作的追加式业务审计记录，包含行为人、目标、发生时间和项目范围或全局范围；不是服务运行日志。原始审计流只对 Admin 开放，且只能由服务端随受治理变更原子追加。
_Avoid_: 应用日志、系统 Project 事件

**Audit Snapshot**:
AuditEvent 中可解释且已脱敏的变更前后业务表示；不包含凭据、密码或密码哈希、Token、完整 Artifact / Evidence 原文等敏感内容。
_Avoid_: 原始数据副本、凭据日志
