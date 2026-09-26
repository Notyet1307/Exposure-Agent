# 云图资产、风险与依据覆盖矩阵（EXP-FOCUS-01A 分层核验）

核验日期：2026-09-23文档/合成及公开CLI研究，2026-09-24授权有界实读；批准基线 `d4763e0ae2da7b60773563101c5f91cb7c773840`，代码读取版本 `ff1cc5c7285abeb7b55512bd9c116a4d961f0b67`。**批准Spec的完整性附件，非完整同步验收结论**；配套[聚焦Spec](../specs/exposure-focus-release-1.md)，任务为[#247](https://github.com/Notyet1307/Exposure-Agent/issues/247)。只追加证据，不改变固定Spec或验收要求；详见[01A核验回执](../work/exp-focus-01a-contract-verification-20260923.md)。E12为新增真实读取，其余历史/合成/静态证据不混账；没有业务数据库或模型调用。GitHub状态仍只在Issue维护，本地回执未发布。

## 已找到的材料与证据强度

| 编号 | 已有材料 | 能证明什么 / 不能证明什么 |
|---|---|---|
| E1 | [cloudatlas_read.proto](../../octobus/cloudatlas-read/proto/cloudatlas_read.proto) 5—26行 | **当前Exposure包**只有`cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets`；请求status/page/size；IPAsset仅id/ip/status；返回items/page/size/total。该包没有资产详情、风险或附件方法，不代表云图产品或CLI缺少这些能力 |
| E2 | [cloudatlas-read.js](../../octobus/cloudatlas-read/bin/cloudatlas-read.js) 19—46、52—85、99—127行 | 使用现有CLI `cloudAtlas asset ip list`；从config的baseUrl/spaceId及secret token形成隔离CLI配置；CLI返回`items[].id/ip/status`，id整数转字符串，`current`映射`page`，多余属性未传入产品协议。允许status valid/await/ignored/invalid、size≤200；这些是代码限制，不证明目标云图版本全部状态语义 |
| E3 | [fixture_upstream.py](../../tests/cloudatlas_fixture/fixture_upstream.py) 123—185行、[verify.py](../../tests/cloudatlas_fixture/verify.py)、[fixture脚本](../../scripts/test-cloudatlas-fixture.sh)、[OctoBus说明](../../octobus/README.md) | 合成GET `/openapi/v1/asset/ip`，TOKEN header，响应`data.current/items/size/total`；fixture有401/403/503/坏结构/断连分支。E3本身不是正式API文档；补充E10提供独立公开schema出处，也不能把fixture执行升级为真实集成 |
| E4 | [cloudatlas_ledger.py](../../backend/app/domain/cloudatlas_ledger.py) 88—146、169—214、263—330、360—421行；[API测试](../../backend/tests/api/routes/test_cloudatlas_ledger.py) | 已发布Run的SourceSnapshot/Observation本地读模型；asset_id/raw_ip/canonical_ip/source_status，本地tags/followed分层；count/total_records/unique_ips分开；risk_state固定NOT_CONNECTED。source_created_at来自本地snapshot.created_at，非上游更新时间。测试存在不等于本轮运行通过 |
| E5 | [真实旧回执 #240](https://github.com/Notyet1307/Exposure-Agent/issues/240) 正文的“2026-09-15 恢复后的本地完成回执”/“2026-09-15 本地部署验收”；[PR #241](https://github.com/Notyet1307/Exposure-Agent/pull/241) | 2026-09-23复读的历史证据：指定来源valid共66页13,182条，IPv6 30条；Runner落地与逐页本地读，网关停止后固定快照仍可读。只限旧IP合同；不是风险/详情/全状态验证，不证明ID长期稳定、分页快照、现时权限或部署。本轮只读公开聚合回执，未进入既有私有存储或读取原始响应/凭据 |
| E6 | [canary runbook](../runbooks/cloudatlas-canary.md)、[ADR-0019](../adr/0019-cloudatlas-native-ledger-and-scoped-profile.md) | 已有隔离、脱敏、单方法授权及真实核验方法；旧流程要求客户输入和Run，不能直接代替独立同步新合同。未执行runbook |
| E7 | [无网络合成检查](../../tests/cloudatlas_fixture/verify_focus_contract.mjs)，命令 `node --experimental-vm-modules tests/cloudatlas_fixture/verify_focus_contract.mjs` | 初次核验9项PASS：执行原adapter函数体，CLI/SDK/文件系统由内存替身提供；覆盖字段裁剪/IPv6、空集、页码映射、重复保留、输入拒绝、坏响应、401/403脱敏、第N页失败及超时。补充CLI研究没有重跑/修改该脚本；不是完整fixture/真实CLI/OctoBus/数据库集成 |
| E8 | [cloudatlas_sources.py](../../backend/app/domain/cloudatlas_sources.py) 176—289、291—356行（静态） | 指纹固定package/descriptor/config/secret Hash、精确实例/单方法和token绑定；Capset必须启用且非all-methods。旧后端每页仍强制valid，检查精确id/ip/status键与页码/size/非负total；验证读取前后指纹一致。未运行此后端或连接现场，指纹不证明业务身份/当前权限 |
| E9 | [旧Runner](../../backend/app/domain/governance_runs.py) 1277—1458行、[旧Artifact解析](../../backend/app/domain/ip_consistency.py) 425—565行、[旧AI读取消费者](../../backend/app/domain/ai_investigation_tools.py) 256—320行（静态） | Runner/解析器检查页序/统一total/累计完整性但保留重复来源行；旧AI读取拒绝重复ID并限制5页/500条。它们是不同用途的旧消费者策略，不是供应商去重/限流承诺；本轮未执行这些路径，不改变旧合同 |
| E10 | chaitin-cli `v2606.0.4`→commit `857ae38973b9c7886fc088a4065e3694202b7982` 的[内置OpenAPI](https://github.com/chaitin/chaitin-cli/blob/857ae38973b9c7886fc088a4065e3694202b7982/products/cloudatlas/spec/openapi.yaml)、[命令生成器](https://github.com/chaitin/chaitin-cli/blob/857ae38973b9c7886fc088a4065e3694202b7982/products/cloudatlas/parser.go)、[客户端](https://github.com/chaitin/chaitin-cli/blob/857ae38973b9c7886fc088a4065e3694202b7982/products/cloudatlas/client.go) | 与当前Dockerfile固定CLI发布版一致；全文解析172路径/191操作/72 GET，公开声明超出旧IP方法；`data`由CLI解包。只证明公开静态合同，未运行CLI或v1.2现场API。GET全集也不是授权白名单；schema、版本身份和安全边界见回执 |
| E11 | 维护者在本会话确认产品**v1.2**、OctoBus＋开源CLI路径，并提供暴露面/风险/种子数据三张截图 | 产品版本已知；仅转述栏目，不复制客户标识、原图或真实行。UI存在不等于API返回齐全；空风险表不能证明无风险/无权限，也不能代替详情/依据样例 |
| E12 | 2026-09-24维护者明确授权的临时OctoBus＋固定CLI＋受限HTTPS转发器实读；来源代号LIVE-A，完整方法/预算/指纹与清理记录见回执 | 7次GET均HTTP/业务200；IP valid、端口各两页共10条；漏洞列表0条；一条端口IP过滤取得一个IP对象；IP首页面重读字节一致。IP `bu`实为object，与E10 string声明冲突；时间无显式时区。仅有界样本，不证明完整同步、长期稳定键或非空风险/依据。临时包不是当前产品包，未落业务库 |

资料检索范围：原仓库、历史聚合回执、固定CLI发布版完整schema及生成/传输代码，以及E12的单空间三GET有界样本。目标产品v1.2已确认；已有非空IP/端口样本，剩余缺口是公开声明差异、非空风险/依据、详情/关系及长期同步/安全语义。不再索取已有授权或整份公开接口资料；凭据和原始响应不入仓库。

## 读表规则

- “结果”只用：**已验证可同步、待核实、接口缺失、权限缺失、明确不适用**。本表不因产品包尚未实现就断言上游“接口缺失”；缺少资料统一待核实，待01A获得事实后再分类。
- “已验证可同步”仍只指E5的**历史指定来源/valid/IP合同**，不以E12有界样本冒充新域完整同步验收。E10“schema已声明”、E12“样本实见”与尚未确认的完整性/长期语义分别记录；无公开或实读依据的路径仍写未知。
- 标识路径分层：E10公开HTTP响应通常为`data.items[]`，E3为合成HTTP，E2 CLI JSON解包后为`items[]`，E1产品RPC再次投影。以下E10字段均按HTTP schema路径记录，不把丰富上游字段冒称当前RPC已返回。
- 为压缩同层字段清单，末级字段用`/`并列，例如`bu.id/name`表示`bu.id`和`bu.name`，不是包含斜杠的JSON键；省略的列表项前缀沿用该行的`data.items[]`。
- “候选保存/页面”是待批准设计意图，不是当前实现。新稳定来源身份建议包含来源空间和对象身份，但实际键字段/长期稳定性仍未知；旧`source_record_key`只定位快照内行，不能用作跨批次实体键。
- E7为消费者合成边界，E10为公开静态合同，E11为版本/UI，E12为授权真实样本。4项“已验证可同步”仍仅限E5历史IP，28项“待核实”不因部分子项PASS升级；“待核实”不表示完全没有实读证据。

## 资产先行字段落点（2026-09-24本地规格修订）

维护者已确认风险数据暂留空、先关注字段，资产使用当前空间且本地测试无需脱敏。对应[Spec修订及01B合同](../specs/exposure-focus-release-1.md)以相关Issue引用的批准commit生效；这不是新增实读证据，32项结果及E12账本不升级。

| 字段组 | 精确来源路径/类型依据 | 01B消费与本地落点 |
|---|---|---|
| 分页/身份 | `data.current/size/total/items[]`；IP/端口`items[].id`源integer，E10＋E12 | 新域版本内记录，保留来源/过滤/版本；接口边界无损传ID；不把同ID当长期实体 |
| IP主字段 | `data.items[].ip/version/subnet/status/live_port/provider/as_name/as_num/location/country/province/city`，E10声明＋E12实见 | 约定结构化字段进新本地读模型；列表/详情分层展示，不仅三个旧IP字段；不自行猜未核实字段类型 |
| 端口主字段 | `data.items[].ip/port/protocol/service/tunnel/product/version/banner/status`，E10声明＋E12实见 | 独立端口记录及详情；按同来源规范IP查询匹配，不写稳定资产外键；banner转义纯文本 |
| 业务分组 | 两域`data.items[].bu.id/name`；E12为object内integer/string | 本片采用实见object，明确覆盖公开IP string声明，不等供应商补样例才能编制合同；不据此认定业务归属 |
| 标签/来源/分类 | `data.items[].tags[].pk/name`；IP `sources[].source/reason/factor/lastseen_at`；端口`categories[]`，嵌套合同按E10 | IP/端口tags、端口categories仅实见空array；非空项类型按固定schema验证，不能冒称实测。来源属性结构化保存，不整体复制HTTP body |
| 时间/空值 | 两域`data.items[].created_at/updated_at/lastseen_at`为string；端口banner/tunnel实见空string，banner公开可null | 保留源字符串及无明确时区事实，抓取/发布时间另列；缺失/null/空串/空数组不混写 |
| 风险字段 | R01—R07/E01—E03列出的`data.items[]`及`proof/vuln`等E10声明；E12只有空items | 继续字段研究与差额记录；非空风险、依据及附件后置，01B不造风险表/假返回0/扫描样本 |

其他类别不从矩阵删除：主域名/DNS/子域名见A04，证书A08，网站/路径/爬虫A09，指纹A07，种子A04/A05/A10；其字段已定位为E10静态声明，当前空间相应实读及详情差额仍未验证。它们进入01C覆盖，不把首片两类对象冒称全部资产。

## 主域名字段落点（2026-09-25）

维护者已批准配套[01C-ROOT Spec](../specs/exposure-focus-release-1.md#exp-focus-01c-root主域名资产本地阅读)及本字段合同；它们由实施Issue固定准确commit，仅细化E10既有公开材料，不是新的真实证据。精确出处：[固定OpenAPI](https://github.com/chaitin/chaitin-cli/blob/857ae38973b9c7886fc088a4065e3694202b7982/products/cloudatlas/spec/openapi.yaml)的`paths./v1/asset/root-domain.get`。该操作声明status必填（valid/await/ignored/negative）、默认sort=-id及空间/页码/大小参数；本片固定valid、-id，不开放其他来源过滤。公开schema未声明此资产的独立详情GET。

| 精确响应路径 | E10声明类型与必填性 | 本片约定本地消费/展示（非已实现） |
|---|---|---|
| `data.current/size/total/items` | 必填integer/integer/integer/array | 页码/大小/非负total校验；源total与已保存条数分开 |
| `data.items[].id/root_domain/status` | 必填integer/string/string，响应status未声明enum | ID无损保存、域版本内身份；域名和状态保留原值，列表/详情可见，不按IP状态枚举硬转 |
| `data.items[].icp_date/icp_num/icp_official_name` | 三个字段均必填，均为nullable string | 备案时间/号/主体；null与空串区分，不证明客户归属 |
| `data.items[].whois_registrant/whois_email/whois_expiration_time` | 三个字段均必填，均为nullable string | 注册主体/邮箱/有效期，详情纯文本；真实邮箱不出受控本地边界，不自动发信 |
| `data.items[].valid_subdomain` | 必填integer | 明确“来源报告有效子域名数”，不当本地子域名列表计数，不补造明细 |
| `data.items[].sources[]` | sources必填array；每项object的source/reason/factor均为必填string | 全部来源项结构化呈现；空array与缺失分开，字段不是外键/下载授权，不自动打开链接 |
| `data.items[].created_at/updated_at/lastseen_at` | 三个字段均必填string，未承诺时区 | 保存源string；源创建/更新/最后发现与本地抓取/发布分别展示，不补时区 |

以上14个记录字段均在E10 required中；仅六个备案/WHOIS字段声明nullable。缺字段与null不互相补齐：本片合同按必填性拒绝缺失记录，不以空值填充凑成功；其他未知字段只记字段差额。此操作未声明IP/端口的bu、tags，不迁入那些字段或伪造空数组。

A04/A05/A10/A12—A15对应的主域名现场内容、长期身份、分页变化和详情差额仍**待核实**；公开示例不是当前空间样本，不改变已有32项结果。DNS、子域名、其他资产和非空风险/依据继续留在01C后续范围，非本切片验收。

## DNS记录字段落点（2026-09-26）

本段与[01C-DNS候选Spec](../specs/exposure-focus-release-1.md#exp-focus-01c-dnsdns记录本地阅读)及ADR候选窄扩展一并待批准，尚未实现或实读。精确出处仍是E10 [固定OpenAPI](https://github.com/chaitin/chaitin-cli/blob/857ae38973b9c7886fc088a4065e3694202b7982/products/cloudatlas/spec/openapi.yaml)的`paths./v1/asset/dns.get`，公开操作名为“子域名列表(列表模式)”；不要与独立`/v1/asset/subdomain`情报列表混同。

请求中space为必填integer、flat为必填string；本片显式固定十进制空间、`flat="1"`、`status=valid`、`sort=-id`、page和size，不开放聚合或其他过滤。query status的valid/invalid/ignored与query rdtype的A/NS/MX/AAAA/SOA/TXT只是查询枚举；响应对应字段只声明string，不能借查询枚举裁掉响应值。page/size示例为0不构成从0起页的保证；本片消费者合同从1起，实际不符须停并记录差额。

| 精确响应路径 | E10声明类型与必填性 | 候选本地消费/展示（非已实现） |
|---|---|---|
| `code/message/data` | 必填integer/string/object | 成功包裹校验，错误脱敏；不持久化整个HTTP包裹 |
| `data.current/size/total/items` | 必填integer/integer/integer/array | 页码/大小/非负total校验；源total与已保存条数、本地匹配数分开 |
| `data.items[].id` | 必填integer | 十进制字符串无损传输/保存，域版本内身份；不推导长期稳定或跨资产身份 |
| `data.items[].domain/subdomain` | 两个字段均必填string | 分别是源声明主域名/子域名文本；subdomain作列表名称及唯一名称搜索字段，domain在详情保留；不拼接、解析或绑定本地主域名 |
| `data.items[].rdtype/record/status` | 三个字段均必填string，响应无enum | 列表/详情保留解析类型、解析值、状态原文；解析值即使形似IP/URL/邮箱也只是文本，不建立外键或触发外部动作 |
| `data.items[].bu` | 必填string | 源声明分组，空串保留；不套用IP/端口bu对象，不推断客户归属；实见object须记录差额并先修订合同 |
| `data.items[].tags[]` | tags必填array；每项object的pk/name必填integer/string | 标签ID无损字符串化，名称原文、顺序与空数组保留；不合并、推断关联或补造缺字段 |
| `data.items[].created_at/updated_at/lastseen_at` | 三个字段均必填string，未声明时区 | 保留源时间原文与空串，另列本地抓取/发布/保留截止；不补时区或作为可靠增量水位 |

共11个记录字段全部required，均未声明nullable；tags项的pk/name也未声明nullable。缺失/null/类型错误拒绝整个未封存版本，合法空字符串和空数组保留，未知属性只记录脱敏字段差额、不整包保存。DNS操作未声明root-domain的WHOIS/备案/sources，不迁入或补造这些字段；所有DNS文本只在受控本地可见，公开材料仅保留字段/类型/聚合证据。

本次仅完成公开schema结构化核对，不执行DNS接口，也不把#257主域名实读迁作DNS证据。A04/A05/A10/A12—A15的DNS现场字段、身份/分页长期语义与权限差额仍待核实；原32项结果和风险/附件缺口不升级。

## 资产覆盖

| ID / 约定信息 | 实际来源及精确字段路径（未知明确写出） | 稳定键/可得性与结果 | 当前本地保存 → 候选保存/页面 | 验收方式 / 缺口 |
|---|---|---|---|---|
| A01 IP来源ID | E10 `GET /v1/asset/ip`→`data.items[].id`（integer）；E1/E2转为字符串；E12两页10条均integer且样本内ID不重复 | **已验证可同步**仅旧合同；E12不证明长期稳定/ID重用 | Observation.cloudatlas_asset_id → 新来源对象身份；外部资产列表/详情 | 同范围多批次/删除重建仍需G2，不用一次唯一性或同IP代替稳定ID |
| A02 IP标识 | E10 `data.items[].ip/version/subnet`；E12三字段实见；E1/E2只保留ip，E7保留文档用IPv6 | IPv4/IPv6旧回执可读；**已验证可同步**仅旧合同；IP不是跨来源稳定键 | Observation.raw_ip/canonical_ip → 保留原值及确定性规范值；搜索/详情 | 本轮未专门覆盖IPv6、mapped IPv6或跨空间；version是IP版本属性，不是产品版本，G1/G2 |
| A03 来源空间/版本 | E2 `spaceId/baseUrl`、E8指纹；E10 query `space`及TOKEN头；E11确认v1.2；E12在维护者指定单空间LIVE-A成功读取 | 当前调用范围已授权/执行，跨空间归属与身份仍**待核实** | SourceInstance及Run固定指纹 → 来源空间/合同身份；详情来源区 | 地址、空间值、凭据不入回执；CLI/OpenAPI版本不当产品版本，配置指纹不当客户归属证明，G2/G3 |
| A04 资产类型及非IP标识 | E10 GET `/v1/asset/root-domain`→`data.items[].id/root_domain`；`/v1/asset/dns`→`id/domain/subdomain/rdtype/record`；`/v1/asset/subdomain`→`id/subdomain/source_name/reason`。证书、网站/端口见A06—A09；种子另有7类GET `/v1/seed/{cert,domain,email-domain,enterprise,icon,keyword,web-title}` | 公开类型/字段已定位，跨类型身份和目标覆盖仍**待核实** | 当前仅IP → 按确认类型保存/筛选；种子与已发现资产分开 | `/asset/dns`与`/asset/subdomain`不是同一返回；截图“网页哈希”种子在此固定schema未声明对应读取操作，不代表供应商无接口；G1 |
| A05 归属/业务/负责人等源属性 | **E10 IP `data.items[].bu`声明string；E12全部10个IP样本实际为object `{id:integer,name:string}`**；端口bu同样为该object，与E10端口声明相符。E10主域名`icp_date/icp_num/icp_official_name/whois_registrant/whois_email/whois_expiration_time`，企业种子`id/name/confidence/equity/investment_path/is_history/enable`未实读 | 本片采用目标实见object；负责人/权威映射及其余类别仍**待核实** | 当前无完整源属性 → 保存源声明；与客户责任字段/本地确认分栏 | 不静默压成string；公开声明差异保留但不阻塞本片采用实见类型。分组/登记人/种子企业不当客户归属证明，G1 |
| A06 端口与服务 | E10 `/v1/attack/port`→`id/ip/port/protocol/service/tunnel/product/version/banner/status/categories[]`；banner声明可null，E12两页10条的banner/tunnel均为空string、categories均为空array。`/v1/attack/openport`另有`id/ip/port/protocol/created_at/updated_at/lastseen_at`，未实读；分组/标签/时间见A05/A10/A13 | 端口样本可读；独立全端口、完整详情及稳定外键仍**待核实** | 当前产品IP协议无 → 服务属性与资产关联 | E12选一条端口IP过滤IP列表取得1条同IP对象，仅单空间字符串匹配，不是稳定外键；空banner不证明完整请求响应可得，G1/G2/G4 |
| A07 组件与指纹 | E10 GET `/v1/attack/appfinger`→`data.items[].id/url/scheme/hostname/netloc/path/port/product_name/product_uuid/vendor/vendor_uuid/version/cpe/bu/status`；网站路径项`apps[].product_uuid/vendor_uuid/product_name/vendor_name/cpe/version/created_at/updated_at/lastseen_at` | 组件/指纹声明已定位，**待核实** | 当前无 → 来源组件、版本和指纹详情 | product_uuid是产品引用，不自动等于风险实例或网站资产ID；空值/版本和命中关系仍需G1/G2 |
| A08 证书 | E10 GET `/v1/asset/cert`→`data.items[].id/cn_name/o_name/ou_name/email_name/subject/issuer/serial_number/sha256/sha1/md5/start_date/end_date/trusted/status/created_at/updated_at/lastseen_at`及`sources[].source/reason/factor` | 证书字段及指纹已声明，身份/关联仍**待核实** | 当前无 → 证书属性及经确认的关联/依据 | 不把证书指纹或sources.reason当上游关联外键；有效期类型/时区、完整材料及敏感处理需G1/G2/G4 |
| A09 网站/URL详情 | E10 GET `/v1/attack/web`→`data.items[].id/url/scheme/hostname/netloc/port/ip/entity/bu/status`；`entity`描述为scheme＋hostname＋port的网站MD5。`/v1/attack/dir`另外有`path/level/status_code/title/render_title/server/x_powered_by/location/content_type/content_lines/content_words/content_length/body_md5_hash/icon_url/icon_mmh3_hash/icon_md5_hash/isadmin/screenshot_link`、`ip_info.ip/version/subnet/provider/as_name/as_num/location/country/province/city`及A07 apps。`/v1/attack/crawler`有`id/target/source/uri/method/hostname/request_type/path/headers/data/status` | 公开网站/路径/爬虫字段已定位，完整正文与详情差异**待核实** | 当前无；客户Web URL不是云图详情 → 约定结构化网站详情/受控材料 | 列表字段丰富≠完整页面正文；entity稳定性/哈希重算未承诺；爬虫headers/data敏感且不当然属于风险实例依据，G1/G2/G4 |
| A10 云图标签及其他约定属性 | E10 IP/DNS/端口/网站/路径/指纹等项声明`data.items[].tags[].pk/name`，并非每类都有；E12 IP/端口tags均空array，未验证非空标签项。IP `live_port/provider/as_name/as_num/location/country/province/city/sources`实见，嵌套`sources[].source/reason/factor/lastseen_at`语义仍待核；种子图标`icon_url/md5_value/mmh3_value`、通用种子`name/type/enable/confidence`仍仅E10 | 样本字段与空值已观察，完整标签/来源语义仍**待核实** | 本地CloudAtlasLedgerRevision → 源字段/本地管理分开保存展示 | 不把空array证明成标签项合同，不把reason/factor当外键；不将缺少字段的类型补造空合同，G1 |
| A11 上游状态原值 | E10 IP项`data.items[].status`；E1/E2仍传原值，旧runner固定valid | 原值**已验证可同步**仅旧合同；业务状态分别见A12 | Observation.cloudatlas_status → 保留源原值；资产状态 | valid不表示无风险，种子enable不是资产status，也不是本地处置 |
| A12 状态定义及全部过滤范围 | E10 IP query枚举：`valid`已确认、`await`待确认、`ignored`已排除、`invalid`历史记录；主域名含`negative`而非invalid；证书`valid/await/ignored`；DNS及网站/端口等`valid/invalid/ignored`；子域名情报`valid/ignored`；种子另用enable/confidence。旧E8仍固定valid | 过滤值及IP中文含义已声明，不再完全未知；转换/可见范围仍**待核实** | 当前status_filter固定valid → 按域保留源状态/过滤范围 | 不能把IP四值全局复用或把ignored/invalid当删除；现场转换、权限与总数口径G1/G2/G3 |
| A13 发现/更新时间/观测时间 | E10多数资产/暴露面项有`created_at/updated_at/lastseen_at`；子域名情报仅created_at/lastseen_at，种子为created_at/updated_at。IP/端口created_at标题为创建时间，网站路径为首次发现时间；E12 IP/端口三字段均为string，无显式Z或时区偏移 | 实际字段已读，时区/精度/语义及更新保证仍**待核实** | 本地snapshot.created_at → 与源时间、抓取/成功时间分开；新鲜度区 | 不自行补UTC/本地时区；不把所有created_at统称首次发现，也不把updated_at当可靠增量水位，G2 |
| A14 列表分页与总数 | E10 `page/size/sort`及`data.current/size/total/items[]`，多类sort说明默认-id，DNS/网站路径另必填flat（0聚合/1列表）；E2解包/E1映射page。E12 IP valid两页各5条、total 13,182；端口两页各5条、total 3,092；IP第一页重读字节一致 | **已验证可同步**仅历史valid全页遍历；E12仅有界分页/短时重读，不是完整遍历或一致性快照 | 旧分页Artifact+快照计数 → 每域成功版本/范围和任务状态 | 各域10个样本ID不重复不证明长期唯一。`/attack/dir`的created_at_before、lastseen_at_after声明integer，lastseen_at_before声明boolean，说明却要求日期字符串；须核对而非静默纠正，时间过滤不是增量游标，G1/G2 |
| A15 独立详情与列表差异 | E10上述asset/attack族未声明独立`/{pk}` GET；7类seed有`/{pk}` GET，`data`字段集合与对应列表项相同。E7证明当前adapter裁去三个IP字段之外的属性 | 公开详情边界已定位，UI完整详情/其他接口仍**待核实** | 当前本地“详情”只是摘要行 → 按约定保存完整可得详情 | 不把未列入此schema推断为供应商接口缺失，也不把丰富列表当已经覆盖UI详情；G1差额核对 |

## 风险、依据及关联历史覆盖

| ID / 约定信息 | 实际接口/字段路径 | 稳定键/可得性与结果 | 当前保存 → 候选保存/页面 | 验收方式 / 缺口 |
|---|---|---|---|---|
| R01 风险列表、稳定ID | E10 `/v1/risk/high-risk`项id为integer、vuln.id为string；`/v1/risk/product`聚合用product_id，`/v1/risk/service`聚合id为string，`/v1/risk/admin`项id为integer，均有分页包裹。E12仅high-risk不传status，HTTP/业务200、items空、total=0 | 空列表包裹可读；非空项、实际实例权限与稳定/重用语义仍**待核实**；high-risk/admin静态x-apifox-status为developing | 当前产品RPC无风险方法，risk_state=NOT_CONNECTED → 分类型来源风险/版本；列表分页 | 0仅代表本次来源/请求返回，不推断全空间无风险、无权限或依据不可得；不把vuln.id/聚合ID当实例ID，G1/G2 |
| R02 名称、类别、源等级 | high-risk项`title/severity/subjects[].pk/subjects[].name`及`vuln.category/cve/cnvd/cnnvd/cwe/cvss3/severity/title`；product项`product/product_id/vendor/cpe/vuln_count/finger_count`；service项`service/protocol/description/port_count`；admin项`web_title/url/hostname/port/is_ip` | 字段已声明，**待核实** | 无 → 按风险族保留名称/类别/源等级，计数不冒充明细 | high-risk参数说明等级1严重/2高危/3中危/4写作“低位”（UI为低危）/9未知；核对差异，不从资产status或Finding推等级，G1 |
| R03 源状态及时间 | high-risk项`status/created_at/updated_at/lastseen_at`；查询说明`open`待处理、`following`跟进中、`false_positive`误报、`fixing`修复中、`fixed`已修复、`ignored`可接受；但响应status枚举未含fixing，且把ignored描述为“忽略”。admin有`status/created_at/lastseen_at`；product/service为`created/lastseen`且项内无status | 字段/查询说明已知，响应枚举与查询差异、转换/默认过滤仍**待核实** | 无 → 源状态与源时间独立于本地处置保存 | 不把有矛盾的声明直接固化成状态机；资产ignored又是已排除，不能全局共用含义。status/severity query为数组声明，多值编码/实际状态需G1/G2核对 |
| R04 受影响资产/服务关系 | high-risk项`assets/assets_type/target`均string；assets_type枚举`domain`域名、`host`IP。`bu.id/name`及`tags[].pk/name`另列；GET `/v1/risk/product/{pk}/finger`项`hostname/finger_count/tags[]/created/lastseen`；admin有hostname/port/url | 类型提示/关联描述已声明，稳定资产外键及跨空间语义**待核实** | 无 → 按核实来源/类型/关系保存，缺资产时保留待关联 | 类型提示不等于稳定外键；不把assets当asset_id，不从计数补明细，不跨空间仅按IP/hostname拼接；G1/G2 |
| R05 描述、影响说明 | high-risk列表项内已有`vuln.description/impact/disclosure_date/reference[]`；product/service的`subjects[].description`。GET `/v1/kb/vuln`另有知识库/策略说明，但不是现场实例 | 描述/危害字段已声明，实际内容/完整性**待核实** | 无 → 来源结构化正文/安全详情 | 不必先假设独立详情endpoint才有正文；不拿独立知识库条目证明客户实例，仍须代表返回/页面对应，G1/G4 |
| R06 检测依据、修复建议 | high-risk项`proof`为漏洞证明Markdown，`vuln.solution/verify_way`为解决方案/检测方式；product/service另有`subjects[].solution` | 实例proof字段与建议已声明，真实内容/关系/可得性**待核实** | 无 → 来源判断及依据；不以AI补造 | verify_way是方法说明而非已发生的检测；proof格式/脱敏/嵌入材料和页面完整性需G1/G4 |
| R07 风险变更/检测历史 | E10目标风险族声明创建/更新/最后发现时间，但未声明独立检测事件/变更历史读取合同 | 历史是否另有接口及事件稳定键**待核实** | 无上游历史合同 → 可得历史与本地同步历史分开 | 时间点不是检测历史；不将本地AuditEvent当云图事件，也不从此schema遗漏断言供应商无历史，G1/G2 |
| E01 证据文本/请求响应 | E10 high-risk项`data.items[].proof` string（Markdown）已声明；没有独立结构化request/response字段。爬虫项headers/data见A09，但未声明它与风险proof的关联 | 公开proof载体已知，真实结构/敏感范围/访问权限**待核实** | 现有Evidence是旧Run引用 → 必要受控源证据及身份 | Markdown不得自动执行HTML/远端请求；不能把banner/爬虫请求直接当同一风险实例证明；G1/G4 |
| E02 截图/二进制附件 | E10网站路径项`data.items[].screenshot_link`可null；admin有`screenshot_link/icon_url`，种子图标有icon_url；未声明附件清单/二进制元数据 | 链接字段已知，附件ID/类型/大小/权限/导出仍**待核实** | 无同步链 → 经批准的本地受控材料及校验身份 | 链接存在不证明可取得或允许保留；断连阅读、大小/类型/重定向/SSRF/撤权需G4 |
| E03 附件链接、有效期与取得方式 | 已声明screenshot_link/icon_url及vuln.reference[]；其签名/有效期/刷新/允许域名/受控下载方法未见明确合同 | **待核实** | 无 → 本地材料引用，外链只作可选诊断 | 参考链接不是附件授权；不得自动追踪Markdown中的URL或猜抓取域名；过期外链不算完成，G4 |
| H01 资产/服务/风险关联及历史稳定性 | E10可见资产/服务id、风险项id及内嵌vuln.id、product_id、hostname与assets/assets_type/target，含义和粒度不同；旧Run/Observation仍只是本地历史 | 关联候选字段已知，跨批次稳定性与关系更正**待核实** | 旧历史保留 → 新来源关系/版本独立固定 | 不把业务产品ID、地址/域名、快照行键统一成实体身份；关系变化不改旧引用，G2 |

## 更新、权限和完整性合同覆盖

| ID / 语义 | 已知 / 未知 | 结果 | 保存/页面与验收要求 |
|---|---|---|---|
| S01 全量/增量与删除 | E10支持页码列表、多类创建/发现时间过滤；目标读取面未声明可靠增量游标/删除事件/一致性快照合同 | **待核实** | 日期过滤不等于更新水位；有界全量只是待批准策略，未返回不自动删除/关闭。G2 |
| S02 分页期间变化/排序/ID重用 | E10部分sort说明默认-id，但未承诺跨页快照/ID重用；E9消费者重复策略不同，单次#240不证明长期合同 | **待核实** | 不把排序参数当一致性承诺或把旧重复策略当供应商规则；分域发布/补读与稳定身份须G2 |
| S03 鉴权/范围/撤销 | E12三GET已授权，执行前后临时包/描述符/配置/凭据Hash/精确实例与方法/Token绑定指纹一致；删除最后Token后旧Token和匿名RPC均503，非预期401/403，拒绝层未定位；禁用Capset后404，源守卫关闭后未增加源请求 | **待核实**：受限实读完成，认证撤销检查未验证通过，产品成员/生产权限未测 | 不把503当匿名授权成功，也不把删Token当已验证认证拒绝；保留非空Token、指纹和来源门禁。不是生产越权结论，G3/G4 |
| S04 失败/空集/部分数据 | E7错误/空集为历史合成PASS；E12漏洞列表真实空集HTTP/业务200，包裹有效；没有制造源401/403/429/5xx、分页失败或断连 | **待核实**：真实空集子项PASS，不升级错误/恢复合同 | 合成和成功样本均不证明数据库发布、重启恢复或最近完整版本保留；本地撤销检查与源HTTP错误分别记账，G2/G3 |
| S05 规模/频率/限制 | E12预算≤8次、页size≤5、串行/有时限，实际7次；源IP valid total 13,182、端口total 3,092、漏洞total 0，仅对应本次过滤/默认语义；未全量枚举 | **待核实**：当前有界计数可见，许可速率/更新目标不明 | 不把total当全域规模或许可预算，不自动用掉第8次；扩域、周期、完整页数及附件限制仍需G3/G4 |
| S06 数据保留/来源撤销后处置 | 原材料私有、无客户出域已有约束；新增风险/附件保留期限与删除约定**未知** | **待核实** | 区分停同步、撤访问和受控保留；不无限保存/不绕撤权。G4 |

## 最小材料缺口

以下缺口保留但区分当前资产先行与后置风险/完整覆盖；已有v1.2、固定CLI资料、当前空间资产样本不重复索取。本地资产测试可保留真实值；Git/Issue/模型及审阅材料仍只记录字段/聚合证据。E12环境已销毁，本次修订不新增读取。

- **G1—字段差额与后置覆盖**：IP/端口首片字段已按E10/E12收敛，IP bu按实见object消费；其他资产类型按已定位schema保留详情/实读差额。非空风险—依据链后置01C，不再是当前字段整理或修订后01B的前置；风险项不因后置改为PASS/不适用，不扫描造数据。
- **G2—身份与同步语义**：长期ID/重用、上游快照/删除/增量仍未确认。01B只做域版本内身份及固定请求范围遍历，重复/总数漂移即失败、不发布；不跨版本继承/合并，不宣称一致性快照。跨批次实体更新仍受ADR-0021限制，后续须补证。
- **G3—新执行与本地保留许可**：当前空间与本地真实值使用方向已确认；E12一次性预算已结束。01B新增实读须固定两类方法/过滤、页数/记录/字节/时长预算及保留截止/清理方式；真实执行和业务实施仍分别授权。空Token/指纹漂移必须在产品执行入口拒绝，不依赖临时守卫或把503当认证通过。
- **G4—安全不随风险后置取消**：资产本地权限、脱离上游阅读、撤访问和有界保留在01B落实；风险正文/附件的目标网络、类型/大小/有效期、敏感字段及保留策略在01C接入前补齐。无需当前先提供非空风险脱敏包，也不能用后置放开原始材料出域。

Laya仓库/版本/许可、cumora部署网络分别到03/04补，不作为01A材料门槛。收到资料后的真实“接口缺失/权限缺失/明确不适用”须逐项记录依据；必需缺项未解决，不宣布完整同步，也不自行改变约定范围。
