import type { app__domain__comparison_results__Readiness } from "@/client"

type Translate = (english: string, chinese: string) => string
export type ReadinessState = app__domain__comparison_results__Readiness["state"]

// One entry per generated state keeps a new readiness state a build error.
const READINESS_TEXT: Record<ReadinessState, [string, string]> = {
  READY: [
    "The applied customer register and published CloudAtlas data are ready.",
    "已应用客户台账和已发布云图资料可用于生成结果。",
  ],
  SCOPE_REQUIRED: [
    "Confirm the network namespace and comparable scope for these materials.",
    "请确认这些资料的网络空间与可比范围。",
  ],
  SCOPE_CONFIRMATION_REQUIRED: [
    "These exact input versions need a same-space confirmation.",
    "这些明确版本需要同空间确认。",
  ],
  CUSTOMER_NOT_READY: [
    "Apply a customer register version first.",
    "请先明确应用客户资产台账版本。",
  ],
  CLOUD_NOT_READY: [
    "This scope has no published, readable CloudAtlas IP/port data.",
    "此范围尚无已发布且可读的云图 IP／端口资料。",
  ],
  INSUFFICIENT_COVERAGE: [
    "Coverage is incomplete. Known records can be read, but full-scope difference statistics are unavailable.",
    "覆盖不足。可阅读已知记录，但不能提供全范围差异统计。",
  ],
  EXPIRED: [
    "The required data has expired. Prepare an authorized published version explicitly.",
    "所需资料已到期，请明确准备获准的已发布版本。",
  ],
  ACCESS_DENIED: [
    "Data access is denied. The result is not an empty set.",
    "资料读取被拒绝，不能将其视为空集。",
  ],
  READ_FAILED: [
    "The data could not be read. Check its fixed version and retry.",
    "无法读取资料，请核对固定版本后重试。",
  ],
  MULTIPLE_SCOPES: [
    "Choose one comparable source or scope.",
    "请选择一个可比的来源或范围。",
  ],
  METADATA_UNAVAILABLE: [
    "Update status could not be confirmed. This does not change the fixed result.",
    "暂无法确认资料更新状态，固定结果保持不变。",
  ],
}

export function readinessText(
  state: ReadinessState | undefined,
  t: Translate,
): string {
  return state
    ? t(...READINESS_TEXT[state])
    : t("Reading material status…", "正在读取资料状态…")
}
