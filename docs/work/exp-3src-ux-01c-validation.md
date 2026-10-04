# EXP-3SRC-UX-01C 本地验证记录

任务：[GitHub #286](https://github.com/Notyet1307/Exposure-Agent/issues/286)，固定行为为[三源工作台 U4/U6 @c15be89](https://github.com/Notyet1307/Exposure-Agent/blob/c15be890eac8bf5044b891c9feccfa3ce7da6f68/docs/specs/three-source-workbench-v1.md)。本记录不替代 Issue 状态、依赖或授权。

## 实现范围

基于本地 `0292ee8`，新增独立处理结果页与原侧栏入口。用户明确选择上传数据与已封存 Analysis 后，可以分页、筛选并读取源侧观测、详情、输入引用与单独的外侧对端。原始行、源侧记录、观测对象、不同 IP 分开计数；批次时间不冒充观测时间。查询不需要来源关联或 GovernanceRun，不创建新处理或调用来源/模型。

两个新增 GET 端点复用原 `analysis_material`，前端复用原 Processing/Reviews/Projects 客户端与 UI 组件。客户端由 `scripts/generate-client.sh` 生成，路由由 Vite/TanStack 生成。没有 Schema 迁移、第二份资产主表、依赖包或新调度器；#287 的新结果期限与清理未在本任务实现。

## 候选检查

| 检查 | 状态 | 证据 |
|---|---|---|
| 后端相关 API | PASS | 8 项；真实组件产物，31 观测/30 IP/86 原行、25+6 分页、精确筛选、合法空、全隔离/未完成、跨项目/撤权/损坏拒读 |
| 后端 lint/typecheck | PASS | Ruff、Mypy 219 文件、ty |
| 新页面组件 | PASS | 10 项；固定批次、完整分页/筛选/证据、独立 peer、无隐式关联或写请求、失败批次、403/404/410 清缓存、显式身份拒绝与手动选批次 |
| 前端 lint/正式 build | PASS | 仓库正式 TypeScript build；原有 Biome 版本提示为 informational |
| 全量前端组件 | 执行中 | 正式构建预览，单 worker；未用局部结果代替全量结果 |
| 全量后端 | 执行中 | 任务专属 PostgreSQL 数据库，未接入真实数据 |
| Standards 独立审阅 | PASS | 固定工作补丁 `4d1660e0a6ab848fc4589a2f7ccd6a27e92248b918b19c25e1f58bf3262cbf14`；无硬违反或需报告的气味 |
| Spec 独立审阅 | PASS | 同一补丁，U4/U6 与本票 AC，无 blocker；不把未来 #287 算入本票 |
| 隔离真实 worker/API/浏览器 | NOT_RUN | 已扩展既有主线，等待干净候选提交；需证明创建关联前能独立查询，停上游后继续读取，Viewer 只读及云图撤权后 NetFlow 仍可读 |
| 新保留期/清理、真实客户三源 | NOT_RUN | 分属 #287 与后续获准现场验收，不能由本票的合成 410 或合成资料证明 |

新增列表/详情 API 和正式页面先观察到失败，再实现并通过。首个分页实现与父路由 `page` 参数发生冲突，组件测试发现后改为本页独立 `resultPage`，未改其他页面语义。首轮构建的链接 Search 类型及 ARIA 错误已修复；不降低 lint 或类型约束。

本机证据：`/Users/yang/.local/share/exposure-agent/three-source-workbench-20261004/`。测试凭据与 Artifact 在任务私有根中，不提交或转发。

## 发布边界

本地候选提交用于固定真实全栈验收。源码 push/PR/merge、真实迁移部署、数据清理、真实来源/模型调用及 Issue 关闭均未执行。完整测试与业务主线结果须另行回收后更新；当前没有把本票或依赖票宣布为 GitHub 已完成。
