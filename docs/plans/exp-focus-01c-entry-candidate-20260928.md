# EXP-FOCUS-01C-ENTRY：入口统一接管回执

身份：2026-09-28候选形成时的只读事实快照。维护者随后确认“继续批准下一步”，批准原候选E1—E7、ACENTRY-1—8及最小替代条款，并仅授权文档发布、固定版本建单和current切换；不授权业务实施、部署、真实读取或关闭#262。

行为及验收已移至[正式Spec的EXP-FOCUS-01C-ENTRY节](../specs/exposure-focus-release-1.md#exp-focus-01c-entry统一云图原生资产账入口)，替代关系见[ADR-0021的统一云图阅读入口](../adr/0021-independent-cloudatlas-local-read-model.md#已接受的窄扩展统一云图阅读入口)。下文“当前”“本轮”“剩余”均描述接管时点，不持续同步任务状态，不恢复旧授权；正式任务、固定commit与权限只从[current](../work/current.md)及其Issue读取。[原Issue候选及分步prompt](exp-focus-01c-entry-issue-candidate.md)保留为建单前材料。

## 1. 实际核对结果与证据边界

### 工作树、版本与任务

- 核对工作树：`/Users/yet/Developer/Exposure-Agent-root-domain`，分支`fix/dns-bu-object`，HEAD `314af3dae9ab3a8edfa09ed4643c79cb098e6b9f`；进入时`git status --short`无输出。
- 受保护工作树：`/Users/yet/Developer/Exposure-Agent`，分支`feat/exposure-focus-01b-250`，HEAD `7045d0490e03722f260659f156da62d332616ce3`；已有未跟踪`.DS_Store`和`docs/.DS_Store`，未覆盖或清理。其他worktree只核对登记信息，未切换、重置或清理。
- GitHub实时main为`589c2377bc785205c9f1db482d6d31c0414ba2d0`；[PR #265](https://github.com/Notyet1307/Exposure-Agent/pull/265)已合并，head正是314af3d；[PR #264](https://github.com/Notyet1307/Exposure-Agent/pull/264)为已合并的DNS bu规格修订。开放PR列表为空。未fetch/pull、commit、push或修改远端。
- 当前文件仍指向[#262](https://github.com/Notyet1307/Exposure-Agent/issues/262)。Issue固定Spec、ADR-0022和矩阵均为`8eb2518cdf055dd1060068f8a1f80729b2b72822`；本地三文件与该commit的Git diff为空。旧云图历史合同由[#240](https://github.com/Notyet1307/Exposure-Agent/issues/240)固定`asset-governance-release-1.md`及ADR-0019@`9f9437583e0fd0acf13033104450fbd82b3a5a7f`解释。
- 实时核对最近100个全状态Issue、全部开放Issue/PR，并按“入口”“统一”“external-assets”及精确Seed-ID查重：未发现专门统一这两个入口的任务；#240是已实现的旧快照账，#250/#255/#257是已交付的新域切片，均不是本候选。正式建单前仍需重查，不能由本次快照推导未来状态。
- 589c237的部署由[#262部署回执](https://github.com/Notyet1307/Exposure-Agent/issues/262#issuecomment-5862476825)及后续产品验收回执证明；本轮未登录部署、读取业务库或重新验收运行镜像，不把远端main等同于现场运行证明。

### #262剩余事项，不扩大DNS范围

1. DNS实现及bu对象修复已经合并；不能因Issue OPEN重新开发。ACDNS-1—5有本地验证，ACDNS-6在[已完成一轮回执](https://github.com/Notyet1307/Exposure-Agent/issues/262#issuecomment-5863252272)中为PASS：20/186部分批次、11字段、本地离线阅读、实际到期EXPIRED/410、20条定界清理；这些是历史证据，不是本轮执行。
2. 最新[人工窗口](https://github.com/Notyet1307/Exposure-Agent/issues/262#issuecomment-5864058375)为另一次20/186部分批次，截止`2026-09-28T06:53:32.221Z`。它之前一次503失败保持FAILED，后续成功不是自动重试或覆盖失败。该窗口交付后，人工体验反馈仍待维护者；不能替维护者打勾。
3. 本轮只读刷新已取得`2026-09-28T06:53:35Z`发布的[最新窗口清理回执](https://github.com/Notyet1307/Exposure-Agent/issues/262#issuecomment-5864964256)：到期列表拒读、固定详情410，删除20条后本来源0条、其他65条不变，版本墓碑保留、来源停用。此为已有维护任务的聚合回执，本会话没有执行清理或远端写入；没有复用04:15窗口的PASS冒充这次清理，也未重新采集或延长保留。
4. #262原生blocking依赖接口返回空列表。代码、部署、实读和两个窗口清理均已有对应回执，剩余是维护者人工体验反馈及关闭决定；关闭未获本轮授权。统一入口另立候选，不追加到DNS旧AC，不以关闭#262作为前端复用的代码前置。
5. Issue正文含多轮历史授权和过期进度，必须按对应时间/固定版本读最新回执，不能把早期“PR OPEN/未部署”当当前状态，亦不能从新窗口继承本轮调用权。

### 大版本位置

[阶段计划](exposure-focus-20260923.md)的01仍为局部交付；四域入口合流不等于风险、附件、其余类别、周期同步或完整矩阵完成。02—05没有因本轮形成新的业务闭环。旧AI核查、人工记录、报告、NetFlow基础保留复用，不重新立项。本片对应交接手册A01/A03/A04/A05/A09/A10/A12/A21/A22及A13的**云图入口局部**；不宣称全面导航收敛或A01—A22全通过。

## 2. 数据与入口现状

以下为314af3d静态代码事实，不冒称本轮浏览器验收。

| 表面 | 当前代码及实际含义 | 本片处理 |
|---|---|---|
| 新四域 | `frontend/src/routes/_layout/projects.$projectId.external-assets.tsx:55–80,444–468,544–658`；独立来源选择、域/版本、搜索、固定详情、任务、来源配置与同步表单 | 迁入统一入口，复用页面及读取逻辑，不重写同步 |
| 新读取API | `backend/app/api/routes/external_assets.py`，`/api/v1/projects/{project_id}/external-assets/...` | 原API路径/DTO/权限/版本身份不改；UI路径不等于API改名 |
| 新本地模型与权限 | `backend/app/domain/external_asset_models.py:22,36–100`明确四域及独立ExternalSync/ExternalAssetVersion；`backend/app/domain/external_assets.py:67–91,242–313,335–371`检查来源/空间/域/版本，撤data_access_enabled为403，列表EXPIRED空数据、固定详情410 | 继续复用Project角色与SourceInstance.data_access_enabled，不新增权限模型；固定版本错误不fallback |
| 旧云图账 | `frontend/src/routes/_layout/projects.$projectId.cloudatlas-ledger.tsx:37–53,82–140`；`cloud_source/cloud_snapshot/cloud_revision`、旧画像和本地修订；后端`cloudatlas_ledger.py` | 保留历史阅读及原管理权限，显著标为“历史 Run 快照”，不转成新域版本 |
| 侧栏 | `components/Sidebar/AppSidebar.tsx:52–103`同时提供“外部资产”和“云图原生资产账”；另有旧“来源管理” | 只合并两个云图阅读项；来源管理注明旧Run用途并引导至新来源配置；其他导航不重做 |
| 项目切换 | `components/WorkspaceSelector.tsx:15–29,105–160`按路径区分两个入口，分别清理`external_*`或`cloud_*`；根页自动选Run与页面路由已有隔离 | 统一路由后按明确视图区分，项目切换清空旧来源/域版本/详情/任务，不能恢复Run前置 |
| 共享上下文与旧配置 | `frontend/src/lib/workspace.ts:142–203`仍有报告/兼容Run查询，但不是新页数据源；`frontend/src/components/CloudAtlasSources.tsx:172–281`调用旧CloudatlasSourceInstancesService的配置、验证与启停 | 不能把报告查询成功变成新阅读门禁；旧表单仅加用途澄清/新配置链接，不改为多域同步配置 |
| 旧画像消费者 | `projects.$projectId.customer-ledger.tsx`链接到旧云图账；旧报告、比较、血缘、核查仍固定Run/Resource | 这些链接明确进入历史，不改写引用，不把新域源ID当Observation/Resource |

来源是不同能力档案，不是一个可任意互换的连接：新IP/端口使用`assets-v1`，主域名`root-domains-v1`，DNS`dns-v1`；旧Run使用`legacy-ip-v1`。页面合流不合并SourceInstance，不原地换合同、不放宽唯一约束、不复制凭据或给旧Capset增权。

现有可复用检查入口：`frontend/tests/external-assets.component.spec.ts`、`frontend/tests/cloudatlas-ledger.spec.ts`；后端`backend/tests/api/routes/test_external_assets.py`和`test_cloudatlas_ledger.py`。客户/NetFlow画像、工作区导航、报告/比较/血缘的相邻回归按实际受影响链接选择，不能为了本片重跑真实云图canary。本文不引用另一工作树7045d中只有IP/端口的旧实现作为四域现状。
