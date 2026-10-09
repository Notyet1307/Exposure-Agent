# V2 AI 解读实施验证

批准行为与ADR固定在 `1c42406d6d4b83b8bad8d54a24ec2e40954abb98`；任务为 #297/#298/#299。维护者后续明确授权正常源码发布、CI/Review后合并、既有8081备份/恢复演练/追加迁移/部署与验收后关闭。部署和Issue状态另行读回，不由本地PASS推定。

本地源码分阶段：A `a17dd09`，B `9df637e`，C `cbabdd2`；受控后端材料/完成桥及opaque run capability为 `182883b`/`beb29f0`，移动布局与真实打印修复为 `196cbca`。旧Run请求/模型路径/发布保护保持；仅追加 `ai2980000001`，不伪造GovernanceRun。

| 验收 | 状态 | 实际证据 |
| --- | --- | --- |
| A-01–04 | PASS | [独立阅读回执](v2-reading-validation.md)：三种真实首次故障/GET重试、分域v1往返、字段/权限/三宽度/双语/键盘。 |
| B-01/07 | PASS | 真实隔离PG/API/生产构建浏览器：结果→明确生成→同报告摘要/全文→CAS修订→独立确认→引用→打印；无Run、无N也能生成。 |
| B-02 | PASS | 实际47地址、20样本、27省略；字节裁剪保留全量统计且不留悬空refs；语言/阅读对象facts/summary相同；添加/撤销/到期N核心统计仍3。 |
| B-03 | PASS | strict schema、必需固定facts、外域引用/地址、虚构数字/严重性/近期活动/已处置负例拒绝；单白名单工具、空参数、隔离child env和禁通用工具由集成/运行合同检查覆盖。自由prose语义不能由这些检查证明。 |
| B-04 | PASS | 实际选定N到期：页面清除摘要/正文、API原稿/材料/历史拒读；实际Context撤销：旧N报告全遮蔽、在途生成FAILED，撤销后Provider零追加调用，C+A仍3。当前actor/源权限每次复验；晚到、403/410/材料409与scope清屏另有组件回归。 |
| B-05/06 | PASS | 同原key/GET零额外生成、异请求冲突、原稿不可变、CAS冲突、独立确认/历史；实际模型A/B绑定、撤销A后B可用；单工具/累计字节/输出/时限门禁。 |
| B-08 | PASS | 后端全量1479 passed；旧Run实际Pi报告生成通过；旧18域查询包含在回归。新增迁移前后53张历史表原字段行/Hash一致、2份旧原稿保留（测试恢复集）；正式恢复/迁移另外验收。 |
| B-09 | PASS | 独立黄金集阅读审阅：一屏结论、两侧独有具体地址、登记/采集依据与改变判断条件、未知/假设/建议准确、固定统计/样本/来源版本可追溯。仅本地固定Provider样例。 |
| C-01 | PASS | 同adapter固定address_key、四段输出，真实Pi生成；地址详情明确入口零自动POST，actor/结果/binding/address分离。 |

## 必要检查与真实运行身份

- `POSTGRES_DB=product_browser_v2_ai_tests uv run bash scripts/tests-start.sh`：1479 passed，3 warnings，1731.41s；随后 `coverage report --fail-under=90` PASS（报告90%）。backend Ruff/mypy226文件/ty PASS。
- 前端52项受影响component回归、build/Biome、context hygiene与diff检查PASS。组件mock与真实业务浏览器分开记账。
- 浏览器1366/1920/390无整页横向溢出；实际打印回调前GET重鉴权，原生Chromium打印三页均非空、逐页PNG检查无裁切/重叠/侧栏/按钮。物理打印机/OS对话框NOT_RUN。
- 完整真实Pi/agent-compose/本地响应Provider探针 `exposure-v2-runtime-991dxdxt` PASS：V2、旧Run、当前地址、模型绑定/撤销、原key和GET；Provider A7/B11次包含资格/业务调用，不能当作单份模型成本。控制面106文件扫描原始Provider Key零命中。
- 临时backend `sha256:efe7bd2f5796efc816e8bcbc0728b17365665b6ca707cf2358bf1fcb411661a1`、runner `sha256:115484c13a5285b93860bfda45dc5970c13c1921484ee88e72b9df17f2abaff3`；两镜像171个app Python文件逐项与 `beb29f0` 一致，runner内build文件同完整SHA。临时runner继承上游OCI标签，应用身份以该文件/源码hash为准；正式release会独立标注合并SHA。
- Standards/批准Spec独立静态审阅及bridge/打印增量审阅PASS；它们不替代上述业务/运行验收。

受限本地证据根：`/Users/yang/.codex/worktrees/exposure-v2-ai-evidence/`；runtime/browser/N各回执在 `runtime-probe/exposure-v2-runtime-991dxdxt/`。黄金原稿/确认版、截图、打印与凭据不进Git。N材料由实际确定性parser/worker在测试control fixture执行，非native NetFlow调度证明；随后报告确实经真实Pi/控制面运行。显式test-fixture读取开关只开启在自有隔离backend，正式实例不改变该开关。

## 失败与纠正

失败证据均保留：初版guest重读Artifact导致拒读，改为后端受控DTO；managed guest缺签名key，改为后端签发仅经secret env传递的run capability；保存阶段仍重读Artifact，完成提交也改为后端复验/保存。没有给模型guest挂载Artifact或传应用签名密钥。

探针配置错误分别纠正：完整runner SHA tag缺失；全库无Run断言误计独立旧Run兼容fixture（改为V2项目无Run）；人工编辑误用POST（改为合同PATCH）；地址黄金输出缺少固定计数ref；N test fixture初始被默认禁读（仅隔离显式开关）。旧Run一次轮询超时未找到可证明锁环；随后完整实际重跑PASS，未改锁。CLI路径、旧schema误用及中断的全量测试均未计为最终PASS。

移动英文select/filter溢出已局部修复。首次打印有空白尾页，改为body portal和选定报告单独布局；确认版三页均非空。首轮layout诊断log保留，确认轮截图以新名称记录。

## 明确未运行与后续门禁

真实外部模型语义、真实token/费用、客户数据出域、真实来源同步/扫描/写回、期限扩展/清理、Durable及跨版本prose变化均NOT_RUN或本期不适用。上述本地固定响应和人工阅读不证明真实模型业务质量。源码PR/必需CI/正常merge、8081加密备份与实际恢复/迁移/部署和Issue关闭需各自记录实际身份与结果。
