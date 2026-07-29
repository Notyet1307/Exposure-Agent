# Exposure-Agent

面向多源资产数据的资产一致性治理与风险发现处置平台。

当前仓库已确认商业版架构，并已导入固定版本的管理控制面模板基线。功能架构、数据流转、技术栈、运行边界和实施顺序见：

[功能架构与数据流转架构 v0.1](docs/architecture/commercial-function-and-data-architecture-v0.1.md)

实现阶段以 FastAPI 官方
[`full-stack-fastapi-template`](https://github.com/fastapi/full-stack-fastapi-template/tree/4d3d5e92c1ea6b3fa0fab02c41124844ec45bca8)
的固定版本作为管理控制面起点，采用边界见：

[ADR-0001：使用 Full Stack FastAPI Template 作为管理控制面基座](docs/adr/0001-use-full-stack-fastapi-template.md)

## v0.1 定位

```text
初期测试：CustomerUpload + CloudAtlas SourceInstance（云图经 OctoBus）
最终交付：客户系统与云图 → OctoBus
→ 确定性资产和风险治理
→ Finding / Evidence
→ 受限 PI 报告 Agent
→ 审核、处置和复测
```

核心原则：

- PostgreSQL 是业务事实库；
- agent-compose 负责定时、触发和隔离执行；
- OctoBus 负责外部系统能力接入；
- 客户系统不可达期间使用受控文件上传完成初期测试，不把文件伪装成外部系统连接；
- Python、SQL 和 Polars 负责确定性数据处理；
- Agent 只基于有界 Evidence 生成结构化报告草稿；
- 真实动作必须经过审批、计划 Hash 和幂等控制。
- 管理控制面复用成熟模板，治理领域、调度和外部能力边界独立实现。

## 当前内容

本仓库包含商业版设计，以及从固定模板收敛出的私有化管理控制面应用壳。当前 Compose 路径由 Nginx 提供前端并同源代理 FastAPI，保留登录、Admin 用户管理、PostgreSQL 迁移、OpenAPI 客户端生成与构建测试基础；不包含临时 Demo 代码、客户数据、运行产物或尚未排期的治理领域功能。

开发与交付边界见 [development.md](development.md) 和 [deployment.md](deployment.md)。
