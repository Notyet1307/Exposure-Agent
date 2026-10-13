# NetFlow bulk 代码审计

2026-10-13，基线及远端 main：`05b14d52ab6d9f3b0eb54c3a7c7fcfed69bd3751`。原 checkout 是 main@16e451d 且有用户 Spec/current/plans WIP，保持原样；本任务在独立 `codex/netflow-bulk` 工作树。以下行号固定基线，后续实现可能移动。

## 当前真实调用链

1. HTTP小文件：`backend/app/api/routes/projects.py:385` 调 `stream_netflow_upload`，`:388` 调 `accept_netflow_dataset`。流式接收不代表异步解析；`backend/app/domain/netflow_dataset_acceptance.py:300` 在接受调用中执行 `parse_netflow_dataset`。
2. 标准化：`backend/app/domain/netflow_datasets.py:145` 解析入口；`:108` `_detect_encoding` 最坏分别扫描UTF8与GB18030；`:166` CSV逻辑记录解析；`:191` SQLite连接；`:296` 每有效行插入完整canonical字符串；`:303` 全局GROUP BY重复统计；`:308` 窗口查询样本。`:287`附近先写全部有效行到CSV，重复记录并未物理删除。`:330` 再扫normalized做Hash、`:337`再扫raw做Hash。
3. 接受幂等：`netflow_dataset_acceptance.py:300`完整解析之后，`:317`才按raw摘要查询同Dataset。`:307`还核对上传摘要；`:389`和`:391`发布前再次校验文件。不能删除这些校验来伪造吞吐改进。
4. 分析：`backend/app/api/routes/netflow_processing.py:163` → `launch_analysis`；`backend/app/domain/netflow_processing.py:796`持久预留、`:952` agent-compose启动；`backend/app/integrations/agent_compose.py:394`直接命令启动 `app.netflow_processing_runner`。worker `backend/app/netflow_processing_runner.py:18`验证ID/build，调用`:36`附近 `execute_analysis`；domain `:1163`固定输入/上下文后调适配器process，`:1024`校验结果后事务发布。已有独立worker不是请求内计算，但没有bulk分片lease/checkpoint恢复；`:1174`附近对已started任务不重复执行，reconcile仅核实旧Session产物/状态。
5. 适配上限：`backend/app/core/config.py:65` `NETFLOW_MAX_BYTES`强制≤50MiB；`backend/app/integrations/netflow_processor.py:263` `default_config`固定100000记录、100MiB；`:274`禁止配置超过这些值。`:139`运行时footprint；`backend/vendor/README.md:3`固定0.4.0 wheel及SHA256。不能修改wheel/footprint或分块调用后简单相加。
6. 新版查询：`frontend/src/components/NetflowResults.tsx` → `backend/app/api/routes/netflow_reviews.py` → `backend/app/domain/netflow_reviews.py`。`netflow_processing.py:526` `analysis_material`先检查状态和当前Context，再 `_inputs`/`verify_receipt`，`:542` `processor.load_bundle`；适配器`:194` `_lines`读成list，`:323` `load_bundle`校验并加载整个bundle。`netflow_reviews.py:546`起observations、`:639`起peers与`:710`起evidence在全量集合上再过滤排序分页。API有skip/limit不等于底层查询有界。
7. V2辅证：`backend/app/domain/comparison_results.py:1282` `_binding_material`复用analysis_material；`:1326`统计全observations，`:1467`逐条构建IP groups后切页。核心两源结果与辅证独立，`:1319`附近捕获N读取错误为UNREADABLE，不能让bulk错误传播阻断核心；bind保持namespace、管理员范围证明/固定资格及截止。
8. 旧V1关联：`backend/app/domain/source_correlations.py:591`仍load全部bundle建立来源记录；bulk不能误入。旧原生活动账 `backend/app/domain/netflow_ledger.py:40–41`维持100000/100MiB，其双端候选与新版declared_source不是相同统计。旧 `netflow_activity.py` 为Run固定活动投影，不是新版观测页面主链。

## 必须保留的身份与撤销

`netflow_processing.py:221` Dataset合同/schema、`:241`项目/租户Context、`:271`当前确认/namespace撤销与输入Hash绑定；`:320`仅管理员创建确认，固定原始与标准化摘要。`:643` current_netflow按可信collection_scope解析，不能用最近上传替代同范围。`:728`附近按完成时间选成功结果，bulk需增加明确输入顺序防迟到覆盖，且不改固定历史。

已完成结果UI仍无条件5秒刷新（`NetflowResults.tsx:92–110` query defaults）；bulk须拆进度/轻量授权复核与不可变内容查询，撤销时清缓存。普通列表不得为完整性重读TB原始文件：新不可变产物与发布回执/查询投影绑定需有独立校验/失效机制，旧读取保护不删。

## 环境与复用

`backend/pyproject.toml:5`要求Python≥3.14；`backend/Dockerfile:1`为3.14，`backend/Dockerfile.runner:1`为3.14-bookworm，guest镜像固定多架构digest。现有依赖无DuckDB/Arrow/Polars；根uv.lock为工作区锁。`agent-compose.yml`已有无模型/云图能力的netflow-processor直命令runner及Artifact挂载；API/runner安装前均核wheel SHA256。

本机只读预检：arm64、内存16GiB、工作盘可用约116GiB（瞬时值，不等于专用预算）。不足以在保留原始/标准化/spill/结果的情况下直接验收1TB或100GB；先隔离小规模/1GB，逐级重新预检，不能自动吃满共享盘。

2026-10-13 PyPI公开元数据实查：DuckDB1.5.6、PyArrow26.0.0均提供CPython3.14的macOS arm64与manylinux arm64/x86_64 wheel。此为可安装性线索，安装、真实运算和Linux镜像验收仍需分别执行。DuckDB官方[内存说明](https://duckdb.org/2024/07/09/memory-management)与[OOM说明](https://duckdb.org/docs/current/guides/performance/oom)明确存在buffer manager外分配；独立进程/容器RSS限制不能省略。

## 实施接缝

独立bulk manifest/成员/分片/执行记录；复用项目授权、操作幂等审计、Context与Analysis身份及agent-compose。版本化result repository连接新版观测、证据、current和V2辅证；旧0.4.0处理/查询继续原合同。重型明细/peer留列式层，PG存版本、对象摘要和查询索引；不新增第二调度器、不把DuckDB提升为权威业务库。完整验收见[bulk合同](../specs/netflow-bulk-v1.md)。

审计是静态事实与本机资源快照，不是容量验收。实际压测/故障/旧回归尚未执行，**TB 验收未执行**。
