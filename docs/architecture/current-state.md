# Exposure-Agent 当前实现

本文件只描述当前代码、测试、迁移、Dockerfile 和 `compose.yml` 可证明的行为。细节以这些可执行事实为准。

## 部署与组件

当前交付面是单客户、单实例的 Docker Compose 应用：

- `frontend`：Nginx 提供 React 静态页面，并将同源 `/api` 代理到 FastAPI；
- `backend`：FastAPI API、确定性治理逻辑和 Artifact 访问；
- `db`：PostgreSQL 权威业务事实库；
- `octobus`：CloudAtlas 外部能力边界；
- `agent-compose`：Governance Runner 的调度、隔离和 Session 生命周期；
- `prestart`、`octobus-package-init`、`agent-compose-project-init`：一次性初始化；
- `governance-runner-image`：供 agent-compose 启动临时 Runner 的构建目标。

持久状态包括 `app-db-data`、`octobus-data`、`agent-compose-data` 三个命名卷，以及 `${ARTIFACT_HOST_PATH}` 指向的主机 Artifact 目录。备份恢复边界见 [deployment.md](../../deployment.md)。

## 已实现业务面

- User、全局 Admin、Project、ProjectMembership 与项目角色；
- Project 归档/恢复及受治理操作的追加式 AuditEvent；
- Project 专属默认 CustomerUploadProfile v1；
- 受控 `.xlsx` CustomerUpload、不可变内容 Hash、warning 汇总、选择与受限删除；
- `NetFlowDataset` 接受与管理：Operator 可在 Project 内列表、上传、选择或清除当前 Dataset，Viewer 只读；新 GovernanceRun 在 Trigger reservation 中用 `governance-run-input-v1` 固定可选 Dataset ID、raw/content Hash、Dataset 合同版本和报告合同，并将它们纳入输入 Hash。选择规则是 explicit absent 固定 `deterministic-report-v1`、present 固定 `deterministic-report-v2`；Runner 建立前的选择漂移 fail-closed，已建立 Run 的固定输入不可变，Retry 复用原 pin（包括历史 present/v1），Rerun 读取当前选择。present 在复核 raw Artifact 字节、Hash 与固定合同后产生唯一不可变 `NETFLOW` SourceSnapshot，保存 Dataset、raw Artifact、schema、raw record count 与可证时间极值；零条 raw record 仍产生 `record_count = 0` Snapshot。输入漂移或合同失效进入 `FAILED_DATA` 且不发布部分事实；explicit absent 不创建 NetFlow RunStep、Snapshot、比较事实或比较 Evidence。
- NetFlow 正向 IP 活动以 `netflow-ip-activity-v1` 按 Run / 已有受管 Resource 唯一聚合，在原子 Publish 中有界批写到 PostgreSQL；只关联同 Project 的既有 Resource（包括本 Run 双来源 RESOLVE 结果），不由 Peer 创建 Resource。`flow_count` 统计涉及该 IP 的有效源记录（保留重复；双端受管各计一次，自环计一次），并固定排序的 Peer / protocol、独立时间极值和内容 Hash；这些样本不表示会话数、完整覆盖或零活动。来源端口仍保留在不可变 Artifact，不推断服务端口或方向，不改变 Finding 生命周期。present/v2 用这些活动生成三来源比较；零 raw record 或零正向活动仍可完整发布，并以 `UNKNOWN` / `no_positive_activity_evidence` 表达限制。发布失败回滚活动、比较和报告事实，Retry 使用同 Run 身份重算。
- CloudAtlas SourceInstance 的配置、只读验证、指纹固定、启用和停用；
- 正式 `cloudatlas-read` OctoBus Package，仅允许 `cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets`；
- GovernanceRun 的 Trigger、Retry、Rerun、RunStep、SourceSnapshot 与 Publish；
- agent-compose Session 创建、终态查询、同 Session 恢复和未知状态 fail-closed；
- 客户内部 OpenAI-compatible 模型经 Pi 使用固定非客户 fixture 执行部署资格检查，PostgreSQL 仅保存脱敏门禁指标和当前配置绑定；
- Operator 可从已发布 `deterministic-report-v1` 报告显式选择一至八个有持久 Evidence 的“未观测资产”并创建 `GENERATING` AI 治理草稿；`deterministic-report-v2` 在详情与请求入口均明确禁用。Controller 先持久保留确定性的 agent-compose Run identity，再启动独立 Pi Session；本阶段 Session 只建立并绑定身份，不接收数据库、应用、模型凭据或草稿输入；
- CustomerUpload 与 CloudAtlas 的 IP Observation、Project 级稳定 IP Resource 和精确解析；
- “未报备资产”“未观测资产”两类 Finding、Occurrence、Transition 与来源引用；
- Finding 详情 API 与 Web 在同一只读数据库快照内展示最新兼容已发布 Run 的 NetFlow 活动上下文：仍 OPEN 或本轮有 Occurrence/Transition 的 Finding 可引用同 Run/Resource 的真实活动，早已 CLOSED 且本轮无事件的 Finding 不关联后续活动。此读取独立于报告样本，仅公开采样流记录数、可空时间及 Run/Snapshot/活动身份和 Hash，不公开 Peer、协议或 raw 数据，不新增绑定表或报告 Evidence target。历史未建模、明确无输入、历史未建模活动合同与合法无正向活动分别说明；活动及完整发布凭据损坏不降格为空结果。
- `deterministic-report-v1`：explicit absent Run 的 canonical JSON、HTML、CSV、Hash 和既有治理 Evidence；历史已发布内容保持不可变。
- `deterministic-report-v2`：present Run 基于三份固定 SourceSnapshot 生成 canonical JSON、HTML 与完整比较 CSV；同一 Publish 事务先持久化 Artifact metadata、报告、完整且不可变的 `IPSourceComparisonFact` 和比较 Evidence，再写其余治理事实、成功终态、latest 指针与 Audit，提交前通过既有发布 reader 重新核对报告字节 Hash、完整比较事实、引用和发布凭据。治理与比较各最多 50 条 Evidence、HTML 各展示 8 条，完整比较 JSON/CSV 不截断；详情最多返回 100 条有界引用，新 Evidence target 不进入 AI allowlist。报告 list/detail/CSV、latest Assets/Findings 和相关 Evidence 读取统一要求 `COMPLETED` 或 `COMPLETED_WITH_WARNINGS` 且 `completed_at` 非空；v2 读取还 fail-closed 校验完整比较发布。报告 Web 显示报告版本、三份输入完整性和准确的 AI 禁用说明，不提供 Lineage UI，也不新增比较 Evidence 详情接口。
- 已发布且兼容的显式 GovernanceRun 提供只读 `/governance-runs/{run_id}/sources` 来源概览和 `/governance-runs/{run_id}/ip-source-comparisons` 分页比较 API；两者先执行 Project read authorization，再按 tenant、Project、Run 和 published report scope 校验，复用既有比较 reader 与 v2 发布校验，不读 Artifact 文件、不使用 latest 替换显式 Run，也不产生写副作用。v2 发布校验可以读取不可变 Finding 事实验证 Report 完整性，但 API 不暴露或修改 Finding。来源概览固定返回 CustomerUpload、CloudAtlas、NetFlow 三个 slot，optional NetFlow 的 explicit absent 与 present（含零记录/零活动）保持可区分；损坏或不完整发布 fail closed。比较 API 只返回有界比较字段，筛选先于稳定的 canonical IP 排序和分页。
- Web 从已完成 Run 卡片进入 `/projects/{project_id}/runs/{run_id}/comparison`，在显式历史 Run 下展示三来源卡片与分页 IP 比较矩阵；URL 保留 classification、netflow_status 和页码，刷新及前进后退保持选择，不把历史 Run 替换为 latest。来源与矩阵响应的 Project、Run、Report 和报告版本必须一致后才展示事实；ABSENT、PRESENT（含零 raw record）、UNKNOWN 与请求错误分开表达，UNKNOWN 不表示不存在、零流量或零风险。页面提供加载、错误重试、空结果、窄屏单列卡片及键盘可滚动矩阵；既有 Assets/Findings latest 页面保持不变。
- 显式、兼容的已发布 Run 提供 `/governance-runs/{run_id}/lineage` 有界只读投影；在同一个 PostgreSQL REPEATABLE READ、read-only 快照中完成认证、Project 授权与事实读取。六类展示节点为 Source、Snapshot、Process 合同摘要、Comparison、该 Run 的 Finding 事件和 Report，八类边区分输入与报告上下文而非伪造因果。默认各展示最多 20 个比较与 Finding，可按 `resource_id` 读取单资产；每组依据引用最多 20 项，完整计数与截断显式分离。v1 按持久报告格式验证身份、来源与摘要，v2 复用完整发布校验；损坏事件或引用不能因未被展示而绕过校验。历史 Finding 不读取可变当前状态；查询不访问 Artifact 文件、外部系统或写数据库，不新增图存储、ETag 或缓存。Lineage UI 仍未实现。

确定性事实由 Python、SQL 和 PostgreSQL 约束生成。agent-compose 的运行结果不等于 GovernanceRun 完成；业务状态始终以 PostgreSQL 为准。

## 当前安全与失败边界

- CustomerUpload 先执行有界 ZIP/OOXML 预检，再使用固定 parser 只读解析；公式、主动内容、异常 worksheet 和资源越界均拒绝。
- XLSX 的 ZIP 阈值是输入防护，不是部署 CPU、内存或超时预算；后者仍需按交付硬件验证。
- NetFlow 上传只接受严格 `UTF-8-SIG` 或 `GB18030`，拒绝批级结构错误；未知额外列仅汇总 warning，行级无效值被确定性隔离或置空，拒绝与处理失败不建立 Dataset、Artifact 或 accepted AuditEvent；
- CloudAtlas Package、Descriptor、Instance、Capset、方法或 token material 漂移时验证失败。
- agent-compose Session 只有权威查询确认终态后才允许恢复；未知、不可达或未识别状态保持 fail-closed。
- 模型资格只允许 Pi 经无重定向本地代理连接解析到私网地址的部署注入端点，禁用模型工具和自动 retry；Secret、完整 Prompt、模型原始输出和 Provider 原始事件不进入 PostgreSQL 或 agent-compose Run 输出；端点、模型、非 Secret 配置、Runner build、资格契约或 agent-compose runtime 指纹漂移立即失效。
- 当前 AI 草稿 Session 的 direct command 是无副作用的占位命令，不接收数据库、应用、模型凭据或草稿输入，也不发出产品模型请求；API 可按已保留的 Run identity 幂等补齐同一 Session 绑定，控制面响应丢失或 Session identity 尚不可见时保留 `GENERATING` 状态供同一 Idempotency-Key 重放，前端在 Session 绑定前仅把该键和有界的已选 Finding ID 保留在当前浏览器标签页的 `sessionStorage` 中用于重载恢复，不保留原始 Evidence 内容，已确认的终态启动失败则收敛为脱敏 `FAILED`。
- 更换 agent-compose 镜像 digest、架构或 driver 后，旧 probe 结论不能外推，必须重新验证当前运行时契约。
- 真实 CloudAtlas 只读 canary 仍是部署门禁，步骤见 [Runbook](../runbooks/cloudatlas-canary.md)。

## 明确未实现

- AI 报告草稿的模型生成、Session 到确定性 Runner handoff 的生产接线、结构化输出校验与人工审核 Agent（当前仅实现请求、持久草稿、独立 Session 和独立的 Runner 输入重载契约）；
- PDF 报告；
- URL、域名、Endpoint、Application 或责任主体治理；
- 客户系统正式 SourceInstance；
- 人工实体匹配或 Finding 人工确认；
- Action Capset、RemediationPlan、审批、自动处置、外部写回或复测闭环；
- 多实例高可用、第二套调度器或生产级 agent-compose HA 语义。
