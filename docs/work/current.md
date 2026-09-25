# 当前工作

- 当前任务：[EXP-FOCUS-01B-BATCH #255](https://github.com/Notyet1307/Exposure-Agent/issues/255)，IP与端口有界批次在正式页面先可读；状态、依赖、验证结果与授权仅在Issue维护。
- 固定规格：[Exposure聚焦Spec@a21380d](https://github.com/Notyet1307/Exposure-Agent/blob/a21380dcd8b677551fa2da0429f0467210543cdb/docs/specs/exposure-focus-release-1.md)，配套[ADR-0022@同版本](https://github.com/Notyet1307/Exposure-Agent/blob/a21380dcd8b677551fa2da0429f0467210543cdb/docs/adr/0022-bounded-external-asset-publication.md)及ADR-0021；适用ACBATCH-1—5及修订后的AC01B-1—7。
- 背景：替代规格经[PR #254](https://github.com/Notyet1307/Exposure-Agent/pull/254)正常门禁合并；字段矩阵、[资产先行核验回执](exp-focus-01a-contract-verification-20260923.md)继续记录既有实见与缺口，不把小样本当完整同步。
- 历史：#250/PR #252的原交付与#253此前真实验收保持原固定Spec含义；#247及旧Run/报告不升级、不重开、不重开发。风险和其他资产域仍后置。
- 停止线：#255允许按固定合同本地实现、迁移演进、客户端生成与验证。业务代码远端生命周期和生产部署不继承规格PR授权；新增真实读取/持久化须在Issue固定本轮精确范围、预算和保留/清理。不得自动重试来源、跨批次合并、续拉、扩大能力或启动01C。
