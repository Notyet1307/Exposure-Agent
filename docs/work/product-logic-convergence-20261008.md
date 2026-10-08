# 产品使用逻辑收敛：2026-10-08 接管与阶段 A 回执

本文件是候选/证据入口，不是任务状态表。GitHub Issue 仍是唯一任务状态、依赖与授权表面。新 V2 规格已由文档 PR #291 合并固定为 `b603b45`，正式实施为 #292，客户替换仍为 #285。后续实现与验收见 [本地验证记录](product-logic-v2-validation.md)。下列阶段 A 接管事实保留其发生时状态，包含当时尚未完成的门禁。

## 接管事实

- 主工作树 `/Users/yang/Test-drive-sales/Exposure-Agent`：`main@16e451d21967dcedeb4c1d4d6afd988d64de38ab`。已有修改为 `docs/specs/asset-governance-release-1.md`、`docs/work/current.md` 和未跟踪 `docs/plans/`，全部原样保留。未 reset/clean/stash。
- 本轮 `git fetch origin` 后 main=`6c0f9f78a85f3162c3b128ca48fbc59184a69b49`，与外部审阅基线相同。未合并 PR 列表为空。
- 隔离工作树 `/Users/yang/.codex/worktrees/product-logic-convergence/Exposure-Agent`，分支 `codex/product-logic-convergence`，从上述最新 main 创建。
- #284/#286 已关闭，PR #288 已交付；#289 已关闭，PR #290 已合并。此处只核对 GitHub 回执与当前源码，未重新证明其部署/历史测试。
- #285 OPEN，批准合同为三源 V1 U3/AC-3S-04/05/09/12/13 @`c15be890eac8bf5044b891c9feccfa3ce7da6f68`；#284 依赖已关闭。本轮客户替换只有此归属，可按旧批准合同独立实施。
- #287 OPEN；90天/清理尚未实施，不纳入本轮。NetFlowAnalysis 当前模型没有结果 TTL 字段，不以 ADR 已接受冒称实现完成。
- 本轮规格：[V2 Spec](../specs/product-logic-convergence-v2.md)、[ADR-0024](../adr/0024-core-comparison-and-optional-netflow-evidence.md)、[实施 Issue 草稿](../plans/product-logic-convergence-issue.md)。V2/ADR已获维护者批准；此文档分支尚未合并，正式Issue尚未建立，新核心实施仍须完成固定规格与正式任务衔接。

## 代码差距与复用

行号以接管基线为准；后续实现可移动。

| 现状与证据 | 根因 | 复用能力 | 必要修改 | 对应测试 |
|---|---|---|---|---|
| `NetflowCorrelation.tsx:727` 固定 summary/身份校验；`Common/Logo.tsx:71` 与 `Sidebar/AppSidebar.tsx:62` 保留固定 query | #284/#290 已解决固定刷新与导航部分问题 | 原 reader、加载/重试、摘要和全量分页 | 不重复开发；仅接新 V2 默认入口与保留回归 | `netflow-correlation.component.spec.ts:126/182/226/277` |
| `source_correlations.py` 的 `materials/read_material/addresses` 已支持 N=null；加入N仍扩张集合 | 旧三源合同的正常行为，非后端强制必须三源 | C/A固定pins、规范IP全集、证据reader | 新常规核心只含C/A；新辅助绑定另读，V1不改 | `test_source_correlations.py:235/418/545/678/855/896`，另加AC-01/02/03/11 |
| `NetflowCorrelation.tsx:559` 只分页列已有修订；无普通最新核心解析 | 没有V2用途/常规发布与范围化latest服务 | 可读目录先过滤后count/page | 服务端完整候选定位、资料更新/就绪与预期发布修订；返回固定ID | 现有`test_source_correlations.py:1009/1120/1138`，另加AC-04/05/08/09 |
| `NetflowResults.tsx:245/256/408` 先选Dataset再Analysis；处理结果查询已交付 | 当前列表仅按Dataset，缺跨Dataset确定采集范围的默认解析 | Analysis封存校验、observations/peers/evidence | 服务端范围化latest成功解析，分开完成时间/窗口/最新尝试；合法空不回退 | `netflow-results.component.spec.ts:120/185/327/349/402`；`test_netflow_processing.py:182` |
| `ProjectPreparation.tsx:56/88/114` 用连接/原Dataset表达ready；`:149` 指向runs | 旧Run启动前置仍被普通入口复用 | `index.tsx:219` ProjectInputs、CloudAtlasSources、NetFlowDatasets/Context/Analysis表单 | 连接/接受/发布分层；统一数据接入并重接正常生成；旧显式runs保留 | AC-14/17/18；原导航/旧Run回归 |
| `index.tsx:219/274` 上传后独立select；客户ledger已有修订CAS | #285未实现全量预览/明确原子应用；旧select没有expected/key | 严格接受、`customer_ledger.save`事务/审计/恢复 | 在#285中补preview/apply/recover及表单复用，不平行新建任务 | `test_customer_uploads.py`、`test_customer_ledger.py`、`customer-ledger.spec.ts`；AC-15 |
| `ExternalAssets.tsx` 已有分页元数据默认解析/18类独立阅读；根页`:659/680/690`仍拆inputs/cloudatlas/runs | 接入组织未合并，返回上下文尚未统一 | 云图现有reader与同步表单；WorkspaceSelector已有独立数据路径 | 只改入口衔接与固定依据返回，保留18类/明确历史参数 | `external-assets/structured/directory.component.spec.ts`；AC-14/16 |
| 旧关联`read_material`逐一验证所有选中依赖；Analysis无结果TTL | V1失败封闭与#287未实施是两件事 | 原权限/期限/完整性检查 | 新辅证独立状态；只消费实际期限，无90天回填或清理 | 旧`test_unreadable_selected_analysis_is_not_a_two_source_success`必须保留；另加AC-10/11/20 |

采集范围不能由 `current_netflow_dataset_id` 单独证明；它最多提供已显式选择的输入线索，仍须检查Context/namespace/来源与窗口资格。不得把不同Dataset自动当同一范围。

只读候选审阅发现并修订三项：明确V2常规用途/发布状态/时间排序；明确可信采集范围和窗口未知；明确Analysis无TTL。为满足本轮辅证独立到期，新Spec另提议仅在新E_j绑定上固定操作者显式截止，无90天默认/旧数据回填；其审批不等于#287获准或已完成。

## 阶段和验证回执

阶段 A 的只读核验与维护者规格批准已完成，尚待文档正常合并和正式Issue固定；B/C/D的新核心行为尚未实施。#285与新合同无行为冲突，可在同一会话按既有固定合同独立完成本地实现与验证。源码同树只由一个写入者修改。

本轮20项业务验收的初始记录均为 **NOT_RUN**：AC-01、02、03、04、05、06、07、08、09、10、11、12、13、14、15、16、17、18、19、20。规格待固定不等于功能FAIL；旧测试/部署回执不改记本轮PASS。实际实施后逐项在本文件追加命令/操作/证据与失败和复测，不能仅改勾选。

待运行的正式命令：`python3 scripts/check-context-hygiene.py`；`cd backend && uv run bash scripts/lint.sh`；`cd backend && uv run bash scripts/tests-start.sh`；`cd frontend && bun run lint`；`cd frontend && bun run build`。真实API/隔离PostgreSQL及Playwright主线按已发现的`frontend/playwright.netflow.config.ts`、`scripts/test-netflow-usability.py`复用/扩展；不得在既有8081生产数据上初始化测试。后者要求固定干净候选SHA，不可把未提交树当精确构建身份。

截图尚未生成，不交付静态原型冒充真实产品页。目标四类截图为比对结果、NetFlow当前列表、数据接入、固定证据返回；只使用隔离合成资料。真实来源/模型调用、生产数据改动、push、PR、merge、部署与Issue关闭均未执行。

## 后续批准与下一门禁

维护者于2026-10-08明确回复“批准候选及上述规格发布、建单范围”，针对本地候选`554e80e8ce172f6b208e2dae85deeec7daf17816`。批准包含V2/ADR0024、新辅证绑定显式截止、仅规格文档push/PR、必需CI/Review后merge及新实施Issue。下一步执行该范围，新Issue引用真实固定路径/commit，客户替换仍唯一归#285。业务源码的push/PR/merge、部署及真实调用不包含在这项规格衔接中。原门禁来源为AGENTS、ADR-0016及用户附件§0.5–0.7；不是技能额外设置的审批。
