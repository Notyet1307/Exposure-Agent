# ADR-0007：允许 AI 治理草稿受限调用客户部署内模型

状态：已接受

范围依据：`REL-003/r1`、父 Delivery Spec #140 与实现 Issue #144 已确认的模型生成边界。本 ADR 只为 `ai-governance-draft` 的单次草稿生成建立窄范围部署例外；它不独立扩大产品范围，不构成通用 OctoBus 绕过、Provider DSL、第二套模型调度器或外部写能力。

## 决策

OctoBus 继续作为客户业务系统、资产系统与 CloudAtlas 的外部能力边界。在当前 Release 内，agent-compose 启动的专用 Pi `ai-governance-draft` Session 可以经部署本地、无重定向的受限代理，直连客户控制环境内、地址固定的 OpenAI-compatible 推理端点。仅允许 loopback、RFC1918 私网和 IPv6 ULA 地址；link-local（包括云 metadata 地址）、公网地址、重定向目标和客户环境外 Provider 均不受信任。

该 Session 只执行一次模型请求。Provider 自动 retry、替代模型、替代 Provider、Codex/OpenAI 或其他外部 fallback 必须关闭；超时、连接错误、空文本、结构无效、资格漂移或引用越界均直接进入失败终态。端点 Host 与解析地址必须固定，TLS SNI 与原始 Host 必须保持一致，响应大小必须有界。

## 数据与能力隔离

Python Supervisor 可以使用 PostgreSQL 凭据重新加载已持久化的草稿输入并保存终态，但模型子进程不得获得数据库凭据、应用 Secret、OctoBus Capset、Artifact 文件系统、自由 Shell、工具、技能、扩展、上下文文件或外部写能力。模型子进程只获得本地代理地址、当前模型身份和单次调用所需的模型 API Secret；Secret 不进入 Prompt、PostgreSQL、agent-compose Run 输出、日志或 AuditEvent。

发送给模型的业务输入只能来自已经固定并重新验证的草稿记录，且仅包含：

- 已发布确定性报告的 Hash 与生成草稿必需的预计算报告字段；
- Operator 明确选择的一至八个 `UNOBSERVED_ASSET` 的 Finding ID、类型、规范化 IP、coverage 与 transition；
- 与上述 Finding 一一绑定、位于 canonical Evidence plan 中的持久化 Evidence ID、fact type 与 fact ID；
- 固定的结构化输出契约和非权威性说明。

不得发送原始 Artifact、上传文件内容、SourceSnapshot/Observation 原始记录、数据库连接信息、Provider 原始事件或未选择 Finding 的事实。模型不得计算或替换权威统计，不得创建、更新或关闭 Finding，不得触发扫描、GovernanceRun、Retry、Rerun 或客户系统写回。

## 准入与终态

调用前必须重新计算当前端点、模型、非 Secret 配置、Runner build、资格契约和 agent-compose runtime 的绑定，并确认存在仍有效的客户内部模型资格结果。任一绑定漂移必须在向 Provider 发送业务数据前 fail closed。

模型输出必须通过服务端的严格 Schema、报告 Hash、完整 Finding 集合和 Evidence allowlist 校验。成功时只保存一次不可变的可审核模型草稿；失败时只保存稳定、脱敏的失败码。生成成功或失败都必须追加脱敏 AuditEvent，不得记录完整 Prompt、完整模型输出、原始 Evidence、Secret 或 Provider 原始错误内容。

确定性报告、GovernanceRun、Finding、FindingOccurrence 与 FindingTransition 在所有成功和失败路径中保持不变并继续可读。

## 非目标

本 ADR 不授权产品内模型目录、模型选择 UI、资格审批 UI、通用模型网关、模型对客户系统的访问、任何外部写动作、自动重试、多 Agent 生成、跨客户模型调用或后续 Release 的其他 AI 用例。扩大这些边界必须由新的已接受 Spec 与 ADR 明确批准。
