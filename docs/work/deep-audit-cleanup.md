# Exposure 代码与测试清理审计

本轮按维护者 2026-10-18 的直接要求，先证明删除安全，再做本地清理及真实 Bug 修复。审计固定远端最新主线 `2b52aa1143405a7a55a0026857db422b44f99f31`，保留该版本 `docs/specs/asset-governance-release-1.md` 的行为合同。隔离分支为 `codex/deep-audit-cleanup`；原 checkout 的 Spec、current 和 plans 未提交改动保留。维护者已授权提交、push、创建 PR，必需 CI 和审阅通过后正常 merge；暂不部署。本轮未新增 Issue。

## 删除前证据

下表在删除前建立。检索覆盖 Git 跟踪的源码、测试、配置、脚本和文档；锁文件单独核对。文件路由、动态加载、模块副作用及历史兼容用途另行检查，零静态引用本身不作为充分证据。

| 候选 | 固定基线证据 | 决定 |
| --- | --- | --- |
| `frontend/src/components/ui/button-group.tsx`，83 行 | 对 `ButtonGroup`、`buttonGroupVariants` 和 `button-group` 的基线全树检索仅命中本文件；无路由注册、动态加载或模块副作用；入口 `main.tsx`、Vite 配置和测试不加载它 | 删除未使用组件；保留仍被其他组件使用的 Slot、Separator 和样式工具 |
| `@radix-ui/react-radio-group`、`@radix-ui/react-scroll-area`、`react-error-boundary`、`react-icons`、`@tanstack/router-devtools` | 包名全树检索仅命中 `frontend/package.json` 与 `bun.lock`；无 import、require、脚本或配置调用 | 删除 5 项直接依赖；实际使用的 `@tanstack/react-router-devtools` 保留，仍需要的传递依赖由 Bun 保留 |
| `next-themes` | 唯一业务引用为 `components/ui/sonner.tsx:10`；应用 `main.tsx` 挂载的是本仓库 `components/theme-provider.tsx`，没有 next-themes Provider。浏览器红用例显示 html dark、通知 data-sonner-theme light | 先修复共享 Toaster 的错误 Context，再移除失去最后一个调用方的依赖 |

复现包名检索：`git grep -n -E '@radix-ui/react-radio-group|@radix-ui/react-scroll-area|@tanstack/router-devtools|react-error-boundary|react-icons|next-themes' 2b52aa1 -- .`。复现动态入口检查：`rg -n 'import\(|import\.meta\.glob|require\(|script.*src' frontend/src frontend/index.html frontend/*.ts`，并检查 Vite 的文件路由插件。生成客户端和路由树不手改。

## 保留的代码与测试

- 后端 890 个顶层 `test_` 函数经 AST 检查，没有同名覆盖或完全相同的函数体；参数化生成的 1557 个主套件用例仍全部保留。语义相似不代表冗余，权限、期限、历史输入、失败和事务回滚分别有价值。例如 `test_failed_attempt_history_does_not_replace_regular_current` 各创建 101 个失败/自定义请求，实际覆盖 100 条分页边界、并发发布和 current 身份保护，不能因耗时或循环重复而删减。
- `report_candidate_facts.generate_run_report_candidate` 和 `agent_compose.expected_model_qualification_run_id` 目前仅有测试直接调用，但对应固定事实完整性/篡改及资格命名空间边界。没有证明迁移或删除它们后保留等价回归价值，本轮保留，不将其误报为已证明无用。
- 旧 Run、确定性报告、NetFlow 0.4.0、小文件入口、旧深链及迁移属于现行兼容合同。依据 `docs/specs/asset-governance-release-1.md`、产品 V2 `b603b45`、AI V2 `1c42406`、bulk `ee61c8c` 以及 ADR-0023/0024/0026 保留。
- 环境门控的 E2E 和 REL-003 oracle 有手动验收、package 脚本或 manifest 入口，不能因普通 CI 跳过就删除。
- Compose、模型连接、bulk 和 fixture 脚本仍由 CI、runbook 或 package 使用。完整结构化云图隔离脚本保留为人工验收工具。
- `tests/cloudatlas_structured/adapter.test.mjs` 的 29 项测试覆盖字段合同、无损 ID、null/缺失、凭据脱敏和调用前预算校验；基线缺少 CI 接线；本轮已接入 Compose CI，测试完整保留。

## 提交前本地验证记录

- 删除前：context hygiene PASS；后端 Ruff、mypy（240 文件）、ty PASS；前端 TypeScript 与生产构建 PASS；Biome 只读检查 PASS，保留既有 schema 版本提示。
- 通知主题回归：修复前 FAIL，实际读到深色页面上的浅色通知；失败日志与浏览器失败上下文保存在 `/Users/yang/.codex/worktrees/exposure-deep-audit/audit-evidence/`，与绿色结果分别留存。
- 后端：独立 PostgreSQL 18、专属合成账户和 Artifact 路径，迁移至当前 head 后执行完整 coverage 套件；不连接既有开发或生产库。**1557 passed / 0 failed，3 warnings（28 分 34 秒）**；coverage 为 **90%**（20141 statements、1992 missed），`coverage report --fail-under=90` 退出码 0。后端代码和测试相对基线无改动，该完整结果适用于最终候选。
- 清理后 `bun ci`、生产构建、Biome 只读检查 PASS；锁文件精确移除 6 项包，361 项保留记录的版本、依赖和完整性哈希不变。通知与语言回归 6/6 PASS，覆盖显式 dark/light 及 system 媒体变化。
- adapter：本机 Node 和 CI 等价 Compose 命令各 29/29 PASS；后者复用已有 OctoBus Node 24 镜像、只读挂载本次候选源码、独立 Compose project，不启动其他服务。`zizmor --offline .github/workflows/test-docker-compose.yml` PASS。GitHub 托管 CI 尚未执行。
- Codex 原生只读子代理独立 Standards / Spec 审阅均 PASS、0 blocker；不是 OMP 工具回执，也不替代独立业务验收。生产构建全量前端组件 **286/286 PASS，0 失败、0 重试（5.4 分钟）**。

## 最终状态与未决项

- 删除 83 行未使用组件、6 项直接依赖及其锁记录；删除测试 **0** 项，新增通知回归 1 项，29 项现有适配器测试纳入 CI。
- 未解决的代码 blocker 为 0；没有证明可删的后端测试入口、历史兼容代码与测试继续保留。
- 非阻断提示：Biome schema 2.3.14 与 CLI 2.4.16 不同；Starlette TestClient 的 httpx 弃用提示保留。另两个 ZIP duplicate-name 警告来自拒绝恶意归档的故意输入，不是运行失败。没有为消除提示更换依赖或削弱测试。
- 本地候选代码与测试 patch SHA256（不含本回执）：`dcc00026c0f10739cae5396c197e74f9d95dccf0f786dd4cf699bf25ed564ae5`。原 checkout 的未提交 diff 哈希在前后核对一致。
- 本轮临时 PostgreSQL、Compose 检查资源、预览进程和合成 `.env` 已清理；日志、红绿浏览器产物和 coverage 数据保存在工作树外。
- 本回执记录提交前的本地验收快照；远端 CI、审阅与合并状态以本次 PR 为准，不以此回执更新既有 GitHub Issue 状态。

## 范围限制

审计共盘点 784 个跟踪文件。深读集中于应用入口、可删候选的调用链、历史兼容边界、主题通知路径、测试及 CI 接线；不声称逐行验证全部业务代码或已排除所有缺陷。本轮不做部署、真实来源/模型调用、TB 性能验收、数据库历史清理或远端 Issue 状态修改。完整 Compose/E2E 业务验收和独立历史 REL-003 oracle 未运行；本轮后端主套件范围为 `backend/tests/`。
