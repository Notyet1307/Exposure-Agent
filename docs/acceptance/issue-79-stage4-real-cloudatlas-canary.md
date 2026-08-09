# Issue #79 验收记录：真实 CloudAtlas Stage 4 隔离 canary

状态：2026-08-09 `PASS`；验收 revision 为 `80d8b2ccdd07ef8264330ffcad92b08081bc5a3b`。原始真实数据与凭据未签入仓库。

## 隔离边界与固定契约

- 使用独立 worktree、Compose project、PostgreSQL database、volume 和端口；输入为一条受控 CustomerUpload。
- OctoBus Capset 设置 `include_all_methods=false`，只允许 `cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets`；实际操作为只读有效 IP Asset 列表读取。
- 固定指纹：
  - Package SHA-256：`1d487b2773d0dc2457d5c552d5a5d9cd34b4e7c732f9a810cf0115cdab3f069c`
  - Descriptor SHA-256：`3fada7cb00f3bca132c28d316ea61158522a1a07d3e80a83f9e68010d1a588e0`
  - CloudAtlas validated fingerprint：`a48abc558c4b2fc40cb020a323a286252a8767c230befc7730f9ae769030738c`
  - CloudAtlas method fingerprint：`6d842a6d6087efe320686c79c9b22ef4d7216303cb988bae6f9beb0c5667699f`
  - Runner build：`stage4-canary-80d8b2c`
  - Processing contract：`ip-v1`

## Run 与计数结果

- 唯一业务 GovernanceRun 状态为 `COMPLETED`。
- `LOAD_CUSTOMER → PULL_CLOUDATLAS → NORMALIZE → RESOLVE → CHECK_FINDINGS → PUBLISH` 六步均为 attempt 1、`SUCCEEDED`。

| 事实 | 计数 |
| --- | ---: |
| SourceSnapshot | 2（CloudAtlas 13,182；CustomerUpload 1） |
| Observation / Observation-Resource link / Resource | 各 13,183 |
| API Assets | 13,183 |
| Finding / OPEN / CLOSED | 13,183 / 13,183 / 0 |
| Occurrence / OPENED Transition | 各 13,183 |
| Occurrence / Transition Snapshot refs | 各 26,366 |

两份 Snapshot 的 13,183 条记录与 Observation、Resource 和 Assets 计数一致；每个 Occurrence 与 OPENED Transition 各保留两份已确认 Snapshot 引用。记录不含 IP、Asset ID、Snapshot ID、Observation 或 Finding 实值。

## UI、来源追溯与泄漏检查

- Assets 在隔离 UI 中完成下一页与返回；详情中的 Observation 有界，Snapshot 引用可见。
- Findings 保持 `OPEN` 完成下一页与返回；详情中的 Occurrence、`OPENED` Transition、Observation 和两份 Snapshot 引用均可读且有界。
- 真实 IP 只在隔离 UI 中查看，未复制到聊天、截图、Issue 或本记录。
- 最终 redaction scan 为 `PASS`：仓库与验收记录未包含真实 IP、原始响应、Observation/Finding 实值、凭据或无界 artifact。

## 执行偏差、凭据与清理

- 首次 Source 预验证因本地剪贴板内容被覆盖而返回 `401 / octobus_authentication_failed`；重新输入临时只读 Capset token 后验证成功。
- 首次启动控制请求因一次性 canary 的 agent-compose project name 与产品默认值不一致而出现 `StartRun 400`、Trigger API `503`；该请求未创建业务 GovernanceRun。修正隔离配置后复用原 Trigger reservation，最终只产生上述一个业务 Run，未重复读取来源。
- 两项偏差均发生在业务 Run 创建前，属于人工输入或一次性隔离配置问题；未发现需要在 #79 内修复的产品代码缺陷，也未修改已审计 revision。
- 未跳过验收步骤。CloudAtlas Source 已禁用，上游 token 已撤销，临时 OctoBus Instance/Capset/material 已移除，canary 栈已停止；隔离数据库中的 durable Run facts 保留。
- 脱敏证据 `evidence-stage4-20260809T053302Z.json` 保留在仓库外；`validate-final` 退出码为 0。

## 未验证项

本 canary 不代表生产发布；未验证新增方法、长期监控、压力测试、报告或处置能力。
