# REL-002：受限 PI 报告 Shadow 的可验证效果

## Metadata

- status: CANDIDATE
- revision: r1
- owner: 人类产品决策者（当前对话授权人）
- product_stage: FRAME
- delivery_stage: NOT_STARTED
- delivery_evidence_alignment: ENGINEERING_AHEAD

## Evidence ledger

| Type | Claim | Source and date | Limitation |
|---|---|---|---|
| DECISION | `REL-001/r1` 只作为历史草稿，不再沿用；其本地和远端分支已按人类授权删除。 | 产品塑形对话与 Git 操作，2026-08-17 | 已关闭的 GitHub PR #126 仍是平台历史记录，不能被分支删除抹除。 |
| DECISION | 首个 PI 闭环保持确定性事实权威：Python、SQL 和 Polars 负责比对与 Finding，PI 只基于有界 Evidence 生成结构化报告草稿，Validator 校验失败时回退现有确定性模板。 | 人类产品决策者确认，2026-08-17；`AGENTS.md` | 这是产品与风险边界，不证明 PI 会改善报告效果。 |
| FACT | 当前本地运行环境已有 4 个完成的 GovernanceRun 和 4 份报告，全部为 `DETERMINISTIC_TEMPLATE` / `deterministic-report-v1`。 | 对本地 Compose PostgreSQL 的只读查询，2026-08-17 | 仅代表本地 fixture 环境，不代表客户环境、生产规模或客户价值。 |
| FACT | `origin/main@25b4a37856612f1e2e670e77fe376c81f6ee8fae` 的报告路径由 `compile_report_core`、`select_evidence` 和 `render_report` 确定性生成；当前配置、依赖和 Runner 执行路径没有 PI 报告 Agent 调用。 | `backend/app/domain/governance_runs.py`、`report_core.py`、`report_renderer.py`、`backend/pyproject.toml`、`agent-compose.yml`，查阅于 2026-08-17 | 源码检查证明当前实现边界，不证明未来 PI Runtime 的兼容性或质量。 |
| FACT | 已接受架构把 PI 定位为“基于确定性 Evidence 生成客户可读报告的编译器”，要求有界只读工具、环境变量过滤、结构化校验、最多一次修复和模板回退；v0.1 先使用单 PI 基线。 | `docs/architecture/commercial-function-and-data-architecture-v0.1.md` §6.7、§9、§18，查阅于 2026-08-17 | 架构是实现标准，不是已交付能力或质量证据。 |
| ASSUMPTION | 授权内部评审者在不接触原始数据的情况下，对照确定性报告查看 PI 草稿，能够判断草稿是否提高解释清晰度且没有增加事实核验负担。 | 当前 Release 假设，2026-08-17 | 尚无固定 rubric、样本或评审结果。 |
| UNKNOWN | 可用 PI Runtime、模型、调用方式、资源成本和私有化部署约束是否满足本 Release 的安全及质量边界。 | 截至 2026-08-17 尚未执行兼容性证据行动 | 会改变技术方案、appetite 或是否继续。 |
| UNKNOWN | 哪种报告样本、质量 rubric 和通过阈值足以支持进入客户 Pilot。 | 截至 2026-08-17 尚未设计 Evidence protocol | 阻止 Commitment，不得由实现完成替代。 |

## Release frame

- actor_and_trigger: `ASSUMPTION`：一名经授权的内部报告评审者，在本地或 staging 的 GovernanceRun 完成并发布确定性结果后，打开 Reports 查看本轮报告。
- observed_problem:
  - facts:
    - 当前运行路径只生成固定的确定性报告，PI 草稿数量为 0。
    - 当前不存在 PI 调用、结构化草稿校验或 PI 失败后的运行接线。
  - assumptions:
    - 固定模板不足以让评审者快速理解本轮变化、开放 Finding 与有界 Evidence 之间的关系。
    - 受限 PI 草稿可以改善解释清晰度，而不会增加事实漂移或核验负担。
  - evidence_refs: Evidence ledger 中的本地运行查询、源码检查和架构基线。
- target_outcome: 授权内部评审者能在同一份已完成 Run 上对照权威确定性报告与通过校验的 PI 草稿，判断 PI 是否在保持事实一致的前提下提高解释清晰度，并据此决定是否进入受控客户 Pilot。
- solution_hypothesis: 单 PI 基线只读取有界 EvidenceBundle 或等价只读工具结果，输出固定 StructuredReport Draft；Python Validator 核验事实引用、统计、Finding 状态和禁止变更项，最多允许一次结构化修复，仍失败则回退现有确定性模板。
- smallest_closed_loop: `完成 GovernanceRun → 冻结确定性报告与 Evidence 边界 → PI 生成 StructuredReport Draft → Validator 校验或回退 → Reports 中向授权内部评审者显示生成模式、校验状态及对照内容 → 评审者记录是否进入客户 Pilot的决定`。
- included_scenarios:
  - 本地或 staging 的已完成 GovernanceRun，不接入生产客户数据。
  - 现有确定性报告继续作为权威基线和降级结果。
  - 单 PI、单固定草稿 Schema、最多一次结构化修复。
  - 有界 Evidence、结构化校验、生成模式和失败原因的可追溯记录。
  - 授权内部评审者可见的 shadow 对照，不影响普通客户视图。
- non_goals:
  - 让 PI 计算权威统计、执行资产匹配、创建或修改 Finding。
  - 让 PI 读取原始上传文件、完整 CSV/Parquet、PostgreSQL 凭据、OctoBus Capset 或自由 Shell。
  - 自动处置、审批、写回外部系统或执行其他真实动作。
  - 客户或生产环境启用、自动替换现有报告、PDF 交付或多语言扩展。
  - `pi-workflow`、多 Agent、通用聊天或开放式分析平台。
  - 用实现完成、模型输出流畅或一次演示替代客户价值证据。
- success baseline: 当前 4 份本地报告全部为 `DETERMINISTIC_TEMPLATE`，PI 草稿与 PI 质量评审均为 0。
- primary_signal: 在预先冻结的代表性报告样本和 rubric 上，PI 草稿全部通过事实 Validator，且授权内部评审者认为其解释清晰度相对确定性模板有足够改善，可以支持进入一个受控客户 Pilot；样本数、评分项和通过阈值必须在 Evidence protocol 执行前固定。
- guardrail:
  - 权威统计、Finding 状态、Evidence 引用和处置方向的事实漂移为 0。
  - 原始客户数据、凭据、Token 和未脱敏 Evidence 暴露为 0。
  - PI 不可用、超时、输出非法或修复失败时，确定性模板仍可发布。
  - 未经独立生产批准，不向客户或生产环境启用 PI 输出。
- evidence_window: 一次有界的本地或 staging shadow 评估；具体日历上限、样本和评审时限在 Evidence protocol 前固定。
- minimum_evidence:
  - 冻结且不含真实敏感数据的代表性报告样本，至少覆盖零 Finding 与非零 Finding 行为；最终样本量在协议中固定。
  - PI Runtime、模型、Prompt、工具边界和 StructuredReport Schema 的可复现身份。
  - 每份草稿的 Validator、单次修复、回退和耗时结果。
  - 草稿与确定性事实逐项比对结果。
  - 授权内部评审者按预先固定 rubric 给出的盲区、核验负担和继续或停止理由。
  - 资源成本、失败模式和私有化运行限制。
- risks:
  - value:
    - PI 文案可能更流畅但没有提高理解或决策质量。
    - 内部评审偏好不能证明客户价值或持续使用。
  - usability:
    - 对照视图可能让评审者误把草稿当作权威结果。
    - 生成模式、回退状态或 Evidence 引用可能表达不清。
  - feasibility:
    - PI Runtime、模型或结构化输出能力可能无法稳定满足固定 Schema。
    - 有界上下文可能不足，扩大上下文又可能突破安全边界。
  - viability:
    - 私有化模型资源、延迟或运维成本可能超过可接受 appetite。
    - 客户部署环境可能不允许所需 Runtime 或模型服务。
  - security_and_privacy:
    - Runner 环境过滤、Run 级只读 Token 或日志脱敏失败可能泄漏受保护信息。
    - Prompt injection 或无 Evidence 推断可能产生误导性草稿。
- appetite: 只评估一个单 PI 报告 shadow、一个固定 StructuredReport Schema、一个本地或 staging 环境和一次有界样本评审；最多一次结构化修复；不建设多 Agent、生产启用或客户数据接入。时间、资源成本和样本上限必须在 Evidence protocol 前固定。
- blocking_unknowns:
  - 可用 PI Runtime、模型和私有化运行方式。
  - 最小有界 Evidence 工具契约及 Run 级 Token 生命周期。
  - 代表性样本、质量 rubric、通过与停止阈值。
  - 授权内部评审者及其独立性要求。
  - 可接受的延迟、资源成本和失败率。
  - shadow 内容在 Reports 中的隔离、标识与审计方式。
- false_positive_completion: Reports 页面出现一段 PI 文案，或模型在单个演示样本上输出成功，但没有固定 Evidence 边界、事实 Validator、确定性回退、可复现身份和预先固定的对照评审结果。

## Controlled release boundary

- authority_and_scope: 人类产品决策者于 2026-08-17 只批准创建本 Release frame 及其预交付分支/PR；本 revision 不授权实现、merge、客户数据处理、客户或生产启用。
- protected_assets_and_data:
  - PostgreSQL 凭据与结构化业务事实库。
  - CustomerUpload 原始文件、完整 Artifact 与未脱敏 Evidence。
  - OctoBus Credential、Capset 和外部系统能力。
  - agent-compose、PI 或模型服务 Token、Prompt 输入和运行日志。
- blast_radius: 首个证据行动仅限本地或 staging、冻结的非敏感样本和授权内部评审者；确定性报告仍是客户可见权威结果。
- pre_release_verification:
  - 证明 PI 进程环境不含数据库连接串、OctoBus Credential 或 Action Capset。
  - 证明工具只返回 Run 级有界 Evidence，Token 在 Session 后失效。
  - 对固定样本执行事实一致性、非法引用、状态误述、Prompt injection、超时和模型不可用测试。
  - 证明任一 PI 失败均不会阻断确定性结果和模板报告。
- rollback_or_recovery: 禁用或绕过 PI shadow 路径，继续发布现有 `DETERMINISTIC_TEMPLATE`；触发条件包括事实漂移、敏感信息暴露、Validator 绕过、不可接受失败率或资源消耗。恢复后重新验证同一 Run 的确定性报告可读且未被修改。
- approval_owners:
  - Release Commitment：人类产品决策者。
  - Admission 激活：人类确认独立审阅后的精确计划。
  - 客户或生产启用、停用或回滚：明确指定的人工生产负责人。
- staged_release: `离线/fixture 验证 → 本地或 staging shadow → 授权内部评审 → 单独的人类客户 Pilot 决定 → 单独的人类生产决定`；本 revision 只允许推进到协议设计，不授权任何运行阶段。
- smoke_and_stop_conditions:
  - smoke: 同一冻结 Run 的确定性报告保持字节与事实稳定，PI 草稿带明确 shadow 标识，Validator 与回退结果可追溯。
  - stop: 任一敏感数据暴露、权威事实漂移、PI 获得禁止权限、确定性回退失败或活动安全事件立即停止。
- audit_evidence: 后续协议必须固定保留 Runtime/模型、Prompt 与 Schema 版本、Evidence 引用身份、输入边界摘要、草稿 Hash、Validator/修复/回退结果、耗时与人工评审身份；不得保存凭据或未脱敏原文。

## Readiness

尚未执行六项 Commitment readiness tests：

1. actor、trigger 和当前工作流只有内部候选假设，未通过证据验证。
2. 当前替代方式存在的事实已知，但“固定模板解释不足”仍是未验证假设。
3. 最小 shadow 闭环已定义，尚未证明可运行。
4. 主要信号和 guardrail 可观察，但样本、rubric、阈值和窗口尚未固定。
5. 最高风险尚未通过兼容性与质量证据行动验证。
6. non-goals、false-positive completion 和主要控制边界已明确，但不能补足前五项。

当前 verdict 不是 `READY_TO_COMMIT`。

## Commitment

- decision: NONE
- committed_revision: NONE
- note: `CANDIDATE r1` 仅冻结待验证 Frame；它不授权 Delivery Spec、tickets、实现、Admission 或运行 PI。

## Delivery trace

- candidate_base: `origin/main@25b4a37856612f1e2e670e77fe376c81f6ee8fae`
- candidate_branch: `product/rel-002-pi-report-shadow-r1`
- artifact_path: `docs/product/releases/rel-002-bounded-pi-report-shadow.md`
- accepted_delivery_base: NONE；只有本 revision 的精确 blob 进入 `origin/main` 后才成为权威 Release revision。
- spec: NONE
- tickets: NONE

## Release record

暂无；本 Release 未 committed、未 delivered、未 released，也未向客户或生产启用。

## Outcome review

不适用；只有后续 Release Record、固定 evidence window 和实际结果证据齐备后才能评价 outcome。
