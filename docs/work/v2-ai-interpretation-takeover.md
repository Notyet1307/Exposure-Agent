# V2 AI 接管与候选回执

日期：2026-10-08。源附件：维护者提供的 `Exposure_V2_AI_Review_and_Codex_Prompt_20261008.md`。维护者已请求“按照 prompt 完成我们 v2 目标”；本回执记录接管及候选，不宣称合同已批准或目标已交付。

## 当前事实

- 已 fetch 并读取远端 main，基线 `5c46d44a753db4f39479640d7f07e0b3909f85df`，与附件静态基线一致。
- 原 `/Users/yang/Test-drive-sales/Exposure-Agent` 为 `16e451d`，存在未提交 Spec/current 和 `docs/plans/`，未改写。新独立工作树 `/Users/yang/.codex/worktrees/exposure-v2-ai/Exposure-Agent`，分支 `codex/exposure-v2-ai`。
- 原生 GitHub最新任务列表及 V2 AI 标题检索没有本次报告任务；#292/#285/#289 CLOSED，PR #293/#295 已在 main。不能复用旧任务的发布/部署/模型授权。
- 已读最新 AGENTS/current、原固定 V2 Spec/ADR-0024、旧报告合同/ADR-0007/0015/0017以及相邻代码。旧报告只接受 Run，V2材料需新 subject和窄ADR。

## 首轮核验

新增 `frontend/tests/core-reading.component.spec.ts` 仅用于先失败复现，HTTP为明确合成mock。命令 `cd frontend && bunx playwright test tests/core-reading.component.spec.ts --project=component --workers=1 --reporter=line`；应用源码保持基线。

| 核验 | 结果 | 实际证据与边界 |
| --- | --- | --- |
| F1 首次binding元数据500 | FAIL | 核心全集3按钮仍可读，地址未显示期望不可读；页面错误被缺binding状态遮蔽 |
| F1 403 | FAIL | 同路径误导；并非真实部署权限复现 |
| F1 超时 | FAIL | 注入网络timedout，同路径未给失败/显式恢复 |
| F2 两域快捷入口 | FAIL | 仅旧合并入口，预期分域IP/port入口不存在；代码只取ip_version_id ?? port_version_id |
| 实际部署浏览器/PG业务复现 | NOT_RUN | 当前仅组件HTTP故障注入，不能代替真实业务链路 |
| AI报告或地址解释实施 | NOT_RUN | 先固定新subject/材料/输出/失效合同与正式任务 |
| 真实模型/来源、远端业务发布、部署 | NOT_RUN | 无本轮对应授权；本轮未读取现场Secret或发起调用 |

测试失败留在新工作树，属于待A修复的红用例，不修改断言换PASS。Playwright `test-results`/错误上下文在工作树本地，未上传；四项错误快照展示仍可读的核心及缺失/误导入口。

首次失败上下文另存 `/Users/yang/.codex/worktrees/exposure-v2-ai-evidence/first-reading-baseline`，manifest固定基线/命令/四份文件SHA-256，后续绿色复测不覆盖该失败版本。前端依赖 `bun ci` 已完成，无lock修改；文档上下文门禁和差异空白检查PASS。应用源码未改，后端完整测试和新的业务链路未运行。

独立只读候选复核分别按Standards和附件合同检查；首轮发现旧`protect_analysis_report()` trigger已发布Run校验不可直接移除，已将subject分支及保留旧检查写入Spec/ADR。修正候选`bbdbe97`的两轴文档复核PASS，原blocker已解决，其余未发现blocker；本段仅补记事实，不变更合同。该复核不冒称OMP独立源码/业务验收。

## 可审阅候选与下一步

[候选Spec](../specs/v2-ai-interpretation.md)、[候选ADR-0025](../adr/0025-v2-ai-report-materials.md)、[A/B/C任务草稿](../plans/v2-ai-interpretation-issues.md) 已给出身份、API/持久化最小方案、结构化输出、全入口期限/撤权、非模型验证范围与各阶段验收。

必须先批准候选合同并固定真实Git commit/正式Issue。附件§0要求“按仓库流程先固定新材料合同、必要的窄ADR和任务归属”，且§0.5明确不自动授权远端Issue/PR；AGENTS要求只实施当前确认Issue，ADR-0016要求批准Spec和Issue固定commit。本次需要的新增许可只为候选Spec/ADR接受和规格文档正常push/PR、必需CI/Review后merge及引用固定版本建单；业务发布、部署、真实调用均保持独立。

完成该衔接后按 A→B→C 本地实施/必要验证/单独提交。每阶段写实际SHA、合同及逐项结果，不将本次候选或红用例描述为V2完成。
