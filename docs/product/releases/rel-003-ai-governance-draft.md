# REL-003：Operator 审核的 AI 治理草稿

## Metadata
- status: COMMITTED
- revision: r1
- owner: product owner
- product_stage: COMMIT
- delivery_stage: SPEC_AUTHORIZED
- delivery_evidence_alignment: SHADOW_PASS
- delivery_contract_revision: P1-P8

## Evidence ledger

| Type | Claim | Source | Limitation |
|---|---|---|---|
| FACT | 当前系统发布不可变确定性报告、Finding 与有界 Evidence；模型 Agent 尚未实现。 | `main@1d9605875fae287b83ffed9f13ec366acd86059d` | 仓库事实不能单独证明用户价值。 |
| DECISION | 下一阶段必须包含 AI 报告解读与处置建议。 | Product owner，本轮规划会话 | 该决定只授权本 Release 的产品方向。 |
| DECISION | Operator 单人审核、按需生成、仅覆盖未观测资产、每份草稿最多 8 个 Evidence-backed Finding。 | Product owner，本轮规划会话 | 不授权自动审批、外部写回或复扫。 |
| FACT | `REL-003/r1-shadow-review-once-v5` 在固定非客户合成报告上通过：8/8 建议为 `DIRECT_ACCEPT`，13/13 claim 为 `SUPPORTED`，无实质事实修正、无 unsupported fact、无 Finding 修改、无未授权外部副作用。 | v5 redacted evaluation SHA-256 `8ccfff1d579a63cec5ee678784bafb1205b06bce0e531e3c839667c868c30e1f`；输入报告 SHA-256 `77dbfc444994e2ce25589eb6ae0d80bbf7043fb58904d15e0aee6d814dd7f164` | 一份合成报告、一名 Operator、一次 Codex 验证；不证明所有客户模型质量。 |
| FACT | Operator 用约 20 分钟完成审核，并判断 AI 将报告摘要、8 个 Finding、Evidence 引用和待确认项组织成可直接审核草稿，减少了逐项整理工作。 | `current-session-authorizer` 对固定输出 SHA-256 `e227fdd52e9a2a2d84945353700b26d5e34223be08e60827a718193098b577e3` 的审核记录 | 单次自报观察，没有 report-only 对照计时，不能证明普遍效率提升。 |
| DECISION | Codex/OpenAI 仅用于本地非客户合成验证；生产环境由 Pi 调用客户环境内、客户控制的 OpenAI-compatible 模型 API，客户数据不得 fallback 到 Codex/OpenAI 或其他外部模型。 | Product owner，本轮 Commitment 决定 | 每个客户模型仍须通过准入验证。 |
| DECISION | 生产模型地址和凭据由客户运维通过部署 Secret 注入，不进入数据库、Prompt 或日志；客户承担内部推理容量，不引入外部按量模型预算。 | Product owner，本轮 Commitment 决定 | 客户侧算力、容量和运维成本仍由客户管理。 |
| DECISION | Delivery contract P1–P8 固定 Operator 选择、独立 Session、幂等与失败语义、PostgreSQL 持久化、审核状态、授权与审计、模型准入及确定性降级。 | Product owner，2026-08-20 Delivery Spec shaping confirmation | 仅授权 Delivery Spec；不授权创建 Issue 或实现。 |

## Release frame

- actor_and_trigger: Project Operator 打开包含未观测资产的已发布确定性报告，并明确请求生成 AI 草稿。
- observed_problem: Operator 需要自行把报告摘要、逐 Finding Evidence、处置方向和待确认项整理成审核材料；影子评审表明有界 AI 草稿可减少这部分逐项整理工作。
- target_outcome: Operator 能基于可追溯事实，更高效地形成补充扫描目标并重新扫描的审核结论。
- solution_hypothesis: 有界 AI 草稿能解释报告并提供 Evidence-backed 处置建议，同时不改变权威事实。
- smallest_closed_loop: 报告发布 → Operator 按需生成 → AI 返回结构化草稿 → Operator 接受、编辑或拒绝；失败时确定性报告保持可用。
- included_scenarios:
  - 只处理 `UNOBSERVED_ASSET`；
  - 报告摘要中的事实必须引用确定性报告字段；
  - 最多处理 8 个已有有界 Evidence 的 Finding；
  - 每项包含 Finding ID、Evidence 引用、复扫建议、待确认项和局限；
  - Operator 可接受、编辑或拒绝；
  - 模型失败时确定性报告继续可用；
  - 每个客户内部模型在启用前通过同一结构化、可用性和可追溯性准入门禁。
- non_goals:
  - 未报备资产；
  - 自动审批；
  - 修改 Finding 或权威统计；
  - 写回客户系统或暴露面系统；
  - 自动触发复扫；
  - 默认多 Agent 路径；
  - 生产环境调用 Codex/OpenAI 或任何外部模型 fallback。
- success_baseline: 确定性报告提供权威事实，但 Operator 需要自行组织摘要、逐项 Evidence、建议和待确认项；本轮未测量 report-only 对照耗时。
- primary_signal: 至少 75% 的 Finding 建议被 Operator 直接接受或仅作文字编辑。
- observed_signal: 固定影子评审中 8/8 建议被直接接受，可用率 100%；Operator 报告有明确整理价值。
- guardrail:
  - 事实与 Evidence 可追溯率为 100%；
  - 零虚构统计；
  - 零 Finding 修改；
  - 零未授权外部副作用。
- evidence_window: 一次有界影子评审，已完成。
- minimum_evidence: 一名合格 Operator 对一份固定报告和 8 个 Finding 完成审核，已满足。
- risks:
  - value: 当前仅有一次自报增量价值观察，普遍效率收益仍须在交付后观察；
  - usability: 客户内部模型能力不同，必须逐模型准入；
  - feasibility: Pi 调用和结构化捕获路径已验证，但 Codex 结果不能替代客户模型准入；
  - viability: 无外部按量模型预算，客户负责内部推理容量和运行成本。
- blocking_unknowns: 无 Release Commitment 阻塞项；具体客户模型只有通过准入门禁才可启用。
- false_positive_completion: 成功生成文本，但建议不可用、缺少引用、需要实质事实纠正，影响权威事实，或未通过客户模型准入即启用。

## Completed evidence protocol

- decision_question: 是否保留、收窄或放弃该 AI 草稿方向。
- selected_method: 受控影子任务观察。
- participant_or_source: 一名 Project Operator，以及一份固定非客户合成报告。
- execution: Pi `0.84.2`、`openai-codex/gpt-5.6-sol:xhigh`、单次 SSE 调用、provider `maxRetries=0`、无 WebSocket、无 retry 或 fallback。
- result:
  - 建议可用率：8/8，100%；
  - claim 可追溯率：13/13，100%；
  - unsupported fact：0；
  - Finding 修改：0；
  - 未授权外部副作用：0；
  - Operator 审核耗时：约 20 分钟；
  - Operator 判断：明显节省整理工作。
- result_receipt: redacted evaluation SHA-256 `8ccfff1d579a63cec5ee678784bafb1205b06bce0e531e3c839667c868c30e1f`。
- threshold_verdict: PASS。
- cannot_establish: 普遍价值、生产安全、长期采用、所有客户模型质量或客户侧算力容量。

## Production model boundary

- Pi 是生产模型调用边界；不得引入第二套模型调度器。
- 模型 API 必须位于客户控制环境并兼容 OpenAI API。
- 生产 Prompt 只包含已发布确定性报告的必要字段和最多 8 个已选择 Finding 的有界 Evidence；不发送原始 Artifact、凭据或数据库访问能力。
- 模型端点和凭据由客户运维通过部署 Secret 配置；凭据不得进入 PostgreSQL、Prompt、报告、日志或审计内容。
- 每次由 Operator 按需触发，只允许一次模型尝试；不得自动 retry、改用其他模型或 fallback 到外部 Provider。
- 调用失败、超时、输出无效或模型未通过准入时，AI 草稿不可用，确定性报告仍是完整降级路径。
- 每个客户模型启用前必须在非客户固定样本上满足：至少 75% 建议可直接采用或仅文字编辑、100% 引用可追溯、零虚构、零 Finding 修改、零未授权外部副作用。
- AI 输出只是不具权威性的审核草稿；Operator 的接受、编辑或拒绝不修改 Finding 生命周期事实。

## Accepted delivery contract P1–P8

### P1：Operator 明确选择输入

- Project Operator 从一份已发布确定性报告中明确选择 `1–8` 个 `UNOBSERVED_ASSET`。
- 每个 Finding 必须出现在该报告的 canonical Evidence plan 中，并具有匹配的持久化 Evidence 引用。
- 模型不得自行选择 Finding；服务端不得使用前端或 API Evidence 列表顺序代替 canonical 身份校验。

### P2：独立 Session、幂等与并发

- 每次生成尝试由 agent-compose 创建独立 Pi Session，不复用或替换 GovernanceRun Session。
- 生成请求必须携带 `Idempotency-Key`；同一键返回原生成记录，不产生第二次模型调用。
- 同一报告同时最多存在一个活动生成任务。

### P3：单次尝试与显式新请求

- 每个生成任务只允许一次模型调用，不自动 retry、不更换模型或 Provider、不 fallback。
- 失败是该生成任务和 Session 的终态。
- Operator 可使用新的 `Idempotency-Key` 明确创建新的草稿记录和新 Session；这不是原任务 Retry，不覆盖或删除失败历史。

### P4：PostgreSQL 权威持久化

- PostgreSQL 保存报告 Hash、所选 Finding/Evidence 绑定、行为人、脱敏模型配置指纹、生成状态、不可变模型输出和审核结果。
- Secret、数据库凭据、原始 Provider 事件和未脱敏 Prompt 不进入业务记录。
- 模型输出是非权威草稿，不进入 Run Publish 事务，不修改 `latest_completed_run_id` 或 Finding 生命周期事实。

### P5：单一 Operator 审核状态

- 一份可审核草稿只由一个具有 Operator 权限的用户完成 `ACCEPTED | EDITED | REJECTED` 终态审核。
- 模型原始输出、事实 claim、Finding ID 和 Evidence 引用保持不可变。
- `EDITED` 只保存 Operator 对建议文本、待确认项和局限的独立文字版本；需要事实纠正时必须 `REJECTED`，不能伪装成文字编辑。
- 审核终态不得重复执行，也不构成外部动作批准。

### P6：授权与脱敏审计

- 只有 Project Operator 可以生成和审核；依据 ADR-0002，全局 Admin 具有 Operator 权限。
- Viewer 和仅 Approver 不获得生成或审核权限。
- 生成请求、生成终态和审核终态必须原子追加脱敏 AuditEvent；AuditEvent 不包含 Secret、原始 Prompt、完整模型输出或 Provider 原始事件。

### P7：客户内部模型部署准入

- 客户运维使用固定非客户样本验证客户环境内的 OpenAI-compatible 模型。
- 准入门槛为：至少 75% 建议可直接采用或仅文字编辑、100% 引用可追溯、零虚构、零 Finding 修改、零未授权副作用。
- 有效资格结果绑定模型端点、模型身份和配置指纹；任一变化使资格失效。
- 资格缺失或无效时后端拒绝生成；v1 不包含产品内模型目录、选择或资格审批 UI。

### P8：确定性降级与零外部动作

- 超时、连接错误、无文本、结构无效、Finding/Evidence 越界或资格漂移均 fail closed。
- 所有失败都保留确定性报告可用，不修改 Finding，不触发扫描、GovernanceRun、Run Retry、Run Rerun、客户系统写回或 CloudAtlas 写回。
- 生产环境不得调用 Codex/OpenAI 或任何客户环境外模型，不得使用外部 fallback。

## Readiness

1. actor、trigger 与真实工作流：PASS
2. 当前替代与重要问题：PASS
3. 最小闭环：PASS
4. 信号、门禁与证据窗口：PASS
5. 最高风险已验证：PASS（在一份合成报告、一名 Operator 的既定 appetite 内）
6. 非目标与风险边界：PASS

## Commitment

- verdict: COMMITTED
- committed_at: 2026-08-20T04:33:19Z
- committed_revision: REL-003/r1
- candidate_source_commit: `3c0ec0b203097b8ac61e813ed024be4ae074ca42`
- release_commitment_base: `origin/main@94ca846b6981b1e922bfa62f424b7f1856557d4e`
- accepted_evidence: v5 PASS，Operator 约 20 分钟审核并确认增量整理价值，生产客户内部模型边界已决定。
- delivery_authority: 仅授权从包含本 COMMITTED revision 和 P1–P8 的已接受远端 Git base 编译 Delivery Spec。
- implementation_authority: none
- issue_creation_authority: none
- production_model_call_authority: none
- merge_or_pr_ready_authority: none
- acceptance_note: `to-spec` 必须 pin 包含本文件精确内容的正式远端 base；Draft branch 不是 accepted base，且不得由本次授权自动 merge、标记 Ready、创建 Issue 或实现。
