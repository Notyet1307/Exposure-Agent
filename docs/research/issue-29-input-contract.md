# Issue #29：CustomerUpload 与云图 OctoBus 读取契约调查

状态：完成调查，建议 **GO** 进入后续初期产品实现 Spec；现有 demo 不可原样复用，最终客户系统接入仍为 **NO-GO**。

## 1. 结论与边界

- 初期输入必须保持两条不同的信任边界：客户侧是 `CustomerUpload`，云图侧是 `SourceInstance`。不得把上传文件伪装成 OctoBus Instance。
- 云图读取底层仍使用 `chaitin-cli`。已验证链路为：公共 OctoBus Connect HTTP → Runtime → Instance → 单方法只读 Capset → `cloudatlas-read` Service → `chaitin-cli asset ip list` → CloudAtlas HTTP GET。
- 可复用 demo 的流式接收、SHA-256 和确定性解析思路；不可复用其“只检查 Excel 容器便接受”的成功语义。
- 本次只新增调查报告、脱敏探针和最小调查 Service Package。Exposure-Agent 的表、迁移、API、UI、生产拉取和 Run 实现均未修改。
- 本次没有连接真实客户系统、真实客户文件或真实 CloudAtlas；CloudAtlas 成功与失败证据来自确定性本地上游 fixture。

## 2. 可复现证据

### 2.1 基线

| 对象 | 已验证修订 |
| --- | --- |
| Exposure-Agent | `f71122a`（调查开始时的 `origin/main`） |
| 现有 demo | `ae55c9ac218827e43e364d0e3db6409693c7ae23` |
| OctoBus 镜像 | `sha256:d1527668a4b961e33e653b1db510d411d951c050641e7d7244886a65de486760` |
| OctoBus Runtime npm 包 | `@chaitin-ai/octobus@0.1.0` |
| 对应 OctoBus 源码快照 | `45e25a2606b583ad997e8948850edbf429e9d776` |
| chaitin-cli | Dockerfile 固定 `v2606.0.4`；二进制 SHA-256 `b91fcfa9e9d3d324bab694333f4dcbead779291cae5a1d7590156046baa09954` |
| 调查 Service | `cloudatlas-read`，声明版本 `0.1.0`，`@chaitin-ai/octobus-sdk@0.5.0` |
| 调查 Service 内容 | Package SHA-256 `49b96cc6ed7e1dfd3464c83553fa86898584706276ee2e97f99195a6ee86e5ec`；Descriptor SHA-256 `3fada7cb00f3bca132c28d316ea61158522a1a07d3e80a83f9e68010d1a588e0` |

OctoBus 导入结果的 `PackageVersion` 为空，因此后续不能只依赖显示版本；至少固定 Package 与 Descriptor 的内容 Hash。

### 2.2 运行命令

前置条件：本机存在 demo 仓库、`cloudatlas-octobus:local` 和 `cloudatlas-reconcile-agent-compose-guest:local` 镜像。

```bash
python3 investigations/issue_29/probe.py
```

探针会：

1. 在内存生成仅含 TEST-NET 地址的 `.xlsx`，启动 demo 的最高层认证上传 HTTP 入口，并调用 demo 的确定性 parser；
2. 启动使用全新临时数据目录的 OctoBus 容器，导入调查 Service、创建 Instance 和单方法 Capset，再从公共 Connect HTTP 调用；
3. 验证成功、失败分类、只读 OpenAPI surface 与指纹变化，最后删除临时容器和临时文件。

它不会修改当前运行中的 demo OctoBus 数据，也不会调用 rescan、plan apply 或其他 Action。

## 3. CustomerUpload 证据与候选契约

### 3.1 已观察行为

脱敏 fixture 经 `/api/customer-files` 得到 HTTP 201，响应 SHA-256 与上传字节完全一致；保存后的文件又通过现有 `compare_customer_report.py` parser（exit 0）。上传与 parser/Run 是分开的动作。

已观察到以下行为：

| 场景 | demo 结果 | 是否可作为产品契约 |
| --- | --- | --- |
| 结构真实 `.xlsx` | 201、流式保存、SHA 正确、parser 成功 | 是，需加结构校验 |
| `.csv` | 415，无接受产物 | 是 |
| 伪造 `.xlsx` | 415，临时文件删除 | 分类需调整为结构/内容错误 |
| 大于 20 MiB | 413，无接受产物 | 是 |
| 缺少必需列 | **201、parser exit 0、文件被保留** | 否，直接复用 NO-GO |
| 同 Project 重复相同内容 | **生成第二份产物** | 否，直接复用 NO-GO |

现有 demo 还接受 `.xls`，但当前 parser 镜像没有验证对应读取依赖；它把清洗后的原始文件名写入存储路径，并且只做浅层 OOXML 容器检查。这些行为都不进入产品契约。

为验证目标失败行为，调查探针在同一个 demo Handler seam 上仅覆写结构判断：缺少必需列时返回 415，父流程删除临时文件，最终接受目录为空。该 gate 只证明“校验后再发布”可复用现有流式路径；产品 API 仍应按下表改用稳定的 422 类别。

### 3.2 候选接受契约

- 仅支持 `.xlsx`；HTTP 请求体上限为 `20 MiB`（20,971,520 bytes），必须按实际读取字节计数，不能只信任 `Content-Length`。
- 工作簿必须可被确定性 parser 打开，且只有一个可见 worksheet；第 1 行是非空、唯一表头，至少有一条数据行。
- 必需列：`资产IP`、`起始端口`、`结束端口`、`是否web界面`、`web界面url`。URL 单元格仅在 Web 标识为“是”时必须有值。
- `资产IP`、端口范围、Web 标识和条件 URL 是拒绝级校验；负责人、部门、服务类型等所有权信息缺失只形成 soft warning，不能把有效报备整体拒绝。
- 接受前完成格式、归档资源上限、结构和拒绝级字段校验；任何失败都删除临时文件，不创建可选择的 CustomerUpload。
- SHA-256 对上传的原始字节计算。不可变身份是 Project 范围内的 CustomerUpload ID + 完整内容 Hash；相同 `(project_id, sha256)` 幂等返回既有版本，不再写第二份 artifact。
- 文件系统或对象存储 key 只使用服务端生成的 UUID/Hash。原始文件名最多作为受保护的显示元数据保存，先校验为 basename、限制长度并移除控制字符；不得进入路径、日志或错误文本。
- 上传成功只表示“可被后续选择”，绝不自动调用 CloudAtlas 或启动 GovernanceRun。
- `.xlsx` 是 ZIP 容器；后续实现除 20 MiB 请求上限外，还必须限制条目数量、单条目和总解压量，避免压缩炸弹。具体解压阈值应在产品实现 Spec 中随 parser 内存基准固定，本调查不伪造未经测量的数值。

### 3.3 脱敏失败契约

| HTTP | 稳定类别 | 语义 |
| --- | --- | --- |
| 400 | `invalid_filename` / `incomplete_upload` | 非 basename、控制字符、长度非法或流提前结束 |
| 401 | `upload_authentication_failed` | 未认证 |
| 403 | `upload_authorization_failed` | 无 Project 上传权限 |
| 413 | `upload_too_large` / `workbook_resource_limit` | 请求体或安全解压界限超出 |
| 415 | `unsupported_workbook_type` | 非 `.xlsx` |
| 422 | `malformed_workbook` / `missing_required_structure` / `invalid_required_value` | 工作簿、结构或拒绝级字段无效 |
| 500 | `upload_storage_failed` | 脱敏的存储错误 |

响应只返回类别和可公开说明；不得返回原始文件名、单元格内容、客户地址、解析库异常、临时路径或 token。

## 4. CloudAtlas SourceInstance 读取契约

### 4.1 精确调用面

| 项目 | 契约 |
| --- | --- |
| Service Package | `cloudatlas-read`，按 Package/Descriptor SHA 固定 |
| Service | `cloudatlas.read.v1.CloudAtlasReadService` |
| 方法 | `ListIPAssets` |
| 完整方法名 | `cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets` |
| Instance Config | `baseUrl`（URI）、`spaceId`（非空） |
| Instance Secret | `token`（只保存在 OctoBus） |
| Capset | enabled；绑定唯一 Instance；`include_all_methods=false`；只选择上述方法；需要 Capset token |
| 底层 CLI | `chaitin-cli cloudAtlas asset ip list` |
| 上游请求 | `GET /openapi/v1/asset/ip`，仅分页与状态过滤 |

公共调用形状：

```http
POST /capsets/cloudatlas-readonly/connect/cloudatlas-fixture/cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets
Authorization: Bearer <capset-token>
Content-Type: application/json

{"status":"valid","page":1,"size":1}
```

脱敏响应形状：

```json
{
  "items": [{"id": "fixture-asset-1", "ip": "192.0.2.10", "status": "valid"}],
  "page": 1,
  "size": 1,
  "total": 1
}
```

探针读取了 Capset 的 OpenAPI，路径集合严格只有上述一个 Connect 方法。上游 fixture 记录到的方法为 GET；没有 Action Service、全方法授权、扫描或计划执行。

`chaitin-cli` 从权限为 `0600` 的运行时临时配置读取 Instance secret，调用后在 `finally` 中删除；token 不进入 argv、探针输出或报告。生产实现仍应保持 Service 进程与普通业务进程隔离，且不得启用 `--verbose-sensitive`。

### 4.2 安全失败契约

| 边界 | HTTP / gRPC 类别 | 稳定消息 |
| --- | --- | --- |
| Capset token 缺失或错误 | 401 | OctoBus 自身认证错误 |
| CloudAtlas 认证拒绝 | 401 / `unauthenticated` | `cloudatlas_authentication_failed` |
| CloudAtlas 授权拒绝 | 403 / `permission_denied` | `cloudatlas_authorization_failed` |
| DNS、连接、超时、EOF | 503 / `unavailable` | `cloudatlas_connectivity_failed` |
| 其他上游失败 | 503 / `unavailable` | `cloudatlas_upstream_failed` |
| 成功 HTTP 但响应不符合契约 | 500 / `data_loss` | `cloudatlas_response_contract_failed` |

错误不得包含 URL query、header、token、CLI stderr 原文或返回记录。

### 4.3 连接指纹

规范名称：`exposure-agent.cloudatlas-source-fingerprint.v1`。

对以下 JSON material 递归按 key 排序、数组按稳定业务 key 排序，使用紧凑 UTF-8 JSON 后计算 SHA-256：

- Service：ID、Package SHA-256、PackageVersion、Descriptor SHA-256；
- Instance：ID、Service ID、ConfigSHA256、SecretSHA256；
- Capset：ID、enabled、Instance bindings（含 `include_all_methods`）、已选择方法、Capset token binding 的 ID 与 TokenHash；
- 完整 selected method 名。

只把最终 fingerprint 存入 Exposure-Agent；不复制原始 Instance secret、Capset token 或完整管理面 material。探针证明：material 不变时 fingerprint 稳定；Instance 绑定、config、credential、Capset 授权或 selected-method contract 任一变化都会改变 fingerprint。

验证不设置时间 TTL。fingerprint 变化立即失效；material 未变时保持已验证，直到后续真实读取失败，失败后必须把连接视为无效并重新验证。

## 5. GovernanceRun 固定关系

初期创建 Run 前必须同时满足：

1. Operator 选定一个属于当前 Project、已通过当前验证契约的不可变 CustomerUpload；
2. 当前 Project 恰有一个启用的 CloudAtlas SourceInstance，其当前 fingerprint 已由上述只读方法成功验证。

创建 GovernanceRun 时固定：CustomerUpload ID + 内容 SHA-256、CloudAtlas SourceInstance ID + 已验证 fingerprint，以及实际 Runner 镜像摘要/构建版本。Retry 必须复用这些值；选择另一份上传、改变 Instance/credential/Capset/method 或改变 Runner 版本时，不得恢复旧 Run，只能显式创建新 Run。上传本身不创建 Run。

客户系统可达后，新生产 Run 的客户侧输入必须改为正式客户 SourceInstance，并通过相同的 OctoBus Instance + 只读 Capset + 最小读取验证；历史 CustomerUpload 和历史 Run 保持不变。

## 6. Go / No-Go

### GO：后续初期产品实现 Spec

可以基于本报告编写 CustomerUpload、CloudAtlas SourceInstance 控制面和 GovernanceRun readiness/pinning 的后续 Spec。两个最高层 seam、最小读取方法、失败类别和指纹 material 都已有运行证据。

### NO-GO：以下事项尚不可宣称完成

- 不得把现有 demo 上传端点原样移植；缺列仍被接受、重复内容重复落盘、原始文件名进入路径等问题必须先修正。
- 不得把本地 fixture 当作真实 CloudAtlas 授权、网络和数据契约验收；生产拉取前仍需在授权环境做只读 canary，并固定真实 Service Package revision。
- 不得把 CustomerUpload 当作最终客户系统接入。客户 API 文档、认证、分页、限流、错误契约及客户 SourceInstance 的真实只读验证仍被客户系统可达性阻塞。
- 不得新增 Action Capset、rescan、通用 Connector、第二凭据库、调度器或时间健康检查循环。

## 7. Acceptance Criteria 对照

| AC | 结果 | 证据/结论 |
| --- | --- | --- |
| 1 | 满足 | 第 3 节定义候选格式、大小、结构、Hash、文件名、去重和错误契约 |
| 2 | 满足 | 探针走 demo 认证上传 + 真实 parser；仅使用内存生成脱敏 fixture |
| 3 | 满足；直接复用仍 NO-GO | unsupported/oversized/malformed 无接受产物；调查结构 gate 拒绝 missing structure 且无残留，同时保留 demo 错误接受的对照证据 |
| 4 | 满足 | 第 4.1 节固定 Package、Service、method、Instance 与单方法 Capset |
| 5 | 满足 | 临时 Runtime + Instance + Capset + 公共 Connect + 确定性 upstream fixture 成功 |
| 6 | 满足 | OpenAPI 仅一个读取路径；实际 CLI 为 GET list；未导入 Action |
| 7 | 满足 | 探针断言稳定性与五类变更失效 |
| 8 | 满足 | 第 3.3、4.2 节及探针失败注入 |
| 9 | 满足 | 第 5 节定义 readiness、pinning 与 Retry |
| 10 | 满足 | 第 6 节分别给出初期 GO 与生产/最终集成 NO-GO |
| 11 | 满足 | 第 5、6 节保留客户系统经 OctoBus 的硬门槛 |
| 12 | 满足 | 仅调查资产；产品模型、迁移、API、UI 和生产拉取未改 |

## 8. 泄露检查

- fixture 只含 `192.0.2.10`、测试 ID 和测试 token；不读取或提交真实客户 workbook。
- 上游日志只记录 method/path/query 及 token 是否存在/匹配，不记录 token 值。
- 探针输出只含状态、错误类别和非秘密 Hash；不会打印 Instance SecretSHA、Capset TokenHash 或 CLI 原始 stderr。
- 临时上传目录、parser 工作区、OctoBus 数据目录和容器均在运行结束后删除；仓库中不生成上传 artifact。
