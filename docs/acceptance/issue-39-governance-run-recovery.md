# Issue #39 验收记录：GovernanceRun 失败关闭与恢复

状态：2026-08-05 本地验收通过；未执行真实 CloudAtlas canary。

## 已验证主链路与失败路径

- 确定性完整链路：`LOAD_CUSTOMER → PULL_CLOUDATLAS → PUBLISH` 生成两份不可变 SourceSnapshot，并在同一事务中完成 Run 与 `latest_completed_run_id`。
- 数据失败：CustomerUpload 读取及 CloudAtlas 边界/响应失败收敛为 `FAILED_DATA`，停止后续步骤并保留已成功快照。
- 处理失败：Artifact/SourceSnapshot 持久化及 PUBLISH/audit 事务失败收敛为 `FAILED_PROCESSING`；发布回滚不留下完成状态或最新指针。
- Retry：可靠确认原 Session 为 `stopped` 后，复用同一 GovernanceRun、Trigger ID、Session ID、固定输入和成功快照；失败步骤 attempt 增加。PUBLISH Retry 不重新读取来源。
- Rerun：输入变化或原 Session 已确认不可恢复时，只允许新 Trigger ID、新 Run 与新 Session；旧 Run 不修改且出现更新 Run 后不可 Retry。
- Fail-closed：`running`、控制面不可达、缺失或未识别 Session 状态不释放 Project 单 Run 资格；PostgreSQL launch reservation 与活动 Run 唯一约束覆盖初次触发、Retry、Rerun 和并发请求。
- 权限与审计：仅 Operator/Admin 可发起恢复；拒绝、终态收敛、attempt、Retry/Rerun 记录脱敏 AuditEvent，并与业务状态原子提交。
- Web：展示稳定失败类别、attempt、快照复用数和阻塞原因；仅显示服务端判定合法的 Retry/Rerun，不提供强制解锁。

## 门槛与验证命令

- #33：固定 XLSX 解析器与资源边界由既有调查和本轮完整后端测试继续覆盖。
- #34：`python3 investigations/issue_34/probe.py` 对固定 agent-compose v2607.10.0 真实控制面通过，确认 `stopped` 终态、outage=`unknown`、同 Session ID Resume、重复 Resume 幂等及缺失 Session 稳定拒绝。
- `cd backend && uv run ruff check . && uv run mypy .`：通过。
- `cd backend && uv run bash scripts/tests-start.sh`：248 passed，覆盖率 89%。
- `cd frontend && bun run lint && bun run build`：通过。
- `cd frontend && bunx playwright test tests/dashboard.component.spec.ts --workers=1 --retries=0`：13 passed。
- `bash scripts/test-governance-run.sh`：真实 PostgreSQL + agent-compose + 临时 OctoBus/CloudAtlas fixture + Playwright Compose smoke 通过，最终两份 SourceSnapshot 均为 1 条记录。

## 未验证项

未连接或调用真实 CloudAtlas 环境，因此真实认证、授权、网络和生产响应契约仍未完成 canary 验收；本轮对应结论仅来自确定性 fixture。未实现自动无限重试、TTL/心跳解锁、通用补偿框架、第二调度器、Observation、Finding、报告、处置或最终客户系统接入。
