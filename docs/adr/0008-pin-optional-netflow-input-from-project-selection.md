# ADR-0008：从 Project 当前选择固定可选 NetFlow 输入

状态：已接受

日期：2026-09-04

## 背景

GovernanceRun 目前由 API 先保留启动资格，再由 Runner 在实际开始执行时建立；CustomerUpload、CloudAtlas 绑定、处理合同和 Runner 版本均随 Run 固定。可选 NetFlow 输入必须沿用这条时序，不能让尚未启动的请求成为 GovernanceRun，也不能让 Retry 静默取得新输入。

可选输入还必须区分“新合同明确没有 NetFlow”“存在一个零记录 Dataset”和“历史 Run 当时尚未建模 NetFlow”。把三者都表示成空值会重写历史含义，并把没有提供数据误报为已经观测到零条流量。

## 决策

Project 保存一个可为空的当前 NetFlowDataset 选择。普通 Trigger 和 Run Rerun 不接收显式 `dataset_id`，也不提供覆盖 Project 当前选择的参数；它们读取各自发起时的 Project 当前选择。选择为空是新输入合同下明确的 absent，选择非空是 present。

API 只在 Project 上建立 launch reservation，固定 Trigger ID、agent-compose control Run identity 和输入 Hash，然后请求 agent-compose 启动 Runner；API 不创建 GovernanceRun。Runner 实际开始后重新验证 Project 当前选择和全部固定输入，验证成功才创建 GovernanceRun，并原子清除对应 reservation。验证失败、选择漂移、控制面状态未知或 reservation 不匹配时均 fail closed，不创建业务 Run。

## 输入状态与持久表示

新 Run 使用输入合同 `governance-run-input-v1`，并固定输入合同版本和输入 Hash：

- **explicit absent**：输入合同为 `governance-run-input-v1`，NetFlowDataset ID、内容 Hash 和 Dataset 合同版本均为空；
- **present**：输入合同为 `governance-run-input-v1`，NetFlowDataset ID、内容 Hash 和 Dataset 合同版本均非空；
- **legacy / unmodeled**：历史 Run 的输入合同版本、输入 Hash 和 NetFlow 固定字段均为空，表示该 Run 建立时尚未建模可选 NetFlow 输入，不表示 absent。

NetFlow 固定字段只能全空或全非空，部分为空是非法状态。历史 Run 不回填输入合同、输入 Hash、NetFlowDataset 引用、NETFLOW SourceSnapshot 或派生事实。

Project 的当前选择是可变配置，不是历史 Run 事实。GovernanceRun 一旦建立，其输入合同、输入 Hash、NetFlow absent/present 状态、Dataset ID、内容 Hash 和 Dataset 合同版本均为不可变固定事实；发布后继续遵守已发布事实不可变约束。

## Canonical 输入与 Hash

输入 Hash 是下列 payload 经 canonicalization 后的 UTF-8 字节所计算的 lowercase SHA-256。以下 JSON Schema 是规范性字段合同；所有层级都拒绝未列出的字段，所有 `required` 字段都必须出现。`processing_contract_version` 和 `report_contract_version` 即使为空也必须显式写为 JSON `null`，`netflow` 即使 absent 也必须显式写为 JSON `null`，不能省略键。

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["contract_version", "project_id", "customer_upload", "cloudatlas", "netflow", "runner"],
  "properties": {
    "contract_version": {"const": "governance-run-input-v1"},
    "project_id": {"type": "string", "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},
    "customer_upload": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "content_sha256", "profile_id", "profile_version"],
      "properties": {
        "id": {"type": "string", "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},
        "content_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "profile_id": {"type": "string", "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},
        "profile_version": {"type": "integer", "minimum": 1}
      }
    },
    "cloudatlas": {
      "type": "object",
      "additionalProperties": false,
      "required": ["source_instance_id", "validated_fingerprint", "capset_id", "method", "package_sha256", "descriptor_sha256"],
      "properties": {
        "source_instance_id": {"type": "string", "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},
        "validated_fingerprint": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "capset_id": {"type": "string", "minLength": 1},
        "method": {"type": "string", "minLength": 1},
        "package_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "descriptor_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}
      }
    },
    "netflow": {
      "oneOf": [
        {"type": "null"},
        {
          "type": "object",
          "additionalProperties": false,
          "required": ["dataset_id", "content_sha256", "dataset_contract_version"],
          "properties": {
            "dataset_id": {"type": "string", "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},
            "content_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "dataset_contract_version": {"type": "string", "minLength": 1}
          }
        }
      ]
    },
    "runner": {
      "type": "object",
      "additionalProperties": false,
      "required": ["build_version", "processing_contract_version", "report_contract_version"],
      "properties": {
        "build_version": {"type": "string", "minLength": 1},
        "processing_contract_version": {"type": ["string", "null"], "minLength": 1},
        "report_contract_version": {"type": ["string", "null"], "minLength": 1}
      }
    }
  }
}
```

Explicit absent 的完整 canonical payload 示例：

```json
{"cloudatlas":{"capset_id":"cloudatlas-read","descriptor_sha256":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd","method":"cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets","package_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","source_instance_id":"44444444-4444-4444-8444-444444444444","validated_fingerprint":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},"contract_version":"governance-run-input-v1","customer_upload":{"content_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","id":"22222222-2222-4222-8222-222222222222","profile_id":"33333333-3333-4333-8333-333333333333","profile_version":1},"netflow":null,"project_id":"11111111-1111-4111-8111-111111111111","runner":{"build_version":"runner-v1","processing_contract_version":"ip-v1","report_contract_version":null}}
```

该示例 payload 的 SHA-256 必须是 `0dc5f48d13f4bd65e1b9592a094792c967ef854002b6f78333f30ad2a307b229`。

Present 时，`netflow` 值必须是以下完整对象；canonical payload 中该对象的键也保持排序，其余层级和字段与上例相同：

```json
{"content_sha256":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","dataset_contract_version":"netflow-dataset-v1","dataset_id":"55555555-5555-4555-8555-555555555555"}
```

Canonicalization 递归按 Unicode code point 对对象键排序，数组保持原顺序，使用紧凑分隔符 `,` 和 `:`，不转义非 ASCII 字符，UUID 必须使用上述小写连字符形式，整数使用 JSON number，空值使用 JSON `null`；编码结果不得带 BOM、前导或尾随空白。

Trigger ID、请求人、agent-compose Session ID 和时间戳属于执行身份或元数据，不进入输入 Hash。同一 Project、同一 Trigger ID 的未完成 reservation 只能接受相同合同版本和输入 Hash；不匹配必须拒绝，不能重新固定。GovernanceRun 建立后，同一 Trigger ID 始终定位原 Run，即使 Project 当前选择已经变化。

## PinnedTriggerInputs seam

深化现有 `PinnedTriggerInputs` module，而不是增加通用来源选择层或逐 Trigger 覆盖层。它的 typed canonical 表示是 launch reservation Hash、Runner 输入、GovernanceRun 固定字段和 Retry 重建的唯一来源；Hash 与传给 Runner 的值不得由两套逻辑分别生成。

Runner 必须从 typed 输入重新生成 canonical 表示并校验 Hash，不能只信任调用方传入的 Hash。report contract 必须进入同一固定输入，避免跨部署重放时在相同 reservation 下改变输出合同。

## 竞态与幂等

选择 NetFlowDataset、Trigger 和 Rerun 均通过 Project 行锁串行读取或修改当前选择。reservation 提交后、GovernanceRun 建立前，当前选择仍可能发生变化；Runner 的二次验证必须检测该变化并 fail closed。GovernanceRun 建立后，Project 当前选择的后续变化永不修改正在执行或历史 Run 的固定事实，但会按现有 current-input 不变门禁影响最新失败 Run 是否仍具备 Retry 资格。

PostgreSQL 的 Project 单活跃 GovernanceRun 约束继续兜底。控制面响应丢失时，相同 Trigger ID 只能恢复相同 reservation 或定位已经建立的原 Run，不能根据新的 Project 当前选择替换输入。未知 agent-compose 状态继续按 ADR-0004 fail closed。

## Retry 与 Rerun

输入合同为 `governance-run-input-v1` 的 Run Retry 只从原 GovernanceRun 重建固定输入，沿用同一 Run、Trigger ID 和 agent-compose Session。它绝不从 Project 当前选择取得替代 Dataset，也不把 present 降级为 absent。Project 当前 NetFlowDataset 选择与原 Run 不同，或原 Dataset、内容 Hash、Dataset 合同版本无法重新验证时，Retry 必须拒绝；需要使用当前新输入时必须 Rerun。

Legacy / unmodeled Run Retry 继续走既有双来源 pinned/retry 路径：不校验并不存在的 v1 输入 Hash，不读取或固定 NetFlow，也不因 Project 当前 NetFlowDataset 选择变化而改变历史语义或 Retry 资格。既有的 CustomerUpload、CloudAtlas、Runner build、processing/report contract、最新 Run 和原 Session 可恢复门禁全部保持。

Run Rerun 使用新的 Trigger ID、GovernanceRun 和 agent-compose Session，并读取 Rerun 发起时的 Project 当前选择。因此 Rerun 可以从 absent 变为 present、从 present 变为 absent，或选择另一个 Dataset；旧 Run 的固定输入保持不变。

## 无 NetFlow 的双来源语义

`governance-run-input-v1` 明确 absent 时，不创建 NetFlow RunStep、NETFLOW SourceSnapshot、NetFlow Observation 或任何伪造的空 Artifact。该 Run 继续执行既有 CustomerUpload 与 CloudAtlas 的双来源 v1 对账语义；成功发布仍进入 `COMPLETED`，Finding 的生成和关闭语义不因 NetFlow 缺失而变化。

present 的 NetFlowDataset 即使包含零条记录，也必须产生 `record_count = 0` 的 NETFLOW SourceSnapshot。它表示完整读取了一个存在的 Dataset，与 explicit absent 不同。后续支持 present 输入时，Publish 的完整输入集合是既有双来源加条件性的 NETFLOW，而不是无条件要求三份 Snapshot；客户可见事实仍由一次原子 Publish 提交。

本 ADR 不接受 `report-v2`，不决定三来源报告展示、Lineage 投影、Dataset 格式细节或三来源 Finding 规则。这些能力仍须分别获得接受的决策与 Delivery Spec。

## 范围与执行门禁

本 ADR 的“已接受”表示 #164 的研究决策已经接受，可以作为后续候选设计的约束；它不等于任何 R1 候选已经通过独立 Admission，不授予任何 R1 Issue 可执行标签，也不授权生产实现或迁移。R1 只有在其 Delivery Spec 和依赖分别通过独立 Admission 后才可执行。

## 被拒方案

### Trigger 显式 Dataset 参数

拒绝在 Trigger 或 Rerun 请求中传入 `dataset_id`。它会扩大人工、API 和计划触发的接口，并要求为“相同 Idempotency-Key、不同 Dataset 参数”增加新的请求绑定规则；现有相同 Trigger ID 定位原 Run 的接口已经足够。

### 显式参数覆盖 Project 当前选择

拒绝同时保留 Project 当前选择和逐 Trigger 覆盖。两套输入来源需要额外优先级、审计和竞态规则，却没有已确认的逐 Run override 需求。

## 后果

Project 需要可选择和清除当前 NetFlowDataset。选择或清除永不修改既有 GovernanceRun 的固定输入；但对输入合同为 `governance-run-input-v1` 的最新失败 Run，它会按 current-input 不变门禁影响 Retry 资格，需要使用新的当前选择时必须 Rerun。新 Run 必须保存输入合同、输入 Hash 和条件性的 NetFlow 固定字段，并把这些字段纳入既有 GovernanceRun 不可变保护。迁移只增加可空的兼容字段与合法组合约束，不更新历史行。

该选择保持 Trigger 接口小而稳定，把选择解析、合同、Hash、传输、Runner 校验和 Retry 重建集中在现有 seam；代价是 Project 当前选择在 Runner 建立 Run 前变化时，本次启动会安全失败并要求使用新 Trigger 重试。
