# 当前工作

- 当前任务：[EXP-FOCUS-01C-RESULT-STRUCTURED #281](https://github.com/Notyet1307/Exposure-Agent/issues/281)：云图 18 类结构化数据接入；任务状态、依赖、授权和逐类型验收仅在该 Issue 维护。
- 固定行为：[聚焦 Spec RESULT R0–R4、RESULT-STRUCTURED / ACS-1–5 @5729d4d](https://github.com/Notyet1307/Exposure-Agent/blob/5729d4dd2fc40cd23eb748a575ba9bc7e2d5ccab/docs/specs/exposure-focus-release-1.md#result-structured18类结构化数据接入)，同版 [接入附录](https://github.com/Notyet1307/Exposure-Agent/blob/5729d4dd2fc40cd23eb748a575ba9bc7e2d5ccab/docs/plans/cloudatlas-full-read-contract-candidate-20261003.md)、[字段矩阵](https://github.com/Notyet1307/Exposure-Agent/blob/5729d4dd2fc40cd23eb748a575ba9bc7e2d5ccab/docs/plans/exposure-focus-cloudatlas-coverage-20260923.md)及 ADR-0021/0022 结构化窄扩展；继承 ADR-0016。
- 初始批准范围为结构化数据、文档发布建单和本地实现；后续部署、真实读取的维护者确认与验收状态以当前 Issue 的最新记录为准，不从初始阶段文字推断权限。当前 Codex 主会话单写，子代理仅独立只读核验。业务代码 push／merge、文档 PR merge、保留扩展及 Issue 关闭仍须独立授权。
- 复用既有四域、独立单域 worker、固定版本和正式台账。新增类型按精确字段／能力合同准入；截图／图标文件和新请求／响应材料排除，网页哈希、企业层级／状态等未定位差额保留。不同状态不因“全部”隐式纳入，不增加风险／模型／扫描／写回或 NetFlow 关联域。
- 保留原 main/WIP、其他 worktree、已部署迁移和历史版本；原 #272、#279 等任务仍保留各自合同与验收，不由本任务更新或关闭。真实接入和前端手工复验不能由静态研究、合成或 CI 替代。
