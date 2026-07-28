# Exposure-Agent

本文件记录 Exposure-Agent 已确认的领域词汇，不替代实现规格或 ADR。

## Language

**Project**:
一个长期、可重复运行的资产一致性治理范围，绑定客户自有系统、暴露面系统及其资产范围，保存成员、策略和多轮对账历史；目标是持续维护跨系统资产事实的一致性。同一客户可以有多个 Project；当资产范围需要独立的成员授权、策略或一致性历史时才拆分 Project，而不是按对账或扫描次数拆分。全局 Admin 是该授权边界的显式例外。以不可变内部 ID 作为事实锚点，名称可修改。
_Avoid_: 租户、工作区、单次对账、Run 分组

**GovernanceRun**:
在一个 Project 内执行的一次有边界的对账周期，记录本轮各数据源的快照、观察结果和差异；同一 Project 可以持续产生多轮 GovernanceRun。Project 可以在尚未配置数据源时创建，但启动 GovernanceRun 前必须至少绑定一个启用且连接有效的客户系统来源，以及一个启用且连接有效的暴露面来源。
_Avoid_: Project、长期资产范围

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

**Archived Project**:
不再接受新的项目内操作或授权变更、但保留数据源绑定、策略、成员关系、治理事实和审计记录的 Project；可由 Admin 重新启用，归档与重新启用都必须审计。Project 不被硬删除。
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
被 Admin 停用的用户，不能认证或获得项目授权；其 ProjectMembership 保留，并在重新启用账号时恢复原有权限。
_Avoid_: 已删除用户、已移除成员

**AuditEvent**:
对受治理操作的追加式业务审计记录，包含行为人、目标、发生时间和项目范围或全局范围；不是服务运行日志。原始审计流只对 Admin 开放，且只能由服务端随受治理变更原子追加。
_Avoid_: 应用日志、系统 Project 事件

**Audit Snapshot**:
AuditEvent 中可解释且已脱敏的变更前后业务表示；不包含凭据、密码或密码哈希、Token、完整 Artifact / Evidence 原文等敏感内容。
_Avoid_: 原始数据副本、凭据日志
