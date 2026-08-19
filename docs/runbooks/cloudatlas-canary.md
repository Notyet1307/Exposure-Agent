# CloudAtlas 只读部署 canary

本 Runbook 验证当前交付包在获授权真实 CloudAtlas 环境中的最小只读链路。它不验证生产发布、写动作、长期监控或未来资源类型。

## 前置条件

- 使用已审阅的源码 revision 和当前交付镜像；
- 获得限时、可撤销、仅用于 canary 的 CloudAtlas 凭据；
- 使用独立 worktree、`COMPOSE_PROJECT_NAME`、Artifact 目录、端口和 canary Project；
- 原始 IP、响应、凭据和未脱敏证据只保存在仓库外受控位置；
- Capset 设置 `include_all_methods=false`，且只允许 `cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets`。

## 执行

1. 从 `.env.example` 创建本地 `.env`，为本次 canary 生成独立随机密钥，并设置临时 `ARTIFACT_HOST_PATH`。
2. 启动隔离 Compose stack，确认 `/health/live`、`/health/ready` 和登录页可用。
3. 登录为 canary Admin，创建专用 Project，并上传只含 TEST-NET 数据的最小 CustomerUpload。
4. 在 OctoBus 中创建专用 CloudAtlas Instance 和最小只读 Capset；不要复用生产写权限或长期 token。
5. 在 Project 的 CloudAtlas 页面绑定 Instance，执行读取验证，并确认 Package、Descriptor、Instance、Capset 和方法指纹均通过。
6. 启用 SourceInstance，以新的 Idempotency-Key 触发一个 GovernanceRun。
7. 等待 Run 进入完成状态，确认必需步骤全部成功、两侧 SourceSnapshot 完整，Assets / Findings 的分页和有界来源追溯可读。
8. 只记录脱敏计数、Hash、稳定状态和失败类别；不得复制真实资产值、原始响应、token 或本地 Evidence 路径到仓库、聊天、Issue 或截图。

## 停止条件

出现以下任一情况立即停止，不把 fixture 或部分结果表述为验收通过：

- Package、Descriptor、Capset、方法或 token material 指纹不一致；
- Capset 暴露额外方法或任何写能力；
- Run 创建前配置失败、Run 失败或来源分页不完整；
- 真实数据、凭据或未脱敏 Artifact 进入普通日志或仓库；
- 当前镜像、driver 或运行边界与待交付对象不一致。

## 清理与记录

1. 禁用 canary SourceInstance，撤销临时 token，删除临时 Instance / Capset material。
2. 停止并删除本次隔离 Compose project 及其临时卷，删除临时 Artifact 目录。
3. 在仓库外保存最小脱敏验收记录：源码 revision、镜像 digest、Package / Descriptor Hash、方法、Run 最终状态、步骤状态、计数、清理确认和未验证项。
4. 任一交付镜像、Package、Descriptor、driver 或只读方法变化后重新执行；历史 canary 不能自动覆盖新对象。
