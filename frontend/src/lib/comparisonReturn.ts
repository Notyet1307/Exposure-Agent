export const comparisonClasses = [
  "all",
  "both",
  "cloud_only",
  "customer_only",
] as const
export type ComparisonClass = (typeof comparisonClasses)[number]
export const comparisonUuid =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export type ComparisonReturn = {
  back_result?: string
  back_binding?: string
  back_class?: ComparisonClass
  back_page?: number
  back_ip?: string
  back_sort?: "ip_asc" | "ip_desc"
  back_address?: string
  back_evidence?: "customer" | "cloud"
  back_evidence_page?: number
  back_extra_page?: number
}

export function comparisonReturnFields(value: object): ComparisonReturn {
  const s = value as Record<string, unknown>
  if (typeof s.back_result !== "string" || !comparisonUuid.test(s.back_result))
    return {}
  return {
    back_result: s.back_result.toLowerCase(),
    back_binding:
      s.back_binding === "none" ||
      (typeof s.back_binding === "string" &&
        comparisonUuid.test(s.back_binding))
        ? (s.back_binding as string)
        : undefined,
    back_class: comparisonClasses.includes(s.back_class as ComparisonClass)
      ? (s.back_class as ComparisonClass)
      : undefined,
    back_page:
      Number.isSafeInteger(Number(s.back_page)) && Number(s.back_page) >= 0
        ? Number(s.back_page)
        : 0,
    back_ip:
      typeof s.back_ip === "string" && s.back_ip.length <= 45
        ? s.back_ip
        : undefined,
    back_sort: s.back_sort === "ip_desc" ? "ip_desc" : "ip_asc",
    back_evidence: s.back_evidence === "cloud" ? "cloud" : "customer",
    back_evidence_page:
      Number.isSafeInteger(Number(s.back_evidence_page)) &&
      Number(s.back_evidence_page) >= 0
        ? Number(s.back_evidence_page)
        : 0,
    back_extra_page:
      Number.isSafeInteger(Number(s.back_extra_page)) &&
      Number(s.back_extra_page) >= 0
        ? Number(s.back_extra_page)
        : 0,
    back_address:
      typeof s.back_address === "string" &&
      /^addr:[a-f0-9]{64}$/.test(s.back_address)
        ? s.back_address
        : undefined,
  }
}
