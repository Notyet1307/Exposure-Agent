# 当前工作

- 当前任务：[EXP-FOCUS-01A #247](https://github.com/Notyet1307/Exposure-Agent/issues/247)，云图资产与风险接口合同核验；状态、依赖、材料缺口与授权只在Issue维护，本页仅为入口。
- 固定规格：[Exposure聚焦Spec@d4763e0](https://github.com/Notyet1307/Exposure-Agent/blob/d4763e0ae2da7b60773563101c5f91cb7c773840/docs/specs/exposure-focus-release-1.md)，配套[ADR-0021@d4763e0](https://github.com/Notyet1307/Exposure-Agent/blob/d4763e0ae2da7b60773563101c5f91cb7c773840/docs/adr/0021-independent-cloudatlas-local-read-model.md)与[覆盖矩阵@同版本](https://github.com/Notyet1307/Exposure-Agent/blob/d4763e0ae2da7b60773563101c5f91cb7c773840/docs/plans/exposure-focus-cloudatlas-coverage-20260923.md)。批准边界不等于执行许可；02的AI/处置替代仍为提议。
- 背景：[00接管回执](exp-focus-00-takeover-20260923.md)、[阶段定义](../plans/exposure-focus-20260923.md)；文档基线经[PR #246](https://github.com/Notyet1307/Exposure-Agent/pull/246)合并，发布衔接见[文档任务 #245](https://github.com/Notyet1307/Exposure-Agent/issues/245)。其余切片保持候选，不自动建单。
- 历史：#238/#240/#242已交付能力继续复用，其状态与关闭授权仍只在各Issue；旧Run/报告按原固定合同读取，不重开发。
- 停止线：建单与入口切换不启动01A；任何执行先核对Issue授权。资料缺失保留BLOCKED，未经精确授权的真实读取为NOT_RUN；不自动执行后续切片，不改业务源码/迁移/生成代码，不调真实云图/业务模型，不扫描/纳管/写回，不改现场数据或部署。
