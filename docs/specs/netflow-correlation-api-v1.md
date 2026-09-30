# NetFlow 源侧关联 API 合同 v1

状态：已批准的待实现合同，随 [EXP-NF-INT-01](exposure-focus-release-1.md#exp-nf-int-01固定输入的-netflow-关联与人工复核材料) 固定同一 Git commit。阶段 B 只发布文档并登记任务，以下端点尚未实现；现有 API 保持不变。这不是从当前 FastAPI 导出的 OpenAPI。阶段 C 另获实施授权后，必须交付实际后端 SHA、`app.openapi()` 导出的完整合同及其 SHA256、合成样例和兼容说明；前端方在自己的分支运行 `bash scripts/generate-client.sh`，该脚本会写入 `frontend/openapi.json` 并执行生成/lint，后端会话不执行它。

本文件是 EXP-NF-INT-01 的规范性接口附录，行为、字段、失败与恢复合同随主 Spec 一起批准；Issue 必须引用两者的同一固定 commit。实际授权、文件唯一写入者及双方候选 SHA 留 GitHub Issue，不由文档批准推导。所有样例值均为合成，不对应客户文件。

## 1. 公共约束

- 基路径 `/api/v1/projects/{project_id}`。认证、角色、tenant 解析、归档限制沿现有 `get_authorized_project`；请求体不接受客户端 tenant 或 actor。
- 所有新响应含 `contract_version=netflow-correlation-v1`、明确 Project 和各固定输入身份。GET 只读、`Cache-Control: private, no-store`。无 GET 触发模型、分析、Run 或云图同步。
- 输入模型 `extra=forbid`；UUID/Hash 不截断，IP 使用规范文本；未知数值 null，不代入 0/false/空数组。对于源字段 missing/null/空串，保留各自可用性标记，不统一成空值。
- 写请求要求 `Idempotency-Key`，1–128 字符、沿现有 `[A-Za-z0-9_-]+`；绑定 actor/Project/操作及规范请求 Hash。同键同内容恢复原响应，同键异内容 409。各创建集合提供 `/operations/{key}` GET 查询原 key，仅原 actor 可读，不根据未知响应换 key。
- 分页沿用 `skip>=0, 1<=limit<=100, default limit=25`，返回 `{data,count,skip,limit}`。`count` 是完整筛选集合行数；`total_*` 是固定版本完整集合；来源 total 单独字段。筛选在排序/分页前，不从当前页计算汇总。
- 任务列表/详情、material_status 筛选、依赖和材料汇总均接受 `feedback_revision_id`。首次读取解析同一次读事务内的当前封存反馈并回传 ID；下一页和详情必须显式传同 ID。每个成功 Analysis 有系统生成的空白原版 UUID；不是用 null 兼指“原版”和“最新”。显式错误/跨 Analysis 反馈 ID 返回 404，不换版本。新反馈发布不改变旧版本分页/计数。
- 地址排序 `ip_asc|ip_desc` 按 family、数值地址、稳定 address_key；服务按 protocol（未知最后）、local_port（不适用最后）、object_key；任务按 work_order、task_id；版本按 created_at desc、id。只支持声明的排序，不接受任意 SQL 字段。
- 切账号/Project/namespace/Analysis/关联版本清除旧结果与恢复意图，晚到响应不污染新范围。显式 ID 拒读时不回退 latest。当前 source 撤权/到期不能用浏览器缓存降级展示。

## 2. 来源选择与范围

### 输入选择形状

`customer` 为 null 或 `{upload_id, revision_id}`，revision_id 可 null 表示上传原版；归档条目的默认比较语义沿原生 reader 的当前有效条目，不把管理归档当物理删除历史。固定 Revision 后不再跟随当前选择。

`cloud` 为 null 或以下之一，不混选：

- `{kind:"legacy_snapshot", source_snapshot_id, ledger_revision, scope_revision}`：复用旧已发布兼容 Run 的云图观察，响应附原 Run、SourceInstance、Hash、valid 过滤；无端口字段。
- `{kind:"external_versions", source_instance_id, ip_version_id, port_version_id}`：两个 version_id 可各自 null，但不能同时 null；均必须属于同一个仍可读的 assets-v1 来源/空间，domain 正确。只读本地已发布完整或正常封存非全量版本；失败暂存拒绝。每域时间/完整性分别返回。

`netflow` 为 null 或 `{analysis_id}`，Analysis 固定 Dataset/context/component；不能直接用当前 Dataset 代替已经完成的 Analysis。

所有来源均 null 拒绝 422。合法未提供用 null，而不是伪造空文件。旧客户 v1 上传合同不支持空工作簿，仍沿原接口拒绝；该拒绝是失败，不冒充 VALID_EMPTY。有效空在支持它的云图/NetFlow 合同中照实保留；有效客户版本按某地址查询零行是“无匹配”，不是“空输入”。

### 同空间确认

创建关联默认 `scope_state=UNKNOWN`，来源自身的可读性不等于跨源关联许可。只有 Admin 可追加该固定来源集合的 `CONFIRMED` 或 `REVOKED` 修订和证据。可引用当前有效的旧 legacy 范围确认，服务端验证其实际适用版本；不让普通请求通过写一个 namespace 字符串自授权。

`correlation_revision_id` 是固定读身份；`root_id` 仅用于找当前撤销/更正门禁。确认/更正返回新 revision ID，旧 ID 保持。读取旧确认时同时回传 `historical_scope_state` 与 `current_scope_state`；撤销不重写旧结果，但阻止当前跨源关联显示/写入。

## 3. 新增端点合同（待实现）

| 方法/路径（均在基路径下） | 权限/用途/返回 |
|---|---|
| GET `/netflow-datasets/{dataset_id}/processing-contexts` | 读角色；上下文修订列表，固定版本、状态和声明出处 |
| POST 同路径 | 全局 Admin；追加 context，含 expected_parent_id；201，不能从旧 CIDR 资格推导 declared_source |
| POST `/netflow-datasets/{dataset_id}/analyses` | Operator/Admin；`{context_revision_id,retry_of_analysis_id?}`；202 持久处理身份；省略 retry_of 是普通创建/恢复原操作，不把排队当完成 |
| GET 同路径 | 读角色；本 Dataset 分析版本/状态，不改当前选择 |
| POST `/netflow-datasets/{dataset_id}/analysis-imports` | Admin；受控 result ZIP＋下述 metadata（含可选 retry_of_analysis_id）；202；导入和 rules replay 同一验证/发布入口 |
| GET `/netflow-analyses/{analysis_id}` | 状态、固定输入、质量和计数、产物指纹、能力标志；处理中没有伪业务结果 |
| POST `/netflow-analyses/{analysis_id}/reconcile` | Operator/Admin；显式核验原 agent-compose Session，只恢复已经完整验证的原产物，不重调度未知任务 |
| GET `/netflow-analyses/{analysis_id}/peers` | 分页独立对端；ip/protocol/peer_port 筛选；不作为本方地址接口 |
| GET `/netflow-analyses/{analysis_id}/review-tasks` | feedback_revision_id 固定分页任务/筛选计数；task_scope/task_kind/material_status/object_key 筛选，批次任务一次计数 |
| GET `/netflow-analyses/{analysis_id}/review-tasks/{task_id}` | feedback_revision_id 固定任务材料、字段 schema、依赖和状态；opaque task_id URL 编码 |
| GET `/netflow-analyses/{analysis_id}/feedback` | feedback_revision_id 可显式固定；首次解析回传封存版本 UUID；返回原提供方声明与实际提交 actor 分别归属 |
| POST 同路径 | Operator/Admin；expected_parent_id＋responses＋可选人工说明；追加回填，201；原版不可更新 |
| GET `/netflow-analyses/{analysis_id}/evidence` | 固定 object_key 或 peer_key 的分页来源引用，side 显式；拒绝任意文件路径、偏移和 URL |
| POST `/source-correlations` | Operator/Admin；上述三个 slot、network_namespace、可选明确 legacy 历史 Run；默认 UNKNOWN；201 |
| GET `/source-correlations` | 读角色；不可变关联修订/输入组合列表，可按 Dataset/namespace 筛选 |
| POST `/source-correlations/{revision_id}/scope-revisions` | Admin；expected_parent_id、CONFIRMED/UNKNOWN/REVOKED、证据；201 新修订 |
| GET `/source-correlations/{revision_id}` | 固定输入卡片、三来源状态、全量正向交集和限制；这是汇总，不是旧 Run report |
| GET `/source-correlations/{revision_id}/addresses` | 分页地址；ip（精确规范化）、positive_sources（精确集合）、unmatched_netflow、has_review_task 筛选，sort=ip_asc 默认 |
| GET `/source-correlations/{revision_id}/addresses/{address_key}` | 地址详情、匹配依据/原因、来源数量、任务链接和可选固定历史 Resource/Run 链接 |
| GET `/source-correlations/{revision_id}/addresses/{address_key}/services` | 分页源侧对象及协议/本地端口/台账区间/云图端口比较，显式未知维度 |
| GET `/source-correlations/{revision_id}/addresses/{address_key}/evidence` | source=customer/cloud/netflow 分页；完整原生行身份、版本、引用及 omitted_count，无后台补采 |

对关联源权限/保留的检查覆盖汇总、地址列表、详情、服务、证据；不能只拦详情。缺失或失败的某输入可在新建关联中如实记录来源状态、展示其他合法自身来源，但任何跨范围/撤权不降格成 NOT_PROVIDED。来源内容破损后依赖它的固定比较不可继续返回旧匹配事实。

### 3.1 写入信封、显式恢复与消费限制

- **Context POST**：`expected_parent_id`（首次 null）、`network_namespace`、`state=CONFIRMED|UNKNOWN|CONFLICT|REVOKED`、`endpoint_selection=declared_source`、`source_position_evidence`（1–2048）、`nat_context=none|mapped|unknown`、`nat_evidence`（none/mapped 必填、1–2048）、`observation_point={id,view}`、`sampling={mode,rate}`。view 为 PUBLIC_EDGE/INTERNAL/UNKNOWN；sampling 沿组件 schema。tenant/project/Dataset Hash/输入合同/test_fixture 由服务端固定；canonical 的组件 input_timezone=UTC，原始时间转换依据和业务确认资格另列。位置/空间未确认时不能启动 declared_source 处理。撤销只追加新修订；GET 历史仍回传当前门禁。
- **Import POST**：multipart 只有 `file`（ZIP）和 `metadata`（JSON）。metadata 为 `{context_revision_id,source_manifest_sha256,original_config,binding_evidence,retry_of_analysis_id?}`；original_config 是能计算相同 config_sha256 的完整 ProcessorConfig，mode 必须 rules；binding_evidence 为 1–2048 字符的 Admin 原身份→目标对象依据。原身份/context 从包内 manifest 读取但不用于鉴权，必须和所选本地上下文一致或有明确原身份映射；不能映射到不同 namespace/输入内容。
- **包布局**：必需 `analysis/manifest.json` 及其明确白名单 Artifact、`review/summary.json`、`review/enriched-observations.jsonl`、`review/review-tasks.jsonl`；可选 `feedback/submission.json` 和完整 `feedback/result/` 下组件生成的 summary.json/review-progress.jsonl/REVIEW.md。各目录原字节/相对引用不改，raw 输入不重复放包中。ZIP 压缩体不超过 Dataset 上传部署限额（最大 50 MiB），解压总量最多 320 MiB、最多 32 个普通文件、单成员最多 100 MiB；更小的 schema/组件阶段限额仍优先。未知成员/重名/链接/路径穿越/CRC或解压字节不符拒绝；不能把整个私有 viewer 文件夹上传。
- **显式失败后重新处理**：普通 analyses/analysis-imports 重复请求无论 key 是否变化都恢复既有处理身份。只有带 `retry_of_analysis_id` 的明确新请求可为同一输入、context、config、component 和（导入时）manifest 创建后继；父记录必须是权威终态 FAILED。Project 锁下核验资格，数据库唯一约束保证一个失败父记录最多一个后继，重复/并发返回该同一后继；新建返回 202，原 key 重放保持原响应。UNKNOWN/运行中/成功或处理身份不一致返回 409 `netflow_retry_not_allowed`。后继使用新的 Analysis/Session，返回 retry_of_analysis_id；旧记录和原任务键不变。reconcile 始终只恢复原 Session，不调用这个新尝试路径。
- **Feedback POST**：`{expected_parent_id,responses,human_note?}`。expected_parent_id 为当前封存反馈 UUID（首次也是系统空白原版）；responses 最多 100 个不同 task_id 的显式替换，元素为 `{task_id,provided_by,submitted_at,answers,note_checks}`。任务完整对象和 binding 从服务端已校验 Artifact 重建，不信任客户端自报 task/context。provided_by/submitted_at 可 null，沿组件来源声明校验，实际账号/时间另存；note_checks 保留原 schema、仅规则保留，不运行模型。answers 用该 task_kind 的组件 JSON Schema（任务详情返回 schema_version 和 answer_schema），不能借其他类型字段。未提及任务完整保留；提及任务以所交完整 answers 替换，允许显式改成空/未知，不把旧字段自动补回。human_note 最多 2048 字符，纯人工说明不改变组件规则答案。
- **反馈整体限制**：沿组件 10000 任务、16 MiB 最终有效 submission、64 KiB 单响应、64 MiB progress 输出限额。即使 patch 很小，合入后的全集也必须满足；超限 413，旧反馈保持。Analysis 发布前验证初始空白反馈可消费；任务材料字段齐全仅为 FIELDS_COMPLETE_PENDING_REVIEW。
- **服务比较分页**：`/addresses/{address_key}/services` 的 `skip/limit` 只选择源侧对象/原生服务材料；`comparison_skip>=0`、`1<=comparison_limit<=100`（默认 0/25）分别约束每个对象内客户及云图比较。`customer_comparisons`、`cloud_comparisons` 各返回 `{data,count,skip,limit}`，count 为该固定版本的完整匹配记录数，未选页不构造比较对象；每项保留 `record_key/version_id/domain`，不同云图域的同号来源 ID 不混淆。翻比较页时固定关联版本、地址键和对象页；不能把当前比较页当全集。全量原生证据仍由独立 evidence 分页读取。
- **固定组件状态适用性**：保留主 Spec N6 的完整六项材料状态词表；依维护者在阶段 C 批准的 N6/AC-NF-11 修订，固定 0.4.0 的 confirmed declared_source 不生成 scope 任务，`MATERIAL_CONFLICT` 在本切片不适用。其余五种状态须实测，不用枚举存在代替可达行为验证。

来源引用是组件保存的有界样本，分页不补造省略行；返回 retained_count/omitted_count 和绑定的 Dataset/Artifact Hash。全量原材料仍受原 Artifact 授权，不接受任意路径/URL，也不将引用样本的 count 叫作完整原始记录数。

## 4. 字段映射

| 组件/现有来源字段 | 新接口字段/语义 |
|---|---|
| Dataset id/raw_sha256/normalized_sha256/contracts | `inputs.netflow.dataset`；canonical 处理 input_sha256 对 normalized，导入 raw profile 对 raw |
| manifest run_id/component_version/schema_version/config_sha256/context_sha256 | `analysis.provenance`；component_run_id 与 Exposure analysis_id 分开 |
| context endpoint_selection/scope_evidence/observation_point/sampling | `analysis.context`；逐行位置声明、NAT 声明、采集/采样未知分开 |
| observations ip/ip_version | `canonical_ip/family`，只有源侧生成地址集合 |
| object_key/protocol/local_port | `service_hypothesis_key/protocol_number/local_port`；观察元组，不命名已确认服务 |
| features record_count/source_count/destination_count | `source_record_count`；declared_source 的 destination_count 必须 0，重复源记录保留 |
| source_refs/source_refs_omitted | `evidence_refs/omitted_count`，均绑定 Dataset/Analysis/side，不宣称样本全集 |
| peers peer_key/peer_port/record_count | 独立 `/peers` DTO；`is_local_candidate=false` |
| enriched observation behavior_tags/review_category/review_task_ids | `behavior/task_refs`，保留组件版本和原解释，不把每个 review 对象变成独立人工任务 |
| Customer Ledger canonical_ip/entry_id/fields.start_port/end_port | 客户匹配行和闭区间；协议/有效时间 UNKNOWN，负责人字段仅来源声明 |
| SourceSnapshot + Observation | 旧云图来源记录引用；没有的端口/服务材料明确未知 |
| ExternalAssetVersion + Record canonical_ip/fields.protocol/port | 新云图各自版本内 IP/端口证据；源 ID 无损字符串、源时间原文及缺口保持 |
| review task/source_run_id/task_id/depends_on | `task_ref={analysis_id,task_id}`；绑定原任务集，无 Resource 前置 |
| feedback material_status/answers/provided_by/submitted_at | `material_status/declared_answers/provider_claim`；实际 authenticated author/time 独立字段 |
| legacy Resource + explicit Run | `history_link` 可 null；需有效 legacy 同空间与该 Run 内真实证据，不自动创建 |

来源状态：`read_state=VALID_NONEMPTY|VALID_EMPTY|NOT_PROVIDED|READ_FAILED`；`coverage_state=SUFFICIENT|INSUFFICIENT|UNKNOWN|NOT_APPLICABLE`。外层 state 在读取有效但不足以支撑完整覆盖解释时为 INSUFFICIENT_COVERAGE，保留 read_state 和正向记录数。

NetFlow 的 VALID_EMPTY 只用于 raw_record_count=0、valid=0、isolated=0 的合法仅表头输入。raw>0/valid=0 表示全部隔离：Analysis FAILED，error_code=`netflow_no_valid_records`、来源 READ_FAILED，result=null；不把 canonical 的零行伪装空输入。部分隔离保留有效事实并将原始质量/覆盖限制带入响应；其他来源的合法零必须由各自输入合同证明。

来源匹配：`MATCHED / NO_MATCH_IN_PINNED_INPUT / NO_MATCH_COVERAGE_UNKNOWN / NOT_PROVIDED / READ_FAILED / SCOPE_UNCONFIRMED`。仅 MATCHED 表示正向依据。`positive_sources` 是本次验证输入中的正向来源集合，不等于其他来源已确认不存在；`unmatched_netflow=true` 只表示没有找到合法的另一来源关联，原因必须同时返回。

服务维度：`protocol_relation=EQUAL|DIFFERENT|UNKNOWN|NOT_APPLICABLE`；`port_relation=IN_RANGE|OUT_OF_RANGE|EQUAL|DIFFERENT|UNKNOWN|NOT_APPLICABLE`；`time_relation=OVERLAP|DISJOINT|UNKNOWN`；`role_state=UNKNOWN` 保留源侧模式的角色门禁。汇总 `assessment=OBSERVED_TUPLE_MATCH|MATERIAL_DIFFERENCE|INSUFFICIENT_EVIDENCE`，第一项也不等于监听/服务/公网确认。缺任一必要维度时只能 INSUFFICIENT_EVIDENCE，仍返回已有可比事实。

## 5. 合成请求/响应

以下省略的 hash 值由实际合成产物产生，不写假生产 fingerprint。本节固定示例的字段语义；完整可机读响应在阶段 C 从运行中的 FastAPI 合成链路导出并与 OpenAPI 校验，不能把示例摘录冒充完整响应或已实现 API。

### 新分析请求

```http
POST /api/v1/projects/10000000-0000-4000-8000-000000000001/netflow-datasets/20000000-0000-4000-8000-000000000001/analyses
Idempotency-Key: synthetic-analysis-001
Content-Type: application/json

{"context_revision_id":"30000000-0000-4000-8000-000000000001"}
```

```json
{
  "contract_version": "netflow-correlation-v1",
  "project_id": "10000000-0000-4000-8000-000000000001",
  "analysis_id": "40000000-0000-4000-8000-000000000001",
  "status": "PENDING",
  "pipeline_complete": false,
  "result": null,
  "test_fixture": true
}
```

### 来源固定请求（没有云图也能读 NetFlow，不造假快照）

```json
{
  "network_namespace": "synthetic-edge-a",
  "customer": {"upload_id":"50000000-0000-4000-8000-000000000001","revision_id":null},
  "cloud": null,
  "netflow": {"analysis_id":"40000000-0000-4000-8000-000000000001"},
  "history_run_id": null
}
```

管理员对上面实际返回的 revision ID 另提交 scope-revisions：

```json
{
  "expected_parent_id":"60000000-0000-4000-8000-000000000001",
  "scope_state":"CONFIRMED",
  "evidence":"Synthetic fixture only: selected customer version and SRC dataset describe the same simulated namespace."
}
```

### NetFlow-only 地址详情（仅为未匹配线索）

```json
{
  "contract_version":"netflow-correlation-v1",
  "project_id":"10000000-0000-4000-8000-000000000001",
  "correlation_revision_id":"60000000-0000-4000-8000-000000000002",
  "network_namespace":"synthetic-edge-a",
  "canonical_ip":"2001:db8:10::25",
  "family":6,
  "positive_sources":["NETFLOW"],
  "unmatched_netflow":true,
  "resource_id":null,
  "history_link":null,
  "source_record_count":3,
  "service_object_count":1,
  "presence":{"customer":"NO_MATCH_IN_PINNED_INPUT","cloud":"NOT_PROVIDED","netflow":"MATCHED"},
  "reasons":["CUSTOMER_PINNED_VERSION_NO_MATCH","CLOUD_NOT_PROVIDED","SOURCE_POSITION_ONLY","SAMPLING_UNKNOWN"],
  "reachability":"NOT_VERIFIED",
  "test_fixture":true
}
```

### 有范围命中但协议/时间不明的服务材料

```json
{
  "canonical_ip":"192.0.2.20",
  "protocol_number":6,
  "local_port":443,
  "role_state":"UNKNOWN",
  "customer":{"start_port":440,"end_port":450,"protocol_number":null},
  "cloud":{"protocol_raw":"tcp","protocol_number":6,"port":443,"source_time_timezone":"UNKNOWN"},
  "customer_comparison":{"protocol_relation":"UNKNOWN","port_relation":"IN_RANGE","time_relation":"UNKNOWN"},
  "cloud_comparison":{"protocol_relation":"EQUAL","port_relation":"EQUAL","time_relation":"UNKNOWN"},
  "assessment":"INSUFFICIENT_EVIDENCE",
  "reasons":["CUSTOMER_PROTOCOL_NOT_PROVIDED","SOURCE_TIME_NOT_COMPARABLE","SOURCE_ROLE_UNKNOWN"],
  "reachability":"NOT_VERIFIED"
}
```

### 覆盖不足不清空已读记录

```json
{
  "source":"NETFLOW",
  "state":"INSUFFICIENT_COVERAGE",
  "read_state":"VALID_NONEMPTY",
  "coverage_state":"UNKNOWN",
  "raw_records":8,
  "valid_records":8,
  "source_addresses":4,
  "source_objects":5,
  "candidate_count":0,
  "review_task_count":5,
  "limitations":["SAMPLING_UNKNOWN","VIEW_UNKNOWN","SOURCE_POSITION_ONLY"]
}
```

### 回填状态（字段齐不等于人工通过）

```json
{
  "material_status":"FIELDS_COMPLETE_PENDING_REVIEW",
  "missing_fields":[],
  "field_errors":[],
  "blocked_by":[],
  "review_required":true,
  "task_closed":false,
  "facts_changed":false,
  "external_reachability":"NOT_VERIFIED"
}
```

## 6. 状态、错误与恢复

Analysis 作业状态沿现有独立 worker 模式固定为：`PENDING / RUNNING / SUCCEEDED / SUCCEEDED_WITH_WARNINGS / FAILED / UNKNOWN`。这是新任务状态，不扩展 GovernanceRun 枚举。只有两个成功状态允许 result；输入合法空也能成功。UNKNOWN 表示执行终态未获权威确认。

错误外形沿现有 `{ "detail": { "code": "..." } }`，不返回原行、地址、端口、路径或库异常。初始公开码：

| HTTP | code | 含义/前端动作 |
|---|---|---|
| 401 | 既有认证错误 | 清空账号范围缓存，重新认证 |
| 403 | `netflow_context_admin_required` / `netflow_write_forbidden` | 不重试写；仅有读取角色不能确认空间/反馈 |
| 403 | `correlation_source_access_revoked` | 清除受限组合结果/详情，不保留旧匹配 |
| 404 | `netflow_input_not_found` / `netflow_analysis_not_found` / `correlation_not_found` / `review_task_not_found` | 缺失或跨范围，不回退 latest |
| 409 | `netflow_key_conflict` / `netflow_revision_conflict` | 读取原操作/当前父版本，人工处理；不自动换 key |
| 409 | `netflow_analysis_not_ready` / `netflow_context_revoked` / `correlation_scope_unconfirmed` | 状态不满足；来源自身读取仍与跨源比较分开 |
| 409 | `netflow_retry_not_allowed` | 不是权威 FAILED、处理身份改变或尚无资格；保留原操作，不隐式重新执行 |
| 409 | `netflow_artifact_integrity_failed` / `netflow_import_replay_mismatch` | 不继续展示或导入业务结果，保留原输入，禁止空集降级 |
| 410 | `correlation_source_expired` | 明确到期，不自动切旧云图或缓存 |
| 413 | `netflow_import_too_large` / `netflow_processing_limit` | 有界处理限制，不截断成成功 |
| 415 | `netflow_import_media_type` | 不支持的包格式，不猜解析器 |
| 422 | `netflow_context_invalid` / `netflow_artifact_schema_invalid` / `netflow_import_incomplete` / `netflow_component_version_unsupported` / `netflow_test_fixture_forbidden` | 修正明确输入；不得靠改已有产物 Header/Hash 绕过 |
| 503 | `netflow_execution_unavailable` | 原操作仍可能存在；按原 key 读取/显式 reconcile，不盲目再建 |

实现须保持上述错误语义并与实际 Pydantic/FastAPI 映射一起导出；必要合同变更须先更新批准 Spec，不能在 Issue 或实现中静默改义。这些名称仍不是当前线上已实现能力。

## 7. 前端验收交接

- 从汇总到全部地址、NetFlow-only、源侧服务材料、三来源版本/证据、批次/对象任务和反馈历史，路径均固定 correlation revision / Analysis / task，不借旧 Resource API 消除空值。
- 本方地址与 peers 有明确区分；“对象保留待复核”与“人工任务数”分别计数，不为每个对象复制批次任务。
- 三来源未提供/失败/空/覆盖不足分别显示；无协议、时区、服务角色显示未知。云图端口命中不得显示“确认监听/暴露”。
- 旧 Run、报告、旧 netflow-ledger 与四域云图入口保持原行为；不嵌入独立 HTML，不另建主导航三账平台。
- 回填状态分页固定反馈 UUID：第一页后更正共享依赖，再取第二页/详情，旧筛选集合和总数保持；用户明确切新版本才显示新状态。失败后重试必须明确引用失败 Analysis，未知响应先恢复原 key/Session，不能换 key 盲目再建。
- 验证分页/筛选/排序和返回状态、显式旧版本、Viewer、Admin 空间确认、部分回填更正、归档/撤权/到期、晚到响应与账户切换。
- 实际 1366/1920/390、键盘焦点、双语与主题；没有前端候选时全部记 NOT_RUN。最终记录 backend SHA＋frontend SHA＋组合候选 SHA，真实 API＋合成数据浏览器通过才算联调；mock 通过仅算界面检查。
