# ADR-0018：客户台账版本以人工派生 CustomerUpload 接入治理

状态：已接受（维护者于 2026-09-15 批准 EXP-EVO-01A 设计与验收目标；已进一步授权规格发布、正式任务衔接、隔离本地实现及合成验证，不代表实现通过）。

依据：[Release 1 Spec 的 EXP-EVO-01A](../specs/asset-governance-release-1.md#exp-evo-01a-客户原生台账与人工派生版本)。本 ADR 仅接受 EXP-EVO-00 候选中的客户台账/派生输入决定，不接受新 namespace、NetFlow 候选或业务 Skills。

## 决定与取舍

日常台账以可追溯来源行与不可变人工 Revision 管理，不依赖已发布 Run 或报告样本。原始上传、人工更正、本地管理字段分层；输入字段改变时物化明确标记人工来源的派生 XLSX，经旧严格校验接受为 CustomerUpload；仅管理字段变化不造新输入。原文件字节、Hash、来源与旧结果不覆盖。

Run 继续固定 CustomerUpload ID、raw hash 和 Profile ID/version，不增加 LedgerRevision 输入类型。人工 Revision 经不可变关联保存出处，不伪称旧 input hash 直接包含新字段；原快照/Observation/Resource/报告合同不变。以后报告或 AI 若需要管理字段，须在对应获准材料合同显式固定 Revision。

此方案复用输入接受、确认、pin、恢复与历史 reader。拒绝原地编辑 Observation/父文件，因其破坏来源与历史；暂不引入另一 Run 输入类型，避免扩散预约、Runner、Schema、Retry 与历史 reader。代价是人工 Revision→合法 XLSX 的适配，以及至少一条有效记录的旧合同：全归档至零条明确拒绝，不造占位记录。

## 事务、权限与身份

旧接受/选择各自提交，人工保存须以最小领域事务将派生输入、Revision、选择与审计原子提交；复用校验和存储，保留旧调用方行为。文件/事务失败保留旧选择，只处理本次未引用文件，不动父 Artifact。

人工幂等按 actor/Project/操作/key 绑定请求，独立于内容去重。预期父 Revision/当前输入/Profile 决定并发冲突；同 key 已完成重放保持原结果。内容可复用既有上传，但不得重写它的来源/父链，人工操作仍有独立身份和审计。

沿用 Project 权限、稳定 Resource 和 ADR-0005 的 mapped IPv6 折叠。重复 IP 行各自保留身份；首片只使用旧 Project 地址空间，不重编号 Resource 或推断跨来源归属。Operator/全局 superuser 可写，Viewer/仅 Approver 只读，归档/撤销沿旧规则拒绝新写。

## 保留边界

继承 ADR-0008 的固定输入/恢复、ADR-0013 的报告分派和 ADR-0016 的权威分工。编辑只生成新版本，不自动启动 Run/模型/扫描，不调外部系统、不关闭 Finding、不改旧报告/引用。01B/01C/02、客户系统同步、空输入和 namespace 治理仍未批准。

PostgreSQL、agent-compose、OctoBus 边界不变，无第二调度器、Controller 或通用规则系统。发布、实施、验证和部署以实际授权及证据分别记录。
