# EXP-FOCUS-01A 文档、合成与授权有界实读回执

核验日期：2026-09-23文档/合成及公开CLI研究；2026-09-24授权有界实读，随后按维护者确认追加资产先行规格交接。任务：[EXP-FOCUS-01A #247](https://github.com/Notyet1307/Exposure-Agent/issues/247)。这是本地证据，不是第二份任务状态表；没有修改Issue、提交、push、PR、merge或产品部署。

历史执行依据：[Spec@d4763e0ae2da7b60773563101c5f91cb7c773840](https://github.com/Notyet1307/Exposure-Agent/blob/d4763e0ae2da7b60773563101c5f91cb7c773840/docs/specs/exposure-focus-release-1.md)，配套ADR-0021与原覆盖矩阵同一commit；代码读取版本`ff1cc5c7285abeb7b55512bd9c116a4d961f0b67`。初次核验前已核对固定材料。E12结束前仅追加矩阵/回执；本次另修改工作树中的[同一Spec](../specs/exposure-focus-release-1.md)及[阶段定义](../plans/exposure-focus-20260923.md)，明确风险后置和01B准入替代，尚未固定新commit/更新Issue。已接受ADR、旧Run/报告合同及业务源码不变。

维护者先授权文档/合成核验并确认产品**云图v1.2**、OctoBus＋开源CLI路径；随后提供指定环境/空间的受控凭据，明确授权只读探测，并选择**建立一次性隔离环境**。新增许可仅覆盖本回执E12的单空间三GET、≤8次/每页≤5及结束销毁；不包括写入、扫描、其他空间、附件、业务源码改动或远端发布。来源在文档中记为LIVE-A，不记录地址、空间值或凭据。

2026-09-23只读查询#247原生`dependencies/blocked_by`为空；2026-09-24在线刷新分别遇GitHub CLI 401、公开API 403，内部Issue读取明确提示旧缓存，**不声称当前远端状态已重新核实**。本次执行依据固定Spec及明确对话授权；未将旧许可/标签解释为扩域授权，未改历史Issue。

## 结论与证据等级

**文档/合成、公开字段研究及7次授权实读已完成。按原固定Spec评估的01A全项仍保留BLOCKED；本次维护者明确风险实样后置，已形成IP＋端口资产先行的01B实施规格，不再等待非空风险样本才能整理或交接字段。新准入须随修订Spec固定并另获实施授权；没有新增实读、业务实现或把历史未验项改成PASS。**

- **静态文档**：现有单方法proto、adapter、后端指纹/Capset验证、fixture、已接受ADR和固定Spec；新增固定版本开源CLI及其内置OpenAPI。前者只证明当前Exposure消费者，后者证明CLI声明的读取面，均不能代替现场核验。
- **历史真实回执**：#240记录的指定来源valid/IP分页与旧快照阅读。复用历史结论，不把它写成本次执行、不外推到风险/附件/全部状态或当前权限。
- **合成证据**：初次核验的原adapter函数体9项离线检查PASS，脚本本次未修改。CLI、OctoBus SDK和临时文件系统均为替身；不升级为实际CLI/SDK集成证据。
- **新增真实E12**：真实OctoBus/SDK/固定CLI经受限HTTPS转发器访问指定来源；IP/端口有界分页、漏洞空列表及一次IP匹配/短时重读已执行。未运行业务模型/数据库/旧Runner，未读取独立详情、附件或非空风险依据；客户原始响应仅作本地确定性解析，不送模型/仓库/Issue，临时文件已销毁。

## 材料与精确合同

字段路径、可得性和缺口的唯一明细仍在[同一覆盖矩阵](../plans/exposure-focus-cloudatlas-coverage-20260923.md)，不在此复制第二份字段权威。下表记录**Exposure旧消费者**；它的单方法限制不是开源CLI能力上限。

| 层次 | 已核实的边界 | 不能据此推出 |
|---|---|---|
| [产品RPC](../../octobus/cloudatlas-read/proto/cloudatlas_read.proto) | 单一`cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets`；request为status/page/size；items只有字符串id/ip/status；response为items/page/size/total | 独立详情、非IP资产、风险、证据/附件方法，稳定业务身份 |
| [adapter](../../octobus/cloudatlas-read/bin/cloudatlas-read.js) | CLI命令`cloudAtlas asset ip list`；请求status限valid/await/ignored/invalid，page正整数、size上限200；CLI超时60秒、输出buffer上限1MiB；CLI整数id转字符串，current转page，额外属性丢弃 | 四种状态的供应商语义、目标版本全量范围、CLI中间表示之外的真实响应合同、长期ID/安全范围 |
| [后端消费者](../../backend/app/domain/cloudatlas_sources.py) | 291—356行固定status=valid；items精确三个字符串键；返回page/size必须等于请求，total为非bool非负整数；只对既定连接/上游错误有界重试。验证读取前后比较指纹 | total是同一快照、不同页无重复/遗漏、增量/删除/业务更新时间合同 |
| [指纹和Capset](../../backend/app/domain/cloudatlas_sources.py) | 176—289行核对固定package/descriptor、config/secret Hash、实例和token material；Capset启用，实例绑定唯一，include_all_methods=false，方法绑定精确单一 | 配置指纹不是来源空间/客户归属证明；旧Capset不授权新增风险方法；本轮未执行其控制面或权限集成测试 |
| [既有上游fixture](../../tests/cloudatlas_fixture/fixture_upstream.py) | 合成路径`/openapi/v1/asset/ip`、TOKEN头、data包裹层；含合成401/403/503/坏结构/断连分支 | 初次仅凭fixture不能确认上游合同；补充公开schema和CLI现已提供该路径/包裹层的独立静态出处，仍非本轮真实调用证据 |

目标云图产品版本由维护者确认为v1.2，不把package/SDK/CLI/OpenAPI版本混作产品版本。E12的具体授权空间与三GET实际返回已补证；其他类型、非空风险/依据及长期语义仍待补。旧商业架构路径不在当前工作树；采用当前AGENTS路由和[当前实现边界](../architecture/current-state.md)，不恢复历史入口。

历史E5已通过GitHub CLI重新读取[#240正文](https://github.com/Notyet1307/Exposure-Agent/issues/240)的“2026-09-15 恢复后的本地完成回执”和“2026-09-15 本地部署验收”，不是缺少comment编号时编造锚点。正文记载valid范围66页、13,182条（IPv4 13,152 / IPv6 30），旧Run完成并在网关停止后仍能读取固定快照；历史快照Hash为`f6cb969c57629681e4d001d8f09282f87e6aa112b444a72a60fa2dbad3cd7e16`。风险读取/云图写入/扫描/纳管未执行。未进入正文所述私有证据目录，未读取原始IP、响应或凭据。

版本旁证：[package.json](../../octobus/cloudatlas-read/package.json)为包`0.1.0`及SDK`0.5.0`；[Dockerfile](../../octobus/Dockerfile)固定CLI `v2606.0.4`。初次检索仅覆盖Exposure仓库，没有取得上游完整schema；本次沿维护者提供的开源地址补齐公开资料，不能继续把已公开字段写成完全未知。

旧消费链的重复语义不同：[Runner](../../backend/app/domain/governance_runs.py)的`_write_cloudatlas_artifact`与[旧解析器](../../backend/app/domain/ip_consistency.py)保留来源重复行、核对页序/总数/累计完整性，后者用`page:N:item:M`定位快照内记录；[旧AI读取](../../backend/app/domain/ai_investigation_tools.py)的`_matching_assets`拒绝重复ID并最多5页/500条。该差异只作静态复用警示，本轮未调用这些后端路径或模型：不能从任一旧消费者反推上游稳定身份、最大规模、去重或增量语义，更不能用模型专用有界读取替代完整同步。

## v1.2截图与开源CLI补充研究（2026-09-23阶段）

### 可复查的公开来源

- 维护者确认：目标**产品v1.2**；截图是UI呈现证据，不是API响应样例或新增调用授权。
- 已用GitHub解析CLI tag `v2606.0.4`为commit **`857ae38973b9c7886fc088a4065e3694202b7982`**，与Exposure当前Dockerfile固定的发布版本对应。
- [该版本内置OpenAPI](https://github.com/chaitin/chaitin-cli/blob/857ae38973b9c7886fc088a4065e3694202b7982/products/cloudatlas/spec/openapi.yaml)：OpenAPI格式`3.0.1`，`info.version=1.0.0`是文档元数据；不是对产品v1.2的否定，也不是现场兼容验收声明。源码说明为从Apifox共享文档合并。
- 完整解析结果：**172个路径、191个操作（GET 72、POST 75、PUT 8、PATCH 1、DELETE 35）**。这些操作包含写入与任务管理，不是可整体开放的只读白名单。
- schema Git blob：`2c284695b28a2aedd0d6993e7446c94e8e811ac0`；文件SHA-256：`4bce5d8165f7ddfd992558d4d74b707f806881f0ed951a76c65a9cbcc8e1f5bd`。源码下载在仓库外临时目录，逐文件复算Git blob匹配；仅提炼合同事实，不向项目复制第三方源码/原始样例。
- 查询时上游main为`fd8b4c84b3f29b502bfee4b0544613ecdc08229a`，其schema blob相同，但client/parser等文件不同；本报告命令与安全行为按**已固定发布版**说明，没有自动升级CLI。
- 用已安装Bun的YAML解析器实际解析全文；未安装新依赖、未运行CLI、未创建本轮新的合成集成证据。Python未安装PyYAML，故使用已有解析能力。

### 三张截图的有限含义

只保留本会话截图编号和通用栏目，不把原图、客户名称、账号、真实IP、资产行或现场规模复制到Git/Issue/回执。

| 截图 | 可以确认的UI栏目 | 不能推出 |
|---|---|---|
| 1 暴露面/端口服务 | 端口服务、网站实体、网站路径、网站指纹、爬虫数据；端口表显示IP、端口、协议、服务、产品、版本、响应包、分组、标签、首次/最后发现 | 所有字段在当前接口均返回、实体稳定键、响应包真实格式或完整性、删除/人工排除授权 |
| 2 风险/漏洞列表 | 漏洞、高危应用、高危端口、管理后台四类入口；状态与严重度筛选，漏洞标题/分组、影响资产、资产分组及首次/最后发现栏目 | 空列表不代表无风险或接口不可用；未提供一条实际风险详情/依据样例，UI标签不能自行转换为API枚举编码 |
| 3 资产/种子数据 | 企业主体、关键词、域名WHOIS、邮箱域名、证书信息、网站图标、网站标题、网页哈希入口；企业种子有监控、层级、股权、状态、置信度及创建/更新时间栏目 | 种子不等于已发现的外部资产，监控开关不等于风险状态；不能由UI按钮推断API读写许可或源字段关系 |

### 已定位的资产与暴露面读取入口（静态）

下列为E10 schema＋命令生成规则所得，不是已执行的命令清单；共同前缀为`chaitin-cli cloudAtlas`。字段权威仍在同一矩阵A01—A15；此表只索引命令与GET路径。新增入口均不在当前Exposure单方法Capset内。

| UI/资料类别 | CLI子命令 | 声明的GET路径 |
|---|---|---|
| IP地址 | `asset ip list` | `/v1/asset/ip` |
| 主域名 | `asset root-domain list` | `/v1/asset/root-domain` |
| 子域名DNS列表 | `asset subdomain list` | `/v1/asset/dns` |
| 子域名情报 | `asset subdomain-intel list` | `/v1/asset/subdomain` |
| 证书 | `asset certificate list` | `/v1/asset/cert` |
| 端口服务 | `exposure port-service list` | `/v1/attack/port` |
| 全端口开放（公开schema另列） | `exposure port-service full-port open`（摘要“开放”生成open，但HTTP为GET） | `/v1/attack/openport` |
| 网站实体 | `exposure website list` | `/v1/attack/web` |
| 网站路径 | `exposure website-path list` | `/v1/attack/dir` |
| 网站指纹 | `exposure website-fingerprint list` | `/v1/attack/appfinger` |
| 爬虫数据 | `exposure crawler list` | `/v1/attack/crawler` |
| 企业主体种子 | `asset seed enterprise list` | `/v1/seed/enterprise` |
| 关键词种子 | `asset seed keyword list` | `/v1/seed/keyword` |
| 域名WHOIS种子 | `asset seed domain-whois list` | `/v1/seed/domain` |
| 邮箱域名种子 | `asset seed email-domain list` | `/v1/seed/email-domain` |
| 证书信息种子 | `asset seed certificate-info list` | `/v1/seed/cert` |
| 网站图标种子 | `asset seed favicon list` | `/v1/seed/icon` |
| 网站标题种子 | `asset seed title list` | `/v1/seed/web-title` |

7类种子还声明对应`get`与`/{pk}` GET；它们不是发现资产详情接口。截图“网页哈希”种子在固定公开schema未找到对应操作，不能编造`web-hash`命令，也不能据此断言供应商没有该接口。

已定位的具体差额，而非重新索取整份资料：

- IP的`invalid`在公开枚举里是“历史记录”，不是凭字面推导的无效/删除；其他域状态集合不同。
- `bu`在IP是string、端口是含id/name的object；不能用同一投影抹平。
- `created_at`在IP/端口标题为“创建时间”，网站路径为“首次发现时间”；截图首次发现须与实际返回核对，不能一律等同。
- 网站路径三个时间过滤参数的schema类型与日期字符串说明矛盾，见矩阵A14；后续不可盲目据此生成强类型调用合同。
- 多类有日期过滤和`sort=-id`说明，但没有据此取得跨页快照一致性、删除/ID重用或可靠增量保证。

### 已定位的风险与依据入口（静态）

同样以`chaitin-cli cloudAtlas`为前缀，字段以矩阵R01—R07/E01—E03为准：

| 类别 | CLI子命令 | 声明的GET路径 |
|---|---|---|
| 漏洞实例 | `risk vulnerability list` | `/v1/risk/high-risk` |
| 高危应用聚合 | `risk high-risk-app list` | `/v1/risk/product` |
| 高危端口/服务聚合 | `risk high-risk-port list` | `/v1/risk/service` |
| 管理后台 | `risk admin-panel list` | `/v1/risk/admin` |
| 高危应用命中资产 | `risk high-risk-app list-finger` | `/v1/risk/product/{pk}/finger` |
| 漏洞知识库/策略 | `strategy vulnerability list-vuln` | `/v1/kb/vuln` |

`list-finger`与`list-vuln`来自同组列表名称冲突的确定性后缀规则；`strategy vulnerability list`实际对应更早排序的`/v1/kb/subject`专题列表，不能用来读取漏洞知识条目。所有名称仍是源码静态推导，未运行CLI。high-risk和admin的Apifox状态标developing；这不证明v1.2现场不能用，也不能据已生成命令宣称实读成功。

**漏洞列表不是只有摘要**：[该GET的schema](https://github.com/chaitin/chaitin-cli/blob/857ae38973b9c7886fc088a4065e3694202b7982/products/cloudatlas/spec/openapi.yaml#L17347-L17759)已内嵌`proof`（漏洞证明Markdown），以及`vuln.description/impact/solution/verify_way`等正文。因此候选纵向链首先核对此列表的实际内容，不预设必须再找独立详情API，更不以额外知识库调用代替实例依据。

尚不能冻结的恰是关系与安全语义：实例是整数id，内嵌vuln.id是漏洞知识标识；`assets/assets_type/target`是字符串而非已声明资产外键。应用/服务为聚合粒度，命中计数不等于明细；应用命中列表只声明hostname等字段。`proof`真实正文/嵌入材料、独立检测历史、附件取得/大小/有效期/保留以及这些关系的跨批次稳定性仍需差额材料。

### 传输与只读边界

来源：[client.go](https://github.com/chaitin/chaitin-cli/blob/857ae38973b9c7886fc088a4065e3694202b7982/products/cloudatlas/client.go#L29-L184)、[command.go](https://github.com/chaitin/chaitin-cli/blob/857ae38973b9c7886fc088a4065e3694202b7982/products/cloudatlas/command.go#L22-L60)、[parser.go](https://github.com/chaitin/chaitin-cli/blob/857ae38973b9c7886fc088a4065e3694202b7982/products/cloudatlas/parser.go#L264-L501)。

1. CLI拼接配置base URL与schema路径；认证为`TOKEN`头，空间通常作为`space` query，由具体`--space`或默认`--space-id`提供。取得实际base URL前不猜地址；schema路径`/v1/...`与base中的`/openapi`分层。
2. `handleResponse`解析`code/message/data`包裹并返回`data`，所以公开HTTP字段`data.items[]`通常成为CLI JSON的`items[]`。现有Exposure adapter再裁剪到id/ip/status；丰富字段缺失发生在当前适配层，不能据此说CLI不支持。
3. CLI不是授权边界：存在写入/删除/重扫命令、任意附加query和仅按部分动词/摘要设置的`--yes`确认。新路径只能按固定GET操作＋精确参数最小扩展OctoBus方法/schema/Capset，不开放通用CLI、任意query或把`--yes`当权限控制。
4. 固定CLI默认`--insecure=true`；现有Exposure adapter明确传`--insecure=false`，后续扩展必须保留验证。CLI HTTP超时30秒，adapter进程预算60秒/输出1MiB只是消费者限制，不是供应商限流/体积承诺。
5. CLI错误可包含上游body，verbose可输出URL/body，TOKEN默认掩码仍保留首尾字符，`--verbose-sensitive`会打印敏感值；真实核验不得把CLI原始日志/错误直接写进公开回执。继续复用adapter安全错误映射，关闭verbose及敏感输出，受控环境保管原材料。
6. 固定client未配置专用重定向策略且用`io.ReadAll`读响应；附件网络/大小/重定向/保留必须另立受限合同。只发现字段/URL不代表允许抓取，也不把CLI的`--dry-run`当访问控制。

## 初次隔离合成执行（2026-09-23阶段）

本节保留初次执行结果；E12不回写或冒充这些合成检查。复查入口（仓库根目录，初次使用Node.js v26.5.0）：

```sh
node --experimental-vm-modules tests/cloudatlas_fixture/verify_focus_contract.mjs
```

[检查文件](../../tests/cloudatlas_fixture/verify_focus_contract.mjs)读取未经修改的adapter，通过标准库VM注入有限的内存依赖；使用文档地址`2001:db8::7`、`.invalid`域及明确合成的标记，不创建真实连接/凭据。只在adapter已知边界上注入结果，不制作风险API或猜测关系字段。VM用于隔离已审阅代码的测试依赖，不作为执行恶意代码的安全沙箱；本轮仅加载该仓库adapter。VM Modules的实验性警告如实保留，没有压制。

| 编号 | 本轮合成结果 | 实际观察和证明上限 |
|---|---|---|
| SYN-01 | PASS | 整数id映射成字符串、IPv6文本保留、多余合成属性不进入RPC；不证明原始风险字段可得 |
| SYN-02 | PASS | 空items与total=0正常返回；不证明上游空集/权限过滤含义 |
| SYN-03 | PASS | 两个给定CLI页的current→page及total映射，三个不同来源ID保留；不是供应商快照/总数一致性验证 |
| SYN-04 | PASS | 同ID同IP两行均保留；adapter未去重，不把重复保留当正确跨批次身份策略 |
| SYN-05 | PASS | 未知status、负page、size=201在CLI边界前拒绝；不声称覆盖全部异常输入 |
| SYN-06 | PASS | 非JSON/缺字段响应产生DATA_LOSS类别；不是所有畸形响应穷举 |
| SYN-07 | PASS | 合成401/403区分鉴权/权限错误，敏感标记未出现在adapter错误message；不是SDK/网关完整脱敏验证 |
| SYN-08 | PASS | 第一页取得后，第二页合成503抛出错误而非成功页；无数据库，不证明发布回滚或旧完整版本保留 |
| SYN-09 | PASS | 合成ETIMEDOUT产生连接失败类别且错误message不包含敏感标记；未实际等待60秒或测试CLI进程终止 |

实际输出：9个上述检查分别PASS，末行为`9 checks PASS; actual adapter body only; SDK/CLI/filesystem simulated; real integration NOT_RUN`。

以下没有可验证的新消费者/供应商合同，**不编写一个自证正确的假同步器**：

| 场景 | 本轮结果 | 阻断与后续核验要求 |
|---|---|---|
| 跨空间相同IP、来源ID重用及跨批次稳定键 | BLOCKED | 缺G1/G2的空间/稳定键/重用定义；不能用同IP或配置Hash自动合并 |
| 风险先于资产、关系暂缺/更正、重复风险 | BLOCKED | 缺实际风险合同与关系键；保留待关联是固定Spec要求，但本轮没有实现可运行的消费者 |
| 页中数据变化/总数漂移、增量缺项/全量消失 | BLOCKED | 缺排序/一致性/删除语义；只验证页映射不代表可靠同步，不自行编造补读策略 |
| 第N页失败后的数据库发布、重启恢复、离线保留完整结果 | NOT_RUN | 不运行应用/数据库/新同步实现；原快照离线能力仅引用历史回执 |
| 实际Capset隔离、指纹漂移、项目成员撤权和附件授权 | NOT_RUN | 本轮只静态读取既有门禁；没有现场访问或新的真实权限 |
| 完整Compose fixture、CLI/SDK端到端、真实canary | NOT_RUN | 本轮选择无网络函数体隔离，不运行容器部署、CLI或真实canary；9项检查不能替代这些层次 |

## 授权有界实读E12（2026-09-24）

### 环境与边界

- 原环境无可用OctoBus/CLI；经维护者明确选择，在仓库外私有临时目录安装固定`@chaitin-ai/octobus@0.1.0`、SDK `0.5.0`及CLI `v2606.0.4`，只监听loopback。这是临时进程/文件隔离，**不是容器或操作系统安全沙箱**；未改现有部署。
- CLI使用[官方darwin_arm64发布包](https://github.com/chaitin/chaitin-cli/releases/expanded_assets/v2606.0.4)，下载包SHA-256核对为`58901473f965a2f09bd6772ca4e469be9f9600c88e262cffac2c66af2cf83d5b`。版本依据固定包元数据/发布物，不声称不受支持的`--version`调用成功。
- 链路为调用端→OctoBus精确Capset→临时SDK服务→实际CLI→loopback受限转发器→目标HTTPS。真实云图凭据只供转发器使用；CLI临时配置仅持有独立的本地守卫凭据。CLI显式`--insecure=false`，但CLI这一跳是loopback HTTP，**上游TLS验证由转发器实施**；禁用代理和重定向，不输出原始CLI日志。
- 临时服务`focus-probe`、实例`bounded-source`、Capset `bounded-reads`仅绑定`cloudatlas.probe.v1.ReadProbe/ListIPAssets`、`ListPortServices`、`ListVulnerabilities`三个精确方法，非all-methods。仅映射`GET /openapi/v1/asset/ip`、`/openapi/v1/attack/port`、`/openapi/v1/risk/high-risk`；不暴露任意CLI/query。此包**不是当前Exposure产品包**，不能据此声称产品已有风险同步。
- 临时包SHA-256：`e6a87097a41244cb0b81e7b29fa1ccd8932fa62237b6632168031ebda745afc6`；descriptor SHA-256：`2691e8388463ea1e2b14be783e7519fca02d3699fcaa957619868af543a85601`。每次真实调用前后核对package/descriptor/config/secret Hash、精确实例/方法/Token绑定及转发器配置；组合指纹一致。仅保留一致性结果和上述非秘密摘要，不公布配置/凭据材料。
- 仅指定单空间；page限定1—2、size≤5，串行最多8次，启用后10分钟截止；单响应≤1MiB，源socket超时15秒、body读取预算30秒、CLI进程45秒。鉴权/限流/HTTP或业务失败/结构异常即停止，无自动重试/降级。没有读取附件URL、扫描、写回或触发新风险。

### 实际读取账本

源请求UTC窗口：**2026-09-24T04:03:26Z—04:04:07Z**。以下7次均HTTP 200、业务code 200；共14,492字节。表中total是上游在该请求范围返回的计数，**不是完整枚举或全部类型/状态/权限可见性证明**。

| 次序 | 方法与过滤 | page/size | 返回条数 | 源total | 响应字节 |
|---|---|---|---|---|---|
| LIVE-01 | IP，status=valid | 1/5 | 5 | 13,182 | 3,277 |
| LIVE-02 | 漏洞，不传status | 1/5 | 0 | 0 | 88 |
| LIVE-03 | 端口服务，不传status | 1/5 | 5 | 3,092 | 1,957 |
| LIVE-04 | IP，status=valid | 2/5 | 5 | 13,182 | 3,175 |
| LIVE-05 | 端口服务，不传status | 2/5 | 5 | 3,092 | 2,013 |
| LIVE-06 | IP，valid＋LIVE-03一条端口的精确IP过滤 | 1/5 | 1 | 1 | 705 |
| LIVE-07 | 重读LIVE-01相同请求 | 1/5 | 5 | 13,182 | 3,277 |

- 两页IP与两页端口各10个integer ID，各域样本内不重复；LIVE-07响应字节Hash与LIVE-01相等。只证明该小样本和短时重读，不证明长期ID稳定、排序保证或分页快照。
- LIVE-06取得一个与所选端口相同IP的资产；这是单空间地址匹配观察，不是已证实的稳定关系外键，更不是风险关联。
- **IP `bu`实际为含integer `id`、string `name`的object；公开E10声明string。** 10个IP样本均如此；端口bu同样为object，与端口声明相符。此差异须明确处理，不能静默转换或改写公开声明。
- IP/端口的`created_at/updated_at/lastseen_at`均存在且为string，样本无显式时区偏移/Z；不能推断UTC或其他时区。IP/端口tags均为空array，端口banner/tunnel为空string、categories为空array，不足以验证非空标签/正文依据。
- LIVE-02只验证漏洞列表的成功空包裹；不传status不等于服务端无默认过滤。非空实例字段、`proof`、`vuln`、真实关系及条目可见权限均未证实，不能说“没有风险”或“供应商不支持依据”。未为制造样例而扫描，也未扩读其他风险族或用掉第8次预算。

### 清理与撤销边界

- 完成7次后先关闭源守卫，再删除临时Capset Token；管理面Token数为0。此时旧Token与匿名RPC均返回**503，而非预期401/403**，所以“删Token即认证拒绝”的检查**未验证通过**；仅凭状态码不定位拒绝层，也不证明匿名授权成功或生产越权。不能把这一步记成撤销PASS。
- 随后明确禁用整个临时Capset，RPC返回404；源调用计数始终为7。停止受监督的网关/守卫进程树，验证两监听端口关闭；销毁本会话临时目录内原始响应、真实凭据文件、网关数据、CLI配置、包及依赖。未更改或撤销用户的上游凭据。
- 销毁前程序化检查本次受保护仓库文件未包含所提供的Token；原始客户行未进入对话、模型、仓库或Issue。此处不声称清除了对话历史或完成不可恢复的磁盘擦除；建议轮换已在会话中提供的上游凭据。
- 上述仅为临时环境清理，不是项目成员撤权、产品离线缓存可见性、源权限吊销或保留策略验收；后者继续列G3/G4。

## 原固定Spec逐AC回执

以下保留E12结束时按`d4763e0`进行的完整01A评估，不改Issue状态或追溯升级结果。其“非空风险/全项完成”前置由后文资产先行修订明确调整；不能拿原结果表单独断言修订后的资产片不可准备，也不能因此宣称01A全项通过。

| AC | 整项结果 | 已完成证据及种类 | 剩余门槛 |
|---|---|---|---|
| AC01A-1 材料复用与边界 | BLOCKED | E1—E12及历史#240已纳入；v1.2已确认，本次单空间三GET已获许可并实读 | 其他约定类型/详情及完整范围仍缺，已知`bu`类型差异待确认；不再索取本次已有空间授权 |
| AC01A-2 完整覆盖 | BLOCKED | 同一32项矩阵区分静态声明与样本实见；IP/端口各两页，漏洞成功空集 | 完整列表/详情、非空风险/依据/附件/历史仍未覆盖；不把10条样本当完整同步 |
| AC01A-3 身份与更新 | BLOCKED | IP/端口样本各10个ID无重复、一次IP首页重读字节一致；历史合成单独记账 | G2长期稳定/重用/空间/排序一致性/更新删除未定；源时间无显式时区 |
| AC01A-4 详情/风险/依据链 | BLOCKED | 一条端口IP过滤取得1个IP对象；公开风险读取面已定位，真实列表为空 | 不是稳定外键；尚无非空资产—实例风险—实际依据对应材料，G1/G4不因空集消失 |
| AC01A-5 权限与数据安全 | BLOCKED | 三GET受限执行、指纹一致、源守卫关闭后计数不变，禁用Capset后404，临时材料销毁 | 末Token删除后旧Token/匿名RPC为503，不能验收认证拒绝；产品成员/源权限撤销及保留合同未测 |
| AC01A-6 真实与合成分账 | BLOCKED | 7次真实GET、初次9项合成、公开研究及历史回执分账；真实成功/空集子项PASS | 非空风险/依据、独立详情/附件及真实错误/恢复场景仍未验证，不是完整AC通过 |
| AC01A-7 可实施交接 | BLOCKED | 已有IP/端口候选实读及明确差异，ADR-0021窄替代和旧历史保护不变 | 风险/依据链、稳定身份及安全准入未冻结；临时三方法包不升级生产包、不自动进入01B |

## 资产先行规格交接（本地修订，未实施）

维护者确认：风险暂空，只关注字段；资产用当前空间，本地测试无需脱敏，并授权继续形成调整后的Spec与01B实施合同。此前要求当前先补非空风险脱敏包的下一动作不再适用。

1. **修订与范围**：同一Spec新增明确替代说明及AC01B-1—7。首片为IP＋端口手动同步、本地列表/详情/同来源IP匹配；风险暂未接入，不造风险数据或假0，不自动读取其他空间/类别。其他资产类别、非空风险/依据及长期稳定身份保留到01C/整体验收。
2. **字段交接**：同一矩阵增加字段落点，IP bu按E12的object消费；时区未知保留原string，空值/缺失不混写。其他资产与风险按E10声明记录，不把静态字段写成实测。当前不要求重做接口资料、资产脱敏或非空风险样本。
3. **身份与实现Seam**：使用独立域版本固定来源/范围/源ID，不把一次ID唯一升级为跨批次稳定实体。任务请求幂等与源实体幂等分开；同IP端口只是带版本的匹配查询，不建立虚假的供应商外键。不伪造旧Run/Observation或覆盖历史。
4. **复用与真实差额**：现有`backend/app/api/routes/cloudatlas_ledger.py`复用项目角色与本地分页模式，但仍绑定旧Run，不能改义复用其端点；`backend/app/domain/cloudatlas_sources.py`固定旧package/单方法/非空Token，`source_public`默认查询控制面，新本地GET不能继承该在线前提；`backend/app/domain/models.py`的SourceInstance存在每Project/type单enabled约束，新旧能力必须显式区分。新Spec要求保留这些边界，不声称新模型已存在。
5. **失败与安全仍在首片**：按域暂存/完整发布、预算/分页/指纹异常不覆盖旧成功版本；agent-compose Session未知不重跑。离线阅读与当前权限复核并存；本地真实值只留受控存储/页面，不进入Git/Issue/模型。新增执行的预算、保留截止及清理方式在实际落地前固定。
6. **发布衔接而非自动推进**：本地文档完成后，另经明确授权发布修订、取得真实新commit并复核#247，查重建立01B并引用该版本、记录独立实施授权。不得以占位SHA替换current，不把01A旧AC改成通过或先关闭#247；未获远端授权，本轮不执行以上操作。

## 差额处理（不再索取风险样本）

G1—G4仍唯一记录在[矩阵](../plans/exposure-focus-cloudatlas-coverage-20260923.md#最小材料缺口)，但不再把非空风险或资产脱敏列为当前工作的前置：

- G1：IP/端口当前已知字段可用于首片合同；其余类别和风险/依据留待01C补实读差额。IP bu类型采用实际对象，不等待上游解释才能设计消费。
- G2：未证实长期身份时只保存域版本，不跨批次继承/合并；排序/total不稳定时失败保留旧结果，不假定快照或自动删除。
- G3：已有当前空间选择和本地真实值使用确认；E12预算结束，后续实际执行另固定方法/限制/保留。不得索取Token到文档或将本地许可当公开授权。
- G4：首片资产权限/有界保留不可后置；风险正文/附件安全合同在相应接入前补齐，不要求现在提供样本。

## 本地交付检查

### 初次文档与合成核验（此前已完成）

- 上述9项合成检查已在最终脚本上重跑PASS；只证明表中边界。
- `python3 scripts/check-context-hygiene.py`：PASS（527个已跟踪文件）；另用同一脚本的链接检查函数验证两份交付Markdown（包括未跟踪新回执），全部本地目标存在。
- `git diff --check`：PASS；另检查全部3份交付文件无行末空白。
- 矩阵仍为32行：4项仅历史IP合同可同步、28项待核实；AC01A-1—7均有独立回执，没有删项或升级未知。
- 初始529个文件中，仅原覆盖矩阵变化，其余528个文件Hash不变，包含业务源码/迁移/旧合同及两份`.DS_Store`。新增仅本回执和无网络合成检查脚本；未产生需清理的临时验证文件，没有安装依赖或修改共享服务。
- 后端/前端完整测试、数据库测试、完整CLI/SDK/OctoBus fixture和本轮真实业务验收均NOT_RUN；没有用文档检查或adapter合成检查替代。
- 初次核验由两个独立只读reviewer完成Standards与Spec审阅：均PASS、零blocker；当时对象为3份交付文件。此记录不冒充新增CLI研究的审阅，也不替代01A业务验收。
- 本轮可复查检查脚本SHA-256：`6318bb8db0fe1bc127a05ee2bcb5318fb59fd82ce736412a853a0ab3dd99c849`；未经修改的adapter SHA-256：`94346c722591a1a6ef0d9e17525682c87480f39441491184f7b1d3e0b64fdfe8`。

### 公开CLI补充研究（2026-09-23阶段，此前已完成）

- 完整解析固定schema，核对172路径/191操作/72 GET；24条文档中的GET命令按源码tag翻译、摘要动词、路径排序及重名后缀规则静态校核PASS。核对中修正全端口动词`open`和知识库`list-vuln`；这不是CLI运行测试。
- `python3 scripts/check-context-hygiene.py`：PASS（527个已跟踪文件）。现有链接检查函数另验两份Markdown，本地目标全部存在；行末空白/结尾换行及原32个字段ID、7个AC回执检查PASS。证据编号E10/E11不计入字段行数。
- 本次开始时已有531个受保护文件：只改变原矩阵和本回执，其余529个Hash未变，含上次合成脚本、adapter、固定Spec/ADR、业务源码/迁移/旧合同及两份`.DS_Store`。没有新增依赖、业务代码或生成产物；未重跑上次9项合成。
- 本次真实CloudAtlas/业务模型/数据库、CLI/SDK/OctoBus集成、业务测试与部署仍为NOT_RUN；公开源码和schema解析不升级为这些证据。
- 关键schema定点核对PASS：漏洞proof与内嵌正文、实例ID/知识ID和分组类型差异、7类种子列表/详情字段集合、asset/attack公开详情边界。另核实assets_type的domain/host提示、响应/查询status差异、banner可null、ip_info子字段及独立必填flat，均未升级为现场证据。
- 两轴独立审阅：**Standards PASS（零blocker，1条P3措辞建议已采纳）**；**Spec PASS（零blocker，非阻断的状态枚举差异建议已采纳）**。建议涉及的R03/R04/A14由Main再对照固定schema补明，不改变AC或授权；这不是01A业务验收通过。
- 两轴审阅完成后已删除本会话创建的仓库外公开源码临时缓存；未将第三方源码、原始schema样例或客户截图加入项目。

### 授权有界实读交付检查（2026-09-24）

- 实际链路完成上述7次源GET；清理后的本地认证检查503不记PASS，禁用Capset后404及源计数仍为7分别记录。临时进程停止、两端口关闭、私有目录销毁；随后再次检查临时目录不存在。
- `python3 scripts/check-context-hygiene.py`：PASS（527个已跟踪文件）；另用现有链接检查函数检查两份Markdown，包括未跟踪回执，全部本地目标存在。两份文档行末空白/结尾换行检查PASS。
- 原32个字段ID完整保留，4项仅历史IP合同可同步、28项待核实；7个AC均独立保留BLOCKED；7行真实账本响应字节合计14,492，检查PASS。
- 本次只编辑同一矩阵/回执；adapter与已有合成检查脚本SHA-256仍与上述原记录一致。没有新增持久依赖、业务代码、迁移或生成产物，没有重跑先前9项合成或前后端/数据库套件；这些检查不替代完整01A业务验收。
- E12及更新结论经两个独立只读reviewer审阅：**Standards PASS，零blocker；Spec PASS，零blocker**。审阅认可的是证据记录和范围合规，不是完整01A业务验收；随后仅追加本节已运行检查回执并澄清初次基线核对时点。

### 资产先行规格修订检查（2026-09-24）

- 本轮仅修改既有Spec、矩阵、阶段定义和本回执，没有新增文档、业务代码、迁移、依赖或运行环境；未执行新的云图/模型/数据库调用，也未执行远端发布。
- `python3 scripts/check-context-hygiene.py`：PASS（527个已跟踪文件）；现有链接检查函数另验4份文档，本地目标及行末空白/结尾换行检查PASS；未找到指向本次改名标题的文档片段链接。
- 32个矩阵字段ID及4项历史可同步/28项待核实均保留；原7个AC及回执BLOCKED结果、7行真实读取账本未升级；新增AC01B-1—7完整。它们是未来实施的验收要求，不是本轮测试通过记录。
- 531个本轮开始时的受保护文件中，仅上述4份文档变化，其余527个Hash不变，包括原合成检查、业务源码、已接受ADR、current入口和两份`.DS_Store`。前后端/数据库/合成业务套件未运行，文档检查不替代产品验收。
- 本轮两轴独立审阅：**Standards PASS，零blocker；Spec PASS，零blocker**。Standards的一条非阻断建议已采纳：入口明确01B细化就在同一Spec内，不要求再造一份。另澄清上游TLS/重定向/流式体积门禁、归档只读及收到访问拒绝后的缓存清理，Spec审阅已覆盖这些澄清。审阅不等于01B已实现、业务验收通过或获得发布授权。
