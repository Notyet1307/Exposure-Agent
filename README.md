# Exposure-Agent

Exposure-Agent 是面向多源资产数据的资产一致性治理与风险发现平台，当前以单客户、单实例 Docker Compose 方式私有化部署。

## 当前能力

- 登录、全局 Admin、用户、Project 和 ProjectMembership 管理；
- 受控 XLSX CustomerUpload、Project 专属默认 Profile 和不可变 Artifact；
- CloudAtlas SourceInstance 经 OctoBus 单方法只读接入、指纹校验和启停；
- GovernanceRun 的触发、Retry、Rerun、步骤状态与 agent-compose Session 边界；
- IP Observation、稳定 Resource，以及“未报备资产”“未观测资产” Finding 生命周期；
- canonical JSON、HTML 和 CSV 的确定性治理报告；
- 追加式业务 AuditEvent。

PostgreSQL 保存权威业务事实；OctoBus 提供外部能力边界；agent-compose 负责 Session 调度与隔离；Nginx 提供前端并同源代理 FastAPI `/api`。

## 互联网暴露面资产

项目侧栏“互联网暴露面资产”直接浏览 IP、端口服务、主域名和 DNS 的本地已发布结果，无需先有旧 Run。其余 14 个分类明确标为“未接入”，不代表零结果。业务表格与右侧详情保留原始字段；筛选结果数、版本本地条数、来源报告总量分别展示。

裸入口按[四域结果合同](docs/specs/exposure-focus-release-1.md#result-ui-a已有四域结果优先)选择可读版本；显式链接被拒绝或到期时不自动换源、换版本。“更新数据”只打开原有预算确认，“同步管理”保留来源配置、任务、版本与到期清理。浏览、检索和详情不触发来源或模型读取；“历史 Run 快照”仍使用原有固定证据与报告。

## 文档入口

- [文档事实源索引](docs/README.md)
- [当前工作](docs/work/current.md)
- [当前实现与运行边界](docs/architecture/current-state.md)
- [稳定架构约束](docs/architecture/constraints.md)
- [开发说明](development.md)
- [部署与恢复](deployment.md)

[目标状态](docs/product/target-state.md) 是非规范性产品方向，不表示已经实现，也不能替代 [当前批准 Spec](docs/specs/asset-governance-release-1.md)。第三方基座的固定来源与许可证义务见 [ADR-0001](docs/adr/0001-use-full-stack-fastapi-template.md) 和 `THIRD_PARTY_NOTICES`。
