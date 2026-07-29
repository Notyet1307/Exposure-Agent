# ADR-0003：同一 Project 只允许一个执行中的 GovernanceRun

状态：已接受

Exposure-Agent v0.1 对同一 Project 同时只执行一个 GovernanceRun：相同触发标识恢复原 Run，不同触发标识在已有执行中 Run 时启动前拒绝且不创建业务 Run，不同 Project 仍可并行。失败 Run 停止执行后释放执行资格，但只有不存在更新 Run 时才能恢复；新 Run 创建后，旧 Run 永久保留为不可恢复的历史记录。该选择牺牲同一 Project 的并行吞吐，以避免 SourceSnapshot、Finding 生命周期和 `latest_completed_run_id` 的并发竞争；约束由 PostgreSQL 兜底，只有出现经过验证的同 Project 分区并行需求时才重新评估。
