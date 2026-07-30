# Issue #33：CustomerUpload XLSX 解析器与资源边界调查

状态：完成调查，建议 **GO** 进入 CustomerUpload 正式摄取实现；本调查不交付 CustomerUpload、Artifact、API 或 UI。

## 1. 决策

后续 `.xlsx` 确定性解析固定使用：

- Python `3.14`（本次实测 `3.14.6`）；
- `openpyxl==3.1.5`，以 `read_only=True`、`data_only=False`、`keep_links=True` 打开；
- `defusedxml==0.7.1`，并在运行时确认 `openpyxl.xml.functions.DEFUSEDXML is True`。

这两个版本已写入 `backend/pyproject.toml` 和 `uv.lock`。`openpyxl` 是唯一工作簿 parser；ZIP 中央目录和 OOXML 关系检查使用 Python/defusedxml 的窄预检，不引入第二个表格 parser 或多 parser 抽象。

选择 `openpyxl` 的理由是它在目标 Python 环境中可运行，能够只读迭代行、保留公式类型、公开 worksheet 可见状态并读取标准 OOXML 关系。`python-calamine` 没有提供本阶段所需的完整 package relationship/active-object 检查面；Pandas 或转换工具会引入本票不需要的数据框、格式转换和额外 parser 路径，因此未采用。

`openpyxl` 自身不提供 ZIP bomb 上限，也不能代替主动内容检查。正式实现必须保持“有界 ZIP/OOXML 预检 → `openpyxl` 只读解析”的顺序；不得直接把未预检的上传交给 `load_workbook`，不得执行或采用公式缓存值，也不得保存/重写客户工作簿。

## 2. 固定全局阈值

| 边界 | 固定值 | 正常样例最大实测 | 余量 |
| --- | ---: | ---: | ---: |
| ZIP entry 数 | 2,048 | 13 | 157.5× |
| 单 entry 解压大小 | 64 MiB（67,108,864 bytes） | 20,280,113 bytes | 3.31× |
| 总解压大小 | 256 MiB（268,435,456 bytes） | 20,300,099 bytes | 13.22× |
| 中央目录读取量 | 4 MiB（4,194,304 bytes） | 873 bytes | 4,804× |

这些是服务级固定值，不按 Project 配置。20 MiB（20,971,520 bytes）请求体上限保持不变，独立于 ZIP 解压上限。

2,048 entries 足以覆盖正常工作簿的 package 扩展，同时在读取中央目录正文前即可从 EOCD 的 entry count 拒绝异常归档。64 MiB 单 entry 上限为接近请求上限的正常静态图片和 50,000 行 worksheet 都保留至少 3.31× 余量。256 MiB 总量允许一个工作簿包含多个接近正常边界的 part，但仍把最坏允许解压量固定在可审计范围内。

阈值不是内存预算：正式摄取仍应在隔离进程/容器中配置总体 CPU、内存和执行超时。该部署级预算依赖交付服务器规格，本票未验证，也不能由上述 ZIP 数值替代。

## 3. 可复现入口与 fixture

从仓库根目录运行：

```bash
uv run --project backend python investigations/issue_33/probe.py
```

可用 `--output <path>` 额外写入同一份脱敏 JSON，或重复 `--fixture <name>` 只运行指定样例。探针在随机临时目录中生成 fixture，结束后由 `TemporaryDirectory` 删除；输出不包含临时路径或原文件名。自动检查入口是：

```bash
cd backend
uv run pytest ../investigations/issue_33/test_probe.py -q
uv run ruff check ../investigations/issue_33
uv run mypy ../investigations/issue_33/probe.py ../investigations/issue_33/test_probe.py
```

所有 fixture 由代码确定性生成，固定 OOXML 时间戳，不提交或读取客户文件：

| fixture | 形态 | 预期 |
| --- | --- | --- |
| `default_v1` | 默认 v1 表头，3 条数据，仅 TEST-NET 地址和虚构责任信息 | 接受 |
| `near_request_limit` | 默认 v1 + 静态 PNG，归档 20,286,591 bytes（请求上限的 96.73%） | 接受 |
| `row_shared_style_boundary` | 50,000 行、1,798 个 shared strings、64 个 style XF | 接受 |
| `entry_count_bomb` | 2,049 个 ZIP entries | `workbook_resource_limit` |
| `compression_bomb` | 70,626-byte 归档内含 67,108,865-byte 高压缩 entry | `workbook_resource_limit` |
| `total_size_bomb` | 5 个各 53,687,092-byte entries，总解压 268,454,113 bytes | `workbook_resource_limit` |
| `formula` | worksheet 公式节点 | 拒绝 `formula` |
| `external_link` | content type + relationship 声明的非固定路径 external-link part | 拒绝 `external_link` |
| `data_connection` | content type + relationship 声明的非固定路径 connections part | 拒绝 `data_connection` |
| `hidden_sheet` | 额外 hidden worksheet | 拒绝 `hidden_sheet` |
| `embedded_object` | content type + relationship 声明的非固定路径 OLE part | 拒绝 `embedded_active_object` |

`near_request_limit` 中的静态图片符合架构允许范围，只保留在原始 Artifact，不参与行解析。高行数样例只使用 `192.0.2.0/24`、`198.51.100.0/24` 和 `203.0.113.0/24`，责任字符串统一为 `Example` / `Fixture` 命名。

## 4. 测量结果

测量环境：Darwin `25.5.0` arm64、Apple M4、16 GiB RAM、CPython `3.14.6`、`openpyxl 3.1.5`、`defusedxml 0.7.1`。命令于单进程运行；耗时是中央目录预检、OOXML 检查和完整只读行迭代之和，峰值是该阶段 `tracemalloc` 记录的 Python allocation peak，不含 fixture 生成和解释器基线。

| 正常 fixture | 请求 bytes | entries | 最大 entry 解压 bytes | 总解压 bytes | 行数 | 解析耗时 | 峰值内存 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `default_v1` | 5,277 | 9 | 10,140 | 18,653 | 3 | 0.007 s | 406,168 bytes |
| `near_request_limit` | 20,286,591 | 13 | 20,280,113 | 20,300,099 | 3 | 0.008 s | 346,512 bytes |
| `row_shared_style_boundary` | 1,794,373 | 7 | 19,468,856 | 19,541,470 | 50,000 | 6.176 s | 4,667,303 bytes |

耗时与内存会随硬件和 Python patch 版本变化；决定阈值的是可复现 shape 和 ZIP 统计，而不是把本机时间写成 SLA。

三个资源样例分别越过 entry 数、单 entry 和总解压量。高压缩比样例的 EOCD 声明 10 entries、中央目录 640 bytes；有界读取中央目录后得到单 entry 解压量 67,108,865 bytes，超过 64 MiB 上限。三个样例都在 `central_directory` 阶段稳定返回 `workbook_resource_limit`，没有读取超限 entry、没有调用 `openpyxl`、没有把内容展开到内存或磁盘。

## 5. 预检与拒绝能力

探针只从文件尾读取最多 65,557 bytes 定位 EOCD。它先验证单磁盘、非 ZIP64、entry count、中央目录长度与文件内边界；只有声明值通过后才按中央目录的精确长度读取，逐项累计压缩/解压大小并验证名称、重复项、加密和压缩方法。任一资源值超限即在正式解析前停止。

随后以受限 entry stream 读取 OOXML content types、relationships 和 XML parts：

- 对全部 OOXML XML part 的本地名 `<f>` 节点识别公式，不依赖固定 worksheet 路径或缓存值；自动检查还把公式 worksheet 移到 relationship 指定的非标准路径，并确认 `openpyxl` 能打开而预检仍会拒绝；
- `externalLinks` part 或 external-link relationship 识别外部链接；
- `connections.xml` 或 connections relationship 识别数据连接；
- `activeX`、`ctrlProps`、`embeddings`、VBA/toolbars part 及对应 relationship type 识别嵌入主动对象；
- `openpyxl` worksheet state 识别 `hidden` / `veryHidden`，并拒绝多 worksheet。

`defusedxml` 同时用于调查预检并被 `openpyxl` 实际启用。探针对五类拒绝能力都有自动测试；本阶段没有静默降级或已知无法识别的必拒类别。

已知边界：预检只支持普通单磁盘、非 ZIP64 的 XLSX；在 20 MiB 请求上限和 2,048-entry 契约下没有接受 ZIP64 的业务需要，正式实现应将 ZIP64 归为 `malformed_workbook`。普通静态图片允许；宏、OLE、ActiveX 和控件不允许。未测量损坏归档修复、CSV/XLS/XLSM 转换、流式行框架、Profile DSL、超大真实客户数据或恶意 XML 的独立 CPU SLA。

## 6. 泄露与残留检查

- fixture 只含 TEST-NET 地址、`.invalid` URL、`Example` / `Fixture` 责任信息和确定性二进制图片；
- 探针和 JSON 结果不输出原始单元格、token、文件名、临时路径或 parser 异常；
- 自动测试检查结果不含当前 home path 和 `token`，并确认探针返回后临时父目录为空；
- 仓库不保存生成后的 `.xlsx` 或 benchmark 临时 JSON。

## 7. 后续实现可直接引用的事实

CustomerUpload 正式实现应直接复用本报告第 1、2、5 节的 parser 配置、固定阈值和校验顺序，并把超限统一映射为 `workbook_resource_limit`。本票没有创建 CustomerUpload、Artifact、数据库模型、迁移、HTTP API 或 UI，也没有验证 PostgreSQL、客户 API、CloudAtlas 或前端行为。
