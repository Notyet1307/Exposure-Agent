import { useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { useCallback, useEffect, useRef, useState } from "react"
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
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { useI18n } from "@/lib/i18n"

const text = (value: unknown) =>
  typeof value === "string" && value ? value : undefined
const page = (value: unknown) =>
  Number.isSafeInteger(Number(value)) && Number(value) >= 0 ? Number(value) : 0
const SIZE = 25
const selectClass =
  "w-full min-w-0 rounded-md border bg-background px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ring"

export const Route = createFileRoute(
  "/_layout/projects/$projectId/external-assets",
)({
  component: ExternalAssets,
  validateSearch: (s: Record<string, unknown>) => ({
    external_source: text(s.external_source),
    external_domain:
      s.external_domain === "port" ? ("port" as const) : ("ip" as const),
    external_version: text(s.external_version),
    external_record: text(s.external_record),
    external_record_version: text(s.external_record_version),
    external_port_version: text(s.external_port_version),
    external_ip: text(s.external_ip),
    external_status: text(s.external_status),
    external_page: page(s.external_page),
    external_match_page: page(s.external_match_page),
    external_task: text(s.external_task),
  }),
})

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
            <dt className="font-medium">{key}</dt>
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

function RecordFields({
  record,
  domain,
}: {
  record: ExternalRecordPublic
  domain: string
}) {
  const { t } = useI18n()
  const common = [
    "id",
    "ip",
    "status",
    "bu",
    "tags",
    "created_at",
    "updated_at",
    "lastseen_at",
  ]
  const fields = [
    ...common,
    ...(domain === "ip"
      ? [
          "version",
          "subnet",
          "live_port",
          "provider",
          "as_name",
          "as_num",
          "location",
          "country",
          "province",
          "city",
          "sources",
        ]
      : [
          "port",
          "protocol",
          "service",
          "tunnel",
          "product",
          "version",
          "banner",
          "categories",
        ]),
  ]
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
  }
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        {t(
          "Source times are original strings; timezone is unconfirmed. Source status is not local disposition.",
          "源时间保留原字符串，时区未确认。源状态不是本地处置状态。",
        )}
      </p>
      <dl className="grid min-w-0 gap-4 sm:grid-cols-2">
        {fields.map((field) => (
          <div className="min-w-0 rounded border p-3" key={field}>
            <dt className="mb-1 font-medium">{labels[field]}</dt>
            <dd className="min-w-0 text-sm">
              <FieldValue value={record.fields[field]} />
            </dd>
          </div>
        ))}
      </dl>
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
          {version.domain === "ip" ? "IP" : t("Port services", "端口服务")} ·{" "}
          {version.complete
            ? t("Full requested range", "请求范围完整")
            : t("Partial batch", "部分批次")}
          {" · "}
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

function ExternalAssets() {
  const { projectId } = Route.useParams()
  const { user } = useAuth()
  const { t } = useI18n()
  useEffect(() => {
    document.title = t("External assets - Exposure", "外部资产 - Exposure")
  }, [t])
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
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  const cache = useQueryClient()
  const [generation, setGeneration] = useState(0)
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
    if (!search.external_source && data?.data.length) {
      void navigate({
        search: {
          ...search,
          external_source:
            data.data.find((source) => source.enabled)?.id ?? data.data[0].id,
        },
        replace: true,
      })
    }
  }, [data, navigate, search])
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
    await cache.cancelQueries({
      queryKey: ["external-assets", actor, projectId],
    })
    cache.removeQueries({ queryKey: ["external-assets", actor, projectId] })
    await sources.refetch()
    setGeneration((value) => value + 1)
  }
  return (
    <div className="mx-auto w-full max-w-7xl min-w-0 space-y-6 p-2 md:p-4">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">
          {t("External assets", "外部资产")}
        </h1>
        <p className="text-sm text-muted-foreground">
          {t(
            "Independent local IP and port-service versions. Browsing never calls CloudAtlas, OctoBus, or a model.",
            "独立的本地 IP 与端口服务版本。浏览不会调用云图、OctoBus 或模型。",
          )}
        </p>
        <p className="rounded border p-3 text-sm">
          {t(
            "Risks: not connected / deferred. No risk statistics are available.",
            "风险：暂未接入 / 后置。尚无风险统计。",
          )}
        </p>
      </header>
      <div role="status" className="text-sm">
        {notice}
      </div>
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
      <Button
        variant="outline"
        disabled={sources.isFetching}
        onClick={() => void reload()}
      >
        {t("Refresh local access and data", "刷新本地权限与数据")}
      </Button>
      {data && !sources.isFetching && (
        <>
          {!data.can_manage && (
            <p className="text-sm">
              {t(
                "Read only: Viewer role or archived project. Source changes and synchronization are unavailable.",
                "只读：查看者角色或已归档项目。不可更改来源或同步。",
              )}
            </p>
          )}
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
                        external_domain: "ip",
                        external_version: undefined,
                        external_record: undefined,
                        external_record_version: undefined,
                        external_port_version: undefined,
                        external_ip: undefined,
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
                  "No assets-v1 source configured. This does not change the legacy CloudAtlas ledger.",
                  "尚未配置 assets-v1 来源。不影响旧云图原生资产账。",
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
                          instance_id: String(values.get("instance")),
                          capset_id: String(values.get("capset")),
                          space_id: String(values.get("space")),
                        },
                      })
                      form.reset()
                      await sources.refetch()
                      await navigate({
                        search: {
                          external_source: created.id,
                          external_domain: "ip",
                          external_version: undefined,
                          external_record: undefined,
                          external_record_version: undefined,
                          external_port_version: undefined,
                          external_ip: undefined,
                          external_status: undefined,
                          external_task: undefined,
                          external_page: 0,
                          external_match_page: 0,
                        },
                      })
                    } catch (error) {
                      if (
                        error instanceof ApiError &&
                        [401, 403, 404, 410].includes(error.status)
                      )
                        await reload()
                      setNotice(
                        t(
                          "Source was not confirmed. Refresh the source list before trying again.",
                          "未确认来源创建结果。请先刷新来源列表，再决定是否重试。",
                        ),
                      )
                    } finally {
                      setBusy(false)
                    }
                  }}
                >
                  <p className="text-sm text-muted-foreground">
                    {t(
                      "Bind the dedicated assets-v1 OctoBus instance, Capset, and space. Credentials are configured server-side; never paste a token here. Saved version identities cannot be edited in place.",
                      "绑定专用 assets-v1 OctoBus 实例、Capset 与空间。凭据由服务端配置，请勿在此粘贴 Token。已有版本的来源身份不可原地修改。",
                    )}
                  </p>
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
          {selected && (
            <SourceAssets
              key={`${selected.id}:${generation}`}
              actor={actor}
              projectId={projectId}
              source={selected}
              canManage={data.can_manage}
              refreshSources={() => sources.refetch()}
              reload={reload}
            />
          )}
          {search.external_source && !selected && (
            <p role="alert">
              {t(
                "The requested source is unavailable in this project.",
                "请求的来源在本项目中不可用。",
              )}
            </p>
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
}: {
  actor: string
  projectId: string
  source: ExternalSourcePublic
  canManage: boolean
  refreshSources: () => Promise<unknown>
  reload: () => Promise<void>
}) {
  const { showSuccessToast } = useCustomToast()
  const { t, formatDate } = useI18n()
  const search = Route.useSearch()
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
  const move = useCallback(
    (change: Partial<typeof search>, replace = false) =>
      navigate({ search: { ...search, ...change }, replace }),
    [navigate, search],
  )
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
      }
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
    [actor, cache, navigate, projectId],
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
    queryKey: [...prefix, "versions", search.external_domain, versionPage],
    enabled: allowed,
    queryFn: () =>
      guarded(
        API.readExternalVersions({
          projectId,
          sourceId: source.id,
          domain: search.external_domain,
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
      search.external_domain,
      search.external_version,
      search.external_ip,
      search.external_status,
      search.external_page,
    ],
    enabled: allowed && !expired,
    queryFn: () =>
      guarded(
        API.readExternalRecords({
          projectId,
          sourceId: source.id,
          domain: search.external_domain,
          versionId: search.external_version,
          ip: search.external_ip,
          status: search.external_status,
          skip: search.external_page * SIZE,
          limit: SIZE,
        }),
      ),
    retry: false,
  })
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
      search.external_record_version,
      search.external_record,
      search.external_port_version,
      search.external_match_page,
    ],
    enabled:
      allowed &&
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
          portVersionId: search.external_port_version,
          skip: search.external_match_page * SIZE,
          limit: SIZE,
        }),
      ),
    retry: false,
  })
  const ports = useQuery({
    queryKey: [...prefix, "versions", "port", portVersionPage],
    enabled: allowed && !!search.external_record,
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
  const recordData = expired || records.isError ? undefined : records.data
  const detailData = expired || detail.isError ? undefined : detail.data
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
      showSuccessToast(
        typeof result === "string"
          ? result
          : t("Operation confirmed.", "操作已确认。"),
      )
      await cache.invalidateQueries({ queryKey: prefix })
      await refreshSources()
    } catch (error) {
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
      setBusy(false)
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
          to="/projects/$projectId/external-assets"
          params={{ projectId }}
          search={{ ...search, external_task: item.id }}
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
              {domain.domain === "ip" ? "IP" : t("Port services", "端口服务")}
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
                  void move({
                    external_domain: domain.domain,
                    external_version: domain.version_id!,
                    external_page: 0,
                    external_record: undefined,
                    external_record_version: undefined,
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
  const renderRows = (
    items: ExternalRecordPublic[],
    domain: string,
    versionId: string,
  ) => (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>IP</TableHead>
          {domain === "port" && (
            <>
              <TableHead>{t("Port / protocol", "端口 / 协议")}</TableHead>
              <TableHead>
                {t("Service / product / version", "服务 / 产品 / 版本")}
              </TableHead>
            </>
          )}
          <TableHead>{t("Source status", "源状态")}</TableHead>
          <TableHead>{t("Business group", "业务分组")}</TableHead>
          <TableHead>
            {t(
              "Source updated time (timezone unconfirmed)",
              "源更新时间（时区未确认）",
            )}
          </TableHead>
          <TableHead>{t("Details", "详情")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((record) => (
          <TableRow key={record.id}>
            <TableCell className="font-mono">
              <FieldValue value={record.fields.ip} />
            </TableCell>
            {domain === "port" && (
              <>
                <TableCell>
                  <FieldValue value={record.fields.port} /> /{" "}
                  <FieldValue value={record.fields.protocol} />
                </TableCell>
                <TableCell>
                  <FieldValue value={record.fields.service} /> /{" "}
                  <FieldValue value={record.fields.product} /> /{" "}
                  <FieldValue value={record.fields.version} />
                </TableCell>
              </>
            )}
            <TableCell>
              <FieldValue value={record.fields.status} />
            </TableCell>
            <TableCell>
              <FieldValue value={record.fields.bu} />
            </TableCell>
            <TableCell>
              <FieldValue value={record.fields.updated_at} />
            </TableCell>
            <TableCell>
              <Link
                className="underline underline-offset-4"
                to="/projects/$projectId/external-assets"
                params={{ projectId }}
                search={{
                  ...search,
                  external_record: record.id,
                  external_record_version: versionId,
                  external_port_version: undefined,
                  external_match_page: 0,
                }}
                aria-label={t(
                  `Details for ${record.ip}, source ID ${record.source_id}`,
                  `${record.ip} 的详情，源 ID ${record.source_id}`,
                )}
              >
                {t("Details", "详情")}
              </Link>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
  return (
    <div className="min-w-0 space-y-6">
      <section
        className="space-y-3 rounded border p-4"
        aria-labelledby="source-heading"
      >
        <h2 id="source-heading" className="text-lg font-medium">
          {t("Source configuration", "来源配置")}
        </h2>
        <dl className="grid min-w-0 gap-3 text-sm sm:grid-cols-2">
          <div>
            <dt>{t("Instance / Capset / space", "实例 / Capset / 空间")}</dt>
            <dd className="break-all">
              {source.instance_id} / {source.capset_id} / {source.space_id}
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
            ? t("Historical data access enabled", "历史数据访问已启用")
            : t("Historical data access revoked", "历史数据访问已撤销")}
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
                      data_access_enabled: !source.data_access_enabled,
                    },
                  }),
                )
              }
            >
              {source.data_access_enabled
                ? t("Revoke historical data access", "撤销历史数据访问")
                : t("Restore historical data access", "恢复历史数据访问")}
            </Button>
          </div>
        )}
      </section>
      <p role="status" className="text-sm">
        {notice}
      </p>
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
          <section
            className="space-y-4 rounded border p-4"
            aria-labelledby="sync-heading"
          >
            <h2 id="sync-heading" className="text-lg font-medium">
              {t("Manual synchronization", "手动同步")}
            </h2>
            <p className="text-sm text-muted-foreground">
              {t(
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
                  {t("Unconfirmed original submission", "尚未确认的原提交")}
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
                    to="/projects/$projectId/external-assets"
                    params={{ projectId }}
                    search={{
                      external_source: intent.source,
                      external_domain: "ip",
                      external_version: undefined,
                      external_record: undefined,
                      external_record_version: undefined,
                      external_port_version: undefined,
                      external_ip: undefined,
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
                  const retention = new Date(String(values.get("retain_until")))
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
                      timeout_seconds: Number(values.get("timeout_seconds")),
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
                    parsed.data.body.max_pages < 2 ||
                    parsed.data.body.max_records <
                      2 * parsed.data.body.page_size
                  ) {
                    setNotice(
                      t(
                        "Reserve at least two pages and twice the page size in records, one page per domain.",
                        "最大页数至少为 2，最大记录数至少为每页条数的两倍，为每个域预留一页。",
                      ),
                    )
                    return
                  }
                  try {
                    sessionStorage.setItem(store, JSON.stringify(parsed.data))
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
                    busy || storageBroken || !source.enabled || !!unresolved
                  }
                  className="space-y-3"
                >
                  <legend className="sr-only">
                    {t("Synchronization authorization", "同步执行授权")}
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
                        label: t("Maximum response bytes", "最大响应字节数"),
                        max: 16777216,
                      },
                      {
                        name: "timeout_seconds",
                        label: t("Timeout seconds", "超时秒数"),
                        max: 300,
                      },
                    ].map(({ name, label, max }) => (
                      <div key={name} className="space-y-1">
                        <Label htmlFor={`budget-${name}`}>{label}</Label>
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
                    <input type="checkbox" required className="mt-1" />
                    {t(
                      "I authorize this bounded read and private local retention until the deadline. Expired data is denied immediately; cleanup deletes only the new read model.",
                      "我授权本次有界读取及截止时间前的私有本地保留。数据到期立即拒绝读取；清理仅删除新读模型。",
                    )}
                  </Label>
                  <Button type="submit">
                    {t("Start authorized synchronization", "开始已授权同步")}
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
                {t("Clean up expired local records", "清理已到期本地记录")}
              </Button>
            )}
          </section>
          <section className="space-y-3" aria-labelledby="tasks-heading">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 id="tasks-heading" className="text-lg font-medium">
                {t("Persistent synchronization tasks", "持久化同步任务")}
              </h2>
              <Button
                variant="outline"
                onClick={() => {
                  void tasks.refetch()
                  if (search.external_task) void task.refetch()
                }}
              >
                {t("Refresh task status (local)", "刷新任务状态（本地）")}
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
                  <p role="status">{t("Loading task…", "正在加载任务…")}</p>
                )}
                {task.isError && (
                  <p role="alert">
                    {t("Task could not be read.", "无法读取任务。")}
                  </p>
                )}
                {task.isSuccess && renderTask(task.data)}
                <Button
                  variant="outline"
                  onClick={() => void move({ external_task: undefined })}
                >
                  {t("Close selected task", "关闭选定任务")}
                </Button>
              </div>
            )}
            {tasks.isPending && (
              <p role="status">{t("Loading tasks…", "正在加载任务…")}</p>
            )}
            {tasks.isError && (
              <p role="alert">
                {t("Could not read local tasks.", "无法读取本地任务。")}
              </p>
            )}
            {tasks.isSuccess && (
              <>
                {tasks.data.data.length ? (
                  tasks.data.data.map(renderTask)
                ) : (
                  <p>{t("No synchronization tasks yet.", "尚无同步任务。")}</p>
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
            <div className="space-y-1">
              <Label htmlFor="external-domain">
                {t("Asset domain", "资产域")}
              </Label>
              <select
                id="external-domain"
                className={selectClass}
                value={search.external_domain}
                onChange={(event) => {
                  setExpired(false)
                  setVersionPage(0)
                  void move({
                    external_domain:
                      event.target.value === "port" ? "port" : "ip",
                    external_version: undefined,
                    external_page: 0,
                    external_record: undefined,
                    external_record_version: undefined,
                    external_port_version: undefined,
                    external_status: undefined,
                  })
                }}
              >
                <option value="ip">
                  {t(
                    "IP assets — source status=valid",
                    "IP 资产 — 来源过滤 status=valid",
                  )}
                </option>
                <option value="port">
                  {t(
                    "Port services — source-default filtering",
                    "端口服务 — 来源默认过滤",
                  )}
                </option>
              </select>
            </div>
            <p className="text-sm text-muted-foreground">
              {t(
                "Partial batches contain only their fetched pages; local count is not source total. A complete version covers only its fixed requested range, not all upstream states or a guaranteed snapshot. Source IDs identify records within a version, not stable cross-version entities.",
                "部分批次仅包含已抓取页面，本地条数不是来源总量。完整版本也仅覆盖固定请求范围，不代表上游全部状态或一致性快照。源 ID 仅标识版本内记录，不是跨版本稳定实体。",
              )}
            </p>
            <form
              key={`${search.external_ip}:${search.external_status}`}
              className="flex flex-wrap items-end gap-3"
              onSubmit={(event) => {
                event.preventDefault()
                const form = new FormData(event.currentTarget)
                void move({
                  external_ip: String(form.get("ip") ?? "").trim() || undefined,
                  external_status:
                    String(form.get("status") ?? "").trim() || undefined,
                  external_page: 0,
                })
                heading.current?.focus()
              }}
            >
              <div className="min-w-0 space-y-1">
                <Label htmlFor="filter-ip">
                  {t("Exact IP (IPv4 or IPv6)", "精确 IP（IPv4 或 IPv6）")}
                </Label>
                <Input
                  id="filter-ip"
                  name="ip"
                  defaultValue={search.external_ip ?? ""}
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
                    external_status: undefined,
                    external_page: 0,
                  })
                }
              >
                {t("Clear filters", "清除筛选")}
              </Button>
            </form>
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
                  cache.removeQueries({ queryKey: [...prefix, "records"] })
                  setExpired(false)
                  await move({ external_version: undefined, external_page: 0 })
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
                  const complete = versions.data?.latest_complete_version
                  if (!complete) return
                  setExpired(false)
                  void move({ external_version: complete.id, external_page: 0 })
                }}
              >
                {t(
                  "Read latest usable complete version",
                  "读取最近可用完整版本",
                )}
              </Button>
            </div>
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
                {t(
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
                <VersionInfo version={recordData.version} />
                {recordData.data.length ? (
                  renderRows(
                    recordData.data,
                    search.external_domain,
                    recordData.version.id,
                  )
                ) : (
                  <p>
                    {recordData.version.record_count === 0
                      ? t(
                          "Published complete empty version for the requested range.",
                          "此请求范围已发布完整空版本。",
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
            <details className="space-y-3" open>
              <summary className="cursor-pointer font-medium">
                {t(
                  "Version history (not source change history)",
                  "版本历史（不是来源变更历史）",
                )}
              </summary>
              {versions.isPending && (
                <p role="status">{t("Loading versions…", "正在加载版本…")}</p>
              )}
              {versions.isError && (
                <p role="alert">
                  {t("Could not read version history.", "无法读取版本历史。")}
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
                            Date.parse(version.retain_until) <= Date.now()
                          }
                          onClick={() => {
                            setExpired(false)
                            void move({
                              external_version: version.id,
                              external_page: 0,
                            })
                            heading.current?.focus()
                          }}
                        >
                          {t("Read this fixed version", "读取此固定版本")}
                        </Button>
                      </article>
                    ))
                  ) : (
                    <p>{t("No published versions.", "尚无已发布版本。")}</p>
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
                heading.current?.focus()
              }
            }}
          >
            <DialogContent className="max-h-[90vh] max-w-[calc(100%-2rem)] overflow-y-auto sm:max-w-5xl">
              <DialogHeader>
                <DialogTitle>
                  {t("Fixed-version record details", "固定版本记录详情")}
                </DialogTitle>
                <DialogDescription>
                  {t(
                    "The URL fixes the source, domain version and record. Text is escaped; source times are not converted to UTC.",
                    "网址固定来源、域版本与记录。文本转义显示，源时间不转换为 UTC。",
                  )}
                </DialogDescription>
              </DialogHeader>
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
                  <VersionInfo version={detailData.version} />
                  <div className="text-sm">
                    <p>{t("Local record identity", "本地记录身份")}</p>
                    <TechnicalValue value={detailData.record.id} />
                    <p>
                      {t("Lossless source ID", "无损源 ID")}:{" "}
                      {detailData.record.source_id}
                    </p>
                    <p>
                      {t("Canonical IP", "规范化 IP")}:{" "}
                      {detailData.record.canonical_ip}
                    </p>
                  </div>
                  <RecordFields
                    record={detailData.record}
                    domain={detailData.version.domain}
                  />
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
                              {version.id} · {formatDate(version.published_at)}{" "}
                              · {version.status} ·{" "}
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
            </DialogContent>
          </Dialog>
        </>
      )}
    </div>
  )
}
