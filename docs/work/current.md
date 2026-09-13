# 当前工作

- 正式任务：[EXP-UX-03 #234：主页、资产和报告中的可见 AI](https://github.com/Notyet1307/Exposure-Agent/issues/234)。状态、依赖与授权以 Issue 为准。
- 批准 Spec：[asset-governance-release-1.md@f934bdc](https://github.com/Notyet1307/Exposure-Agent/blob/f934bdc1ee6fe0146f1a88bca217cbcc0c4e0d0c/docs/specs/asset-governance-release-1.md)，EXP-UX-03 节；沿用 ADR-0015/0017 的材料、运行身份与人工确认边界。
- 分支 `codex/exp-ux-03`，实现基线 `fbba894bb1dcb3d6e52e484b2979bb38fafcbc6c`。01/02 已合并、部署并关闭；本次复用已有核查/报告/人工记录引擎，优化可见入口与上下文连续性，不做04或新工具。
- 已完成 actor/固定范围的恢复隔离及历史版本读取、首页 AI 区、资产快捷问题和报告定位，本地候选已通过相关验证。页面打开/刷新/导航不创建任务，Viewer只读，模型不可用不阻断事实与历史。
- 当前允许规格/Issue衔接、本地实施和必要隔离合成验证。业务代码push/PR、合并、部署、关闭另保门禁；真实外部Provider目的地/材料须另行固定授权，不从02授权外推。
- 保留当前8080、原模型与数据、其他工作树和WIP；Issue专属临时回执/固定Run快照不进main。所有验收按PASS/FAIL/BLOCKED/NOT_RUN记录，独立代码审阅不代替业务验收。

- 本地验证：前端相关组件 86 项、后端相关 API 21 项通过；前后端 lint/typecheck/build、上下文门禁通过。Standards/Spec 独立审阅无实质问题；三宽度首页视觉检查通过。
- 隔离合成端到端通过：导航与快捷问题零创建，显式核查/追问、人工记录、报告编辑/确认成功，原稿与持久连接身份保留，Finding 未改写。真实 Pi/控制面使用本地固定响应 Provider；外部模型语义与本候选部署未运行。
- 同条件五次本地反馈中位数 8.4ms→9ms（+7.1%，低于100ms，未观察到长任务）；先前测试选择器/环境准备失败已保留，修正后重跑通过。下一步是发布本地候选并创建PR，仍须遵循上述远端授权边界；Issue保持开放。
