# NetFlow 来源稳定性与首次使用：静态交接

此快照记录 #279 的候选代码和本次合成验收，不是实时任务账。任务状态、依赖与授权仅以 [#279](https://github.com/Notyet1307/Exposure-Agent/issues/279) 为准。

## 固定身份与边界

- 接管的远端 main：`f1f3be9e54308d2e125e1fdba6f8e886305b14b8`，包含 #277/#278。
- 批准 Spec：`85c360edc1f88718895ff8da9f978742f3c24bd0` 的 `docs/specs/exposure-focus-release-1.md` NU0–NU3、AC-NU-*，`docs/specs/netflow-correlation-api-v1.md` 第 8 节及 ADR-0020 窄扩展。
- 分支：`codex/netflow-usability`。阶段 A：`36b8d4ca33195823a601d3533c11960c5bc73df5` 与 `32e6882d07dcf00e3098465c0e437e11864e3e63`；阶段 B：`e4f747aec45da68f1b58893e46e9f0c6c304d8e1`；测试脚本 import 整理 `3dd2b3526b978283bdfe3ca39e294b7a99b750f1`；真实恢复/晚到响应验收 `eef5150`。PR：[\#280](https://github.com/Notyet1307/Exposure-Agent/pull/280)，未合并且未启用自动合并。
- 原工作区的 main 与未提交 Spec/current/plans 保持原样；所有候选变更在独立 worktree。
- 仅合成数据、隔离凭据和任务 PostgreSQL。未调用真实客户或业务模型，未扫描，未合并、部署、生产迁移或关闭 Issue。合成通过不代表 AC-NF-15 真实客户验收。

## 改动与入口

A 修复关联目录被自然到期记录阻断：先项目授权，只排除明确到期/撤权记录，在同一可读集合上计数和分页，完整性/未知错误继续失败。数据库先做明确筛选，材料验证采用流式迭代和有界请求内指纹缓存。准确 count 仍需检查筛选范围的各个关联；未增加持久化读取回执或省略完整性校验。

A 同时保留 URL 显式空值/非法值并校验完整固定身份，缺省身份才从权威修订补全。全部历史选择器使用 25 条分页，必要的固定 ID 元信息查询沿原权限过滤。没有历史/latest 自动替代。

B 用户入口：项目侧栏“NetFlow 来源关联”→“导入 NetFlow 数据”→既有 CSV/TXT 上传→“为刚上传的数据配置处理上下文”。Admin 明确提供并确认上下文后点击分析；Operator 可使用已有确认上下文并补充材料，Viewer 只读。单 NetFlow 来源即可创建固定关联。

B 复核入口：固定关联的“复核任务”→选择任务→按字段填写、明确声明提供方/时间→追加更正→读取父修订。未填写、null、空串、false、0 保持区别；部分材料可以保存，完整材料仍等待人工复核。实际提交账号/时间与提供方声明分开保存；旧版本只读、计数和分页不随新更正漂移。

B 结果页将完整 ID、Hash、JSON、Schema 与逐条来源比较折叠。来源、状态、错误和下一步有中英文业务文案，覆盖限制、获取/保留时间仍显示。上下文、分析、关联、范围、反馈使用同一明确拒绝/不确定结果区分，冲突 key 保留原操作恢复。

涉及文件范围：后端 `source_correlations`、既有数据集/客户上传/Context/云图版本/旧快照列表和测试；原生成工具更新的 SDK/types；前端 NetFlow 关联/上下文/答案/筛选/恢复组件、必要上传与项目选择入口；组件 fixture、独立全栈配置与脚本。历史接口样例/Hash 和旧验收保持原字节，旧文档增加静态身份说明。

## 证据与验收分层

本轮开发环境证据根目录为 `/tmp/exposure-nu279`；原型运行的独立证据目录由脚本打印。日志和生成凭据在受限本地目录，秘密、完整请求 trace 与运行 Artifact 不入 Git。

| 层次 | 本快照的结果 | 证据 |
|---|---|---|
| A 后端定向回归 | 22 PASS；混合/跨页/全到期/空集、项目拒绝、撤权、损坏、未知错误、101 条 count/page、固定详情 | `a-directory-tests.log` |
| 后端全套 | 1360 PASS，3 warnings，754.05s，90% coverage；覆盖 B 的最终后端源码（后续仅前端验收和脚本文档） | `backend-tests.log`、`backend-tests-final.log` |
| 后端 lint/type | PASS，214 个 mypy 文件、ruff、ty | `b3-backend-lint.log` |
| 实际 Schema 一致性 | 18 个 processor 集成测试 PASS；六类答案 fixture 与固定 0.4.0 wheel 的 inline answer schema 一致，未引用的定义不复制 | `b3-schema-test.log` |
| Mock 组件测试 | 全部 211 PASS（`eef5150`）；本轮 30 项含七类目录 101 记录/后页、固定身份、恢复和表单边界 | `frontend-final-components.log` |
| 前端 lint/build | PASS；已有 Biome 配置 schema 版本提示不影响退出码，未升级工具链 | `b-final-lint.log`、`b-final-build.log` |
| 真实 API/worker 与页面 | PASS @干净 `eef5150`：新项目、页面上传/Context、真实响应丢失后原操作恢复、真实 worker、三源 TLS 同步、部分/更正/历史、共享依赖、真实晚到反馈响应、停止上游后 GET-only 分页/角色/到期/跨项目/撤权 | `harness-final.log`；完整运行证据 `/private/tmp/exposure-netflow-usability-azdzazg0/{result.json,browser-result.json,harness.log}` |
| 自然到期/跨项目 | 到期固定详情 410，目录 3→2，有效固定详情 200；跨项目 404 | `retention-check.log` |
| 独立 Standards | PASS；Context 409 恢复、harness 输出目录保护与固定构建身份的问题均修复后独立复核 | 独立审阅记录随 Issue/PR 回执 |
| 独立 Spec | A 与 B UI 分别复核 PASS，无遗留 P1/P2；不替代业务验收 | 独立审阅记录随 Issue/PR 回执 |
| 独立业务验收 | PASS：服务材料先等待共享依赖，补齐导出后两者待人工复核，task_closed/facts_changed 均 false；历史页哈希稳定 | `acceptance-postcheck-result.json`、`acceptance-postcheck.log` |
| 布局与交互 | 独立验收 390/1366/1920、CN/EN、Tab、summary Enter、reduced-motion PASS；复核阶段零 POST | `acceptance-postcheck-*.png` |
| CI | 本静态快照提交时尚在运行；最终结果读取 [PR #280 Checks](https://github.com/Notyet1307/Exposure-Agent/pull/280/checks)，以其确切 head 为准 | 最终 PR 回执补充 |
| 真实客户 AC-NF-15、生产部署 | NOT_RUN；本轮未授权 | 不以合成样本替代 |

## 可复用全栈入口

前提：使用已提交且干净的候选 checkout（执行期间保持 HEAD/工作树不变）；本机 Docker Desktop/OrbStack 提供 `host.docker.internal`，已安装项目的 uv/bun 依赖和 Playwright Chromium；能够构建仓库原 runner/OctoBus 镜像。此入口不连接既有开发库。

```sh
python3 scripts/test-netflow-usability.py
```

脚本创建随机名称的 PostgreSQL、固定 digest agent-compose、合成 TLS 上游与 OctoBus，只注册 `netflow-processor`/`cloudatlas-sync`。API/UI 使用私有临时工作目录与随机 loopback 端口，不读取仓库 `.env` 或继承模型凭据。测试实际使用 `frontend/playwright.netflow.config.ts`。源码与运行时的 build version、结果、诊断、截图保存于打印的证据目录。

正常/失败退出都只移除本次容器、guest 与网络，保留证据；`--keep` 可保留本次容器用于诊断。`--output` 必须是空目录。未修改数据库业务行来伪造 Context/Analysis/Correlation；migration/init 只针对新建测试库。

## 停止线与具体下一步

A/B 实现、本地验证、独立双轴审阅和独立业务验收已完成，无已知代码 blocker。真实客户 AC-NF-15、部署和生产迁移仍 NOT_RUN。此文档提交后的 CI 状态仅在 #279/#280 更新，不建立第二个实时状态账。

下一会话先执行 `gh pr view 280 --json state,headRefOid,baseRefOid,mergeStateStatus,autoMergeRequest` 和 `gh pr checks 280`，核对当前 head 与本轮代码身份。若有失败，只处理该 head 的失败日志；所有必需门禁通过后，等待维护者明确决定是否合并。不要重开已通过的 A 行为或重造旧数据。

最终交付后由维护者决定合并；本轮不得自动 merge/deploy/close。后续仅记录“新来源对象接入核查”候选：需另定受支持对象、输入 Evidence、权限与独立 Spec/Issue，不实现新的问题、交办审批或处置生命周期。
