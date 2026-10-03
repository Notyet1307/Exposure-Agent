# 云图 18 类结构化只读接入合同

日期：2026-10-03。状态：**维护者已批准规格、文档分支推送、文档 PR、专属 Issue 与后续本地实现；发布回执记录实际 SHA 和 Issue。** 文件名保留 candidate 以维持既有链接，但本版消费规则已获批准。

正式行为落点为 [RESULT-STRUCTURED 子合同](../specs/exposure-focus-release-1.md#result-structured18类结构化数据接入)；本稿作为对应方法、字段消费和预算的规范性附录。现有 18 类分类范围不包含风险／漏洞读取。

用户已明确要求接入侧栏其他类型，并选择“覆盖全部类型，先同步有效／监控中的记录”。现有页面缺陷按 #272 修正；新增类型不能借用 #279 的 NetFlow 实施范围。可以复用用户已经提供的连接配置，但本次已明确新增类别目标、字段消费、过滤、预算和私有保留范围；首次新增调用仍需满足 R3 的精确能力／字段准入，按 R4 发布规格并建立专属 Issue，不由本文件自动部署新能力或改写旧授权。

## 已确认范围与待定项

- 目录目标为 5 类资产、6 类暴露面、7 类只读发现种子，共 18 类。
- 现有 IP、端口服务、主域名、DNS 合同和历史版本不变；其余 14 类新增独立本地记录、版本、列表、详情和明确字段检索。
- 新增有 `status` 的资产／暴露面类型固定 `status=valid`；新增种子固定源过滤 `enable=true`。该字段不代表 Exposure 的同步开关、监控授权或本地任务状态。开放端口没有 status，读取明确空间的原列表范围，不伪造有效状态。
- 只读发现种子不计入发现资产数量，不执行监控、搜索、扫描、纳管、增删改或外部写回。
- 不增加模型、风险接入、第二调度器、通用规则 DSL、跨批次实体合并或新的 NetFlow 关联输入类型。
- **2026-10-03 用户已选择：先接入全部结构化数据。** 网站截图／图标只保存已声明的链接和 Hash 字段，不下载文件；爬虫 `headers/data` 及任何请求头、响应头、请求／响应正文不落库、不在页面呈现、不进入日志或诊断样本。爬虫其余 12 个声明字段在本片范围。既有端口 `banner` 的已批准合同保留。材料差额保留在父级 RESULT，不据此宣称父级全部验收完成。

## 事实源

1. 当前代码基线 `f246b361d92fa298a1f9ac35b7a11db085b69c2c`。
2. 已批准 RESULT / UI-A 固定文档提交 `8b3b8c2f879e1b739060db1bd748ce4474bbc77a`：
   - `docs/specs/exposure-focus-release-1.md` R0–R4、ACRESULT-1–10；
   - `docs/adr/0021-independent-cloudatlas-local-read-model.md`；
   - `docs/plans/exposure-focus-cloudatlas-coverage-20260923.md`，继续作为唯一字段事实矩阵。
3. 官方 `chaitin/chaitin-cli@v2606.0.4`，源码提交 `857ae38973b9c7886fc088a4065e3694202b7982` 的 [OpenAPI](https://github.com/chaitin/chaitin-cli/blob/857ae38973b9c7886fc088a4065e3694202b7982/products/cloudatlas/spec/openapi.yaml)。文件 SHA-256：`4bce5d8165f7ddfd992558d4d74b707f806881f0ed951a76c65a9cbcc8e1f5bd`。

公开 schema 证明接口声明，不证明当前客户空间的字段形状、非空材料或全量验收。新字段事实只能追加到原矩阵；下表是拟固定的消费规则，不建立第二份字段权威。

## 新增类型、方法与范围

全部路径均位于经配置固定的 HTTPS 来源 `/openapi` 下，仅允许表内 GET。每次显式传入被批准的十进制空间 ID、`page`、`size`、`sort=-id`，不允许调用方提供任意 URL、方法或查询表达式。

| 类型 | GET 路径 | 固定过滤 | 必须明确的特殊规则 |
|---|---|---|---|
| 子域名情报 | `/v1/asset/subdomain` | `status=valid` | 与 DNS 独立；source_name/reason 是来源声明，不建立推测关系 |
| 证书 | `/v1/asset/cert` | `status=valid` | 保留源 trusted 与指纹；不把它解释为本地信任验证，不获取证书本体 |
| 开放端口 | `/v1/attack/openport` | 不添加不存在的 status | 与端口服务独立；IP、端口、协议分列，不宣称公网可达 |
| 网站实体 | `/v1/attack/web` | `status=valid` | URL 只读文本；entity 不作为已证实的跨域外键；bu 按 E15 固定为 id/name 对象 |
| 网站路径 | `/v1/attack/dir` | `status=valid, flat="1"` | 不启用有声明冲突的日期过滤；ip_info 的缺失子项保留；附件另见下节 |
| 网站指纹 | `/v1/attack/appfinger` | `status=valid` | 产品 UUID、CPE 与网站记录身份分开；bu 按 E15 固定为 id/name 对象 |
| 爬虫数据 | `/v1/attack/crawler` | `status=valid` | id 为最低记录身份要求；其余缺失字段不补造；headers/data 单独决策 |
| 企业主体种子 | `/v1/seed/enterprise` | `enable=true` | equity/investment_path/is_history 为源声明；不推导公司控制关系或资产归属 |
| 关键词种子 | `/v1/seed/keyword` | `enable=true` | name/type/confidence 是发现输入，不执行发现任务 |
| 域名 WHOIS 种子 | `/v1/seed/domain` | `enable=true` | 不与主域名 WHOIS 属性混为一类，不主动查询 WHOIS |
| 邮箱域名种子 | `/v1/seed/email-domain` | `enable=true` | 不解析邮箱、不发送邮件 |
| 证书信息种子 | `/v1/seed/cert` | `enable=true` | O/OU 等发现输入不冒充已发现证书 |
| 网站图标种子 | `/v1/seed/icon` | `enable=true` | 图标 URL、MD5、MMH3 可 null；不把链接等同于本地图标文件 |
| 网站标题种子 | `/v1/seed/web-title` | `enable=true` | full/like 为源匹配类型，不运行搜索或监控 |

首轮不开放 7 个种子的单条 GET `/{pk}`：公开列表已声明目标字段，本地详情由固定版本内已校验的列表记录生成，不声称调用过供应商单条详情接口。若现场 UI 有列表外信息，先记录差额及官方获取方式。

### 本地检索

检索只作用于所选本地固定版本。文本为大小写不敏感的字面子串，列出的同类字段之间取 OR；`%`、`_` 和反斜线不是通配符。IP 与指纹值使用下表明确的精确匹配，不引入任意 query/DSL、实时上游回查或 headers/data 检索。

| 类型 | 字段及匹配 |
|---|---|
| 子域名情报 | `subdomain` 文本 |
| 证书 | `cn_name` 文本；另有 `sha256` 原值精确匹配 |
| 开放端口 | 规范化 `ip` 精确匹配 |
| 网站实体 | `url / hostname` 文本 |
| 网站路径 | `url / path / title / render_title` 文本 |
| 网站指纹 | `url / product_name / vendor / version / cpe` 文本 |
| 爬虫 | `target / hostname / uri / path` 文本 |
| 有 name 的六类种子 | `name` 文本；`enable / confidence / type` 只作已有字段源原值过滤 |
| 图标种子 | `md5_value / mmh3_value` 原值精确匹配 |

有 status 的类型只过滤所选版本内的源原值；没有该字段的开放端口不显示假状态控件。不从当前 valid 版本反查 ignored/invalid，也不把筛选结果数当来源总量。

## 身份、字段与错误合同

1. 记录身份固定为项目、来源、空间、能力合同、域、版本及源 ID。源整数 ID 无损转为十进制字符串；不经 JavaScript 浮点数舍入。源 ID 只表示版本内身份，不承诺跨批次稳定性。`space` 在 openport/dir/seed 的公开声明为 integer，在其他新增类型为 string；本地始终固定十进制字符串，并原字面值编码为 HTTP query，禁止经 JavaScript Number 转换。即使来源把 space 标为可选，Exposure 也必须显式传入被批准的空间。
2. 有明确 required/nullable 的字段，按上述固定 schema 校验；本片排除的 crawler headers/data 在边界适配后即丢弃，不形成未知字段错误。crawler 和关键词／域名 WHOIS／邮箱域名／证书信息／图标／网站标题六种 seed 列表未声明 required：要求 id 必填以支撑分页去重，其余缺失保持 missing；字段存在时仍须符合声明类型。enterprise 列表有 required，不纳入这条例外。未经明确 nullable 的 null 不自动接受。以上是本地消费者规则，不是来源对字段必填的承诺。
3. 空字符串、空数组、null、missing、false、0 分别保存和展示。不得通过默认值、删坏行、字符串／对象任意联合或整包响应落库掩盖合同错误。
4. 未知额外字段仅保留脱敏数量／结构差额，不保存未知值或未知字段名。每个新版本累积 `omitted_field_count`（未知字段出现次数，不是去重字段数）；旧版本未采集时为 null。页面同时显示字段覆盖限制，不把分页完整当所有源字段都已保存。类型冲突停止未封存版本，只输出固定脱敏错误码、已批准字段名／类型类别及差额数量，不能将真实值写入 Git、Issue、模型或普通日志。
5. `web/dir/appfinger` 的 bu 按 E15 单页类型诊断修正为必填对象，恰消费 `id`（源 integer 无损转十进制字符串）和 `name`（string），二者必填；不接受 string/object 联合或用空字符串回退。诊断各 20 条均呈该结构，未知子字段仍只计数。该结构与对应合成 fixture 一起固定后，才允许业务版本发布；任何后续形状漂移停止对应域。
6. 时间保留源原文及未知时区标记，不自行换算、不增加日期范围查询。链接作为转义文本展示，不自动访问客户网站、不执行 HTML、脚本或实时 DNS。
7. 精确空值例外：dir 的 `icon_md5_hash / icon_mmh3_hash / icon_url / screenshot_link` 可 null；E15 明确增加 `render_title / server / x_powered_by` 三个 string-or-null 字段（均仍必填），各在 20 条样本中实见 1 个 null，其他字符串不得类推放宽；icon seed 的 `icon_url / md5_value / mmh3_value` 可 null。dir 的 ip_info 子项没有 required 声明，缺项保持 missing。cert 的 sources 子项必须有 source/reason/factor；web/dir/appfinger 的 tags 子项必须有 pk/name；dir 的 apps 子项必须有 product_uuid/vendor_uuid/product_name/vendor_name/cpe/version/created_at/updated_at/lastseen_at。其他嵌套类型仍按同版矩阵与固定 schema，不以此清单放宽字段类型。
8. 同版矩阵中的响应包裹规则同样必须校验：`code / message / data.current / data.size / data.total / data.items`，不能只验证单条字段。版本身份还必须固定实际 `status / enable / flat / sort`、读取范围和预算；请求总量与记录身份不得因缺省参数而漂移。

## 能力身份和调用边界

- 每个新增类型使用一个静态能力档案和一个白名单列表方法；来源实例固定类型、HTTPS 地址、空间及配置指纹。对应 Capset 设 `include_all_methods=false`，不选择写方法、单条详情或其他域。
- 新包和 descriptor 在实现时按固定工具链构建，验收前必须将准确 Hash 写入受版本控制的 pin manifest；配置、上游 Secret 和 Capset token 绑定进入规范化指纹，不把秘密明文放进应用数据库或日志。当前尚未生成这些新包，所以没有可用于真实调用的已批准 Hash，不以通配 Hash 或旧四域包代替。
- 来源验证核对包、descriptor、实例、配置、方法集合和 token 绑定。发生漂移必须重新验证，不能悄悄扩大既有能力。
- 仅 HTTPS 且验证证书链和主机名；不跟随重定向，不访问链接字段中的目标。401 归认证失败、403 归授权失败；其他非 200、重定向、异常压缩、坏 JSON/字段归相应固定来源错误；字节超限与 DNS/TLS/连接/总时长超时明确失败。所有错误沿现有脱敏边界，不保存上游错误正文，不自动重试，异常后停止该任务后续来源调用。

## 分页、发布与保留合同

- 预算硬边界明确为：page_size 1–200、max_pages 1–10000、max_records 1–1000000、max_response_bytes 1–16777216、timeout_seconds 1–300。retain_until 必须是未来的绝对时间。没有无限循环、自动续拉、定时同步或自动重试。
- 每个新增档案只同步其单个域，从第 1 页串行读取；容量为 `min(max_pages, floor(max_records / page_size))`，至少一页。复用已有 ROOT/DNS 单域规则，不引入新的多域配额分配，也不改旧 IP／端口双域合同。
- 新域首次诊断固定为每类最多一次、`page_size=20, max_pages=1, max_records=20, max_response_bytes=4194304, timeout_seconds=120`，串行执行。只输出包裹有效性、已批准字段的存在／类型／nullable 计数、未知字段数量、total 与内容 Hash；不保存原始响应或记录取值，不把未批准字段名输出。诊断不发布业务版本；不得为诊断扩大旧 Capset。
- 待精确类型合同、固定包 Hash、来源验证和隔离验收通过，每个新增类型新建一次业务同步：`page_size=200, max_pages=160, max_records=32000, max_response_bytes=4194304, timeout_seconds=300`。最多 14 个新域诊断和 14 个业务同步，不自动续拉／重试；若源 total 超过预算、期间漂移或未读完，保持明确部分／失败状态，另报完整读取所需差额。
- 首轮真实接入只使用维护者已经配置的 HTTPS 来源及空间 2536，精确域过滤见方法表；数据仍保留至 `2026-10-10T01:53:00Z`（北京时间 10 月 10 日 09:53），不延长旧数据。到期按既有独立读模型清理方法只处理对应来源及到期版本；本片不新增自动清理任务，实际删除仍由操作者显式执行。
- 只有累计记录量等于一致的源 total、没有重复源 ID、页面和字段均完整时才发布 complete=true。正常达到预算可发布显式部分版本；任何异常立即停止后续来源调用，未封存内容不可读。
- 状态区分完整成功、正常部分完成、部分失败、失败、未知。未知只核对原 Session，不创建替代执行。失败不得覆盖或清空最近仍可读的旧版本。
- 版本与来源过滤范围固定；各域独立时间，不冒称整个云图的一致性快照。最新部分版本与最近完整版本分别保留。
- 复用已有成员、角色、归档、来源 data_access、到期与清理规则。旧版本不延长、不恢复；清理只能覆盖对应新读模型，不影响旧 Run、报告、Artifact 或其他来源。

## 本轮明确排除的材料

用户选择先交付结构化数据，因此不下载截图／图标，不保存爬虫 headers/data、请求／响应头和正文。URL、图标指纹和页面正文 Hash 作为已声明结构字段可保存并以纯文本显示；它们不等于文件或正文已经取得。页面不自动加载这些外部 URL。

公开资料尚未定位网页哈希种子的读取方法，也未给企业种子返回 level/status 字段。它们保留为待定位差额；不猜 endpoint，不用网站路径的 body_md5_hash 或图标 Hash 替代另一类记录。父级 ACRESULT-2/5/6 中的额外信息和材料验收不因本片完成而升级为 PASS。

## 实施顺序

1. 复用已经完成的页面修正和无损文本存储，不重复开发；新候选包含后端 `301d743` 与前端 `a72459d` 的已验证改动。
2. 接好已有 ROOT/DNS 的独立只读配置，仍由操作者显式给定同步预算与保留期限。IP／端口完整读取也新建固定批次，不覆盖这次小批量证据。
3. 将本稿收敛为正式 Spec 子合同，并更新同版 ADR-0021/0022 与原字段矩阵；查重后创建专属 Issue，引用固定提交。#272/#279 不承载新增 14 类的隐式扩权。
4. 在独立工作树实现已满足合同的类型：复用 PostgreSQL、OctoBus、现有 agent-compose worker 和版本发布路径；静态显式方法／字段映射，不引入通用规则平台。Schema 仅新增迁移，API 变化由原生成命令更新客户端。
5. 每类使用正式前后端和隔离合成来源验证，再按获准空间、方法、预算和保留窗口进行真实只读验收。原始客户明细留在本地授权边界，只回报聚合、类型诊断和 Hash。

## 验收清单

- 18 类各自列表、主要字段、详情、检索和服务端分页；种子单独分组、不计入资产总数。
- 空值／缺失／超大整数／长文本和恶意字符串保持原义且安全显示；未知字段不静默宽松接纳。
- 完整、部分、失败、未知、无数据、未配置、未同步、到期、撤权分别可辨；计数属于明确来源和固定版本，不受当前页或筛选误导。
- 刷新、切屏、切类别、版本、账号和项目不丢未提交输入、不串数据；撤权及到期仍立即拒读。
- 部分页、total 漂移、重复 ID、第 N 页失败、超预算、会话未知的发布／恢复均有可执行检查。
- 浏览、搜索、详情和分类切换不发起上游读取、模型调用或写操作。
- 独立 Standards、固定 Spec 审阅、合成业务验收、当前部署验收、真实逐类型验收分别记账。未实现附件或敏感材料时，不将整个 RESULT 标为完成。
- 网页哈希的读取方法仍未定位；企业来源 UI 的层级／状态与公开返回字段之间仍有差额。18 类列表路径齐全不能替代这些差额，也不能直接把父级 ACRESULT-2 判为完整。

## 当前停止线

本合同已批准，但不能被当作“14 类已接入”。本轮已获准推送文档分支、创建文档 PR、建立实际 Issue 后继续本地实现。文档 PR merge、业务代码 push/PR/merge、进一步迁移／部署和 Issue 关闭仍单独验收，不能由文档发布推导。

## 已解决的共享存储前置

原有 IP／端口曾因 JSONB 无法保存 NUL 而失败。后端 `301d7433a5846e707bc48ec0e019eab8d518b23c` 已用 JSON 原文及严格校验的检索投影修复，并新增前向迁移；相关 110 项回归通过。维护者另行批准备份、真实库迁移及一次同步后，IP 13,182 条／端口 3,092 条完整发布，231 条端口记录含 NUL，API 原文读回通过，旧 800 条及历史批次哈希一致。

这些聚合结果仅证明既有 IP／端口链路，不能代替新增 14 类验收。共享迁移已部署，不删除或改写；新增 Schema 变化必须使用后续迁移。导入真实 NUL 后不能无损直接降回旧 JSONB 结构。
