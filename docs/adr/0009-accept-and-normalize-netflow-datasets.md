# ADR-0009：完整接受并规范化 NetFlowDataset

状态：提议

日期：2026-09-04

## 研究依据与背景

ADR-0008 已决定由 Project 保存当前可选 NetFlowDataset 选择，并由 GovernanceRun 固定 Dataset 身份、原始内容 Hash 和 Dataset 合同版本。本提议只为 #165 给出 Dataset 成立时点、原始与规范化 Artifact、质量失败、保留删除和生产获取的候选合同，不代表该合同已被接受，也不授权任何 R1 实现。

仓库外用户提供的《NetFlow上报数据字段说明(1).doc》本机 SHA-256 是 `b6be54f9dfd7a1e739bd32c3d6c054bd62268839b4801650e5efa8876d756189`。该材料只证明部分来源字段语义：`IN_BYTES` / `IN_PKTS` 已乘采样比，`OUT_BYTES` / `OUT_PKTS` 当前为零，`start_time` / `end_time` 使用固定东八区的 `YYYY-MM-DD HH:MM:SS`；`FLOW_SAMPLER_ID` 在提供 `-r` 时表示采样器 ID，未提供时可回填 exporter 地址。本提议只把这些事实作为推断限制，所有未证明的协议编号全集、实际采样率、采集点、覆盖完整性、空值、重复、迟到数据和生产获取语义均保持 `UNKNOWN`；不引用敏感样例。

## Dataset 成立与 Artifact

本提议中的一次 NetFlow upload attempt 是瞬时传输，不是持久领域对象。候选合同要求服务先把输入流入隔离临时文件并执行完整确定性扫描；只有扫描和规范化完成后，才逻辑上一次性建立 NetFlowDataset、原始 raw Artifact、规范化 normalized Artifact 和脱敏 AuditEvent。数据库事务失败时补偿已提升文件；事务未提交的临时或孤立字节不构成 Artifact。拒绝或处理失败的 attempt 不建立 Dataset、Artifact 或 accepted AuditEvent，也不新增 upload-attempt 表。

候选 Dataset 不能只通过结构预检成立。结构预检会把全量不可用、编码歧义或行质量未知的对象暴露给 Project current selection，并把重复解析和合同漂移推迟到每次 Run。完整扫描在接受时一次固定原始记录数、activity-valid 记录数、隔离记录数、warning、可解析时间范围、raw Hash、normalized Hash、Schema fingerprint 和 Dataset 合同版本；同一 Dataset 的 normalized Artifact 只生成一次，Run 不重新解释 raw 字节。

候选 normalized v1 使用 Python 标准库即可生成的 canonical UTF-8 CSV，不引入 Polars、Arrow 或 Parquet。它只输出 activity-valid 行，并按原始 CSV logical data record 顺序保留重复；源记录键是 `row:<从 1 开始的 CSV logical data record 序号>`，不按物理换行计数。精确 header 和列序是：

```text
source_record_key,src_ip,dst_ip,protocol,src_port,dst_port,start_time_utc,end_time_utc,in_bytes_estimated,in_packets_estimated,tcp_flags
```

`src_ip` 和 `dst_ip` 使用现有 Canonical IP 与 ADR-0005。所有源整数 token 必须逐字匹配 ASCII `0|[1-9][0-9]*`，不得 trim，且不接受空白、符号或前导零，再应用字段范围；protocol 是 `0..255`，port 是 `1..65535`，count 是 `0..18446744073709551615`，flag 是 `0..255`。optional 空 token 或非法、溢出 token 规范化为 null 并 warning；protocol 空或非法则整行隔离。有效整数使用 `str(int)` 的最短无符号十进制表示。`IN_BYTES` / `IN_PKTS` 不做再次采样乘法。有效时间固定写成 `YYYY-MM-DDTHH:MM:SSZ`，无效时间为 null。null 是两个逗号之间零字节的空字段；固定的 11 列不允许把空字符串解释为业务文本。

字节合同是 UTF-8 无 BOM，每一行包括 header 都以 LF 结束，并使用 `csv.writer(delimiter=",", quotechar='"', doublequote=True, escapechar=None, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)`。normalized 值禁止包含 CR、LF 或 NUL。Schema fingerprint 是上述精确 header 行加一个 LF 后的 SHA-256 lowercase hex，即 `e445a0e962a050f2b7b24589ce19fe6267953952addcc7dbdc7376e9579258f9`；normalized Hash 是完整 canonical bytes 的 SHA-256 lowercase hex。

normalized Artifact 的物理字节可由 raw Artifact 和固定合同重建，是内部处理表示，不是第二事实库；同一 Dataset 只生成一次，Run 不重新解释 raw 字节。已经固定的 Artifact 不得原地重建或覆盖，重解释必须形成新合同版本和新 Dataset。

## 有界 envelope

候选 v1 只接受扩展名大小写不敏感的 `.csv` 或 `.txt`，内容必须是首行为表头的逗号分隔 CSV，并允许 LF 或 CRLF。输入文本流以 `newline=""` 交给 `csv.reader(delimiter=",", quotechar='"', doublequote=True, escapechar=None, skipinitialspace=False, strict=True, quoting=csv.QUOTE_MINIMAL)`；每个 CSV logical data record 的字段数必须与 header 字段数完全相同。扩展名不替代内容检查。不接受 XLSX、压缩包、压缩流、分隔符 sniffing 或其他导入格式；任意 NUL 拒绝整批。

编码只按 `utf-8-sig`、`gb18030` 的顺序严格解码；不得使用 replacement decoding、系统默认编码或统计探测。首个严格成功的编码被固定为 Dataset 接受元数据。同一输入不得因部署环境不同而采用不同解码结果。

header token 大小写敏感且不得 trim；每个 token 必须非空且唯一。下列 required header 必须逐字存在：

- `IP_SRC_ADDR`
- `IP_DST_ADDR`
- `PROTOCOL`
- `L4_SRC_PORT`
- `L4_DST_PORT`

`start_time`、`end_time`、`IN_BYTES`、`IN_PKTS` 和 `TCP_FLAGS` 是候选 v1 逐字识别的 optional header。其他输入列只保留在 raw Artifact 中、不进入 normalized Artifact，并产生一个有界的 Dataset warning；它们不自动扩展 normalized Schema。任意重复 header 拒绝整批，避免同名列优先级成为隐式合同。

NetFlow 必须有部署级原始字节硬上限，以便传输和完整扫描 fail fast；它不是 Project 策略。CustomerUpload 的 20 MiB 是 XLSX 输入防护，不能外推为 NetFlow 上限。R1 必须在目标部署硬件上以最坏允许样本 benchmark 后固定必需配置及部署默认值；运行时未配置、非整数或越界必须 fail startup，不得使用静默 fallback。本 ADR 不凭空规定绝对字节值。

## 批级拒绝与行级质量

只有批级信任边界失败才拒绝整批且不建立 Dataset：未授权或跨 Project 操作、传输不完整、部署硬上限超限、内容类型不受支持、严格解码失败、NUL、不可恢复的 CSV quoting/列结构、空白或重复表头、必填表头缺失，以及接受期间原始内容 Hash 改变。输入导致的拒绝返回稳定脱敏数据错误；接受期间的文件存储、Artifact 提升、依赖或数据库事务失败只返回稳定 processing error。两类失败都不建立 Dataset，且此处不是 GovernanceRun 状态分类；错误不得回显原始值、文件路径或 parser 异常。

单行坏字段不拒绝整批。每个 CSV logical data record 都有稳定 source record key。所有质量 warning 统一保存 `code`、`field`（适用时使用逐字源字段名，否则为 null）、`count`，以及按原 logical record 顺序最多 20 个 `source_record_key`；不保存 raw 值。warning 按 `(code, field)` 聚合，`count` 是命中的 logical record 数；唯一例外是 `netflow_ignored_input_columns`，其 `field = null`、`count` 是被忽略的 header 数且 source record key 列表为空。候选 v1 实际使用的最小稳定 code 是：`netflow_invalid_ip`、`netflow_invalid_protocol`、`netflow_unknown_protocol`、`netflow_invalid_port`、`netflow_invalid_time`、`netflow_invalid_time_range`、`netflow_invalid_count`、`netflow_invalid_tcp_flags`、`netflow_ignored_input_columns`、`netflow_duplicate_records`。

一条 activity-valid 记录必须同时具有两个可按现有 Canonical IP 合同规范化的 IP，以及符合上述严格整数词法和 `0..255` 范围的 protocol。任一条件失败时整行隔离并计数，不产生 normalized 行。候选 v1 只把 `1`（ICMP）、`6`（TCP）、`17`（UDP）和 `58`（ICMPv6）列为已识别 protocol；其他数值合法的 protocol 保留原数值，两个 port 置 null 并记录 `netflow_unknown_protocol`，该行只可支持 IP 正向活动事实。

protocol 为 TCP `6` 或 UDP `17` 时，缺失、不符合严格整数词法或不在 `1..65535` 的源端口或目的端口置 null 并记录 `netflow_invalid_port`，但该 activity-valid 行仍保留用于 IP 正向活动；任一端口为 null 时不得执行依赖完整端口的服务推断。非 TCP/UDP protocol 的两个 port 一律置 null，且不得把 ICMP 行中的 `0`、`2048` 或其他来源占位值当成端口错误或服务事实。

时间只接受无时区后缀的 `YYYY-MM-DD HH:MM:SS`，按 stdlib 固定 UTC+08:00 offset 解释并规范化为 UTC；不使用 `Asia/Shanghai` 或系统 tzdb。单端缺失或不可解析时只将该端置 null 并记录 `netflow_invalid_time`；两端都成功解析但 `end < start` 时两端都置 null 并记录 `netflow_invalid_time_range`。activity-valid 行继续保留，但无效时间不得参与依赖有效时间的判断。Dataset 的可解析时间范围只是有效行的最小开始与最大结束，不是覆盖声明。optional count 空、非法或超出无符号 64 位范围时置 null 并记录 `netflow_invalid_count`；TCP flags 空、非法或超出 `0..255` 时置 null 并记录 `netflow_invalid_tcp_flags`。

不设置任意失败率阈值，不引入质量规则 DSL。精确重复按 activity-valid normalized 行除 `source_record_key` 外的 10 个 canonical 字段全部相等分组，且不去重。质量事实保存 `duplicate_group_count` 和 `duplicate_record_count = sum(group_size - 1)`；`netflow_duplicate_records` 的样本是每组首条之后的 duplicate source record key 合并后按原 logical record 顺序取前 20 个。

## 零记录、选择与 Run 失败

表头合法但没有原始数据记录，或完整扫描后没有 activity-valid 记录，仍可建立零记录 Dataset，以保留 ADR-0008 已接受的“Dataset present 且零记录”与 explicit absent 的区别。v1 将这类 Dataset 标为不可选择，Project current selection 必须拒绝它。若它因防御性校验、历史错误或竞态仍被固定并执行，Run 必须建立 `record_count = 0` 的 NETFLOW SourceSnapshot 后进入 `FAILED_DATA`，不得发布伪造的“未观测”事实。

本段只收窄固定 NetFlow 输入的失败分类，不改变 CloudAtlas 或既有来源的分类。固定 NetFlow 输入只要无法读取或无法证明完整性——包括 raw 或 normalized Artifact missing、open/read/stat 失败，tenant/Project scope、内容 Hash、字节大小、Schema fingerprint、合同不匹配或不可变绑定漂移——一律 fail closed 为 `FAILED_DATA`；不得从同一个 `OSError` 猜测是否为瞬时存储故障。只有全部输入完整性已经证明后，Runner 的数据库持久化失败或实现异常才是 `FAILED_PROCESSING`。Retry 和 Rerun 继续遵守 ADR-0008 的固定输入规则。

Dataset warning 是否令成功 Run 最终成为 `COMPLETED_WITH_WARNINGS` 不由本 ADR 决定；#166 决定 Publish 状态。这里只规定只有有效字段可以形成正向证据：覆盖完整性固定为 `UNKNOWN`，sampling rate 与 observation point 固定为 null，直到来源提供可验证合同；不得据此形成 `NOT_OBSERVED`、零事件或零风险结论。时间、采样或其他质量不足只产生确定性质量事实，后续能力是否可评估及其持久方式留给 #166 和各自获准的能力决策；本 ADR 不决定也不拒绝通用 Capability 表。

研究材料表明 `IN_BYTES` / `IN_PKTS` 是乘采样比后的来源估算值，因此候选 normalized v1 只纳入 `in_bytes_estimated` / `in_packets_estimated`，不得再次乘采样率。`OUT_BYTES` / `OUT_PKTS` 当前为零，仅构成禁止生成双向流量指标的推断限制，不进入 normalized v1。`FLOW_SAMPLER_ID` 可能是采样器 ID，也可能在未提供 `-r` 时回填 exporter 地址；只能断言它不是 sampling ratio，不能把它当作稳定 sampling identity，也不进入 normalized v1。协议全集、采样率、舍入与聚合、覆盖、采集点、NAT、迟到数据等未给出的生产语义继续保持 `UNKNOWN`。

## Scope、幂等、删除与备份

NetFlowDataset、raw Artifact 和 normalized Artifact 都必须以复合 tenant + Project 约束绑定；读取、选择、删除、reservation、Run 和 Snapshot 不得只凭全局 UUID。接受幂等身份是同一 tenant 内的 `(project_id, raw_sha256, dataset_contract_version)`；相同内容和合同返回原 Dataset，不产生第二组 Artifact 或 accepted AuditEvent。Hash 相同也不得跨 Project 复用，以免泄露存在性或扩大授权面。显示文件名不参与身份；合同版本变化形成新 Dataset。

不设置 TTL 或自动清理。只允许 Admin 删除既不是 Project current selection，也未被 launch reservation、GovernanceRun、SourceSnapshot 或其他治理事实引用的 Dataset；删除 raw 与 normalized Artifact 时复用现有文件隔离、数据库补偿和脱敏审计模式，所有引用 fail closed。R1 实现任务是否包含删除接口由后续 Delivery Spec 收口，本 ADR 只固定允许删除的治理边界。

NetFlow Artifact 使用现有 Artifact 路径，不引入新存储。它与 PostgreSQL、OctoBus 和 agent-compose 一起进入现有四存储协调备份/恢复边界。在线删除只影响当前在线状态，不承诺擦除已有备份；备份保留、加密、到期销毁和恢复集一致性仍由客户部署方负责。

## 权威关系与外部获取

raw Artifact 是不可变原始字节证据；normalized Artifact 是确定性派生的内部表示；二者都不是权威结构化业务事实库。PostgreSQL 是 Dataset 元数据、选择、质量事实、Run 固定事实、Snapshot 和已发布聚合的唯一权威结构化业务事实库。客户可见聚合只能由 Run Publish 原子提交。Artifact 缺失或 Hash 不符时必须 fail closed，不能静默覆盖、就地修复或从另一份副本重写历史身份。

R1 人工上传是过渡输入，不冒充 SourceInstance。生产环境自动获取 NetFlow 只能通过另行接受的新只读 OctoBus 合同；在认证、分页、时间窗、完整性、采样、迟到数据、采集点和 NAT 语义明确前，不定义 OctoBus 方法，不创建未来 Adapter，也不允许 backend 或 Runner 直接持有客户外部系统能力。

## 明确不做

本提议不引入通用导入器、规则 DSL、消息队列、实时或流式采集、跨 Project Artifact 去重、未来 SourceInstance Adapter、未获准的外部读取方法或为未来能力预留的抽象。

ADR-0009 只记录 #165 的候选 NetFlowDataset、Artifact 与质量失败边界。它不代表决定已被接受，不授权 R1，也不决定 report、Publish 状态或 Capability 持久模型；这些能力仍须由各自后续 Issue、独立 Admission 和 Delivery Spec 决定。
