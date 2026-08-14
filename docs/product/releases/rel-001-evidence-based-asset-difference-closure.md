# REL-001：真实资产差异的有据判断与复测闭环

## Metadata

- status: CANDIDATE
- revision: r1
- owner: 人类产品决策者（当前对话授权人，姓名尚未记录）
- product_stage: FRAME
- delivery_stage: NOT_STARTED
- delivery_evidence_alignment: ENGINEERING_AHEAD

## Evidence ledger

| Type | Claim | Source and date | Limitation |
|---|---|---|---|
| DECISION | 首个 Release 优先验证真实客户角色是否会在真实内外部资产对账中，对差异完成有依据的判断、形成行动、完成复测，并愿意再次使用。 | 产品塑形对话，2026-08-12 | 这是产品方向选择，不是客户行为证据。 |
| DECISION | 不预设该真实客户角色为仓库中的 Operator；实际角色及可能的多人协作链必须由近期客户故事或观察验证。 | 产品塑形对话，2026-08-12；复核于 2026-08-14 | 系统角色只能提供词汇，不能证明客户职责。 |
| DECISION | AI 暂为次级 shadow/对照假设，只用于差异调查卡、下一步核验建议、确认记录草稿和复测差异解释。 | 产品塑形对话，2026-08-12 | 尚无证据证明 AI 会改善结果、效率或再次使用意愿。 |
| DECISION | AI 不参与资产匹配或权威统计，不修改 Finding，不替代人工判断，不审批或执行外部动作。 | 产品塑形对话，2026-08-12；`AGENTS.md`；`docs/architecture/commercial-function-and-data-architecture-v0.1.md` | 权限边界降低风险，但本身不能证明产品价值。 |
| FACT | 仓库架构基线已定义确定性资产比对、可追溯 Finding 生命周期、复测以及受限 PI 报告 Agent 的技术边界。 | `docs/architecture/commercial-function-and-data-architecture-v0.1.md`，基线日期 2026-07-19，本次复核 2026-08-14 | 架构与工程设计不能证明真实客户存在该问题或会采用闭环。 |
| FACT | 当前管理界面的项目工作区使用 `Inputs`、`CloudAtlas`、`Runs`、`Assets`、`Findings` 和 `Reports` 等英文标签。 | `frontend/src/routes/_layout/index.tsx`，`origin/main@03f640d`，查阅于 2026-08-14 | 这是当前代码事实，不证明已部署环境或客户理解。 |
| FACT | 人类产品决策者已安排一名不参与产品设计的业务系统日常运维人员，预计于 2026-08-14 下午参与；该参与者不懂英文。 | 产品塑形对话，2026-08-14 | 这是招募与语言条件，不证明该角色实际承担目标闭环，也不证明会如期完成会谈。 |
| ASSUMPTION | 业务系统日常运维人员参与真实资产差异的判断、行动交接或复测，是本 Release 的候选 actor 或协作链成员。 | 基于 2026-08-14 的参与者招募信息 | 必须由一个近期具体事件验证，不能由职位名称推定。 |
| DECISION | 由于独立参与者已可用，未执行的 founder dogfood 不再是当前证据行动；先进行不展示产品的中文近期故事访谈，验证 actor、现有流程、替代方式和重要失败。 | 人类产品决策者确认参与者后，2026-08-14 | 该访谈不验证界面可用性、完整闭环或再次使用行为。 |
| DECISION | 当前界面的英文标签会把语言障碍混入任务完成结果，因此本轮访谈不展示产品、不口译界面，也不把英文界面表现计入产品价值或流程证据。 | 产品塑形对话与代码复核，2026-08-14 | 后续是否需要中文原型或产品本地化，必须根据本轮证据另行决定。 |
| DECISION | 人类产品决策者授权创建并预交付发布本 revision；只有其精确 blob 进入 `origin/main` 后，才授权按本文件的边界执行 E1 访谈。 | 产品塑形对话，2026-08-14 | 不授权 merge、敏感数据处理、录音、产品任务测试、AI shadow、真实动作或进入 COMMIT。 |
| UNKNOWN | 该参与者最近是否实际处理过目标差异、承担哪些步骤，以及判断、行动、复测和再次使用决策是否跨多人交接。 | 截至 2026-08-14 尚未访谈 | 会改变 actor、最小闭环与后续证据方法。 |
| UNKNOWN | 客户当前如何完成内外部资产对账、使用什么替代方式、最重要的失败是什么。 | 截至 2026-08-14 未取得客户行为证据 | 阻止建立基线和判断新闭环是否更有价值。 |

## Release frame

- actor_and_trigger: `ASSUMPTION`：业务系统日常运维人员是候选 actor 或协作链成员；当其发现或收到一次真实的内部资产事实与外部暴露面资产事实差异时开始工作。必须由近期具体故事验证其实际职责，不得把职位名称或仓库中的 Operator 角色当作客户证据。
- observed_problem:
  - facts: 当前没有客户事实证明判断、行动推动或复测存在足够严重的问题。
  - assumptions:
    - 真实客户当前难以依据可追溯来源事实判断资产差异。
    - 判断结果难以转化为有责任归属的行动并推进到复测。
    - 完成一次闭环后，客户会认为该方式值得再次使用。
  - evidence_refs: 暂无客户证据。
- target_outcome: 真实客户角色能对至少一个真实资产差异作出有来源依据的判断，形成并推动具体行动，完成真实复测，并通过实际安排下一次对账或同等行为表现再次使用意愿。
- solution_hypothesis: 确定性 IP 差异、可追溯来源依据以及明确的“判断—行动—复测”记录，可以让真实客户角色完成闭环并愿意再次使用；AI 是否带来额外价值作为独立的次级 shadow 假设观察。
- smallest_closed_loop: `真实内部资产事实 + 真实外部暴露面事实 → 确定性 IP 差异 → 查看来源依据 → 客户作出判断 → 形成并推动修正或重扫行动 → 新的完整 Run 复测 → 理解关闭或继续开放结果 → 作出再次使用决定`。
- included_scenarios:
  - 一个真实客户环境中的一轮内外部资产对账。
  - 一个实际承担闭环的客户角色，或一条被观察到的真实多人协作链。
  - IP-only 的“未报备资产”或“未观测资产”。
  - 从真实差异到行动、复测和再次使用决定的至少一个完整案例。
  - AI shadow 使用与主判断隔离，在客户完成独立判断后才用于对照。
- non_goals:
  - 预设 Operator 就是真实 actor。
  - 端口、URL、域名、应用、部门或责任人差异。
  - 风险归一、自动处置、自由聊天或通用 Agent。
  - 让 AI 生成权威事实、自动确认、修改或关闭 Finding，或执行外部动作。
  - 以技术比对成功、页面完成、AI 文案质量或口头兴趣替代真实闭环行为。
- success baseline: `UNKNOWN`；必须先取得客户当前流程、耗时、交接、完成率或其他可比较信号。
- primary_signal: 真实客户角色或协作链完成“有据判断—具体行动—真实复测”，并以安排下一次实际对账、提交下一批真实输入或等价成本行为表现再次使用意愿。
- guardrail:
  - 每个用户可见结论可追溯至确定性来源事实。
  - AI 输出和人工猜测均不得改变权威 Finding。
  - 未经既定审批和安全机制不得执行外部动作。
  - 不将客户敏感原始数据、凭据、IP 或未脱敏证据写入本 Release artifact。
- evidence_window: 一次真实差异评审到其真实复测及再次使用决定；具体日历上限必须在执行 Evidence protocol 前固定。
- minimum_evidence:
  - 真实参与者身份类别、近期触发和当前工作流的观察记录。
  - 当前替代方式及其重要失败的具体近期案例。
  - 前后两次完整且可追溯的真实来源事实。
  - 带来源依据的客户判断记录。
  - 明确的行动、责任归属及实际推进证据。
  - 复测结果及客户对结果的理解。
  - 下一次真实使用安排或拒绝再次使用的具体原因；口头好感不单独计入。
  - 最终样本量和通过阈值须在 Evidence protocol 运行前固定。
- risks:
  - value:
    - 真实客户可能不认为资产差异值得形成治理闭环。
    - 一次闭环可能由服务推动而非产品价值驱动。
    - 口头再次使用意愿可能不转化为行为。
  - usability:
    - 来源依据可能不足以支持判断。
    - 判断、行动和复测可能跨多个角色，单角色界面无法闭环。
    - 术语或状态可能导致客户误解“未观测”为“不存在”。
    - 当前英文管理界面无法由本次不懂英文的参与者独立使用；口译会污染任务完成信号。
  - feasibility:
    - 可能无法在证据窗口内取得两侧真实数据、推动行动或完成复测。
    - 真实来源失败可能使差异或关闭结论不成立。
  - viability:
    - 私有化环境、审批责任、敏感数据处理或客户接入成本可能阻碍重复使用。
    - 完成闭环可能依赖不可持续的人工服务。
  - AI shadow:
    - AI 可能制造无来源解释、锚定客户判断或增加核验负担。
    - shadow 结果若提前暴露，会污染主假设的客户独立判断。
- appetite: 只验证一个真实客户上下文和一个端到端对账—复测周期；从最多五个候选差异中选择至少一个推进完整闭环；不建设自动处置或扩展资产类型。具体时间、成本和参与者上限须在 Evidence protocol 前固定。
- blocking_unknowns:
  - 业务系统日常运维人员是否为真实 actor 或协作链成员，职责是否跨多人交接。
  - 最近一次真实触发、当前工作流、替代方式及其最重要失败是什么。
  - 能否安全取得真实内外部资产事实并在有界时间内完成行动和复测。
  - 谁能作出再次使用决定，以及什么行为足以代表真实再次使用。
  - 当前基线与固定的通过、失败和停止阈值。
  - 客户数据处理、记录和观察所需的授权及脱敏边界。
- false_positive_completion: 确定性比对运行成功、界面或 AI 输出完成，甚至客户口头表示有用，但没有真实客户完成有据判断、推动行动、完成复测并作出有行为成本的再次使用决定。

### Secondary AI shadow hypothesis

AI 只基于与客户主流程相同的有界 Evidence，生成：

1. 差异调查卡：区分已知事实、可能原因和缺失证据；
2. 下一步核验建议：给出有限核验路径及每一步所需证据；
3. 确认记录草稿：整理客户已经给出的判断、依据和下一步；
4. 复测差异解释：解释前后完整 Run 的确定性变化。

AI shadow 输出必须与客户独立判断隔离，不计入本 Release 的主要通过条件。只有预先固定对照方法后，才能判断它是否改善结果质量、耗时或再次使用意愿。

## Current evidence protocol

以下协议字段均为 `DECISION`，在执行前固定；实际回答和结果只能在执行后按来源记录为 `FACT`、`UNKNOWN` 或新的 `DECISION`。

### E1 中文近期故事访谈 v1

- protocol_id: `E1-cn-ops-recent-story-v1`
- protocol_status: `AUTHORIZED_AFTER_ORIGIN_MAIN_PUBLICATION`
- evidence_class: `EXTERNAL_CUSTOMER_RECENT_STORY_INTERVIEW`
- decision_question: 业务系统日常运维人员是否在近期真实事件中参与资产差异的发现、判断、行动交接或复测；其当前替代流程是否存在足以支持、重做或放弃本 Release frame 的重要失败？
- riskiest_assumption: “业务系统日常运维人员”这一职位类别确实处于目标工作流中，并面对可观察且重要的判断、交接或复测问题；职位名称不是 actor 证据。
- participant_or_source: 1 名不参与产品设计的业务系统日常运维人员；由人类产品决策者于 2026-08-14 安排；参与者不懂英文。
- freshness: 优先讲述访谈日前 180 天内最近一次真实事件；若最近一次更早，记录实际时间并返回 `E1_INCONCLUSIVE`，不得用假设场景替代。
- non_decisions:
  - 当前产品界面是否可用；
  - 哪项功能或本地化方案应当建设；
  - 参与者能否完成完整的新产品闭环；
  - 客户是否采用、付费或持续复用；
  - Release 是否可进入 COMMIT；
  - AI 是否产生客户价值。

#### Scope and sample

- 只访谈 1 名参与者，只还原 1 个最近的具体事件。
- 事件从参与者最初发现或收到差异开始，直到其实际停止参与、完成交接、确认结束或进行复查为止。
- 使用“系统里登记的资产”“外部看到的资产”“差异”“处理完成”等中文业务表达，不使用 `Run`、`Finding`、`Evidence`、`Operator` 等产品术语引导回答。
- 不展示当前产品、原型、报告、架构图或解决方案，不翻译英文界面供其操作。
- 本协议不读取真实系统、不处理客户数据、不执行外部动作、不运行 AI，也不要求参与者准备截图或原始材料。

#### Session protocol

1. **Consent and boundary**：说明本次只了解最近一次真实工作，不评价个人表现；取得参与同意；明确不要说出真实 IP、主机名、URL、系统名、客户身份、账号、凭据或其他敏感信息；默认不录音。
2. **Unaided story**：先只问：“请从最近一次你发现或收到系统内登记资产与外部看到的资产不一致开始，按当时顺序讲讲发生了什么。”在参与者讲完前不展示方案、不提供步骤清单。
3. **Timeline clarification**：只追问实际发生的时间顺序、触发、输入、工具类别、判断依据、输出和结束状态；主持人不得替参与者补全缺失步骤。
4. **Roles and handoffs**：确认参与者亲自做了什么、前后交给谁、谁能决定下一步、交接依赖什么信息，以及在哪一步最容易等待、丢失或误解。
5. **Alternative and failure**：确认当时实际使用的系统、表格或沟通渠道类别，以及最耗时、最易错或后果最严重的一次具体失败；不得用“是不是很麻烦”等引导性问题制造痛点。
6. **Completion and recurrence**：确认当时如何判断处理结束，是否重新检查、重新扫描或回看结果；记录同类事件的大致频率及最近一次之后是否再次发生。
7. **Close**：复述脱敏后的流程与未知，请参与者纠正；不推销产品，只可询问其是否愿意在后续另行授权的受控任务观察中继续参与。

#### Evidence to capture

只在仓库外的获批位置保存会谈笔记；Release artifact 只接收脱敏结论和不反推出客户或资产的引用。

- 参与者角色类别及其在事件中的实际职责；
- 事件距访谈日的时间范围和真实触发；
- 当前替代方式的工具类别，不记录产品名、系统名或文件名；
- 按发生顺序记录的步骤、判断点、输出和完成状态；
- 前序与后续角色类别、交接内容类别和等待点；
- 一个最重要失败、其可观察后果以及参与者当时采用的 workaround；
- 是否存在复查、重扫或其他完成验证，以及由谁判断结束；
- 主持人的提示、解释、遗漏字段和任何访谈污染；
- 所有未回答项按 `UNKNOWN` 记录，不由主持人补全；
- 是否出现敏感信息、活动 Incident、不同意参与或其他停止条件，目标必须为零。

#### Privacy and safety

- 默认不录音、不截图、不收集原始文件；任何录音都需要新的明确同意和获批存储位置，本 revision 不包含该授权。
- 不在 Git、Issue、聊天、模型上下文或普通日志中写入真实 IP、主机名、URL、系统名、客户身份、人员姓名、凭据、文件名、原始行或完整逐字稿；使用 `E1-P01`、`E1-S01` 等不可逆脱敏别名。
- 参与者开始透露敏感值时立即打断并改用类别描述；已经听到的敏感内容不进入笔记或本 artifact。
- 若事件涉及活动安全事故、未经授权的数据访问、正在进行的外部动作或参与者不同意边界，返回 `E1_STOP_SAFETY` 并停止普通产品访谈。
- 当前英文界面不进入本轮；主持人不得通过实时口译帮助参与者完成产品任务后把结果记作可用性证据。

#### Appetite

- participant: 1 名业务系统日常运维人员；
- sample: 1 个最近的真实事件；
- participant_time: 最多 45 分钟；
- facilitator_redaction_time: 最多 15 分钟；
- sessions: 1；
- product_exposure: 0；
- implementation_or_data_access: 0；
- evidence_window: 2026-08-14 当日会谈；如未发生，必须重新确认日期和参与者可用性后才可执行。

#### Pass, fail, and stop thresholds

仅当以下条件全部成立时返回 `E1_FRAME_SUPPORTED`：

1. 参与者不依赖产品提示，还原一个访谈日前 180 天内的具体真实事件，而非一般看法或假设场景。
2. 真实触发、当前替代方式、主要步骤、至少一个交接和实际结束状态均已记录；未知项可以保留，但不得由主持人补全。
3. 参与者亲自承担至少一个会影响判断、行动交接或完成验证的实质步骤；若是多人链路，能区分各角色职责。
4. 参与者给出至少一个未被引导的具体重要失败、成本或风险，并说明其可观察后果。
5. 能说明当时如何判断处理结束，或明确指出没有复查/复测机制及其后果。
6. 必填字段记录完整率为 100%，其中允许显式 `UNKNOWN`；敏感信息留存、未授权访问、产品暴露和安全事件均为 0。

其他 verdict：

- `E1_ACTOR_REWORK`：存在近期事件，但参与者不承担目标链路中的实质步骤，或证据显示应改访谈其他角色。
- `E1_PROBLEM_REWORK`：参与者确实承担相关步骤，但当前替代方式没有重要失败、成本或风险，或目标结果与其工作无关。
- `E1_INCONCLUSIVE`：没有 180 天内的具体事件、只能给出泛泛回答、关键字段因时间或访谈污染无法判断，或会谈未按 appetite 完成。
- `E1_STOP_SAFETY`：未取得参与同意、出现敏感信息收集风险、活动 Incident、未经授权的数据或其他安全边界触发。

任一 verdict 都是有效证据结果；不得为了获得 `E1_FRAME_SUPPORTED` 更换问题、补写回答或展示产品。

#### Return format

执行后只允许向本 artifact 写入脱敏结果，格式为：

```yaml
protocol_id: E1-cn-ops-recent-story-v1
session_date: <YYYY-MM-DD>
source_ref: <approved external redacted note identity>
verdict: E1_FRAME_SUPPORTED | E1_ACTOR_REWORK | E1_PROBLEM_REWORK | E1_INCONCLUSIVE | E1_STOP_SAFETY
participant_role_category: <redacted category>
story_recency_days: <number | UNKNOWN>
trigger: <redacted finding | UNKNOWN>
current_alternative: <redacted finding | UNKNOWN>
workflow_steps: []
handoffs: []
important_failure: <redacted finding | NONE | UNKNOWN>
observable_consequence: <redacted finding | NONE | UNKNOWN>
completion_or_retest: <redacted finding | NONE | UNKNOWN>
metrics:
  participant_minutes: <number>
  mandatory_fields_recorded: <percentage>
  facilitator_interventions: <number>
  product_exposures: <number>
  sensitive_items_retained: <number>
limitations: []
readiness_effect:
  test_1_actor_trigger_workflow: SUPPORT | REWORK | UNKNOWN
  test_2_alternative_and_failure: SUPPORT | REWORK | UNKNOWN
next_evidence_decision: <one candidate decision or stop reason>
```

执行授权仅在本 `r1` 的精确 blob 已进入 `origin/main`、参与者和协议边界未漂移且现场再次取得参与同意时生效。授权不包含 merge、录音、敏感数据处理、产品任务测试、AI shadow、真实动作、复测执行、结果写回或进入 COMMIT；任何范围变化必须停止并重新请求授权。

## Readiness

尚未执行六项 COMMIT readiness tests。E1 只能为 readiness test 1（真实 actor、近期 trigger 和当前工作流）与 test 2（当前替代方式及重要失败）提供一名参与者、一个上下文的候选证据，并可能要求重做 actor 或问题定义；它不验证完整最小闭环、主要信号、guardrail、再次使用行为或其他 readiness tests。本 revision 不得据此进入 Commitment。

## Commitment

- decision: NONE
- committed_revision: NONE
- note: `CANDIDATE r1` 不是 Commitment；只有六项 readiness tests 全部 PASS 后，才可请求人类选择 `COMMITTED | HOLD | REWORK | DROP`。

## Delivery trace

暂无。未授权生成 Delivery Spec、tickets 或 Admission 材料。

## Release record

暂无；本 Release 尚未 committed、delivered 或 released。

## Outcome review

不适用；只有实际 Release、满足已固定 evidence window 并取得结果证据后才可评估。
