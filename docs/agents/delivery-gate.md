# Delivery Gate（历史）

本文件是历史流程说明，不是当前工作入口，也不自动授权实施。

`/to-spec` 与 `/to-tickets` 仍可作为方法使用。下文曾描述的 Delivery Spec Parent、Case-bound Release Graph、Codex Controller handoff，以及 ready-label 自动授权，不是当前入口。不要恢复 Controller、Release Graph 或 ready-label 自动授权。当前任务状态见 `issue-tracker.md`；行为预期见 Git 中已批准 Spec。

历史流程曾是：

1. `/to-spec` 发布 Delivery Spec Parent（`needs-triage`）并记录 acceptance receipt。
2. 已接受 Parent 视为当时不可变权威。
3. `/to-tickets` 起草完整候选子任务，独立审阅就绪与 graph，在任何 tracker 写入前取得明确人工批准。
4. 一次原子发布创建全部 `needs-triage` 候选、挂上原生子任务、写入 blocker 边，并把当时的 `delivery-release-graph:v3` 绑到 Planning Case。
5. 发布漂移或任何部分 tracker 结果失败关闭；在 graph 按新 tracker 状态重建前，候选不可执行。
6. 默认下一跳曾是 `/prepare-codex-release`，准备一次 Codex Controller handoff 并取得一次人工批准，且不粘贴 ready 标签。

当时也可显式选择 Legacy `/admit-ticket`：在任何 `ready-for-agent` 或 `ready-for-human` 变更前做独立 admission。Legacy 先激活子任务，最后激活 Parent。

当时 verdict 与 execution lane 独立：完整的仅人工票是 `READY/HUMAN`，不是 `NEEDS_INFO`。`SPLIT` 候选保持 `needs-triage`；确认的 `NEEDS_INFO` 候选进入 `needs-info`。来源、候选、关系、Oracle、所有权或 accepted-base 的实质变化需要新的 graph 和审阅。

Wayfinder maps 与 `wayfinder:*` 决策票是规划材料，从未作为可执行 Delivery Parent，也从未接受 ready 标签。

Label 字符串见 `docs/agents/triage-labels.md`。Tracker 关系操作见 `docs/agents/issue-tracker.md`。
