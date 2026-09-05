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
- 受控 `.csv` / `.txt` NetFlowDataset 接受：部署必配且最高 50 MiB 的字节上限、确定性全量扫描与规范化、不可变 raw / normalized Artifact、Project 内幂等身份和脱敏审计；当前不提供 Dataset 列表、选择、删除，也不把 Dataset 固定到 GovernanceRun；
- CloudAtlas SourceInstance 的配置、只读验证、指纹固定、启用和停用；
- 正式 `cloudatlas-read` OctoBus Package，仅允许 `cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets`；
- GovernanceRun 的 Trigger、Retry、Rerun、RunStep、SourceSnapshot 与 Publish；
- agent-compose Session 创建、终态查询、同 Session 恢复和未知状态 fail-closed；
- 客户内部 OpenAI-compatible 模型经 Pi 使用固定非客户 fixture 执行部署资格检查，PostgreSQL 仅保存脱敏门禁指标和当前配置绑定；
- Operator 可从已发布报告显式选择一至八个有持久 Evidence 的“未观测资产”并创建 `GENERATING` AI 治理草稿；Controller 先持久保留确定性的 agent-compose Run identity，再启动独立 Pi Session；本阶段 Session 只建立并绑定身份，不接收数据库、应用、模型凭据或草稿输入；
- CustomerUpload 与 CloudAtlas 的 IP Observation、Project 级稳定 IP Resource 和精确解析；
- “未报备资产”“未观测资产”两类 Finding、Occurrence、Transition 与来源引用；
- `deterministic-report-v1` 报告：canonical JSON、HTML、CSV 与 Hash；
- Assets、Findings、GovernanceRun 和确定性报告的 API 与 Web 读取面。

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
