# EXP-FOCUS-00 产品收敛接管回执

日期：2026-09-23。**仅接管与候选文档，不是新功能完成回执，不是实施授权或任务状态表。** 用户已确认外部暴露核查与处置方向；本轮没有重新询问三账产品定位。

历史快照说明：下文“本轮/当前/未批准/未发布”均指00只读接管时点，不是后续发布状态。文档定稿与远端操作另由[#245](https://github.com/Notyet1307/Exposure-Agent/issues/245)记录；继续工作必须读取[当前入口](current.md)及其固定Spec/实际Issue，本回执不恢复旧授权。

## 1. 身份、授权与现场保护

| 项目 | 本轮只读核对结果 |
|---|---|
| 当前代码 | `main`，HEAD=`71f65e9053e01bf4cb97cafe5ee5e538c9c34db2`；`git ls-remote origin refs/heads/main`同一SHA。没有fetch/pull/reset/checkout/clean |
| 原有工作 | 跟踪文件无未提交diff、暂存diff；未跟踪`.DS_Store`、`docs/.DS_Store`及用户提供的`docs/plans/Exposure_OMP_实施交接手册_20260923.md`。全部保留、不纳入清理。当前仓库登记一个worktree；未据此推断其他目录/机器无WIP |
| 原批准行为 | `docs/work/current.md`仍指向[#242](https://github.com/Notyet1307/Exposure-Agent/issues/242)；Spec固定`d0eb8b99261c5ce807be252e07e55fdef5049aa1`。该Spec与HEAD的blob均为`4abd30b46c6e410211b3470735f2bdb5b2c10b04`，本地读取与固定版本内容一致 |
| 本轮授权 | 以本轮明确指令执行00只读核对和新增候选文档；没有FOCUS正式Issue。旧Issue的发布/真实读取/部署授权不沿用 |
| 文档写者 | 父会话单写者；三个scout只读检查云图合同、核查审计、原生账/前端；未委派源码修改或测试。子任务读到本轮新增草稿不作为旧能力证据 |
| 保护基线 | 写文档前记录523个已有文件的SHA-256（全部跟踪文件及已有未跟踪文件）；不公开文件内容/秘密。原始交接手册及现有AGENTS/current/旧Spec/旧ADR不修改 |
| 外部操作 | 仅GitHub/Git远端只读和公开cumora README；没有真实云图、Exposure业务API、业务模型、数据库/现场服务、扫描/纳管/写回、部署调用 |
| 提交/发布 | 本轮commit、push、创建/修改Issue、PR、merge、关闭Issue、部署均未发生；没有安装/升级工具或依赖 |

磁盘现行AGENTS已是OMP原生工作流，不沿用旧会话自动注入的Harness/Controller描述。当前事实源为现行AGENTS、current及其固定Spec/实际Issue；旧大架构基线文件当前目录未列出，按现行路由读`docs/architecture/current-state.md`与`constraints.md`，没有恢复历史流程。产品方向确认与文档批准、业务实现、真实读取、发布、部署是不同授权。

## 2. 实际任务/PR：OPEN不等于未实现

下表是2026-09-23的只读接管快照，不在仓库持续维护状态；后续必须回GitHub读取。

| Issue | 实际PR/实现证据 | 本轮判断 |
|---|---|---|
| [#238 EXP-EVO-01A](https://github.com/Notyet1307/Exposure-Agent/issues/238)，OPEN | [#239](https://github.com/Notyet1307/Exposure-Agent/pull/239) MERGED，merge=`162b9c2be1a9950ea493961c696382e0479e74e2`；Issue有客户原生台账及部署回执 | 已实现/已合并；部署仅引用历史回执，本轮未查现场。OPEN用于关闭授权收尾，不重开发 |
| [#240 EXP-EVO-01B](https://github.com/Notyet1307/Exposure-Agent/issues/240)，OPEN | [#241](https://github.com/Notyet1307/Exposure-Agent/pull/241) MERGED，merge=`f822e9cbf0e0ac63dd8173fcfe1987660181a514`；有旧ListIPAssets真实分页、落地、断开网关后固定快照阅读及部署回执 | 原生IP来源账已实现，但不等于完整资产/风险同步；不重做基础接入 |
| [#242 EXP-EVO-01C](https://github.com/Notyet1307/Exposure-Agent/issues/242)，OPEN | [#243](https://github.com/Notyet1307/Exposure-Agent/pull/243) MERGED，merge=`37b73d9ef830fe52f193f646642f924de529b6ef`；[#244](https://github.com/Notyet1307/Exposure-Agent/pull/244)兼容修正MERGED至当前HEAD；有活动账/IPv6候选与部署回执 | 代码已在本机，不把current中的旧任务指针当新开发指令；不自动关闭 |

开放Issue列表仅以上3项，开放PR为0；全状态`EXP-FOCUS` Issue和PR检索无匹配。创建正式01A前仍须重查Seed-ID及相同交付范围，不能把本次查重当永久保证。补查旧[#29](https://github.com/Notyet1307/Exposure-Agent/issues/29)/[#35](https://github.com/Notyet1307/Exposure-Agent/issues/35)只确认初期最小只读合同，没有发现完整风险合同；旧任务中的未勾选不能推翻后续代码/交付事实。

#242顶部仍写main后置流水线IN_PROGRESS，已过时：本轮GitHub读回当前HEAD对应[Backend](https://github.com/Notyet1307/Exposure-Agent/actions/runs/35055533962)、[Playwright](https://github.com/Notyet1307/Exposure-Agent/actions/runs/35055533814)、[Compose](https://github.com/Notyet1307/Exposure-Agent/actions/runs/35055533887)均completed/success；#244四项必需PR检查也为SUCCESS。本轮只观察既有CI，不重跑、不修改Issue，也不把历史CI当新方向验收。

## 3. 本机OMP与Skills

- `omp --version`实测 **18.2.11**；`omp --help`可用。`docs/agents/skill-usage.md`提到18.1.15属于旧记录，不据此降级/升级。只读GitHub通过已可用`gh`完成。
- `omp plugin list`实测`@dietrichgebert/ponytail@4.9.0`；本会话具备read/grep/glob、bash/eval、task/scout/reviewer、LSP设备和browser能力。未对未使用的运行时宣称已验证；未启动浏览器/服务或产品模型。
- 实际发现`~/.agents/skills/`中的Matt `to-spec`、`to-tickets`、`domain-modeling`、`code-review`等；已读取to-spec/to-tickets和domain-modeling方法。前两者标记`disable-model-invocation: true`，本轮只用已有上下文合成规格及纵向切片方法，**没有杜撰或调用斜杠命令**。
- 这两个方法里的自动建单/打标签被本轮授权和仓库ADR-0016约束；不发布Issue、不重问已确定方向、不复制本地任务状态系统。没有恢复Wayfinder/Controller/Admission。
- 未核验全局与项目OMP配置的有效优先级，不能声称autolearn/autoContinue策略已由本轮证明；不读取认证文件或密钥值。源码仓库里的Pi/模型配置不等于OMP开发工具配置。

## 4. 能力差异清单

以下是**静态代码/测试存在证据**与明确标注的历史回执，不是本轮业务测试PASS。路径都相对当前HEAD；新草稿不作为已有实现的证明。

### 4.1 直接复用

| 能力 | 代码/测试证据 | 复用边界 |
|---|---|---|
| 项目/角色/归档授权及来源范围 | `backend/app/api/project_authorization.py`；各原生账route授权；`backend/tests/api/routes/test_cloudatlas_ledger.py`、`test_netflow_ledger.py`、`test_customer_ledger.py` | 沿服务端授权，不因本地同步或cumora放宽；Viewer/Approver读取不获得Operator写权 |
| OctoBus最小能力、指纹、来源配置/验证/启停及错误脱敏 | `backend/app/domain/cloudatlas_sources.py`、`api/routes/cloudatlas_source_instances.py`；`octobus/cloudatlas-read/`；`backend/tests/domain/test_cloudatlas_package_contract.py`、`test_cloudatlas_sources.py`、`tests/api/routes/test_cloudatlas_source_instances.py` | 复用边界和校验机制，不沿用旧授权去读风险，不把只支持一个方法当完整合同 |
| 旧IP快照完整性、分页/总数、失败保留、本地修订 | `cloudatlas_ledger.py:88-146,169-214,360-421`；`governance_runs.py`分页拉取；`ip_consistency.py`规范化；`test_cloudatlas_ledger.py`、`frontend/tests/cloudatlas-ledger.spec.ts` | 已有全量来源行而非报告样本；仅valid与id/ip/status、已发布旧Run；保留作为历史reader和实现模式 |
| CustomerUpload/原生上下文和不可变修订 | `backend/app/domain/customer_ledger.py`、对应route；`test_customer_ledger.py`、`frontend/tests/customer-ledger.spec.ts` | 兼容输入、归属/责任等现有上下文可复用；不继续扩建内部主数据CRUD；客户字段不能冒充云图源属性 |
| NetFlow接受、规范化、范围、候选与计数 | `netflow_datasets.py`、`netflow_activity.py:113-204`、`netflow_ledger.py`；`test_netflow_datasets.py`、`test_netflow_activity.py`、`test_netflow_ledger.py`、`tests/netflow_fixture/verify.py` | 原Dataset/hash/记录数、mapped IPv6、自环/重复流、namespace/撤权、范围外peer规则已有；不是服务识别或已验证暴露 |
| AI核查/追问、人工记录、后续差异验证、报告版本 | `backend/app/domain/ai_investigations.py`、`ai_investigation_tools.py`、`manual_reviews.py`、`ai_analysis_reports.py`；`backend/tests/api/routes/test_ai_investigations.py`、`test_ai_investigation_followups.py`、`test_manual_reviews.py`、`test_analysis_reports.py`，`backend/tests/domain/test_ai_investigation_tools.py`及`backend/tests/integrations/test_pi_investigation.py` | 执行安全壳、材料Hash、工具预算、追问/未知恢复、人工版本、报告编辑/确认已有；当前固定Resource+已发布Run，后续验证只判旧IP差异，不等于新风险复测；新来源需批准新材料合同 |
| 审计/修订、幂等与未知恢复 | `backend/app/domain/audit.py`，各ledger保存链；`backend/app/api/routes/audit_events.py:9-32` | 追加审计、预期父、actor/Project/key与业务事务复用；原始AuditEvent仍Admin-only，不能直接成为普通时间线 |
| 显式历史和技术详情 | `frontend/src/components/TechnicalValue.tsx`；三账、comparison、lineage路由；`frontend/tests/run-lineage.component.spec.ts`、`backend/tests/api/routes/test_lineage.py` | 固定版本、Hash/引用校验、复制/键盘/窄屏已有；不要另造身份框架或删除完整性保护 |
| 运行隔离与Session恢复 | `backend/app/integrations/agent_compose.py`、治理/AI runner；ADR-0003/0004，#244治理build与模型build分离 | 复用生命周期/固定执行身份；不能声称已有独立云图周期同步业务，不能增加第二调度器或猜超时终止 |

审计事实需准确命名：当前`AuditEvent`是数据库保护的追加记录，现有Hash主要绑定材料、输入、快照和报告；未发现AuditEvent自身的`prev_hash/event_hash`或签名链，不能称已实现“Hash审计链”，本轮也不建议为展示收敛新增一套链。`AgentComposeClient`证明Start/Get/Resume执行能力，不证明已有产品周期同步；接入周期任务前还需核实agent-compose受控计划能力及计划身份/恢复合同，不先加cron框架或第二调度器。

### 4.2 改造，不从零重建

1. **完整云图合同与本地来源模型**：当前proto只有ListIPAssets和id/ip/status，桥显式裁掉其他属性。按01A真实合同扩展只读白名单、指纹/Capset和结构化本地阅读；表结构在合同后确定，不扩建第四套CMDB。
2. **从旧Run解耦同步**：`cloudatlas_ledger._scope()`要求已发布Run，SourceSnapshot有旧Run身份；不可删约束或造假输入。新路径有独立来源/同步版本/任务与各域时间，旧快照reader保持原合同。
3. **浏览不隐式外调/写状态**：发现容易遗漏的复用陷阱：来源列表route `cloudatlas_source_instances.py:76-109`调用`source_public(..., session=...)`；`cloudatlas_sources.py:409-452`在已验证配置上查询OctoBus当前指纹，漂移会提交验证失效审计。新离线阅读不得依赖这个实时控制面GET。应区分本地浏览与显式来源诊断/验证，**不能为离线体验删除执行时指纹安全门禁**。本轮未调用该API。
4. **核查与处置消费者**：复用现有核查/人工/报告，而为新资产/风险固定本地版本/来源证据；本地问题与上游风险状态分开，旧Finding确定性关闭不改。责任、交办、复测/关闭合同需后续02，不用原“验证对账差异解决”冒充风险处置。
5. **NetFlow线索**：已有范围内IPv6地址候选，增加服务线索的确定性规则/原因/不确定性及评测，不改旧flow_count、不从src/dst直接猜服务端、不建全流量平台；Laya另验。
6. **时间线和界面**：从获准业务事实投影问题/任务时间线，保留管理员原始审计；已有技术折叠/复制复用。页面收敛不等于后端权限放宽。
7. **cumora适配**：Exposure提供同一授权服务/任务身份的最小适配；不能在cumora重复维护资产/问题。只读协议研究可早做，真正实现及跨网络验证留04。

### 4.3 退出普通界面，但不删历史

- `frontend/src/components/Sidebar/AppSidebar.tsx:47-100`仍提供三账和独立Lineage；`WorkspaceSelector.tsx`识别三账一级路径。新普通导航改工作台、外部资产（含风险）、核查与处置、报告；来源/任务诊断进入设置。
- 客户台账CRUD退到受控兼容/历史用途，不再是普通工作台主流程；NetFlow全端点账退到输入/诊断，普通入口强调有限线索；旧云图账保留固定历史而不是新的完整资产产品面。
- 独立血缘图退出主导航，单资产事实/核查/来源依据继续可达；现有lineage路由承载AI/人工面板，不能连路由删除。
- 保留`/projects/{projectId}/customer-ledger`、`cloudatlas-ledger`、`netflow-ledger`及其版本/修订查询参数；保留`/projects/{projectId}/runs/{runId}/comparison`、`lineage?resource_id=...`和根路由显式project/run/view历史入口。不能重定向到latest代替历史。
- 完整Hash/ID/内部版本不散落普通摘要，但不删除、不改引用值；只在同范围授权的技术详情显示。清除普通入口不构成删除API/表/旧报告的授权。

### 4.4 真正缺失 / 尚未证明

- **已确认产品实现缺失**：独立云图同步任务与新来源读模型、完整资产/服务详情、源风险列表/详情/关系/依据附件、本地问题闭环和按问题/任务的业务时间线、新来源核查材料合同、Exposure侧cumora适配。
- **不是从零缺失**：旧来源IP落地和离线快照阅读、NetFlow端点及IPv6候选、人工结论/旧差异验证、AI报告版本、技术Hash折叠已存在。
- **资料未知，不能断言供应商无能力**：目标云图版本/全量类型/状态、风险/详情/附件接口字段、稳定ID/分页变化/删除/增量语义、权限与保留策略；详见矩阵G1—G4。
- **Laya未知**：未找到该项目的实际仓库/模型制品、版本、许可证、运行入口或测试。不能按同名猜；这些只阻塞03的模型资格/启用，不阻塞规则版或01。
- **cumora已有基础不能重造**：本轮读到[cumora README](https://github.com/Notyet1307/cumora/blob/main/README.md)已有WeKnora/A2A/MCP受控接入、版本发布、任务/交接成果、采用记录；其信任文件只允许literal loopback与精确资源范围，保存/metadata验证不等于业务执行。Exposure连接、服务身份及跨容器/异机部署链路未验；不能因README存在就说已经打通，也不能按“cumora无接入”重建。

## 5. 旧新冲突与最小替代

完整“原条款→新决定→适用范围→历史兼容”清单在[候选ADR-0021](../adr/0021-independent-cloudatlas-local-read-model.md)，本轮不改旧ADR。

重点结论：ADR-0019第1条及最后一段的**已发布Run依赖、只许ListIPAssets、不增独立同步/周期任务**与新方向直接冲突，必须显式窄范围替代；“不复制原始响应/第四份主表”不能被偷偷突破，候选仅允许必要的来源读模型及另行约定的受控依据材料。新增表数量、附件保留期限、周期参数均未批准。

ADR-0018的客户CRUD、ADR-0020的活动账和旧Spec S1的Lineage导航不是要整篇废止；替代的是新普通产品定位/入口及后续消费者。旧Revision、Dataset、计数、namespace/授权、Run/Resource/Finding、报告字节/Hash与深链继续保留。ADR-0003/0004的单活跃/未知Session、0008/0013的pin与v1/v2历史、0016的权威分工、0017的模型版本/凭据边界继续适用。

ADR-0015第13条同样将合成AI任务限定为旧Resource/已发布Run和明确Run报告；新本地来源对象核查不能只修改DTO绕过该限制。候选ADR-0021补充窄替代入口，02实施前仍须固定新材料/任务合同；私网生产默认、合成公网例外的精确目的地/材料白名单、有界工具、无自动retry/fallback、客户数据不自动出域全部保留。ADR-0017的连接资格不等于新材料许可。

部分老ADR文件状态仍是“提议”，例如0012，不能因为代码已有Lineage就把它当已接受Standards；本轮以现行已批准Spec、当前实现和相关已接受ADR为依据。旧Spec的“工单/闭环非目标”只应在新02合同获批后对新路径作窄替代，不能直接重解释旧Finding。

## 6. 字段矩阵、阶段及第一项任务落点

本轮仅新增以下六份材料：

| 交付 | 路径 / 身份 |
|---|---|
| 接管回执、能力差异、入口与授权 | 本文件 |
| 六阶段定义（00—05） | [docs/plans/exposure-focus-20260923.md](../plans/exposure-focus-20260923.md)，候选路线，不记录日常任务状态 |
| 新行为及01A验收 | [docs/specs/exposure-focus-release-1.md](../specs/exposure-focus-release-1.md)，DRAFT，建议正式Spec落点 |
| 旧新冲突/窄替代/历史兼容 | [docs/adr/0021-independent-cloudatlas-local-read-model.md](../adr/0021-independent-cloudatlas-local-read-model.md)，Proposed |
| 完整类别字段覆盖/最小缺口 | [docs/plans/exposure-focus-cloudatlas-coverage-20260923.md](../plans/exposure-focus-cloudatlas-coverage-20260923.md)，候选合同附件 |
| 首项候选Issue正文 | [docs/plans/exp-focus-01a-issue-candidate.md](../plans/exp-focus-01a-issue-candidate.md)，未创建/未批准 |

矩阵覆盖资产身份/空间/类型/归属、端口服务/组件指纹/证书网站/标签、状态时间、列表/详情、风险身份/等级/状态/关系/正文/历史、依据文本/附件，以及更新、权限、失败和保留。每项有来源/字段路径、稳定键、可得性、当前/候选保存、页面与验收；上游未知不猜。已存在的IP协议、合成样例和#240真实聚合回执无需用户重供；只补G1完整合同及脱敏样例、G2缺失的同步语义、G3精确只读范围/限制、G4附件/数据安全约定。

第一项建议仅为**EXP-FOCUS-01A“云图资产与风险接口合同核验”**。已有资料可支持文档部分；完整风险/依据等必需合同及本轮真实只读权限仍BLOCKED。真实核验NOT_RUN；不宣称01A完成，不用01B单一对象代替01整体完整同步。

## 7. 正式路由建议（尚未执行）

1. 维护者批准后，保留`docs/specs/exposure-focus-release-1.md`作为唯一新行为Spec落点；固定本文件、必要ADR及矩阵的真实提交。旧`asset-governance-release-1.md`不复制/覆盖，继续作为旧Run/报告及兼容行为合同。
2. `AGENTS.md`默认读取第3项改为“读取current所指当前Issue固定的Spec路径与commit；旧IP对账Spec用于历史兼容”。保留第2项current及第4项实际Issue，禁止永远硬编码旧Spec或新增第二套任务系统。
3. `docs/work/current.md`在正式01A Issue存在后，仅放该Issue链接、固定新Spec准确commit/节、接受ADR、候选/证据入口及停止线。移走的是默认当前指针，不是关闭#242或重开旧任务；旧#238/#240/#242的收尾留GitHub。
4. `docs/README.md`仅在文档批准轮补新Spec/路线入口及旧Spec的历史用途；`CONTEXT.md`如需调整Project定位/源风险/暴露问题术语，按已批准定义做必要更新，不把任务状态或未定表结构写进词汇表。本轮上述文件全部未改。
5. 没有真实批准commit就不能发布“固定Spec”链接；草稿获产品方向认可不自动变成已接受ADR。发布前重新检查ADR编号、未提交工作及重复Issue。

## 8. 验证边界与下一步唯一授权

已执行：本机Git/远端/实际Issue/PR/CI读取、OMP版本/帮助/插件与已安装Skill文档读取、相关代码/测试静态检查、原文件Hash基线记录。未运行后端/前端业务测试、build、产品浏览器验收、真实云图/模型、现场部署检查；本轮没有业务变更，也没有获准的隔离业务运行。上述均**NOT_RUN**，不是PASS。

**下一步唯一建议：批准并发布文档基线，随后查重建立01A正式Issue；不开始业务实现。** 需要用户明确授权：

> 批准本回执所列候选Spec/ADR的窄范围替代及01A验收合同；未知接口、字段、权限和现场事实仍未知。授权这批文档的必要路由调整、本地提交、push、文档PR、必需CI/Review及满足门禁后的merge；固定文档commit后查重并创建仅01A的正式Issue。其余阶段保持候选。仍不授权业务源码/迁移/生成代码、真实云图/业务模型、扫描/纳管/写回、现场数据修改或部署。

若维护者只批准文档内容但不批准远端写入，则只固定获准的本地文档工作并停止，不自行建单。真实云图读取还需按01A正文另给精确环境/空间/已知方法/时间及调用限制/凭据安全使用授权；旧#240不替代。材料不足先完成可达文档并保留BLOCKED，不让用户重复提供已有资料。

下一会话先读本回执、阶段路线、候选Spec/ADR和01A正文，再核对未变的AGENTS/current及实际GitHub；批准后改为AGENTS→current→固定Spec/Issue。本轮完成接管后停止，不自动执行上述授权模板。

## 9. 本轮文档与保护校验结果

- **PASS**：`python3 scripts/check-context-hygiene.py`，输出`context hygiene passed (520 tracked files)`。该脚本只检查已跟踪文件，不能单独证明本轮未跟踪草稿有效。
- **PASS**：对6份新增材料另外调用同一Markdown本地链接检查；无缺失目标。以一次性内存检查核对00—05每阶段均有业务目标、范围、非目标、依赖、完成标准、停止条件；32行资产/风险/依据/更新覆盖项存在；Spec与候选Issue的AC01A-1—7一致。
- **PASS**：523个原有文件逐一复核SHA-256不变，包含旧批准入口和用户原有未跟踪材料。新增范围仅上列6份候选/回执；没有持久化验证脚本或测试产物。
- **NOT_RUN**：产品业务测试/构建/浏览器验收、真实云图/业务模型、现场数据/服务验证与部署。历史PR/CI及Issue回执均已标明来源，不能替代这些未执行项。
- **BLOCKED（后续01A）**：批准固定版本及G1—G4必要合同/权限/安全材料；不是00接管未完成，也不是允许缩小完整同步目标。到此停止。
