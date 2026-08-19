# Exposure-Agent 稳定架构约束

这些约束长期有效；改变它们需要新的已接受 ADR。

- PostgreSQL 是唯一权威结构化业务事实库。
- agent-compose 只负责调度、隔离和 Session 生命周期，不承担业务事实。
- OctoBus 是客户系统与 CloudAtlas 的外部能力边界；应用不绕过它直接持有外部能力。
- Python、SQL 和 Polars 生成权威确定性事实。
- 报告或模型 Agent 只能读取有界 Evidence 并生成草稿，不计算权威统计、不创建或修改 Finding，也不获得数据库凭据、OctoBus Capset 或自由 Shell。该限制不描述执行确定性 Python 的 Governance Runner。
- 未经新 ADR，不引入 Redis、Celery、Kafka、Temporal、第二套调度器、通用规则 DSL 或默认多 Agent 路径。
- CustomerUpload 是客户系统不可达期间的过渡输入，不冒充 SourceInstance。
- 已发布 GovernanceRun 的来源事实、解析链接和 Finding 生命周期事实不可追加或重写。
- 认证、Project 授权、追加式审计、凭据隔离和数据防泄漏边界不得为简化实现而削弱。
- 任何外部写动作都必须先有明确审批、固定计划 Hash、有效授权和幂等键；当前仓库尚未实现该动作面。
