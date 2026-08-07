# ADR-0003：同一 Project 只允许一个执行中的 GovernanceRun

状态：已接受

Exposure-Agent v0.1 对同一 Project 同时只执行一个 GovernanceRun：相同触发标识恢复原 Run，不同触发标识在已有执行中 Run 时启动前拒绝且不创建业务 Run，不同 Project 仍可并行。失败 Run 停止执行后不允许普通的不同触发标识创建新一轮；任何新一轮都必须由 Operator 显式执行 `Run Rerun`，使用新的 Trigger ID、新 GovernanceRun 和新 Session。原失败 Run 只有在不存在更新 Run、原 Session 可恢复且固定输入未变化时才能 Retry；新 Run 创建后，旧 Run 永久保留为不可恢复的历史记录。该失败 Run 的 Rerun-only 规则由 #39 确认，用于覆盖本 ADR 原先关于失败后释放普通新 Run 资格的表述。

该选择牺牲同一 Project 的并行吞吐，以避免 SourceSnapshot、Finding 生命周期和 `latest_completed_run_id` 的并发竞争；约束由 PostgreSQL 兜底，只有出现经过验证的同 Project 分区并行需求时才重新评估。
