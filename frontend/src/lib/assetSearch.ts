// Decide from explicit query keys, before either view injects pagination defaults.
const historyKeys = [
  "cloud_source",
  "cloud_snapshot",
  "cloud_revision",
  "cloud_page",
  "cloud_ip",
  "cloud_asset",
  "profile_ip",
  "customer_upload",
  "customer_revision",
  "customer_page",
  "profile_cloud_page",
] as const
const syncedKeys = [
  "external_source",
  "external_domain",
  "external_version",
  "external_record",
  "external_record_version",
  "external_port_version",
  "external_ip",
  "external_root_domain",
  "external_subdomain",
  "external_status",
  "external_page",
  "external_match_page",
  "external_task",
] as const
const text = (value: unknown) => (typeof value === "string" ? value : undefined)
export const externalDomains = [
  "ip",
  "port",
  "root_domain",
  "dns",
  "subdomain",
  "cert",
  "openport",
  "web",
  "dir",
  "appfinger",
  "crawler",
  "seed_enterprise",
  "seed_keyword",
  "seed_domain",
  "seed_email",
  "seed_cert",
  "seed_icon",
  "seed_title",
] as const
export type ExternalDomain = (typeof externalDomains)[number]
const externalDomain = (value: unknown): ExternalDomain =>
  externalDomains.includes(value as ExternalDomain)
    ? (value as ExternalDomain)
    : "ip"
const number = (value: unknown) =>
  value !== undefined &&
  value !== "" &&
  Number.isSafeInteger(Number(value)) &&
  Number(value) >= 0
    ? Number(value)
    : undefined

export function historicalAssetSearch(s: Record<string, unknown>) {
  return {
    asset_view: "history" as const,
    cloud_source: text(s.cloud_source),
    cloud_snapshot: text(s.cloud_snapshot),
    cloud_revision: number(s.cloud_revision),
    cloud_page: number(s.cloud_page) ?? 0,
    cloud_ip: text(s.cloud_ip),
    cloud_asset: text(s.cloud_asset),
    profile_ip: text(s.profile_ip),
    customer_upload: text(s.customer_upload),
    customer_revision: text(s.customer_revision),
    customer_page: number(s.customer_page) ?? 0,
    profile_cloud_page: number(s.profile_cloud_page) ?? 0,
  }
}

export function syncedAssetSearch(s: Record<string, unknown>) {
  return {
    asset_view: "synced" as const,
    external_source: text(s.external_source) || undefined,
    external_domain: externalDomain(s.external_domain),
    external_version: text(s.external_version) || undefined,
    external_record: text(s.external_record) || undefined,
    external_record_version: text(s.external_record_version) || undefined,
    external_port_version: text(s.external_port_version) || undefined,
    external_ip: text(s.external_ip) || undefined,
    external_root_domain: text(s.external_root_domain) || undefined,
    external_subdomain: text(s.external_subdomain) || undefined,
    external_status: text(s.external_status) || undefined,
    external_q: text(s.external_q) || undefined,
    external_sha256: text(s.external_sha256) || undefined,
    external_md5_value: text(s.external_md5_value) || undefined,
    external_mmh3_value: text(s.external_mmh3_value) || undefined,
    external_seed_enabled:
      s.external_seed_enabled === "true"
        ? true
        : s.external_seed_enabled === "false"
          ? false
          : undefined,
    external_confidence: text(s.external_confidence) || undefined,
    external_seed_type: text(s.external_seed_type) || undefined,
    external_page: number(s.external_page) ?? 0,
    external_match_page: number(s.external_match_page) ?? 0,
    external_task: text(s.external_task) || undefined,
  }
}

export type AssetSearch = {
  cloud_source?: string
  cloud_snapshot?: string
  cloud_revision?: number
  cloud_page?: number
  cloud_ip?: string
  cloud_asset?: string
  profile_ip?: string
  customer_upload?: string
  customer_revision?: string
  customer_page?: number
  profile_cloud_page?: number
  external_source?: string
  external_domain?: ExternalDomain
  external_version?: string
  external_record?: string
  external_record_version?: string
  external_port_version?: string
  external_ip?: string
  external_root_domain?: string
  external_subdomain?: string
  external_status?: string
  external_q?: string
  external_sha256?: string
  external_md5_value?: string
  external_mmh3_value?: string
  external_seed_enabled?: boolean
  external_confidence?: string
  external_seed_type?: string
  external_page?: number
  external_match_page?: number
  external_task?: string
  asset_view?: "synced" | "history"
  asset_error?: "invalid" | "conflict"
}

export function validateAssetSearch(s: Record<string, unknown>): AssetSearch {
  const history = historyKeys.some((key) => s[key] !== undefined)
  const synced = syncedKeys.some((key) => s[key] !== undefined)
  if (
    s.asset_view !== undefined &&
    s.asset_view !== "synced" &&
    s.asset_view !== "history"
  )
    return { asset_error: "invalid" }
  if (
    (history && synced) ||
    (s.asset_view === "synced" && history) ||
    (s.asset_view === "history" && synced)
  )
    return { asset_error: "conflict" }
  const view = s.asset_view ?? (history ? "history" : "synced")
  // Keep bare intent observable after router canonicalization; component
  // selectors supply their own domain and pagination defaults.
  if (
    view === "synced" &&
    Object.keys(s).every((key) => s[key] === undefined || key === "asset_view")
  )
    return { asset_view: "synced" }
  return view === "history" ? historicalAssetSearch(s) : syncedAssetSearch(s)
}
