# 当前工作

- V2真实模型兼容修复[#298](https://github.com/Notyet1307/Exposure-Agent/issues/298)：源码[PR#302](https://github.com/Notyet1307/Exposure-Agent/pull/302)正常合并9e99d19，8081受保护部署/默认V1+V2资格及管理/运营原生可读草稿验收完成，见[回执](v2-model-contract-validation.md)。仅固定合成C+A出域；管理稿人工修订保留原稿，均未自动确认，真实客户验收仍未执行。下方NOT_CONFIGURED等条目保留此前快照；实际任务状态以GitHub为准。

- V2阅读/AI报告/地址解释 #297/#298/#299 已经[源码PR#300](https://github.com/Notyet1307/Exposure-Agent/pull/300)必需CI/独立审阅后正常合并为`7dadbbb`，8081备份、实际恢复/追加迁移、上线及阅读验收PASS，见[交付回执](v2-ai-interpretation-deployment.md)。正式模型仍NOT_CONFIGURED，未真实调用来源/模型。按维护者授权关闭三票，实际状态以GitHub为准；其余票/WIP/历史/期限保留。下方为各此前阶段快照。

- V2阅读/报告/地址解释 #297/#298/#299 本地实施与必要验收完成，见[验证回执](v2-ai-interpretation-validation.md)。批准Spec/ADR固定`1c42406`；分阶段源码与后续修复在`codex/v2-interpretation-implementation`。当前正按维护者已授权的正常源码PR/CI/merge→既有8081备份/恢复演练/迁移/部署验收→关闭推进，远端状态以Issue/PR为准。下方保留此前阶段授权/交付快照。

- 2026-10-09维护者明确授权按附件完成V2后正常源码push/PR、必需CI/Review后merge、既有8081备份/恢复演练/追加迁移与部署验收、完成后关闭297/298/299；各Issue已记录该后续授权。固定Spec/ADR1c42406不变，当前在B实现/验证，A候选a17dd09已本地提交。此前仅本地阶段条目保留为历史，不覆盖本授权；真实来源/模型出域、清理和保留期限扩展仍未包含。

- V2阶段A[#297](https://github.com/Notyet1307/Exposure-Agent/issues/297)本地实现/隔离阅读验收已完成，见[回执](v2-reading-validation.md)；固定Spec/ADR为`1c42406`（文档PR#296已合并），阶段B[#298](https://github.com/Notyet1307/Exposure-Agent/issues/298)与C[#299](https://github.com/Notyet1307/Exposure-Agent/issues/299)按本地候选验收顺序继续。当前仅分阶段本地实现/验证/提交，业务源码发布、部署、真实调用及关闭仍未获许可；Issue状态以GitHub为准。下方是此前规格发布前及已交付快照。

- 2026-10-08 V2阅读与AI报告候选b307415已获维护者明确批准：[Spec](../specs/v2-ai-interpretation.md)、[ADR-0025](../adr/0025-v2-ai-report-materials.md)和[A/B/C任务拆分](../plans/v2-ai-interpretation-issues.md)。当前授权规格文档push/PR、必需CI/Review后merge及固定commit建单，随后本地分阶段实施/隔离合成验证/提交；业务源码发布、部署、真实调用和关闭保持独立。工作树`exposure-v2-ai`保护原checkout WIP；[接管/红用例记录](v2-ai-interpretation-takeover.md)保留旧阶段事实。正式Issue待发布，下方保留已交付事实。

- 2026-10-08 产品使用逻辑收敛 [#292](https://github.com/Notyet1307/Exposure-Agent/issues/292) 与客户全量替换 [#285](https://github.com/Notyet1307/Exposure-Agent/issues/285)：维护者后续明确授权合并、部署和关闭。源码 [PR #293](https://github.com/Notyet1307/Exposure-Agent/pull/293) 经必需CI与独立审阅后正常合并为 `6f0d5ea`，8081现有正式实例已完成加密备份、实际恢复/迁移演练、上线与阅读验收，见 [上线回执](product-logic-v2-deployment.md)。固定 V2 Spec/ADR-0024 仍为 `b603b45`；[实施验证](product-logic-v2-validation.md) 与 [阶段 A 接管记录](product-logic-convergence-20261008.md) 保留各阶段事实。正式项目首次V2生成仍要求管理员确认网络空间及可比范围；本次未发起新的来源或模型调用。#287 不纳入；任务状态和关闭以各自GitHub Issue为准。

- 当前本地跟进为维护者 2026-10-07 提出的应用导航精简与固定比对刷新问题，分支 `codex/navigation-refresh-fix`，基于 `e8bbdc01b54b28719ddeb707ad7fd20bbb3ad3d3`。范围、复现、验证和发布边界见 [本地候选记录](navigation-refresh-validation.md)。维护者于 2026-10-08 明确授权建单、push/PR、必需 CI 通过后合并及 8081 前端部署；正式跟踪为 [#289](https://github.com/Notyet1307/Exposure-Agent/issues/289)。远端验收状态以该 Issue 为准。
- 既有交付为 [源码 PR #288](https://github.com/Notyet1307/Exposure-Agent/pull/288)；[#284](https://github.com/Notyet1307/Exposure-Agent/issues/284) 与 [#286](https://github.com/Notyet1307/Exposure-Agent/issues/286) 已在合并和 8081 部署验收后关闭。任务状态、依赖及授权仍以 GitHub 为准。本地后续候选不得冒称已由该 PR 发布。
- 固定行为：[三源比对工作台 V1 @c15be89](https://github.com/Notyet1307/Exposure-Agent/blob/c15be890eac8bf5044b891c9feccfa3ce7da6f68/docs/specs/three-source-workbench-v1.md) 及同版 [ADR-0023](https://github.com/Notyet1307/Exposure-Agent/blob/c15be890eac8bf5044b891c9feccfa3ce7da6f68/docs/adr/0023-versioned-result-retention.md)。本次导航变更保留旧 Run、报告、血缘及资产详情的路由和语义，刷新修复不放宽身份、权限或失败封闭。
- 前序导航交付时客户清单替换 #285 与新结果保留 #287 尚未实施；本轮 #285 本地实现见上方记录，#287 仍未纳入；其依赖状态以 GitHub 原生关系为准，不由导航调整或演示配置宣称完成。
- 维护者另行授权的混合演示已配置模拟客户登记并固定已有真实云图端口批次与 NetFlow Analysis；模拟登记不等于真实客户报备，不能将此演示记作真实客户三源业务验收。原历史数据及既有期限保持。
- [#281](https://github.com/Notyet1307/Exposure-Agent/issues/281) 按维护者要求保持开放，等待 ACS-5 人工页面对照；[#279](https://github.com/Notyet1307/Exposure-Agent/issues/279) 保留自己的固定规格和验收。当前反馈不授权新增来源/模型调用、数据清理或既有保留期变更。
- 前序云图接入固定 [RESULT-STRUCTURED / ACS-1–5 @5729d4d](https://github.com/Notyet1307/Exposure-Agent/blob/5729d4dd2fc40cd23eb748a575ba9bc7e2d5ccab/docs/specs/exposure-focus-release-1.md#result-structured18类结构化数据接入)，同版附录/字段矩阵和 ADR-0021/0022 继续适用。#284/#286 的本地历史验证记录保留原日期，分别见 [工作台验证](exp-3src-ux-01a-validation.md) 和 [独立查询验证](exp-3src-ux-01c-validation.md)。
