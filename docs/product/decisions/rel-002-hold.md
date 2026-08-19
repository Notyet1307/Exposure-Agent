# REL-002：受限 PI 报告 Shadow

- status: HOLD
- delivery: NOT_STARTED
- implementation_authority: none
- decision: 当前不实现，也不继续技术实验

## HOLD 原因

- 现有运行路径只生成权威确定性报告，Runner 未接入 PI。
- 已完成的技术探针不能证明真实报告审核价值。
- 人类证据未取得近期、真实、非测试业务审核中的具体问题故事。
- 继续模型、Provider 或 Reviewer 实验会让工程进度领先于产品证据。

确定性报告继续作为当前权威结果和降级结果。本决定不授权 PI、模型调用、E3、Delivery Spec、tickets、实现或生产启用。

## Reopen condition

出现一名目标 actor 的近期真实非测试业务审核故事，包含 trigger、实际步骤、当前替代、具体失败和可观察后果；随后必须在新的权威 revision 中重新冻结产品证据协议。不得复用已关闭的 H1 或 E3 v1 作为通过证据。

## 历史证据

- 完整实验与决策过程保留在 Git 历史和 GitHub PR #136。
- 本 HOLD 墓碑建立于基线 `d783318862ef6d613dafcb51498cb0ced644818c`。
- 历史 evidence、token 统计、临时路径和固定验收快照不进入默认 Agent 上下文。
