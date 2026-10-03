import { useQuery, useQueryClient } from "@tanstack/react-query"
import { getRouteApi, Link } from "@tanstack/react-router"
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react"
import { z } from "zod"

import {
  ExternalAssetsService as API,
  ApiError,
  type ExternalRecordPublic,
  type ExternalSourcePublic,
  type ExternalSyncPublic,
  type ExternalVersionPublic,
} from "@/client"
import { ResultPagination } from "@/components/ResultPagination"
import { TechnicalValue } from "@/components/TechnicalValue"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { externalDomains, syncedAssetSearch } from "@/lib/assetSearch"
import { useI18n } from "@/lib/i18n"

const SIZE = 25
const selectClass =
  "w-full min-w-0 rounded-md border bg-background px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ring"
const panelClass =
  "left-auto right-0 top-0 h-dvh max-h-dvh w-full max-w-full translate-x-0 translate-y-0 grid-rows-[auto_auto_minmax(0,1fr)] gap-0 rounded-none p-0 sm:rounded-none motion-reduce:animate-none [&>div:first-child]:px-4 [&>div:first-child]:pt-3 [&>div:first-child]:pr-12"
type Domain = ExternalVersionPublic["domain"]
const domains: readonly Domain[] = externalDomains

const profileDomains: Record<
  ExternalSourcePublic["capability_profile"],
  Domain
> = {
  "assets-v1": "ip",
  "root-domains-v1": "root_domain",
  "dns-v1": "dns",
  "subdomain-v1": "subdomain",
  "cert-v1": "cert",
  "openport-v1": "openport",
  "web-v1": "web",
  "dir-v1": "dir",
  "appfinger-v1": "appfinger",
  "crawler-v1": "crawler",
  "seed-enterprise-v1": "seed_enterprise",
  "seed-keyword-v1": "seed_keyword",
  "seed-domain-v1": "seed_domain",
  "seed-email-v1": "seed_email",
  "seed-cert-v1": "seed_cert",
  "seed-icon-v1": "seed_icon",
  "seed-title-v1": "seed_title",
}
const sourceDomain = (
  profile: ExternalSourcePublic["capability_profile"] | undefined,
): Domain => (profile ? profileDomains[profile] : "ip")

const supportsDomain = (source: ExternalSourcePublic, domain: Domain) =>
  sourceDomain(source.capability_profile) === domain ||
  (source.capability_profile === "assets-v1" && domain === "port")

const hasErrorCode = (error: unknown, code: string) =>
  error instanceof ApiError &&
  typeof error.body === "object" &&
  error.body !== null &&
  "detail" in error.body &&
  typeof error.body.detail === "object" &&
  error.body.detail !== null &&
  "code" in error.body.detail &&
  error.body.detail.code === code

const categories = [
  {
    en: "Assets",
    zh: "资产",
    items: [
      ["ip", "IP", "IP"],
      ["root_domain", "Root domains", "主域名"],
      ["dns", "Subdomains / DNS", "子域名 / DNS"],
      ["subdomain", "Subdomain intelligence", "子域名情报"],
      ["cert", "Certificates", "证书"],
    ],
  },
  {
    en: "Exposure",
    zh: "暴露面",
    items: [
      ["port", "Port services", "端口服务"],
      ["openport", "Open ports", "开放端口"],
      ["web", "Websites", "网站实体"],
      ["dir", "Website paths", "网站路径"],
      ["appfinger", "Website fingerprints", "网站指纹"],
      ["crawler", "Crawler data", "爬虫数据"],
    ],
  },
  {
    en: "Discovery seeds (read only)",
    zh: "发现种子（只读）",
    items: [
      ["seed_enterprise", "Enterprises", "企业主体"],
      ["seed_keyword", "Keywords", "关键词"],
      ["seed_domain", "Domain WHOIS", "域名 WHOIS"],
      ["seed_email", "Email domains", "邮箱域名"],
      ["seed_cert", "Certificate information", "证书信息"],
      ["seed_icon", "Website icons", "网站图标"],
      ["seed_title", "Website titles", "网站标题"],
    ],
  },
] as const

function AssetDirectory({
  selected,
  source,
  versionId,
  counts,
  onSelect,
}: {
  selected: string
  source: ExternalSourcePublic | undefined
  versionId: string | undefined
  counts: Record<string, ExternalVersionPublic>
  onSelect: (category: string) => void
}) {
  const { t } = useI18n()
  const countFor = (id: string) => {
    const domain = domains.find((item) => item === id)
    if (!domain) return t("Not integrated", "未接入")
    if (!source) return t("Not configured", "未配置")
    if (!source.data_access_enabled) return t("Unavailable", "不可用")
    if (!supportsDomain(source, domain)) return t("Not set", "未配置")
    const version = counts[`${source.id}:${domain}`]
    if (
      !version ||
      (domain === selected && versionId && version.id !== versionId)
    )
      return t("Not read", "未读取")
    return version.complete
      ? String(version.record_count)
      : t(
          `${version.record_count} (partial)`,
          `${version.record_count}（部分）`,
        )
  }
  const countTitle = (id: string) => {
    const domain = domains.find((item) => item === id)
    if (
      domain &&
      source?.data_access_enabled &&
      !supportsDomain(source, domain)
    )
      return t(
        "Not configured for the current source.",
        "当前来源未配置此类型。",
      )
    return t(
      "Counts belong to the selected source and fixed version only; they do not change with local filters.",
      "计数仅属于选定来源和固定版本，不随本地筛选变化。",
    )
  }
  const items = (group: (typeof categories)[number]) => (
    <div className="mt-2 space-y-1">
      {group.items.map(([id, en, zh]) => (
        <button
          key={id}
          type="button"
          aria-current={id === selected ? "page" : undefined}
          className={`flex w-full items-center justify-between gap-2 rounded px-3 py-2 text-left text-sm focus-visible:outline-2 focus-visible:outline-ring ${id === selected ? "bg-accent font-medium text-accent-foreground" : "hover:bg-muted"}`}
          onClick={() => onSelect(id)}
        >
          <span>{t(en, zh)}</span>
          <span
            className="text-xs text-muted-foreground"
            title={countTitle(id)}
          >
            {countFor(id)}
          </span>
        </button>
      ))}
    </div>
  )
  return (
    <>
      <div className="space-y-1 md:hidden">
        <Label htmlFor="external-domain">{t("Asset domain", "资产域")}</Label>
        <select
          id="external-domain"
          className={selectClass}
          value={selected}
          onChange={(event) => onSelect(event.target.value)}
        >
          {categories.map((group) => (
            <optgroup key={group.en} label={t(group.en, group.zh)}>
              {group.items.map(([id, en, zh]) => (
                <option key={id} value={id}>
                  {t(en, zh)}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </div>
      <nav
        aria-label={t("Asset categories", "资产分类")}
        className="hidden space-y-5 border-r pr-3 md:block"
      >
        {categories.slice(0, 2).map((group) => (
          <section key={group.en}>
            <h2 className="px-3 text-xs font-medium text-muted-foreground">
              {t(group.en, group.zh)}
            </h2>
            {items(group)}
          </section>
        ))}
        <details>
          <summary className="cursor-pointer px-3 text-xs font-medium text-muted-foreground">
            {t(categories[2].en, categories[2].zh)}
          </summary>
          {items(categories[2])}
        </details>
      </nav>
    </>
  )
}

const Route = getRouteApi("/_layout/projects/$projectId/cloudatlas-ledger")

const intentSchema = z.object({
  key: z.string().uuid(),
  source: z.string().uuid(),
  body: z.object({
    page_size: z.number().int().min(1).max(200),
    max_pages: z.number().int().min(1).max(10000),
    max_records: z.number().int().min(1).max(1000000),
    max_response_bytes: z.number().int().min(1).max(16777216),
    timeout_seconds: z.number().int().min(1).max(300),
    retain_until: z.string().datetime({ offset: true }),
  }),
})
type Intent = z.infer<typeof intentSchema>

function Status({ value }: { value: string }) {
  const { t } = useI18n()
  const names: Record<string, string> = {
    PENDING: t("Pending", "等待执行"),
    RUNNING: t("Running", "执行中"),
    UNKNOWN: t("Unknown — reconciliation required", "未知 — 需显式核对"),
    SUCCEEDED: t("Succeeded", "已成功"),
    PARTIAL_SUCCEEDED: t("Batch completed — not full", "批次完成 — 非全量"),
    PARTIAL_FAILED: t("Partially failed", "部分失败"),
    FAILED: t("Failed", "失败"),
    PUBLISHED: t("Published version", "已发布版本"),
    EXPIRED: t("Expired — data unavailable", "已到期 — 数据不可读"),
  }
  return (
    <span className="rounded border px-2 py-1 text-xs">
      {names[value] ?? value}
    </span>
  )
}

// Values are escaped text, never HTML or source URLs. Absence is not null or empty.
function FieldValue({ value }: { value: unknown }) {
  const { t } = useI18n()
  if (value === undefined)
    return <span className="text-muted-foreground">{t("Missing", "缺失")}</span>
  if (value === null)
    return (
      <span className="text-muted-foreground">{t("Null", "空值 null")}</span>
    )
  if (value === "")
    return (
      <span className="text-muted-foreground">
        {t("Empty string", "空字符串")}
      </span>
    )
  if (Array.isArray(value))
    return value.length ? (
      <ul className="space-y-2 border-l pl-3">
        {value.map((item, index) => (
          <li key={index}>
            <FieldValue value={item} />
          </li>
        ))}
      </ul>
    ) : (
      <span className="text-muted-foreground">
        {t("Empty array", "空数组")}
      </span>
    )
  if (typeof value === "object")
    return (
      <dl className="space-y-1">
        {Object.entries(value).map(([key, item]) => (
          <div key={key} className="min-w-0">
            <dt className="font-medium">
              {key === "source"
                ? t("Source", "来源")
                : key === "reason"
                  ? t("Reason", "原因")
                  : key === "factor"
                    ? t("Factor", "依据")
                    : key}
            </dt>
            <dd className="pl-3">
              <FieldValue value={item} />
            </dd>
          </div>
        ))}
      </dl>
    )
  return (
    <span className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
      {String(value)}
    </span>
  )
}

const property = (value: unknown, key: string): unknown =>
  value !== null && typeof value === "object" ? Reflect.get(value, key) : value
const names = (value: unknown) =>
  Array.isArray(value)
    ? value.map((item) => property(item, "name"))
    : property(value, "name")

const structuredFields: Record<string, string[]> = {
  subdomain: ["subdomain", "source_name", "reason", "status"],
  cert: [
    "cn_name",
    "o_name",
    "ou_name",
    "email_name",
    "subject",
    "issuer",
    "serial_number",
    "sha256",
    "sha1",
    "md5",
    "start_date",
    "end_date",
    "trusted",
    "sources",
    "status",
  ],
  openport: ["ip", "port", "protocol"],
  web: [
    "url",
    "scheme",
    "hostname",
    "netloc",
    "port",
    "ip",
    "entity",
    "bu",
    "tags",
    "status",
  ],
  dir: [
    "url",
    "path",
    "scheme",
    "hostname",
    "netloc",
    "port",
    "ip",
    "ip_info",
    "bu",
    "tags",
    "apps",
    "level",
    "status",
    "status_code",
    "title",
    "render_title",
    "server",
    "x_powered_by",
    "location",
    "content_type",
    "content_lines",
    "content_words",
    "content_length",
    "body_md5_hash",
    "icon_url",
    "icon_mmh3_hash",
    "icon_md5_hash",
    "isadmin",
    "screenshot_link",
  ],
  appfinger: [
    "url",
    "scheme",
    "hostname",
    "netloc",
    "path",
    "port",
    "product_name",
    "product_uuid",
    "vendor",
    "vendor_uuid",
    "version",
    "cpe",
    "bu",
    "tags",
    "status",
  ],
  crawler: [
    "target",
    "hostname",
    "uri",
    "path",
    "method",
    "request_type",
    "source",
    "status",
  ],
  seed_enterprise: [
    "name",
    "credit_code",
    "legal_person",
    "reg_capital",
    "reg_date",
    "address",
    "industry",
    "scope",
    "status",
    "enable",
    "confidence",
    "equity",
    "investment_path",
    "is_history",
  ],
  seed_keyword: ["name", "type", "enable", "confidence"],
  seed_domain: ["name", "type", "enable", "confidence"],
  seed_email: ["name", "enable", "confidence"],
  seed_cert: ["name", "type", "enable", "confidence"],
  seed_icon: ["icon_url", "md5_value", "mmh3_value", "enable", "confidence"],
  seed_title: ["name", "type", "enable", "confidence"],
}

function RecordFields({
  record,
  domain,
}: {
  record: ExternalRecordPublic
  domain: string
}) {
  const { t } = useI18n()
  const groups: [string, string[]][] = structuredFields[domain]
    ? [
        [
          t("Structured source fields", "结构化来源字段"),
          structuredFields[domain],
        ],
      ]
    : domain === "dns"
      ? [
          [
            t("DNS record", "解析记录"),
            ["subdomain", "domain", "rdtype", "record", "status"],
          ],
          [t("Groups and tags", "分组与标签"), ["bu", "tags"]],
        ]
      : domain === "root_domain"
        ? [
            [
              t("Domain", "域名信息"),
              ["root_domain", "status", "valid_subdomain"],
            ],
            [
              t("Source-claimed ICP", "源声明备案"),
              ["icp_official_name", "icp_num", "icp_date"],
            ],
            [
              t("Source-claimed WHOIS", "源声明 WHOIS"),
              ["whois_registrant", "whois_email", "whois_expiration_time"],
            ],
            [t("Source observations", "来源观测"), ["sources"]],
          ]
        : domain === "ip"
          ? [
              [
                t("Asset information", "资产信息"),
                ["ip", "version", "status", "bu", "tags"],
              ],
              [
                t("Network and location", "网络与地理"),
                [
                  "provider",
                  "as_name",
                  "as_num",
                  "subnet",
                  "location",
                  "country",
                  "province",
                  "city",
                ],
              ],
              [
                t("Source-reported live ports", "来源报告存活端口数"),
                ["live_port"],
              ],
              [t("Source observations", "来源观测"), ["sources"]],
            ]
          : [
              [
                t("Service", "服务信息"),
                [
                  "ip",
                  "port",
                  "protocol",
                  "service",
                  "product",
                  "version",
                  "tunnel",
                  "status",
                ],
              ],
              [t("Groups and tags", "分组与标签"), ["bu", "tags"]],
              [
                t("Banner and categories", "Banner 与分类"),
                ["banner", "categories"],
              ],
            ]
  groups.push([
    t("Source times", "源时间"),
    ["created_at", "updated_at", "lastseen_at"],
  ])
  const labels: Record<string, string> = {
    id: t("Source record ID", "源记录 ID"),
    ip: "IP",
    status: t("Source status", "源状态"),
    bu: t("Business group", "业务分组"),
    tags: t("Source tags", "源标签"),
    created_at: t("Source created time", "源创建时间"),
    updated_at: t("Source updated time", "源更新时间"),
    lastseen_at: t("Source last-seen time", "源最近发现时间"),
    version:
      domain === "ip"
        ? t("IP version", "IP 版本")
        : t("Product version", "产品版本"),
    subnet: t("Subnet", "子网"),
    live_port: t("Live ports", "存活端口"),
    provider: t("Provider", "提供商"),
    as_name: t("AS name", "AS 名称"),
    as_num: t("AS number", "AS 编号"),
    location: t("Location", "位置"),
    country: t("Country", "国家"),
    province: t("Province", "省份"),
    city: t("City", "城市"),
    sources: t("Source observations", "来源观测属性"),
    port: t("Port", "端口"),
    protocol: t("Protocol", "协议"),
    service: t("Service", "服务"),
    tunnel: t("Tunnel", "隧道"),
    product: t("Product", "产品"),
    banner: "Banner",
    categories: t("Categories", "分类"),
    root_domain: t("Root domain", "主域名"),
    domain: t("Source-claimed root domain", "源声明主域名"),
    subdomain: t("Subdomain", "子域名"),
    rdtype: t("Record type", "解析类型"),
    record: t("Record value", "解析值"),
    icp_date: t("Source-claimed ICP date", "源声明备案时间"),
    icp_num: t("Source-claimed ICP number", "源声明备案号"),
    icp_official_name: t("Source-claimed ICP organization", "源声明备案主体"),
    whois_registrant: t(
      "Source-claimed WHOIS registrant",
      "源声明 WHOIS 注册主体",
    ),
    whois_email: t("Source-claimed WHOIS email", "源声明 WHOIS 邮箱"),
    whois_expiration_time: t(
      "Source-claimed WHOIS expiration",
      "源声明 WHOIS 有效期",
    ),
    valid_subdomain: t(
      "Source-reported valid subdomains",
      "来源报告有效子域名数",
    ),
  }
  return (
    <div className="space-y-3">
      {groups.map(([title, fields]) => (
        <section key={title} className="min-w-0 space-y-3">
          <h3 className="border-b pb-2 font-medium">{title}</h3>
          <dl className="grid min-w-0 gap-4 sm:grid-cols-2">
            {fields.map((field) => (
              <div
                className={`min-w-0 ${["sources", "banner", "record", "categories"].includes(field) ? "sm:col-span-2" : ""}`}
                key={field}
              >
                <dt className="mb-1 text-sm text-muted-foreground">
                  {labels[field] ?? field}
                </dt>
                <dd className="min-w-0 text-sm">
                  {field === "sources" &&
                  Array.isArray(record.fields.sources) &&
                  record.fields.sources.length ? (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>{t("Source", "来源")}</TableHead>
                          <TableHead>{t("Reason", "原因")}</TableHead>
                          <TableHead>{t("Factor", "依据")}</TableHead>
                          {domain === "ip" && (
                            <TableHead>
                              {t("Source last-seen time", "源最近发现时间")}
                            </TableHead>
                          )}
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {record.fields.sources.map((observation, index) => (
                          <TableRow key={index}>
                            {[
                              "source",
                              "reason",
                              "factor",
                              ...(domain === "ip" ? ["lastseen_at"] : []),
                            ].map((key) => (
                              <TableCell
                                key={key}
                                className="max-w-64 whitespace-normal align-top"
                              >
                                <FieldValue
                                  value={property(observation, key)}
                                />
                              </TableCell>
                            ))}
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  ) : (
                    <div
                      className={
                        field === "banner" || field === "record"
                          ? "max-h-80 overflow-auto rounded border p-3"
                          : undefined
                      }
                    >
                      <FieldValue
                        value={
                          field === "bu" || field === "tags"
                            ? names(record.fields[field])
                            : record.fields[field]
                        }
                      />
                    </div>
                  )}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      ))}
      <details className="rounded border p-3">
        <summary className="cursor-pointer font-medium">
          {t("Technical trace", "技术追溯")}
        </summary>
        <dl className="mt-3 grid gap-3 sm:grid-cols-2">
          <div>
            <dt>{labels.id}</dt>
            <dd>
              <FieldValue value={record.fields.id} />
            </dd>
          </div>
          {domain !== "root_domain" && (
            <>
              <div>
                <dt>{t("Source group ID", "源分组 ID")}</dt>
                <dd>
                  <FieldValue value={property(record.fields.bu, "id")} />
                </dd>
              </div>
              <div>
                <dt>{t("Source tag IDs", "源标签 ID")}</dt>
                <dd>
                  <FieldValue
                    value={
                      Array.isArray(record.fields.tags)
                        ? record.fields.tags.map((tag) => property(tag, "pk"))
                        : record.fields.tags
                    }
                  />
                </dd>
              </div>
            </>
          )}
        </dl>
      </details>
      {domain === "port" && (
        <p className="text-sm text-muted-foreground">
          {t(
            "Banner is source text, not a complete response packet. Response-packet material is not integrated.",
            "Banner 是源文本，不是完整响应包；响应包材料尚未接入。",
          )}
        </p>
      )}
      <p className="text-sm text-muted-foreground">
        {t(
          "Source times are original strings; timezone is unconfirmed. Source status is not local disposition.",
          "源时间保留原字符串，时区未确认。源状态不是本地处置状态。",
        )}
      </p>
      {domain === "root_domain" && (
        <p className="text-sm text-muted-foreground">
          {t(
            "ICP, WHOIS, and observations are source claims, not proof of customer ownership. The valid-subdomain count is source-reported; no subdomain records are synchronized. Domains, emails, and observation URLs are displayed only as text.",
            "备案、WHOIS 及观测均为源声明，不证明客户归属。有效子域名数由来源报告，未同步子域名记录。域名、邮箱和观测网址仅作为文本展示。",
          )}
        </p>
      )}
      {domain === "dns" && (
        <p className="text-sm text-muted-foreground">
          {t(
            "DNS names, types, values, groups and tags are source claims, shown only as text. No DNS lookup, external navigation or asset relationship is inferred.",
            "DNS 名称、类型、解析值、分组和标签均为源声明，仅作文本展示；不解析、不访问外链、不推导资产关系。",
          )}
        </p>
      )}
    </div>
  )
}

function VersionInfo({ version }: { version: ExternalVersionPublic }) {
  const { t, formatDate } = useI18n()
  return (
    <div className="space-y-2 rounded border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Status value={version.status} />
        <span>
          {version.domain === "dns"
            ? t("DNS records", "DNS 记录")
            : version.domain === "root_domain"
              ? t("Root domains", "主域名")
              : version.domain === "ip"
                ? "IP"
                : t("Port services", "端口服务")}{" "}
          ·{" "}
          {version.complete
            ? t("Full requested range", "请求范围完整")
            : t("Partial batch", "部分批次")}
          {" · "}
          {version.omitted_field_count && version.omitted_field_count > 0 && (
            <p className="text-sm text-muted-foreground">
              {t(
                "Contract-external fields were not saved.",
                "合同外字段未保存。",
              )}
            </p>
          )}
          {version.record_count} /{" "}
          {version.expected_total ?? t("unknown", "未知")}{" "}
          {t(
            "local records / source-reported total",
            "本地条数 / 来源声明总量",
          )}
        </span>
      </div>
      <dl className="grid min-w-0 gap-2 sm:grid-cols-2">
        <div>
          <dt>{t("Version", "版本")}</dt>
          <dd>
            <TechnicalValue value={version.id} />
          </dd>
        </div>
        <div>
          <dt>{t("Source / space", "来源 / 空间")}</dt>
          <dd className="break-all">
            {version.source_id} / {version.space_id}
          </dd>
        </div>
        <div>
          <dt>{t("Fetched locally", "本地抓取时间")}</dt>
          <dd>{formatDate(version.fetched_at)}</dd>
        </div>
        <div>
          <dt>{t("Published locally", "本地发布时间")}</dt>
          <dd>{formatDate(version.published_at)}</dd>
        </div>
        <div>
          <dt>{t("Retention deadline", "保留截止时间")}</dt>
          <dd>{formatDate(version.retain_until)}</dd>
        </div>
        <div>
          <dt>{t("Fetched page range", "已抓取页范围")}</dt>
          <dd>
            {version.pages_read === null
              ? t(
                  "Not recorded for this historical version",
                  "此历史版本未记录",
                )
              : `1–${version.pages_read}`}
          </dd>
        </div>
        <div>
          <dt>{t("Publication boundary", "发布边界")}</dt>
          <dd>
            {version.stop_reason === "batch_limit"
              ? t(
                  "Normal per-domain batch quota reached",
                  "正常达到该域批次配额",
                )
              : version.stop_reason === "source_complete"
                ? t(
                    "Source-reported requested range complete",
                    "来源声明的请求范围完整",
                  )
                : t("Not recorded", "未记录")}
          </dd>
        </div>
        <div>
          <dt>{t("Request range / sort", "请求范围 / 排序")}</dt>
          <dd>
            {version.domain === "port" ? (
              t("Source-default filtering", "来源默认过滤")
            ) : (
              <FieldValue value={version.filter} />
            )}{" "}
            / {version.sort}
          </dd>
        </div>
      </dl>
      <details>
        <summary className="cursor-pointer">
          {t("Technical fingerprint", "技术指纹")}
        </summary>
        <div className="mt-2">
          <FieldValue value={version.fingerprint} />
        </div>
      </details>
    </div>
  )
}

export default function ExternalAssets() {
  const { projectId } = Route.useParams()
  const { user } = useAuth()
  return user ? (
    <AssetsPage
      key={`${user.id}:${projectId}`}
      actor={user.id}
      projectId={projectId}
    />
  ) : null
}

function AssetsPage({
  actor,
  projectId,
}: {
  actor: string
  projectId: string
}) {
  const { t } = useI18n()
  // The validator leaves domain absent only for a bare entry. Read both values
  // from the committed match: location can advance before its search does.
  const { search, bare } = Route.useSearch({
    select: (value) => ({
      search: syncedAssetSearch(value),
      bare: value.external_domain === undefined,
    }),
  })
  const [category, setCategory] = useState<string>(search.external_domain)
  const [management, setManagement] = useState<string | null>(
    search.external_task ? "tasks" : null,
  )
  const [defaultState, setDefaultState] = useState<
    "idle" | "loading" | "empty" | "error"
  >("idle")
  const defaultAttempt = useRef(false)
  useEffect(() => {
    setCategory(search.external_domain)
  }, [search.external_domain])
  const navigate = Route.useNavigate()
  const cache = useQueryClient()
  const live = useRef(true)
  useEffect(() => {
    live.current = true
    return () => {
      live.current = false
    }
  }, [])
  const [generation, setGeneration] = useState(0)
  const [directoryCounts, setDirectoryCounts] = useState<
    Record<string, ExternalVersionPublic>
  >({})
  const reportVersion = useCallback(
    (sourceId: string, version: ExternalVersionPublic) =>
      setDirectoryCounts((previous) => {
        const key = `${sourceId}:${version.domain}`
        return previous[key]?.id === version.id &&
          previous[key]?.record_count === version.record_count &&
          previous[key]?.complete === version.complete
          ? previous
          : { ...previous, [key]: version }
      }),
    [],
  )
  const clearVersions = useCallback((sourceId: string) => {
    setDirectoryCounts((previous) => {
      const next = { ...previous }
      for (const key of Object.keys(next))
        if (key.startsWith(`${sourceId}:`)) delete next[key]
      return next
    })
  }, [])
  const [notice, setNotice] = useState("")
  const [busy, setBusy] = useState(false)
  const sources = useQuery({
    queryKey: ["external-sources", actor, projectId],
    queryFn: () => API.readExternalSources({ projectId }),
    retry: false,
    staleTime: 0,
    refetchOnMount: "always",
  })
  const data = sources.isError ? undefined : sources.data
  const selected = data?.data.find(
    (source) => source.id === search.external_source,
  )
  useEffect(() => {
    if (!bare) {
      defaultAttempt.current = false
      return
    }
    if (!data?.data.length || defaultAttempt.current) return
    defaultAttempt.current = true
    let active = true
    let finished = false
    let request: ReturnType<typeof API.readExternalVersions> | undefined
    setDefaultState("loading")
    const select = async () => {
      try {
        // Metadata only: do not redefine the implicit backend head or read every domain's rows.
        for (const domain of domains) {
          for (const source of data.data) {
            if (!source.data_access_enabled || !supportsDomain(source, domain))
              continue
            for (let skip = 0; active; skip += SIZE) {
              request = API.readExternalVersions({
                projectId,
                sourceId: source.id,
                domain,
                skip,
                limit: SIZE,
              })
              const page = await request
              if (!active) return
              const version = page.data.find(
                (item) =>
                  item.status === "PUBLISHED" &&
                  Date.parse(item.retain_until) > Date.now(),
              )
              if (version) {
                finished = true
                await navigate({
                  search: {
                    asset_view: "synced",
                    external_source: source.id,
                    external_domain: domain,
                    external_version: version.id,
                  },
                  replace: true,
                  hash: true,
                })
                return
              }
              if (skip + page.data.length >= page.count) break
              if (!page.data.length)
                throw new Error("Incomplete version metadata")
            }
            if (!active) return
          }
        }
        finished = true
        if (active) setDefaultState("empty")
      } catch {
        finished = true
        if (active) setDefaultState("error")
      }
    }
    void select()
    return () => {
      active = false
      request?.cancel()
      if (!finished) defaultAttempt.current = false
    }
  }, [bare, data, navigate, projectId])
  useEffect(() => {
    if (!bare && !search.external_source && data?.data.length) {
      void navigate({
        search: {
          ...search,
          external_source:
            data.data.find((source) => source.enabled)?.id ?? data.data[0].id,
        },
        replace: true,
        hash: true,
      })
    }
  }, [bare, data, navigate, search])
  useEffect(() => {
    if (
      (sources.error instanceof ApiError &&
        [401, 403, 404, 410].includes(sources.error.status)) ||
      (sources.isSuccess &&
        !sources.isFetching &&
        search.external_source &&
        !selected)
    ) {
      void cache
        .cancelQueries({ queryKey: ["external-assets", actor, projectId] })
        .then(() =>
          cache.removeQueries({
            queryKey: ["external-assets", actor, projectId],
          }),
        )
      if (search.external_record || search.external_record_version)
        void navigate({
          search: {
            ...search,
            external_record: undefined,
            external_record_version: undefined,
          },
          replace: true,
        })
    }
  }, [
    sources.error,
    sources.isSuccess,
    sources.isFetching,
    selected,
    actor,
    projectId,
    cache,
    navigate,
    search,
  ])
  const reload = async () => {
    defaultAttempt.current = false
    await cache.cancelQueries({
      queryKey: ["external-assets", actor, projectId],
    })
    cache.removeQueries({ queryKey: ["external-assets", actor, projectId] })
    await sources.refetch()
    setGeneration((value) => value + 1)
  }
  const chooseCategory = (value: string) => {
    setCategory(value)
    const domain = domains.find((item) => item === value)
    if (!domain) return
    const target =
      selected && supportsDomain(selected, domain)
        ? selected
        : (data?.data.find(
            (item) => item.data_access_enabled && supportsDomain(item, domain),
          ) ?? data?.data.find((item) => supportsDomain(item, domain)))
    if (
      !target ||
      (target.id === selected?.id && domain === search.external_domain)
    )
      return
    void navigate({
      search: {
        asset_view: "synced",
        external_source: target.id,
        external_domain: domain,
      },
      hash: true,
    })
  }
  const sourceControls = data ? (
    <section
      className="space-y-3 rounded border p-4"
      aria-labelledby="sources-heading"
    >
      <h2 id="sources-heading" className="text-lg font-medium">
        {t("Sources", "来源")}
      </h2>
      {data.data.length ? (
        <div className="space-y-2">
          <Label htmlFor="external-source">
            {t("Source instance", "来源实例")}
          </Label>
          <select
            id="external-source"
            className={selectClass}
            value={search.external_source ?? ""}
            onChange={(event) =>
              void navigate({
                search: {
                  external_source: event.target.value,
                  external_domain: sourceDomain(
                    data.data.find((source) => source.id === event.target.value)
                      ?.capability_profile,
                  ),
                  external_version: undefined,
                  external_record: undefined,
                  external_record_version: undefined,
                  external_port_version: undefined,
                  external_ip: undefined,
                  external_root_domain: undefined,
                  external_subdomain: undefined,
                  external_status: undefined,
                  external_task: undefined,
                  external_page: 0,
                  external_match_page: 0,
                },
              })
            }
          >
            {!selected && (
              <option value="">{t("Choose source", "选择来源")}</option>
            )}
            {data.data.map((source) => (
              <option key={source.id} value={source.id}>
                {source.instance_id} · {source.space_id} ·{" "}
                {source.capability_profile === "dns-v1"
                  ? t("DNS records", "DNS 记录")
                  : source.capability_profile === "root-domains-v1"
                    ? t("Root domains", "主域名")
                    : t("IP and port services", "IP 与端口服务")}{" "}
                ·{" "}
                {source.enabled
                  ? t("sync enabled", "同步启用")
                  : t("sync disabled", "同步停用")}
              </option>
            ))}
          </select>
        </div>
      ) : (
        <p>
          {t(
            "No synced-asset source configured. Historical Run snapshots remain available in the history view.",
            "尚未配置已同步资产来源。历史 Run 快照仍可从历史视图访问。",
          )}
        </p>
      )}
      {data.can_manage && (
        <details>
          <summary className="cursor-pointer">
            {t("Set up a new source", "配置新来源")}
          </summary>
          <form
            className="mt-3 space-y-3"
            onSubmit={async (event) => {
              event.preventDefault()
              if (busy) return
              const form = event.currentTarget
              const values = new FormData(form)
              setBusy(true)
              setNotice("")
              try {
                const created = await API.createExternalSource({
                  projectId,
                  requestBody: {
                    capability_profile:
                      values.get("capability_profile") === "dns-v1"
                        ? "dns-v1"
                        : values.get("capability_profile") === "root-domains-v1"
                          ? "root-domains-v1"
                          : "assets-v1",
                    instance_id: String(values.get("instance")),
                    capset_id: String(values.get("capset")),
                    space_id: String(values.get("space")),
                  },
                })
                if (!live.current) return
                form.reset()
                await sources.refetch()
                if (!live.current) return
                await navigate({
                  search: {
                    external_source: created.id,
                    external_domain: sourceDomain(created.capability_profile),
                    external_version: undefined,
                    external_record: undefined,
                    external_record_version: undefined,
                    external_port_version: undefined,
                    external_ip: undefined,
                    external_root_domain: undefined,
                    external_subdomain: undefined,
                    external_status: undefined,
                    external_task: undefined,
                    external_page: 0,
                    external_match_page: 0,
                  },
                })
              } catch (error) {
                if (!live.current) return
                if (
                  error instanceof ApiError &&
                  [401, 403, 404, 410].includes(error.status)
                )
                  await reload()
                if (!live.current) return
                setNotice(
                  t(
                    "Source was not confirmed. Refresh the source list before trying again.",
                    "未确认来源创建结果。请先刷新来源列表，再决定是否重试。",
                  ),
                )
              } finally {
                if (live.current) setBusy(false)
              }
            }}
          >
            <p className="text-sm text-muted-foreground">
              {t(
                "Choose the capability contract and bind its dedicated OctoBus instance, Capset, and space. Credentials are configured server-side; never paste a token here. Saved source identities and capabilities cannot be edited in place.",
                "请选择能力合同并绑定其专用 OctoBus 实例、Capset 与空间。凭据由服务端配置，请勿在此粘贴 Token。已有来源身份与能力合同不可原地修改。",
              )}
            </p>
            <div className="space-y-1">
              <Label htmlFor="new-capability">
                {t("Capability contract", "能力合同")}
              </Label>
              <select
                id="new-capability"
                name="capability_profile"
                className={selectClass}
                defaultValue="assets-v1"
                disabled={busy}
              >
                <option value="assets-v1">
                  {t(
                    "IP and port services — assets-v1",
                    "IP 与端口服务 — assets-v1",
                  )}
                </option>
                <option value="root-domains-v1">
                  {t(
                    "Root domains only — root-domains-v1",
                    "仅主域名 — root-domains-v1",
                  )}
                </option>
                <option value="dns-v1">
                  {t("DNS records only — dns-v1", "仅 DNS 记录 — dns-v1")}
                </option>
              </select>
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              {[
                ["instance", t("Instance ID", "实例 ID")],
                ["capset", t("Capset ID", "Capset ID")],
                [
                  "space",
                  t(
                    "Space ID (decimal string, e.g. 7)",
                    "空间 ID（十进制字符串，如 7）",
                  ),
                ],
              ].map(([name, label]) => (
                <div key={name} className="space-y-1">
                  <Label htmlFor={`new-${name}`}>{label}</Label>
                  <Input
                    id={`new-${name}`}
                    name={name}
                    required
                    disabled={busy}
                    autoComplete="off"
                    inputMode={name === "space" ? "numeric" : undefined}
                    pattern={name === "space" ? "[0-9]+" : undefined}
                  />
                </div>
              ))}
            </div>
            <Button type="submit" disabled={busy}>
              {t("Create disabled source", "创建停用来源")}
            </Button>
          </form>
        </details>
      )}
    </section>
  ) : null
  return (
    <div className="min-w-0 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          {t(
            "Local published results. Browsing never calls a source or model.",
            "本地已发布结果；浏览不会调用来源或模型。",
          )}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={sources.isFetching}
            onClick={() => void reload()}
          >
            {t("Refresh local access and data", "刷新本地权限与数据")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!data}
            onClick={() => setManagement("sources")}
          >
            {t("Sync management", "同步管理")}
          </Button>
          <Button
            size="sm"
            disabled={
              !data?.can_manage ||
              !selected?.data_access_enabled ||
              category !== search.external_domain
            }
            onClick={() => setManagement("sync")}
          >
            {t("Update data", "更新数据")}
          </Button>
        </div>
      </div>
      {notice && (
        <p role="status" className="text-sm">
          {notice}
        </p>
      )}
      {sources.isPending && (
        <p role="status">{t("Loading local sources…", "正在加载本地来源…")}</p>
      )}
      {sources.isError && (
        <p role="alert">
          {t(
            "Sources unavailable or access denied. Restricted data is not displayed.",
            "来源不可用或访问被拒绝。不显示受限数据。",
          )}
        </p>
      )}
      {data && (
        <>
          {!data.can_manage && (
            <p className="text-sm text-muted-foreground">
              {t(
                "Read only: Viewer role or archived project. Source changes and synchronization are unavailable.",
                "只读：查看者角色或已归档项目。不可更改来源或同步。",
              )}
            </p>
          )}
          <div className="grid min-w-0 gap-4 md:grid-cols-[177px_minmax(0,1fr)]">
            <AssetDirectory
              selected={category}
              source={selected}
              versionId={search.external_version}
              counts={directoryCounts}
              onSelect={chooseCategory}
            />
            <div className="min-w-0">
              {selected && (
                <div hidden={category !== search.external_domain}>
                  <SourceAssets
                    key={`${selected.id}:${search.external_domain}:${generation}`}
                    actor={actor}
                    projectId={projectId}
                    source={selected}
                    canManage={data.can_manage}
                    refreshSources={() => sources.refetch()}
                    reload={reload}
                    sourceControls={sourceControls}
                    management={management}
                    setManagement={setManagement}
                    reportVersion={reportVersion}
                    clearVersions={clearVersions}
                  />
                </div>
              )}
              {!domains.some((domain) => domain === category) ? (
                <section className="space-y-2 rounded border p-6">
                  <h2 className="font-medium">
                    {t("Not integrated", "尚未接入")}
                  </h2>
                  <p className="text-sm text-muted-foreground">
                    {t(
                      "This category has no approved local collection/read path yet. This is not a successful zero result; discovery seeds are read-only inputs, not discovered assets.",
                      "此分类尚无获准的本地采集与阅读接线，不是成功的零条结果；发现种子是只读输入，不是已发现资产。",
                    )}
                  </p>
                </section>
              ) : category !== search.external_domain || !data.data.length ? (
                <p role="status">
                  {t(
                    "No synced-asset source configured for this category.",
                    "此分类尚未配置已同步资产来源。",
                  )}
                </p>
              ) : bare && !selected ? (
                defaultState === "error" ? (
                  <p role="alert">
                    {t(
                      "Version metadata could not be read. No default was substituted; select a source explicitly in Sync management.",
                      "无法读取版本元数据；未替换默认结果。请在同步管理中显式选择来源。",
                    )}
                  </p>
                ) : (
                  <p role="status">
                    {defaultState === "empty"
                      ? t(
                          "No authorized published version is currently within retention. This is not a complete empty result; inspect sources and version history.",
                          "当前没有获准且未到期的已发布版本。这不是完整空集；请检查来源和版本历史。",
                        )
                      : t(
                          "Selecting an authorized local version…",
                          "正在选择获准的本地版本…",
                        )}
                  </p>
                )
              ) : null}
              {search.external_source && !selected && (
                <p role="alert">
                  {t(
                    "The requested source is unavailable in this project.",
                    "请求的来源在本项目中不可用。",
                  )}
                </p>
              )}
            </div>
          </div>
          {!selected && (
            <Dialog
              open={management !== null}
              onOpenChange={(open) => {
                if (!open) setManagement(null)
              }}
            >
              <DialogContent className={`${panelClass} sm:max-w-4xl`}>
                <DialogHeader className="border-b p-4 text-left">
                  <DialogTitle>{t("Sync management", "同步管理")}</DialogTitle>
                  <DialogDescription>
                    {t(
                      "Select or configure a source. No source read is started here.",
                      "选择或配置来源；此处不会发起来源读取。",
                    )}
                  </DialogDescription>
                </DialogHeader>
                <div className="min-h-0 overflow-y-auto p-4">
                  {sourceControls}
                </div>
              </DialogContent>
            </Dialog>
          )}
        </>
      )}
    </div>
  )
}

function SourceAssets({
  actor,
  projectId,
  source,
  canManage,
  refreshSources,
  reload,
  sourceControls,
  management,
  setManagement,
  reportVersion,
  clearVersions,
}: {
  actor: string
  projectId: string
  source: ExternalSourcePublic
  canManage: boolean
  refreshSources: () => Promise<unknown>
  reload: () => Promise<void>
  sourceControls: ReactNode
  management: string | null
  setManagement: (tab: string | null) => void
  reportVersion: (sourceId: string, version: ExternalVersionPublic) => void
  clearVersions: (sourceId: string) => void
}) {
  const { showSuccessToast } = useCustomToast()
  const { t, formatDate } = useI18n()
  const search = Route.useSearch({ select: syncedAssetSearch })
  const rootDomains = source.capability_profile === "root-domains-v1"
  const dnsRecords = source.capability_profile === "dns-v1"
  const selectedDomain = sourceDomain(source.capability_profile)
  const singleDomain = source.capability_profile !== "assets-v1"
  const addressDomain = selectedDomain === "openport" || !singleDomain
  const domain = singleDomain
    ? selectedDomain
    : search.external_domain === "port"
      ? "port"
      : "ip"
  const scopeReady =
    search.external_domain === domain &&
    (rootDomains || !search.external_root_domain) &&
    (dnsRecords || !search.external_subdomain) &&
    (!singleDomain ||
      (!search.external_ip &&
        !search.external_port_version &&
        search.external_match_page === 0))
  const navigate = Route.useNavigate()
  const cache = useQueryClient()
  const prefix = ["external-assets", actor, projectId, source.id]
  const [denied, setDenied] = useState(false)
  const [expired, setExpired] = useState(false)
  const deniedRef = useRef(false)
  const live = useRef(true)
  useEffect(() => {
    live.current = true
    return () => {
      live.current = false
    }
  }, [])
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  const [notice, setNotice] = useState("")
  const [taskPage, setTaskPage] = useState(0)
  const [versionPage, setVersionPage] = useState(0)
  const [portVersionPage, setPortVersionPage] = useState(0)
  const heading = useRef<HTMLHeadingElement>(null)
  const detailTrigger = useRef<HTMLElement | null>(null)
  const [expanded, setExpanded] = useState(false)
  useEffect(() => setExpanded(false), [])
  useEffect(() => {
    if (search.external_task) setManagement("tasks")
  }, [search.external_task, setManagement])
  const move = useCallback(
    (change: Partial<typeof search>, replace = false) =>
      navigate({ search: { ...search, ...change }, replace, hash: true }),
    [navigate, search],
  )
  useEffect(() => {
    if (!scopeReady)
      void move(
        {
          external_domain: domain,
          external_ip: addressDomain ? search.external_ip : undefined,
          external_root_domain: rootDomains
            ? search.external_root_domain
            : undefined,
          external_subdomain: dnsRecords
            ? search.external_subdomain
            : undefined,
          external_port_version: singleDomain
            ? undefined
            : search.external_port_version,
          external_match_page: singleDomain ? 0 : search.external_match_page,
        },
        true,
      )
  }, [
    addressDomain,
    domain,
    move,
    rootDomains,
    dnsRecords,
    singleDomain,
    scopeReady,
    search.external_ip,
    search.external_root_domain,
    search.external_subdomain,
    search.external_port_version,
    search.external_match_page,
  ])
  const store = `exposure:external-sync:${actor}:${projectId}`
  const [saved] = useState(() => {
    try {
      const raw = sessionStorage.getItem(store)
      if (!raw) return { intent: null, broken: false }
      const result = intentSchema.safeParse(JSON.parse(raw))
      return result.success
        ? { intent: result.data, broken: false }
        : { intent: null, broken: true }
    } catch {
      return { intent: null, broken: true }
    }
  })
  const [intent, setIntent] = useState<Intent | null>(saved.intent)
  const [storageBroken, setStorageBroken] = useState(saved.broken)
  const revoke = useCallback(
    (expiryOnly = false) => {
      if (!live.current) return
      if (expiryOnly) setExpired(true)
      else {
        deniedRef.current = true
        setDenied(true)
        setManagement(null)
      }
      clearVersions(source.id)
      const filters = {
        queryKey: ["external-assets", actor, projectId],
        predicate: (query: { queryKey: readonly unknown[] }) =>
          !expiryOnly ||
          ["records", "detail"].includes(String(query.queryKey[4])),
      }
      void cache.cancelQueries(filters).then(() => cache.removeQueries(filters))
      void navigate({
        search: (previous) => ({
          ...previous,
          external_record: undefined,
          external_record_version: undefined,
          external_port_version: undefined,
        }),
        replace: true,
      })
    },
    [
      actor,
      cache,
      clearVersions,
      navigate,
      projectId,
      setManagement,
      source.id,
    ],
  )
  const guarded = async <T,>(request: Promise<T>): Promise<T> => {
    try {
      const result = await request
      if (!live.current || deniedRef.current)
        throw new Error("Access must be checked again")
      return result
    } catch (error) {
      if (
        error instanceof ApiError &&
        [401, 403, 404, 410].includes(error.status)
      )
        revoke(error.status === 410)
      throw error
    }
  }
  const allowed = source.data_access_enabled && !denied
  const versions = useQuery({
    queryKey: [...prefix, "versions", domain, versionPage],
    enabled: allowed && scopeReady && management === "versions",
    queryFn: () =>
      guarded(
        API.readExternalVersions({
          projectId,
          sourceId: source.id,
          domain,
          skip: versionPage * SIZE,
          limit: SIZE,
        }),
      ),
    retry: false,
  })
  const records = useQuery({
    queryKey: [
      ...prefix,
      "records",
      domain,
      search.external_version,
      search.external_ip,
      search.external_root_domain,
      search.external_subdomain,
      search.external_status,
      search.external_q,
      search.external_sha256,
      search.external_md5_value,
      search.external_mmh3_value,
      search.external_seed_enabled,
      search.external_confidence,
      search.external_seed_type,
      search.external_page,
    ],
    enabled: allowed && scopeReady && !expired,
    queryFn: () =>
      guarded(
        API.readExternalRecords({
          projectId,
          sourceId: source.id,
          domain,
          versionId: search.external_version,
          ip: addressDomain ? search.external_ip : undefined,
          rootDomain: rootDomains ? search.external_root_domain : undefined,
          subdomain: dnsRecords ? search.external_subdomain : undefined,
          status: search.external_status,
          q: search.external_q,
          sha256: search.external_sha256,
          md5Value: search.external_md5_value,
          mmh3Value: search.external_mmh3_value,
          seedEnabled: search.external_seed_enabled,
          confidence: search.external_confidence,
          seedType: search.external_seed_type,
          skip: search.external_page * SIZE,
          limit: SIZE,
        }),
      ),
    retry: false,
  })
  const invalidIpFilter =
    !singleDomain && hasErrorCode(records.error, "external_ip_filter_invalid")
  const tasks = useQuery({
    queryKey: [...prefix, "tasks", taskPage],
    enabled: allowed,
    queryFn: () =>
      guarded(
        API.readExternalSyncs({
          projectId,
          sourceId: source.id,
          skip: taskPage * SIZE,
          limit: SIZE,
        }),
      ),
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.data.some((task) =>
        ["PENDING", "RUNNING"].includes(task.status),
      )
        ? 5000
        : false,
  })
  const task = useQuery({
    queryKey: [...prefix, "task", search.external_task],
    enabled: allowed && !!search.external_task,
    queryFn: () =>
      guarded(
        API.readExternalSync({
          projectId,
          sourceId: source.id,
          syncId: search.external_task!,
        }),
      ),
    retry: false,
    refetchInterval: (query) =>
      query.state.data &&
      ["PENDING", "RUNNING"].includes(query.state.data.status)
        ? 5000
        : false,
  })
  const detail = useQuery({
    queryKey: [
      ...prefix,
      "detail",
      domain,
      search.external_record_version,
      search.external_record,
      singleDomain ? undefined : search.external_port_version,
      singleDomain ? 0 : search.external_match_page,
    ],
    enabled:
      allowed &&
      scopeReady &&
      !expired &&
      !!search.external_record &&
      !!search.external_record_version,
    queryFn: () =>
      guarded(
        API.readExternalRecord({
          projectId,
          sourceId: source.id,
          versionId: search.external_record_version!,
          recordId: search.external_record!,
          portVersionId: singleDomain
            ? undefined
            : search.external_port_version,
          skip: singleDomain ? 0 : search.external_match_page * SIZE,
          limit: SIZE,
        }),
      ),
    retry: false,
  })
  const ports = useQuery({
    queryKey: [...prefix, "versions", "port", portVersionPage],
    enabled:
      allowed &&
      scopeReady &&
      !singleDomain &&
      !!search.external_record &&
      detail.data?.version.domain === "ip",
    queryFn: () =>
      guarded(
        API.readExternalVersions({
          projectId,
          sourceId: source.id,
          domain: "port",
          skip: portVersionPage * SIZE,
          limit: SIZE,
        }),
      ),
    retry: false,
  })
  const recordData =
    !scopeReady || expired || records.isError ? undefined : records.data
  const detailData =
    !scopeReady || expired || detail.isError ? undefined : detail.data
  useEffect(() => {
    if (
      recordData?.state === "PUBLISHED" &&
      recordData.version &&
      !search.external_version &&
      !records.isFetching
    )
      void move({ external_version: recordData.version.id }, true)
  }, [recordData, search.external_version, records.isFetching, move])
  useEffect(() => {
    if (recordData?.state === "PUBLISHED" && recordData.version)
      reportVersion(source.id, recordData.version)
  }, [recordData, reportVersion, source.id])
  useEffect(() => {
    if (!source.data_access_enabled) revoke()
  }, [source.data_access_enabled, revoke])
  // Expiry is an access boundary even while the browser is idle on a fixed detail.
  useEffect(() => {
    const deadlines = [
      recordData?.version?.retain_until,
      detailData?.version.retain_until,
      search.external_port_version
        ? detailData?.port_version?.retain_until
        : undefined,
    ]
      .filter((value): value is string => !!value)
      .map(Date.parse)
    if (!deadlines.length) return
    let timer: number
    const check = () => {
      const delay = Math.min(...deadlines) - Date.now()
      if (delay <= 0) revoke(true)
      else timer = window.setTimeout(check, Math.min(delay, 2_147_483_647))
    }
    check()
    return () => window.clearTimeout(timer)
  }, [
    recordData?.version?.retain_until,
    detailData?.version.retain_until,
    detailData?.port_version?.retain_until,
    search.external_port_version,
    revoke,
  ])
  useEffect(() => {
    if (recordData?.state === "EXPIRED") revoke(true)
  }, [recordData?.state, revoke])
  const operation = async (action: () => Promise<unknown>) => {
    if (busyRef.current) return
    busyRef.current = true
    setBusy(true)
    setNotice("")
    try {
      const result = await action()
      if (!live.current) return
      showSuccessToast(
        typeof result === "string"
          ? result
          : t("Operation confirmed.", "操作已确认。"),
      )
      await cache.invalidateQueries({ queryKey: prefix })
      if (!live.current) return
      await refreshSources()
    } catch (error) {
      if (!live.current) return
      if (
        error instanceof ApiError &&
        [401, 403, 404, 410].includes(error.status)
      )
        revoke()
      setNotice(
        error instanceof ApiError && error.status === 409
          ? t(
              "Conflict: check validation, enabled legacy source, and unresolved tasks before retrying.",
              "冲突：请检查校验结果、已启用的旧来源及未决任务后重试。",
            )
          : t(
              "Operation could not be confirmed. Refresh local state; do not assume it succeeded.",
              "无法确认操作结果。请刷新本地状态，不应假定已成功。",
            ),
      )
    } finally {
      busyRef.current = false
      if (live.current) setBusy(false)
    }
  }
  const sendIntent = async (pending: Intent) => {
    if (busyRef.current) return
    busyRef.current = true
    setBusy(true)
    setNotice("")
    try {
      const result = await guarded(
        API.createExternalSync({
          projectId,
          sourceId: pending.source,
          idempotencyKey: pending.key,
          requestBody: pending.body,
        }),
      )
      sessionStorage.removeItem(store)
      setIntent(null)
      await move({ external_task: result.id })
      await cache.invalidateQueries({ queryKey: prefix })
    } catch (error) {
      if (!live.current) return
      if (error instanceof ApiError && error.status === 422) {
        // Validation rejection precedes task reservation; unlike transport failures,
        // this is a confirmed non-submission, so the operator may correct the budget.
        try {
          sessionStorage.removeItem(store)
          setIntent(null)
        } catch {
          setStorageBroken(true)
        }
        setNotice(
          t(
            "The server rejected this budget or retention deadline before task creation. Correct the values before submitting.",
            "服务端在创建任务前拒绝了预算或保留截止时间。请修正后再提交。",
          ),
        )
        return
      }
      setNotice(
        error instanceof ApiError && error.status === 409
          ? t(
              "Submission conflict. The original key and budget are retained; inspect existing tasks. Do not submit a replacement task.",
              "提交冲突。已保留原幂等键和预算，请核对现有任务，不要提交替代任务。",
            )
          : t(
              "Submission outcome is unconfirmed. The original request is saved. Recover using the SAME key and budget below; never create a fresh retry.",
              "提交结果未确认。原请求已保存。请使用下方同一幂等键和预算恢复，不要使用新键重试。",
            ),
      )
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }
  const unresolved = tasks.data?.data.some((item) =>
    ["PENDING", "RUNNING", "UNKNOWN"].includes(item.status),
  )
  const renderTask = (item: ExternalSyncPublic) => (
    <article className="space-y-3 rounded border p-3" key={item.id}>
      <div className="flex flex-wrap items-center gap-3">
        <Status value={item.status} />
        <Link
          className="break-all text-sm underline"
          to="/projects/$projectId/cloudatlas-ledger"
          params={{ projectId }}
          search={{ ...search, asset_view: "synced", external_task: item.id }}
        >
          {item.id}
        </Link>
      </div>
      <p className="text-sm">
        {t("Created", "创建")} {formatDate(item.created_at)} ·{" "}
        {t("Retention", "保留截止")} {formatDate(item.retain_until)}
      </p>
      {item.started_at && (
        <p className="text-sm">
          {t("Started", "开始")} {formatDate(item.started_at)}
        </p>
      )}
      {item.completed_at && (
        <p className="text-sm">
          {t("Completed", "完成")} {formatDate(item.completed_at)}
        </p>
      )}
      {item.error_code && (
        <p className="break-all text-sm">
          {t("Error code", "错误码")}: {item.error_code}
        </p>
      )}
      <ul className="space-y-2">
        {item.domains.map((domain) => (
          <li
            className="flex flex-wrap items-center gap-2 text-sm"
            key={domain.domain}
          >
            <span>
              {domain.domain === "dns"
                ? t("DNS records", "DNS 记录")
                : domain.domain === "root_domain"
                  ? t("Root domains", "主域名")
                  : domain.domain === "ip"
                    ? "IP"
                    : t("Port services", "端口服务")}
            </span>
            <Status value={domain.status} />
            {domain.status === "PUBLISHED" && (
              <span>
                {domain.complete
                  ? t("Full requested range", "请求范围完整")
                  : t("Partial batch", "部分批次")}
                {" · "}
                {domain.record_count} /{" "}
                {domain.expected_total ?? t("unknown", "未知")}{" "}
                {t(
                  "local records / source-reported total",
                  "本地条数 / 来源声明总量",
                )}
                {" · "}
                {t("Pages", "页范围")}:{" "}
                {domain.pages_read === null
                  ? t("not recorded", "未记录")
                  : `1–${domain.pages_read}`}
              </span>
            )}
            {domain.error_code && <span>{domain.error_code}</span>}
            {domain.version_id && domain.status === "PUBLISHED" && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setExpired(false)
                  setVersionPage(0)
                  setManagement(null)
                  void move({
                    external_domain: domain.domain,
                    external_version: domain.version_id!,
                    external_page: 0,
                    external_record: undefined,
                    external_record_version: undefined,
                    external_port_version: undefined,
                    external_match_page: 0,
                  })
                }}
              >
                {t("Read published version", "读取已发布版本")}
              </Button>
            )}
          </li>
        ))}
      </ul>
      {item.status === "UNKNOWN" && (
        <>
          <p className="text-sm">
            {t(
              "Unknown is not failed or successful. Reconcile only the reserved agent-compose run/session; this does not restart source reads.",
              "未知不等于失败或成功。仅核对已保留的 agent-compose 运行和会话，不会重启来源读取。",
            )}
          </p>
          {canManage && (
            <Button
              disabled={busy}
              variant="outline"
              onClick={() =>
                void operation(() =>
                  API.reconcileExternalSync({
                    projectId,
                    sourceId: source.id,
                    syncId: item.id,
                  }),
                )
              }
            >
              {t("Reconcile original task", "核对原任务")}
            </Button>
          )}
        </>
      )}
      <details>
        <summary className="cursor-pointer text-sm">
          {t("Execution identity", "执行身份")}
        </summary>
        <dl className="mt-2 text-sm">
          <dt>{t("Agent run", "代理运行")}</dt>
          <dd>
            <FieldValue value={item.agent_run_id} />
          </dd>
          <dt>{t("Session", "会话")}</dt>
          <dd>
            <FieldValue value={item.session_id} />
          </dd>
        </dl>
      </details>
    </article>
  )
  const cell = (value: unknown) => (
    <div className="line-clamp-2 max-w-64 whitespace-normal break-words">
      <FieldValue value={value} />
    </div>
  )
  const renderRows = (
    items: ExternalRecordPublic[],
    domain: string,
    versionId: string,
  ) => {
    const detailLink = (record: ExternalRecordPublic) => (
      <Link
        className="underline underline-offset-4"
        to="/projects/$projectId/cloudatlas-ledger"
        params={{ projectId }}
        search={{
          ...search,
          asset_view: "synced",
          external_record: record.id,
          external_record_version: versionId,
          external_port_version: undefined,
          external_match_page: 0,
        }}
        onClick={(event) => {
          detailTrigger.current = event.currentTarget
        }}
        aria-label={t(
          `Details for ${domain === "dns" ? record.fields.subdomain : domain === "root_domain" ? record.fields.root_domain : record.ip}, source ID ${record.source_id}`,
          `${domain === "dns" ? record.fields.subdomain : domain === "root_domain" ? record.fields.root_domain : record.ip} 的详情，源 ID ${record.source_id}`,
        )}
      >
        {t("Details", "详情")}
      </Link>
    )
    const structured = structuredFields[domain]
    if (structured) {
      const primary =
        structured.find((field) =>
          [
            "name",
            "subdomain",
            "cn_name",
            "ip",
            "url",
            "target",
            "icon_url",
          ].includes(field),
        ) ?? "id"
      const details = structured
        .filter(
          (field) =>
            ![
              primary,
              "status",
              "created_at",
              "updated_at",
              "lastseen_at",
              "enable",
              "confidence",
            ].includes(field),
        )
        .slice(0, 4)
      const hasStatus = structured.includes("status")
      const hasTimes = structured.some((field) =>
        ["created_at", "updated_at", "lastseen_at"].includes(field),
      )
      const title = (field: string) =>
        t(
          {
            id: "Source ID",
            name: "Name",
            ip: "IP",
            port: "Port",
            protocol: "Protocol",
            url: "URL",
            subdomain: "Subdomain",
            cn_name: "Certificate name",
            target: "Target",
            icon_url: "Icon link",
            status: "Source status",
            created_at: "Source created time",
            updated_at: "Source updated time",
            lastseen_at: "Source last-seen time",
          }[field] ?? field,
          {
            id: "来源 ID",
            name: "名称",
            ip: "IP",
            port: "端口",
            protocol: "协议",
            url: "URL",
            subdomain: "子域名",
            cn_name: "证书名称",
            target: "目标",
            icon_url: "图标链接",
            status: "源状态",
            created_at: "源创建时间",
            updated_at: "源更新时间",
            lastseen_at: "源最近发现时间",
          }[field] ?? field,
        )
      return (
        <Table className="min-w-[760px]">
          <TableHeader>
            <TableRow>
              <TableHead>{title(primary)}</TableHead>
              {details.map((field) => (
                <TableHead key={field}>{title(field)}</TableHead>
              ))}
              {hasStatus && <TableHead>{title("status")}</TableHead>}
              {hasTimes && <TableHead>{t("Source times", "源时间")}</TableHead>}
              <TableHead>{t("Details", "详情")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((record) => (
              <TableRow key={record.id}>
                <TableCell className="font-mono">
                  {cell(record.fields[primary] ?? record.source_id)}
                </TableCell>
                {details.map((field) => (
                  <TableCell key={field}>
                    {cell(record.fields[field])}
                  </TableCell>
                ))}
                {hasStatus && (
                  <TableCell>{cell(record.fields.status)}</TableCell>
                )}
                {hasTimes && (
                  <TableCell>
                    {cell(
                      [
                        record.fields.created_at,
                        record.fields.updated_at,
                        record.fields.lastseen_at,
                      ].filter((value) => value !== undefined),
                    )}
                  </TableCell>
                )}
                <TableCell>{detailLink(record)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )
    }
    if (domain === "port")
      return (
        <Table className="min-w-[1080px]">
          <TableHeader>
            <TableRow>
              <TableHead>{t("IP", "IP")}</TableHead>
              <TableHead>{t("Port", "端口")}</TableHead>
              <TableHead>{t("Protocol", "协议")}</TableHead>
              <TableHead>
                {t("Service / product / version", "服务 / 产品 / 版本")}
              </TableHead>
              <TableHead>{t("Group / tags", "分组 / 标签")}</TableHead>
              <TableHead>{t("Source status", "源状态")}</TableHead>
              <TableHead>
                {t("Source last-seen time", "源最近发现时间")}
              </TableHead>
              <TableHead>{t("Details", "详情")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((record) => (
              <TableRow key={record.id}>
                <TableCell className="font-mono">
                  {cell(record.fields.ip)}
                </TableCell>
                <TableCell className="font-mono">
                  {cell(record.fields.port)}
                </TableCell>
                <TableCell>{cell(record.fields.protocol)}</TableCell>
                <TableCell>
                  {cell(record.fields.service)}
                  {cell(record.fields.product)}
                  {cell(record.fields.version)}
                </TableCell>
                <TableCell>
                  {cell(names(record.fields.bu))}
                  {cell(names(record.fields.tags))}
                </TableCell>
                <TableCell>{cell(record.fields.status)}</TableCell>
                <TableCell>{cell(record.fields.lastseen_at)}</TableCell>
                <TableCell>{detailLink(record)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )
    return (
      <Table className="min-w-[760px]">
        <TableHeader>
          <TableRow>
            <TableHead>
              {domain === "dns"
                ? t("Subdomain", "子域名")
                : domain === "root_domain"
                  ? t("Root domain", "主域名")
                  : t("IP / version", "IP / 版本")}
            </TableHead>
            <TableHead>
              {domain === "dns"
                ? t("Record type / value", "解析类型 / 值")
                : domain === "root_domain"
                  ? t(
                      "Source-claimed ICP organization / number",
                      "源声明备案主体 / 号",
                    )
                  : domain === "port"
                    ? t("Service / product / version", "服务 / 产品 / 版本")
                    : t("Group / tags", "分组 / 标签")}
            </TableHead>
            <TableHead>
              {domain === "ip"
                ? t("Network ownership", "网络归属")
                : domain === "root_domain"
                  ? t(
                      "Source-reported valid subdomains",
                      "来源报告有效子域名数",
                    )
                  : t("Group / tags", "分组 / 标签")}
            </TableHead>
            <TableHead>{t("Source status", "源状态")}</TableHead>
            <TableHead>
              {t("Source last-seen time", "源最近发现时间")}
            </TableHead>
            <TableHead>{t("Details", "详情")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((record) => (
            <TableRow key={record.id}>
              <TableCell className="font-mono">
                {cell(
                  domain === "dns"
                    ? record.fields.subdomain
                    : domain === "root_domain"
                      ? record.fields.root_domain
                      : record.fields.ip,
                )}
                {domain === "ip" && (
                  <div className="text-xs text-muted-foreground">
                    {t("Version", "版本")}:{" "}
                    <FieldValue value={record.fields.version} />
                  </div>
                )}
              </TableCell>
              <TableCell>
                {domain === "ip" ? (
                  <>
                    {cell(names(record.fields.bu))}
                    {cell(names(record.fields.tags))}
                  </>
                ) : domain === "root_domain" ? (
                  <>
                    {cell(record.fields.icp_official_name)}
                    {cell(record.fields.icp_num)}
                  </>
                ) : (
                  <>
                    {cell(record.fields.rdtype)}
                    {cell(record.fields.record)}
                  </>
                )}
              </TableCell>
              <TableCell>
                {domain === "ip" ? (
                  <>
                    {cell(record.fields.provider)}
                    {cell(record.fields.as_name)}
                    {cell(record.fields.as_num)}
                  </>
                ) : domain === "root_domain" ? (
                  cell(record.fields.valid_subdomain)
                ) : (
                  <>
                    {cell(names(record.fields.bu))}
                    {cell(names(record.fields.tags))}
                  </>
                )}
              </TableCell>
              <TableCell>{cell(record.fields.status)}</TableCell>
              <TableCell>{cell(record.fields.lastseen_at)}</TableCell>
              <TableCell>{detailLink(record)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    )
  }
  return (
    <div className="min-w-0 space-y-6">
      {notice && (
        <p role="status" className="text-sm">
          {notice}
        </p>
      )}
      {(intent || storageBroken) && (
        <p role="status" className="flex flex-wrap items-center gap-2 text-sm">
          {t(
            "An original submission requires attention; a new request must not replace it.",
            "原提交需要处理，不可用新请求替代。",
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() => setManagement("sync")}
          >
            {t("Inspect original submission", "检查原提交")}
          </Button>
        </p>
      )}
      {!allowed ? (
        <section role="alert" className="space-y-3 rounded border p-4">
          <h2 className="font-medium">
            {t(
              "Data unavailable: access denied, expired, or scope no longer exists",
              "数据不可用：权限被拒绝、已到期或范围已不存在",
            )}
          </h2>
          <p>
            {t(
              "Restricted lists, cached records, and open details have been cleared. No older cached version is used.",
              "已清除受限列表、缓存记录及已打开详情，不回退到旧缓存版本。",
            )}
          </p>
          <Button
            variant="outline"
            onClick={async () => {
              await move(
                {
                  external_version: undefined,
                  external_record: undefined,
                  external_record_version: undefined,
                  external_port_version: undefined,
                  external_page: 0,
                },
                true,
              )
              await reload()
            }}
          >
            {t("Recheck local access", "重新检查本地访问")}
          </Button>
        </section>
      ) : (
        <>
          {!tasks.isError &&
            taskPage === 0 &&
            tasks.data?.data[0] &&
            [
              "FAILED",
              "PARTIAL_FAILED",
              "UNKNOWN",
              "PENDING",
              "RUNNING",
            ].includes(tasks.data.data[0].status) && (
              <div
                role="status"
                className="flex flex-wrap items-center gap-3 rounded border p-3 text-sm"
              >
                <Status value={tasks.data.data[0].status} />
                <span>
                  {t(
                    "Task status does not replace the selected local version.",
                    "任务状态不替换选定的本地版本。",
                  )}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setManagement("tasks")}
                >
                  {t("View tasks", "查看任务")}
                </Button>
              </div>
            )}
          <section
            className="min-w-0 space-y-4"
            aria-labelledby="records-heading"
          >
            <h2
              id="records-heading"
              ref={heading}
              tabIndex={-1}
              className="text-lg font-medium"
            >
              {t("Local asset records", "本地资产记录")}
            </h2>
            <details className="space-y-2 text-sm">
              <summary className="cursor-pointer text-muted-foreground">
                {t("Search and range semantics", "检索与范围说明")}
              </summary>
              <p className="text-sm text-muted-foreground">
                {t(
                  "Partial batches contain only their fetched pages; local count is not source total. A complete version covers only its fixed requested range, not all upstream states or a guaranteed snapshot. Source IDs identify records within a version, not stable cross-version entities.",
                  "部分批次仅包含已抓取页面，本地条数不是来源总量。完整版本也仅覆盖固定请求范围，不代表上游全部状态或一致性快照。源 ID 仅标识版本内记录，不是跨版本稳定实体。",
                )}
              </p>
              {!singleDomain && (
                <p className="text-sm text-muted-foreground">
                  {t(
                    "IP lookup sends one exact IPv4 or IPv6 value to the selected local fixed version. It does not search CIDR ranges, prefixes, or upstream data.",
                    "IP 检索只将一个精确 IPv4 或 IPv6 值发送到选定的本地固定版本；不检索 CIDR、前缀或上游数据。",
                  )}
                </p>
              )}
              {rootDomains && (
                <p className="text-sm text-muted-foreground">
                  {t(
                    "Search is a case-insensitive literal substring of the original root-domain text in the selected local version. The matching local row count is not the source total or the source-reported valid-subdomain count. ICP/WHOIS are source claims, not ownership proof; no subdomains are synchronized.",
                    "搜索仅对选定本地版本的原主域名文本作大小写不敏感的字面子串匹配。匹配的本地行数不是来源总量，也不是来源报告有效子域名数。备案 / WHOIS 均为源声明，不证明归属；未同步子域名。",
                  )}
                </p>
              )}
              {dnsRecords && (
                <p className="text-sm text-muted-foreground">
                  {t(
                    "Search matches only the original subdomain text in the selected local version, case-insensitively and literally. It does not search record values or infer asset relationships.",
                    "搜索仅对选定本地版本的原子域名文本作大小写不敏感的字面子串匹配；不搜索解析值、不推导资产关系。",
                  )}
                </p>
              )}
            </details>
            <form
              key={`${domain}:${search.external_ip}:${search.external_root_domain}:${search.external_subdomain}:${search.external_status}`}
              className="flex flex-wrap items-end gap-3"
              onSubmit={(event) => {
                event.preventDefault()
                const form = new FormData(event.currentTarget)
                void move({
                  external_ip: singleDomain
                    ? undefined
                    : String(form.get("ip") ?? "").trim() || undefined,
                  external_root_domain: rootDomains
                    ? String(form.get("root_domain") ?? "") || undefined
                    : undefined,
                  external_subdomain: dnsRecords
                    ? String(form.get("subdomain") ?? "") || undefined
                    : undefined,
                  external_status:
                    String(form.get("status") ?? "").trim() || undefined,
                  external_page: 0,
                })
                heading.current?.focus()
              }}
            >
              <div className="min-w-0 space-y-1">
                <Label htmlFor="filter-name">
                  {dnsRecords
                    ? t(
                        "Subdomain contains (local text)",
                        "子域名包含（本地文本）",
                      )
                    : rootDomains
                      ? t(
                          "Root domain contains (local text)",
                          "主域名包含（本地文本）",
                        )
                      : t("Exact IP (IPv4 or IPv6)", "精确 IP（IPv4 或 IPv6）")}
                </Label>
                <Input
                  id="filter-name"
                  name={
                    dnsRecords
                      ? "subdomain"
                      : rootDomains
                        ? "root_domain"
                        : "ip"
                  }
                  maxLength={singleDomain ? 1024 : undefined}
                  defaultValue={
                    (dnsRecords
                      ? search.external_subdomain
                      : rootDomains
                        ? search.external_root_domain
                        : search.external_ip) ?? ""
                  }
                  aria-invalid={invalidIpFilter ? true : undefined}
                />
              </div>
              <div className="min-w-0 space-y-1">
                <Label htmlFor="filter-status">
                  {t("Local source-status filter", "本地源状态筛选")}
                </Label>
                <Input
                  id="filter-status"
                  name="status"
                  defaultValue={search.external_status ?? ""}
                />
              </div>
              <Button type="submit">
                {t("Filter local records", "筛选本地记录")}
              </Button>
              <Button
                variant="outline"
                type="button"
                onClick={() =>
                  void move({
                    external_ip: undefined,
                    external_root_domain: undefined,
                    external_subdomain: undefined,
                    external_status: undefined,
                    external_page: 0,
                  })
                }
              >
                {t("Clear filters", "清除筛选")}
              </Button>
            </form>
            {expired && (
              <p role="alert">
                {t(
                  "The selected data expired. Restricted cached records and open details were cleared; no older version is substituted. History metadata and cleanup remain available.",
                  "选定数据已到期。已清除受限缓存记录及打开的详情，不以旧版本替代。仍可查看版本元数据并执行清理。",
                )}
              </p>
            )}
            {!expired && records.isPending && (
              <p role="status">
                {t("Loading local records…", "正在加载本地记录…")}
              </p>
            )}
            {!expired && records.isError && (
              <p role="alert">
                {invalidIpFilter
                  ? t(
                      "The IP format is invalid. Enter one exact IPv4 or IPv6 address; CIDR ranges and partial values are not accepted.",
                      "IP 格式无效。请输入一个精确 IPv4 或 IPv6 地址；不接受 CIDR 范围或部分值。",
                    )
                  : t(
                      "Local records could not be read. Cached results are not used.",
                      "无法读取本地记录，不使用缓存结果。",
                    )}
              </p>
            )}
            {recordData?.state === "NOT_SYNCED" && (
              <p role="status">
                {t(
                  "Not synchronized: no readable version has been published for this domain. Check task failures above; this is not a successful empty result.",
                  "未同步：此域尚未发布可读版本。请检查上方失败任务；这不是成功的空结果。",
                )}
              </p>
            )}
            {recordData?.state === "PUBLISHED" && recordData.version && (
              <>
                <div className="space-y-2 rounded border bg-muted/20 p-3 text-sm">
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                    <span className="break-all font-medium">
                      {source.instance_id} / {source.space_id}
                    </span>
                    <span>
                      {domain === "port"
                        ? t("Source-default scope", "来源默认范围")
                        : domain === "dns"
                          ? "flat=1 · status=valid"
                          : "status=valid"}
                    </span>
                    <span>
                      {recordData.version.complete
                        ? t("Full requested range", "请求范围完整")
                        : t("Partial batch", "部分批次")}
                    </span>
                    <span>
                      {t("Filtered records", "筛选结果")}: {recordData.count}
                    </span>
                    <span>
                      {t("Local records", "本地记录")}:{" "}
                      {recordData.version.record_count}
                    </span>
                    <span>
                      {t("Source-reported total", "来源声明总量")}:{" "}
                      {recordData.version.expected_total ??
                        t("unknown", "未知")}
                    </span>
                    <span>
                      {t("Fetched locally", "本地采集时间")}:{" "}
                      {formatDate(recordData.version.fetched_at)}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setManagement("versions")}
                    >
                      {t("More scopes / versions", "更多范围 / 版本")}
                    </Button>
                  </div>
                  <details>
                    <summary className="cursor-pointer text-muted-foreground">
                      {t(
                        "Fixed version and range details",
                        "固定版本与范围详情",
                      )}
                    </summary>
                    <VersionInfo version={recordData.version} />
                  </details>
                </div>
                {recordData.data.length ? (
                  renderRows(recordData.data, domain, recordData.version.id)
                ) : (
                  <p>
                    {recordData.version.record_count === 0
                      ? t(
                          "Published complete empty version for the requested range.",
                          "此请求范围已发布完整空版本。",
                        )
                      : !recordData.version.complete
                        ? t(
                            "No records match this partial local batch or page. This does not show that the upstream source has no record.",
                            "当前部分本地批次或页码没有匹配记录；这不表示上游来源没有该记录。",
                          )
                        : t(
                            "No records match these local filters or page.",
                            "当前本地筛选或页码无匹配记录。",
                          )}
                  </p>
                )}
                <ResultPagination
                  label={t("Records", "记录")}
                  count={recordData.count}
                  page={search.external_page}
                  pageSize={SIZE}
                  onPageChange={(next) => {
                    void move({ external_page: next })
                    heading.current?.focus()
                  }}
                />
              </>
            )}
          </section>
          <Dialog
            open={!!search.external_record}
            onOpenChange={(open) => {
              if (!open) {
                void move({
                  external_record: undefined,
                  external_record_version: undefined,
                  external_port_version: undefined,
                  external_match_page: 0,
                })
              }
            }}
          >
            <DialogContent
              className={`${panelClass} ${expanded ? "sm:max-w-[1040px]" : "sm:max-w-[650px]"}`}
              onCloseAutoFocus={(event) => {
                event.preventDefault()
                if (detailTrigger.current?.isConnected)
                  detailTrigger.current.focus()
                else heading.current?.focus()
              }}
            >
              <DialogHeader className="border-b p-4 text-left">
                <div className="flex items-center justify-between gap-3">
                  <DialogTitle>
                    {t("Fixed-version record details", "固定版本记录详情")}
                  </DialogTitle>
                  <Button
                    className="hidden shrink-0 sm:inline-flex"
                    size="sm"
                    variant="outline"
                    onClick={() => setExpanded((value) => !value)}
                  >
                    {expanded
                      ? t("Restore width", "收起宽度")
                      : t("Expand reading", "展开阅读")}
                  </Button>
                </div>
                <DialogDescription>
                  {t(
                    "The URL fixes the source, domain version and record. Text is escaped; source times are not converted to UTC.",
                    "网址固定来源、域版本与记录。文本转义显示，源时间不转换为 UTC。",
                  )}
                </DialogDescription>
              </DialogHeader>
              <div className="min-h-0 overflow-y-auto p-4">
                {!search.external_record_version && (
                  <p role="alert">
                    {t(
                      "This link is incomplete: a fixed record version is required.",
                      "链接不完整：必须指定记录的固定版本。",
                    )}
                  </p>
                )}
                {detail.isPending && search.external_record_version && (
                  <p role="status">
                    {t("Loading fixed detail…", "正在加载固定详情…")}
                  </p>
                )}
                {detail.isError && (
                  <p role="alert">
                    {t(
                      "Detail unavailable. Cached detail is not displayed.",
                      "详情不可用，不显示缓存详情。",
                    )}
                  </p>
                )}
                {detailData && (
                  <div className="min-w-0 space-y-4">
                    <RecordFields
                      record={detailData.record}
                      domain={detailData.version.domain}
                    />
                    <details className="space-y-3 rounded border p-3">
                      <summary className="cursor-pointer font-medium">
                        {t("Version and local identity", "版本与本地身份")}
                      </summary>
                      <VersionInfo version={detailData.version} />
                      <div className="text-sm">
                        <p>{t("Local record identity", "本地记录身份")}</p>
                        <TechnicalValue value={detailData.record.id} />
                        <p>
                          {t("Lossless source ID", "无损源 ID")}:{" "}
                          {detailData.record.source_id}
                        </p>
                        {(detailData.version.domain === "ip" ||
                          detailData.version.domain === "port") && (
                          <p>
                            {t("Canonical IP", "规范化 IP")}:{" "}
                            <FieldValue
                              value={detailData.record.canonical_ip}
                            />
                          </p>
                        )}
                      </div>
                    </details>
                    {detailData.version.domain === "ip" && (
                      <section
                        className="min-w-0 space-y-3 rounded border p-3"
                        aria-labelledby="matches-heading"
                      >
                        <h3 id="matches-heading" className="font-medium">
                          {t(
                            "Same-IP matches across two selected versions",
                            "两个选定版本间的同 IP 匹配",
                          )}
                        </h3>
                        <p className="text-sm">
                          {t(
                            "A query match within the same source and space, NOT a stable foreign key. Every match is preserved. Port records without a matching IP asset remain available in the independent port list.",
                            "仅为同来源、同空间内的查询匹配，不是稳定外键。保留全部匹配；没有对应 IP 对象的端口仍可在独立端口列表中读取。",
                          )}
                        </p>
                        <Label htmlFor="match-port-version">
                          {t("Explicit port version", "显式选择端口版本")}
                        </Label>
                        <select
                          id="match-port-version"
                          className={selectClass}
                          value={search.external_port_version ?? ""}
                          onChange={(event) =>
                            void move({
                              external_port_version:
                                event.target.value || undefined,
                              external_match_page: 0,
                            })
                          }
                        >
                          <option value="">
                            {t(
                              "Choose a port version — no implicit association",
                              "选择端口版本 — 不自动关联",
                            )}
                          </option>
                          {search.external_port_version &&
                            !ports.data?.data.some(
                              (version) =>
                                version.id === search.external_port_version,
                            ) && (
                              <option value={search.external_port_version}>
                                {search.external_port_version}
                              </option>
                            )}
                          {!ports.isError &&
                            ports.data?.data.map((version) => (
                              <option
                                key={version.id}
                                value={version.id}
                                disabled={
                                  version.status === "EXPIRED" ||
                                  Date.parse(version.retain_until) <= Date.now()
                                }
                              >
                                {version.id} ·{" "}
                                {formatDate(version.published_at)} ·{" "}
                                {version.status} ·{" "}
                                {version.complete
                                  ? t("Full requested range", "请求范围完整")
                                  : t("Partial batch", "部分批次")}
                              </option>
                            ))}
                        </select>
                        {ports.isError && (
                          <p role="alert">
                            {t(
                              "Could not read port versions.",
                              "无法读取端口版本。",
                            )}
                          </p>
                        )}
                        {ports.isSuccess && (
                          <ResultPagination
                            label={t("Port versions", "端口版本")}
                            count={ports.data.count}
                            page={portVersionPage}
                            pageSize={SIZE}
                            onPageChange={setPortVersionPage}
                          />
                        )}
                        {search.external_port_version &&
                          detailData.port_version && (
                            <>
                              <VersionInfo version={detailData.port_version} />
                              <p className="text-sm">
                                {t(
                                  `Same-IP matches: ${detailData.matched_port_count}`,
                                  `同 IP 匹配：${detailData.matched_port_count}`,
                                )}
                              </p>
                              {detailData.matched_ports.length ? (
                                renderRows(
                                  detailData.matched_ports,
                                  "port",
                                  detailData.port_version.id,
                                )
                              ) : (
                                <p>
                                  {t(
                                    "No same-IP match in these two versions. This is not evidence that the IP has no open ports.",
                                    "这两个版本之间无同 IP 匹配，不代表此 IP 没有开放端口。",
                                  )}
                                </p>
                              )}
                              <ResultPagination
                                label={t("Same-IP matches", "同 IP 匹配")}
                                count={detailData.matched_port_count}
                                page={search.external_match_page}
                                pageSize={SIZE}
                                onPageChange={(next) =>
                                  void move({ external_match_page: next })
                                }
                              />
                            </>
                          )}
                      </section>
                    )}
                  </div>
                )}
              </div>
            </DialogContent>
          </Dialog>
        </>
      )}
      <Dialog
        open={management !== null}
        onOpenChange={(open) => {
          if (!open) {
            setManagement(null)
            setTaskPage(0)
          }
        }}
      >
        <DialogContent className={`${panelClass} sm:max-w-4xl`}>
          <DialogHeader className="border-b p-4 text-left">
            <DialogTitle>{t("Sync management", "同步管理")}</DialogTitle>
            <DialogDescription>
              {t(
                "Local settings and task history. Opening this panel never starts a source read.",
                "本地配置与任务历史。打开面板不会发起来源读取。",
              )}
            </DialogDescription>
            <p role="status" className="text-sm">
              {notice}
            </p>
            {!allowed && (
              <p role="alert">
                {t(
                  "Record access is unavailable. Only authorized source configuration is shown.",
                  "记录访问不可用；仅显示获准的来源配置。",
                )}
              </p>
            )}
          </DialogHeader>
          <Tabs
            value={!allowed ? "sources" : (management ?? "sources")}
            onValueChange={setManagement}
            className="min-h-0 overflow-hidden"
          >
            <TabsList className="m-4 mb-0 grid h-auto w-auto shrink-0 grid-cols-2 sm:grid-cols-4">
              <TabsTrigger value="sources">
                {t("Sources", "来源配置")}
              </TabsTrigger>
              <TabsTrigger value="sync" disabled={!allowed}>
                {t("Read scope", "同步范围")}
              </TabsTrigger>
              <TabsTrigger value="tasks" disabled={!allowed}>
                {t("Tasks", "任务诊断")}
              </TabsTrigger>
              <TabsTrigger value="versions" disabled={!allowed}>
                {t("Versions", "版本历史")}
              </TabsTrigger>
            </TabsList>
            <div className="min-h-0 overflow-y-auto p-4">
              <TabsContent value="sources" className="space-y-4">
                {sourceControls}
                <section
                  className="space-y-3 rounded border p-4"
                  aria-labelledby="source-heading"
                >
                  <h2 id="source-heading" className="text-lg font-medium">
                    {t("Source configuration", "来源配置")}
                  </h2>
                  <dl className="grid min-w-0 gap-3 text-sm sm:grid-cols-2">
                    <div>
                      <dt>{t("Capability contract", "能力合同")}</dt>
                      <dd>{source.capability_profile}</dd>
                    </div>
                    <div>
                      <dt>
                        {t("Instance / Capset / space", "实例 / Capset / 空间")}
                      </dt>
                      <dd className="break-all">
                        {source.instance_id} / {source.capset_id} /{" "}
                        {source.space_id}
                      </dd>
                    </div>
                    <div>
                      <dt>{t("Metadata validation", "元数据校验")}</dt>
                      <dd>
                        {source.validation_status === "validated"
                          ? t("Validated", "已校验")
                          : source.validation_status === "failed"
                            ? t("Validation failed", "校验失败")
                            : t("Not validated", "未校验")}
                      </dd>
                    </div>
                  </dl>
                  <p className="text-sm">
                    {source.enabled
                      ? t("Synchronization enabled", "同步已启用")
                      : t(
                          "Synchronization disabled — existing local versions remain readable",
                          "同步已停用 — 已有本地版本仍可读取",
                        )}{" "}
                    ·{" "}
                    {source.data_access_enabled
                      ? t(
                          "Historical data access enabled",
                          "历史数据访问已启用",
                        )
                      : t(
                          "Historical data access revoked",
                          "历史数据访问已撤销",
                        )}
                  </p>
                  <details>
                    <summary className="cursor-pointer text-sm">
                      {t("Validated technical fingerprint", "已校验技术指纹")}
                    </summary>
                    <FieldValue value={source.validated_fingerprint} />
                  </details>
                  {canManage && (
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        disabled={busy}
                        onClick={() =>
                          void operation(() =>
                            API.validateExternalSource({
                              projectId,
                              sourceId: source.id,
                            }),
                          )
                        }
                      >
                        {t(
                          "Validate metadata (no source read)",
                          "校验元数据（不读取来源）",
                        )}
                      </Button>
                      <Button
                        variant="outline"
                        disabled={busy}
                        onClick={() =>
                          void operation(() =>
                            API.updateExternalSource({
                              projectId,
                              sourceId: source.id,
                              requestBody: { enabled: !source.enabled },
                            }),
                          )
                        }
                      >
                        {source.enabled
                          ? t("Disable synchronization", "停用同步")
                          : t("Enable synchronization", "启用同步")}
                      </Button>
                      <Button
                        variant="outline"
                        disabled={busy}
                        onClick={() =>
                          void operation(() =>
                            API.updateExternalSource({
                              projectId,
                              sourceId: source.id,
                              requestBody: {
                                data_access_enabled:
                                  !source.data_access_enabled,
                              },
                            }),
                          )
                        }
                      >
                        {source.data_access_enabled
                          ? t(
                              "Revoke historical data access",
                              "撤销历史数据访问",
                            )
                          : t(
                              "Restore historical data access",
                              "恢复历史数据访问",
                            )}
                      </Button>
                    </div>
                  )}
                </section>
              </TabsContent>
              {allowed && (
                <>
                  <TabsContent value="sync">
                    <section
                      className="space-y-4 rounded border p-4"
                      aria-labelledby="sync-heading"
                    >
                      <h2 id="sync-heading" className="text-lg font-medium">
                        {t("Manual synchronization", "手动同步")}
                      </h2>
                      <p className="text-sm text-muted-foreground">
                        {dnsRecords
                          ? t(
                              "Explicit authorization required: DNS records only, flat=1, status=valid, sort=-id. Read serially from page 1; capacity = min(maximum pages, floor(maximum records / page size)), with at least one page. Normal quota completion publishes a partial batch. Anomalies stop calls; no retries, continuation, parsing, asset linking, or other-domain reads. Retention applies only to this new read.",
                              "需显式授权：仅 DNS 记录，flat=1、status=valid、sort=-id。从第 1 页串行读取；容量 = min(最大页数, floor(最大记录数 / 每页条数))，至少一页。正常到额发布部分批次；异常停止，不重试、不续拉、不解析、不关联资产、不读取其他域。保留截止仅适用于本次新增读取。",
                            )
                          : rootDomains
                            ? t(
                                "Explicit authorization required: root domains only, status=valid, sort=-id. Start at page 1 and read serially. Capacity = min(maximum pages, floor(maximum records / page size)), entirely reserved for root domains, with at least one page. Normal quota completion publishes a clearly partial batch; a complete version requires the entire requested range. Any anomaly stops source calls; no retries, continuation, cross-batch merging, or IP/port reads. Retention applies only to this new read.",
                                "需显式授权：仅主域名，过滤 status=valid，排序 -id。从第 1 页串行读取。容量 = min(最大页数, floor(最大记录数 / 每页条数))，全部属于主域名且至少一页。正常到额可发布明确标识的部分批次；读完请求范围才是完整版本。异常停止来源调用，不重试、不续拉、不跨批次合并、不读取 IP 或端口；保留截止仅适用于本次新增读取。",
                              )
                            : t(
                                "Explicit authorization required: IP status=valid; ports use source-default filtering; sort=-id. Both domains start at page 1, alternate serially, and reserve at least one page each. Capacity = min(maximum pages, floor(maximum records / page size)); IP gets the rounded-up half and ports the rounded-down half, with no borrowing. Normal quota completion publishes a clearly partial batch. Any anomaly stops further source calls; no automatic retries or cross-batch merging. Retention applies only to this new read.",
                                "需显式授权：IP 过滤 status=valid；端口采用来源默认过滤；排序 -id。两域均从第 1 页串行轮转，各预留至少一页。容量 = min(最大页数, floor(最大记录数 / 每页条数))；IP 取上半数、端口取下半数，余量不借用。正常达到配额可发布明确标识的部分批次。异常立即停止后续来源调用，不自动重试、不跨批次合并；保留截止仅适用于本次新增读取。",
                              )}
                      </p>
                      {!canManage && (
                        <p>
                          {t(
                            "Only an Operator/Admin in an active project can start or reconcile tasks.",
                            "仅活动项目的操作员 / 管理员可发起或核对任务。",
                          )}
                        </p>
                      )}
                      {storageBroken && (
                        <p role="alert">
                          {t(
                            "The saved submission cannot be read safely. New submissions are blocked: inspect server task history and recover the original browser storage before proceeding.",
                            "无法安全读取已保存的提交。已阻止新提交：请核对服务端任务历史并恢复原浏览器存储后再操作。",
                          )}
                        </p>
                      )}
                      {intent && (
                        <div className="space-y-2 rounded border p-3">
                          <h3 className="font-medium">
                            {t(
                              "Unconfirmed original submission",
                              "尚未确认的原提交",
                            )}
                          </h3>
                          <TechnicalValue
                            value={intent.key}
                            label={t("idempotency key", "幂等键")}
                          />
                          <dl className="grid gap-2 text-sm sm:grid-cols-2">
                            {Object.entries(intent.body).map(([key, value]) => (
                              <div key={key}>
                                <dt>{key}</dt>
                                <dd>{value}</dd>
                              </div>
                            ))}
                          </dl>
                          {intent.source === source.id ? (
                            <Button
                              disabled={!canManage || busy || storageBroken}
                              onClick={() => void sendIntent(intent)}
                            >
                              {t(
                                "Recover submission using the same key",
                                "使用同一幂等键恢复提交",
                              )}
                            </Button>
                          ) : (
                            <Link
                              className="underline"
                              to="/projects/$projectId/cloudatlas-ledger"
                              params={{ projectId }}
                              search={{
                                asset_view: "synced",
                                external_source: intent.source,
                                external_domain: "ip",
                                external_version: undefined,
                                external_record: undefined,
                                external_record_version: undefined,
                                external_port_version: undefined,
                                external_ip: undefined,
                                external_root_domain: undefined,
                                external_subdomain: undefined,
                                external_status: undefined,
                                external_task: undefined,
                                external_page: 0,
                                external_match_page: 0,
                              }}
                            >
                              {t(
                                "Open original source to recover submission",
                                "打开原来源恢复提交",
                              )}
                            </Link>
                          )}
                        </div>
                      )}
                      {canManage && !intent && (
                        <form
                          className="space-y-3"
                          onSubmit={(event) => {
                            event.preventDefault()
                            if (
                              busyRef.current ||
                              storageBroken ||
                              !source.enabled ||
                              unresolved
                            )
                              return
                            const values = new FormData(event.currentTarget)
                            const retention = new Date(
                              String(values.get("retain_until")),
                            )
                            if (
                              !Number.isFinite(retention.getTime()) ||
                              retention.getTime() <= Date.now()
                            ) {
                              setNotice(
                                t(
                                  "Choose a future retention deadline.",
                                  "请选择未来的保留截止时间。",
                                ),
                              )
                              return
                            }
                            const parsed = intentSchema.safeParse({
                              key: crypto.randomUUID(),
                              source: source.id,
                              body: {
                                page_size: Number(values.get("page_size")),
                                max_pages: Number(values.get("max_pages")),
                                max_records: Number(values.get("max_records")),
                                max_response_bytes: Number(
                                  values.get("max_response_bytes"),
                                ),
                                timeout_seconds: Number(
                                  values.get("timeout_seconds"),
                                ),
                                retain_until: retention.toISOString(),
                              },
                            })
                            if (!parsed.success) {
                              setNotice(
                                t(
                                  "Enter every positive integer budget and a retention deadline.",
                                  "请填写全部正整数预算与保留截止时间。",
                                ),
                              )
                              return
                            }
                            if (
                              parsed.data.body.max_pages <
                                (singleDomain ? 1 : 2) ||
                              parsed.data.body.max_records <
                                (singleDomain ? 1 : 2) *
                                  parsed.data.body.page_size
                            ) {
                              setNotice(
                                dnsRecords
                                  ? t(
                                      "Reserve at least one page and at least the page size in records for DNS records.",
                                      "DNS 最大页数至少为 1，最大记录数至少为每页条数。",
                                    )
                                  : rootDomains
                                    ? t(
                                        "Reserve at least one page and at least the page size in records for root domains.",
                                        "主域名最大页数至少为 1，最大记录数至少为每页条数。",
                                      )
                                    : t(
                                        "Reserve at least two pages and twice the page size in records, one page per domain.",
                                        "最大页数至少为 2，最大记录数至少为每页条数的两倍，为每个域预留一页。",
                                      ),
                              )
                              return
                            }
                            try {
                              sessionStorage.setItem(
                                store,
                                JSON.stringify(parsed.data),
                              )
                              setIntent(parsed.data)
                            } catch {
                              setStorageBroken(true)
                              return
                            }
                            void sendIntent(parsed.data)
                          }}
                        >
                          <fieldset
                            disabled={
                              busy ||
                              storageBroken ||
                              !source.enabled ||
                              !!unresolved
                            }
                            className="space-y-3"
                          >
                            <legend className="sr-only">
                              {t(
                                "Synchronization authorization",
                                "同步执行授权",
                              )}
                            </legend>
                            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                              {[
                                {
                                  name: "page_size",
                                  label: t("Page size", "每页条数"),
                                  max: 200,
                                },
                                {
                                  name: "max_pages",
                                  label: t("Maximum pages", "最大页数"),
                                  max: 10000,
                                },
                                {
                                  name: "max_records",
                                  label: t("Maximum records", "最大记录数"),
                                  max: 1000000,
                                },
                                {
                                  name: "max_response_bytes",
                                  label: t(
                                    "Maximum response bytes",
                                    "最大响应字节数",
                                  ),
                                  max: 16777216,
                                },
                                {
                                  name: "timeout_seconds",
                                  label: t("Timeout seconds", "超时秒数"),
                                  max: 300,
                                },
                              ].map(({ name, label, max }) => (
                                <div key={name} className="space-y-1">
                                  <Label htmlFor={`budget-${name}`}>
                                    {label}
                                  </Label>
                                  <Input
                                    id={`budget-${name}`}
                                    name={name}
                                    type="number"
                                    inputMode="numeric"
                                    required
                                    min={1}
                                    max={max}
                                    step={1}
                                  />
                                </div>
                              ))}
                              <div className="space-y-1">
                                <Label htmlFor="retain-until">
                                  {t(
                                    "Retention deadline (your local timezone)",
                                    "保留截止（浏览器本地时区）",
                                  )}
                                </Label>
                                <Input
                                  id="retain-until"
                                  name="retain_until"
                                  type="datetime-local"
                                  required
                                />
                              </div>
                            </div>
                            <Label className="flex items-start gap-2">
                              <input
                                type="checkbox"
                                required
                                className="mt-1"
                              />
                              {t(
                                "I authorize this bounded read and private local retention until the deadline. Expired data is denied immediately; cleanup deletes only the new read model.",
                                "我授权本次有界读取及截止时间前的私有本地保留。数据到期立即拒绝读取；清理仅删除新读模型。",
                              )}
                            </Label>
                            <Button type="submit">
                              {t(
                                "Start authorized synchronization",
                                "开始已授权同步",
                              )}
                            </Button>
                          </fieldset>
                        </form>
                      )}
                      {unresolved && (
                        <p role="status">
                          {t(
                            "An execution is unresolved. Finish or reconcile its original session; a fresh task cannot bypass it.",
                            "存在未决执行。请等待或核对原会话，不可用新任务绕过。",
                          )}
                        </p>
                      )}
                      {canManage && (
                        <Button
                          variant="outline"
                          disabled={busy}
                          onClick={() =>
                            void operation(async () => {
                              const result = await API.purgeExternalExpired({
                                projectId,
                                sourceId: source.id,
                              })
                              return t(
                                `Deleted ${result.deleted_records} expired new-model records; legacy data unchanged.`,
                                `已删除 ${result.deleted_records} 条到期新模型记录，旧数据不变。`,
                              )
                            })
                          }
                        >
                          {t(
                            "Clean up expired local records",
                            "清理已到期本地记录",
                          )}
                        </Button>
                      )}
                    </section>
                  </TabsContent>
                  <TabsContent value="tasks">
                    <section
                      className="space-y-3"
                      aria-labelledby="tasks-heading"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <h2 id="tasks-heading" className="text-lg font-medium">
                          {t(
                            "Persistent synchronization tasks",
                            "持久化同步任务",
                          )}
                        </h2>
                        <Button
                          variant="outline"
                          onClick={() => {
                            void tasks.refetch()
                            if (search.external_task) void task.refetch()
                          }}
                        >
                          {t(
                            "Refresh task status (local)",
                            "刷新任务状态（本地）",
                          )}
                        </Button>
                      </div>
                      <p className="text-sm text-muted-foreground">
                        {t(
                          "Status reads never execute or reconcile tasks. Full completion, normal bounded completion, partial failure, and unknown execution are distinct. Published partial batches never become complete versions; older complete versions remain explicitly selectable until expiry.",
                          "状态读取不会执行或核对任务。全量成功、正常批次完成、部分失败和未知执行分别显示。部分批次不会成为完整版本；旧完整版本在到期前仍可显式选择。",
                        )}
                      </p>
                      {search.external_task && (
                        <div className="space-y-2 rounded border p-3">
                          <h3 className="font-medium">
                            {t("Selected task", "选定任务")}
                          </h3>
                          {task.isPending && (
                            <p role="status">
                              {t("Loading task…", "正在加载任务…")}
                            </p>
                          )}
                          {task.isError && (
                            <p role="alert">
                              {t("Task could not be read.", "无法读取任务。")}
                            </p>
                          )}
                          {task.isSuccess && renderTask(task.data)}
                          <Button
                            variant="outline"
                            onClick={() =>
                              void move({ external_task: undefined })
                            }
                          >
                            {t("Close selected task", "关闭选定任务")}
                          </Button>
                        </div>
                      )}
                      {tasks.isPending && (
                        <p role="status">
                          {t("Loading tasks…", "正在加载任务…")}
                        </p>
                      )}
                      {tasks.isError && (
                        <p role="alert">
                          {t(
                            "Could not read local tasks.",
                            "无法读取本地任务。",
                          )}
                        </p>
                      )}
                      {tasks.isSuccess && (
                        <>
                          {tasks.data.data.length ? (
                            tasks.data.data.map(renderTask)
                          ) : (
                            <p>
                              {t(
                                "No synchronization tasks yet.",
                                "尚无同步任务。",
                              )}
                            </p>
                          )}
                          <ResultPagination
                            label={t("Tasks", "任务")}
                            page={taskPage}
                            pageSize={SIZE}
                            count={tasks.data.count}
                            onPageChange={setTaskPage}
                          />
                        </>
                      )}
                    </section>
                  </TabsContent>
                  <TabsContent value="versions" className="space-y-4">
                    <div className="flex flex-wrap items-center gap-3">
                      <span className="break-all text-sm">
                        {search.external_version
                          ? t(
                              `Fixed version: ${search.external_version}`,
                              `固定版本：${search.external_version}`,
                            )
                          : t(
                              "Latest readable batch pointer (no fallback after expiry)",
                              "最新可读批次指针（到期不回退）",
                            )}
                      </span>
                      <Button
                        variant="outline"
                        onClick={async () => {
                          await cache.cancelQueries({
                            queryKey: [...prefix, "records"],
                          })
                          cache.removeQueries({
                            queryKey: [...prefix, "records"],
                          })
                          setExpired(false)
                          setManagement(null)
                          await move({
                            external_version: undefined,
                            external_page: 0,
                          })
                        }}
                      >
                        {t("Read latest local version", "读取最新本地版本")}
                      </Button>
                      <Button
                        variant="outline"
                        disabled={
                          !versions.isSuccess ||
                          !versions.data.latest_complete_version ||
                          Date.parse(
                            versions.data.latest_complete_version.retain_until,
                          ) <= Date.now()
                        }
                        onClick={() => {
                          const complete =
                            versions.data?.latest_complete_version
                          if (!complete) return
                          setExpired(false)
                          setManagement(null)
                          void move({
                            external_version: complete.id,
                            external_page: 0,
                          })
                        }}
                      >
                        {t(
                          "Read latest usable complete version",
                          "读取最近可用完整版本",
                        )}
                      </Button>
                    </div>
                    <details className="space-y-3" open>
                      <summary className="cursor-pointer font-medium">
                        {t(
                          "Version history (not source change history)",
                          "版本历史（不是来源变更历史）",
                        )}
                      </summary>
                      {versions.isPending && (
                        <p role="status">
                          {t("Loading versions…", "正在加载版本…")}
                        </p>
                      )}
                      {versions.isError && (
                        <p role="alert">
                          {t(
                            "Could not read version history.",
                            "无法读取版本历史。",
                          )}
                        </p>
                      )}
                      {versions.isSuccess && (
                        <>
                          {versions.data.data.length ? (
                            versions.data.data.map((version) => (
                              <article className="space-y-2" key={version.id}>
                                <VersionInfo version={version} />
                                <Button
                                  variant="outline"
                                  disabled={
                                    version.status === "EXPIRED" ||
                                    Date.parse(version.retain_until) <=
                                      Date.now()
                                  }
                                  onClick={() => {
                                    setExpired(false)
                                    setManagement(null)
                                    void move({
                                      external_version: version.id,
                                      external_page: 0,
                                    })
                                    heading.current?.focus()
                                  }}
                                >
                                  {t(
                                    "Read this fixed version",
                                    "读取此固定版本",
                                  )}
                                </Button>
                              </article>
                            ))
                          ) : (
                            <p>
                              {t("No published versions.", "尚无已发布版本。")}
                            </p>
                          )}
                          <ResultPagination
                            label={t("Versions", "版本")}
                            count={versions.data.count}
                            page={versionPage}
                            pageSize={SIZE}
                            onPageChange={setVersionPage}
                          />
                        </>
                      )}
                    </details>
                  </TabsContent>
                </>
              )}
            </div>
          </Tabs>
        </DialogContent>
      </Dialog>
    </div>
  )
}
