# 当前工作

- 正式任务：[EXP-UX-01 #230：新建项目、准备输入与首轮比对](https://github.com/Notyet1307/Exposure-Agent/issues/230)，任务状态、依赖与授权以 GitHub Issue 为准。
- 固定批准 Spec：[asset-governance-release-1.md@8a07554](https://github.com/Notyet1307/Exposure-Agent/blob/8a07554ef399339f0909544c4dbba8b180afc0a1/docs/specs/asset-governance-release-1.md)，EXP-UX-01 节。
- 当前候选分支：`codex/exp-ux-01`。实现创建幂等、三来源准备、确认输入身份与首轮固定结果，以及刷新恢复、账号隔离和键盘焦点。
- 当前远端交付范围：独立验收后提交、推送、创建 Draft PR 并核对该提交的 CI；不包含合并、正式部署或关闭 Issue。
- 验证记录：[EXP-UX-01 候选验证](issue-230-validation.md)。两轴代码审阅、隔离业务验收和远端 CI 分别记录，不相互代替。
- 边界：不调用外部模型，不改现场模型或执行器绑定，不修改既有 B0/400 资产、历史事实、其他工作树或 WIP；不扩展到 LLM 设置、CloudAtlas 文件导入或 XLSX 兼容放宽。
- 下一步以 #230 及其 Draft PR 的实际检查结果为准；未通过、未运行的验收不得记为 PASS。
- 权威规则：[ADR-0016](../adr/0016-pin-approved-spec-and-issue-status.md)。
