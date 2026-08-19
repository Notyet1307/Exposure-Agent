status: non-normative
implementation_authority: none
default_agent_context: excluded

# Exposure-Agent 产品目标状态

本文件只保存仍有产品价值的未来方向。它不是当前实现、Spec、AC 或排期；只有新的 GitHub Issue / PRD 和必要的已接受 ADR 才能激活其中能力。

## 多源接入

- 客户系统可达后，以正式 OctoBus SourceInstance 替代 CustomerUpload 作为新 Run 的客户侧输入；
- 根据真实客户 API 契约实现认证、分页、限流和增量读取；
- 保留 CustomerUpload 历史事实，但不把它扩展成通用导入平台。

## 资产与风险治理

- 在有可靠双侧数据契约后扩展 Endpoint、Domain、URL、Application 和责任主体；
- 增加来源关系、责任关系和需要人工确认的实体匹配；
- 保留 CloudAtlas 原始风险判断，再形成可追溯的治理 Finding；
- 仅以完整成功 Run 的正向证据驱动 Finding 生命周期。

## 报告

- 在 REL-002 重新满足真实 actor / workflow / value 证据后，评估受限报告 Agent；
- Agent 仍只消费有界 Evidence，输出结构化草稿，并由确定性 Validator fail-closed；
- 评估 PDF 等额外交付格式，但不改变 canonical JSON 和确定性报告的权威地位。

## 审核与处置

- 基于已确认 Finding 形成固定 Hash 的 RemediationPlan；
- 由不同职责主体审批或拒绝；
- 通过最小权限 OctoBus Action Capset 幂等执行；
- 记录外部任务状态，并以新的确定性 Run 复测，而不是直接改写 Finding。

## 交付成熟度

- 在目标客户硬件上验证容量、CPU、内存、恢复时间和数据恢复点；
- 完成离线镜像、版本清单、SBOM、备份恢复演练和客户身份源集成；
- 只有实测瓶颈或客户约束出现后，才评估分区、对象存储或高可用形态。
