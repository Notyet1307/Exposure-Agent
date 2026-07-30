# Issue #34：agent-compose Session 终态与恢复契约调查

状态：完成调查，建议 **GO（仅限已验证的 agent-compose v2607.10.0 Docker 控制面契约）** 进入 GovernanceRun 设计；本调查不创建 `GovernanceRun`、`RunStep`、`SourceSnapshot`、业务 API 或数据库状态。

## 1. 固定对象与范围

探针固定下列 Linux arm64 OCI manifest，而非 `latest`：

| 对象 | 固定引用 | 构建版本 / revision |
| --- | --- | --- |
| 控制面 | `ghcr.io/chaitin/agent-compose@sha256:838452756fe1f71b0f4239c02068700c3f15c8cf8ffade1a09ba08837669f89e` | `v2607.10.0` / `e14c4dbd5e3b0dec6178073902d67d2765390427` |
| 确定性最小 Guest | `ghcr.io/chaitin/agent-compose-guest@sha256:99a031b38be9e6afc5b7ce5161a4c5ee6f93c9990f3b39a3fbd8c9b29044ee32` | 同一 source revision；guest runtime `0.7.0` |

Guest 只执行三个固定 shell command：`printf issue34-success`、`exit 17`、`sleep 8; printf issue34-caller-loss`。它不调用模型、不读取客户数据、不使用凭据；控制面、Guest、项目配置和 Docker data root 都创建于一次性临时目录，探针结束时删除。

这不是对 agent-compose 任意未来版本、其它 runtime driver、分布式/HA 部署或 Exposure-Agent 生产恢复流程的验收。后续改用不同 digest、架构、driver 或控制面版本时，必须重新运行本调查，而不能把本结论外推到浮动 `latest`。

## 2. 可复现入口与最小自动检查

前提：可用 Docker daemon，并已允许拉取上述两个公开镜像。探针通过实际控制面创建 Project、提交 detached command Run、查询和恢复 Sandbox；不模拟 Session 生命周期。

```bash
python3 investigations/issue_34/probe.py
python3 -m unittest discover -s investigations/issue_34 -p test_probe.py -v
```

`--output <path>` 可把与 stdout 相同的脱敏 JSON 写到调用方指定位置。输出只保留 image/revision、随机但稳定的本次 `session_id`、状态、exit code 和 resume return code；不会输出临时路径、Docker container ID、Guest transcript、完整 command output、凭据或 token。自动检查同时锁定镜像 digest、fail-closed 映射、outage 必须使 authoritative query 非零，以及 Resume JSON 的成功、`resumed` 状态与同 ID 响应。

本次固定对象的实际脱敏证据已提交为 [`investigations/issue_34/evidence/probe-v2607.10.0.json`](../../investigations/issue_34/evidence/probe-v2607.10.0.json)（SHA-256：`ce1f00771e79166c79c8ba3e4cc01fb3ee8e4844b918c7bb1405b4a86de35457`）。它记录每个场景的匿名本次 Session ID、查询状态、outage query 的非零 exit code，以及首次、重复和失败 Guest 终态 Resume 的返回 ID；不含临时运行目录、凭据或 Guest 输出。

## 3. 实测控制面入口与字段语义

探针使用：

```text
agent-compose ps --all --json
agent-compose inspect run <run-id> --json
agent-compose resume <sandbox-id> --json
```

`ps` 的 `sandboxes[].sandbox_id` 是本调查记录并在 Resume 中重用的稳定 Session/Sandbox ID，`sandboxes[].status` 是运行时生命周期状态。成功完成和 `exit 17` 的 Guest 都经成功的控制面查询报告为 `status: "stopped"`；因此 `stopped` 可证明 runtime Session 已终止，但不能单独表达 Guest 业务结果。

`inspect run` 补充 Run 结果：成功样例为 `status: "succeeded", exit_code: 0`，失败样例为 `status: "failed", exit_code: 17`。这两个 Run 字段用于诊断 Guest command 的结果；后续 Exposure-Agent 仍须以 PostgreSQL 中的业务事实为准，不能将 agent-compose Run 记录当作 `GovernanceRun` 事实源。

本次探针每次运行产生新 ID；报告会记录同一个 ID 在 `guest_success` 与 `resume` 前后相同，因而既可复核稳定性，又不把上一台机器的临时 Session 伪装成可恢复生产对象。

## 4. 已验证场景与结果

| 场景 | 实测控制面事实 | 允许的 Exposure-Agent 结论 |
| --- | --- | --- |
| Guest 成功 | `ps --all` 返回相同 Session ID，`stopped`；`inspect run` 为 `succeeded/0` | 已确认 Session 终态；可按原 ID 尝试 Resume |
| Guest 失败 | `ps --all` 返回相同 Session ID，`stopped`；`inspect run` 为 `failed/17` | 已确认 Session 终态；可按原 ID 尝试 Resume，业务 Run 是否可 Retry 仍由 PostgreSQL 前置条件决定 |
| 调用方失联 | detached CLI 返回后，长命令 Session 仍由 `ps --all` 返回为 `running` | 不释放同 Project 单 Run 资格；不能据 CLI 已退出或经过时间判断终止 |
| 控制面短暂不可达 | 停止控制面后，独立 client 的 `status --json` 必须非零，否则探针失败；没有成功的 `ps` 查询 | 状态是 `unknown`，不以 Docker 本地进程、TTL、心跳或上次状态推断终止 |
| 控制面重启 | 用同一 `/data` 重启同一 pinned image 后，原 caller-loss ID 仍可查询并为 `running` | 仍执行，继续持有资格；没有第二个 Session |
| Resume 已终态 ID | 成功及 Guest-failure 两个 `stopped` ID 的第一次 Resume 都返回 0 和 `results[0].status: "resumed"`，并解析 `results[0].sandbox_id` 与原 ID 比较 | Resume 的前置状态在本次固定版本中是 `stopped`；恢复的是原 Session ID |
| 重复 Resume | 对已恢复 ID 再次调用返回 0、`resumed` 和同一 response ID，Session 数没有增加 | 本版本观测为幂等，不创建替代 Session |
| 不可恢复 ID | 删除已停止 Session 后 Resume 返回 CLI exit code 2 | 不可恢复时稳定非零拒绝；调用方必须保留旧 Run 为历史并要求显式 Rerun，而非替换它的 Session |

探针的完整 JSON 还断言：控制面不可达时没有提交 replacement Session（`replacement_session_started: false`），并记录 outage 前的 Session 数。这个断言是后续调用方必须遵守的 fail-closed 调用纪律，不是本票偷偷实现的业务锁或第二套调度器。

## 5. 后续实现可直接采用的最小映射和顺序

该映射满足 ADR-0004，且不添加 TTL：

| 成功控制面查询结果 | Session 分类 | 对 Project 单 Run 资格 | 后续调用 |
| --- | --- | --- | --- |
| `sandboxes[].status == "stopped"` 或 `"failed"` | `terminal` | 可以按事务性业务规则收敛旧 Run | 仅 `ResumeSession(session_id)`；不得创建替代 Session |
| `sandboxes[].status == "running"` | `running` | 保留 | 不 Resume，不启动第二个 Session |
| 请求失败、响应缺失、或未识别状态 | `unknown` | 保留 | 不 Resume，不启动第二个 Session，不用 TTL 推断 |

建议调用顺序：

1. Runner/恢复协调器先用关联的 `session_id` 执行成功的 `ps --all --json`（或等价的单 Session authoritative query）；
2. 仅当查询把该 ID 明确分类为 terminal，才在 PostgreSQL 事务中把遗留 `RUNNING` 的业务 Run 收敛为 `FAILED_PROCESSING`，并在其它 ADR-0003 Retry 前置条件仍成立时调用 `ResumeSession`；
3. Resume 必须带原 ID，并再次验证返回/后续查询的 ID 未变化；
4. 对 `running` 或 `unknown` 直接 fail-closed，保留单 Run 资格并向 Operator 报告控制面/终态未知；
5. Resume 非零、Session 已被删除或不可恢复时，Retry 失败。只有 Operator 显式发起新的 `Run Rerun` 才可创建新 `GovernanceRun` 与新 Session。

控制面 `stopped` 只解决“runtime 已终态”的门槛，并不授权业务完成、发布或自动 Retry；`GovernanceRun.status`、固定输入/版本条件和同 Project 排他性仍必须由 PostgreSQL 实现。这正是架构基线“agent-compose Session 不是业务事实源”的边界。

## 6. 未验证项与保留风险

- 本票没有验证 webhook/notification 的 delivery、顺序、持久化或断线补偿；后续实现使用已验证 query，不把通知当作唯一终态证据。
- 探针只覆盖 Docker driver、单 daemon 和临时本地 `/data`；没有验证多个 daemon 共享状态、网络分区、控制面数据损坏、容器运行时永久丢失或生产认证/TLS。
- `resume` 对已运行 Session 在本版本返回 0 的具体行为不构成允许调用方对 `running` 调用 Resume 的许可；ADR-0004 的安全调用方仍只在已确认 terminal 时调用。
- Guest command 成功/失败的 control-plane Run 结果不等于 Exposure-Agent 业务 `GovernanceRun` 成功/失败。没有实现 PostgreSQL 收敛、Retry、Rerun、锁、API 或 UI。

因此没有需要重开 ADR-0004 的最小阻塞事实：所固定版本提供了可查询的持久 Session ID、可观察的 `stopped` 终态、控制面重启后的重新查询，以及同 ID Resume/重复 Resume/不存在 ID 拒绝行为。任何上述固定前提发生变化，或产品需要通知替代查询、HA 终态保证时，必须基于新证据重开相关 ADR，而不能引入 heartbeat TTL 绕过。
