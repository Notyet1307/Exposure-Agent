# REL-003：Operator 审核的 AI 治理草稿

## Metadata
- status: CANDIDATE
- revision: r1
- owner: product owner
- product_stage: FRAME
- delivery_stage: NOT_STARTED
- delivery_evidence_alignment: UNKNOWN

## Evidence ledger

| Type | Claim | Source | Limitation |
|---|---|---|---|
| FACT | 当前系统发布不可变确定性报告、Finding 与有界 Evidence；模型 Agent 尚未实现。 | `main@1d9605875fae287b83ffed9f13ec366acd86059d` | 仓库事实不能证明用户价值。 |
| DECISION | 下一阶段必须包含 AI 报告解读与处置建议。 | Product owner，本轮规划会话 | 这是方案约束，不是价值证据。 |
| DECISION | Operator 单人审核、按需生成、仅覆盖未观测资产、每份草稿最多 8 个 Evidence-backed Finding。 | Product owner，本轮规划会话 | 不授权实现或生产调用。 |
| UNKNOWN | AI 草稿是否相对确定性报告带来足够增量价值。 | 尚无正式 Evidence | 阻塞 Commitment。 |
| UNKNOWN | 允许使用的模型部署位置、数据保留与供应商边界。 | 尚未决定 | 阻塞真实资产数据验证。 |

## Release frame

- actor_and_trigger: Project Operator 打开包含未观测资产的已发布确定性报告，并明确请求生成 AI 草稿。
- observed_problem: 尚无正式 Evidence 证明当前人工流程造成延迟、遗漏、错误或追溯失败。
- target_outcome: Operator 能基于可追溯事实，更高效地形成补充扫描目标并重新扫描的审核结论。
- solution_hypothesis: 有界 AI 草稿能解释报告并提供 Evidence-backed 处置建议，同时不改变权威事实。
- smallest_closed_loop: 报告发布 → Operator 按需生成 → AI 返回结构化草稿 → Operator 接受、编辑或拒绝。
- included_scenarios:
  - 只处理 `UNOBSERVED_ASSET`；
  - 报告摘要中的事实必须引用确定性报告字段；
  - 最多处理 8 个已有有界 Evidence 的 Finding；
  - 每项包含 Finding ID、Evidence 引用、复扫建议、待确认项和局限；
  - Operator 可接受、编辑或拒绝；
  - 模型失败时确定性报告继续可用。
- non_goals:
  - 未报备资产；
  - 自动审批；
  - 修改 Finding 或权威统计；
  - 写回客户系统或暴露面系统；
  - 自动触发复扫；
  - 默认多 Agent 路径。
- success baseline: UNKNOWN
- primary_signal: 至少 75% 的 Finding 建议被 Operator 直接接受或仅作文字编辑。
- guardrail:
  - 事实与 Evidence 可追溯率为 100%；
  - 零虚构统计；
  - 零 Finding 修改；
  - 零外部副作用。
- evidence_window: 一次有界影子评审。
- minimum_evidence: 一名合格 Operator 对一份固定报告及最多 8 个 Finding 完成审核。
- risks:
  - value: 当前人工流程没有已观察到的负面后果；
  - usability: 草稿可能增加而不是减少审核负担；
  - feasibility: 模型可能无法稳定满足结构化与引用约束；
  - viability: 模型成本、部署位置和数据保留边界尚未确定。
- appetite: 一份报告、一名 Operator、最多 8 个 Finding、无生产动作。
- blocking_unknowns:
  - 增量审核价值；
  - 模型与资产数据的批准边界。
- false_positive_completion: 成功生成文本，但建议不可用、缺少引用、需要实质事实纠正，或影响权威事实。

## Current evidence protocol

- decision_question: 是否保留、收窄或放弃该 AI 草稿方向。
- selected_method: 受控影子任务观察。
- participant_or_source: 一名合格 Operator，以及一份经批准的固定、脱敏报告样本。
- evidence_to_capture:
  - 每项建议的接受、文字编辑、实质纠正或拒绝；
  - 所有事实引用的可追溯检查；
  - 审核耗时与 Operator 的具体解释。
- pass_threshold:
  - 建议可用率至少 75%；
  - 可追溯率 100%；
  - 零虚构统计和外部副作用。
- stop_condition:
  - 任一真实数据越界；
  - 任一未经 Evidence 支持的事实性陈述；
  - 模型尝试修改 Finding 或触发外部动作。
- cannot_establish: 普遍价值、生产安全、长期采用或完整模型质量。
- authorization: NOT_AUTHORIZED

## Control boundaries

- 只允许读取固定报告版本和有界 Evidence。
- 不发送原始 Artifact、凭据、Token 或数据库访问能力。
- 模型无数据库凭据、OctoBus Capset 或自由 Shell。
- 模型部署位置、供应商和数据保留规则批准前，不使用真实客户资产数据。
- 确定性报告始终是权威结果和降级路径。
- 停用 AI 生成功能即可恢复到原有确定性报告流程。

## Readiness

1. actor、trigger 与真实工作流：UNKNOWN
2. 当前替代与重要失败：UNKNOWN
3. 最小闭环：PASS
4. 信号、门禁与证据窗口：PASS
5. 最高风险已验证：UNKNOWN
6. 非目标与风险边界：PASS

## Commitment

- verdict: NOT_READY
- implementation_authority: none
