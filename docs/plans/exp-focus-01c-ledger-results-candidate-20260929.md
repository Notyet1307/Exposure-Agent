# 结果台账审定记录与前端设计候选（2026-09-29）

维护者先选择“对齐资产与暴露面的完整信息”，在候选交付后明确“继续下一步”。结果结构、完整覆盖、本地检索、准入与验收条款已迁入[正式Spec的RESULT节](../specs/exposure-focus-release-1.md#exp-focus-01c-result云图资产与暴露面结果台账)，配套[ADR-0021结果台账扩展](../adr/0021-independent-cloudatlas-local-read-model.md#已接受的扩展结果优先的完整台账)。本文只保留问题来源与交接边界，不再维护第二份行为合同。

前两节保留`0756d25`之前的审定与交接记录；后续push事实及本轮设计回收与确认回执见下方“RESULT前端设计回收”。历史授权措辞不代表本轮权限。

## 审定依据

维护者反馈：“我要的资产台账应该是类似把云图的界面的信息复刻下载，在 Exposure 上面也展示，现在云图原生资产账只有过程看不到结果和展示。”所选范围不是四域限定方案，也未加入风险与检测依据；既有资产导航中的种子信息只读呈现，管理动作不在范围内。

代码基线 `6eeb02bba406878a3a5e306e353e7ca0a1fea3a9` 中，[页面](../../frontend/src/components/ExternalAssets.tsx)先展示来源/同步/任务，再展示记录；详情先技术身份后业务属性。[本地模型](../../backend/app/domain/external_asset_models.py)和[OctoBus合同](../../octobus/README.md)仅承接四域。到期样本不可读不能解释展示层级的不足，也不授权恢复样本。

字段、公开接口和截图转述仍只在[同一覆盖矩阵E14补证](exposure-focus-cloudatlas-coverage-20260923.md#2026-09-29结果台账补证静态)记录；公开声明与现场证据分开。迁移保留全部18类已定位信息、网页哈希/企业层级状态/响应包/图片等差额，以及全部10条ACRESULT，不以样本或单片代替完整交付。

## 固定与交接

本轮批准并固定本地文档，不修改业务代码，不发起真实来源/模型调用、部署或远端操作。批准结果要求不等于新增来源/材料合同已经闭合；具体依赖继续遵守正式Spec的R3，不猜字段/方法或默认为无限保留。

收到明确发布授权后，走文档push/PR/正常CI与Review/merge，再用实际已发布commit及Seed-ID `EXP-FOCUS-01C-RESULT`查重建单或复用任务，并绑定Spec、ADR与矩阵后切换current。本地提交不能冒称已发布固定版本；没有实际Issue不编造编号。业务实现、真实读取、部署和关闭分别授权。

当前正式任务和权限仍只读[current](../work/current.md)所指Issue；#267的ENTRY固定合同与历史结果、#262及其他旧任务不因本次审定改义或关闭。

## RESULT前端设计回收：布局与A范围已确认

### 设计回收时的基线与证据层级

- 仓库`Notyet1307/Exposure-Agent`，工作目录`Exposure-Agent-root-domain`，分支`docs/cloudatlas-ledger-results-candidate`，HEAD `0756d25f3be7968340873478e325a3c0c25af74f`；设计回收接管时工作区干净。该轮未改生产前后端、正式Spec/ADR/矩阵、current、生成文件或部署环境，未提交Git；后续确认的本地条款迁移见末节。
- 当前Issue仍为[#267](https://github.com/Notyet1307/Exposure-Agent/issues/267)，本轮只读核对为OPEN，updatedAt `2026-09-29T03:45:35Z`。其合同仍是[ENTRY Spec@59c3c86](https://github.com/Notyet1307/Exposure-Agent/blob/59c3c86b6ac4afeaea2b9ccf5f6847317f3bed56/docs/specs/exposure-focus-release-1.md#exp-focus-01c-entry统一云图原生资产账入口)。最新回执记录ENTRY主题修复已合并、frontend-only部署到`6eeb02b`；这是旧任务回执，不是本轮现场复验或RESULT许可。
- 本轮GitHub只读compare返回`main=6eeb02bba406878a3a5e306e353e7ca0a1fea3a9`、基线ahead=1/behind=0；按分支查询全部状态PR返回空。`0756d25`已push且可远端读取，但当次核对尚未合并main、未有该分支PR；未核验部署环境，不推导RESULT已部署。上文“仅本地固化”是历史审定记录，后续push已由维护者单独授权完成。
- 行为唯一依据为[RESULT R0—R4/ACRESULT-1—10@0756d25](https://github.com/Notyet1307/Exposure-Agent/blob/0756d25f3be7968340873478e325a3c0c25af74f/docs/specs/exposure-focus-release-1.md#exp-focus-01c-result云图资产与暴露面结果台账)，配套[ADR-0021结果台账扩展@同版](https://github.com/Notyet1307/Exposure-Agent/blob/0756d25f3be7968340873478e325a3c0c25af74f/docs/adr/0021-independent-cloudatlas-local-read-model.md#已接受的扩展结果优先的完整台账)、[唯一覆盖矩阵E14@同版](https://github.com/Notyet1307/Exposure-Agent/blob/0756d25f3be7968340873478e325a3c0c25af74f/docs/plans/exposure-focus-cloudatlas-coverage-20260923.md#2026-09-29结果台账补证静态)。四域继承`8eb2518cdf055dd1060068f8a1f80729b2b72822`，旧Run继承`9f9437583e0fd0acf13033104450fbd82b3a5a7f`；不重做全项目P0、01A、ENTRY或四域采集。
- 输入为维护者提供的`Exposure_前端交互样稿.html`、`Exposure_前端改版评审与OMP提示词.md`；原附件保持不变。HTML SHA-256 `1fe3fa6c9366f5624d19b99e6947b7f743a04b0b8145fee3b7d7d435b078ad78`；说明SHA-256 `dafb3acd2add38a2d68fd294150b4389d3a614597629fd4b8b370836b8d4f18d`。附件及本节都是视觉/接线候选，不是新增字段、权限或实现事实。

### 打开与审阅

双击[独立交互HTML](result-ui-prototype-20260929.html)，或从仓库根目录执行`open docs/plans/result-ui-prototype-20260929.html`。无需安装、服务、登录或生产环境；所有数据为手工模拟，CSP禁止连接与外部资源，状态仅在内存。保留附件的单一布局，不为本轮另造多个产品页面或生产路由。

四域可切换、规定字段搜索、分页、打开右侧详情、扩大阅读、Escape返回；顶部切换异常情境和模拟账号/项目，更新数据只打开范围/预算。同步管理可切来源配置、任务诊断、历史版本；网页路径仅有明确标识的目标态预览。其他未接入类别与种子不伪造记录。本样稿不支持生产深链、真实历史版本或后端权限验证，不得把模拟数组/身份/时间/预算迁入业务代码。

### 当前实现 → 目标差额

以下文件行号均基于`0756d25`；保留确认前的诊断/建议，不是复制字段合同。最新已确认要求以正式Spec的UI-A子合同为准，表内“待确认/拟”不再重新开启已经完成的布局和A范围确认。

| 差额 | 已实现证据 | 候选决定及所属切片 |
|---|---|---|
| 普通入口名称 | `Sidebar/AppSidebar.tsx:56`、`AssetViews.tsx:16-24`沿用“云图原生资产账”；ENTRY E1固定该名称 | **待确认展示窄差额**：“互联网暴露面资产” / `Internet exposure assets`，仅普通菜单与页面标题；需后续正式条款窄修订。A，不全局替换供应商名称、API、模型、路由或历史 |
| 首屏先过程后结果 | `ExternalAssets.tsx:1491-1641`先来源/手动同步，记录区在后 | 分类、业务列表、紧凑范围条先出现；来源/预算/任务下沉同入口管理窗口。A |
| 类型从技术来源档案间接选择 | `ExternalAssets.tsx:43-50,456-479,815-831`按来源能力定域 | 业务分类先行；IP/端口共享来源、ROOT/DNS独立来源不变。新增类别显示未接入，不当0。A；新增读模型属于C |
| 裸入口不一定选到可读数据 | 当前选择首个enabled来源，否则首项；不以阅读授权或可读版本筛选 | 拟采用下文默认选择策略；显式上下文绝不参与自动选择。A可复用本地元数据，B仅列有依据的可选最小差额 |
| 通用表格缺少主要业务列 | `ExternalAssets.tsx:1355-1489`缺IP网络/标签、DNS分组/标签、ROOT备案号，时间列用updated_at | 以R2默认列为优先，源最近发现时间用lastseen_at原值；updated_at仍在详情，不改其语义。A |
| 业务分组和详情不够可读 | `FieldValue:88-143`递归显示对象；`RecordFields:145-309`按通用键值卡展开；`2330-2403`详情先版本/ID | 分组名称和标签名直接阅读；按域组织业务、子表与技术追溯。保留现有安全转义和四类空值区别，不能靠“原始JSON”签字段完成。A |
| 范围信息占据主区域 | `VersionInfo:312-413`已有本地量、源total、过滤、分页范围、采集/发布/保留与指纹 | 顶部压缩显示，不新增大数字卡。完整版本信息移入追溯/管理；筛选count不等于version.record_count或expected_total。A，无新统计API |
| 附件状态不全且有假筛选 | 附件缺未配置/固定身份拒读；status下拉不实际过滤；到期只关闭而保留详情DOM | 回收稿补齐状态、清除受限DOM；单一valid样本禁用状态下拉，不承诺其他状态。正式接线保留现有本地原值过滤能力。A |
| 附件已归并全站导航 | 附件默认“历史工作区”与当前`AppSidebar.tsx:52-113`不同 | 回收稿默认保留已发布结果/项目管理所有原入口；归并仅一个独立建议说明。不作为四域切片条件 |
| 14类新增信息及材料缺失 | R2/E14表明只有四域采集/保存/读取链已实现 | C按R3逐片固定合同；18类、网页哈希、企业层级/状态和额外详情仍是完整目标内差额，不被本次四域切片替代 |

### 已确认页面与交互

维护者在设计交付后明确“确认继续吧”。原8项页面决定已迁入[正式Spec的UI-A子合同](../specs/exposure-focus-release-1.md#result-ui-a已有四域结果优先)，此处不保留第二份行为定义。HTML与截图继续是模拟视觉参考，不证明正式接线或业务验收通过。


### 首片：已有四域结果优先，A / B / C分账

**A：推荐先行的纯展示切片。** 只调整现有四域的分类入口、业务列/详情、范围条、同步管理层级、拟批准普通名称和默认元数据选择；不增加数据域、保存字段、采集方法、权限、保留或同步Runner。完成判据是四域正式前端接现有API可浏览、搜索、分页、固定详情和过程管理，并通过下方回归；不是18类完整RESULT验收。

**B：现有API足以支撑A，不能先造聚合接口。**

- `GET .../sources`现有来源列表包含配置与阅读权限，`backend/app/api/routes/external_assets.py:53-73`按created_at降序/id排序；当前列表不是跨域结果目录。
- `GET .../sources/{source_id}/versions?domain=...`在`:274-313`提供分页版本元数据，包含`record_count/expected_total/complete/filter/sort/pages_read/时间/保留`。只查询获准来源的既有域，可逐页寻找候选可读版本；不预取所有域的records。查询数取决于来源数和版本历史，**不是全项目最多四次**。只在真正裸入口运行，并保持actor/project取消和迟到响应隔离；局部元数据失败不能表述成无来源/完整空集。
- 已选版本的列表响应自带版本与筛选命中`count`；服务端`external_assets.records:266-330`仅SQL读取。详情返回完整已保存`fields`；表格补列、分组名称、字段重排无需新API。
- **明确可选B1，不在A默认范围**：若元数据逐页成本实际不可接受，最小候选是在现有versions响应补`latest_readable_version`（允许部分批次、需当前来源/空间且未到期），并列于现有仅完整版本的`latest_complete_version`。必须另固定读取/拒读/空值合同、复用source_for及版本状态规则；后端模型/路由/合同测试及`bash scripts/generate-client.sh`随之更新。它不是current-head保证、不是所有来源聚合、更不是新事实库；不能用`data[0]`或最近完整版本假充同一含义。本轮不实现、不命名新endpoint，也不提前批准该字段。
- `ExternalAssetHead`与“最新可读历史版本”不是同一概念；隐式records仍按既有head。候选默认选择必须先选定明确可读版本，而不是先读到EXPIRED再自动兜底。对显式上下文仍原样拒读，以上优化不能改变此规则。

**C：新类型、保存与材料合同，独立于A。** 继续按同一矩阵E14和R3记录：子域名情报/证书/开放端口/网站实体/路径/指纹/爬虫及七类只读种子，分别闭合方法、身份、字段/空值、分页/排序/错误、权限、发布和保留后做采集→存储→列表→详情，不只交付占位。响应包、截图/图标、敏感请求材料分别固定受控取得、内容/字节限制、权限和删除；网页哈希及企业层级/状态不猜端点/字段。banner不是响应包、DNS不是情报、种子不是资产、源状态不是风险/整改。缺项阻塞依赖片，不阻塞另获批准的A；少量样本/四域完成不能把C改成可选或签全覆盖。

**独立导航候选**：“历史工作区”归并需单独确认范围及权限/可发现性回归，不随A实施。保留资产与差异、血缘、报告、客户台账、NetFlow、输入、来源、运行、当前资产、发现项、AI设置及条件用户管理；既有AI设置不等于本轮增加AI执行。无新框架、调度器、通用插件或全仓组件重构。

### 四域正式接线

已确认的默认列与详情分组已迁入上述UI-A子合同；下面仅保留代码复用计划，不定义新的字段权威。


| 文件/组件复用 | 首片改动与保护 |
|---|---|
| `frontend/src/components/ExternalAssets.tsx` | 保留AssetsPage/SourceAssets为查询、URL、固定记录和权限生命周期所有者；重排`renderRows/RecordFields/VersionInfo`。分类和表格先在本文件局部组件整理；只有代码可读性需要时才抽出无查询的展示子组件，不拆第二数据控制器 |
| `frontend/src/components/ui/table.tsx` + `ResultPagination.tsx` | 复用横向滚动Table和服务端count分页；不用`Common/DataTable.tsx`的本地data.length分页代替版本总量 |
| `frontend/src/components/ui/dialog.tsx` | 沿用当前详情Dialog，样式改右侧/可展开/窄屏全宽；保留固定URL控制开闭、Escape、触发记录或标题焦点兜底。同步管理复用Dialog/Tabs，不复制移动sidebar的整套Sheet外壳 |
| `frontend/src/components/ui/tabs.tsx`、原native select/Input/Button/Badge | Tabs只用于管理/详情分组，不把18类做同级页签；分类窄屏用原生选择器，减少新依赖与状态 |
| `frontend/src/lib/assetSearch.ts`、`routes/_layout/projects.$projectId.cloudatlas-ledger.tsx`、`projects.$projectId.external-assets.tsx` | 保留已实现解析、历史/新视图、兼容replace及fragment、账号/项目卸载清理；不新建生产路由 |
| `frontend/src/components/AssetViews.tsx`、`Sidebar/AppSidebar.tsx` | 仅名称批准后改对应`t(en,zh)`显示调用；普通菜单之外的label、path/search/active逻辑及条件Admin保持不变 |
| `frontend/src/lib/i18n.tsx`、`components/theme-provider.tsx`、既有Appearance/LanguageSwitcher | 复用双语、时间格式及主题tokens；源原始时间不调用formatDate臆造时区。保护既有主题菜单模态焦点修复 |
| 既有后端与生成客户端 | A保持不变。B1若另获准才最小改`external_asset_models.py`、API `external_assets.py`及相邻合同测试，按仓库脚本生成客户端，禁止手改生成物 |

### 路由、权限与验收回归计划

接线保留`assetSearch.ts:15-29`全部13个external参数与`:2-13`旧历史族；不在本候选另造参数白名单。非法asset_view、混合族仍fail closed，不把“显式优先”误解为丢掉冲突族。`external_record_version`不被当前列表version覆盖；端口匹配只用显式`external_port_version`；关闭详情仅清详情相关参数，搜索、分页、任务与列表身份保持。

查询键继续用`['external-sources',actor,projectId]`及`['external-assets',actor,projectId,source.id,...]`，records/detail含原域/版本/过滤/页码；版本、任务和匹配键不合并。项目/账号切换取消旧范围并移除缓存，来源切换清不相容选择；401/403/404/410、idle到期计时器和已打开管理面板都不能留下受限记录。停同步仍允许合法历史阅读；撤数据权限不借旧Run兜底，也不反向篡改旧Run原权限。

| 回归组 | 复用证据/待补覆盖 | 对应ACRESULT |
|---|---|---|
| 四域首屏与列/详情 | 正式前端+FastAPI+隔离PostgreSQL、固定合同合成采集/发布；不以静态数组当API接线。无旧Run的新项目首屏即记录；嵌套字段/长文本/四种空值完整可读 | 1、3、5、10（仅四域） |
| 默认/显式身份 | 无显式参数才选可读元数据；第一来源撤权/停同步、头版本到期但其他获准历史可读、完整0条、元数据查询失败分别验证；选定后的拒读不换版本 | 1、7、8、9 |
| 搜索/分页/固定详情 | IP/IPv6规范化精确、ROOT/DNS大小写及`%/_/反斜线`字面；25条边界、计数三分、返回/刷新/前进后退；ROOT/DNS无伪IP匹配 | 3、4、7、9 |
| 深链兼容 | external-assets完整支持参数+fragment只replace一次；旧cloud_*进入history；非法/混合/跨来源域版本记录拒读；不重放POST，不回落latest | 7、8、9 |
| 失败与权限 | FAILED/部分失败/UNKNOWN保留仍可读旧版本并提示本次任务；成员/来源撤权、403/410、自然到期清已开详情；Viewer/归档只读、停同步可读、账号/项目/来源迟到响应隔离 | 7、8、9 |
| 无副作用与历史 | 断开合成上游仍读；浏览/筛选/切类/开关管理无来源/模型调用及同步POST；旧Run/画像/报告/Hash/引用与原权限不变 | 6、9 |
| 可用性 | 中英文、深浅主题、1366/1920/390px、长文本、键盘横滚、模态Tab圈定、Escape及触发记录/标题焦点恢复，避免主题菜单焦点回归 | 10 |
| 完整覆盖 | 18类与矩阵额外UI差额按C逐项核对；本轮及A均不能签完整ACRESULT-2或材料版ACRESULT-5 | 2、5（尚未执行） |

既有`frontend/tests/external-assets.component.spec.ts:295-670`已覆盖未知提交/同键恢复、403详情清空、到期拒读、ROOT/DNS字面查询、冲突链接及项目迟到响应；仍应补实际FAILED/UNKNOWN返回、完整空集、Viewer/归档和移动目录到详情的上下文回归。`frontend/tests/cloudatlas-ledger.spec.ts:11-309`是旧历史浏览器覆盖，受`RUN_GOVERNANCE_E2E=1`门控；不能因有文件就声称已运行。后端相邻`backend/tests/api/routes/test_external_assets.py`已有固定身份、失败保留、撤权/到期、空/部分版本与只读权限案例，实施时复用而不是再造字段oracle。

### 本轮实际浏览器验证与截图

**PASS仅限独立静态候选。** 原生Chromium直接打开file HTML，43项交互检查通过；记录在[verification.json](result-ui-prototype-20260929/verification.json)，包含基线、附件/HTML SHA-256、逐项检查和NOT_RUN。浏览器网络仅2次本地文件加载，HTTP/外部资源请求0，页面错误0。1366、1920及390px均实际打开；390px页面scrollWidth=390，表格可独立键盘横滚，详情宽390，Escape恢复记录焦点。宽度是CSS视口，PNG物理像素随DPR变化。

实际检查覆盖四域规定搜索/分页、IPv6规范化、ROOT字面特殊字符、DNS不搜解析值、业务详情/展开/返回、共享IP端口预算入口、管理分区、各异常状态、打开详情后的到期/撤权DOM清空、模拟项目切换/归档只读、未接入与种子、网站目标态标识、深浅主题和减少动效。原附件提及的`preview_test_results.json`未作为本轮证据；以下为本轮重新观察与保存。

| 场景（全部模拟数据） | 截图 |
|---|---|
| 列表 / 宽屏 / 深色 | [1366px](result-ui-prototype-20260929/list-1366.png) · [1920px](result-ui-prototype-20260929/list-wide-1920.png) · [深色1920px](result-ui-prototype-20260929/list-dark-1920.png) |
| 右侧详情 / 长详情 | [详情](result-ui-prototype-20260929/detail-1366.png) · [展开](result-ui-prototype-20260929/detail-expanded.png) |
| 同步管理 | [共享IP/端口范围与预算](result-ui-prototype-20260929/sync-management.png) |
| 正常部分 / 完整 | [部分批次](result-ui-prototype-20260929/state-normal.png) · [请求范围完整](result-ui-prototype-20260929/state-complete.png) |
| 未接入 / 未配置 / 未同步 | [未接入](result-ui-prototype-20260929/unintegrated.png) · [未配置](result-ui-prototype-20260929/state-unconfigured.png) · [未同步](result-ui-prototype-20260929/state-unsynced.png) |
| 完整空集 / 无匹配 | [完整空集](result-ui-prototype-20260929/state-empty.png) · [字面查询无匹配](result-ui-prototype-20260929/no-match.png) |
| FAILED / UNKNOWN | [保留旧结果并提示失败](result-ui-prototype-20260929/state-failed.png) · [任务未决](result-ui-prototype-20260929/state-unknown.png) · [显式核对说明390px](result-ui-prototype-20260929/unknown-task-390.png) |
| 到期 / 撤权 / 固定身份无效 | [到期](result-ui-prototype-20260929/state-expired.png) · [撤权](result-ui-prototype-20260929/state-revoked.png) · [不回落latest](result-ui-prototype-20260929/state-invalid.png) |
| 账号/项目只读样例 | [项目B无配置、Viewer禁用写操作](result-ui-prototype-20260929/viewer-project-b.png) |
| 390px | [列表](result-ui-prototype-20260929/list-390.png) · [全宽详情](result-ui-prototype-20260929/detail-390.png) · [同步管理](result-ui-prototype-20260929/sync-390.png) |

文档检查`python3 scripts/check-context-hygiene.py`：PASS（588个已追踪文件）；新增HTML与23张PNG另由实际浏览器和文件完整性核对。OMP原生独立审阅：**Standards PASS / Spec PASS，均0项缺陷**；只审候选与边界，不替代业务验收或维护者视觉确认。原附件指纹未变，浏览器已关闭，无预览服务或生产变更留存。

**NOT_RUN**：生产React/FastAPI/隔离PostgreSQL采集发布链、现场页面/真实来源/模型、生产深链前进后退与跨账号迟到响应、真实权限/自然到期、英文布局及生产主题/Radix接线、18类完整字段与材料。前后端测试、lint/build未运行：设计回收无业务代码改动，未启动数据库或部署服务。静态场景切换不是生产授权/缓存安全证明，所有ACRESULT业务验收均未执行；后续布局与A范围确认不把这些项目改成PASS。

### 确认回执与下一步停止线

维护者明确“确认继续吧”，已确认右侧模态详情/展开阅读、结果优先目录表格、普通中英文名称及A四域范围。8项页面决定和默认列/详情分组迁入[正式Spec UI-A](../specs/exposure-focus-release-1.md#result-ui-a已有四域结果优先)，并以[ADR-0021 UI-A窄替代](../adr/0021-independent-cloudatlas-local-read-model.md#已确认的ui-a窄替代)记录相对ENTRY的边界。B1、全站导航归并不在A；C仍为完整目标内依赖。

本次只读查重以父Seed-ID、RESULT标题及“结果优先”标题搜索全状态Issue，均未发现匹配任务；#267仍OPEN，updatedAt未变。尚缺**包含UI-A的准确已发布commit，以及绑定该版本的真实任务和实施许可**。`0756d25`没有本节，不能伪称已固定；未编造Issue号或切current，也不借#267许可编码。

下一步需要明确授权：本地文档提交及push → 文档PR/正常CI与Review/merge → 按Seed-ID/交付范围再次查重建单或复用真实任务并固定Spec/ADR/矩阵与current。完成这些前置后，再按实际任务的本地A实施授权接线；部署、真实读取、保留调整和关闭仍分开。本次没有执行上述远端动作或业务实现；新增`.DS_Store`及`docs/.DS_Store`保持原样，不清理用户工作区。

HTML、23张截图和43项静态交互记录原样保留；它们是已审阅视觉参考，不是正式业务实现。本次条款迁移另作一致性检查与独立审阅；不恢复到期数据，不新增风险0/AI执行/扫描/纳管/写回，不自动进入下一阶段。

本次迁移检查：8项决定（仅去除已完成的待确认尾句）及4域列原样保留；既有ENTRY、RESULT R0—R4/ACRESULT及里程碑/权威尾节逐字未变。上下文门禁PASS（588个已追踪文件），HTML SHA-256仍为`d4a83912c08e166c624f8fe6e200e2b1ef9bb5b969856a440cd0f5f7baf37369`。OMP原生独立审阅：Spec PASS/0项；Standards PASS/1项P3陈旧“待确认”字样已修正，无blocker。以上是文档迁移验证，不是业务验收；未运行前后端测试或部署。
