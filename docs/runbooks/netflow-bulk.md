# NetFlow bulk V1：接入、验证、配置与回退

范围：独立 bulk worker、冻结多文件 CSV/TXT、Parquet、DuckDB 与 PostgreSQL 投影。旧上传入口仍限 50 MiB，旧 0.4.0 wheel/足迹/结果合同不变。任务和授权见 [#304](https://github.com/Notyet1307/Exposure-Agent/issues/304)，行为见[固定 Spec](../specs/netflow-bulk-v1.md)。本文命令不代表已授权修改现有部署；本轮只使用隔离合成环境。

## 数据与口径

- 原始快照在 `NETFLOW_BULK_ROOT/<tenant>/<project>/<source>/<ready SHA>/`；目录由运维封存，API/worker 只读挂载。API 不接收任意文件路径，也不上传原始大文件。
- `input-manifest.json` 固定成员的文件名、SHA256、字节数、编码、时区和 CSV schema 版本；`normalization-plan.json` 固定输入与 normalizer/schema 身份。bulk Dataset 的兼容 `raw_sha256/normalized_sha256` 分别指这两个文件，不冒称单个原始 CSV 或所有 Parquet 的内容摘要。
- Context/Analysis 固定 tenant/project/namespace/context/policy；`netflow_bulk_members`、`netflow_bulk_shards` 逐行记录成员与分片校验、计数和完成状态。`netflow_bulk_jobs` 保存 lease/fence/heartbeat、取消与阶段。标准化分片及发布收据保留自己的 SHA256。
- Dataset 登记时尚不知道行数，公共响应返回 `counts_state=PENDING` 与空计数；完整标准化后才返回已核实的行数。旧 Dataset 行数保持原值。bulk 去重计数属于具体 Analysis/filter/policy，不写回旧 Dataset 统计。
- 必需列：`IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT`。CSV/TXT 均按逗号 CSV 解析，支持引号内换行。UTF-8 或 GB18030 由封存命令明确声明；不自动修复乱码，不支持压缩输入。
- 可选时间 `start_time/end_time` 接受 ISO 日期时间；无偏移时用 manifest 声明时区，默认 UTC。复用原先 UTC+08:00 导出时应传 `--timezone Asia/Shanghai`。歧义/不存在的当地时间、缺失/错误时间保留未知，不当作采集窗口证明。
- 去重身份列为 `EXPORTER,OBSERVATION_POINT,OBSERVATION_DOMAIN_ID,SAMPLING_MODE`；sampled 还需可解释的有效 `SAMPLING_RATE`。缺失或明确 unknown/null/N/A 等占位身份会保守加入稳定文件/逻辑记录引用，不合并。其他原始列，包括 NAT、采样、计数、flags，保留在完整键与原始字段中。
- IPv4 mapped IPv6 规范为 IPv4；整数先有界校验再转换。TCP/UDP 的数值端口 0 保留为观测值并可过滤，不表示监听。旧小文件口径仍按其原合同处理 0。地址/协议无效进入 invalid；可选字段不可解释时保留原值与未知语义。
- 先有效性、再过滤、再对整个冻结 dataset 精确去重：`raw = invalid + filtered + retained`，`retained = unique + duplicate`。unique 是唯一导出记录，**不是会话或真实事件数**；raw 原始证据不删除。跨 dataset/跨日增量去重未实现。
- Parquet 明细及高基数 peer/证据留在列式层；PostgreSQL 保存元数据、对象/地址投影和索引。样本每对象最多 20 个，完整计数、样本数、遗漏数分开。未知归属、服务角色、监听与可达性保持未知。bulk 未执行旧材料复核规则；不能拿预处理或观测计数冒称 0.4.0 全分析兼容。

## 安装和资源

在本地候选工作树：

```sh
cd /Users/yang/.codex/worktrees/netflow-bulk/Exposure-Agent/backend
uv sync --frozen
```

后端保持 Python 3.14；锁定 DuckDB 1.5.6、PyArrow 26.0.0。API 与现有 runner 使用同一锁文件和原 Dockerfile，无全后端降级。实际平台验证及差额见[验证回执](../work/netflow-bulk-validation.md)。

| 配置 | 默认 | 含义 |
|---|---:|---|
| `NETFLOW_BULK_ROOT` | 未配置 | 关闭新 bulk 接入/分析；已有结果仍可读 |
| `NETFLOW_BULK_MEMORY_MB` | 512 | DuckDB buffer manager，MB；不等于进程 RSS 硬上限 |
| `NETFLOW_BULK_THREADS` | 2 | 计算线程；本机容量验证使用 1 |
| `NETFLOW_BULK_TEMP_BYTES` | 8 GiB | DuckDB spill 配额 |
| `NETFLOW_BULK_DISK_RESERVE_BYTES` | 2 GiB | worker 必须保留的空闲盘；本机 benchmark 保留 20 GiB |
| `NETFLOW_BULK_RSS_BYTES` | 2 GiB | 总进程 RSS 检查预算，超限中断计算 |
| `NETFLOW_BULK_TIMEOUT_SECONDS` | 86400 | 总处理时间预算 |
| `NETFLOW_BULK_LEASE_SECONDS` | 120 | lease；heartbeat 每 3 秒，重型 SQL 可中断 |

API 元数据 JSON 上限 2 MiB、manifest 最多 4096 文件且 2 MiB；字段最多 65536 字符，逻辑 CSV 记录最多 256 KiB 解码后 UTF-8 字节。分片最多 65536 行且按实际展开 JSON/行开销约 16 MiB 分批，row group 最多 8192 行。合法记录不会按物理行或任意字节切片。

Linux worker 设置 `RLIMIT_AS=4×RSS预算` 和 CPU 时间上限；RSS 检查与 DuckDB 中断另行执行，不能把虚拟地址上限称 RSS 上限。DuckDB 禁网络/自动扩展，仅允许任务目录。结果 peer 查询独立限制 64 MB、1线程、256 MiB 临时盘、10秒和每 API 进程最多2条此类查询。

固定 agent-compose v2608.4.0 的 Docker agent 配置不提供 per-agent memory 字段，不能随意写入无效的 `mem_limit`。硬容器内存限制的隔离验证命令见 benchmark 回执；正式环境需按实际 runner/宿主设施设置和读回预算。

## 封存与提交

先从已经完成写入、仅合成或明确授权脱敏的目录创建独立快照。原目录不被修改；封存时流式复制/计算摘要，拒绝写入中变化、符号链接和重复文件身份，持久化目录后才发布 ready 标记。

```sh
uv run python -m app.netflow_bulk seal \
  --source /path/to/closed-csv-files \
  --root /path/to/operator-owned-snapshots \
  --tenant TENANT_UUID --project PROJECT_UUID --source-id collector-a \
  --encoding utf-8-sig --timezone Asia/Shanghai
```

命令输出 `source_id`、`ready_id` 和文件数。管理员可在原“数据接入 → NetFlow处理 → 登记服务器批次”填写两项编号。随后沿原上下文确认表单明确 namespace、采集范围和位置声明，再点击分析。源地址并不因此成为本方资产。

等价 API（token 不写入命令文件或报告）：

1. `POST /api/v1/projects/{project}/netflow-bulk/datasets`，`Idempotency-Key`，JSON `{"source_id":"collector-a","ready_id":"完整SHA256"}`。返回 dataset ID。
2. 原 `POST /netflow-datasets/{dataset}/processing-contexts` 管理员确认 Context。新 Context 不改写旧 Context/计数。
3. 原 `POST /netflow-datasets/{dataset}/analyses` 支持 bulk 默认处理。高级过滤用 `POST /netflow-bulk/datasets/{dataset}/analyses`，JSON含 `context_revision_id` 和 `bulk_filter`（`cidrs`、`protocols`、带偏移的 `start/end`）。CIDR仅过滤源侧，不证明归属；IPv4/IPv6/mapped CIDR采用合并区间与 ASOF 匹配。
4. `GET /netflow-bulk/analyses/{analysis}/progress` 查询阶段。`POST .../cancel` 请求取消，保留检查点；界面也有“取消批量处理”。失败/取消不成为当前结果。
5. 中断后先原 `POST /netflow-analyses/{analysis}/reconcile` 查询原 Session。确认终止并分类失败后，用原失败 ID 作为 `retry_of_analysis_id` 显式重试；不能把 lease 到期当作已证明旧进程死亡。

全局只准入一个未完成 bulk 任务，并原子争抢 lease。预约后的授权撤销/归档会记录失败，避免遗留预约占住容量。并发失败返回明确拒绝，不排出一批等待中的昂贵 guest。

## 查询与恢复协议

- 原观测、peer、证据 API 根据 Analysis 后端分发。bulk 的对象/地址由 PostgreSQL过滤排序分页；peer 使用有资源上限的列式查询。`next_cursor` 绑定版本身份、查询条件和唯一排序键；旧 offset URL 保持兼容，连续翻页优先 cursor。
- `GET /netflow-bulk/analyses/{analysis}/record?reference=...` 由文件摘要及逻辑行号定位一个已提交分片/row group；查证据前验证该分片 SHA256。页面可点击引用读取原逻辑记录。
- 列表只检查 PostgreSQL封存身份及文件大小/mtime/ctime，不读取或 hash 原始 CSV。inode 因挂载不同而变化，仅保留诊断值。变更会失效并拒读；管理员可 `POST .../invalidate` 明确使结果失效。原小文件完整性校验不删除。
- 标准化分片：私有临时文件 → 文件/目录 fsync → rename → checkpoint。未提交孤立文件不会参与计算。恢复已提交片会校验并比对重放数据；单个未完成大文件仍可能从头重读，不支持任意字节续读。
- 完整标准化后只封存一次目录和分片状态。重复过滤验证封存状态并复用 Parquet，避免重读 CSV，也避免以重新 hash 全部列式明细破坏列裁剪。
- 结果先分批 staging 投影，在不持 lease 行锁时完成全量文件校验和计数核对；最后短事务检查 lease/fence、权限、Context、原 Session和已验证文件状态，再原子发布。失败、取消、旧 fence 和未完成版本不可读。
- 当前结果按可信采集范围、冻结输入登记顺序及处理预约顺序稳定选择，旧输入迟完成不能覆盖新输入的成功结果；固定历史不替换。已知失效版本排除，首次发现未知完整性故障仍失败封闭。
- V2 辅证走新仓储，管理员可用原显式范围证明绑定。bulk 不走旧 V1 全量关联资格路径；需该旧资格 ID 时明确拒绝。N失败/撤销/到期不会阻断 C/A 核心。旧 ledger/旧 Run 输入明确拒绝 bulk，不误读 manifest 为 CSV。
- 完成结果不再每5秒重取明细；轻量访问资格检查仍轮询，撤销清除缓存。新增 optional policy/count-semantic 字段只序列化到 bulk 辅证，旧元数据字节结构不因空默认字段改变。

## 配置、部署与回退边界

本轮未更新既有8080/8081、生产凭据或数据。实际启用需单独授权，并先备份/恢复演练：

1. 在隔离副本执行 `uv run alembic upgrade head`，确认新增3个revision。首项将旧Dataset计数字段扩为bigint，可能锁表/重写，不能未经实测假定在线无停顿。旧行值与Artifact字节不重算。
2. 以固定代码SHA分别构建原API/runner镜像，读回镜像和 `/app/runner-build-version`；0.4.0 wheel 校验仍必须通过。
3. API 使用可选 `compose.netflow-bulk.yml` 加只读 snapshot 挂载。对已渲染、受保护的 agent 配置，使用 `uv run python scripts/render-netflow-bulk-agent.py --input ... --output 新文件 --snapshot-root 绝对目录` 生成新配置；脚本不应用、不覆盖原文件，输出0600。它只增加现有 netflow-processor 的受控挂载及预算。
4. 确认 API/worker 看到相同原始快照和Artifact根；用合成多文件实际走登记→Context→异步执行→查询→证据→撤销，并读回资源限制。配置写入不等于运行时验收。
5. 安全回退先停止新 bulk 准入、取消并确认原 Session结束，保留理解 bulk 协议的只读代码、数据库与全部证据。不要删除共享迁移、清空表或删除整个 attempts 目录（其中有已提交分片）。schema downgrade 明确拒绝。回退到完全不认识bulk的旧后端前须另做兼容验收，不能保证旧二进制可读新合同。

## 重现验证

```sh
# backend目录，专用隔离PostgreSQL；不得复用现场 .env
uv run pytest tests/domain/test_netflow_bulk_engine.py tests/api/routes/test_netflow_bulk.py -q
uv run python -m app.netflow_bulk benchmark --output /new/isolated/benchmark-dir \
  --bytes 1000000000 --memory-mb 128 --threads 1 --rss-mb 768 --temp-gb 8 --reserve-gb 20
```

生成器支持固定种子、目标字节/近似行宽、IPv6、重复、对象/peer基数、热点IP、多文件重叠。实际字节/行数、实际重复率以报告为准。`scripts/benchmark-netflow-bulk-api.py` 不读取dotenv，要求显式环境变量配置（ENVIRONMENT=local、POSTGRES_SERVER=127.0.0.1、POSTGRES_PORT=15434、POSTGRES_DB=bulk_test及测试账号），在私有空目录启动父子进程；只允许本任务专用本机测试库，使用独立OS worker和真实PG/API，控制面是fixture；`scripts/test-netflow-bulk-runtime.py` 另用真实 agent-compose/Linux guest，复用既有隔离harness。模型、真实来源和现有部署均不参与。

真实agent-compose隔离验证可从仓库根执行（使用新的证据目录，安装前述uv依赖；脚本自行创建随机端口测试设施；运行前及发布PASS前要求工作树干净且HEAD不变）：

```sh
uv run --package app python scripts/test-netflow-bulk-runtime.py /new/isolated/runtime-evidence
```

逐级预检和实测见[benchmark报告](../work/netflow-bulk-benchmark.md)。**TB 验收未执行**；不能用本机小规模结果推出TB吞吐、日增量、压缩率或硬件需求。
