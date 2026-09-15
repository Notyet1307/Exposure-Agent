import { useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { useEffect, useRef, useState } from "react"
import {
  CloudatlasLedgerService as API,
  ApiError,
  CloudatlasSourceInstancesService,
  type CloudLedgerEdit,
  type CloudLedgerEntry,
  type CloudRevisionPublic,
} from "@/client"
import { ResultPagination } from "@/components/ResultPagination"
import { TechnicalValue } from "@/components/TechnicalValue"
import { Button } from "@/components/ui/button"
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
import { useI18n } from "@/lib/i18n"
import { requestDigest } from "@/lib/ledgerIntent"

const text = (v: unknown) => (typeof v === "string" ? v : undefined)
const number = (v: unknown) =>
  v !== undefined &&
  v !== "" &&
  Number.isSafeInteger(Number(v)) &&
  Number(v) >= 0
    ? Number(v)
    : undefined
export const Route = createFileRoute(
  "/_layout/projects/$projectId/cloudatlas-ledger",
)({
  component: CloudLedger,
  validateSearch: (s: Record<string, unknown>) => ({
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
  }),
})
type Pending = {
  key: string
  digest: string
  snapshot: string
  revision: number
  kind: CloudLedgerEdit["kind"]
  observation: string | null
}
const SIZE = 25
function CloudLedger() {
  const { projectId } = Route.useParams()
  const { user } = useAuth()
  const { t } = useI18n()
  useEffect(() => {
    document.title = t(
      "CloudAtlas ledger - Exposure",
      "云图原生资产账 - Exposure",
    )
  }, [t])
  return user ? (
    <Ledger
      key={`${user.id}:${projectId}`}
      actor={user.id}
      projectId={projectId}
    />
  ) : null
}
function Ledger({ actor, projectId }: { actor: string; projectId: string }) {
  const { t, formatDate } = useI18n()
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  const cache = useQueryClient()
  const scope = `${search.cloud_source}/${search.cloud_snapshot}/${search.cloud_revision}`
  const live = useRef(true)
  const scopeRef = useRef(scope)
  scopeRef.current = scope
  useEffect(() => {
    live.current = true
    return () => {
      live.current = false
    }
  }, [])
  const here = (captured: string) =>
    live.current && scopeRef.current === captured
  const store = `exposure:cloud-ledger:${actor}:${projectId}`
  const [pending, setPending] = useState<Pending | null>(() => {
    try {
      const p = JSON.parse(
        sessionStorage.getItem(store) ?? "null",
      ) as Pending | null
      return p &&
        /^[A-Za-z0-9_-]{1,128}$/.test(p.key) &&
        /^[a-f0-9]{64}$/.test(p.digest) &&
        typeof p.snapshot === "string" &&
        Number.isSafeInteger(p.revision) &&
        ["scope", "management"].includes(p.kind)
        ? p
        : null
    } catch {
      return null
    }
  })
  const [editor, setEditor] = useState<{
    scope: string
    body: CloudLedgerEdit
  } | null>(null)
  const [selected, setSelected] = useState<{
    scope: string
    row: CloudLedgerEntry
  } | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState("")
  const [query, setQuery] = useState(
    search.cloud_ip ?? search.cloud_asset ?? "",
  )
  const [queryKind, setQueryKind] = useState("ip")
  const [historyPage, setHistoryPage] = useState(0)
  const [snapshotsPage, setSnapshotsPage] = useState(0)
  const heading = useRef<HTMLHeadingElement>(null)
  const formHeading = useRef<HTMLHeadingElement>(null)
  const source = useQuery({
    queryKey: ["cloud-ledger-sources", actor, projectId],
    queryFn: () =>
      CloudatlasSourceInstancesService.readCloudatlasSources({ projectId }),
    retry: false,
  })
  const ledger = useQuery({
    queryKey: [
      "cloud-ledger",
      actor,
      projectId,
      search.cloud_source,
      search.cloud_snapshot,
      search.cloud_revision,
      search.cloud_page,
      search.cloud_ip,
      search.cloud_asset,
    ],
    queryFn: () =>
      API.readCloudatlasLedger({
        projectId,
        sourceId: search.cloud_source,
        snapshotId: search.cloud_snapshot,
        revision: search.cloud_revision,
        ip: search.cloud_ip,
        assetId: search.cloud_asset,
        skip: search.cloud_page * SIZE,
        limit: SIZE,
      }),
    retry: false,
  })
  const data = ledger.isError ? undefined : ledger.data
  const pinned =
    !!data?.snapshot_id &&
    search.cloud_snapshot === data.snapshot_id &&
    search.cloud_revision === data.revision &&
    search.cloud_source === data.source_instance_id
  const move = (change: Partial<typeof search>, replace = false) =>
    navigate({ search: { ...search, ...change }, replace })
  useEffect(() => {
    if (data?.snapshot_id && !pinned && !ledger.isFetching)
      void navigate({
        search: {
          ...search,
          cloud_snapshot: data.snapshot_id,
          cloud_source: data.source_instance_id ?? undefined,
          cloud_revision: data.revision ?? 0,
        },
        replace: true,
      })
  }, [data, pinned, ledger.isFetching, navigate, search])
  useEffect(() => {
    if (editor && editor.scope !== scope) setEditor(null)
    if (selected && selected.scope !== scope) setSelected(null)
    setNotice("")
  }, [scope, editor, selected])
  useEffect(() => {
    if (editor?.scope === scope) formHeading.current?.focus()
  }, [editor?.scope, scope])
  const versions = useQuery({
    queryKey: [
      "cloud-ledger-snapshots",
      actor,
      projectId,
      data?.source_instance_id,
      snapshotsPage,
    ],
    enabled: !!data?.source_instance_id,
    queryFn: () =>
      API.readCloudatlasLedgerSnapshots({
        projectId,
        sourceId: data!.source_instance_id!,
        skip: snapshotsPage * SIZE,
        limit: SIZE,
      }),
    retry: false,
  })
  const history = useQuery({
    queryKey: [
      "cloud-ledger-history",
      actor,
      projectId,
      data?.snapshot_id,
      historyPage,
    ],
    enabled: pinned,
    queryFn: () =>
      API.readCloudatlasLedgerRevisions({
        projectId,
        snapshotId: data!.snapshot_id!,
        skip: historyPage * SIZE,
        limit: SIZE,
      }),
    retry: false,
  })
  const profile = useQuery({
    queryKey: [
      "cloud-ledger-profile",
      actor,
      projectId,
      search.cloud_snapshot,
      search.cloud_revision,
      search.profile_ip,
      search.customer_upload,
      search.customer_revision,
      search.customer_page,
      search.profile_cloud_page,
    ],
    enabled: pinned && !!search.profile_ip,
    queryFn: () =>
      API.readCloudatlasIpProfile({
        projectId,
        snapshotId: search.cloud_snapshot!,
        revision: search.cloud_revision,
        ip: search.profile_ip!,
        uploadId: search.customer_upload,
        customerRevisionId: search.customer_revision,
        customerOriginal: !!search.customer_upload && !search.customer_revision,
        customerSkip: search.customer_page * SIZE,
        cloudSkip: search.profile_cloud_page * SIZE,
        limit: SIZE,
      }),
    retry: false,
  })
  useEffect(() => {
    if (
      profile.isSuccess &&
      !profile.isFetching &&
      profile.data.customer.upload_id &&
      !search.customer_upload
    )
      void navigate({
        search: {
          ...search,
          customer_upload: profile.data.customer.upload_id,
          customer_revision: profile.data.customer.revision_id ?? undefined,
        },
        replace: true,
      })
  }, [profile.isSuccess, profile.isFetching, profile.data, search, navigate])
  const editable =
    pinned &&
    data?.can_manage &&
    data.revision === data.current_revision &&
    !ledger.isFetching
  const activeEditor = editor?.scope === scope ? editor.body : null
  const activeRow = selected?.scope === scope ? selected.row : null
  const pendingHere =
    pending?.snapshot === search.cloud_snapshot &&
    pending?.revision === search.cloud_revision
  const failure = (e: unknown) =>
    e instanceof ApiError && e.status === 409
      ? t(
          "Version or operation conflict. Read the original operation and reload the current revision.",
          "版本或操作冲突。请查询原操作并读取当前修订。",
        )
      : e instanceof ApiError && [403, 404].includes(e.status)
        ? t(
            "This scope is unavailable or access was removed.",
            "此范围不可用或权限已撤销。",
          )
        : t(
            "Could not confirm the result. Check the original operation before retrying.",
            "无法确认结果。重试前请查询原操作。",
          )
  const state = (value?: string) =>
    ({
      NO_SOURCE: t("No enabled source selected", "未选择已启用来源"),
      NOT_READ: t("No source snapshot yet", "尚无已落地快照"),
      READING: t("Source read in progress", "来源正在读取"),
      READ_FAILED: t("Source read failed", "来源读取失败"),
      READ_UNPUBLISHED: t(
        "Read finished; Run not published",
        "读取已完成，批次尚未发布",
      ),
      DOWNSTREAM_FAILED: t(
        "Source read completed; later processing failed",
        "来源读取已完成，后续处理失败",
      ),
      PUBLISHED: t("Published", "已发布"),
      PRESENT: t("Complete published snapshot", "完整已发布快照"),
      EMPTY: t("Successful empty snapshot", "成功读取的空快照"),
      UNKNOWN: t("Network scope not confirmed", "网络范围尚未确认"),
      SEPARATE: t("Separate from customer address space", "与客户地址空间分离"),
      CONFIRMED_LEGACY: t(
        "Confirmed same legacy Project space",
        "已确认同属项目既有地址空间",
      ),
      REVOKED: t(
        "Historical confirmation no longer authorizes association",
        "历史确认已不能用于当前关联",
      ),
    })[value ?? ""] ?? t("Unavailable", "不可用")
  const start = (kind: CloudLedgerEdit["kind"], row?: CloudLedgerEntry) => {
    if (!editable || pending || (kind === "scope" && !data?.can_confirm_scope))
      return
    setEditor({
      scope,
      body: {
        snapshot_id: data!.snapshot_id!,
        expected_revision: data!.revision ?? 0,
        kind,
        observation_id: row?.observation_id ?? null,
        tags: row?.tags ?? [],
        followed: row?.followed ?? false,
        scope_state: kind === "scope" ? "UNKNOWN" : null,
        reason: "",
      },
    })
  }
  const accept = async (result: CloudRevisionPublic, captured: string) => {
    sessionStorage.removeItem(store)
    if (!here(captured)) return
    setPending(null)
    setEditor(null)
    setSelected(null)
    await cache.invalidateQueries({ queryKey: ["cloud-ledger"] })
    await cache.invalidateQueries({ queryKey: ["cloud-ledger-history"] })
    await cache.invalidateQueries({ queryKey: ["cloud-ledger-profile"] })
    if (here(captured)) {
      await move({ cloud_revision: result.revision })
      setNotice(t("Saved as a new local revision.", "已保存为新的本地修订。"))
      heading.current?.focus()
    }
  }
  const save = async () => {
    if (!activeEditor || !editable || busy) return
    const captured = scope
    const body = activeEditor
    setBusy(true)
    try {
      const digest = await requestDigest(body)
      if (!here(captured)) return
      if (pending && (!pendingHere || pending.digest !== digest)) {
        setNotice(
          t(
            "Re-enter the exact original intent to recover it.",
            "请重填与原操作完全一致的内容后恢复。",
          ),
        )
        return
      }
      const intent = pending ?? {
        key: crypto.randomUUID(),
        digest,
        snapshot: body.snapshot_id,
        revision: body.expected_revision,
        kind: body.kind,
        observation: body.observation_id ?? null,
      }
      sessionStorage.setItem(store, JSON.stringify(intent))
      setPending(intent)
      await accept(
        await API.createCloudatlasLedgerRevision({
          projectId,
          idempotencyKey: intent.key,
          requestBody: body,
        }),
        captured,
      )
    } catch (e) {
      if (here(captured)) {
        const code =
          e instanceof ApiError
            ? (e.body as { detail?: { code?: string } })?.detail?.code
            : undefined
        if (
          e instanceof ApiError &&
          (e.status === 422 || code === "cloud_ledger_version_conflict")
        ) {
          sessionStorage.removeItem(store)
          setPending(null)
          setNotice(
            e.status === 422
              ? t(
                  "Input rejected. Correct the fields and save again.",
                  "输入已被拒绝。请修正字段后重新保存。",
                )
              : failure(e),
          )
          if (code === "cloud_ledger_version_conflict")
            await cache.invalidateQueries({ queryKey: ["cloud-ledger"] })
        } else setNotice(failure(e))
      }
    } finally {
      if (live.current) setBusy(false)
    }
  }
  const recover = async () => {
    if (!pending || !pendingHere || busy) return
    const captured = scope
    setBusy(true)
    try {
      await accept(
        await API.readCloudatlasLedgerOperation({
          projectId,
          operationKey: pending.key,
        }),
        captured,
      )
    } catch (e) {
      if (here(captured))
        setNotice(
          e instanceof ApiError && e.status === 404
            ? t(
                "No committed result found. Re-enter the same intent and submit with the original key.",
                "尚未找到已提交结果。可重填原内容，使用原操作键恢复提交。",
              )
            : failure(e),
        )
    } finally {
      if (live.current) setBusy(false)
    }
  }
  const details = (row: CloudLedgerEntry) => (
    <details className="max-w-xl">
      <summary className="cursor-pointer">
        {t("Source identity", "来源身份")}
      </summary>
      <div className="space-y-2 py-2">
        <TechnicalValue
          value={row.asset_id}
          label={t("CloudAtlas ID", "云图 ID")}
        />
        <TechnicalValue
          value={row.observation_id}
          label={t("Observation", "来源记录")}
        />
        <p className="break-all">
          {t("Source record", "来源行")}：{row.source_record_key}
        </p>
        <p className="break-all">
          {t("Original IP", "原始 IP")}：{row.raw_ip}
        </p>
      </div>
    </details>
  )
  return (
    <div className="min-w-0 space-y-6">
      <header className="space-y-3">
        <h1
          ref={heading}
          tabIndex={-1}
          className="text-2xl font-bold tracking-tight"
        >
          {t("CloudAtlas native ledger", "云图原生资产账")}
        </h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          {t(
            "Read complete published source records. Tags and attention are local; source status is unchanged.",
            "阅读完整已发布来源记录。标签与关注只保存在本地，不改变云图原值。",
          )}
        </p>
        <p className="text-sm text-muted-foreground">
          {t(
            "This source includes confirmed (valid) records only. Risk evidence is not connected.",
            "当前来源只包含已确认（valid）记录。尚未接入风险证据。",
          )}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline">
            <Link to="/" search={{ project: projectId, view: "cloudatlas" }}>
              {t("Source configuration", "来源配置")}
            </Link>
          </Button>
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => {
              setHistoryPage(0)
              void move({
                cloud_snapshot: undefined,
                cloud_revision: undefined,
                cloud_page: 0,
                profile_ip: undefined,
                customer_upload: undefined,
                customer_revision: undefined,
              })
            }}
          >
            {t("Read latest published snapshot", "读取最新已发布快照")}
          </Button>
        </div>
      </header>
      <div className="flex flex-wrap items-end gap-3">
        <Label className="flex flex-col gap-2">
          {t("Source instance", "来源实例")}
          <select
            className="max-w-72 rounded-md border bg-background p-2"
            value={data?.source_instance_id ?? search.cloud_source ?? ""}
            disabled={busy || !source.isSuccess}
            onChange={(e) => {
              setSnapshotsPage(0)
              setHistoryPage(0)
              void move({
                cloud_source: e.target.value,
                cloud_snapshot: undefined,
                cloud_revision: undefined,
                cloud_page: 0,
                profile_ip: undefined,
                customer_upload: undefined,
                customer_revision: undefined,
              })
            }}
          >
            <option value="">{t("Select source", "选择来源")}</option>
            {source.data?.data.map((s, i) => (
              <option key={s.id} value={s.id}>
                {t(`Source ${i + 1}`, `来源 ${i + 1}`)}
                {s.enabled
                  ? t(" · enabled", " · 已启用")
                  : t(" · disabled", " · 已停用")}
              </option>
            ))}
          </select>
        </Label>
        <p className="text-sm">{state(data?.state)}</p>
      </div>
      {source.isError && (
        <p role="alert">
          {t("Could not read source choices.", "无法读取来源选项。")}
        </p>
      )}
      {ledger.isPending || ledger.isFetching ? (
        <p role="status">
          {t("Reading fixed source records…", "正在读取固定来源记录…")}
        </p>
      ) : null}
      {ledger.isError && (
        <p role="alert">
          {t(
            "Source records could not be verified. No other snapshot is substituted.",
            "来源记录未能通过读取校验，未替换为其他快照。",
          )}
        </p>
      )}
      {notice && (
        <p role="status" className="rounded-md border p-3">
          {notice}
        </p>
      )}
      {pending && (
        <section className="space-y-2 rounded-md border p-3">
          <h2 className="font-semibold">
            {t("Unconfirmed local operation", "待确认的本地操作")}
          </h2>
          <p className="text-sm">
            {t(
              "Check the original operation; refreshing never resubmits it.",
              "查询原操作结果；刷新不会自动重复提交。",
            )}
          </p>
          {pendingHere ? (
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => void recover()}
              >
                {t("Check original operation", "查询原操作")}
              </Button>
              <Button
                variant="outline"
                disabled={
                  busy ||
                  !editable ||
                  (pending.kind === "scope" && !data?.can_confirm_scope)
                }
                onClick={() =>
                  setEditor({
                    scope,
                    body: {
                      snapshot_id: pending.snapshot,
                      expected_revision: pending.revision,
                      kind: pending.kind,
                      observation_id: pending.observation,
                      tags: [],
                      followed: false,
                      scope_state: pending.kind === "scope" ? "UNKNOWN" : null,
                      reason: "",
                    },
                  })
                }
              >
                {t("Re-enter original intent", "重填原操作内容")}
              </Button>
            </div>
          ) : (
            <Button
              variant="outline"
              onClick={() =>
                void move({
                  cloud_source: undefined,
                  cloud_snapshot: pending.snapshot,
                  cloud_revision: pending.revision,
                  cloud_page: 0,
                  profile_ip: undefined,
                })
              }
            >
              {t("Return to operation snapshot", "返回原操作快照")}
            </Button>
          )}
        </section>
      )}
      {data?.snapshot_id && (
        <>
          <section className="space-y-2 border-y py-4">
            <p>
              {t("Source as of", "来源截至")}{" "}
              {formatDate(data.source_created_at!)} ·{" "}
              {t("Local revision", "本地修订")} {data.revision}
            </p>
            <p>
              {t("Source rows", "来源行数")}：{data.total_records} ·{" "}
              {t("Canonical addresses", "规范地址数")}：{data.unique_ips}
            </p>
            <p className="text-sm">
              {t("Latest attempt for this source", "此来源最近一次尝试")}：
              {state(data.latest_attempt_state)}
              {data.latest_attempt_at
                ? ` · ${formatDate(data.latest_attempt_at)}`
                : ""}
            </p>
            <p>{state(data.association)}</p>
            <Button
              variant="outline"
              disabled={
                !editable || !data.can_confirm_scope || !!pending || busy
              }
              onClick={() => start("scope")}
            >
              {t("Confirm network relationship", "确认网络范围关系")}
            </Button>
            <details>
              <summary className="cursor-pointer">
                {t("Snapshot references", "快照依据")}
              </summary>
              <div className="space-y-2 py-2">
                {[
                  data.source_instance_id,
                  data.snapshot_id,
                  data.governance_run_id,
                  data.content_sha256,
                ].map((v) => (
                  <div key={v}>
                    <TechnicalValue value={v ?? ""} />
                  </div>
                ))}
              </div>
            </details>
          </section>
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              void move({
                cloud_ip: queryKind === "ip" && query ? query : undefined,
                cloud_asset: queryKind === "id" && query ? query : undefined,
                cloud_page: 0,
              })
            }}
          >
            <Label className="flex flex-col gap-2">
              {t("Search by", "查询方式")}
              <select
                className="rounded-md border bg-background p-2"
                value={queryKind}
                onChange={(e) => setQueryKind(e.target.value)}
              >
                <option value="ip">IP</option>
                <option value="id">{t("CloudAtlas ID", "云图 ID")}</option>
              </select>
            </Label>
            <Label className="flex min-w-48 flex-1 flex-col gap-2">
              {t("Exact IP or ID", "精确 IP 或 ID")}
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                maxLength={255}
              />
            </Label>
            <Button type="submit">{t("Search", "查询")}</Button>
            <Button
              type="button"
              variant="outline"
              disabled={queryKind !== "ip" || !query || !pinned}
              onClick={() =>
                void move({
                  profile_ip: query,
                  customer_page: 0,
                  profile_cloud_page: 0,
                  customer_upload: undefined,
                  customer_revision: undefined,
                })
              }
            >
              {t("Query IP profile", "查询 IP 画像")}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setQuery("")
                void move({
                  cloud_ip: undefined,
                  cloud_asset: undefined,
                  cloud_page: 0,
                })
              }}
            >
              {t("Clear", "清除筛选")}
            </Button>
          </form>
          <section
            className="overflow-x-auto rounded-md border [&>[data-slot=table-container]]:overflow-visible"
            // biome-ignore lint/a11y/noNoninteractiveTabindex: keyboard users must be able to scroll this table region.
            tabIndex={0}
            aria-label={t("CloudAtlas source records", "云图来源记录")}
          >
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>IP</TableHead>
                  <TableHead>{t("Source status", "云图原状态")}</TableHead>
                  <TableHead>
                    {t("Local tags / attention", "本地标签 / 关注")}
                  </TableHead>
                  <TableHead>{t("Actions", "操作")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.data?.map((row) => (
                  <TableRow key={row.observation_id}>
                    <TableCell>
                      <button
                        type="button"
                        className="text-left underline underline-offset-4 focus-visible:outline-2"
                        onClick={() => setSelected({ scope, row })}
                      >
                        {row.canonical_ip}
                      </button>
                    </TableCell>
                    <TableCell>{row.source_status}</TableCell>
                    <TableCell className="max-w-64 whitespace-normal break-words">
                      {row.tags?.join("、") || "—"}
                      {row.followed ? t(" · Followed", " · 已关注") : ""}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            void move({
                              profile_ip: row.canonical_ip,
                              customer_page: 0,
                              profile_cloud_page: 0,
                              customer_upload: undefined,
                              customer_revision: undefined,
                            })
                          }
                        >
                          {t("IP profile", "IP 画像")}
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={!editable || !!pending || busy}
                          onClick={() => start("management", row)}
                        >
                          {t("Manage", "本地管理")}
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </section>
          {data.count === 0 && (
            <p>
              {data.total_records === 0
                ? t(
                    "This complete snapshot contains no source records.",
                    "这个完整快照没有来源记录。",
                  )
                : t("No match in this snapshot.", "此快照没有匹配记录。")}
            </p>
          )}
          <ResultPagination
            label={t("Source", "来源")}
            count={data.count ?? 0}
            page={search.cloud_page}
            pageSize={SIZE}
            onPageChange={(n) => void move({ cloud_page: n })}
          />
          {activeRow && (
            <section className="space-y-2 rounded-md border p-4">
              <h2 className="font-semibold">
                {t("Source record", "来源记录")} · {activeRow.canonical_ip}
              </h2>
              {details(activeRow)}
              <Button variant="outline" onClick={() => setSelected(null)}>
                {t("Close details", "关闭详情")}
              </Button>
            </section>
          )}
          {activeEditor && (
            <form
              className="space-y-4 rounded-md border p-4"
              onSubmit={(e) => {
                e.preventDefault()
                void save()
              }}
            >
              <h2 ref={formHeading} tabIndex={-1} className="font-semibold">
                {activeEditor.kind === "scope"
                  ? t("Confirm network relationship", "确认网络范围关系")
                  : t("Local management", "本地管理")}
              </h2>
              {activeEditor.kind === "scope" ? (
                <Label className="flex flex-col gap-2">
                  {t(
                    "Relationship to legacy Project space",
                    "与项目既有地址空间的关系",
                  )}
                  <select
                    className="rounded-md border bg-background p-2"
                    value={activeEditor.scope_state ?? "UNKNOWN"}
                    onChange={(e) =>
                      setEditor({
                        scope,
                        body: {
                          ...activeEditor,
                          scope_state: e.target
                            .value as CloudLedgerEdit["scope_state"],
                        },
                      })
                    }
                  >
                    {["UNKNOWN", "SEPARATE", "CONFIRMED_LEGACY"].map((s) => (
                      <option key={s} value={s}>
                        {state(s)}
                      </option>
                    ))}
                  </select>
                </Label>
              ) : (
                <>
                  <Label className="flex flex-col gap-2">
                    {t("Tags (comma separated)", "标签（逗号分隔）")}
                    <Input
                      value={activeEditor.tags?.join(",")}
                      onChange={(e) =>
                        setEditor({
                          scope,
                          body: {
                            ...activeEditor,
                            tags: e.target.value
                              ? e.target.value
                                  .split(/[,，]/)
                                  .map((s) => s.trim())
                              : [],
                          },
                        })
                      }
                    />
                  </Label>
                  <Label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={activeEditor.followed}
                      onChange={(e) =>
                        setEditor({
                          scope,
                          body: { ...activeEditor, followed: e.target.checked },
                        })
                      }
                    />
                    {t("Follow this source record", "关注这条来源记录")}
                  </Label>
                </>
              )}
              <Label className="flex flex-col gap-2">
                {t("Reason / evidence", "理由 / 依据")}
                <Input
                  required
                  maxLength={1000}
                  value={activeEditor.reason}
                  onChange={(e) =>
                    setEditor({
                      scope,
                      body: { ...activeEditor, reason: e.target.value },
                    })
                  }
                />
              </Label>
              <div className="flex gap-2">
                <Button
                  type="submit"
                  disabled={
                    busy ||
                    !editable ||
                    (activeEditor.kind === "scope" && !data.can_confirm_scope)
                  }
                >
                  {busy
                    ? t("Saving…", "保存中…")
                    : pending
                      ? t("Recover same intent", "恢复原操作")
                      : t("Save new revision", "保存新修订")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => {
                    setEditor(null)
                    heading.current?.focus()
                  }}
                >
                  {t("Close editor", "关闭编辑")}
                </Button>
              </div>
            </form>
          )}
          {search.profile_ip && (
            <section className="space-y-4 border-t pt-5">
              <h2 className="text-xl font-semibold">
                {t("IP profile", "IP 画像")} ·{" "}
                <span className="break-all">{search.profile_ip}</span>
              </h2>
              {profile.isFetching && (
                <p role="status">
                  {t("Reading pinned sources…", "正在读取固定来源…")}
                </p>
              )}
              {profile.isError && (
                <p role="alert">
                  {t(
                    "Profile unavailable. No alternate source version was substituted.",
                    "画像不可用，未替换成其他来源版本。",
                  )}
                </p>
              )}
              {profile.isSuccess && !profile.isFetching && (
                <>
                  <p>{state(profile.data.association)}</p>
                  <p className="text-sm text-muted-foreground">
                    {t(
                      "Each source has its own timestamp. Risk evidence is not connected; CloudAtlas absence does not mean unmonitored.",
                      "各来源有独立截至时间。尚未接入风险证据；快照未观测不等于未监控。",
                    )}
                  </p>
                  <h3 className="font-semibold">
                    {t("Customer version", "客户版本")} ·{" "}
                    {profile.data.customer.source_created_at
                      ? formatDate(profile.data.customer.source_created_at)
                      : t("Not selected", "未选择")}
                  </h3>
                  <p>
                    {t("Matching source rows", "匹配来源行")}：
                    {profile.data.customer.count}
                  </p>
                  {profile.data.customer.data?.map((row) => (
                    <div key={row.entry_id} className="border-b py-2">
                      <p className="break-all">
                        {row.canonical_ip} ·{" "}
                        {String(row.fields.asset_owner ?? "—")}
                      </p>
                      <details>
                        <summary className="cursor-pointer">
                          {t("Customer record fields", "客户记录字段")}
                        </summary>
                        <dl className="space-y-1 py-2">
                          {Object.entries(row.fields).map(([k, v]) => (
                            <div key={k} className="flex flex-wrap gap-2">
                              <dt>{k}</dt>
                              <dd className="break-all">
                                {typeof v === "object" && v !== null
                                  ? JSON.stringify(v)
                                  : String(v ?? "—")}
                              </dd>
                            </div>
                          ))}
                        </dl>
                      </details>
                    </div>
                  ))}
                  {profile.data.customer.count === 0 && (
                    <p>
                      {profile.data.customer.upload_id
                        ? t(
                            "Not declared in this complete customer version.",
                            "该完整客户版本未报备此 IP。",
                          )
                        : t(
                            "No customer input selected.",
                            "尚未选择客户输入。",
                          )}
                    </p>
                  )}
                  <ResultPagination
                    label={t("Customer", "客户")}
                    count={profile.data.customer.count ?? 0}
                    page={search.customer_page}
                    pageSize={SIZE}
                    onPageChange={(n) => void move({ customer_page: n })}
                  />
                  <Button asChild variant="outline">
                    <Link
                      to="/projects/$projectId/customer-ledger"
                      params={{ projectId }}
                      search={{
                        ledger_upload:
                          profile.data.customer.upload_id ?? undefined,
                        ledger_revision:
                          profile.data.customer.revision_id ?? undefined,
                        ledger_ip: search.profile_ip,
                        ledger_query: undefined,
                        ledger_page: 1,
                        ledger_archived: false,
                      }}
                    >
                      {t("Open this customer version", "打开此客户版本")}
                    </Link>
                  </Button>
                  <h3 className="font-semibold">
                    {t("CloudAtlas snapshot", "云图快照")} ·{" "}
                    {formatDate(profile.data.cloud.source_created_at!)}
                  </h3>
                  <p>
                    {t("Matching source rows", "匹配来源行")}：
                    {profile.data.cloud.count}
                  </p>
                  {profile.data.cloud.data?.map((row) => (
                    <div key={row.observation_id} className="border-b py-2">
                      <p className="break-all">
                        {row.canonical_ip} · {row.source_status} ·{" "}
                        {row.tags?.join("、") || "—"}
                      </p>
                      {details(row)}
                    </div>
                  ))}
                  {profile.data.cloud.count === 0 && (
                    <p>
                      {t(
                        "Not observed in this complete valid snapshot.",
                        "此完整 valid 快照未观测到该 IP。",
                      )}
                    </p>
                  )}
                  <ResultPagination
                    label={t("CloudAtlas profile", "云图画像")}
                    count={profile.data.cloud.count ?? 0}
                    page={search.profile_cloud_page}
                    pageSize={SIZE}
                    onPageChange={(n) => void move({ profile_cloud_page: n })}
                  />
                  {profile.data.resource_id &&
                  profile.data.governance_run_id ? (
                    <>
                      <p>
                        {t(
                          "Activity in this historical Run",
                          "此历史批次的活动",
                        )}
                        ：
                        {profile.data.netflow_state === "INPUT_ABSENT"
                          ? t(
                              "NetFlow input not provided",
                              "未提供 NetFlow 输入",
                            )
                          : profile.data.comparison?.netflow_status === "ACTIVE"
                            ? t("Positive activity evidence", "有正向活动证据")
                            : t(
                                "No positive activity conclusion; see fixed evidence",
                                "不能形成正向活动结论，详见固定证据",
                              )}
                      </p>
                      <Button asChild>
                        <Link
                          to="/projects/$projectId/runs/$runId/lineage"
                          params={{
                            projectId,
                            runId: profile.data.governance_run_id,
                          }}
                          search={{
                            project: projectId,
                            run: profile.data.governance_run_id,
                            resource_id: profile.data.resource_id,
                          }}
                        >
                          {t(
                            "View fixed Run evidence and handling records",
                            "查看固定批次依据与处理记录",
                          )}
                        </Link>
                      </Button>
                    </>
                  ) : (
                    <p>
                      {t(
                        "No authorized historical resource association. Handling records are not attached.",
                        "尚无获确认的历史资产关联，未带入处理记录。",
                      )}
                    </p>
                  )}
                </>
              )}
              <Button
                variant="outline"
                onClick={() => void move({ profile_ip: undefined })}
              >
                {t("Close profile", "关闭画像")}
              </Button>
            </section>
          )}
          <details>
            <summary className="cursor-pointer">
              {t("Snapshot and local revision history", "快照与本地修订历史")}
            </summary>
            <div className="space-y-4 py-3">
              <h2 className="font-semibold">
                {t("Published snapshots", "已发布快照")}
              </h2>
              {versions.isError && (
                <p role="alert">
                  {t("Snapshot history unavailable", "快照历史读取失败")}
                </p>
              )}
              {versions.data?.map((v) => (
                <Button
                  key={v.id}
                  variant="outline"
                  className="mr-2 mb-2"
                  onClick={() => {
                    setHistoryPage(0)
                    void move({
                      cloud_snapshot: v.id,
                      cloud_revision: undefined,
                      cloud_page: 0,
                      profile_ip: undefined,
                      customer_upload: undefined,
                      customer_revision: undefined,
                    })
                  }}
                >
                  {formatDate(v.created_at)} · {v.record_count}{" "}
                  {t("rows", "行")}
                </Button>
              ))}
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  disabled={snapshotsPage === 0}
                  onClick={() => setSnapshotsPage((n) => n - 1)}
                >
                  {t("Previous snapshots", "上一页快照")}
                </Button>
                <Button
                  variant="outline"
                  disabled={(versions.data?.length ?? 0) < SIZE}
                  onClick={() => setSnapshotsPage((n) => n + 1)}
                >
                  {t("More snapshots", "下一页快照")}
                </Button>
              </div>
              <h2 className="font-semibold">
                {t("Local revision history", "本地修订历史")}
              </h2>
              <Button
                variant="outline"
                onClick={() => void move({ cloud_revision: 0 })}
              >
                {t(
                  "Original source / no local changes",
                  "原始来源 / 无本地修订",
                )}
              </Button>
              <Button
                variant="outline"
                onClick={() =>
                  void move({ cloud_revision: data.current_revision })
                }
              >
                {t("Current local revision", "当前本地修订")}
              </Button>
              {history.isError && (
                <p role="alert">
                  {t("Revision history unavailable", "修订历史读取失败")}
                </p>
              )}
              {history.data?.map((v) => (
                <div key={v.id} className="space-y-1 border-b py-2">
                  <Button
                    variant="outline"
                    onClick={() => void move({ cloud_revision: v.revision })}
                  >
                    {t("Revision", "修订")} {v.revision} ·{" "}
                    {formatDate(v.created_at)}
                  </Button>
                  <p className="break-words">{v.reason}</p>
                  <p>
                    {v.kind === "scope"
                      ? state(v.scope_state ?? "UNKNOWN")
                      : `${v.tags.join("、")}${v.followed ? t(" · Followed", " · 已关注") : ""}`}
                  </p>
                  <details>
                    <summary>{t("Author and record", "作者与记录")}</summary>
                    <TechnicalValue value={v.created_by} />
                    <TechnicalValue
                      value={v.observation_id ?? v.source_snapshot_id}
                    />
                  </details>
                </div>
              ))}
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  disabled={historyPage === 0}
                  onClick={() => setHistoryPage((n) => n - 1)}
                >
                  {t("Previous revisions", "上一页修订")}
                </Button>
                <Button
                  variant="outline"
                  disabled={(history.data?.length ?? 0) < SIZE}
                  onClick={() => setHistoryPage((n) => n + 1)}
                >
                  {t("More revisions", "下一页修订")}
                </Button>
              </div>
            </div>
          </details>
        </>
      )}
    </div>
  )
}
