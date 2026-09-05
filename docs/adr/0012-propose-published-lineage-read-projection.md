# ADR-0012：提议已发布 Lineage 只读投影

状态：提议

日期：2026-09-05

## 门禁

本 ADR 是 Issue #169 的候选研究决策，仅描述已发布事实的只读 Lineage projection seam；不代表 accepted decision、独立 Admission 或 R1 实现授权。
本 ADR 不修改生产代码、测试、CONTEXT、current-state、约束、部署或数据库 schema；不新增 React dependency，不实现 UI，也不持久化 Graph Artifact。
ADR-0009、ADR-0010、ADR-0011 仍为各自候选提议；本 ADR 不把其中候选 Dataset、三来源比较、report-v2 或 `IPSourceComparisonFact` 变成已接受事实。

## 已核对的现状

- 当前没有 Lineage/Graph API，也没有 Graph DTO。后端公开的是 `/ip-assets`、`/findings`、`/governance-reports` 及其 detail/download 路由（`backend/app/api/routes/ip_results.py:48-161`；`backend/app/api/routes/governance_reports.py:390-471,605-675`）。前端只有 Assets、Findings、Reports 等现有页面，没有 Graph/Lineage 页面（`frontend/src/routes/_layout/index.tsx:14-18,480-500`）。
- 当前 IP 读模型以 Project 的 `latest_completed_run_id` 找到唯一 latest Run；`published_run_view()` 要求 latest Run 为 `COMPLETED`、processing contract 为 `ip-v1`，并要求 NORMALIZE、RESOLVE、CHECK_FINDINGS、PUBLISH steps 均成功（`backend/app/domain/ip_results.py:49-103`）。这是现有 Stage 4 latest 读门禁，不是本 ADR 所需的历史显式 Run + Report published predicate。
- 当前 Report list/detail 只按 tenant、Project、Run scope 与 `completed_at IS NOT NULL` 读取，尚未统一检查 Run 成功状态；CSV route 也按 scoped Report/Artifact 读取（`backend/app/domain/governance_reports.py:84-231,275-345`；`backend/app/api/routes/governance_reports.py:605-675`）。ADR-0011 提议的 shared `published report` predicate 才是目标候选合同，本 ADR 不声称它已经存在。
- 当前 PostgreSQL 已持久化的事实包括 Project、GovernanceRun、GovernanceReport、Evidence、RunStep、SourceSnapshot、Resource、Observation、ObservationResourceLink、Finding、FindingOccurrence、FindingTransition 及其 scope-checked links（`backend/app/domain/models.py:507-1572`）。Evidence 以四个可空 FK 强制 exact-one target 和 tenant + Project + Run + Report scope（`backend/app/domain/models.py:755-845`）。
- 当前 Finding occurrence/transition 及其 observation/snapshot links 已是可发布事实（`backend/app/domain/models.py:1282-1572`）；Finding 仍遵守 ADR-0005 的 canonical IP identity，mapped IPv6 不得成为另一 Resource（`docs/adr/0005-collapse-ipv4-mapped-ipv6-resource-identity.md:1-5`）。
- 当前 frontend 使用 React `19.2.7`，没有 `reactflow`、`@xyflow/*` 或 `dagre` dependency（`frontend/package.json:15-64`）。React 19 是已有运行时事实，不是本 ADR 引入的依赖。
- 现有 read tests 已证明 Project scope、角色读取、bounded trace、published report detail、历史 Stage 4 compatibility 与 CSV artifact hash 检查；它们不能证明已有 Graph API（`backend/tests/api/routes/test_stage4_governance_results.py:710-932`；`backend/tests/api/routes/test_governance_report_reads.py:310-443`；`backend/tests/api/routes/test_governance_report_downloads.py:73-227`）。

## 决策

### 1. 只读接口与 published predicate

未来 R1 可在现有 project authorization seam 上增加候选接口：

```text
GET /api/v1/projects/{project_id}/governance-runs/{governance_run_id}/lineage
```

这是本 ADR 的候选接口，不是当前已存在的 route。必须要求显式 `governance_run_id`，不提供隐含 latest 变体；用户需要 latest 时由调用方先读取现有 latest pointer，再以显式 Run 查询。这样历史 Run 的 Lineage 不会随 Project 当前状态或新 Run 改写。

请求先复用 `get_authorized_project()` 和 `PROJECT_READ_ROLES`：Viewer、Operator、Approver 与 ADR-0002 允许的 Global Admin 可读。当前实现对未授权 Project、跨 tenant 或无 membership scope 的 `get_authorized_project()` 查找返回 404 `Project not found`（`backend/app/api/project_authorization.py:54-62`），不是 403；候选接口优先统一沿用该 404，避免泄露对象存在性。无此 Run、无匹配 Report 或不满足 published predicate 也统一 fail closed；若未来候选合同改用 403，必须作为新候选行为单独明确，不能描述为现状。

R1 必须建立并复用一个共享 `published report` predicate：

1. Report 与 Run 的 tenant、Project、Run scope 完全匹配；
2. Run status 为 `COMPLETED` 或 `COMPLETED_WITH_WARNINGS`；
3. Run `completed_at` 非空；
4. Report 为该 Run 唯一 scoped Report，contract/generation mode 满足已接受的报告合同；
5. 被投影的每个子事实与该 tenant、Project、Run 具有数据库 scope match。

该 predicate 只允许读取最终 Publish 已提交的结构化事实。candidate file、raw Artifact bytes、BUILD/VALIDATE 中间结果、未发布 RunStep、未提交的 finding mutation 和任何早期步骤事实均不可读取。没有 Report 的 legacy/stage4-only Run 不是 `PARTIAL` Lineage，而是 `lineage_published_report_required` 的 fail-closed 结果；实现可沿现有 detail 的 404 语义返回 404。

PostgreSQL 查询必须在一个一致性读取事务/快照中完成；不得先读取 Run 再在另一个快照拼接节点。不得用 Project 当前 selection、latest pointer、candidate file 或缺失行推断已发布事实。

### 2. 代表性 DTO spike：原生 SVG/CSS 与 React Flow/Dagre

本次研究在仓库外的 `/tmp/lineage-dto-spike` 完成，不产生可入仓 prototype、fixture、Run snapshot 或 Issue Evidence。两种实现消费同一份非敏感代表性 DTO；DTO 有 1 个 Project、1 个已发布 Run、1 个 Report、2 个 SourceSnapshot、4 个 Observation、2 个 Resource、1 个 Finding、1 个 FindingOccurrence、1 个 FindingTransition、3 个 Evidence，共 17 个 node、25 个 edge。边界值同时包含长 accessible label、`empty_evidence_entries:[]`、`optional_netflow:"ABSENT"` 和 `UNKNOWN` activity。

Spike DTO（示例仅列合同字段，省略的字段不存在，不是 `facts:{}` 占位）：
示例 edge 对象只列 `edge_key`、`kind`、`from`、`to`；本次 spike 源码不向 edge DTO 加入 renderer-only 的 `index` 或其他辅助字段，因此这些字段不进入 DTO，也不进入任何 canonical bytes。

```json
{
  "schema_version":"published-lineage-v1",
  "projection_version":"v1",
  "project_id":"00000000-0000-4000-8000-000000000001",
  "governance_run_id":"00000000-0000-4000-8000-000000000002",
  "governance_report_id":"00000000-0000-4000-8000-000000000003",
  "status":"COMPLETE",
  "boundary_examples":{
    "long_label":"Customer Upload / CloudAtlas / source snapshot with a deliberately long accessible label",
    "empty_evidence_entries":[],
    "optional_netflow":"ABSENT",
    "unknown_activity":{"value":null,"reason_code":"quality_unknown"}
  },
  "nodes":[
    {"node_key":"project/00000000-0000-4000-8000-000000000001","kind":"PROJECT","label":"Project · long accessible label","facts":{"tenant_scope":"deployment"}},
    {"node_key":"run/00000000-0000-4000-8000-000000000002","kind":"GOVERNANCE_RUN","label":"Run · COMPLETED","facts":{"status":"COMPLETED","processing_contract_version":"ip-v1"}},
    {"node_key":"source_snapshot/00000000-0000-4000-8000-000000000011","kind":"SOURCE_SNAPSHOT","label":"Snapshot · CUSTOMER_UPLOAD","facts":{"source_type":"CUSTOMER_UPLOAD","source_record_count":2}},
    {"node_key":"source_snapshot/00000000-0000-4000-8000-000000000012","kind":"SOURCE_SNAPSHOT","label":"Snapshot · CLOUDATLAS","facts":{"source_type":"CLOUDATLAS","source_record_count":2}},
    {"node_key":"observation/00000000-0000-4000-8000-000000000021","kind":"OBSERVATION","label":"Observation · row:2 · 192.0.2.10","facts":{"source_type":"CUSTOMER_UPLOAD","source_record_key":"row:2","canonical_ip":"192.0.2.10"}},
    {"node_key":"observation/00000000-0000-4000-8000-000000000022","kind":"OBSERVATION","label":"Observation · row:3 · 2001:db8::1","facts":{"source_type":"CUSTOMER_UPLOAD","source_record_key":"row:3","canonical_ip":"2001:db8::1"}},
    {"node_key":"observation/00000000-0000-4000-8000-000000000023","kind":"OBSERVATION","label":"Observation · page:1:item:0 · 192.0.2.10","facts":{"source_type":"CLOUDATLAS","source_record_key":"page:1:item:0","canonical_ip":"192.0.2.10"}},
    {"node_key":"observation/00000000-0000-4000-8000-000000000024","kind":"OBSERVATION","label":"Observation · page:1:item:1 · 2001:db8::1","facts":{"source_type":"CLOUDATLAS","source_record_key":"page:1:item:1","canonical_ip":"2001:db8::1"}},
    {"node_key":"resource/00000000-0000-4000-8000-000000000031","kind":"RESOURCE","label":"Resource · 192.0.2.10","facts":{"resource_type":"IP","canonical_key":"192.0.2.10"}},
    {"node_key":"resource/00000000-0000-4000-8000-000000000032","kind":"RESOURCE","label":"Resource · 2001:db8::1","facts":{"resource_type":"IP","canonical_key":"2001:db8::1"}},
    {"node_key":"finding/00000000-0000-4000-8000-000000000041","kind":"FINDING","label":"Finding · UNREPORTED_ASSET · UNKNOWN","facts":{"finding_type":"UNREPORTED_ASSET","status":"OPEN","activity":{"value":null,"reason_code":"quality_unknown"}}},
    {"node_key":"finding_occurrence/00000000-0000-4000-8000-000000000042","kind":"FINDING_OCCURRENCE","label":"Occurrence · OPENED","facts":{"transition_type":"OPENED"}},
    {"node_key":"finding_transition/00000000-0000-4000-8000-000000000043","kind":"FINDING_TRANSITION","label":"Transition · OPENED","facts":{"transition_type":"OPENED"}},
    {"node_key":"report/00000000-0000-4000-8000-000000000003","kind":"GOVERNANCE_REPORT","label":"Report · deterministic-report-v1","facts":{"report_contract_version":"deterministic-report-v1","generation_mode":"DETERMINISTIC_TEMPLATE"}},
    {"node_key":"evidence/00000000-0000-4000-8000-000000000051","kind":"EVIDENCE","label":"Evidence · source snapshot","facts":{"target":"SOURCE_SNAPSHOT"}},
    {"node_key":"evidence/00000000-0000-4000-8000-000000000052","kind":"EVIDENCE","label":"Evidence · observation","facts":{"target":"OBSERVATION"}},
    {"node_key":"evidence/00000000-0000-4000-8000-000000000053","kind":"EVIDENCE","label":"Evidence · empty optional branch","facts":{"target":"FINDING_TRANSITION","optional":true}}
  ],
  "edges":[
    {"edge_key":"edge/PROJECT_RUN/project/00000000-0000-4000-8000-000000000001/run/00000000-0000-4000-8000-000000000002","kind":"PROJECT_RUN","from":"project/00000000-0000-4000-8000-000000000001","to":"run/00000000-0000-4000-8000-000000000002"},
    {"edge_key":"edge/RUN_SOURCE_SNAPSHOT/run/00000000-0000-4000-8000-000000000002/source_snapshot/00000000-0000-4000-8000-000000000011","kind":"RUN_SOURCE_SNAPSHOT","from":"run/00000000-0000-4000-8000-000000000002","to":"source_snapshot/00000000-0000-4000-8000-000000000011"},
    {"edge_key":"edge/RUN_SOURCE_SNAPSHOT/run/00000000-0000-4000-8000-000000000002/source_snapshot/00000000-0000-4000-8000-000000000012","kind":"RUN_SOURCE_SNAPSHOT","from":"run/00000000-0000-4000-8000-000000000002","to":"source_snapshot/00000000-0000-4000-8000-000000000012"},
    {"edge_key":"edge/SOURCE_SNAPSHOT_OBSERVATION/source_snapshot/00000000-0000-4000-8000-000000000011/observation/00000000-0000-4000-8000-000000000021","kind":"SOURCE_SNAPSHOT_OBSERVATION","from":"source_snapshot/00000000-0000-4000-8000-000000000011","to":"observation/00000000-0000-4000-8000-000000000021"},
    {"edge_key":"edge/SOURCE_SNAPSHOT_OBSERVATION/source_snapshot/00000000-0000-4000-8000-000000000011/observation/00000000-0000-4000-8000-000000000022","kind":"SOURCE_SNAPSHOT_OBSERVATION","from":"source_snapshot/00000000-0000-4000-8000-000000000011","to":"observation/00000000-0000-4000-8000-000000000022"},
    {"edge_key":"edge/SOURCE_SNAPSHOT_OBSERVATION/source_snapshot/00000000-0000-4000-8000-000000000012/observation/00000000-0000-4000-8000-000000000023","kind":"SOURCE_SNAPSHOT_OBSERVATION","from":"source_snapshot/00000000-0000-4000-8000-000000000012","to":"observation/00000000-0000-4000-8000-000000000023"},
    {"edge_key":"edge/SOURCE_SNAPSHOT_OBSERVATION/source_snapshot/00000000-0000-4000-8000-000000000012/observation/00000000-0000-4000-8000-000000000024","kind":"SOURCE_SNAPSHOT_OBSERVATION","from":"source_snapshot/00000000-0000-4000-8000-000000000012","to":"observation/00000000-0000-4000-8000-000000000024"},
    {"edge_key":"edge/OBSERVATION_RESOURCE/observation/00000000-0000-4000-8000-000000000021/resource/00000000-0000-4000-8000-000000000031","kind":"OBSERVATION_RESOURCE","from":"observation/00000000-0000-4000-8000-000000000021","to":"resource/00000000-0000-4000-8000-000000000031"},
    {"edge_key":"edge/OBSERVATION_RESOURCE/observation/00000000-0000-4000-8000-000000000023/resource/00000000-0000-4000-8000-000000000031","kind":"OBSERVATION_RESOURCE","from":"observation/00000000-0000-4000-8000-000000000023","to":"resource/00000000-0000-4000-8000-000000000031"},
    {"edge_key":"edge/OBSERVATION_RESOURCE/observation/00000000-0000-4000-8000-000000000022/resource/00000000-0000-4000-8000-000000000032","kind":"OBSERVATION_RESOURCE","from":"observation/00000000-0000-4000-8000-000000000022","to":"resource/00000000-0000-4000-8000-000000000032"},
    {"edge_key":"edge/OBSERVATION_RESOURCE/observation/00000000-0000-4000-8000-000000000024/resource/00000000-0000-4000-8000-000000000032","kind":"OBSERVATION_RESOURCE","from":"observation/00000000-0000-4000-8000-000000000024","to":"resource/00000000-0000-4000-8000-000000000032"},
    {"edge_key":"edge/RESOURCE_FINDING/resource/00000000-0000-4000-8000-000000000031/finding/00000000-0000-4000-8000-000000000041","kind":"RESOURCE_FINDING","from":"resource/00000000-0000-4000-8000-000000000031","to":"finding/00000000-0000-4000-8000-000000000041"},
    {"edge_key":"edge/FINDING_OCCURRENCE/finding/00000000-0000-4000-8000-000000000041/finding_occurrence/00000000-0000-4000-8000-000000000042","kind":"FINDING_OCCURRENCE","from":"finding/00000000-0000-4000-8000-000000000041","to":"finding_occurrence/00000000-0000-4000-8000-000000000042"},
    {"edge_key":"edge/FINDING_TRANSITION/finding/00000000-0000-4000-8000-000000000041/finding_transition/00000000-0000-4000-8000-000000000043","kind":"FINDING_TRANSITION","from":"finding/00000000-0000-4000-8000-000000000041","to":"finding_transition/00000000-0000-4000-8000-000000000043"},
    {"edge_key":"edge/OCCURRENCE_OBSERVATION/finding_occurrence/00000000-0000-4000-8000-000000000042/observation/00000000-0000-4000-8000-000000000021","kind":"OCCURRENCE_OBSERVATION","from":"finding_occurrence/00000000-0000-4000-8000-000000000042","to":"observation/00000000-0000-4000-8000-000000000021"},
    {"edge_key":"edge/OCCURRENCE_SNAPSHOT/finding_occurrence/00000000-0000-4000-8000-000000000042/source_snapshot/00000000-0000-4000-8000-000000000011","kind":"OCCURRENCE_SNAPSHOT","from":"finding_occurrence/00000000-0000-4000-8000-000000000042","to":"source_snapshot/00000000-0000-4000-8000-000000000011"},
    {"edge_key":"edge/TRANSITION_OBSERVATION/finding_transition/00000000-0000-4000-8000-000000000043/observation/00000000-0000-4000-8000-000000000021","kind":"TRANSITION_OBSERVATION","from":"finding_transition/00000000-0000-4000-8000-000000000043","to":"observation/00000000-0000-4000-8000-000000000021"},
    {"edge_key":"edge/TRANSITION_SNAPSHOT/finding_transition/00000000-0000-4000-8000-000000000043/source_snapshot/00000000-0000-4000-8000-000000000011","kind":"TRANSITION_SNAPSHOT","from":"finding_transition/00000000-0000-4000-8000-000000000043","to":"source_snapshot/00000000-0000-4000-8000-000000000011"},
    {"edge_key":"edge/RUN_REPORT/run/00000000-0000-4000-8000-000000000002/report/00000000-0000-4000-8000-000000000003","kind":"RUN_REPORT","from":"run/00000000-0000-4000-8000-000000000002","to":"report/00000000-0000-4000-8000-000000000003"},
    {"edge_key":"edge/REPORT_EVIDENCE/report/00000000-0000-4000-8000-000000000003/evidence/00000000-0000-4000-8000-000000000051","kind":"REPORT_EVIDENCE","from":"report/00000000-0000-4000-8000-000000000003","to":"evidence/00000000-0000-4000-8000-000000000051"},
    {"edge_key":"edge/REPORT_EVIDENCE/report/00000000-0000-4000-8000-000000000003/evidence/00000000-0000-4000-8000-000000000052","kind":"REPORT_EVIDENCE","from":"report/00000000-0000-4000-8000-000000000003","to":"evidence/00000000-0000-4000-8000-000000000052"},
    {"edge_key":"edge/REPORT_EVIDENCE/report/00000000-0000-4000-8000-000000000003/evidence/00000000-0000-4000-8000-000000000053","kind":"REPORT_EVIDENCE","from":"report/00000000-0000-4000-8000-000000000003","to":"evidence/00000000-0000-4000-8000-000000000053"},
    {"edge_key":"edge/EVIDENCE_SOURCE_SNAPSHOT/evidence/00000000-0000-4000-8000-000000000051/source_snapshot/00000000-0000-4000-8000-000000000011","kind":"EVIDENCE_SOURCE_SNAPSHOT","from":"evidence/00000000-0000-4000-8000-000000000051","to":"source_snapshot/00000000-0000-4000-8000-000000000011"},
    {"edge_key":"edge/EVIDENCE_OBSERVATION/evidence/00000000-0000-4000-8000-000000000052/observation/00000000-0000-4000-8000-000000000023","kind":"EVIDENCE_OBSERVATION","from":"evidence/00000000-0000-4000-8000-000000000052","to":"observation/00000000-0000-4000-8000-000000000023"},
    {"edge_key":"edge/EVIDENCE_FINDING_TRANSITION/evidence/00000000-0000-4000-8000-000000000053/finding_transition/00000000-0000-4000-8000-000000000043","kind":"EVIDENCE_FINDING_TRANSITION","from":"evidence/00000000-0000-4000-8000-000000000053","to":"finding_transition/00000000-0000-4000-8000-000000000043"}
  ]
}
```

预期计数固定为 `nodes=17`、`edges=25`，其中 node kind 计数为 `PROJECT:1`、`GOVERNANCE_RUN:1`、`SOURCE_SNAPSHOT:2`、`OBSERVATION:4`、`RESOURCE:2`、`FINDING:1`、`FINDING_OCCURRENCE:1`、`FINDING_TRANSITION:1`、`GOVERNANCE_REPORT:1`、`EVIDENCE:3`；edge kind 计数为 `PROJECT_RUN:1`、`RUN_SOURCE_SNAPSHOT:2`、`SOURCE_SNAPSHOT_OBSERVATION:4`、`OBSERVATION_RESOURCE:4`、`RESOURCE_FINDING:1`、`FINDING_OCCURRENCE:1`、`FINDING_TRANSITION:1`、`OCCURRENCE_OBSERVATION:1`、`OCCURRENCE_SNAPSHOT:1`、`TRANSITION_OBSERVATION:1`、`TRANSITION_SNAPSHOT:1`、`RUN_REPORT:1`、`REPORT_EVIDENCE:3`、`EVIDENCE_SOURCE_SNAPSHOT:1`、`EVIDENCE_OBSERVATION:1`、`EVIDENCE_FINDING_TRANSITION:1`。

Spike 方法与实测结果：

- 临时 package 使用现有前端的 React `19.2.7`/React DOM `19.2.7`，并只在 `/tmp` 安装 `@xyflow/react@12.11.6`、`@dagrejs/dagre@3.1.1`、Vite `8.2.2`；`@xyflow/react` 的 peer contract 为 React/React DOM `>=17`，因此该组合安装和浏览器运行通过。临时安装没有改 `frontend/package.json` 或任何仓库 lock。
- 磁盘包体实测（`du -sk`，KiB 文件系统占用）：原生 SVG/DOM 增量为 0；React Flow 目录 2,860 KiB、Dagre 目录 1,632 KiB，二者直接增量 4,492 KiB；临时完整 `node_modules` 为 49,756 KiB。生产构建同时包含两种 renderer，输出为 JS 424.94 kB（gzip 134.85 kB）与 CSS 15.92 kB（gzip 2.76 kB）；该数字不是把原生和 library 拆开的 bundle 结论。
- 同一页面实际渲染的 DOM selector 计数为：原生 SVG 有 17 个 node group、25 条 line，React Flow 有 17 个 `.react-flow__node`、25 个 `.react-flow__edge`。这些是渲染结果计数，不是每个 node/edge 都有 `data-testid`。
- 键盘实测：原生可访问 DOM 列表产生 17 个 `button`，全部 `tabIndex=0`，Tab 顺序逐一到达并保留完整 aria-label。React Flow 节点产生 17 个 `role=group`/`tabIndex=0`，但默认节点没有 aria-label；25 个 edge group 进入焦点/ARIA DOM。结论是 React Flow 不能替代显式节点键盘路径，原生方案必须保留同步 DOM list。
- 读屏/DOM 实测：原生 node button 的 aria-label 含 kind 与 long label；必要事实详情由同步 DOM list 按合同显式提供，本 spike 不证明所有 facts 都出现在 aria-label 中。React Flow 节点的可见文本存在但没有对应 aria-label。原生 SVG edge 仅视觉层 `aria-hidden`；React Flow 的 edge DOM 需额外审计。两种方案都能显示同一事实，但原生方案的读屏语义由本 ADR 可直接约束。
- React Flow/Dagre 的 runtime 渲染与 Dagre layout 在 Chromium 中成功，节点/边计数为 17/25；原生 renderer 同样成功。没有提交截图、构建产物或临时文件。

因此选择原生 SVG/CSS + 同步的可访问 DOM list：bounded static lineage 不需要拖拽、缩放或自由布局，且没有新增包体。若未来规模或交互需求超过此选择，必须重新做有实际 bundle、React 19 peer、键盘、读屏和 rendering 证据的 spike，并由新 ADR 决定；不能在 R1 中悄然引入 React Flow/Dagre。

### 3. DTO、节点与边

DTO 只包含经过 published predicate 的事实和稳定的投影元数据：

- 顶层：`schema_version`、`projection_version`、`project_id`、显式 `governance_run_id`、匹配的 `governance_report_id`、`status`、`nodes`、`edges`、`truncated`、`idempotency_sha256`、`semantic_sha256`、`representation_sha256`。`idempotency_sha256` 是请求 tuple 的可重放识别值，不是业务事实；若实现不回显它，仍必须按本节计算并使用。
- `PROJECT`：Project identity 与 tenant scope；不展开成员、Secret 或可变配置。
- `GOVERNANCE_RUN`：Run identity、status、`completed_at`、processing/report contract version；不暴露 Session/control identity、request metadata 或 RunStep。
- `SOURCE_SNAPSHOT`：source type、content/schema/method fingerprint、record count 及 published identity；不暴露 raw Artifact bytes、storage path 或 candidate file。
- `OBSERVATION`：source type、source record key、canonical IP、已发布 CloudAtlas asset/status 字段及 identity；不投影 raw upload、Artifact 内容或未确认的端口/方向。
- `RESOURCE`：`IP` type、Resource identity、ADR-0005 canonical key。
- `FINDING`：Finding identity、type/status、Resource reference；FindingOccurrence 与 FindingTransition 作为现有 published fact 可选节点，使用其 persisted transition/occurrence type，不创建新的生命周期类型。
- `GOVERNANCE_REPORT`：Report identity、contract version、generation mode、published HTML/CSV hashes；不嵌入 raw HTML/CSV bytes。
- `EVIDENCE`：Evidence identity、coverage 若已有合同、以及 exact-one target reference；target 只能是现有 SourceSnapshot、Observation、FindingOccurrence 或 FindingTransition。Evidence target 不复制事实。

当前模型没有 published `Process`、`Detection` 或 `IPSourceComparisonFact` table；本 ADR 不创建这些节点，也不把 `RunStep` 伪装成 Process。ADR-0011 的 comparison fact 只有在另一个 accepted contract 后才可追加新的 node/edge kind。

稳定 node key 必须是 scoped persisted identity，而不是显示文本：

```text
project/<project_id>
run/<governance_run_id>
source_snapshot/<source_snapshot_id>
observation/<observation_id>
resource/<resource_id>
finding/<finding_id>
finding_occurrence/<finding_occurrence_id>
finding_transition/<finding_transition_id>
report/<governance_report_id>
evidence/<evidence_id>
```

稳定 edge key 精确为 `edge/<kind>/<from_node_key>/<to_node_key>`；同一 scope 内禁止重复。初始 allowlist 为：`PROJECT_RUN`、`RUN_SOURCE_SNAPSHOT`、`SOURCE_SNAPSHOT_OBSERVATION`、`OBSERVATION_RESOURCE`、`RESOURCE_FINDING`、`FINDING_OCCURRENCE`、`FINDING_TRANSITION`、`OCCURRENCE_OBSERVATION`、`OCCURRENCE_SNAPSHOT`、`TRANSITION_OBSERVATION`、`TRANSITION_SNAPSHOT`、`RUN_REPORT`、`REPORT_EVIDENCE`、`EVIDENCE_SOURCE_SNAPSHOT`、`EVIDENCE_OBSERVATION`、`EVIDENCE_FINDING_OCCURRENCE`、`EVIDENCE_FINDING_TRANSITION`。不存在的 target、scope mismatch、重复 edge 或 unknown kind 均 fail closed。

节点 kind rank 的完整顺序为：`PROJECT(1)`、`GOVERNANCE_RUN(2)`、`SOURCE_SNAPSHOT(3)`、`OBSERVATION(4)`、`RESOURCE(5)`、`FINDING(6)`、`FINDING_OCCURRENCE(7)`、`FINDING_TRANSITION(8)`、`GOVERNANCE_REPORT(9)`、`EVIDENCE(10)`。edge kind rank 的完整顺序为：`PROJECT_RUN(1)`、`RUN_SOURCE_SNAPSHOT(2)`、`SOURCE_SNAPSHOT_OBSERVATION(3)`、`OBSERVATION_RESOURCE(4)`、`RESOURCE_FINDING(5)`、`FINDING_OCCURRENCE(6)`、`FINDING_TRANSITION(7)`、`OCCURRENCE_OBSERVATION(8)`、`OCCURRENCE_SNAPSHOT(9)`、`TRANSITION_OBSERVATION(10)`、`TRANSITION_SNAPSHOT(11)`、`RUN_REPORT(12)`、`REPORT_EVIDENCE(13)`、`EVIDENCE_SOURCE_SNAPSHOT(14)`、`EVIDENCE_OBSERVATION(15)`、`EVIDENCE_FINDING_OCCURRENCE(16)`、`EVIDENCE_FINDING_TRANSITION(17)`。

节点先按 kind rank、再按 `node_key` 的 Unicode code point 升序；边先按 kind rank、再按 `from_node_key`、`to_node_key`、`edge_key` 升序。对象键递归排序，数组只使用上述确定性顺序；不按数据库默认顺序、created_at 或 UI label 排序。

### 4. Empty、Partial 与 UNKNOWN

- `COMPLETE`：published predicate 通过，所有本次投影合同要求的事实与边存在，且响应没有截断。
- `EMPTY`：published predicate 通过，但除了必要 Project/Run/Report identity 外没有可投影的 optional fact/edge；例如合法的零 Finding/零 Evidence 报告。`EMPTY` 不表示资产、流量或风险为零。
- `PARTIAL`：只在显式 bounded limit/cursor 造成截断，或某个已由 accepted contract 标明为 optional 的分支缺失时使用；DTO 必须返回 `truncated`/continuation 或 optional branch state，禁止静默丢节点。explicit absent NetFlow 是合同上的 `ABSENT`，不是 `UNKNOWN`，也不必伪造 NETFLOW 节点。
- `UNKNOWN`：只表达 published fact 明确允许但无法建立正向值的属性，例如 NetFlow quality/coverage 的 unknown；属性值必须为 `null` 并带稳定 reason code。不得把缺行、零行、invalid 行、missing target 或 failed Run 推断成零活动、无风险或不存在。

缺失 mandatory fact、scope mismatch、报告与 Run 不一致、预期 target 缺失或 published predicate 失败不是 `UNKNOWN`，而是稳定 fail-closed 错误。`UNKNOWN` 不允许成为业务 identity、Finding 状态或自动关闭依据。

### 5. 三种 Hash 与 HTTP ETag

三者职责严格分离：

1. **`idempotency_sha256`**：对 canonical request tuple 的 compact UTF-8 canonical JSON bytes 做 SHA-256。tuple 至少按以下顺序包含 tenant、Project、显式 `governance_run_id`、`projection_version`、query bounds（limit/cursor 等）和 auth-independent scope；不包含 user、role 或 Authorization，因此同一 scope 的重复投影请求得到同一值。它只用于识别重复投影请求、日志关联或短期去重，不是 Project、Run、Report、Finding、Evidence 或任何事实的 identity；不允许以它定位或创建业务事实。
2. **`semantic_sha256`**：对 published facts 的 semantic canonical bytes 做 SHA-256，只包含 scope 与显式 Run/Report identity、Run published status/completed_at/contract versions、SourceSnapshot 的 source type/fingerprints/record count、Observation 的 source type/record key/canonical fields、Resource canonical key、Finding type/status/occurrence/transition semantics、Report contract/mode/artifact hashes、Evidence exact target 和允许的 edge relations。它排除 UI label、SVG 坐标、分页/cursor、ETag、created/updated operational timestamps、storage path 与 raw bytes；组成必须随 projection version 版本化，且不得替代业务 identity。
3. **`representation_sha256`**：对完整 DTO representation bytes 做 SHA-256；bytes 使用 UTF-8、递归按 Unicode code point 排序的对象键、固定 node/edge rank、紧凑 JSON 分隔符、不带 BOM 或前后空白。`representation_sha256` 字段本身从 preimage 中排除，HTTP ETag 也不进入 DTO preimage；其他已确定的顶层字段（包括回显的 `idempotency_sha256` 与 `semantic_sha256`）按该 canonical representation 序列化。它涵盖完整 DTO 的 status、truncated、query-bound response、nodes 和 edges，是表示稳定性证明，不是业务 identity。

HTTP `ETag` 只作表示/version/cache validator，格式固定为强 validator：`"published-lineage-v1:<representation_sha256>"`。每次请求仍必须重新执行 authorization、scope 和 published predicate，不能用 ETag 绕过 ACL，也不能把 ETag 当作数据库 key、幂等键或事实 identity。`If-None-Match` 只有在同一 scope、同一 query bounds、同一 projection version 下才能返回 304。

历史显式 Run 的 published facts 通过 completed-run late-mutation guards 保持不可变，故同一 projection version 下 `semantic_sha256` 与 `representation_sha256` 稳定。新 Run Publish 只产生新 scope 的表示，不失效或改写旧 Run 的 ETag。projection schema、node/edge allowlist、published predicate 或 ordering policy 变化时必须提升 projection version，重新产生 representation Hash/ETag；权限变化不能由缓存绕过，仍需重新授权。`idempotency_sha256` 不参与 ETag，也不回填为业务字段。

### 6. 只读、不可变与边界

R1 只从 PostgreSQL 已提交 facts 生成 DTO，不写入任何 graph 表，不创建 Graph Artifact，不创建 RunStep，不在 lineage 查询时追加 AuditEvent，不修改 latest pointer，不触发 Report、Retry、Rerun 或 Finding mutation。Graph 可在请求内临时组装并丢弃。

`COMPLETED` 与 `COMPLETED_WITH_WARNINGS` 的既有 completed-run guards 继续拒绝 Report、Evidence、Observation、Snapshot、Finding identity 与 links 的晚到 mutation；读取发现不一致时 fail closed，而不是修复、补回或缓存不一致结果。现有 Report CSV 的 artifact/hash preflight 证明了“先验证再公开”的方向（`backend/tests/api/routes/test_governance_report_downloads.py:153-227`），Lineage 不得绕过同等 scope/hash/published checks。

项目归档不改变已发布 Lineage 的只读事实；权限仍先校验。Viewer/Approver 可读取已授权的 published projection，但沿用当前 CSV 仅 Operator/Admin 可下载的差异：Lineage 是结构化只读视图，不提供 raw artifact 下载。

## 被拒方案

- **读取 latest 并隐式推断 Run**：拒绝；历史可读性和 ETag 稳定性要求显式 Run。
- **直接读取 candidate/raw Artifact 或早期 RunStep**：拒绝；它们不是客户可见的 published PostgreSQL facts。
- **持久化 Graph Artifact 或 Graph RunStep**：拒绝；增加第二事实形态、迁移和晚到 mutation seam，没有本票需求。
- **引入 Service、Detection、Entity Graph、通用 lineage registry 或 graph database**：拒绝；当前模型没有这些已接受事实，且会扩大领域合同。
- **React Flow/Dagre 作为默认实现**：拒绝；代表性 DTO 在 bounded static lineage 下不需要拖拽/缩放，新增包体与 a11y/React 19 验证成本不提供足够 leverage。
- **把 canonical/semantic Hash 或 ETag 当业务 ID**：拒绝；三者职责已在第 5 节分离。

## 依赖、Delivery 冻结与 YAGNI

后续 Delivery Spec 必须冻结：candidate endpoint 的精确 JSON Schema、projection version、node/edge kind allowlist、fact fields、scope/auth 错误码、max nodes/edges、continuation、Hash canonicalization、ETag/cache headers、empty/partial/unknown reason codes、golden DTO 与 accessibility acceptance。Delivery 不得改变本 ADR 的 published-only、explicit-Run、no-persistence、no-Service/Detection、no-React-dependency 选择。

R1 只有在本 ADR 与其 Delivery Spec 分别通过独立 Admission 后才可执行。若未来图规模、交互或 comparison fact 需求超过原生 SVG/CSS 的 bounded contract，先做新的 DTO spike 和独立决策；不在本 ADR 中预留 dependency、plugin、layout registry 或第二套调度器。

## 参考

- Issue #169：最小 Lineage 只读投影及实现方式。
- ADR-0002：Project authorization 与 Global Admin 例外。
- ADR-0003/0004：单活跃 Run、Retry/Rerun 与 Session fail-closed。
- ADR-0005：canonical IP Resource identity。
- ADR-0007：模型只读有界 Evidence，不读取 raw/normalized Artifact。
- ADR-0008：Run 固定输入、历史 Run 不回填、Retry/Rerun 语义。
- ADR-0011：候选 published report predicate、原子 Publish、Evidence 与 report-v2 边界；仍为提议，不授权 R1。
