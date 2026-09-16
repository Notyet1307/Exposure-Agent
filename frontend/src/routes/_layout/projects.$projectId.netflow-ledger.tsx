import { useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { useEffect, useRef, useState } from "react"
import {
  NetflowLedgerService as API,
  type ApiError,
  type Edit,
  type Endpoint,
  ProjectsService,
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

const SIZE = 25
const text = (value: unknown) => (typeof value === "string" ? value : undefined)
const integer = (value: unknown) =>
  Number.isSafeInteger(Number(value)) && Number(value) >= 0
    ? Number(value)
    : undefined
export const Route = createFileRoute(
  "/_layout/projects/$projectId/netflow-ledger",
)({
  component: NetflowLedger,
  validateSearch: (search: Record<string, unknown>) => ({
    dataset: text(search.dataset),
    revision: integer(search.revision),
    page: integer(search.page) ?? 0,
    ip: text(search.ip),
    candidate: search.candidate === true || search.candidate === "true",
    profile_ip: text(search.profile_ip),
    customer_upload: text(search.customer_upload),
    customer_revision: text(search.customer_revision),
    cloud_snapshot: text(search.cloud_snapshot),
    cloud_revision: integer(search.cloud_revision),
  }),
})
type Pending = {
  key: string
  digest: string
  dataset: string
  revision: number
}
function NetflowLedger() {
  const { projectId } = Route.useParams()
  const { user } = useAuth()
  const search = Route.useSearch()
  const { t } = useI18n()
  useEffect(() => {
    document.title = t(
      "NetFlow activity ledger - Exposure",
      "NetFlow 原生活动账 - Exposure",
    )
  }, [t])
  return user ? (
    <Ledger
      key={`${user.id}:${projectId}:${search.dataset}:${search.revision}`}
      actor={user.id}
      projectId={projectId}
    />
  ) : null
}
function Ledger({ actor, projectId }: { actor: string; projectId: string }) {
  const { t } = useI18n()
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  const cache = useQueryClient()
  const scope = `${actor}/${projectId}/${search.dataset}/${search.revision}`
  const scopeRef = useRef(scope)
  scopeRef.current = scope
  useEffect(() => {
    scopeRef.current = scope
    return () => {
      scopeRef.current = "unmounted"
    }
  }, [scope])
  const [query, setQuery] = useState(search.ip ?? "")
  const [editor, setEditor] = useState<Partial<Edit> | null>(null)
  const [reason, setReason] = useState("")
  const [notice, setNotice] = useState("")
  const store = `exposure:netflow-ledger:${actor}:${projectId}:${search.dataset}`
  const [pending, setPending] = useState<Pending | null>(() => {
    try {
      return JSON.parse(
        sessionStorage.getItem(store) ?? "null",
      ) as Pending | null
    } catch {
      return null
    }
  })
  const ledger = useQuery({
    queryKey: [
      "netflow-ledger",
      actor,
      projectId,
      search.dataset,
      search.revision,
      search.page,
      search.ip,
      search.candidate,
    ],
    queryFn: () =>
      API.readNetflowLedger({
        projectId,
        datasetId: search.dataset,
        revision: search.revision,
        ip: search.ip,
        candidate: search.candidate,
        skip: search.page * SIZE,
        limit: SIZE,
      }),
    retry: false,
  })
  const datasets = useQuery({
    queryKey: ["netflow-datasets", actor, projectId],
    queryFn: () => ProjectsService.readNetflowDatasets({ projectId }),
    retry: false,
  })
  const profile = useQuery({
    queryKey: [
      "netflow-profile",
      actor,
      projectId,
      search.profile_ip,
      search.dataset,
      search.revision,
      search.customer_upload,
      search.customer_revision,
      search.cloud_snapshot,
      search.cloud_revision,
    ],
    enabled: !!search.profile_ip && !!search.dataset,
    queryFn: () =>
      API.readNetflowLedgerProfile({
        projectId,
        datasetId: search.dataset!,
        ip: search.profile_ip!,
        revision: search.revision,
        uploadId: search.customer_upload,
        customerRevisionId: search.customer_revision,
        snapshotId: search.cloud_snapshot,
        cloudRevision: search.cloud_revision,
      }),
    retry: false,
  })
  const data = ledger.data
  useEffect(() => {
    if (
      data?.dataset_id &&
      (search.dataset !== data.dataset_id || search.revision !== data.revision)
    )
      void navigate({
        search: {
          ...search,
          dataset: data.dataset_id,
          revision: data.revision,
        },
        replace: true,
      })
  }, [data, search, navigate])
  useEffect(() => {
    setEditor(null)
    setNotice("")
  }, [])
  const move = (change: Partial<typeof search>) => {
    const reset = "dataset" in change || "revision" in change
    return navigate({
      search: {
        ...search,
        ...(reset
          ? {
              profile_ip: undefined,
              customer_upload: undefined,
              customer_revision: undefined,
              cloud_snapshot: undefined,
              cloud_revision: undefined,
            }
          : {}),
        ...change,
      },
    })
  }
  const recover = async () => {
    const captured = scope
    if (!pending) return
    try {
      const row = await API.readNetflowLedgerOperation({
        projectId,
        operationKey: pending.key,
      })
      if (scopeRef.current !== captured) return
      sessionStorage.removeItem(store)
      setPending(null)
      if (row.dataset_id !== search.dataset) return
      move({ revision: row.revision })
      await cache.invalidateQueries({
        queryKey: ["netflow-ledger", actor, projectId],
      })
    } catch {
      if (scopeRef.current !== captured) return
      setNotice(
        t("The original operation is still unavailable.", "原操作仍不可读取。"),
      )
    }
  }
  const save = async () => {
    if (
      !data ||
      !editor ||
      !reason.trim() ||
      pending ||
      data.revision !== data.current_revision
    )
      return
    const body = {
      dataset_id: data.dataset_id!,
      expected_revision: data.revision ?? 0,
      kind: editor.kind!,
      namespace: editor.namespace!,
      cidrs: editor.cidrs ?? [],
      canonical_ip: editor.canonical_ip ?? null,
      collector: editor.collector ?? "",
      location: editor.location ?? "",
      evidence: editor.evidence ?? "",
      viewpoint: editor.viewpoint ?? null,
      scope_status: editor.scope_status ?? null,
      followed: editor.followed ?? false,
      excluded: editor.excluded ?? false,
      reason,
    }
    const captured = scope
    const digest = await requestDigest(body)
    if (scopeRef.current !== captured) return
    const intent = {
      key: crypto.randomUUID(),
      digest,
      dataset: data.dataset_id!,
      revision: data.current_revision ?? 0,
    }
    sessionStorage.setItem(store, JSON.stringify(intent))
    setPending(intent)
    try {
      const row = await API.createNetflowLedgerRevision({
        projectId,
        idempotencyKey: intent.key,
        requestBody: body,
      })
      if (scopeRef.current !== captured) return
      sessionStorage.removeItem(store)
      setPending(null)
      setEditor(null)
      if (row.dataset_id !== search.dataset) return
      move({ revision: row.revision })
      await cache.invalidateQueries({
        queryKey: ["netflow-ledger", actor, projectId],
      })
    } catch (error) {
      if (scopeRef.current !== captured) return
      const api = error as ApiError
      if ([400, 403, 404, 409, 422].includes(api.status)) {
        sessionStorage.removeItem(store)
        setPending(null)
        setNotice(
          t(
            "Input was rejected. Correct it and try again.",
            "输入被拒绝；请更正后再试。",
          ),
        )
      } else
        setNotice(
          t(
            "Result is unknown. Query the original operation; do not submit again.",
            "结果未知；请查询原操作。",
          ),
        )
    }
  }
  return (
    <main className="container mx-auto max-w-6xl px-4 py-6">
      <h1 className="text-2xl font-semibold">
        {t("NetFlow activity ledger", "NetFlow 原生活动账")}
      </h1>
      <p className="mt-2 text-sm text-muted-foreground">
        {t(
          "Fixed normalized Dataset evidence. Reading does not create a Run or make an external request.",
          "固定规范化 Dataset 证据；读取不会创建运行或发起外部请求。",
        )}
      </p>
      <div className="mt-5 flex flex-wrap gap-2">
        <Label>
          {t("Dataset", "Dataset")}
          <select
            aria-label={t("Dataset", "Dataset")}
            value={search.dataset ?? ""}
            onChange={(event) =>
              move({
                dataset: event.target.value || undefined,
                revision: undefined,
                page: 0,
              })
            }
          >
            <option value="">{t("Current selection", "当前选择")}</option>
            {datasets.data?.data.map((dataset) => (
              <option key={dataset.id} value={dataset.id}>
                {dataset.display_filename}
              </option>
            ))}
          </select>
        </Label>
        <Link
          className="self-end text-sm underline"
          to="/"
          search={{ project: projectId, view: "inputs" }}
        >
          {t("Manage inputs", "管理输入")}
        </Link>
        <Input
          aria-label={t("Exact IP", "精确 IP")}
          className="max-w-xs"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <Button onClick={() => move({ ip: query || undefined, page: 0 })}>
          {t("Filter", "筛选")}
        </Button>
        <Button
          variant="outline"
          onClick={() => move({ candidate: !search.candidate, page: 0 })}
        >
          {search.candidate
            ? t("All endpoints", "全部端点")
            : t("Candidates only", "仅候选")}
        </Button>
        {data?.can_confirm_scope && data.revision === data.current_revision && (
          <Button
            variant="outline"
            onClick={() =>
              setEditor({
                kind: "scope",
                namespace: data.current_scope?.namespace ?? "",
                cidrs: data.current_scope?.cidrs ?? [],
                collector: "",
                location: "",
                evidence: "",
                viewpoint: "UNKNOWN",
                scope_status: "UNKNOWN",
              })
            }
          >
            {t("Confirm scope", "确认范围")}
          </Button>
        )}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button
          variant="outline"
          onClick={() => move({ revision: undefined, page: 0 })}
        >
          {t("Read current revision", "读取当前修订")}
        </Button>
        <Label>
          {t("Read historical revision", "读取历史修订")}
          <Input
            aria-label={t("Historical revision", "历史修订")}
            type="number"
            min={0}
            max={data?.current_revision}
            defaultValue={search.revision}
            onKeyDown={(e) => {
              if (e.key === "Enter")
                void move({ revision: Number(e.currentTarget.value), page: 0 })
            }}
          />
        </Label>
        <span className="text-sm">
          {t("Selected / current revision", "所选 / 当前修订")}:{" "}
          {data?.revision ?? 0} / {data?.current_revision ?? 0}
        </span>
      </div>
      {notice && <p className="mt-3 text-sm text-destructive">{notice}</p>}
      {pending && (
        <section className="mt-4 border p-3">
          <h2 className="font-semibold">
            {t("Unconfirmed local operation", "待确认的本地操作")}
          </h2>
          <Button
            className="mt-2"
            variant="outline"
            onClick={() => void recover()}
          >
            {t("Check original operation", "查询原操作")}
          </Button>
        </section>
      )}
      {ledger.isError ? (
        <p className="mt-6 text-destructive">
          {t(
            "Projection unavailable. Check Dataset integrity and the fixed version.",
            "投影不可用；请检查 Dataset 完整性和固定版本。",
          )}
        </p>
      ) : (
        <>
          <div className="mt-4 flex flex-wrap gap-3 text-sm">
            <span>
              {data ? stateText(data.state, t) : t("Loading…", "正在读取…")}
            </span>
            <span>
              {t("Endpoints", "端点")} {data?.count ?? 0}/
              {data?.total_endpoints ?? 0}
            </span>
            {data?.dataset_sha256 && (
              <details className="min-w-0 max-w-full">
                <summary>
                  {t("Pinned source and integrity", "固定来源与完整性")}
                </summary>
                <TechnicalValue
                  label={t("Normalized hash", "规范化哈希")}
                  value={data.dataset_sha256}
                />
                {data.raw_sha256 && (
                  <p>
                    <TechnicalValue
                      label={t("Original hash", "原文件哈希")}
                      value={data.raw_sha256}
                    />
                  </p>
                )}
                {data.dataset_id && (
                  <p>
                    <TechnicalValue
                      label={t("Dataset identity", "数据版本标识")}
                      value={data.dataset_id}
                    />
                  </p>
                )}
                <p>{data.contract_version}</p>
                {data.scope && (
                  <p>
                    {t("Network scope", "网络空间")}: {data.scope.namespace} ·{" "}
                    {data.scope.cidrs.join(", ")} · {data.scope.evidence}
                  </p>
                )}
              </details>
            )}
          </div>
          {data?.dataset_id && (
            <p className="mt-2 text-sm text-muted-foreground">
              {t(
                "Valid flow records / isolated rows / source records",
                "有效流记录 / 隔离行 / 原始记录",
              )}
              : {data.valid_records ?? 0} / {data.isolated_records ?? 0} /{" "}
              {data.raw_records ?? 0}.{" "}
              {t(
                "Activity does not prove reachability, a listening service, or risk.",
                "有活动不代表公网可达、存在监听服务或风险。",
              )}
            </p>
          )}
          <div className="mt-4 overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>IP</TableHead>
                  <TableHead>{t("Roles", "角色")}</TableHead>
                  <TableHead>{t("Flows", "流数")}</TableHead>
                  <TableHead>{t("Candidate", "候选")}</TableHead>
                  <TableHead>{t("Evidence", "证据")}</TableHead>
                  <TableHead>{t("Action", "操作")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data?.data?.map((row: Endpoint) => (
                  <TableRow key={row.canonical_ip}>
                    <TableCell className="font-mono text-xs">
                      {row.canonical_ip}
                    </TableCell>
                    <TableCell>
                      {row.roles
                        .map((role) =>
                          role === "src"
                            ? t("Source", "源端")
                            : t("Destination", "目的端"),
                        )
                        .join(" / ")}
                    </TableCell>
                    <TableCell>{row.flow_count}</TableCell>
                    <TableCell>
                      {stateText(row.candidate_state, t)}
                      {row.historical_candidate_state !==
                        row.candidate_state && (
                        <p className="text-xs text-muted-foreground">
                          {t("At this revision", "所选修订当时")}:{" "}
                          {stateText(row.historical_candidate_state, t)}
                        </p>
                      )}
                    </TableCell>
                    <TableCell>
                      <details>
                        <summary>{t("Source evidence", "来源依据")}</summary>
                        <p>{(row.source_record_keys ?? []).join(", ")}</p>
                        <p>
                          {t("Protocols", "协议")}:{" "}
                          {(row.protocols ?? []).join(", ")}
                        </p>
                        <p>
                          {t("First / last observed", "首次 / 最近观测")}:{" "}
                          {row.first_seen_utc ?? t("Unknown", "未知")} /{" "}
                          {row.last_seen_utc ?? t("Unknown", "未知")}
                        </p>
                      </details>
                    </TableCell>
                    <TableCell className="flex gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          move({ profile_ip: row.canonical_ip ?? undefined })
                        }
                      >
                        {t("IP profile", "IP 画像")}
                      </Button>
                      {data.can_manage &&
                        data.revision === data.current_revision &&
                        row.namespace && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() =>
                              setEditor({
                                kind: "management",
                                namespace: row.namespace ?? "",
                                canonical_ip: row.canonical_ip ?? undefined,
                                followed: row.followed,
                                excluded: row.excluded,
                              })
                            }
                          >
                            {t("Manage", "管理")}
                          </Button>
                        )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <ResultPagination
            label="NetFlow endpoints"
            count={data?.count ?? 0}
            page={search.page}
            pageSize={SIZE}
            onPageChange={(page) => move({ page })}
          />
        </>
      )}
      {editor && (
        <section className="mt-6 max-w-xl space-y-3 border p-4">
          <h2 className="text-lg font-semibold">
            {editor.kind === "scope"
              ? t("Confirm network scope", "确认网络范围")
              : t("Manage endpoint", "管理端点")}
          </h2>
          <Label>
            {t("Namespace", "命名空间")}
            <Input
              value={editor.namespace ?? ""}
              onChange={(event) =>
                setEditor({ ...editor, namespace: event.target.value })
              }
            />
          </Label>
          {editor.kind === "scope" && (
            <>
              <Label>
                CIDR
                <input
                  aria-label="CIDRs"
                  className="mt-1 w-full rounded-md border px-3 py-2"
                  value={(editor.cidrs ?? []).join(",")}
                  onChange={(event) =>
                    setEditor({
                      ...editor,
                      cidrs: event.target.value
                        .split(",")
                        .map((v) => v.trim())
                        .filter(Boolean),
                    })
                  }
                />
              </Label>
              <Label>
                {t("Collector", "采集来源")}
                <Input
                  value={editor.collector ?? ""}
                  onChange={(event) =>
                    setEditor({ ...editor, collector: event.target.value })
                  }
                />
              </Label>
              <Label>
                {t("Location", "位置")}
                <Input
                  value={editor.location ?? ""}
                  onChange={(event) =>
                    setEditor({ ...editor, location: event.target.value })
                  }
                />
              </Label>
              <Label>
                {t("Evidence", "证据出处")}
                <Input
                  value={editor.evidence ?? ""}
                  onChange={(event) =>
                    setEditor({ ...editor, evidence: event.target.value })
                  }
                />
              </Label>
              <Label>
                {t("Viewpoint", "视角")}
                <select
                  aria-label={t("Viewpoint", "视角")}
                  value={editor.viewpoint ?? "UNKNOWN"}
                  onChange={(event) =>
                    setEditor({
                      ...editor,
                      viewpoint: event.target.value as Edit["viewpoint"],
                    })
                  }
                >
                  <option value="PUBLIC">PUBLIC / 公网</option>
                  <option value="INTERNAL">INTERNAL / 内部</option>
                  <option value="UNKNOWN">UNKNOWN / 未知</option>
                </select>
              </Label>
              <Label>
                {t("Scope status", "范围状态")}
                <select
                  aria-label={t("Scope status", "范围状态")}
                  value={editor.scope_status ?? "UNKNOWN"}
                  onChange={(event) =>
                    setEditor({
                      ...editor,
                      scope_status: event.target.value as Edit["scope_status"],
                    })
                  }
                >
                  <option value="CONFIRMED">CONFIRMED / 已确认</option>
                  <option value="UNKNOWN">UNKNOWN / 未知</option>
                  <option value="CONFLICT">CONFLICT / 冲突</option>
                  <option value="REVOKED">REVOKED / 已撤销</option>
                </select>
              </Label>
            </>
          )}
          {editor.kind === "management" && (
            <>
              <Label className="flex gap-2">
                <input
                  type="checkbox"
                  checked={editor.followed ?? false}
                  onChange={(event) =>
                    setEditor({ ...editor, followed: event.target.checked })
                  }
                />
                {t("Follow this endpoint", "关注此端点")}
              </Label>
              <Label className="flex gap-2">
                <input
                  type="checkbox"
                  checked={editor.excluded ?? false}
                  onChange={(event) =>
                    setEditor({ ...editor, excluded: event.target.checked })
                  }
                />
                {t("Exclude from candidates", "从候选中排除")}
              </Label>
            </>
          )}
          <Label>
            {t("Reason / evidence", "理由 / 证据")}
            <Input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </Label>
          <div className="flex gap-2">
            <Button disabled={!!pending} onClick={() => void save()}>
              {t("Save revision", "保存新修订")}
            </Button>
            <Button variant="outline" onClick={() => setEditor(null)}>
              {t("Cancel", "取消")}
            </Button>
          </div>
        </section>
      )}
      {search.profile_ip && (
        <section className="mt-6 border p-4">
          <h2 className="text-lg font-semibold">
            {t("Fixed IP profile", "固定 IP 画像")}
          </h2>
          <p className="mt-2 text-sm">
            {t(
              "This profile is fixed to the Dataset and optional source versions in the URL. It does not call AI or imply risk.",
              "该画像固定到 URL 中的 Dataset 和可选来源版本；不会调用 AI，也不代表风险。",
            )}
          </p>
          {profile.isLoading && (
            <p>
              {t("Loading fixed source versions…", "正在读取固定来源版本…")}
            </p>
          )}
          {profile.isError && (
            <p className="text-destructive">
              {t("The fixed profile is unavailable.", "固定画像不可用。")}
            </p>
          )}
          {profile.data && (
            <div className="mt-3 space-y-1 text-sm">
              <p>
                {t("Association", "关联")}:{" "}
                {stateText(profile.data.association, t)}
              </p>
              <p>
                {t("Risk", "风险")}: {stateText(profile.data.risk_state, t)}
              </p>
              <p>
                {t("Processing history", "处理历史")}:{" "}
                {stateText(profile.data.processing_state, t)}
              </p>
              <p>
                {t("Customer source", "客户来源")}:{" "}
                {profile.data.customer
                  ? t("Provided", "已提供")
                  : t("Not provided", "未提供")}
              </p>
              <p>
                {t("CloudAtlas source", "云图来源")}:{" "}
                {profile.data.cloud
                  ? t("Provided", "已提供")
                  : t("Not provided", "未提供")}
              </p>
              <p className="break-all">IP: {profile.data.canonical_ip}</p>
              {profile.data.netflow.data?.map((row) => (
                <p key={row.canonical_ip}>
                  {row.flow_count} {t("observed flow records", "条观测流记录")}{" "}
                  · {stateText(row.candidate_state, t)}
                </p>
              ))}
              {profile.data.resource_id && profile.data.governance_run_id && (
                <Link
                  to="/"
                  search={{
                    project: projectId,
                    view: "assets",
                    asset_id: profile.data.resource_id,
                    run: profile.data.governance_run_id,
                  }}
                >
                  {t("Open fixed Run history", "打开固定批次历史")}
                </Link>
              )}
              <p>
                {t("NetFlow endpoints", "NetFlow 端点")}:{" "}
                {profile.data.netflow.data?.length ?? 0}
              </p>
            </div>
          )}
          {(search.customer_upload || search.customer_revision) && (
            <Link
              className="mt-2 inline-block underline"
              to="/projects/$projectId/customer-ledger"
              params={{ projectId }}
              search={{
                ledger_upload: search.customer_upload,
                ledger_revision: search.customer_revision,
                ledger_query: undefined,
                ledger_ip: search.profile_ip,
                ledger_page: 0,
                ledger_archived: false,
              }}
            >
              {t("Open customer source", "打开客户来源")}
            </Link>
          )}
        </section>
      )}
    </main>
  )
}

function stateText(
  value: string | undefined,
  t: (en: string, zh: string) => string,
) {
  const names: Record<string, [string, string]> = {
    NO_DATASET: ["No Dataset selected", "未选择流量数据"],
    EMPTY: ["Accepted empty Dataset", "已接受的空数据"],
    NO_POSITIVE_EVIDENCE: ["No valid activity evidence", "无有效活动证据"],
    NOT_COVERED: ["IP not observed in this Dataset", "本数据中未观测该 IP"],
    PRESENT: ["Source observations available", "已读取来源观测"],
    CANDIDATE: ["Monitoring candidate; not submitted", "监控候选，尚未提交"],
    EXCLUDED: ["Excluded locally", "已在本地排除"],
    EXTERNAL_PEER: ["External peer", "范围外对端"],
    PENDING_SCOPE: ["Ownership or authorization pending", "归属或授权待确认"],
    REVOKED: ["Current scope revoked", "当前范围已撤销"],
    CONFLICT: ["Network scope conflict", "网络空间冲突"],
    VIEWPOINT_UNSUPPORTED: [
      "Internal viewpoint not supported for public monitoring",
      "内网视角不适用公网候选",
    ],
    NOT_IPV6: ["Not an IPv6 candidate", "非 IPv6 候选"],
    INELIGIBLE_ADDRESS: [
      "Local or special address excluded",
      "已排除本地或特殊地址",
    ],
    UNKNOWN: ["No confirmed association", "尚无可靠关联"],
    NOT_CONNECTED: ["Risk evidence not connected", "尚未接入风险证据"],
    NO_RESOURCE_HISTORY: [
      "No associated handling history",
      "暂无可关联的处理记录",
    ],
    FIXED_RUN_HISTORY: ["History from the fixed Run", "固定批次处理历史"],
    CONFIRMED_LEGACY: [
      "Confirmed legacy network association",
      "已确认旧网络空间关联",
    ],
  }
  const label = names[value ?? "UNKNOWN"]
  return label ? t(...label) : (value ?? "")
}
