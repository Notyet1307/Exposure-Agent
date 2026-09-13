# 产品模型连接的部署与恢复准备

适用规范：ADR-0017 与固定 EXP-UX-02 Spec。此文是部署准备说明，不是已授权执行记录；合成验收不授予外部 Provider/客户材料出域许可。

## 显式启用配置

默认 `compose.yml` 保留原环境连接。产品内保存/验证/启用需要额外使用 `compose.model-connections.yml`，以及部署管理员提供的受保护目录：

- `MODEL_CONNECTION_KEY_HOST_DIRECTORY`：预先存在的绝对目录，位于 Git、Artifact 和 PostgreSQL/数据库备份目录之外。目录不可被 group/other 写入；建议 0700。
- `MODEL_CONNECTION_KEY_ID`：默认 `v1`；目录内的 `<key_id>.key` 必须是非符号链接普通文件、0600、恰好 32 个随机字节。不得复用 JWT/登录 Secret、覆盖现存 Key 或在日志中输出内容。
- 模板仅向 backend 只读挂载 `/run/model-keys`；缺少目录立即失败，不自动创建。Runner 与 agent-compose 不挂载主密钥。保留所有仍被历史 Secret 引用的 Key ID。
- `RUNNER_BUILD_VERSION` 保留现有 legacy 连接的 Runner 身份。可选 `MODEL_CONNECTION_RUNNER_BUILD_VERSION` 单独指定新版本连接所用的已构建 Runner；未设置时回退到前者。新版本和实际 Run 环境均固定这个身份，不能重标旧镜像或借用旧资格。
- `DOCKER_IMAGE_RUNNER` 下的两个标签必须按需保留。若 managed 标签不同，先在已批准的干净源码目录额外构建该镜像，再启用覆盖配置；默认 `governance-runner-image` 仍负责 legacy 标签，不会自动构建另一标签。已有任务依赖的镜像和版本项目不得删除。

```sh
docker build -f backend/Dockerfile.runner \
  --build-arg RUNNER_BUILD_VERSION="${MODEL_CONNECTION_RUNNER_BUILD_VERSION:?}" \
  -t "${DOCKER_IMAGE_RUNNER:?}:${MODEL_CONNECTION_RUNNER_BUILD_VERSION}" .
```

静态配置检查（不启动服务）：

```sh
docker compose -f compose.yml -f compose.model-connections.yml config --quiet
```

只记录成功/失败或必要的脱敏字段，不公开完整渲染配置。此检查只证明 Compose 配置可解析，不证明主密钥可解密、网络可达、模型能力或部署验收。

## 部署与首次接管检查

执行部署前先固定候选提交/镜像、必需 CI/审阅和部署授权，保留数据库与当前运行清单。按既有迁移流程新增表/字段，不回写旧记录的版本身份。

上线后按顺序验证：登录/权限；主密钥和 Secret 可解析性；管理员显式导入或保存；固定合成验证；确认旧 legacy 运行/Session 已终态；管理员显式启用；新任务固定新版本、旧任务保留原版本。未知旧会话以 `legacy_binding_unknown` 阻止首次切换，不能删除记录或假定已结束来绕过。

保存、验证、启用分开。刷新/原操作 GET 只读；结果未知时先按原操作 key 查询，再由管理员明确重试原意图，不生成替代 key 或重复版本。

## 备份与恢复

数据库备份含认证密文与不透明引用；主密钥必须独立保管、独立恢复，不能与数据库备份合包。恢复前核对所有被引用 Key ID 及文件权限，再逐个确认 Secret 可解析；缺失/错误时保持 fail closed，不导入替代凭据，不切到其他版本或 legacy 环境。

已有失败记录保持失败。恢复正确密钥后，新执行可以重新验证；不把配置读回或旧结果改成新的 PASS。撤销仅阻断后续调用，不能收回已经发出的数据。

## 回退边界

接管后的数据库保存了版本化任务事实。不要直接换回旧镜像并依靠全局环境连接继续接新任务；这可能绕过已固定版本和撤销状态。出现回归时先停止新增 AI 工作，保留数据库/Key/原镜像与任务现场，制定明确恢复方案。不要删除共享迁移、降级抹除密文、重建任务或改写原失败。

独立核查、分析报告与旧 governance draft 的执行合同分别验收。旧 draft 的占位会话不是模型生成结果，不得将原生会话成功显示为模型能力通过。
