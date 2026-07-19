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

保留：

- FastAPI、Pydantic 和 PostgreSQL；
- Alembic 数据库迁移；
- React、TypeScript、Vite 和现有组件基础；
- JWT、密码哈希、用户管理和密码恢复；
- OpenAPI 前端客户端生成；
- Pytest、Playwright、Compose 和 GitHub Actions 检查。

首期删除或禁用：

- 示例 Item 业务；
- 公开注册；
- Traefik、Adminer 和邮件测试服务；
- 与私有化交付无关的部署示例。

不从其他管理模板叠加：

- Vue Vben Admin；
- React Admin；
- Ant Design Pro；
- RuoYi 的 Redis、APScheduler 或代码生成模块。

## 业务边界

模板不提供以下 Exposure-Agent 能力，这些能力必须在独立领域包中实现：

- `Project` 和 `ProjectMembership`；
- Viewer、Operator、Approver、Admin 四个项目角色；
- `GovernanceRun`、`RunStep` 和失败恢复；
- `SourceSnapshot`、`Observation`、`Resource`；
- `Finding`、`Evidence` 和 `PolicyDecision`；
- `RemediationPlan`、`Approval` 和 `ActionJob`；
- OctoBus、agent-compose 和 PI 集成；
- 追加式业务审计 `AuditEvent`。

PostgreSQL 仍是业务事实库。模板不能成为工作流引擎、治理事实模型或外部能力网关。

## 数据访问边界

模板现有认证和用户模型使用 SQLModel。引入时删除示例 Item，并将小型用户与认证模型迁移到 SQLAlchemy + Pydantic，避免长期维护两套建模规范。此后所有模型由同一 SQLAlchemy Metadata 和 Alembic 环境管理。

## 采用门槛

正式进入治理业务开发前，只验证一条纵向链路：

```text
登录
→ 当前用户读取其 Project
→ Viewer 查看 Run
→ Operator 创建 Run 请求
→ Approver 审批
→ Admin 管理 ProjectMembership
→ 所有写操作产生 AuditEvent
```

必须满足：

- 未登录返回 `401`；
- 越权由后端返回 `403`；
- Project A 用户不能读取 Project B 数据；
- 空库和已有库都能执行迁移；
- OpenAPI 客户端可重新生成；
- 后端、前端和 Compose 检查通过；
- Polars、PyArrow、OctoBus Client 和 PI Runtime 可在选定 Python 版本安装；
- 不引入 Redis、多租户套餐或第二套调度器。

## 许可证处理

引入代码时保留上游 MIT 许可证和版权声明，并在 Exposure-Agent 增加 `THIRD_PARTY_NOTICES`。发布前生成 SBOM 并复核传递依赖许可证。

Exposure-Agent 自身的开源许可证另行确定。
