# ADR-0001：使用 Full Stack FastAPI Template 作为管理控制面基座

- 状态：已接受
- 日期：2026-07-19
- 上游仓库：[`fastapi/full-stack-fastapi-template`](https://github.com/fastapi/full-stack-fastapi-template)
- 固定提交：[`4d3d5e92c1ea6b3fa0fab02c41124844ec45bca8`](https://github.com/fastapi/full-stack-fastapi-template/commit/4d3d5e92c1ea6b3fa0fab02c41124844ec45bca8)
- 许可证：MIT

## 背景

Exposure-Agent 需要登录、用户管理、Web/API 工程骨架、PostgreSQL、数据库迁移、OpenAPI 客户端和持续测试，但不需要通用多租户 SaaS、动态菜单平台、社交登录、消息中心或第二套任务调度器。

候选中的 Fast-Vben-Admin 已提供较完整的通用后台能力，但会同时引入 Vue、Redis、多租户和大量首期无关模块，且维护历史较短。FastAPI 官方 Full Stack FastAPI Template 的技术栈和运行边界与本项目更接近。

## 决策

实现阶段从固定提交 `4d3d5e9` 的 Full Stack FastAPI Template 开始构建管理控制面。它作为一次性代码基线引入 Exposure-Agent，由本项目独立维护，不自动合并上游更新。

导入时在临时目录通过该固定提交的 Copier 生成项目，所有凭据使用非生产占位值。只把产品代码、Compose、测试、OpenAPI 客户端生成和 GitHub Actions 等工程资产带入当前 Git 历史；保留本仓现有 `AGENTS.md` 与设计文档，不导入上游 `.agents/`、`.claude/`、Copier 更新元数据或真实凭据。来源提交、MIT License 和第三方声明必须保留。

保留：

- FastAPI、Pydantic 和 PostgreSQL；
- Alembic 数据库迁移；
- React、TypeScript、Vite 和现有组件基础；
- JWT、密码哈希和用户管理；
- OpenAPI 前端客户端生成；
- Pytest、Playwright、Compose 和 GitHub Actions 检查。

固定版本的基线导入和本地清理分成两个独立任务。基线导入任务只生成并验证模板，不增加 Exposure-Agent 业务模型，也不删除模板功能；确认上游 backend、frontend、Compose 和测试基线可运行后，再执行清理任务。

清理任务删除或禁用：

- 示例 Item 业务；
- 公开注册和密码恢复（包括 SMTP 配置、邮件模板及相关测试）；
- Traefik、Adminer 和 Mailcatcher（包括本地开发与 E2E 配置）；
- Sentry SDK 与配置，首期仅保留标准输出日志；
- 与私有化交付无关的部署示例。

首期账号由 Admin 创建和维护，不建设自助注册、邮件验证或密码恢复流程。
继续使用模板的邮箱字段作为唯一登录标识，但不验证邮箱所有权，也不发送账号邮件。
模板现有 `is_superuser` 直接作为全局 Admin 身份，用于管理用户、项目、成员角色和 Policy；Admin 不写入 `ProjectMembership`。`ProjectMembership` 只承载 Viewer、Operator 和 Approver 三种项目角色。
保留模板的 `FIRST_SUPERUSER` 启动引导：首次部署从环境密钥幂等创建首个全局 Admin，不接受默认凭据，也不把真实凭据提交到仓库；后续账号由 Admin 创建。
删除用户自助删除和 Admin 硬删除入口。账号生命周期只使用模板现有 `is_active`：Admin 可以停用账号，停用后禁止登录，但用户记录和历史审计关联继续保留。
保留模板现有的用户自助修改密码，并允许 Admin 直接重置密码。首期不增加临时密码过期或首次登录强制修改流程。

Traefik 删除后，由 `governance-web` 容器中的 Nginx 提供静态资源并将同源 `/api` 请求转发到 FastAPI。TLS、域名和外部入口策略由客户现有基础设施负责，本项目不再维护独立网关或自动证书逻辑。

GitHub Actions 只保留构建与测试 CI；删除模板的 staging/production 部署 workflow、自托管 Runner 配置和相关发布假设。私有化部署流程由客户环境决定。

不从其他管理模板叠加：

- Vue Vben Admin；
- React Admin；
- Ant Design Pro；
- RuoYi 的 Redis、APScheduler 或代码生成模块。

## 业务边界

模板不提供以下 Exposure-Agent 能力，这些能力必须在独立领域包中实现：

- `Project` 和 `ProjectMembership`；
- Viewer、Operator、Approver 三个项目角色；
- `GovernanceRun`、`RunStep` 和失败恢复；
- `SourceSnapshot`、`Observation`、`Resource`；
- `Finding`、`Evidence` 和 `PolicyDecision`；
- `RemediationPlan`、`Approval` 和 `ActionJob`；
- OctoBus、agent-compose 和 PI 集成；
- 追加式业务审计 `AuditEvent`。

PostgreSQL 仍是业务事实库。模板不能成为工作流引擎、治理事实模型或外部能力网关。

## 数据访问边界

模板现有认证和用户模型使用 SQLModel。首期保留这套实现，新增的 Project、ProjectMembership、GovernanceRun 和 AuditEvent 也沿用 SQLModel，共用同一 SQLAlchemy Engine、Session、Metadata 和 Alembic 环境。

只有实际业务模型遇到 SQLModel 无法满足且有可复现证据的限制时，才另立 ADR 评估迁移；模板采用阶段不预先重写已经可用的认证和用户基础设施。

## 模板采用门槛

模板采用分两步验收，不等待 Project、Run、审批或 AuditEvent 等业务功能完成：

1. 基线导入：证明固定提交生成的 backend、frontend、Compose 和原有测试可以运行。
2. 本地清理：证明登录、Admin 用户管理、数据库迁移和 OpenAPI 客户端生成仍然可用，后端、前端、Playwright、Compose 与 CI 检查通过。

清理完成后还必须确认：

- 示例 Item、公开注册、密码恢复和邮件链路已删除；
- Traefik、Adminer、Sentry 和模板部署 workflow 已删除；
- 未引入 Redis、多租户套餐或第二套调度器。

Project 隔离、角色权限、Run、审批和业务审计的纵向验收属于后续领域实现，不作为模板采用完成条件。

## 许可证处理

引入代码时保留上游 MIT 许可证和版权声明，并在 Exposure-Agent 增加 `THIRD_PARTY_NOTICES`。发布前生成 SBOM 并复核传递依赖许可证。

Exposure-Agent 自身的开源许可证另行确定。
