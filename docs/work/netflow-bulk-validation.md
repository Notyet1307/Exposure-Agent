# NetFlow bulk V1：本地交付与验收回执

日期2026-10-13；[Issue #304](https://github.com/Notyet1307/Exposure-Agent/issues/304)；批准Spec/ADR固定 `ee61c8ce4249a2390d38a065c8cbbbec2be90e1d`。基线`05b14d52ab6d9f3b0eb54c3a7c7fcfed69bd3751`，隔离工作树`/Users/yang/.codex/worktrees/netflow-bulk/Exposure-Agent`，分支`codex/netflow-bulk`。任务状态/依赖/授权仍以GitHub Issue为准。

## 交付内容

真实调用链与初始瓶颈见[审计](netflow-bulk-audit.md)。本轮提供独立源码bulk引擎、追加3个迁移、锁定DuckDB/PyArrow、冻结多文件接入、Parquet标准化、完整键精确外存去重、持久任务/lease/fencing/checkpoint/取消、原子发布、PostgreSQL观测投影、列式peer与定向证据、新版观测页和V2可选辅证接入。

保留原50 MiB小文件入口、固定0.4.0 wheel/足迹、旧结果读取、固定历史及Context撤销。旧ledger/V1全量关联明确拒绝bulk。NetFlow未知归属/监听/可达性保持未知；N失败不阻断C/A核心比对。没有新增逐条模型调用。

分阶段本地提交：

| 阶段 | 提交 |
|---|---|
| 诊断、ADR与数据/去重合同 | `6be81a7`、`ee61c8c`（已授权规格发布） |
| 独立引擎与合成生成器 | `ab10cab` |
| 可恢复任务、查询与业务接入 | `91cd93f` |
| 审阅/运行时发现的修复 | `851195e`至`6d491d7` |
| 正确性、故障、查询、UI及运行时harness | `795d119`、`b64dc4f`、`e577a39`（测试类型、隔离和恢复证据加强） |

源码/测试已本地提交；业务源码push/PR/merge、部署与关闭Issue不在本轮授权内，未执行。部署、启用、回退和运行命令见[Runbook](../runbooks/netflow-bulk.md)。

## 验收矩阵

| 验收 | 结果及证据 |
|---|---|
| AC-B01 | PASS（合成隔离范围）：受控ready、路径/链接/压缩拒绝、身份/hash校验、旧上限与0.4.0回归 |
| AC-B02 | PASS：跨文件/分片、重排/重跑、完整与缺失身份、不同采集点、时区/异常、NAT/采样、IPv6/mapped、引号换行、编码和字段/逻辑记录/展开行预算；计数守恒 |
| AC-B03 | PASS（注入范围）：真实SIGKILL后恢复；两worker竞争/lease过期/旧fence拒绝；checkpoint与最终发布故障；取消；模拟ENOSPC/预留盘不足。未实际填满宿主盘 |
| AC-B04 | PASS（1 GB）：超过硬内存的输入完成并实际spill；RSS、阶段、字节/行、产物和小样本恢复时间见[benchmark](netflow-bulk-benchmark.md) |
| AC-B05 | PASS（测试规模）：重新过滤禁用CSV解析器仍成功；查询时原始目录实际不可用仍成功；80万级对象、72万级peer服务端分页、游标与固定历史；未做OS级全局I/O追踪 |
| AC-B06 | PASS（自动化范围）：项目隔离、Context撤销、未完成拒读、历史/新旧顺序、V2辅证失效不阻断核心；浏览器缓存清除另验 |
| AC-B07 | PASS（相关回归范围）：旧语义子集对照与新去重差异显式断言；原生Standards/Spec审阅及独立业务验收分开记载 |
| AC-B08 | 部分PASS：1 GB容量、冷连接/热查询和处理时API实测；10 GB预检停止，100 GB/1 TB NOT_RUN；**TB 验收未执行** |

后端最终bulk/故障测试48项通过，46.42秒；相关NetFlow旧处理、查询、runner/集成、activity/ledger等212项通过，167.90秒；C/A与可选N相关业务测试68项通过，230.14秒。这些集合有交叉，不相加声称328个唯一用例，也不声称全仓库测试通过。[相关回归XML](evidence/netflow-bulk/related-regression.xml)、[bulk恢复XML](evidence/netflow-bulk/bulk-recovery.xml)。

前端固定结果组件最终13项通过（22.4秒，单worker）；包含cursor翻页、不可变内容不再5秒重取、访问资格轮询、撤销清缓存和身份冲突不回退。此前一次并行运行出现加载超时，另一项断言依赖已被访问检查清掉的身份文案；保留失败日志，并改为断言拒读标题及零内容请求。[桌面](evidence/netflow-bulk/bulk-desktop.png)/[390px移动布局](evidence/netflow-bulk/bulk-mobile.png)已查看，无页面横向溢出，宽表格在自身容器内滚动。

后端ruff/mypy/ty通过，mypy覆盖237个源文件。前端lint/typecheck/build通过，存在既有Biome配置迁移提示和Vite弃用提示。独立PostgreSQL从旧head升级到3个追加revision成功；现网规模锁表耗时和带生产数据恢复演练未执行。原0.4.0 wheel SHA256仍为`eba079556be6066c66eb450421571acb07afe527d46dd4e5b8b6b95c93c56d3f`，未原地修改。

## 审阅及发现处理

OMP原生reviewer分别按Standards和固定Spec独立静态审阅。初次因非交互审批阻断没有执行检查，维护者明确授权本轮只读审阅后重新运行。最终Standards全量至3854d74无finding；Spec发现定向证据缺失/不可读应持久失效的P2，6d491d7修复，两轴增量复审均无finding。[原生回执](evidence/netflow-bulk/native-reviews.md)。静态审阅不代替执行、性能或业务验收。

测试harness增量审阅另发现dotenv读取边界、固定提交证据检查、相对输出路径与API失败误报PASS四项，已在e577a39修复，e577a39两轴增量复审均无finding，见[最终原生回执](evidence/netflow-bulk/harness-review-final.json)。[初次静态回执](evidence/netflow-bulk/harness-review-initial.json)。当前任务原`.env`是本会话新建的合成专用库配置；没有据该发现推断曾读取生产凭据。加强后的恢复用例另用原始CSV独立生成无故障基准，比较全部输出表的逻辑行与所有计数；19项API/故障用例通过。[完整恢复比较回执](evidence/netflow-bulk/full-recovery-comparison.xml)。

运行中还修复了跨macOS/Linux挂载inode差异、发布长哈希持有lease锁、CSV逻辑记录/展开字段预算、未知采样保守身份、数字端口0、失败预约释放/审计及访问资格失败清缓存。旧失败日志保留在本任务临时证据目录，最终通过不覆盖失败历史。

修复后32 MB脚本验证：audit hook禁止任何dotenv读取，使用相对输出路径仍成功；处理期注入一次HTTP503后报告FAIL/退出1，正常组PASS/退出0；脏工作树在启动前拒绝。[脚本门禁回执](evidence/netflow-bulk/harness-guard-results.json)。

严格入口随后在干净fa08480构建执行真实agent-compose验收，运行前与写PASS前HEAD/工作树检查通过：128,002,652字节、134,826行，49.704秒，RSS624,156,672字节，计数与先前一致。[最终运行时回执](evidence/netflow-bulk/runtime-delivery.json)。fa08480相对6d491d7的backend/app、frontend/src与锁定依赖无差异；后续提交仅归档证据/文档，不以文档HEAD冒称重新运行的构建。

## 独立业务验收

独立验收者自行构造2个CSV、7条逻辑记录并手算oracle，使用固定6d491d7、独立随机端口PostgreSQL、真实HTTP和agent-compose Linux worker。跨文件IPv4-mapped同一记录、不同采集点、两条缺时间、IPv6、无效IP的预期与实际一致：raw7、invalid1、filtered0、retained6、unique5、duplicate1；对象2、peer1。固定analysis的cursor分页、定向证据/原记录读回通过；Context撤销后observations返回409/netflow_context_revoked。耗时22.884秒。[独立回执](evidence/netflow-bulk/independent-business.json)。这是独立小样本业务验收，不等于真实客户验收或TB验收。

此前另一独立尝试的初始oracle没有将mapped地址规范化计入重复，预期有误而候选结果正确；原FAIL文件保留，未冒称产品缺陷。上面的PASS来自另行设计的7行oracle和真实运行，不覆盖原失败。

## 交付边界

所有输入为固定合成数据；没有读取生产凭据、修改8080/8081、调用真实来源或业务模型，没有清理既有Run/报告/Artifact。独立测试只清理自己创建的进程/容器，临时数据和失败证据保留。

实现边界：未压缩CSV/TXT；冻结单逻辑dataset去重，不承诺跨日/跨dataset增量；单个未完成大文件可能重读；单个bulk准入；旧0.4.0材料复核/反馈并未迁移；bulk不是旧引擎全部能力的替代品。Linux amd64运行、完整磁盘冷缓存、生产数据恢复/迁移停顿、10 GB及以上和真实客户业务验收均NOT_RUN。

**TB 验收未执行。** 本轮结果不构成生产容量或客户验收承诺。
