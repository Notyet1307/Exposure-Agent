import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { useEffect, useMemo, useRef, useState } from "react"
import {
  ApiError,
  NetflowProcessingService,
  NetflowReviewsService,
  ProjectsService,
} from "@/client"
import { ResultPagination } from "@/components/ResultPagination"
import { TechnicalValue } from "@/components/TechnicalValue"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useI18n } from "@/lib/i18n"
import { netflowErrorCode } from "@/lib/netflow-errors"
import { netflowProtocol, netflowText } from "@/lib/netflow-labels"

const SIZE = 25
const EVIDENCE_SIZE = 10
export type NetflowResultsSearch = {
  analysis?: string
  dataset?: string
  collectionScope?: string
  history?: boolean
  tab?: "observations" | "peers"
  resultPage?: number
  datasetPage?: number
  batchPage?: number
  ip?: string
  protocol?: number
  port?: number
  sort?: "ip_asc" | "ip_desc"
  object?: string
  peer?: string
  evidence?: boolean
  evidencePage?: number
  invalid?: boolean
}
type Navigate = (options: {
  search: (previous: NetflowResultsSearch) => NetflowResultsSearch
  replace?: boolean
}) => Promise<void>

export default function NetflowResults({
  actor,
  projectId,
  search,
  navigate,
}: {
  actor: string
  projectId: string
  search: NetflowResultsSearch
  navigate: Navigate
}) {
  const { t, formatDate } = useI18n()
  const cache = useQueryClient()
  const scope = useMemo(
    () => [
      "netflow-results",
      actor,
      projectId,
      search.analysis ?? "none",
      search.dataset ?? "none",
      search.collectionScope ?? "none",
    ],
    [actor, projectId, search.analysis, search.dataset, search.collectionScope],
  )
  const [denied, setDenied] = useState(false)
  const [ip, setIp] = useState(search.ip ?? "")
  const [protocol, setProtocol] = useState(search.protocol?.toString() ?? "")
  const [port, setPort] = useState(search.port?.toString() ?? "")
  const detailTarget = useRef<HTMLElement>(null)
  const evidenceTarget = useRef<HTMLElement>(null)
  const tab = search.tab ?? "observations"
  const change = (patch: Partial<NetflowResultsSearch>) =>
    void navigate({ search: (previous) => ({ ...previous, ...patch }) })
  useEffect(() => {
    setIp(search.ip ?? "")
    setProtocol(search.protocol?.toString() ?? "")
    setPort(search.port?.toString() ?? "")
  }, [search.ip, search.protocol, search.port])
  useEffect(() => {
    document.title = t(
      "NetFlow observations - Exposure",
      "NetFlow 观测 - Exposure",
    )
  }, [t])
  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState === "visible")
        void cache.invalidateQueries({ queryKey: scope })
    }
    document.addEventListener("visibilitychange", refresh)
    return () => {
      document.removeEventListener("visibilitychange", refresh)
      void cache.cancelQueries({ queryKey: scope })
      cache.removeQueries({ queryKey: scope })
    }
  }, [cache, scope])
  const available = !denied && !search.invalid
  const options = {
    retry: false,
    staleTime: 0,
    gcTime: 0,
    refetchInterval: 5000,
  }
  const batch = useQuery({
    ...options,
    queryKey: [...scope, "batch"],
    enabled: available && Boolean(search.analysis),
    queryFn: () =>
      NetflowProcessingService.readAnalysis({
        projectId,
        analysisId: search.analysis!,
      }),
  })
  const current = useQuery({
    ...options,
    queryKey: [...scope, "current"],
    enabled:
      available &&
      ((Boolean(search.analysis) &&
        Boolean(search.collectionScope) &&
        !search.history) ||
        (!search.history && !search.dataset)),
    queryFn: () =>
      NetflowProcessingService.readCurrentNetflow({
        projectId,
        collectionScope: search.collectionScope,
      }),
  })
  useEffect(() => {
    const resolved = current.data?.current
    if (!resolved || search.analysis || search.history || search.dataset) return
    void navigate({
      replace: true,
      search: (previous) => ({
        ...previous,
        analysis: resolved.analysis_id,
        dataset: resolved.dataset_id,
        collectionScope: current.data?.scope_id ?? undefined,
      }),
    })
  }, [
    current.data?.current,
    navigate,
    search.analysis,
    search.dataset,
    search.history,
    current.data?.scope_id,
  ])
  const identity = batch.data
  const identityMatches = Boolean(
    identity &&
      identity.project_id === projectId &&
      identity.analysis_id === search.analysis &&
      (!search.dataset || identity.dataset_id === search.dataset),
  )
  const readable =
    available &&
    identityMatches &&
    identity?.can_read_result === true &&
    ["SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"].includes(identity.status) &&
    !batch.isError
  const verify = <
    T extends {
      project_id: string
      analysis_id: string
      dataset_id: string
      context_revision_id: string
      network_namespace: string
    },
  >(
    value: T,
  ): T => {
    if (
      !identity ||
      value.project_id !== projectId ||
      value.analysis_id !== identity.analysis_id ||
      value.dataset_id !== identity.dataset_id ||
      value.context_revision_id !== identity.context_revision_id ||
      value.network_namespace !== identity.network_namespace
    )
      throw new Error("Fixed batch identity mismatch")
    return value
  }
  const observations = useQuery({
    ...options,
    queryKey: [
      ...scope,
      "observations",
      search.ip,
      search.protocol,
      search.port,
      search.sort,
      search.resultPage,
    ],
    enabled: readable && tab === "observations",
    queryFn: async () =>
      verify(
        await NetflowReviewsService.readObservations({
          projectId,
          analysisId: search.analysis!,
          ip: search.ip,
          protocol: search.protocol,
          sourcePort: search.port,
          sort: search.sort ?? "ip_asc",
          skip: (search.resultPage ?? 0) * SIZE,
          limit: SIZE,
        }),
      ),
  })
  const detail = useQuery({
    ...options,
    queryKey: [...scope, "detail", search.object],
    enabled: readable && tab === "observations" && Boolean(search.object),
    queryFn: async () =>
      verify(
        await NetflowReviewsService.readObservation({
          projectId,
          analysisId: search.analysis!,
          objectKey: search.object!,
        }),
      ),
  })
  const peers = useQuery({
    ...options,
    queryKey: [
      ...scope,
      "peers",
      search.ip,
      search.protocol,
      search.port,
      search.sort,
      search.resultPage,
    ],
    enabled: readable && tab === "peers",
    queryFn: async () =>
      verify(
        await NetflowReviewsService.readPeers({
          projectId,
          analysisId: search.analysis!,
          ip: search.ip,
          protocol: search.protocol,
          peerPort: search.port,
          sort: search.sort ?? "ip_asc",
          skip: (search.resultPage ?? 0) * SIZE,
          limit: SIZE,
        }),
      ),
  })
  const evidence = useQuery({
    ...options,
    queryKey: [
      ...scope,
      "evidence",
      tab,
      search.object,
      search.peer,
      search.evidencePage,
    ],
    enabled:
      readable &&
      search.evidence === true &&
      Boolean(
        tab === "observations"
          ? search.object && detail.isSuccess && !detail.isError
          : search.peer,
      ),
    queryFn: async () =>
      verify(
        await NetflowReviewsService.readEvidence({
          projectId,
          analysisId: search.analysis!,
          objectKey: tab === "observations" ? search.object : undefined,
          peerKey: tab === "peers" ? search.peer : undefined,
          skip: (search.evidencePage ?? 0) * EVIDENCE_SIZE,
          limit: EVIDENCE_SIZE,
        }),
      ),
  })
  const datasets = useQuery({
    ...options,
    queryKey: [...scope, "datasets", search.datasetPage],
    enabled:
      available &&
      !search.analysis &&
      Boolean(search.history || search.dataset),
    queryFn: () =>
      ProjectsService.readNetflowDatasets({
        projectId,
        skip: (search.datasetPage ?? 0) * SIZE,
        limit: SIZE,
      }),
  })
  const batches = useQuery({
    ...options,
    queryKey: [...scope, "batches", search.batchPage],
    enabled: available && !search.analysis && Boolean(search.dataset),
    queryFn: () =>
      NetflowProcessingService.readAnalyses({
        projectId,
        datasetId: search.dataset!,
        skip: (search.batchPage ?? 0) * SIZE,
        limit: SIZE,
      }),
  })
  const failure = [
    batch,
    observations,
    detail,
    peers,
    evidence,
    ...(search.analysis ? [] : [current]),
    datasets,
    batches,
  ].find((query) => query.isError)?.error
  useEffect(() => {
    if (
      !(failure instanceof ApiError) ||
      ![401, 403, 404, 410].includes(failure.status)
    )
      return
    setDenied(true)
    void cache.cancelQueries({ queryKey: scope })
    cache.removeQueries({ queryKey: scope })
  }, [cache, scope, failure])
  const mismatch = Boolean(identity && !identityMatches)
  const blocked = denied || search.invalid || mismatch || Boolean(failure)
  useEffect(() => {
    if (
      search.object &&
      detail.data?.object_key === search.object &&
      !search.evidence
    )
      detailTarget.current?.focus()
  }, [search.object, detail.data?.object_key, search.evidence])
  useEffect(() => {
    if (search.evidence && evidence.isSuccess && !evidence.isError)
      evidenceTarget.current?.focus()
  }, [search.evidence, evidence.isSuccess, evidence.isError])
  const date = (value: string | null | undefined) =>
    value ? formatDate(value) : t("Unknown", "未知")
  const pageData = tab === "observations" ? observations.data : peers.data
  const rows =
    tab === "observations"
      ? observations.data?.data.map((row) => ({
          key: row.object_key,
          ip: row.canonical_ip,
          protocol: row.protocol_number,
          port: row.source_port,
          records: row.source_record_count,
        }))
      : peers.data?.data.map((row) => ({
          key: row.peer_key,
          ip: row.canonical_ip,
          protocol: row.protocol_number,
          port: row.peer_port,
          records: row.source_record_count,
        }))
  return (
    <main className="min-w-0 space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">
          {t("NetFlow observations", "NetFlow 观测")}
        </h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          {t(
            "Read the observations from one fixed processing batch. Source-side records and external peers remain separate; records do not prove ownership, listening services or reachability.",
            "查询一个固定处理批次的观测。源侧记录与外侧对端分别呈现；记录不证明资产归属、监听服务或可达性。",
          )}
        </p>
        <div className="flex flex-wrap gap-4 text-sm">
          <Link
            className="underline"
            to="/projects/$projectId/netflow-ledger"
            params={{ projectId }}
            search={{
              dataset: identity?.dataset_id,
              revision: undefined,
              page: 0,
              ip: undefined,
              candidate: false,
              profile_ip: undefined,
              customer_upload: undefined,
              customer_revision: undefined,
              cloud_snapshot: undefined,
              cloud_revision: undefined,
            }}
          >
            {t("Original activity ledger", "原生活动账")}
          </Link>
          <Link
            className="underline"
            to="/projects/$projectId/netflow-correlation"
            params={{ projectId }}
            search={{}}
          >
            {t("Comparison results", "比对结果")}
          </Link>
          <Link
            className="underline"
            to="/"
            search={{ project: projectId, view: "inputs" }}
            hash="netflow-inputs"
          >
            {t("Upload and processing", "上传与处理")}
          </Link>
          {search.analysis && (
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                void navigate({ search: () => ({ history: true }) })
              }
            >
              {t("Browse processing history", "浏览处理历史")}
            </Button>
          )}
        </div>
      </header>
      {blocked ? (
        <section
          role="alert"
          className="rounded-lg border border-destructive p-4"
        >
          <h2 className="font-semibold">
            {t("This fixed batch cannot be read", "无法读取该固定批次")}
          </h2>
          <p className="mt-2 text-sm">
            {search.invalid || mismatch
              ? t(
                  "The explicit batch identity is invalid or conflicts with this project or dataset.",
                  "明确批次身份无效，或与项目、上传数据不一致。",
                )
              : t(
                  "Access, result validity or integrity could not be verified. The page has cleared restricted results. Select a batch explicitly to continue.",
                  "无法验证权限、结果有效性或完整性，页面已清除受限结果。请明确选择批次后再继续。",
                )}
          </p>
          {failure && (
            <p className="mt-2 text-sm">
              {netflowText(
                netflowErrorCode(failure) ?? "netflow_analysis_not_readable",
                t,
              )}
            </p>
          )}
        </section>
      ) : !search.analysis &&
        !search.history &&
        !search.dataset &&
        current.isPending ? (
        <p role="status">
          {t("Resolving the current processed data…", "正在解析当前处理数据…")}
        </p>
      ) : !search.analysis ? (
        <section
          className="space-y-5"
          aria-label={t("Choose a processing batch", "选择处理批次")}
        >
          <h2 className="text-lg font-semibold">
            {t(
              "Choose a collection scope or processing history",
              "选择采集范围或处理历史",
            )}
          </h2>
          {current.data?.latest_attempt && (
            <p className="text-sm text-muted-foreground">
              {t("Latest processing attempt", "最近处理尝试")}:{" "}
              {netflowText(current.data.latest_attempt.status, t)} ·{" "}
              {date(
                current.data.latest_attempt.completed_at ??
                  current.data.latest_attempt.created_at,
              )}
            </p>
          )}
          {(current.data?.scopes?.length ?? 0) > 1 && (
            <section
              className="space-y-2"
              aria-label={t("Collection scopes", "采集范围")}
            >
              <p className="text-sm text-muted-foreground">
                {t(
                  "More than one confirmed collection scope is available. Choose one before reading a fixed result.",
                  "存在多个已确认采集范围。请先选择范围，再读取固定结果。",
                )}
              </p>
              <div className="flex flex-wrap gap-2">
                {current.data?.scopes.map((row) => (
                  <Button
                    key={row.scope_id}
                    variant="outline"
                    onClick={() =>
                      void navigate({
                        search: (previous) => ({
                          ...previous,
                          collectionScope: row.scope_id,
                        }),
                      })
                    }
                  >
                    {row.label} · {row.network_namespace}
                  </Button>
                ))}
              </div>
            </section>
          )}
          {!search.history && !search.dataset ? (
            <div className="space-y-3">
              <p>
                {t(
                  "No readable result is selected yet. Choose a confirmed scope above, or prepare processing data.",
                  "尚未定位可读的处理结果。可选择上方已确认范围，或准备处理资料。",
                )}
              </p>
              <Button
                variant="outline"
                onClick={() =>
                  void navigate({ search: () => ({ history: true }) })
                }
              >
                {t("Browse processing history", "浏览处理历史")}
              </Button>
            </div>
          ) : datasets.isPending ? (
            <p role="status">
              {t("Loading uploaded data…", "正在读取上传数据…")}
            </p>
          ) : (
            <>
              {!datasets.data?.count && (
                <p>
                  {t(
                    "No NetFlow uploads in this project.",
                    "本项目尚无 NetFlow 上传数据。",
                  )}
                </p>
              )}
              <div className="flex flex-wrap gap-2">
                {datasets.data?.data.map((row) => (
                  <Button
                    key={row.id}
                    variant={search.dataset === row.id ? "default" : "outline"}
                    onClick={() =>
                      void navigate({
                        search: () => ({
                          dataset: row.id,
                          datasetPage: search.datasetPage,
                        }),
                      })
                    }
                  >
                    {row.display_filename}
                  </Button>
                ))}
              </div>
              <ResultPagination
                label={t("Uploads", "上传数据")}
                count={datasets.data?.count ?? 0}
                page={search.datasetPage ?? 0}
                pageSize={SIZE}
                onPageChange={(page) => change({ datasetPage: page })}
              />
            </>
          )}
          {search.dataset && (
            <div className="space-y-3">
              <h3 className="font-medium">
                {t("Processing batches", "处理批次")}
              </h3>
              {batches.isPending ? (
                <p role="status">{t("Loading batches…", "正在读取批次…")}</p>
              ) : !batches.data?.count ? (
                <p>
                  {t(
                    "No processing batch exists for this upload. Open Source comparison to prepare processing.",
                    "该上传数据尚无处理批次。可前往来源比对准备处理。",
                  )}
                </p>
              ) : (
                <ul className="space-y-2">
                  {batches.data?.data.map((row) => (
                    <li
                      key={row.analysis_id}
                      className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3"
                    >
                      <span>
                        {date(row.completed_at ?? row.created_at)} ·{" "}
                        {netflowText(row.status, t)} · {row.network_namespace}
                      </span>
                      <Button
                        variant="outline"
                        disabled={
                          !row.can_read_result ||
                          !["SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"].includes(
                            row.status,
                          )
                        }
                        onClick={() =>
                          void navigate({
                            search: () => ({
                              analysis: row.analysis_id,
                              dataset: row.dataset_id,
                            }),
                          })
                        }
                      >
                        {t("Open batch", "打开批次")}
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
              <ResultPagination
                label={t("Batches", "处理批次")}
                count={batches.data?.count ?? 0}
                page={search.batchPage ?? 0}
                pageSize={SIZE}
                onPageChange={(page) => change({ batchPage: page })}
              />
            </div>
          )}
        </section>
      ) : batch.isPending ? (
        <p role="status">
          {t("Verifying the fixed batch…", "正在验证固定批次…")}
        </p>
      ) : !readable ? (
        <section role="alert" className="rounded-lg border p-4">
          <h2 className="font-semibold">
            {t(
              "This batch has no readable published result",
              "该批次没有可读的已发布结果",
            )}
          </h2>
          <p>
            {netflowText(identity?.status ?? "UNKNOWN", t)} ·{" "}
            {t(
              "Incomplete, failed or isolated input is not an empty result.",
              "未完成、失败或全部隔离不能视为空结果。",
            )}
          </p>
        </section>
      ) : (
        <>
          <section
            className="space-y-3"
            aria-label={t("Fixed processing batch", "固定处理批次")}
          >
            <p className="text-sm">
              {t("Network scope", "网络范围")}: {identity?.network_namespace} ·{" "}
              {t("Processing completed", "处理完成时间")}:{" "}
              {date(identity?.completed_at)}
            </p>
            {current.data?.latest_attempt &&
              current.data.latest_attempt.analysis_id !==
                identity?.analysis_id && (
                <p className="text-sm text-muted-foreground">
                  {t(
                    "A newer processing attempt is available.",
                    "有新的处理结果可供查看。",
                  )}
                </p>
              )}
            <p className="text-sm">
              {t("Observation window", "实际观测窗口")}:{" "}
              {identity?.observation_window?.state === "NOT_PROVIDED"
                ? t("Not provided", "未提供")
                : t("Unknown", "未知")}
            </p>
            {identity?.test_fixture && (
              <p className="text-sm text-muted-foreground">
                {t("Synthetic test data", "合成测试数据")}
              </p>
            )}
            <details className="text-sm">
              <summary className="cursor-pointer">
                {t("Batch identity and input context", "批次身份与输入上下文")}
              </summary>
              <div className="mt-2 space-y-2">
                <TechnicalValue
                  label={t("Analysis ID", "处理批次标识")}
                  value={identity?.analysis_id ?? ""}
                />
                <p>
                  {t("Created", "创建时间")}: {date(identity?.created_at)}
                </p>
                <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all rounded border p-3">
                  {JSON.stringify(
                    {
                      dataset: identity?.dataset_id,
                      context: identity?.context_revision_id,
                      input: identity?.context,
                      provenance: identity?.provenance,
                    },
                    null,
                    2,
                  )}
                </pre>
              </div>
            </details>
          </section>
          <section
            className="flex flex-wrap gap-2"
            aria-label={t("Result views", "结果视图")}
          >
            {(["observations", "peers"] as const).map((value) => (
              <Button
                key={value}
                variant={tab === value ? "default" : "outline"}
                aria-pressed={tab === value}
                onClick={() =>
                  change({
                    tab: value,
                    resultPage: 0,
                    ip: undefined,
                    protocol: undefined,
                    port: undefined,
                    object: undefined,
                    peer: undefined,
                    evidence: false,
                    evidencePage: 0,
                  })
                }
              >
                {value === "observations"
                  ? t("Source observations", "源侧观测")
                  : t("External peers", "外侧对端")}
              </Button>
            ))}
          </section>
          {tab === "observations" && observations.data && (
            <section
              className="grid gap-3 sm:grid-cols-3"
              aria-label={t("Batch counts", "批次计数")}
            >
              {[
                [
                  t("Original rows", "原始行数"),
                  observations.data.raw_record_count,
                ],
                [
                  t("Observation objects", "观测对象数"),
                  observations.data.total_observations,
                ],
                [
                  t("Distinct source IPs", "不同源 IP 数"),
                  observations.data.total_addresses,
                ],
              ].map(([label, value]) => (
                <div className="rounded-lg border p-4" key={label}>
                  <p className="text-sm text-muted-foreground">{label}</p>
                  <output
                    className="mt-2 text-2xl font-semibold tabular-nums"
                    aria-label={String(label)}
                  >
                    {value}
                  </output>
                </div>
              ))}
            </section>
          )}
          {tab === "observations" && observations.data && (
            <p className="text-sm text-muted-foreground">
              {t(
                "Records contributing to source observations",
                "贡献源侧观测的记录数",
              )}
              : {observations.data.total_source_records} ·{" "}
              {t("Observation time: unknown", "观测时间：未知")} ·{" "}
              {t(
                "Processing time is not observation time.",
                "处理时间不代表观测时间。",
              )}
            </p>
          )}
          {tab === "peers" && (
            <p className="text-sm text-muted-foreground">
              {t(
                "Destination-side peers are a separate collection and are excluded from source IP and observation counts.",
                "目的侧对端是独立集合，不计入源 IP 或源侧观测数量。",
              )}
              {peers.data && (
                <>
                  {" "}
                  {t("All peers", "全部对端")}: {peers.data.total_peers} ·{" "}
                  {t("Peer records", "对端记录数")}:{" "}
                  {peers.data.total_peer_records}
                </>
              )}
            </p>
          )}
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(event) => {
              event.preventDefault()
              change({
                ip: ip.trim() || undefined,
                protocol: protocol === "" ? undefined : Number(protocol),
                port: port === "" ? undefined : Number(port),
                resultPage: 0,
                object: undefined,
                peer: undefined,
                evidence: false,
                evidencePage: 0,
              })
            }}
          >
            <Label className="grid gap-2">
              {t("Exact IP", "精确 IP")}
              <Input
                value={ip}
                onChange={(event) => setIp(event.target.value)}
                className="w-48"
              />
            </Label>
            <Label className="grid gap-2">
              {t("Protocol number", "协议编号")}
              <Input
                type="number"
                min={0}
                max={255}
                value={protocol}
                onChange={(event) => setProtocol(event.target.value)}
                className="w-36"
              />
            </Label>
            <Label className="grid gap-2">
              {tab === "observations"
                ? t("Source-side port", "源侧端口")
                : t("Peer port", "对端端口")}
              <Input
                type="number"
                min={0}
                max={65535}
                value={port}
                onChange={(event) => setPort(event.target.value)}
                className="w-36"
              />
            </Label>
            <Button type="submit">{t("Filter", "筛选")}</Button>
            <Button
              type="button"
              variant="outline"
              onClick={() =>
                change({
                  ip: undefined,
                  protocol: undefined,
                  port: undefined,
                  resultPage: 0,
                  object: undefined,
                  peer: undefined,
                  evidence: false,
                })
              }
            >
              {t("Clear", "清除")}
            </Button>
            <Label className="grid gap-2">
              {t("Order", "排序")}
              <select
                className="h-9 rounded-md border bg-background px-2"
                value={search.sort ?? "ip_asc"}
                onChange={(event) =>
                  change({
                    sort: event.target.value as "ip_asc" | "ip_desc",
                    resultPage: 0,
                  })
                }
              >
                <option value="ip_asc">{t("IP ascending", "IP 升序")}</option>
                <option value="ip_desc">{t("IP descending", "IP 降序")}</option>
              </select>
            </Label>
          </form>
          {(
            tab === "observations"
              ? observations.isPending
              : peers.isPending
          ) ? (
            <p role="status">{t("Loading records…", "正在读取记录…")}</p>
          ) : (
            <>
              <p className="text-sm">
                {t("Filtered total", "筛选总数")}: {pageData?.count}
              </p>
              {!rows?.length ? (
                <p>
                  {t(
                    "No records match this query in the selected batch.",
                    "本批次没有匹配此查询的记录。",
                  )}
                </p>
              ) : (
                <section
                  className="overflow-x-auto"
                  aria-label={t("Processed record table", "处理记录表格")}
                >
                  <table className="w-full min-w-[36rem] text-left text-sm">
                    <thead>
                      <tr className="border-b">
                        <th className="p-3">IP</th>
                        <th className="p-3">{t("Protocol", "协议")}</th>
                        <th className="p-3">
                          {tab === "observations"
                            ? t("Source-side port", "源侧端口")
                            : t("Peer port", "对端端口")}
                        </th>
                        <th className="p-3">{t("Records", "记录数")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row) => (
                        <tr key={row.key} className="border-b">
                          <td className="p-3">
                            <button
                              type="button"
                              className="rounded font-mono underline focus-visible:outline-2 focus-visible:outline-offset-2"
                              onClick={() =>
                                change(
                                  tab === "observations"
                                    ? {
                                        object: row.key,
                                        evidence: false,
                                        evidencePage: 0,
                                      }
                                    : {
                                        peer: row.key,
                                        evidence: true,
                                        evidencePage: 0,
                                      },
                                )
                              }
                            >
                              {row.ip}
                            </button>
                          </td>
                          <td className="p-3">
                            {netflowProtocol(row.protocol, t)}
                          </td>
                          <td className="p-3">{row.port ?? "—"}</td>
                          <td className="p-3 tabular-nums">{row.records}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </section>
              )}
              <ResultPagination
                label={
                  tab === "observations"
                    ? t("Observations", "观测对象")
                    : t("Peers", "对端")
                }
                count={pageData?.count ?? 0}
                page={search.resultPage ?? 0}
                pageSize={SIZE}
                onPageChange={(page) =>
                  change({
                    resultPage: page,
                    object: undefined,
                    peer: undefined,
                    evidence: false,
                    evidencePage: 0,
                  })
                }
              />
            </>
          )}
          {tab === "observations" && search.object && (
            <section
              ref={detailTarget}
              tabIndex={-1}
              className="space-y-3 rounded-lg border p-4"
              aria-label={t("Observation details", "观测详情")}
            >
              <h2 className="text-lg font-semibold">
                {t("Observation details", "观测详情")}
              </h2>
              {detail.isPending ? (
                <p role="status">
                  {t("Loading observation…", "正在读取观测…")}
                </p>
              ) : (
                detail.data && (
                  <>
                    <p className="break-all font-mono">
                      {detail.data.canonical_ip} ·{" "}
                      {netflowProtocol(detail.data.protocol_number, t)}
                    </p>
                    <p>
                      {t("Source-side observed port", "源侧观测端口")}:{" "}
                      {detail.data.source_port ?? "—"}
                    </p>
                    <p>
                      {t("Source-side records", "源侧记录数")}:{" "}
                      {detail.data.source_record_count}
                    </p>
                    <p>{t("Observation time: unknown", "观测时间：未知")}</p>
                    <p className="text-sm text-muted-foreground">
                      {t(
                        "Source-side position does not identify the connection initiator or a listening service. Verify the original timing and service role before making service conclusions.",
                        "源侧位置不代表连接发起方或监听服务。判断服务前，请核对原始时间和服务角色。",
                      )}
                    </p>
                    <Button
                      variant="outline"
                      onClick={() =>
                        change({ evidence: true, evidencePage: 0 })
                      }
                    >
                      {t("View input evidence", "查看输入证据")}
                    </Button>
                    <details className="text-sm">
                      <summary className="cursor-pointer">
                        {t(
                          "Original observation and context",
                          "原始观测与上下文",
                        )}
                      </summary>
                      <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-all rounded border p-3">
                        {JSON.stringify(detail.data, null, 2)}
                      </pre>
                    </details>
                  </>
                )
              )}
            </section>
          )}
          {search.evidence && (
            <section
              ref={evidenceTarget}
              tabIndex={-1}
              className="space-y-3 rounded-lg border p-4"
              aria-label={t("Input evidence", "输入证据")}
            >
              <h2 className="text-lg font-semibold">
                {t("Input evidence", "输入证据")}
              </h2>
              {evidence.isPending ? (
                <p role="status">{t("Loading evidence…", "正在读取证据…")}</p>
              ) : (
                evidence.data && (
                  <>
                    <p className="text-sm">
                      {t("Retained references", "保留引用数")}:{" "}
                      {evidence.data.retained_count} ·{" "}
                      {t("Omitted references", "省略引用数")}:{" "}
                      {evidence.data.omitted_count}
                    </p>
                    <ul className="space-y-2">
                      {evidence.data.data.map((row) => (
                        <li
                          key={`${row.side}:${row.reference}`}
                          className="break-all font-mono text-sm"
                        >
                          {row.reference}
                        </li>
                      ))}
                    </ul>
                    <ResultPagination
                      label={t("Evidence", "证据")}
                      count={evidence.data.count}
                      page={search.evidencePage ?? 0}
                      pageSize={EVIDENCE_SIZE}
                      onPageChange={(page) => change({ evidencePage: page })}
                    />
                    <details className="text-sm">
                      <summary className="cursor-pointer">
                        {t("Evidence identity and hashes", "证据身份与 Hash")}
                      </summary>
                      <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all rounded border p-3">
                        {JSON.stringify(evidence.data, null, 2)}
                      </pre>
                    </details>
                  </>
                )
              )}
            </section>
          )}
        </>
      )}
    </main>
  )
}
