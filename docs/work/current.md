# 当前工作

- 当前实施入口：[EXP-3SRC-UX-01A #284](https://github.com/Notyet1307/Exposure-Agent/issues/284)：在原有前端集成 A 方案，先呈现确定的 IP 事实、准确总览与完整来源差异，再进入原因和依据。可独立实施的另一入口为 [NetFlow 处理数据查询 #286](https://github.com/Notyet1307/Exposure-Agent/issues/286)。
- 固定行为：[三源比对工作台 V1 @c15be89](https://github.com/Notyet1307/Exposure-Agent/blob/c15be890eac8bf5044b891c9feccfa3ce7da6f68/docs/specs/three-source-workbench-v1.md) 及同版 [ADR-0023](https://github.com/Notyet1307/Exposure-Agent/blob/c15be890eac8bf5044b891c9feccfa3ce7da6f68/docs/adr/0023-versioned-result-retention.md)。客户清单替换任务 [#285](https://github.com/Notyet1307/Exposure-Agent/issues/285) 依赖 #284；结果保留任务 [#287](https://github.com/Notyet1307/Exposure-Agent/issues/287) 依赖 #284/#286。任务状态、依赖、授权与验收以各 GitHub Issue 为准。
- 维护者于 2026-10-04 确认规格、ADR、四项任务拆分，以及文档分支 push/PR 和建单；已授权本地实现、验证与提交。业务源码 push/PR/merge、真实迁移部署、数据清理和新增来源/模型调用仍须分别授权。文档 PR 为 [#283](https://github.com/Notyet1307/Exposure-Agent/pull/283)。
- 本地代码基线为已验收的 `ef1b774d6f91d1cf342b30f469d588b94b2ef0b9`，含尚未全部远端发布的先行修复；本次文档分支从 `origin/main=f246b361d92fa298a1f9ac35b7a11db085b69c2c` 分出。不得借文档发布推送整条业务分支；后续源码发布前复核提交范围和依赖。
- 已有任务 [#279](https://github.com/Notyet1307/Exposure-Agent/issues/279)、[#281](https://github.com/Notyet1307/Exposure-Agent/issues/281) 保留自己的固定规格、验收和授权，不由本轮改写或关闭。已发布旧 Run/报告、原始 Dataset、客户历史和既有真实数据期限保持原合同。
- 当前真实项目仍缺客户清单，原型与隔离合成验收不能冒称真实三源业务验收。A 原型仅是已选的信息层次参考，正式功能需由本轮真实接口和用户主线证明。
