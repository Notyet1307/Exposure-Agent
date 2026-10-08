# 产品使用逻辑收敛 V2：本地实现与合成验收

本文件记录候选与验证证据，不代替 GitHub Issue 状态、部署回执或真实客户验收。维护者随后确认源码发布阶段授权，已推送并创建 [PR #293](https://github.com/Notyet1307/Exposure-Agent/pull/293)；CI当前状态以PR对应head的检查为准，合并/部署/关闭仍未授权。

## 身份与授权

- 实施：[#292](https://github.com/Notyet1307/Exposure-Agent/issues/292)；客户全量替换唯一归属 [#285](https://github.com/Notyet1307/Exposure-Agent/issues/285)。两票保持 OPEN。
- 固定行为：[V2 Spec @b603b45](https://github.com/Notyet1307/Exposure-Agent/blob/b603b45c853de764e47f99ccd1ed3ba98dec7c7e/docs/specs/product-logic-convergence-v2.md)、同版 ADR-0024；#285 继续固定三源 V1 U3 @c15be890。
- 文档 PR #291 已经独立 Standards/Spec 审阅并正常合并，固定提交 `b603b45c853de764e47f99ccd1ed3ba98dec7c7e`；GitHub 原生依赖 #292 blocked_by #285 已建立。此文档发布不等于业务源码发布。
- 实现分支：`codex/product-logic-convergence`；隔离树：`/Users/yang/.codex/worktrees/product-logic-convergence/Exposure-Agent`。最终源码候选与检查结果在下方固定。
- 原工作树 `/Users/yang/Test-drive-sales/Exposure-Agent` 的 main@16e451d 和三个原有 WIP 路径保持不变：`docs/specs/asset-governance-release-1.md`、`docs/work/current.md`、未跟踪 `docs/plans/`。未 reset、stash、clean 或覆盖。
- 初始交付仅本地业务实现、提交、依赖安装、合成隔离验证。维护者随后明确确认推送、建PR、观察CI：初始候选 `46fbfb9` 已推送至源码PR #293。未merge、部署/生产迁移、调用真实来源或模型、清理历史对象或关闭Issue；#287未实施。

## 实际变化

普通入口由服务端解析同作用域最新常规 C+A 发布结果，解析后固定到 URL。核心统计只有 C∪A 三类；新 NetFlow 辅证有独立固定身份与操作者明确填写的截止，读取仍经过原 Analysis reader。E 到期或撤权不会改变 C/A 分类；V1 固定三源 reader 保持失败封闭。

客户替换复用严格接受和台账读取，增加全量 preview、CAS 原子 apply、原 key 恢复。预览不改变当前，重放不逆向切换，当前文件不能通过重应用清空人工修订。被固定结果或替换回执引用的旧文件不可删除。

NetFlow 普通入口跨 Dataset 在已确认采集范围内定位最新成功可读 Analysis；合法空集不回退。原始处理时间与真实窗口分别显示；当前处理合同没有真实窗口时显示未提供。Context 新增显式采集范围及依据，旧记录不回填，不凭 current Dataset 自动合并采集范围。

导航为比对结果、云图资产、客户资产台账、NetFlow 观测；项目设置统一数据接入。客户页与接入页复用上传/替换表单；云图入口打开原有配置同步面板；NetFlow 复用 Context/Analysis 表单。固定依据与“查看当前数据”分开，返回保留结果、辅证、分类、筛选、页码和详情选择。旧 Run/报告/深链作为次级兼容入口保留。

## API 与迁移

| 能力 | 路径（前缀 `/api/v1/projects/{project_id}`） |
|---|---|
| 当前、就绪、历史 | `GET /comparison-results/current`、`/readiness`、`/history` |
| 确认、发布与回执 | `POST /comparison-results/scope-confirmations`、`POST /comparison-results`、`GET /comparison-results/operations/{key}` |
| 固定核心读取 | `GET /comparison-results/{id}/summary`、`/updates`、`/addresses`、`/addresses/{key}`、`/addresses/{key}/evidence` |
| 辅证版本 | `/comparison-results/{id}/supplements` 的 GET/POST，以及固定 binding、history、operation 和 addresses GET；移除新增空绑定版本 |
| NetFlow 当前 | `GET /netflow-results/current?collection_scope=…`；其余 Analysis/observations/peers/evidence reader 复用 |
| 客户替换 | `POST /customer-ledger/replacements/preview`、`POST /customer-ledger/replacements`、`GET /customer-ledger/replacements/{operation_key}` |

新增三条连续迁移：`f1a2b3c4d5e6`（不可变替换回执）→ `cb2920000001`（Context 范围声明）→ `cp2920000001`（C+A 发布与 E 绑定）。未改写共享迁移。身份、作用域外键、发布状态及不可变触发器在 PostgreSQL 约束；降级遇已有新事实拒绝删除。没有迁移旧 V1 身份、回填90天、延长期限或增加新调度器。

客户端由 `bash scripts/generate-client.sh` 生成；路由由原 Vite/TanStack 插件生成，无手工修改生成文件。没有新增运行时依赖。

## 验证环境与命令

合成 PostgreSQL 18 容器 `exposure-product-logic-7225f2f730-db`，仅 loopback 32801；后端 62381，开发 UI 62382，生产构建预览 62383。原 8080/8081 服务未改动。任务证据根目录为 `/Users/yang/.codex/worktrees/product-logic-convergence/evidence/`；临时环境文件权限600，不入 Git、不输出凭据。

`run-isolated.py` 与 `run-browser.py` 仅载入任务私有环境，命令主体如下。产品浏览器用例直接继承已配置环境执行 `uv run python ../scripts/seed-product-logic-acceptance.py`，不依赖任务临时wrapper路径；未配置产品fixture/evidence时普通CI跳过该专用用例，专用config明确报缺配置：

- `python3 scripts/check-context-hygiene.py`
- `cd backend && uv run bash scripts/lint.sh`
- `cd backend && uv run bash scripts/tests-start.sh`（独立 `product_full_7225f2f730` 数据库）
- `cd backend && uv run pytest tests/api/routes/test_core_comparisons.py tests/api/routes/test_customer_ledger.py::test_replacement_cannot_reset_current_manual_revision -q --tb=line`
- `cd frontend && bun run lint && bun run build`
- `cd frontend && bunx playwright test --config playwright.product.config.ts --reporter=line`
- `cd frontend && bunx playwright test --project=component --workers=1 --reporter=line …`，兼容阅读与交互预算使用生产构建预览。

浏览器 fixture 由 `scripts/seed-product-logic-acceptance.py` 在明确 `product_browser_*` 本机测试库中初始化；脚本拒绝生产/非 loopback。先 C+A 真实 UI 生成，再单独初始化 N。云图是 SQL 封存的合成发布，客户经严格 XLSX 接受及 apply，NetFlow 经真实处理器和合成控制面生命周期；没有将控制面 stub 冒称真实 agent-compose/OctoBus 验收。

## 首次失败与修复

- 浏览器最初两次等待误用了后端地址匹配 UI 代理响应、未展开“查看本次资料”；修正测试操作，真实主线通过。
- 旧 UI 测试仍预期 Source comparison/Processed NetFlow data/技术选择器和直接 select；保留固定身份/拒读断言，旧选择器转显式 history/legacy，客户改 preview→apply。缺失的新只读 metadata mock 会触发真实401；补精确 mock，不放宽产品鉴权。
- 旧 Run 交互预算在开发构建失败，原断言在生产构建重跑通过，未放宽预算。
- 独立审阅发现同当前 upload 的重应用会清除人工 revision：在 preview/apply 共享入口拒绝，新增真实 PG 回归通过。
- 额外测试第一次错误尝试发布不完整云图批次，数据库正确拒绝；改用“完整读取但有过滤范围”的合法部分覆盖 fixture。管理修订 fixture 与 Viewer 错误码断言也按实际既有合同纠正；未改生产保护换取测试通过。先前启动的全套因此主动中断，修正后重新执行。
- 兼容测试发现共享父页面在 `/users/me` 500 时提前空白，阻断原恢复控件：在共享Layout统一权限错误、重试与加载门控。43项接入/创建/跨账号/权限回归通过。
- 首次生成丢回执时的普通 latest 解析可能掩盖未恢复操作：存在原意图时暂停解析，先按原 key GET 恢复；真实 browser abort-after-commit、reload、recover 无重复发布已通过。

## 独立审阅与业务复核

Standards 与固定 Spec 由独立只读 reviewer 分轴审阅。`23a227a` 基础结论均 PASS，`8af4288` 原回执恢复和 `1bd0b81` 共享权限恢复增量分别复核 PASS。错误报告经主会话结合实际 Project 锁、路由 key、部分覆盖统计校验后撤回，真实客户替换问题修复。无尚存代码审阅 blocker。

最终独立业务 reviewer 未参与源码或验收测试编写，在固定候选 `9f8bcc34df1a06e2a9611bb096f0f07eeabd711e` 上独占合成验证窗口，执行全部3条实际浏览器流程：**3 passed，52.8s，退出0**。逐一对照 C+A计数、N补充线索、客户与核心丢回执恢复、固定依据往返、到期、真实撤权和晚响应隔离，并查看已加载实际内容的截图；结论PASS。日志 `evidence/product-browser/independent-business-final.log`。此前另一轮只完成首屏、其他操作未完成；未用该首轮局部结果替代最终独立复验。

## 源码候选与20项验收

源码候选：`1bd0b8183d1d3c5cf55df347f5312cad68a07c3f`。后续仅补充E移除断言、截图等待、隔离fixture可移植启动、旧集成测试入口适配和本回执/导航文档变化。下列 PASS 均限本轮合成、隔离验证，不代表真实客户上线验收。

| 验收 | 状态 | 本轮直接证据 |
|---|---|---|
| AC-01 C+A无需N | PASS | `test_two_source_core_http_is_fixed_and_has_no_netflow` 验证该项目三张 N 表均无行；真实浏览器先生成核心，再初始化 N。 |
| AC-02 黄金三分类 | PASS | PG黄金集3/1/1/1；N=.20/.40只让.40进入独立补充线索；明确移除E后仍为3/1/1/1。真实浏览器扩展集123/121/1/1在附加、到期、撤权后均不变。 |
| AC-03 N状态与未知范围 | PASS | 无N、主集未匹配、窗口未提供、独立绑定到期与Context撤销分别验证；范围确认与namespace失败封闭；部分覆盖只读事实，分类为null并拒绝三类筛选。 |
| AC-04 完整候选定位 | PASS | PG构造101失败尝试+102自定义发布，current仍为原常规成功；历史103项第二页3项；另验多namespace/跨project、NetFlow跨Dataset和101失败历史。 |
| AC-05 新失败不覆盖 | PASS | 并发过期CAS失败记录与latest_attempt分开；旧成功不变；浏览器current metadata503显示错误，不显示空结果。本地同步生成没有伪RUNNING。 |
| AC-06 NetFlow裸入口 | PASS | 实际处理器生成2观测，裸路由自动固定Analysis并直接读列表；scope测试禁止namespace或不同采集范围误并；处理完成时间与窗口未知分开。 |
| AC-07 合法空集 | PASS | PG新成功空Analysis优先旧非空；失败/未处理/隔离及权限路径保持错误/状态；云图合法空发布与部分覆盖也分别验证。 |
| AC-08 新资料只提示 | PASS | 已应用C替换后 `/updates=UPDATED`，旧summary逐字段不变；新版本要求确切scope确认；元数据错误不冒称无更新。 |
| AC-09 幂等和并发 | PASS | 不同key并发一201一409；同key同请求两201同ID；核心和客户真实浏览器均fetch后丢回执、刷新、GET原key恢复，业务POST不重复。 |
| AC-10 固定拒读和缓存 | PASS | 固定结果scope撤销拒读；真实已撤销Analysis深链拒读不fallback；E到期/撤权清内容，故意延迟的成功正文返回不复活；旧固定UI403/404/410回归保留。 |
| AC-11 新旧合同隔离 | PASS | E到期正文410但核心200；Context撤销使E不可读而核心200，绑定同N的旧V1整份409。没有把E到期称为Analysis TTL到期。 |
| AC-12 地址/行/端点 | PASS | 原规范IPv4/IPv6/mapped和namespace/API回归重跑；新核心复用同一地址计算；真实.20保留2客户原始行；N源侧/对端分页与原始证据独立。 |
| AC-13 总数和分页 | PASS | 真实123固定全集、25条/页、5页，三类、IP筛选、详情和证据往返；API count与页面长度分开；101+历史另有PG检查。 |
| AC-14 主流程与返回 | PASS | 普通生成/更新不调用Run；客户/云图固定版本链接带真实固定ID；返回保留结果、辅证、筛选与页码；旧显式Run、revision深链继续通过。 |
| AC-15 客户替换 | PASS | 严格接受/预览不切current，明确apply切换；全量差异、重复行、profile/revision CAS、并发/丢回执/审计失败保护；同upload重应用422保留人工修订。 |
| AC-16 独立数据页 | PASS | 18类云图目录/结构化/固定阅读34项组件回归及后端相应API检查；N浏览不请求C/A或旧Run；云图入口无N前置。 |
| AC-17 浏览只读 | PASS | 真实浏览器在初始化和明确写操作之外记录请求：筛选、分页、详情、资料往返、刷新均无业务POST。同步/处理/模型是独立操作。 |
| AC-18 权限和切换 | PASS | 真实PG Viewer写403、跨project404、归档写409读200；旧UI账号/project切换和晚响应回归；新共享权限边界500可重试且不渲染业务正文；E真实撤权及晚响应清除。 |
| AC-19 实际页面 | PASS | 真实1366/1920/390、中英、明暗、无整页横向溢出；原生表格横向阅读、键盘详情关闭；接入页各宽度及对比度/交互预算回归。列表和结论均来自实际API。 |
| AC-20 历史和迁移 | PASS | 旧Run/报告/Hash/引用相关API与UI回归；新增迁移从旧库升级保留事实；非空core降级明确RuntimeError，原summary不变；未物理清理或改写共享迁移。 |

### 执行回执

- 最终真实浏览器：`product-logic.spec.ts` **3 passed，52.7s**；生产构建62383＋实际API62381＋独立PostgreSQL。日志 `evidence/product-browser/portable-fixture-final.log`。先前同源码生产构建主线亦3 passed（`final-browser.log`）。
- 核心/客户额外PG回归：**8 passed，87.12s**，`evidence/core-regression.log`。此前客户与基础核心62项通过；NetFlow/旧关联/报告/迁移定向192项通过。
- 前端兼容：V1+旧Run **63 passed**；云图18类相关 **34 passed**；NetFlow当前/固定阅读 **12 passed**；接入、创建、账号与权限恢复 **43 passed**。共152项，使用生产构建预览，未放宽原性能/权限/固定身份断言。
- 完整后端套件：**1457 passed，3 warnings，1078.48s，coverage 90%**。标准 `scripts/tests-start.sh` 已正常退出0；日志 `evidence/backend-full.log`。随后补充验证E移除不改3/1/1/1及E到期后原Analysis仍按旧规则可读，单项2.33s通过，`evidence/evidence-removal.log`。
- 后端ruff/mypy/ty、前端Biome/build通过；Biome配置版本提示为既有信息，没有修改无关配置。context hygiene最终文档校验通过。

### 截图

截图是实际合成页面；生产构建复核没有开发工具覆盖。原图与SHA256随本记录保存；结构化回执见 [summary.json](evidence/product-logic-v2/summary.json)：

- [比对结果，1366英文亮色](evidence/product-logic-v2/comparison-1366-en-light.png)
- [比对结果，1920中文暗色](evidence/product-logic-v2/comparison-1920-zh-CN-dark.png)
- [比对结果，390中文](evidence/product-logic-v2/comparison-390-zh-CN-light.png)
- [NetFlow当前列表](evidence/product-logic-v2/netflow-en-1366.png)
- [统一数据接入与客户应用](evidence/product-logic-v2/data-access-en-1366.png)
- [固定地址与两条客户原始依据](evidence/product-logic-v2/fixed-evidence-en-1366.png)
- [辅证撤权后的核心](evidence/product-logic-v2/core-after-evidence-revocation.png)

### 尚未执行的独立阶段

真实客户数据、真实OctoBus/agent-compose/模型、生产迁移/部署、业务源码merge及Issue关闭均为 **NOT_RUN（不在本轮授权）**。业务源码push/PR已获后续明确授权并完成，必需CI按PR head独立验收。#285/#292的远端依赖与任务关闭仍由对应Issue承载；本地集成通过不关闭任何票。#287保留/清理未实施；底层历史Analysis没有新增TTL。

旧 `RUN_GOVERNANCE_E2E` / `RUN_NETFLOW_USABILITY_E2E` 专用完整栈本轮未重新启动（NOT_RUN）；仅适配显式legacy/history、数据接入和preview/apply入口，保留原断言，测试收集通过。旧Run/报告已由本轮完整后端与63项固定阅读/兼容组件检查覆盖，不将此结果冒充上述专用栈端到端回执。

主会话与独立reviewer的3条正式真实浏览器验收分别通过，静态两轴审阅和业务验收分别记账。没有留下待修复的产品blocker。


## 修改文件

业务源码固定于 `1bd0b81`；清单包含后续测试与交付文档；另随仓库保存 `docs/work/evidence/product-logic-v2/` 下8张合成截图及 `summary.json`。

```text
backend/app/alembic/env.py
backend/app/alembic/versions/cb2920000001_add_netflow_collection_scope.py
backend/app/alembic/versions/cp2920000001_add_core_comparison_results.py
backend/app/alembic/versions/f1a2b3c4d5e6_add_customer_upload_replacement_receipts.py
backend/app/api/main.py
backend/app/api/routes/comparison_results.py
backend/app/api/routes/customer_ledger.py
backend/app/api/routes/netflow_processing.py
backend/app/domain/comparison_models.py
backend/app/domain/comparison_results.py
backend/app/domain/customer_ledger.py
backend/app/domain/customer_uploads.py
backend/app/domain/models.py
backend/app/domain/netflow_models.py
backend/app/domain/netflow_processing.py
backend/tests/api/routes/test_core_comparisons.py
backend/tests/api/routes/test_customer_ledger.py
backend/tests/api/routes/test_netflow_processing.py
backend/tests/api/routes/test_source_correlations.py
backend/tests/utils/netflow_processing.py
docs/work/current.md
docs/work/product-logic-convergence-20261008.md
docs/work/product-logic-v2-validation.md
frontend/playwright.product.config.ts
frontend/src/client/schemas.gen.ts
frontend/src/client/sdk.gen.ts
frontend/src/client/types.gen.ts
frontend/src/components/Common/Logo.tsx
frontend/src/components/ComparisonReturnLink.tsx
frontend/src/components/CoreComparisonResults.tsx
frontend/src/components/ExternalAssets.tsx
frontend/src/components/NetFlowDatasets.tsx
frontend/src/components/NetflowContextForm.tsx
frontend/src/components/NetflowInputManagement.tsx
frontend/src/components/NetflowResults.tsx
frontend/src/components/ProjectPreparation.tsx
frontend/src/components/Sidebar/AppSidebar.tsx
frontend/src/components/WorkspaceSelector.tsx
frontend/src/lib/assetSearch.ts
frontend/src/lib/comparisonReturn.ts
frontend/src/lib/workspace.ts
frontend/src/routes/_layout.tsx
frontend/src/routes/_layout/index.tsx
frontend/src/routes/_layout/projects.$projectId.cloudatlas-ledger.tsx
frontend/src/routes/_layout/projects.$projectId.customer-ledger.tsx
frontend/src/routes/_layout/projects.$projectId.netflow-correlation.tsx
frontend/src/routes/_layout/projects.$projectId.netflow-results.tsx
frontend/tests/customer-ledger.spec.ts
frontend/tests/customer-upload.spec.ts
frontend/tests/dashboard.component.spec.ts
frontend/tests/first-comparison.component.spec.ts
frontend/tests/first-comparison.spec.ts
frontend/tests/governance-run.spec.ts
frontend/tests/netflow-correlation.component.spec.ts
frontend/tests/netflow-results.component.spec.ts
frontend/tests/netflow-usability.spec.ts
frontend/tests/product-logic.spec.ts
scripts/seed-product-logic-acceptance.py
```
