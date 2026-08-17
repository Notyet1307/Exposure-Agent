# REL-002：受限 PI 报告 Shadow 的可验证效果

## Metadata

- status: CANDIDATE
- revision: r2
- owner: 人类产品决策者（当前对话授权人）
- product_stage: FRAME
- delivery_stage: NOT_STARTED
- delivery_evidence_alignment: ENGINEERING_AHEAD

## Evidence ledger

| Type | Claim | Source and date | Limitation |
|---|---|---|---|
| DECISION | `REL-001/r1` 只作为历史草稿，不再沿用；其本地和远端分支已按人类授权删除。 | 产品塑形对话与 Git 操作，2026-08-17 | 已关闭的 GitHub PR #126 仍是平台历史记录，不能被分支删除抹除。 |
| FACT | `REL-002/r1` 的精确 blob `e74543712f4e6a6ff61f48e7591d00b07cc231ee` 已通过 PR #129 进入 `origin/main@18536329024e36932d11312739adf097ca7cf744`。 | Git 与 GitHub PR #129，2026-08-17 | 只证明 Frame 已持久化，不证明 PI 能力或报告效果。 |
| DECISION | 首个 PI 闭环保持确定性事实权威：Python、SQL 和 Polars 负责比对与 Finding，PI 只基于有界 Evidence 生成结构化报告草稿，Validator 校验失败时回退现有确定性模板。 | 人类产品决策者确认，2026-08-17；`AGENTS.md` | 这是产品与风险边界，不证明 PI 会改善报告效果。 |
| DECISION | 开发和测试使用百智云 DeepSeek V4 Flash；生产使用满足同一输入、输出、权限和校验契约的内部模型，不把生产绑定到开发 Provider。 | 人类产品决策者确认，2026-08-17 | 内部生产模型的实际兼容性仍须在生产启用前独立验证。 |
| DECISION | 模型可以原样接收经授权、Run 级、有界且为报告所必需的内部敏感业务 Evidence，包括实际 IP、资产标识和 Finding 内容；不得接收凭据、Token、密码、原始上传文件、完整数据库或无界数据。 | 人类产品决策者确认，2026-08-17；`AGENTS.md`；架构 §9.2–§9.4、§12.2 | 内部使用和内部模型不取消最小权限、凭据隔离、审计及防数据外泄边界。 |
| DECISION | 开发验证不设置美元成本上限；仍固定样本、证据窗口、修复次数和停止条件，以保证可复现性与防止失控。 | 人类产品决策者确认，2026-08-17 | 不是生产容量、并发或配额决策。 |
| FACT | 百智云 OpenAI 网关模型目录 `https://ai-api-gateway.app.baizhi.cloud/api/openai/models` 的授权只读请求返回 HTTP 200 和 41 个模型，其中包含 `deepseek-v4-flash`。 | 百智云网关模型目录，live-verified，访问于 2026-08-17 | 目录存在不证明 Responses API、结构化输出、稳定性或报告质量兼容。 |
| FACT | 本机 PI 0.84.2 支持 SDK 和 JSONL RPC；RPC 可禁用 Session、全部工具、Extensions、Skills、Prompt Templates 和 Context Files，并显式选择 Provider/Model。 | 本机 PI 0.84.2 `README.md`、`docs/sdk.md`、`docs/rpc.md` 与只读 RPC 能力探测，2026-08-17 | 主机能力不证明当前 Runner 镜像已经包含或正确隔离 PI。 |
| FACT | 当前 Runner 镜像具有 Node 和 Python，但没有 `pi` 可执行文件；现有运行路径没有 PI 调用。 | `backend/Dockerfile.runner`、运行镜像只读检查及源码检查，2026-08-17 | 需要后续 Delivery 才能正式接线；本 Release 的 Evidence 行动只能使用隔离的临时探针。 |
| FACT | 当前本地运行环境已有 4 个完成的 GovernanceRun 和 4 份报告，全部为 `DETERMINISTIC_TEMPLATE` / `deterministic-report-v1`。 | 对本地 Compose PostgreSQL 的只读查询，2026-08-17 | 仅代表本地 fixture 环境，不代表客户环境、生产规模或客户价值。 |
| ASSUMPTION | 授权内部评审者对照确定性报告查看 PI 草稿，能够判断草稿是否提高解释清晰度且没有增加事实核验负担。 | 当前 Release 假设，2026-08-17 | 尚未执行固定 rubric 的评审。 |
| UNKNOWN | `baizhi-responses/deepseek-v4-flash` 是否能在固定 Evidence、Prompt 和 Schema 下稳定产生事实一致的草稿。 | 截至 2026-08-17 尚未执行内容调用 | 是当前 Evidence protocol 要回答的最高风险未知。 |

## Release frame

- actor_and_trigger: `ASSUMPTION`：一名经授权的内部报告评审者，在本地或 staging 的 GovernanceRun 完成并发布确定性结果后，打开 Reports 查看本轮报告。
- observed_problem:
  - facts:
    - 当前运行路径只生成固定的确定性报告，PI 草稿数量为 0。
    - 百智云目录存在目标模型，但当前 Runner 尚未包含或调用 PI。
  - assumptions:
    - 固定模板不足以让评审者快速理解本轮变化、开放 Finding 与有界 Evidence 之间的关系。
    - 受限 PI 草稿可以改善解释清晰度，而不会增加事实漂移或核验负担。
  - evidence_refs: Evidence ledger 中的运行查询、源码与镜像检查、PI 官方本地文档和百智云目录探测。
- target_outcome: 授权内部评审者能在同一份已完成 Run 上对照权威确定性报告与通过校验的 PI 草稿，判断 PI 是否在保持事实一致的前提下提高解释清晰度，并据此决定是否进入受控内部 Pilot。
- solution_hypothesis: 单 PI 基线只读取有界 EvidenceBundle 或等价只读工具结果，输出固定 StructuredReport Draft；Python Validator 核验事实引用、统计、Finding 状态和禁止变更项，最多允许一次结构化修复，仍失败则回退现有确定性模板。
- smallest_closed_loop: `完成 GovernanceRun → 冻结确定性报告与 Evidence 边界 → PI 生成 StructuredReport Draft → Validator 校验或回退 → Reports 中向授权内部评审者显示生成模式、校验状态及对照内容 → 评审者记录是否进入内部 Pilot 的决定`。
- included_scenarios:
  - 本地或 staging 的已完成 GovernanceRun，不接入生产动作路径。
  - 经授权、Run 级、有界的内部敏感业务 Evidence 可以保留实际业务值，以免脱敏破坏报告语义。
  - 现有确定性报告继续作为权威基线和降级结果。
  - 单 PI、单固定草稿 Schema、最多一次结构化修复。
  - 有界 Evidence、结构化校验、生成模式和失败原因的可追溯记录。
  - 授权内部评审者可见的 shadow 对照，不影响普通客户视图。
- non_goals:
  - 让 PI 计算权威统计、执行资产匹配、创建或修改 Finding。
  - 让 PI 读取凭据、Token、密码、原始上传文件、完整 CSV/Parquet、完整数据库、PostgreSQL 连接信息、OctoBus Capset 或自由 Shell。
  - 自动处置、审批、写回外部系统或执行其他真实动作。
  - 生产启用、自动替换现有报告、PDF 交付或多语言扩展。
  - `pi-workflow`、多 Agent、通用聊天或开放式分析平台。
  - 用实现完成、模型输出流畅或一次演示替代内部评审证据。
- success baseline: 当前 4 份本地报告全部为 `DETERMINISTIC_TEMPLATE`，PI 草稿与 PI 质量评审均为 0。
- primary_signal: 在 E1 冻结的两类报告样本上，6 份 PI 草稿最终全部通过事实 Validator，至少 5 份首次通过，且授权内部评审者认为两类样本的解释清晰度均优于确定性模板、事实核验负担不增加。
- guardrail:
  - 权威统计、Finding 状态、Evidence 引用和处置方向的事实漂移为 0。
  - 未授权数据、凭据、Token、密码、原始 Artifact 和无界上下文进入模型或日志为 0。
  - 经授权且为报告必需的 Run 级敏感业务 Evidence 不因脱敏而丢失语义。
  - PI 不可用、超时、输出非法或修复失败时，确定性模板仍可发布。
  - 未经独立生产批准，不向生产环境启用 PI 输出。
- evidence_window: E1 从首次内容请求开始最多 45 分钟；仅用于固定样本的开发 shadow 评估，不设置美元成本上限。
- minimum_evidence:
  - 两个冻结且经授权的 Run 级报告样本：一个零 Finding，一个包含当前差异、开放积压和生命周期变化的混合 Finding 样本。
  - PI Runtime、Provider、Model、Prompt、工具边界和 StructuredReport Schema 的可复现身份。
  - 每份草稿的 Validator、单次修复、回退和耗时结果。
  - 草稿与确定性事实逐项比对结果。
  - 授权内部评审者按固定 rubric 给出的盲区、核验负担和继续或停止理由。
  - Provider/API 失败模式及生产内部模型需要复验的兼容边界。
- risks:
  - value:
    - PI 文案可能更流畅但没有提高理解或决策质量。
    - 单名内部评审者偏好不能证明客户价值或持续使用。
  - usability:
    - 对照视图可能让评审者误把草稿当作权威结果。
    - 生成模式、回退状态或 Evidence 引用可能表达不清。
  - feasibility:
    - 百智云目标模型可能无法稳定满足 Responses API 或固定 Schema。
    - 有界上下文可能不足，扩大上下文又可能突破最小权限边界。
  - viability:
    - 开发 Provider 的结果可能无法迁移到生产内部模型。
    - 私有化模型资源、延迟或运维约束仍需生产前独立验证。
  - security_and_privacy:
    - Runner 环境过滤、Run 级只读 Token 或日志控制失败可能泄漏凭据或超范围数据。
    - Prompt injection 或无 Evidence 推断可能产生误导性草稿。
- appetite: 只评估一个单 PI 报告 shadow、一个固定 StructuredReport Schema、两个样本各三次独立生成和一次有界内部评审；每份非法草稿最多修复一次；证据窗口 45 分钟；不设置美元成本上限，不建设多 Agent、生产启用或外部动作。
- blocking_unknowns:
  - 百智云目标模型的 Responses API、Schema、稳定性和事实一致性。
  - 授权内部评审者是否认为草稿提高解释清晰度且不增加核验负担。
  - 未来生产内部模型对同一契约的兼容性。
  - 正式 Run 级 Evidence Token、Reports shadow 隔离和审计接线的 Delivery 设计。
- false_positive_completion: PI 输出成功或页面出现一段文案，但没有固定 Evidence 边界、事实 Validator、确定性回退、可复现身份和预先固定的对照评审结果。

## Controlled release boundary

- authority_and_scope: 人类产品决策者于 2026-08-17 批准 `REL-002/r2` 协议边界及其预交付分支/PR；本 revision 不授权模型内容调用、实现、merge、生产启用或外部动作。
- protected_assets_and_data:
  - 可以进入模型：经授权、Run 级、有界且为报告必需的内部业务 Evidence，包括实际 IP、资产标识和 Finding 内容。
  - 不得进入模型：数据库凭据、密码、Token、OctoBus Credential/Capset、原始上传文件、完整 Artifact、完整数据库或无界查询结果。
  - 不得进入 Git 或普通日志：完整模型上下文、凭据、原始文件和未经批准的业务数据副本。
- blast_radius: 首个证据行动仅限本地或 staging、两个冻结的内部 Run 级样本和一名授权内部评审者；确定性报告仍是权威结果。
- pre_release_verification:
  - 证明 PI 进程环境不含数据库连接串、OctoBus Credential 或 Action Capset。
  - 证明输入只含已选 Run 的有界 Evidence，且任何临时 Token 在 Session 后失效。
  - 对固定样本执行事实一致性、非法引用、状态误述、Prompt injection、超时和模型不可用测试。
  - 证明任一 PI 失败均不会阻断确定性结果和模板报告。
- rollback_or_recovery: 禁用或绕过 PI shadow 路径，继续发布现有 `DETERMINISTIC_TEMPLATE`；触发条件包括事实漂移、超范围数据暴露、Validator 绕过、不可接受失败率或资源失控。恢复后重新验证同一 Run 的确定性报告可读且未被修改。
- approval_owners:
  - Evidence 执行：人类产品决策者对权威 r2 的单独授权。
  - Release Commitment：人类产品决策者。
  - Admission 激活：人类确认独立审阅后的精确计划。
  - 生产启用、停用或回滚：明确指定的人工生产负责人。
- staged_release: `目录与契约探测 → 固定样本开发 shadow → 授权内部评审 → 单独的人类内部 Pilot 决定 → 使用生产内部模型重新验收 → 单独的人类生产决定`；本 revision 只允许推进到协议持久化。
- smoke_and_stop_conditions:
  - smoke: 同一冻结 Run 的确定性报告保持事实稳定，PI 草稿带明确 shadow 标识，Validator 与回退结果可追溯。
  - stop: 任一凭据泄漏、未授权数据暴露、权威事实漂移、PI 获得禁止权限、确定性回退失败或活动安全事件立即停止。
- audit_evidence: E1 只保留 Runtime/Provider/Model、Prompt 与 Schema Hash、Evidence 输入边界摘要与 Hash、草稿 Hash、Validator/修复/回退结果、耗时和人工评审身份；不把完整模型上下文、凭据或原始 Artifact 写入 Git 或普通日志。

## Current evidence protocol

### E1 百智云 DeepSeek V4 Flash 报告 Shadow 兼容性与质量评估 v1

- protocol_id: `E1-baizhi-deepseek-v4-flash-shadow-v1`
- protocol_status: `DESIGNED_NOT_AUTHORIZED`
- evidence_class: `CONTROLLED_INTERNAL_MODEL_SHADOW`
- decision_question: PI 0.84.2 通过百智云 `deepseek-v4-flash`，能否只基于固定的 Run 级 Evidence 生成事实一致、Schema 合法且比确定性模板更清晰的报告草稿，从而值得进入受控内部 Pilot？
- riskiest_assumption: 目标模型在有界上下文和无内置工具条件下仍能稳定遵守结构化报告契约，不引入事实漂移或额外核验负担。
- participant_or_source:
  - 模型：百智云 OpenAI 网关 `baizhi-responses/deepseek-v4-flash`。
  - 样本：两个经授权、冻结的内部 Run 级报告事实与 EvidenceBundle；若当前本地数据不具备所需形态，使用同一确定性契约生成的内部 fixture，但不得据此声称真实业务质量已验证。
  - 评审：一名未参与草稿生成的授权内部报告评审者。

#### Fixed runtime identity

- pi_version: `0.84.2`
- transport: `JSONL RPC`
- provider_id: `baizhi-responses`
- model_id: `deepseek-v4-flash`
- api: `openai-responses`
- base_url: `https://ai-api-gateway.app.baizhi.cloud/api/openai`
- production_model_rule: 生产内部模型不要求同名，但必须重新通过同一输入边界、StructuredReport Schema、Validator、回退和评审协议。
- cost_rule: 不设置美元成本上限；记录 Provider 返回的 token、耗时和 cost 字段（如有），仅作证据，不作为本轮停止条件。

#### Scope and sample

- 选择一个完整输入且零 Finding 的冻结样本。
- 选择一个同时包含当前差异、开放积压和至少一种生命周期变化的冻结混合样本。
- 每个样本使用全新 ephemeral PI Session 独立生成 3 次，共 6 次初始生成。
- 每份未通过 Validator 的草稿最多进行 1 次结构化修复；修复只接收原 Schema、原有界输入和 Validator 错误码，不扩大 Evidence。
- 额外执行一次本地强制非法草稿或模型失败路径，证明系统选择确定性模板；该项不需要真实模型生成。
- 从首次内容请求开始的证据窗口为 45 分钟；超过窗口返回未完成，不扩大样本或延长阈值。

#### Input and credential boundary

- 模型输入可以保留经授权样本中的实际 IP、资产标识、Finding 内容和 Evidence 引用，不要求为提高形式安全而破坏业务语义。
- 输入只能来自所选 Run 的冻结报告事实和有界 EvidenceBundle；不得追加跨 Run 全库查询或完整来源文件。
- 不向模型传递数据库连接串、密码、Token、OctoBus Credential/Capset、原始上传文件或完整 Artifact。
- 使用临时权限为 `0700` 的 PI agent 目录；模型配置只引用运行时环境变量，不复制或挂载现有 `auth.json`，执行结束后删除临时目录。
- PI 子进程使用环境变量 allowlist；不得继承 PostgreSQL、OctoBus、agent-compose 或应用密钥。
- 敏感业务输入与完整模型输出保存在获批的内部临时位置，默认不进入 Git、Session 文件或普通日志；协议结果只记录 Hash、错误码和脱敏摘要。

#### PI process contract

- 使用 `--mode rpc --no-session --no-tools --no-extensions --no-skills --no-prompt-templates --no-context-files --no-approve`。
- 设置 `PI_OFFLINE=1`、`PI_TELEMETRY=0`，禁用启动更新、包检查和遥测。
- 每次生成使用新进程或已证明状态为空的新 Session；不得复用其他用户对话历史。
- RPC 客户端只按 LF 拆分 JSONL，并等待 `agent_settled` 或明确错误；超时后发送 abort 并终止子进程。
- Provider/Model、API、Base URL 或 PI 版本与固定身份不一致时，不发送报告内容并返回 `E1_STOP_IDENTITY_DRIFT`。

#### StructuredReport Draft contract

草稿必须是单个 JSON 对象且拒绝额外字段，至少包含：

- `report_identity`：Run、Project、报告契约和生成模式引用；
- `executive_summary`：只解释确定性摘要，不新增数字；
- `input_completeness`：逐来源完整性与 Snapshot 引用；
- `ip_consistency_explanation`：匹配数和两类 Finding 数的客户可读解释；
- `lifecycle_changes`：本轮 OPENED、REOPENED、CLOSED 的有界解释；
- `open_backlog_explanation`：截至本轮的开放积压解释；
- `evidence_examples`：只引用输入中存在的 Evidence ID；
- `directions_and_limitations`：保持确定性处置方向及限制；
- `provenance`：Provider、Model、Prompt/Schema 版本和输入 Hash。

PI 不得新增或修改严重性、置信度、责任、根因、Finding 状态、统计、推荐动作或关闭结论。

#### Validator and repair

Validator 在接受草稿前逐项检查：

1. JSON 与固定 Schema 合法且无额外字段；
2. Run、Project、Finding、Evidence 和 Snapshot 引用均存在于冻结输入；
3. 所有数字、Finding 类型、状态、Transition 和处置方向与确定性报告完全一致；
4. “未观测”没有被表述为“不存在”或“已关闭”；
5. 没有无 Evidence 的新风险、根因、严重性、置信度、责任或动作；
6. Evidence 中的指令性文本没有被当作系统指令执行；
7. 输出不包含凭据、Token、密码或输入边界外的数据。

首次失败只允许一次修复；修复后仍失败则记录错误码并选择确定性模板，不接受部分草稿。

#### Internal review rubric

评审者在不知道具体生成轮次的情况下，分别对两类样本比较确定性模板与已通过 Validator 的 PI 草稿：

- 是否更快理解本轮输入是否完整；
- 是否更清楚理解匹配、当前差异、生命周期变化和开放积压的关系；
- 是否能从每个解释定位到对应 Evidence；
- 是否产生需要额外核验的模糊、夸大或新判断；
- 是否愿意让该 shadow 进入下一次受控内部 Pilot。

每个样本必须得到“解释更清晰”且“事实核验负担不增加”；口头偏好必须附一个具体改善点和一个仍存在的限制。

#### Evidence to capture

- PI、Provider、Model、API 和 Base URL 身份；
- 两个冻结输入的契约版本与 Hash，不复制完整输入到 Release artifact；
- Prompt、Schema 和 Validator 版本与 Hash；
- 每次初始生成与修复的开始、结束、耗时、终止原因和输出 Hash；
- 首次及最终 Validator 结果、错误码和是否回退；
- Provider 返回的 token/cost 字段（如有），不设成本阈值；
- 内部评审 rubric 结果、具体改善点、限制和污染；
- 任何身份漂移、超范围数据、凭据暴露、活动 Incident 或停止条件。

#### Pass, rework, fail, and stop thresholds

仅当以下条件全部成立时返回 `E1_PASS`：

1. 6/6 最终草稿通过全部 Validator，且至少 5/6 初始草稿无需修复即通过；
2. 权威事实漂移、非法引用、禁止的新判断、凭据泄漏和输入边界外数据均为 0；
3. 强制失败路径可靠选择现有确定性模板，且权威报告未被修改；
4. 两类样本均被内部评审者判定解释更清晰、事实核验负担不增加，并记录具体理由；
5. 全部行动在 45 分钟窗口内完成，Provider/Model/PI 身份没有漂移。

其他 verdict：

- `E1_REWORK_CONTRACT`：模型可调用，但 Schema、Prompt、Validator 或单次修复契约需要调整；不得扩大 Evidence 来掩盖失败。
- `E1_FAIL_QUALITY`：事实可守住，但首次通过率、清晰度或核验负担未达阈值；停止进入 Pilot。
- `E1_FAIL_COMPATIBILITY`：目标模型或 Responses API 无法完成固定调用契约；返回兼容性证据，不切换模型获取通过结果。
- `E1_INCOMPLETE`：45 分钟内未完成固定样本；不得临时缩减分母或延长窗口。
- `E1_STOP_IDENTITY_DRIFT`：PI、Provider、Model、API 或 Base URL 与固定身份不一致。
- `E1_STOP_SAFETY`：凭据泄漏、未授权或无界数据进入模型/日志、PI 获得禁止权限、确定性回退失败或活动 Incident。

任一 verdict 都是有效证据结果；不得为了获得 `E1_PASS` 改模型、扩大上下文、跳过 Validator 或重写阈值。

#### Return format

只允许将以下结果块写回后续 Release revision：

```yaml
protocol_id: E1-baizhi-deepseek-v4-flash-shadow-v1
executed_at: <ISO-8601>
pi_version: <value>
provider_id: <value>
model_id: <value>
api: <value>
base_url: <non-secret URL>
input_hashes: []
prompt_hash: <sha256>
schema_hash: <sha256>
validator_hash: <sha256>
initial_runs: 6
initial_passes: <number>
repair_attempts: <number>
final_passes: <number>
fallback_verified: <true | false>
fact_drift_count: <number>
illegal_reference_count: <number>
credential_exposure_count: <number>
out_of_boundary_data_count: <number>
elapsed_minutes: <number>
usage_reported: <summary | unavailable>
review:
  zero_finding_clearer: <true | false | NOT_RUN>
  mixed_finding_clearer: <true | false | NOT_RUN>
  verification_burden_increased: <true | false | NOT_RUN>
  concrete_improvements: []
  limitations: []
verdict: E1_PASS | E1_REWORK_CONTRACT | E1_FAIL_QUALITY | E1_FAIL_COMPATIBILITY | E1_INCOMPLETE | E1_STOP_IDENTITY_DRIFT | E1_STOP_SAFETY
readiness_effect: <one bounded statement>
```

E1 只有在本 r2 精确 blob 进入 `origin/main`、样本授权与边界未漂移且人类再次明确授权内容调用后才能执行。本 revision 的写入或 merge 不等于模型调用授权。

## Readiness

尚未执行六项 Commitment readiness tests：

1. 内部评审 actor 和 trigger 已在 Frame 中限定，但实际工作流尚未通过 E1 观察。
2. 当前替代方式是确定性模板；“解释不足”仍是未验证假设。
3. 最小 shadow 闭环和状态交接已定义，尚未证明可运行。
4. 主要信号、guardrail、样本、rubric、45 分钟窗口及最小证据已固定，等待执行。
5. 最高风险由 E1 覆盖，但尚无结果。
6. non-goals、false-positive completion、权限、恢复和停止边界已明确。

当前 verdict 不是 `READY_TO_COMMIT`。

## Commitment

- decision: NONE
- committed_revision: NONE
- note: `CANDIDATE r2` 只冻结 E1 协议；它不授权模型内容调用、Delivery Spec、tickets、实现、Admission 或生产启用。

## Delivery trace

- r1_accepted_base: `origin/main@18536329024e36932d11312739adf097ca7cf744`
- r1_blob: `e74543712f4e6a6ff61f48e7591d00b07cc231ee`
- r2_candidate_base: `origin/main@18536329024e36932d11312739adf097ca7cf744`
- r2_candidate_branch: `product/rel-002-evidence-r2`
- artifact_path: `docs/product/releases/rel-002-bounded-pi-report-shadow.md`
- r2_accepted_delivery_base: NONE；只有本 r2 的精确 blob 进入 `origin/main` 后才成为权威 revision。
- spec: NONE
- tickets: NONE

## Release record

暂无；本 Release 未 committed、未 delivered、未 released，也未向生产启用。

## Outcome review

不适用；只有后续 Release Record、固定 evidence window 和实际结果证据齐备后才能评价 outcome。
