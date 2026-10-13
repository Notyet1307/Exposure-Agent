# OMP 原生只读审阅回执

范围与限制随各结论保留；不是运行或业务验收。

## StandardsFinal

- **overall_correctness：`correct`（仅限静态审阅）**
- **confidence：0.77**
- **findings：`[]`**

**explanation**

Reviewer 对 `05b14d52ab6d9f3b0eb54c3a7c7fcfed69bd3751..3854d74` 全量变更及必要固定版本调用方，依据 AGENTS、已接受 ADR-0026 和同版 Spec 审阅，未发现达到可证实、补丁引入且应修复标准的缺陷。该判断不代表运行或业务验收通过。

重点静态结论：

- **发布长 IO 与 lease 锁**：全量文件哈希和投影校验已移出 lease 行锁事务；投影写入按有界批次提交。
- **CSV 逻辑行上限**：`BoundedLines` 在 `csv.reader` 获得逻辑记录前累计并限制输入量，同时保留引号换行支持。
- **目录 fsync**：ready、分片 rename、normalized 硬链接及最终结果路径已增加目录 fsync。
- **失败预约释放、审计与取消**：失败处理具有 fencing／终态保护、预约释放及审计；取消和最终发布通过共享项目锁与 job 检查串行化。
- **挂载与前端切换**：挂载校验不再依赖跨挂载 inode 相等；登记组件按账号／项目重新挂载，结果查询缓存绑定账号／项目／analysis。

**unchecked**

未检查未提交改动、另一 reviewer 结论或生产环境；未运行 tests/build/lint/benchmark、数据库迁移、浏览器交互或业务模型调用。未实测故障恢复、并发 lease／取消／发布、断电持久性、跨 macOS/Linux 挂载时间戳一致性、账号／项目切换、Linux 多架构镜像及资源／查询性能。**以上均不记 PASS；TB 验收未执行。**

---

## SpecFinal

- **overall_correctness：`incorrect`（仅限静态审阅）**
- **confidence：0.88**
- **findings：1 项**

### [P2] 在定向证据文件缺失或不可读时持久标记数据集失效

- **位置**：`backend/app/domain/netflow_bulk_queries.py:595–602`
- **finding confidence：0.98**

在已发布 analysis 的某个标准化分片被删除、替换为符号链接或变为不可读后，请求该分片的有效 reference，会在这里的 `safe_file()`／`file_hash()` 抛出 `BulkError`／`OSError`，尚未进入设置 `BulkDataset.invalidated` 的分支；`NetFlowRoute` 也不捕获这两类异常，因此返回未处理的 500。

后续 `gate()` 只检查结果投影文件及数据库失效标记，不检查该标准化分片，故同一数据集的普通列表和 V2 辅证仍可继续作为有效结果读取。这违反 B6 的“发现漂移置失效且拒读”。应将路径安全检查与文件读取异常纳入同一持久失效处理，而不只处理成功读完后的摘要不一致。

**explanation**

Reviewer 对同一固定 diff，按 `docs/specs/netflow-bulk-v1.md@ee61c8ce4249a2390d38a065c8cbbbec2be90e1d` 静态审阅。由于上述定向证据读取未完整落实持久失效合同，不能判定补丁正确。

其余重点静态结论：

- **端口 0／00**：TCP／UDP 均归一为整数 `0`。
- **5000 位数字**：在 `int` 转换前去前导零并检查位数，超范围值不会进入超长整数转换。
- **未知采样保守策略**：未知模式、sampled 缺失／无效 rate、缺失采集身份或有效时间，均按稳定来源引用保守保留。
- **全数据集去重**：完整 canonical key 在全 dataset retained 表去重并确定代表记录，计数守恒。
- **查询、游标与辅证**：观察／peer 游标绑定分析身份和过滤条件，消费路由已接入；V2 辅证使用独立 gate 和 PostgreSQL 分页。
- **旧版本边界**：旧仓储分支及 50 MiB／0.4.0 处理边界保留。

上述均非运行验收 PASS。

**unchecked**

未执行 tests/build/lint/benchmark、数据库迁移、API/UI/agent-compose 运行、故障注入、镜像安装及依赖下载验证；未验收 RSS/spill、kill／lease／双 worker／磁盘耗尽恢复、冷／热查询与并发性能或旧版回归；未读取未提交测试／验证或另一 reviewer 结果。**TB 验收未执行，不记 PASS。**

---

## StandardsDelta

**findings:** `[]`

**verdict:**

仅对已提交的 `3854d74..6d491d7` 做只读静态 Standards 增量审阅，未发现可由该增量直接证明的权限边界、持久化结果/证据不可变性或故障失效边界回归。已核对相关已接受 ADR、固定 Spec 的 B6，以及 `6d491d7` 的证据读取入口、项目/租户与 Context 门禁、分片校验、失效提交和后续读取门禁：新增异常路径在拒读前持久化 `dataset.invalidated`，未改写已发布结果或证据内容。未审阅工作树未提交内容，未重新审计基线；TB 未运行（TB 验收未执行），本结论不是运行验收 PASS。

## SpecDelta

**findings:** `[]`

**verdict:**

仅对已提交增量 `3854d74..6d491d7` 及必要的 `6d491d7` 调用链进行了只读静态审阅；行为依据为 `ee61c8ce4249a2390d38a065c8cbbbec2be90e1d:docs/specs/netflow-bulk-v1.md` 的 B6，并查阅了 skill-usage、ADR-0016、ADR-0026 与相关 ADR-0024。结论：此前报告的定向证据分片缺失、符号链接或不可读未持久失效问题，在本次限定范围内静态判断为完整修复，未发现可证实的增量缺陷。

具体调用链：bulk `/record` 路由直接调用 `netflow_bulk_queries.record`；新增 try 范围覆盖 `safe_file`、`file_hash` 与 Parquet 读取。分片缺失或符号链接由 `safe_file` 转为 `BulkError`，文件访问或读取权限错误由 `OSError` 捕获，摘要不符也显式转为 `BulkError`；这些路径统一设置 `BulkDataset.invalidated=True`，并在抛出 `bulk_integrity_invalidated`（HTTP 409）之前调用 `session.commit()`。该字段是 PostgreSQL 映射字段，不是会话内临时标记；请求依赖 `get_db` 创建独立 Session，路由错误处理只传播 HTTPException，不存在包住此次提交并将其撤销的外层事务。因此按代码事务语义，后续请求关闭或回滚不能撤销此前已成功提交的失效状态。

后续独立请求中，`observations`、`peers`、`observation`、`evidence`、`record` 均先经过 `gate`，并因 `dataset.invalidated` 拒读；V2 辅证经 `_binding_material` 分发至同一 `gate`，辅证地址请求拒读，辅证摘要转换为 `UNREADABLE` 且不返回辅证明细或计数，不回退旧内容。上述结论是静态调用链与事务语义判断，不是运行验证。未读取工作树未提交内容作为审阅证据，未执行测试、应用、build、lint 或 smoke；TB 未运行，TB 验收未执行，不记 PASS。
