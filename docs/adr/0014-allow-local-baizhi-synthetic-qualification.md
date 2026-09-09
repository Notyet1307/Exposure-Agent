# ADR-0014：允许本地百智云合成样本资格测试

状态：已接受

范围依据：#204 本地验收期间，维护者于 2026-09-09 明确批准测试阶段复用本地 OMP 的百智云 provider，并批准仅向其发送固定合成资格样本的公网例外。

## 决策

默认仍执行 ADR-0006 的私网限制。仅在本地测试部署显式设置 `MODEL_QUALIFICATION_ALLOW_BAIZHI_TEST=true` 时，固定四样本 `model-qualifier` 可连接 `https://ai-api-gateway.app.baizhi.cloud/api/openai`。不接受其他 host、路径、HTTP、显式端口、用户信息、查询或 fragment 作为公网例外。DNS 必须全部解析为公网地址，连接使用本次已验证的固定地址，保留原 Host/TLS SNI；私网或 metadata 重绑定、重定向仍拒绝。

资格命令、资格状态读取和专用 Runner 共享这个显式开关；关闭开关立即拒绝该公网绑定。原有端点、模型身份、配置 revision、Runner build、资格合同与 runtime 指纹继续决定结果是否有效。配置复用 OMP 的 Responses provider 和现有凭据；凭据只进入受限部署配置与既有 Secret 注入，不进入 Git、报告、Prompt 或日志。

## 不变的业务边界

该开关只授权 `qualification_prompt()` 的固定非客户样本。产品治理草稿的绑定校验不传入此开关，继续遵循 ADR-0007 的私网限制，因此测试资格 PASS 不授权向百智云发送任何客户事实、Evidence、Artifact 或报告草稿。资格模型禁用工具、扩展、上下文文件与自动 retry，输出仍按原 Schema 和质量门禁校验。

本决策不授权生产环境启用、公网模型目录、通用代理、替代 Provider 或客户数据外发。结束本地测试后关闭开关并移除测试模型凭据；客户部署仍须用部署内模型取得当前绑定的 PASS。

这里的本地测试指维护者当前的本机部署，不等于应用的 `ENVIRONMENT=local` 安全模式：本机使用正式 Compose，backend 仍以 `ENVIRONMENT=production` 运行并保留其校验。资格例外由默认关闭的专用测试开关控制；部署操作者负责在客户生产部署前关闭它，不能通过降低应用安全模式启用测试。
