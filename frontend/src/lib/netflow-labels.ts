// Labels for the bounded NetFlow contract. Raw values remain in technical details.
const labels: Record<string, readonly [string, string]> = Object.setPrototypeOf(
  {
    CUSTOMER: ["Customer material", "客户材料"],
    CLOUD: ["CloudAtlas material", "云图材料"],
    NETFLOW: ["NetFlow observations", "NetFlow 观测"],
    UNKNOWN: ["Unknown; more evidence is needed", "未知，仍需补充依据"],
    CONFIRMED: ["Confirmed", "已确认"],
    CONFIRMED_LEGACY: ["Confirmed legacy scope", "已确认的旧版范围"],
    CONFLICT: ["Conflicting declarations", "声明存在冲突"],
    REVOKED: ["Revoked", "已撤销"],
    PENDING: ["Waiting to run", "等待执行"],
    RUNNING: ["Running", "正在执行"],
    SUCCEEDED: ["Analysis completed", "分析已完成"],
    SUCCEEDED_WITH_WARNINGS: [
      "Completed with coverage warnings",
      "已完成，存在覆盖警告",
    ],
    FAILED: [
      "Failed; inspect the error before retrying",
      "执行失败，请先查看错误",
    ],
    PUBLISHED: ["Published local version", "已发布的本地版本"],
    EXPIRED: ["Expired; this version cannot be read", "已到期，此版本不可读取"],
    VALID: ["Readable", "可读取"],
    VALID_NONEMPTY: ["Readable, with records", "可读取，包含记录"],
    VALID_EMPTY: ["Readable, with zero records", "可读取，记录为空"],
    NOT_PROVIDED: ["No input supplied", "未提供输入"],
    READ_FAILED: [
      "Reading failed; count is unavailable",
      "读取失败，数量不可用",
    ],
    SUFFICIENT: [
      "Coverage meets the declared conditions",
      "覆盖满足已声明条件",
    ],
    INSUFFICIENT: ["Coverage is insufficient", "覆盖不足"],
    NOT_APPLICABLE: ["Not applicable", "不适用"],
    AWAITING_FEEDBACK: ["Awaiting material", "等待补充材料"],
    MATERIAL_INCOMPLETE: ["Material is incomplete", "材料尚不齐全"],
    INVALID_MATERIAL: ["Material needs correction", "材料格式需要更正"],
    MATERIAL_CONFLICT: ["Material declarations conflict", "材料声明存在冲突"],
    AWAITING_DEPENDENCY_MATERIAL: ["Awaiting shared material", "等待共享材料"],
    FIELDS_COMPLETE_PENDING_REVIEW: [
      "Material complete; awaiting human review",
      "材料已齐全，等待人工复核",
    ],
    NOT_VERIFIED: ["Reachability has not been verified", "尚未验证可达性"],
    INSUFFICIENT_EVIDENCE: [
      "Insufficient evidence for a conclusion",
      "证据不足，不能作出结论",
    ],
    EQUAL: ["Equal", "相同"],
    DIFFERENT: ["Different", "不同"],
    IN_RANGE: ["Within the declared range", "在声明范围内"],
    OUT_OF_RANGE: ["Outside the declared range", "不在声明范围内"],
    OVERLAP: ["Time windows overlap", "时间窗重叠"],
    DISJOINT: ["Time windows do not overlap", "时间窗不重叠"],
    MATCHED: ["Observed in the selected input", "已在所选输入中观测到"],
    MISSING: ["Not supplied", "未填写"],
    NULL: ["Explicit null", "明确空值"],
    EMPTY: ["Empty value", "空值"],
    PRESENT: ["Value supplied", "已填写"],
    CANONICAL_IP_EQUAL_WITH_CONFIRMED_SCOPE: [
      "Same address in the confirmed network space",
      "在已确认网络空间内为同一地址",
    ],
    CLOUD_SELECTED_BATCH_NOT_FULL_COVERAGE: [
      "CloudAtlas covers only the selected batch, not the entire network",
      "云图仅覆盖所选批次，不代表全网",
    ],
    CUSTOMER_PROTOCOL_NOT_PROVIDED: [
      "Customer material does not supply a protocol",
      "客户材料未提供协议",
    ],
    INPUT_RECORDS_ISOLATED: [
      "Some input records were isolated during validation",
      "部分输入记录在校验时被隔离",
    ],
    INSUFFICIENT_COVERAGE: [
      "Observation coverage is insufficient",
      "观测覆盖不足",
    ],
    NO_MATCH_COVERAGE_UNKNOWN: [
      "No match; coverage is unknown, so absence cannot be inferred",
      "未命中且覆盖未知，不能据此认定不存在",
    ],
    NO_MATCH_IN_PINNED_INPUT: [
      "No match in this fixed input; this does not prove absence",
      "此固定输入未命中，不代表不存在",
    ],
    PORT_EVIDENCE_NOT_RETAINED: [
      "Port evidence was not retained",
      "未保留端口依据",
    ],
    SCOPE_UNCONFIRMED: [
      "Confirm that the selected sources describe the same network space",
      "请确认所选来源属于同一网络空间",
    ],
    SOURCE_POSITION_ONLY: [
      "Source-side position does not prove who initiated a connection or that a service listens",
      "源侧位置不能证明连接发起方或服务监听",
    ],
    SOURCE_PROTOCOL_PRESERVED: [
      "Protocol is preserved as supplied by the source",
      "协议按来源原始声明保留",
    ],
    SOURCE_ROLE_UNKNOWN: [
      "The observed endpoint's business role is unknown",
      "观测端点的业务角色未知",
    ],
    SOURCE_TIME_NOT_COMPARABLE: [
      "Source time windows cannot be compared",
      "来源时间窗不能比较",
    ],
    VIEW_UNKNOWN: ["Observation viewpoint is unknown", "观测视角未知"],
    export: ["Export and collection material", "导出与采集材料"],
    nat: ["NAT mapping material", "NAT 映射材料"],
    service: ["Service role material", "服务角色材料"],
    source: ["Source-side position material", "源侧位置材料"],
    tcp: ["TCP flags material", "TCP 标志材料"],
    coverage: ["Observation coverage material", "观测覆盖材料"],
    dataset: ["This dataset", "此数据集"],
    object: ["One observed service", "单个观测服务"],
    INPUT_RECORDS_NOT_SESSIONS: [
      "Input rows are records, not connection sessions",
      "输入行为记录，不代表连接会话",
    ],
    REACHABILITY_NOT_VERIFIED: [
      "Public reachability has not been verified",
      "尚未验证公网可达性",
    ],
    OBSERVATION_COVERAGE_NOT_COMPLETE: [
      "Observation coverage is incomplete",
      "观测覆盖不完整",
    ],
    REVERSE_TUPLES_DO_NOT_PROVE_HANDSHAKE: [
      "Reverse tuples do not prove a handshake",
      "反向元组不能证明握手成功",
    ],
    COUNTERS_NOT_RESCALED: [
      "Counters have not been rescaled for sampling",
      "计数未按采样率放大",
    ],
    SAMPLING_UNKNOWN: ["Sampling is unknown", "采样情况未知"],
    ORIGINAL_MAPPED_FORM_UNRECOVERABLE: [
      "The original address form cannot be reconstructed",
      "无法还原原始地址形式",
    ],
    SYNTHETIC_TEST_ONLY: [
      "Synthetic test material only; not customer acceptance evidence",
      "仅为合成测试材料，不代表客户验收证据",
    ],
    SOURCE_POSITION_DECLARATION_NOT_OWNERSHIP_OR_AUTHORIZATION: [
      "Source position is a declaration, not proof of ownership or authorization",
      "源侧位置声明不能证明归属或授权",
    ],
    SOURCE_COLUMN_NOT_CONNECTION_INITIATOR: [
      "The source column does not identify the connection initiator",
      "源列不能证明连接发起方",
    ],
    REVERSE_MATCHING_NOT_EVALUATED: [
      "Reverse matching was not evaluated",
      "未评估反向匹配",
    ],
    EXTERNAL_PEER_BY_CUSTOMER_DECLARATION: [
      "External peer position comes from the supplied declaration",
      "外侧对端位置来自提供方声明",
    ],
    analysis: ["Whole analysis", "整个分析"],
    candidate: ["Selected clue", "所选线索"],
    correlation_source_expired: [
      "A fixed source has expired. Select another readable version explicitly.",
      "固定来源已到期，请明确选择其他可读版本。",
    ],
    correlation_source_access_revoked: [
      "Source access has been revoked. Ask an administrator to check authorization.",
      "来源读取权限已撤销，请管理员核对授权。",
    ],
    correlation_not_found: [
      "The fixed correlation is unavailable in this project.",
      "此项目中无法读取该固定关联。",
    ],
    correlation_scope_unconfirmed: [
      "The shared network space is not confirmed.",
      "共同网络空间尚未确认。",
    ],
    INVALID_FIELD_VALUE: [
      "Correct this field's type, format or value",
      "请更正此字段的类型、格式或取值",
    ],
    INVALID_TIME_WINDOW: [
      "End time precedes start time",
      "结束时间早于开始时间",
    ],
    UNKNOWN_SAMPLING_WITH_RATE: [
      "Unknown sampling cannot declare a definite rate",
      "采样未知时不能声明确定比例",
    ],
    INVALID_SAMPLING_RATE: [
      "Sampling mode and rate disagree",
      "采样方式与比例不一致",
    ],
    DUPLICATE_MAPPING_SOURCE: [
      "A pre-NAT endpoint is declared more than once",
      "同一转换前端点被重复声明",
    ],
    PROTOCOL_PORT_MISMATCH: [
      "Ports do not match the protocol's requirements",
      "端口填写与协议要求不一致",
    ],
    NAT_MAPPING_FOR_TARGET_MISSING: [
      "No mapping covers this observed endpoint",
      "没有映射覆盖此观测端点",
    ],
    NAT_MAPPING_FOR_TARGET_AMBIGUOUS: [
      "Multiple mappings match this endpoint",
      "多个映射匹配此端点",
    ],
    NAT_MAPPING_WINDOW_DOES_NOT_COVER_TARGET: [
      "The mapping does not cover the observation window",
      "映射未覆盖观测时间窗",
    ],
    NAT_TARGET_WINDOW_UNKNOWN: [
      "Observation time is unknown; mapping coverage cannot be verified",
      "观测时间未知，无法核验映射覆盖",
    ],
    NAMESPACE_DECLARATION_CONFLICT: [
      "The declared network space conflicts with the analysis",
      "声明网络空间与分析冲突",
    ],
    DECLARED_SCOPE_CONFLICT: [
      "Supplied scope declarations conflict",
      "提供的范围声明存在冲突",
    ],
    netflow_revision_conflict: [
      "A newer version exists. Read it before appending a correction.",
      "已有较新版本，请先读取后再追加更正。",
    ],
    netflow_key_conflict: [
      "This operation key already identifies another request. Query the original operation.",
      "此操作标识已绑定其他请求，请查询原操作。",
    ],
    netflow_context_revoked: [
      "The processing context is no longer authorized. Ask an Admin to confirm a new version.",
      "处理上下文已失效，请管理员确认新版本。",
    ],
    netflow_context_invalid: [
      "The processing context does not match these fixed inputs.",
      "处理上下文与固定输入不匹配。",
    ],
    netflow_context_admin_required: [
      "Only an Admin can confirm a processing context.",
      "仅管理员可确认处理上下文。",
    ],
    netflow_write_forbidden: [
      "Your role cannot make this change.",
      "当前角色无权执行此更改。",
    ],
    netflow_input_not_found: [
      "The fixed input is unavailable in this project.",
      "此项目中无法读取该固定输入。",
    ],
    netflow_analysis_not_found: [
      "The fixed analysis is unavailable in this project.",
      "此项目中无法读取该固定分析。",
    ],
    netflow_analysis_not_ready: [
      "Analysis is not ready. Query the original operation; do not start a duplicate.",
      "分析尚未就绪，请查询原操作，不要重复启动。",
    ],
    netflow_artifact_integrity_failed: [
      "Material integrity verification failed. Stop and ask an administrator to investigate.",
      "材料完整性校验失败，请停止操作并联系管理员核查。",
    ],
    netflow_artifact_schema_invalid: [
      "The submitted fields do not match the required format.",
      "提交字段不符合规定格式。",
    ],
  },
  null,
)

export function netflowText(
  value: string,
  t: (en: string, zh: string) => string,
): string {
  const pair = labels[value] ?? labels[value.toUpperCase()]
  if (pair) return t(...pair)
  if (value.includes("+") && value.split("+").every((part) => labels[part]))
    return value
      .split("+")
      .map((part) => netflowText(part, t))
      .join(" + ")
  return value
}
