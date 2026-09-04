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
客户系统不可达期间用于初期测试的客户侧输入文件版本，只有通过确定性校验后才成立，具有不可变 ID 与内容 Hash、归属于一个 Project，并固定校验时使用的 CustomerUploadProfile 版本；GovernanceRun 明确固定其中一个版本。它是过渡输入，不冒充 SourceInstance，也不改变客户系统最终经 OctoBus 接入的目标。
_Avoid_: 上传尝试、校验失败文件、客户系统、SourceInstance、可变附件路径、最终集成方式

**CustomerUploadProfile**:
归属于一个 Project 的不可变、版本化表格结构契约，定义后续 CustomerUpload 的列名映射、别名、必填或可选，以及缺失时的拒绝或 warning 分类；每个 Project 独立维护版本链，每个 CustomerUpload 固定校验时使用的版本。IP、端口、Web 标识、URL 等值语义及核心字段不可降级约束仍由确定性代码定义。
_Avoid_: 跨 Project 共享 Profile、通用规则 DSL、可视化规则编辑器、历史上传重解释、值校验脚本

**NetFlowDataset**:
归属于一个 Project、通过确定性校验后成立的不可变 NetFlow 输入版本，具有不可变 ID、内容 Hash 和校验时使用的合同版本。Project 可以选择其中一个作为当前可选输入，也可以明确不选择；GovernanceRun 固定选择结果，存在但记录数为零的 Dataset 仍不同于未提供 NetFlow。
_Avoid_: 可变流量库、实时采集流、缺失输入、SourceSnapshot、零记录即 absent

**GovernanceRun**:
在一个 Project 内由 Runner 实际开始执行的一次有边界的对账周期，固定客户侧输入、暴露面 SourceInstance、已验证连接配置版本、可选 NetFlow 输入的 absent 或 present 状态、输入合同与输入 Hash，以及实际参与计算的 Runner 版本；present 时同时固定 NetFlowDataset 的身份、内容 Hash 和合同版本。初期测试的客户侧输入是一个 CustomerUpload 内容 Hash；客户系统可达后的最终输入是客户 SourceInstance。同一 Project 可以持续产生多轮 GovernanceRun，但同一时间最多执行一轮；尚未启动 Runner 的触发请求不是 GovernanceRun。规范化、字段映射或 Policy 功能引入后，其实际版本也随 Run 固定。历史上尚未建模可选 NetFlow 的 Run 是 unmodeled，不等于明确 absent。
_Avoid_: Project、长期资产范围、排队中的触发请求

**SourceSnapshot**:
GovernanceRun 对一个实际参与的输入来源读取结果形成的不可变批次记录，固定来源版本、原始 Artifact 引用、内容 Hash、Schema 或连接指纹及记录数。明确 absent 的 NetFlow 不产生 SourceSnapshot；present 的 NetFlowDataset 即使记录数为零仍产生 NETFLOW SourceSnapshot。它不保存后续规范化的 Observation，也不是统一资产 Resource。
_Avoid_: CustomerUpload、SourceInstance、Observation、Resource、可变行表

**Observation**:
从 SourceSnapshot 中一条来源记录确定性形成的不可变、带来源结构化事实；重复来源记录仍形成不同 Observation，多条 Observation 可以解析到同一个 Resource。
_Avoid_: SourceSnapshot、去重后资产、跨来源合并结果、Resource

**Resource**:
Project 内跨 GovernanceRun 稳定存在的规范技术资产身份；相同资源类型与 Canonical Key 始终表示同一个 Resource，每轮及每个来源的具体事实仍由 Observation 和解析关系表达。即使后续两侧均未观测到也不删除，当前出现状态由最新完整 Run 的 Observation 表达。
_Avoid_: Observation、单轮资产副本、来源当前值汇总

**ObservationResourceLink**:
特定处理契约将一条 Observation 解析到一个 Resource 的不可变关系；当前 IP 精确解析中每条 Observation 恰有一个链接，不表示模糊候选或人工确认。
_Avoid_: Observation 上的可变 Resource 字段、候选匹配、确认记录

**Canonical IP**:
IP Resource 使用的确定性地址身份；标准 IPv4-mapped IPv6 与其承载的 IPv4 表示同一地址，除此以外 IPv4 与 IPv6 保持各自的规范地址语义。
_Avoid_: 原始 IP 文本、主机名、CIDR、任意 IPv6 到 IPv4 折叠

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
对一个未成功完成的 GovernanceRun 再次执行，沿用同一 Run、触发标识和 agent-compose Session，并在 RunStep 中增加尝试；它不创建新的治理周期，也不从 Project 当前选择替换原 Run 固定的可选 NetFlow 输入。只有失败被分类为可恢复、Project 中不存在更新 Run、原 Session 可恢复，且该 Run 固定的客户侧输入、暴露面来源绑定、已验证连接配置、可选 NetFlow 选择与实际参与计算的版本均未变化时才可 Retry；确定性来源或处理合同错误必须修复后 Rerun，更新 Run 一旦创建，旧 Run 永久成为历史记录。
_Avoid_: Rerun、新 GovernanceRun

**Run Rerun**:
明确发起一个新的治理周期，使用新的触发标识并创建新的 GovernanceRun 和 agent-compose Session，即使它与旧 Run 来自同一 Project；新 Run 读取 Rerun 发起时的 Project 当前可选 NetFlow 选择，不继承旧 Run 的选择。
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
跨 GovernanceRun 持续存在的治理问题；同一差异复现时沿用原 Finding、增加 FindingOccurrence，并在原 Finding 已关闭时重新打开。后续完整成功的 GovernanceRun 只有在两边正向匹配到同一资产时，才可自动关闭该 Finding；当前状态保存在 Finding，变化历史由 FindingTransition 保留，数据源失败、单纯未再次发现或两边都未观测到都不能自动关闭。
_Avoid_: 单次 Run 差异记录、缺失即关闭

**FindingOccurrence**:
某个 Finding 在一次完整 GovernanceRun 中被确定性发现的不可变记录，关联出现侧的 Observation 和两侧 SourceSnapshot；它不表示 Finding 已关闭。
_Avoid_: 新 Finding、关闭记录、AuditEvent

**FindingTransition**:
完整 GovernanceRun 对 Finding 执行 `OPENED`、`CLOSED` 或 `REOPENED` 的不可变生命周期事实，关联作出该判断的来源事实；它不是操作者行为审计。
_Avoid_: FindingOccurrence、AuditEvent、可变状态日志

**Evidence**:
某个用户可见治理结论对特定 GovernanceRun 中来源事实和确定性判断依据的结构化引用；用于追溯结论，不复制原始 Artifact，也不记录操作者行为。
_Avoid_: 原始数据副本、AuditEvent、独立证据平台

**AI Governance Draft**:
Project Operator 针对一份已发布 GovernanceReport 明确选择 `1–8` 个未观测资产及其 canonical Evidence 后发起的一次独立、不可重试的非权威模型草稿；报告 Hash、选择绑定、模型配置和 Session 在生成前固定，原始模型输出不可变。生成失败或单次 Operator 的 `ACCEPTED | EDITED | REJECTED` 审核均为终态；`EDITED` 只另存 Operator 文字，不改变 GovernanceReport、GovernanceRun、Finding 或 Evidence 事实。
_Avoid_: 权威报告、GovernanceRun、可变模型结果、自动 Retry、Finding 修改

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
