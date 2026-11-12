export type EvidenceSource = "customer" | "cloud"

export type EvidencePageSearch = {
  core_customer_page?: number
  core_cloud_page?: number
  core_evidence?: EvidenceSource
  core_evidence_page?: number
}

export type EvidencePages = {
  customer: number
  cloud: number
}

export const comparisonPageSize = 25
export const comparisonPageMax = Math.floor(
  Number.MAX_SAFE_INTEGER / comparisonPageSize,
)

export const emptyEvidencePages = {
  core_customer_page: 0,
  core_cloud_page: 0,
  core_evidence_page: 0,
} as const

export function resolveEvidencePages(
  search: EvidencePageSearch,
): EvidencePages {
  const selected = search.core_evidence === "cloud" ? "cloud" : "customer"
  const legacy = search.core_evidence_page ?? 0
  return {
    customer:
      search.core_customer_page ?? (selected === "customer" ? legacy : 0),
    cloud: search.core_cloud_page ?? (selected === "cloud" ? legacy : 0),
  }
}

export function evidencePagePatch(
  search: EvidencePageSearch,
  source: EvidenceSource,
  page: number,
) {
  const pages = { ...resolveEvidencePages(search), [source]: page }
  return {
    core_customer_page: pages.customer,
    core_cloud_page: pages.cloud,
    core_evidence_page: 0,
  }
}
