# 当前工作

- 当前任务：[EXP-FOCUS-01B #250](https://github.com/Notyet1307/Exposure-Agent/issues/250)，IP与端口服务的本地阅读链路；状态、依赖、材料缺口与授权只在Issue维护，本页仅为入口。
- 固定规格：[Exposure聚焦Spec@0969f0c](https://github.com/Notyet1307/Exposure-Agent/blob/0969f0c9b8cfc6e0c9c1c09ac228924ad268d5c7/docs/specs/exposure-focus-release-1.md)，配套[ADR-0021@同版本](https://github.com/Notyet1307/Exposure-Agent/blob/0969f0c9b8cfc6e0c9c1c09ac228924ad268d5c7/docs/adr/0021-independent-cloudatlas-local-read-model.md)与[覆盖矩阵@同版本](https://github.com/Notyet1307/Exposure-Agent/blob/0969f0c9b8cfc6e0c9c1c09ac228924ad268d5c7/docs/plans/exposure-focus-cloudatlas-coverage-20260923.md)。适用AC01B-1—7；批准边界不等于执行许可，02的AI/处置替代仍为提议。
- 背景：[资产先行核验回执](exp-focus-01a-contract-verification-20260923.md)、[阶段定义](../plans/exposure-focus-20260923.md)；规格修订经[PR #249](https://github.com/Notyet1307/Exposure-Agent/pull/249)合并。[01A #247](https://github.com/Notyet1307/Exposure-Agent/issues/247)保留原固定基线与未验差额，不因入口切换关闭或升级验收结果；其余切片保持候选，不自动建单。
- 历史：#238/#240/#242已交付能力继续复用，其状态与关闭授权仍只在各Issue；旧Run/报告按原固定合同读取，不重开发。
- 停止线：建单与入口切换不启动01B；任何执行先核对Issue授权。后置风险不冒称通过，未经新精确授权的真实读取/持久化为NOT_RUN，旧E12预算不沿用；不自动执行业务实现或后续切片，不改业务源码/迁移/生成代码，不调真实云图/业务模型，不扫描/纳管/写回，不改现场数据或部署。
