# 固定 NetFlow 组件

- 文件：`netflow_processor-0.4.0-py3-none-any.whl`
- SHA256：`eba079556be6066c66eb450421571acb07afe527d46dd4e5b8b6b95c93c56d3f`
- 来源：维护者提供的 `netflow-processor/dist/` 0.4.0 构建产物，原字节复制；本仓库没有重新打包或修改组件。
- wheel 原始元数据：`netflow-processor==0.4.0`，Python `>=3.11`，`setuptools (80.9.0)`，`py3-none-any`，依赖 `jsonschema==4.25.1`。
- 原 wheel 未声明许可证。本仓库不补造 SPDX 标识、第三方许可或未提供的上游源码 commit，也不将固定二进制 Hash 表述为可从任意源码重建的证明。
- 维护者在阶段 C 明确声明“自有组件，允许公开分发”；授权记录见 [#273](https://github.com/Notyet1307/Exposure-Agent/issues/273#issuecomment-5890071682)。该授权覆盖本文件所列固定 wheel，不扩展到私有 viewer、真实客户材料或其他版本；依赖包仍保留其各自权利声明。

`backend/pyproject.toml` 与根 `uv.lock` 固定此文件；API/worker 镜像在安装前校验上述 SHA256。运行适配器同时校验已安装组件足迹，默认 rules，不提供模型或云图调用能力。组件升级须另行批准并更新固定合同与验收，不能原地替换同名 wheel。

0.4.0 的 confirmed declared_source 不产生 scope 任务，因此 `MATERIAL_CONFLICT` 在该切片不可达。维护者批准的 N6/AC-NF-11 修订保留完整状态词表，实际验收其他五种可达状态；不修改原组件或注入任务。
