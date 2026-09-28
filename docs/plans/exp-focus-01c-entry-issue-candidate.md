# EXP-FOCUS-01C-ENTRY 候选Issue与分步授权prompt

2026-09-28建单前材料快照。维护者随后批准文档固化、发布、固定版本建单与current切换；业务实施仍待独立授权。行为和唯一验收定义已移至[正式Spec的ENTRY节](../specs/exposure-focus-release-1.md#exp-focus-01c-entry统一云图原生资产账入口)，只读事实见[接管回执](exp-focus-01c-entry-candidate-20260928.md)。下文“未创建”“待固定”及prompt A保留为发布前步骤，不是持续更新的状态或再次执行许可；实际任务、固定commit和授权只读[current](../work/current.md)及其Issue。

## 候选Issue正文

正式建单前将以下规格引用填成实际已合并commit及不可变链接。不得用DNS的8eb2518冒充ENTRY合同，也不编造Issue编号；本文保留发布前正文，正式Issue使用固定Spec并独立维护状态。

### 标题

`[EXP-FOCUS-01C-ENTRY] 统一云图原生资产账：四域本地阅读与历史快照承接`

### 身份与行为权威

Seed-ID：`EXP-FOCUS-01C-ENTRY`。

- 正式Spec落点：`docs/specs/exposure-focus-release-1.md`新增`EXP-FOCUS-01C-ENTRY`节，E1—E7、ACENTRY-1—8；新固定commit须在建单前取得。
- 配套决定：同版本`docs/adr/0021-independent-cloudatlas-local-read-model.md`的“统一云图阅读入口”窄扩展；ADR-0016/0019/0022及旧合同继续按声明范围适用。
- 四域继承基线：Spec/ADR-0022/字段矩阵@`8eb2518cdf055dd1060068f8a1f80729b2b72822`中的01B/ACBATCH、ROOT和DNS，字段/同步/权限/版本/保留不变。
- 旧历史：#240固定`docs/specs/asset-governance-release-1.md`及ADR-0019@`9f9437583e0fd0acf13033104450fbd82b3a5a7f`；其他旧报告/核查继续各自固定合同，不重新解释。
- Issue只记录状态、依赖、执行授权与证据，不能以正文暗改上述行为。

### 用户问题与交付

已同步的IP、端口服务、主域名、DNS目前在external-assets，名称为“云图原生资产账”的旧入口仍读Run快照。普通用户不能知道哪个入口有新数据。

交付一个“云图原生资产账”用户入口：默认已同步四域，次级“历史 Run 快照”保留旧阅读、画像及管理合同；原external-assets深链兼容转向统一页。无台账/NetFlow/旧Run的新项目也可找到已有四域的列表、搜索、详情、版本和任务状态。不是只换菜单标题，也不把两套数据合并。

### 实施范围

1. `/projects/{projectId}/cloudatlas-ledger`成为规范用户URL，`asset_view=synced|history`明确视图；裸URL默认synced，旧显式历史参数进入history；混合参数明确拒绝歧义。原external-assets仅replace兼容跳转，完整保留既有external_*和fragment，不丢固定身份。
2. 复用两页读取实现、既有DTO/query缓存和同步意图存储；迁移所有相关内部链接、侧栏及项目切换。新旧来源配置分清用途，不改能力合同。
3. 继承四域搜索、分页、固定详情、完整/非全量、版本选择、任务、撤权、过期和清理行为，分别展示来源、域、采集/发布时间及范围。
4. 保留旧Run/SourceSnapshot/Observation/revision/profile、报告和引用；原cloudatlas-ledger及external-assets后端API路径和语义不变，不做数据库或客户端合同变更。
5. 更新受影响既有检查与用户/架构文档，实际浏览器验证；Standards/Spec双轴审阅和独立业务验收分开。

### 非目标

重写四域同步/字段/权限/版本/到期逻辑、数据迁移或重新发布、客户台账/NetFlow前置、三账主线、全站导航重构、风险/附件、其他资产类别、周期同步、跨批次合并、Laya、cumora、AI核查/报告重做、扫描/纳管/写回。新入口不会把新版本自动接到旧Finding/Resource/核查模型。

### 查重、依赖与#262边界

- 本次实时main589c237、PR #265已合并，开放PR为空；没有发现ENTRY同范围任务。正式创建时再次查全状态Seed-ID及同范围任务，有同项则复用，不重复建单。
- #250/#255/#257及#262的四域实现可复用。#262 OPEN不代表DNS未实现；最新窗口清理已有[完成回执](https://github.com/Notyet1307/Exposure-Agent/issues/262#issuecomment-5864964256)，人工体验反馈及关闭决定仍留原Issue。本任务不关闭、重开或扩大#262，不以其关闭作为代码依赖。
- 必须先有批准且固定的ENTRY Spec/ADR及正式Issue与实施授权。#247风险合同后置差额、旧#240的关闭与02—05不作为本片实施前置。
- 新真实样本不是入口合流前置。实现与隔离合成浏览器验收不继承任何旧真实来源/Token/预算/保留窗口。

### 验收清单

精确定义采用固定Spec的ACENTRY-1—8，不在Issue另改合同。发布正文时将下列名称链接到实际固定Spec：

- [ ] ACENTRY-1：无旧Run的新项目，唯一云图入口可发现四域。
- [ ] ACENTRY-2：四域列表/原搜索/分页/固定详情/版本/任务及同IP匹配不退化。
- [ ] ACENTRY-3：来源、域、时间、部分/完整、失败/未知/过期和计数诚实。
- [ ] ACENTRY-4：external-assets、旧历史参数及新规范链接兼容；歧义拒绝、固定身份不漂移。
- [ ] ACENTRY-5：Viewer/归档/来源隔离/撤权/到期及已打开缓存拒读不退化。
- [ ] ACENTRY-6：旧快照、画像、Run报告/引用可访问，标为历史，内容和权限不改义。
- [ ] ACENTRY-7：来源设置用途清楚，离线本地阅读与无副作用成立；不自动同步/恢复。
- [ ] ACENTRY-8：双语、主题、窄屏、键盘/焦点及必要文档/旧回归完整，审阅与业务验收分账。

### 验证与证据

隔离的真实前端+FastAPI+PostgreSQL，使用合成已发布四域版本及旧快照/报告；记录实际用户交互、固定身份与调用计数。复用已有后端权限/过期/历史检查与前端行为检查；路由兼容回归必须覆盖fixed detail、port version、task、旧profile/revision及歧义参数，不能仅测文案或mock转发。

每项记录PASS/FAIL/BLOCKED/NOT_RUN、源码及Spec版本、证据种类。DNS历史真实回执只证明DNS既往验收，不等于新入口验收；不为本Issue补采真实数据或延长已到期保留。全量测试未跑就说明，不能用构建代替页面验证。

### 授权与停止线

建单不自动授权业务实现；实施按维护者当前明确范围执行。业务commit/push/PR/merge、部署和关闭各自按授权与门禁验收，不从CI通过或Spec合并推导。

出现必须改变后端合同、扩展来源、恢复旧Run前置、丢固定引用或读取过期数据的方案时，停止相应扩展并报告最小差额。完成当前获准实施、检查与审阅后停，不自动进入下一片。关闭须业务PR合并、所要求部署/业务验收完成或明确不适用且取得关闭授权。

## 下一步prompt A：批准并固定规格、建单，到此停止

以下为维护者已批准的文档发布阶段操作文本；保存于此不允许重复执行已完成动作。实际执行进度按GitHub；业务实施仍需另行发送prompt B。

```text
批准正式Spec的EXP-FOCUS-01C-ENTRY节E1—E7、ACENTRY-1—8及ADR-0021统一云图阅读入口窄扩展，采用统一cloudatlas-ledger默认新四域、asset_view区分历史、external-assets保留兼容链接的方案。

授权只做本项文档固化与建单：先核对目标工作树现有改动和GitHub实时Issue/PR，保护 /Users/yet/Developer/Exposure-Agent 及其他worktree；将候选条款纳入exposure-focus-release-1.md，在ADR-0021追加该窄扩展，同步必要的阶段计划/交接手册入口称谓澄清。保留旧Spec/ADR和所有历史结果，不重写DNS字段矩阵。按仓库规则完成文档检查及OMP原生Standards/Spec独立审阅。

本次允许仅文档commit、push、创建PR、观察必需CI/Review并在正常门禁通过后merge；不得绕过分支保护。固定实际合并文档中的Spec/ADR commit，按Seed-ID EXP-FOCUS-01C-ENTRY和交付范围查重，用候选Issue正文建单或复用已存在同项，填写真实固定链接和AC。明确本片仅文档已批准、业务实施仍待授权；current通过文档PR指向实际新Issue及固定Spec，注明#262剩余事项仍在原Issue，不把它记为完成。不要为了先写current伪造编号或未来SHA。

只读核对#262最新人工反馈及已有到期清理回执；不关闭或改写#262，不重新采集、不延长保留。不改业务代码/数据库/生成客户端，不部署、不调用真实云图/模型、不扫描/纳管/写回。文档发布、建单及current切换后交付固定Spec commit、新Issue链接与下一条实施prompt，立即停止。
```

## 批准后prompt B：实施唯一ENTRY任务，到本地验收停止

只有prompt A已实际完成后发送。它让会话从current和GitHub解析准确编号/commit，不需用户填写工具可查的信息，也不允许把尚未固定的候选当正式合同。

```text
继续实施当前已批准的唯一 EXP-FOCUS-01C-ENTRY 任务。

先读取AGENTS.md、docs/agents/skill-usage.md、docs/work/current.md和其实际GitHub Issue及固定Spec/ADR commit，核对Seed-ID确为EXP-FOCUS-01C-ENTRY，且含已批准E1—E7及ACENTRY-1—8；若仍指#262或规格尚未正式固定，先报告缺少的前置，不借DNS范围实施入口。核对 /Users/yet/Developer/Exposure-Agent-root-domain 和相关PR/代码，保护现有改动及 /Users/yet/Developer/Exposure-Agent，不因Issue OPEN重复已交付工作。

授权本任务本地业务实施、受影响既有检查、隔离合成实际浏览器验收及OMP原生Standards/Spec独立审阅；本轮不授权commit、push、远端Issue/PR变更、merge、部署或关闭。只复用四域页面与旧历史页面完成规范路由、历史视图、external-assets兼容跳转、侧栏/项目选择/相关链接及来源配置引导；不重写四域API/同步/权限/版本/保留，不改数据库或生成客户端，不手工编辑routeTree.gen.ts。

逐条按ACENTRY-1—8验证：无Run项目四域可达；列表/搜索/详情/版本/任务；完整/部分/失败/过期与各域时间；新旧深链和歧义参数；Viewer/归档/撤权/到期缓存/跨来源隔离；旧快照/画像/报告/引用原义；离线只读无副作用；中英文、主题、键盘与窄屏。使用隔离真实前端+API+PostgreSQL和合成数据，不能仅用mock或构建冒充业务验收。复用现有测试与事实源，不增加通用框架。

没有新真实云图/业务模型/扫描/纳管/写回授权，不读取既有客户原值给模型，不重新采集样本，不延长或恢复DNS旧窗口。#262只读已有人工/清理回执，不替它关闭或改范围。不得扩展风险/附件、其他域、周期同步、跨批次合并、NetFlow、Laya或cumora。

完成后分别报告每项实际证据和未运行检查，修复双轴审阅blocker并复审；更新必要用户/架构文档，清理本轮临时合成环境。交付变更文件、本地验收与剩余授权需求，立即停止，不自动提交、发布、部署或进入02—05。
```
