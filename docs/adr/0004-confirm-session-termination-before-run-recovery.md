# ADR-0004：确认 Session 终止后才能恢复遗留 GovernanceRun

状态：已接受

Runner 失联或经过一段时间本身不能释放 Project 的单 Run 执行资格；只有可靠确认关联的 agent-compose Session 已进入终态，才能把仍处于执行中的 GovernanceRun 收敛为 `FAILED_PROCESSING` 并允许通过 `ResumeSession` 恢复同一个 `session_id`。原 Session 无法恢复时必须显式创建新的 Run 和 Session，不为旧 Run 静默替换 Session。该选择以故障期间的可用性换取不并发运行两个 Runner 的安全边界；在 agent-compose 终态查询或通知契约得到验证前必须 fail-closed，不引入任意心跳 TTL 来猜测 Session 已死亡。
