# Exposure-Agent

Exposure-Agent 面向外部暴露核查与处置：云图提供外部资产和来源依据，客户平台提供内部材料，NetFlow 提供需要复核的活动线索。当前部署形态为单客户、单实例 Docker Compose。来源观测、材料齐全、确认暴露和处置完成是不同事实。

## 当前能力

- 登录、全局 Admin、用户、Project 和 ProjectMembership 管理；
- 受控 XLSX CustomerUpload、Project 专属默认 Profile 和不可变 Artifact；
- CloudAtlas 来源经 OctoBus 按合同限定方法只读接入，保留指纹、版本与授权边界；
- GovernanceRun 的触发、Retry、Rerun、步骤状态与 agent-compose Session 边界；
- IP Observation、稳定 Resource，以及“未报备资产”“未观测资产” Finding 生命周期；
- canonical JSON、HTML 和 CSV 的确定性治理报告；
- 固定 Dataset/Context/Analysis 的 NetFlow 来源关联、证据分页和追加式材料反馈；
- 追加式业务 AuditEvent。

PostgreSQL 保存权威业务事实；OctoBus 提供外部能力边界；agent-compose 负责 Session 调度与隔离；Nginx 提供前端并同源代理 FastAPI `/api`。

## 互联网暴露面资产

项目侧栏“互联网暴露面资产”直接浏览 IP、端口服务、主域名和 DNS 的本地已发布结果，无需先有旧 Run。其余 14 个分类明确标为“未接入”，不代表零结果。业务表格与右侧详情保留原始字段；筛选结果数、版本本地条数、来源报告总量分别展示。

裸入口按[四域结果合同](docs/specs/exposure-focus-release-1.md#result-ui-a已有四域结果优先)选择可读版本；显式链接被拒绝或到期时不自动换源、换版本。“更新数据”只打开原有预算确认，“同步管理”保留来源配置、任务、版本与到期清理。浏览、检索和详情不触发来源或模型读取；“历史 Run 快照”仍使用原有固定证据与报告。

## NetFlow 首次使用与复核

项目侧栏进入“NetFlow 来源关联”，通过“导入 NetFlow 数据”使用已有 CSV/TXT 上传页。上传后进入“配置处理上下文”，由 Admin 明确填写并确认网络空间、源侧位置、NAT、观测点及采样依据，再显式启动分析。Operator 可按权限选择本地来源创建关联、补充材料；Viewer 只读。单 NetFlow 来源也可关联。

结果页先显示地址、来源与材料状态；来源版本、完整标识、原始 JSON 和 Schema 在可展开详情中。更正追加版本，旧反馈保持只读；材料齐全仍须人工复核。首次使用改动的固定规格、验收与待合并状态见 [#279](https://github.com/Notyet1307/Exposure-Agent/issues/279) 和[静态交接](docs/work/netflow-usability-handoff.md)，不代表已部署或真实客户验收通过。

## 文档入口

- [文档事实源索引](docs/README.md)
- [当前工作](docs/work/current.md)
- [当前实现与运行边界](docs/architecture/current-state.md)
- [稳定架构约束](docs/architecture/constraints.md)
- [开发说明](development.md)
- [部署与恢复](deployment.md)

[目标状态](docs/product/target-state.md) 是非规范性产品方向，不表示已经实现，也不能替代 [当前任务所固定的批准 Spec](docs/work/current.md)。第三方基座的固定来源与许可证义务见 [ADR-0001](docs/adr/0001-use-full-stack-fastapi-template.md) 和 `THIRD_PARTY_NOTICES`。
