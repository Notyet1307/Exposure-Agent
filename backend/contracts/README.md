# NetFlow correlation v1：后端接口交付

## 固定身份与取得方式

- Issue：[后端 #273](https://github.com/Notyet1307/Exposure-Agent/issues/273)；前端消费者 [#274](https://github.com/Notyet1307/Exposure-Agent/issues/274)。任务状态、授权及验收回执以 Issue 为准。
- 后端分支：`feat/netflow-source-correlation-273`；原实现基线：`61f30702abf4c58d28a656fa57ab314f11306828`。main 同步 commit `bf66e7a1725034c3d288b869eceaa5ebca5a7d12` 保留既有提交身份。
- **后端源码 commit：`241a0ae5c10447292f60373bc11892d1266985cf`**。本目录的接口材料单独提交，避免把文件自身 commit 写入自身内容。
- 批准 Spec commit：`ea1ea7563c0f41dc19b4f0c6c4cc81470709b742`，包含 [EXP-NF-INT-01 N1–N8 / AC-NF-01–15](../../docs/specs/exposure-focus-release-1.md#exp-nf-int-01固定输入的-netflow-关联与人工复核材料) 与 [规范性 API 合同](../../docs/specs/netflow-correlation-api-v1.md)。这是原 `5d95f8a0a0367ac8fa4351170b5c6dd53a27cd07` 合同经维护者批准的窄修订：固定组件的五种可达状态验收及内层比较分页。完整六项材料状态词表不变。
- 固定 `netflow_processor==0.4.0` wheel 的来源、原字节 Hash 和分发授权见 [vendor 说明](../vendor/README.md)。不补造许可证。
- 生成客户端 commit：`0487125185d3b1aa17c2189329f6267e7fbcf611`，仅由原 `scripts/generate-client.sh` 更新 `frontend/src/client/{schemas,sdk,types}.gen.ts`，没有手工修改。

提交的远端可取得性、PR/CI 状态与当前授权以 [#273](https://github.com/Notyet1307/Exposure-Agent/issues/273) 最新回执为准，不推定另一台电脑已同步。阶段 C 实施和 wheel 分发授权分别见 [实施评论](https://github.com/Notyet1307/Exposure-Agent/issues/273#issuecomment-5890042266)、[分发评论](https://github.com/Notyet1307/Exposure-Agent/issues/273#issuecomment-5890071682)；[发布授权](https://github.com/Notyet1307/Exposure-Agent/issues/273#issuecomment-5903066444) 之后，[本轮窄授权](https://github.com/Notyet1307/Exposure-Agent/issues/273#issuecomment-5903483698) 另允许 main→任务分支同步及三个客户端文件的生成、提交与 CI。Spec 中阶段 B 的授权说明是当时记录，不覆盖后续明确批准；PR 合入 main、页面开发、部署、生产迁移及 Issue 关闭仍未授权。

## 导出与字节校验

| 文件 | SHA256 |
|---|---|
| `netflow-correlation-v1.openapi.json` | `963736f980b89681296bc7dfa194a0e6b300f5069f4957bdf072b7ae59c185bf` |
| `netflow-correlation-v1.examples.json` | `e71dfc96da3d5b6304b8f893cb69a5fa301d676994f5fdd738a2726d8a8d8ac4` |

OpenAPI 来自实际运行的 FastAPI `/api/v1/openapi.json`，保留完整应用的 103 条路径，而非手写或截取的假 OpenAPI；最终构建的独立 API 容器返回同一 schema。文件使用 UTF-8、键排序、两空格缩进和末尾换行。可执行：

```sh
shasum -a 256 backend/contracts/netflow-correlation-v1.openapi.json backend/contracts/netflow-correlation-v1.examples.json
```

样例包含 **34 个完整真实 HTTP 响应**及对应合成请求，全部通过对应响应 schema 校验；同时校验了 5 个声明 JSON body 的请求、1 个实际 multipart 请求和预期被拒绝的分页边界。包含实际 415 媒体类型拒绝和最终 worker 镜像发布的合法空输入。`authorization_supplied` 仅表示本次请求是否携带授权；不表示端点允许匿名。JWT、登录名/密码、数据库密码与 controller token 未导出，已做已知隔离凭据扫描。

`request_multipart.metadata` 是发送前的 JSON 对象；线路上的 `metadata` 表单字段是它的 **JSON 字符串**，不是第二个文件。`file` 是 ZIP 二进制。OpenAPI 明确声明二者必填，并以 `contentSchema` 保留 metadata 的完整约束。样例只附实际文件名、字节数、Hash 和生成出处，不内嵌 ZIP，也不虚构可供下载的 URL。实际重传返回原 Analysis，未启动重复处理。

导入被预留拒绝或 metadata 校验失败时，只清理本次请求没有持久 Artifact 收据的上传目录。事务先回滚，再取得同一 Project 锁、等待不确定的原事务结束后读取持久收据；提交回执丢失时不能仅因异常删除已归属 Analysis 的输入。实际 HTTP 冲突/坏 metadata 不再新增遗留目录，原导入结果仍可读；回归覆盖提交前失败、提交后回执丢失和调度响应丢失后的原输入保留。

## 消费者必须保持的语义

- 页面和操作固定 Project、Dataset/context、Analysis、来源版本及反馈修订。UUID 仅是本次合成环境身份，不能硬编码为生产 ID。POST 的 `Idempotency-Key` 和预期父修订来自实际用户操作；响应丢失时恢复原操作，不换 key 自动重试。
- Analysis 的 `feedback_revision_id` 指向原子发布时保留的系统空白初版，不随随后人工反馈漂移。首次反馈/任务读取可以解析当前封存版本；后续分页、筛选、详情必须传回同一个 `feedback_revision_id`。更正仍使用 `expected_parent_id`，不能用当前页隐式覆盖。
- `/addresses/{address_key}/services` 的外层对象页使用 `skip/limit`；每个对象的 `customer_comparisons`、`cloud_comparisons` 都是 `{data,count,skip,limit}` 分页信封，使用独立 `comparison_skip/comparison_limit`，默认 0/25，limit 1–100。比较保留原 `record_key`、`version_id`、`domain`，同号云图 IP/port 记录不能合并为一个键。实际 31 条客户比较分成 25/6 两页，未截断总数。
- 同 namespace 更正 context 后，旧结果和旧反馈仍按当前读权限保留；新的分析、反馈及关联确认不能继续使用旧 context，返回 409 `netflow_context_revoked`。已有幂等操作恢复与新写分开；当前撤销、权限或保留门禁仍可拒绝历史读取。
- 失败、未知、未提供、合法空和覆盖未知不能都绘制成空表。全部隔离输入实际返回 FAILED/`netflow_no_valid_records`，result 为 null；真正零 raw/valid/isolated 行已由最终 worker 镜像成功发布。只有权威 FAILED 原 Session 经显式核验后，才能请求唯一后继；普通换 key、成功或 UNKNOWN 不重算。
- 固定 0.4.0 的 confirmed declared_source 只产生五种可达材料状态，已经逐项真实观察。`MATERIAL_CONFLICT` 保留枚举，但本切片不适用，不能注入任务或弱化确认以制造该状态。字段齐全仍待人工，`review_required=true / task_closed=false / facts_changed=false`；提供方账号/时间声明与本系统实际 actor/time 分开。
- SRC 是已声明的本方位置，不是发起方、managed、监听或暴露证明。DST peers 独立；源记录数仅由 SRC 计入。缺协议/时间资格/角色保持 UNKNOWN，公网可达性为 NOT_VERIFIED。客户 XLSX v1 的单端口合同未放宽：现有 `start_port=end_port`，不因闭区间比对语义接受新的上传格式。
- 所有新读取及已定义的错误响应使用 `private, no-store`。错误体是 `{"detail":{"code":"..."}}` 或现有认证错误的字符串 detail；不能假设 422 一律是 FastAPI 的错误数组。撤权、到期、归档和跨范围错误不得用已缓存的来源事实覆盖。

## 合成验证与兼容边界

- NetFlow：真实 Dataset HTTP 接收 → 隔离 agent-compose → 固定 wheel rules worker → PostgreSQL 原子发布 → 真实 API；有记录案例为 8 条有效记录、4 源地址、5 源对象、0 candidates。candidates 为空没有丢弃源对象。最终 worker 容器的实际 image ID、Session 和环境已核验，无 MODEL_/CLOUDATLAS_ 或 OpenAI/Anthropic key 环境变量。
- 三源：客户材料是经现有上传 API 接收的合成 XLSX；新云图是明确标记的**本地预置合成已保存版本**，没有调用真实云图同步。37 个地址覆盖七个正向交集，超过一页；纯 peer 不进入主集合。不能把该验证当成实际外部同步验收。
- 导入：固定组件真实生成带独立 provider 身份的完整包及反馈，再由真实隔离 worker rules replay。原 manifest/反馈字节不改；系统空白初版与导入反馈分别追加，提供方时间声明不冒充本系统提交时间。
- legacy：准备材料时复用旧合成 publisher fixture，并模拟旧外部/控制面响应；随后关联读取全部经过真实 HTTP。所选旧 Run 的历史链接保留，旧快照没有端口时明确 `PORT_EVIDENCE_NOT_RETAINED`，不伪造端口。
- 原双端 NetFlow、Resource、GovernanceRun、Finding、报告和 ManualReview 合同不变；本接口不会生成假 Resource/Run 来承接活动对象。没有做最大容量吞吐验收，不以这组样例宣称最大上限性能。

前端页面和后续业务接入仍归前端方；本会话仅按上述单写者窄例外生成三个客户端文件，没有修改根 `bun.lock`、生成路由或开发页面。生成器重复运行无漂移，三个新增服务已通过生成 SDK→真实隔离 API→PostgreSQL 的只读合成 smoke，覆盖固定反馈分页、合法空/未提供/覆盖未知和错误反馈 UUID 的拒读；这不是浏览器验收。另一台电脑的实际 branch/base/HEAD/WIP 及最终业务集成人尚未交换，不作推定。**AC-NF-14 为 NOT_RUN；AC-NF-15 因缺真实三方材料与对应授权为 BLOCKED。** 代码审阅、自动化检查及合成运行证据不替代独立业务验收，也不代表整个前后端接入完成。
