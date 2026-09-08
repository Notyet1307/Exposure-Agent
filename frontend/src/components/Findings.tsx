import { useQuery } from "@tanstack/react-query"
import { useEffect, useRef } from "react"

import {
  type FindingDetailPublic,
  type FindingOccurrencePublic,
  type FindingPublic,
  type FindingTransitionPublic,
  type IPObservationPublic,
  IpResultsService,
  type SourceSnapshotPublic,
} from "@/client"
import { ResultPagination } from "@/components/ResultPagination"
import { Stage4ResultNotice } from "@/components/Stage4ResultNotice"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

import { useI18n } from "@/lib/i18n"
import { useWorkspaceNavigate, useWorkspaceSearch } from "@/lib/workspace"

const PAGE_SIZE = 25
const TRACE_PAGE_SIZE = 20
const FINDING_STATUSES = ["OPEN", "CLOSED"] as const
type FindingStatus = (typeof FINDING_STATUSES)[number]

function findingLabel(findingType: string, t: ReturnType<typeof useI18n>["t"]) {
  if (findingType === "UNREPORTED_ASSET")
    return t("Unreported asset", "未申报资产")
  if (findingType === "UNOBSERVED_ASSET")
    return t("Unobserved asset", "未观测资产")
  return findingType
}

function ObservationTable({
  observations,
}: {
  observations: IPObservationPublic[] | undefined
}) {
  const { t, translateValue } = useI18n()
  if (!observations || observations.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {t("No observations.", "暂无观测记录。")}
      </p>
    )
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("Raw IP", "原始 IP")}</TableHead>
          <TableHead>{t("Canonical IP", "规范化 IP")}</TableHead>
          <TableHead>{t("Source", "来源")}</TableHead>
          <TableHead>{t("Location", "位置")}</TableHead>
          <TableHead>{t("CloudAtlas ID", "CloudAtlas ID")}</TableHead>
          <TableHead>{t("CloudAtlas status", "CloudAtlas 状态")}</TableHead>
          <TableHead>{t("Snapshot", "快照")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {observations.map((observation) => (
          <TableRow key={observation.id}>
            <TableCell className="font-mono text-xs">
              {observation.raw_ip}
            </TableCell>
            <TableCell className="font-mono text-xs">
              {observation.canonical_ip}
            </TableCell>
            <TableCell>{translateValue(observation.source_type)}</TableCell>
            <TableCell className="font-mono text-xs">
              {observation.source_record_key}
            </TableCell>
            <TableCell className="font-mono text-xs">
              {observation.cloudatlas_asset_id ?? "—"}
            </TableCell>
            <TableCell>{observation.cloudatlas_status ?? "—"}</TableCell>
            <TableCell className="font-mono text-xs">
              {observation.source_snapshot_id}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function SnapshotReferences({
  snapshotIds,
  snapshots,
}: {
  snapshotIds: string[] | undefined
  snapshots: SourceSnapshotPublic[] | undefined
}) {
  const { t, translateValue } = useI18n()
  const references = snapshots ?? []
  if (references.length === 0 && (!snapshotIds || snapshotIds.length === 0)) {
    return (
      <p className="text-sm text-muted-foreground">
        {t("No Snapshot references.", "暂无快照引用。")}
      </p>
    )
  }
  return (
    <div className="space-y-2">
      {references.map((snapshot) => (
        <div key={snapshot.id} className="rounded-md border p-2 text-xs">
          <div className="font-medium">
            {translateValue(snapshot.source_type)}
          </div>
          <div className="break-all font-mono">
            {t("Snapshot", "快照")} {snapshot.id}
          </div>
          <div className="break-all">
            {t(
              `${snapshot.record_count} records`,
              `${snapshot.record_count} 条记录`,
            )}{" "}
            · SHA-256 {snapshot.content_sha256}
          </div>
        </div>
      ))}
      {snapshotIds
        ?.filter(
          (snapshotId) =>
            !references.some((snapshot) => snapshot.id === snapshotId),
        )
        .map((snapshotId) => (
          <div key={snapshotId} className="break-all font-mono text-xs">
            {t("Snapshot", "快照")} {snapshotId}
          </div>
        ))}
    </div>
  )
}

function TraceSection({
  title,
  trace,
}: {
  title: string
  trace: FindingOccurrencePublic | FindingTransitionPublic
}) {
  const { t, formatDate } = useI18n()
  return (
    <div className="space-y-3 rounded-md border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium">{title}</h3>
        <span className="break-all text-xs text-muted-foreground">
          {t("Run", "运行")} {trace.governance_run_id} ·{" "}
          {formatDate(trace.created_at)}
        </span>
      </div>
      <ObservationTable observations={trace.observations} />
      <div>
        <p className="mb-2 text-sm font-medium">
          {t("Confirmed Snapshot references", "已确认的快照引用")}
        </p>
        <SnapshotReferences
          snapshotIds={trace.source_snapshot_ids}
          snapshots={trace.source_snapshots}
        />
      </div>
    </div>
  )
}

const NETFLOW_EMPTY_MESSAGES: Record<
  Exclude<
    FindingDetailPublic["netflow_context"]["status"],
    "POSITIVE_ACTIVITY"
  >,
  [string, string]
> = Object.setPrototypeOf(
  {
    NOT_APPLICABLE: [
      "Not applicable to this Finding in this Run. This does not describe whether the resource has traffic.",
      "不适用于此运行中的该发现项。这并不说明该资源是否有流量。",
    ],
    INPUT_UNMODELED: [
      "This historical Run did not model NetFlow input.",
      "该历史运行未建模 NetFlow 输入。",
    ],
    INPUT_ABSENT: [
      "No NetFlow input was provided for this Run.",
      "此运行未提供 NetFlow 输入。",
    ],
    ACTIVITY_UNMODELED: [
      "This historical Run did not model the NetFlow activity contract.",
      "该历史运行未建模 NetFlow 活动合同。",
    ],
    NO_POSITIVE_ACTIVITY: [
      "This Run has no positive NetFlow activity evidence for this resource. This does not mean no traffic or zero risk.",
      "此运行没有该资源的正向 NetFlow 活动证据。这不意味着没有流量或零风险。",
    ],
  },
  null,
)

function NetFlowContext({
  context,
}: {
  context: FindingDetailPublic["netflow_context"]
}) {
  const { t, language } = useI18n()
  const activity = context.activity
  const emptyMessage =
    context.status === "POSITIVE_ACTIVITY"
      ? undefined
      : NETFLOW_EMPTY_MESSAGES[context.status]
  return (
    <section
      aria-labelledby="finding-netflow-title"
      className="min-w-0 space-y-3 rounded-md border p-3 text-sm"
    >
      <h3 id="finding-netflow-title" className="font-medium">
        {t(
          "Latest published Run NetFlow activity",
          "最近已发布运行的 NetFlow 活动",
        )}
      </h3>
      <p className="break-all font-mono text-xs">
        {t("Run", "运行")} {context.governance_run_id}
      </p>
      <p className="text-muted-foreground">
        {t(
          "Activity is supplementary context only. It does not establish that the Finding still applies or change its status or lifecycle.",
          "活动仅为补充上下文，不能证明该发现项仍然适用，也不会改变其状态或生命周期。",
        )}
      </p>
      {activity ? (
        <>
          <p className="text-xs text-muted-foreground">
            {t(
              `Activity times use your local time zone (${Intl.DateTimeFormat().resolvedOptions().timeZone}).`,
              `活动时间使用您的本地时区（${Intl.DateTimeFormat().resolvedOptions().timeZone}）。`,
            )}
          </p>
          <dl className="grid min-w-0 gap-3 sm:grid-cols-2">
            <div>
              <dt className="font-medium">
                {t("Sampled flow records", "采样流记录")}
              </dt>
              <dd>{activity.flow_count}</dd>
              <dd className="text-xs text-muted-foreground">
                {t(
                  "Not distinct connections, sessions, or events.",
                  "并非独立连接、会话或事件的数量。",
                )}
              </dd>
            </div>
            <div>
              <dt className="font-medium">{t("First activity", "首次活动")}</dt>
              <dd>
                {activity.first_seen_utc === null
                  ? t("Not provided", "未提供")
                  : new Date(activity.first_seen_utc).toLocaleString(
                      language === "en" ? "en-US" : "zh-CN",
                    )}
              </dd>
            </div>
            <div>
              <dt className="font-medium">{t("Last activity", "末次活动")}</dt>
              <dd>
                {activity.last_seen_utc === null
                  ? t("Not provided", "未提供")
                  : new Date(activity.last_seen_utc).toLocaleString(
                      language === "en" ? "en-US" : "zh-CN",
                    )}
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="font-medium">{t("Activity ID", "活动 ID")}</dt>
              <dd className="break-all font-mono text-xs">
                {activity.activity_id}
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="font-medium">
                {t("NETFLOW Snapshot ID", "NETFLOW 快照 ID")}
              </dt>
              <dd className="break-all font-mono text-xs">
                {activity.source_snapshot_id}
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="font-medium">
                {t("Aggregation contract", "聚合合同")}
              </dt>
              <dd className="break-all font-mono text-xs">
                {activity.aggregation_contract_version}
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="font-medium">
                {t("Content SHA-256", "内容 SHA-256")}
              </dt>
              <dd className="break-all font-mono text-xs">
                {activity.content_sha256}
              </dd>
            </div>
          </dl>
        </>
      ) : context.status !== "POSITIVE_ACTIVITY" ? (
        <p className="text-muted-foreground">
          {emptyMessage
            ? t(...emptyMessage)
            : t(
                `Unknown NetFlow context status: ${context.status}`,
                `未知的 NetFlow 上下文状态：${context.status}`,
              )}
        </p>
      ) : null}
    </section>
  )
}

function FindingDetailDialog({
  projectId,
  findingId,
  onOpenChange,
}: {
  projectId: string
  findingId: string | null
  onOpenChange: (open: boolean) => void
}) {
  const { t, formatDate, translateValue } = useI18n()
  const search = useWorkspaceSearch()
  const navigate = useWorkspaceNavigate()
  const occurrencePage = (search.occurrence_page ?? 1) - 1
  const transitionPage = (search.transition_page ?? 1) - 1
  const returnFocusRef = useRef<HTMLElement | null>(null)
  const detailQuery = useQuery({
    queryKey: ["finding", projectId, findingId, occurrencePage, transitionPage],
    queryFn: async () => {
      const detail = await IpResultsService.readFinding({
        projectId,
        findingId: findingId as string,
        occurrenceSkip: occurrencePage * TRACE_PAGE_SIZE,
        transitionSkip: transitionPage * TRACE_PAGE_SIZE,
        traceLimit: TRACE_PAGE_SIZE,
      })
      if (
        (detail.netflow_context.status === "POSITIVE_ACTIVITY") !==
        (detail.netflow_context.activity !== null)
      ) {
        throw new Error("Invalid Finding NetFlow context")
      }
      return detail
    },
    enabled: findingId !== null,
  })

  useEffect(() => {
    if (findingId === null || !detailQuery.data) return
    const occurrencePageCount = Math.max(
      1,
      Math.ceil(detailQuery.data.occurrence_count / TRACE_PAGE_SIZE),
    )
    const transitionPageCount = Math.max(
      1,
      Math.ceil(detailQuery.data.transition_count / TRACE_PAGE_SIZE),
    )
    if (
      occurrencePage >= occurrencePageCount ||
      transitionPage >= transitionPageCount
    ) {
      void navigate({
        search: (prev) => ({
          ...prev,
          occurrence_page:
            occurrencePage >= occurrencePageCount
              ? occurrencePageCount > 1
                ? occurrencePageCount
                : undefined
              : prev.occurrence_page,
          transition_page:
            transitionPage >= transitionPageCount
              ? transitionPageCount > 1
                ? transitionPageCount
                : undefined
              : prev.transition_page,
        }),
        replace: true,
      })
    }
  }, [detailQuery.data, findingId, navigate, occurrencePage, transitionPage])

  return (
    <Dialog
      open={findingId !== null}
      onOpenChange={(open) => onOpenChange(open)}
    >
      <DialogContent
        className="max-h-[90vh] max-w-[calc(100%-2rem)] overflow-y-auto sm:max-w-6xl"
        onOpenAutoFocus={() => {
          returnFocusRef.current =
            document.activeElement instanceof HTMLElement
              ? document.activeElement
              : null
        }}
        onCloseAutoFocus={(event) => {
          event.preventDefault()
          returnFocusRef.current?.focus()
        }}
      >
        <DialogHeader>
          <DialogTitle>{t("Finding details", "发现项详情")}</DialogTitle>
          <DialogDescription>
            {t(
              "Occurrences, lifecycle transitions, source observations, and confirmed Snapshot references are bounded by the server.",
              "出现记录、生命周期变更、来源观测记录和已确认的快照引用均受服务端数量边界限制。",
            )}
          </DialogDescription>
        </DialogHeader>
        {detailQuery.isPending && (
          <p role="status">
            {t("Loading Finding details…", "正在加载发现项详情…")}
          </p>
        )}
        {detailQuery.isError && (
          <Alert variant="destructive">
            <AlertTitle>
              {t("Finding details could not be loaded", "无法加载发现项详情")}
            </AlertTitle>
            <AlertDescription>
              {t("Please try again later.", "请稍后重试。")}
            </AlertDescription>
          </Alert>
        )}
        {detailQuery.data && (
          <div className="min-w-0 space-y-4">
            <div className="grid gap-3 text-sm md:grid-cols-4">
              <div>
                <p className="font-medium">{t("Finding ID", "发现项 ID")}</p>
                <p className="break-all font-mono text-xs">
                  {detailQuery.data.id}
                </p>
              </div>
              <div>
                <p className="font-medium">{t("Canonical IP", "规范化 IP")}</p>
                <p className="break-all font-mono">
                  {detailQuery.data.canonical_ip}
                </p>
              </div>
              <div>
                <p className="font-medium">{t("Status", "状态")}</p>
                <Badge>{translateValue(detailQuery.data.status)}</Badge>
              </div>
              <div>
                <p className="font-medium">
                  {t("Last occurrence", "最近出现")}
                </p>
                <p>
                  {detailQuery.data.latest_occurrence_at
                    ? formatDate(detailQuery.data.latest_occurrence_at)
                    : "—"}
                </p>
                {detailQuery.data.latest_occurrence_run_id && (
                  <p className="break-all font-mono text-xs text-muted-foreground">
                    {t("Run", "运行")}{" "}
                    {detailQuery.data.latest_occurrence_run_id}
                  </p>
                )}
              </div>
            </div>
            <NetFlowContext context={detailQuery.data.netflow_context} />
            <div>
              <p className="mb-2 text-sm font-medium">
                {t("Occurrences", "出现记录")}
              </p>
              {(detailQuery.data.occurrences ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  {t("No Finding Occurrences.", "暂无发现项出现记录。")}
                </p>
              ) : (
                <div className="space-y-3">
                  {(detailQuery.data.occurrences ?? []).map((occurrence) => (
                    <TraceSection
                      key={occurrence.id}
                      title={t("Occurrence", "出现记录")}
                      trace={occurrence}
                    />
                  ))}
                  <ResultPagination
                    label={t("Finding occurrences", "发现项出现记录")}
                    count={detailQuery.data.occurrence_count}
                    page={occurrencePage}
                    pageSize={TRACE_PAGE_SIZE}
                    onPageChange={(nextPage) =>
                      navigate({
                        search: (prev) => ({
                          ...prev,
                          occurrence_page:
                            nextPage > 0 ? nextPage + 1 : undefined,
                        }),
                      })
                    }
                  />
                </div>
              )}
            </div>
            <div>
              <p className="mb-2 text-sm font-medium">
                {t("Transitions", "状态变更")}
              </p>
              {(detailQuery.data.transitions ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  {t("No Finding Transitions.", "暂无发现项状态变更。")}
                </p>
              ) : (
                <div className="space-y-3">
                  {(detailQuery.data.transitions ?? []).map((transition) => (
                    <TraceSection
                      key={transition.id}
                      title={t(
                        `Transition · ${transition.transition_type}`,
                        `状态变更 · ${translateValue(transition.transition_type)}`,
                      )}
                      trace={transition}
                    />
                  ))}
                  <ResultPagination
                    label={t("Finding transitions", "发现项状态变更")}
                    count={detailQuery.data.transition_count}
                    page={transitionPage}
                    pageSize={TRACE_PAGE_SIZE}
                    onPageChange={(nextPage) =>
                      navigate({
                        search: (prev) => ({
                          ...prev,
                          transition_page:
                            nextPage > 0 ? nextPage + 1 : undefined,
                        }),
                      })
                    }
                  />
                </div>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function FindingRow({
  finding,
  onDetails,
}: {
  finding: FindingPublic
  onDetails: () => void
}) {
  const { t, formatDate, translateValue } = useI18n()
  const activityTimes = [
    finding.latest_occurrence_at,
    finding.latest_transition_at,
  ]
    .filter((value): value is string => value !== null)
    .sort()
  const latestActivity = activityTimes[activityTimes.length - 1] ?? null

  return (
    <TableRow>
      <TableCell className="max-w-56 break-all font-mono text-xs">
        {finding.id}
      </TableCell>
      <TableCell>
        <div>{findingLabel(finding.finding_type, t)}</div>
        <div className="font-mono text-xs text-muted-foreground">
          {finding.finding_type}
        </div>
      </TableCell>
      <TableCell>
        <Badge variant={finding.status === "OPEN" ? "destructive" : "default"}>
          {translateValue(finding.status)}
        </Badge>
      </TableCell>
      <TableCell className="font-mono">{finding.canonical_ip}</TableCell>
      <TableCell>
        <div>{latestActivity ? formatDate(latestActivity) : "—"}</div>
        {finding.latest_occurrence_run_id && (
          <div className="break-all font-mono text-xs text-muted-foreground">
            {t("Last occurrence Run", "最近出现的运行")}{" "}
            {finding.latest_occurrence_run_id}
          </div>
        )}
      </TableCell>
      <TableCell>{finding.occurrence_count}</TableCell>
      <TableCell>{finding.transition_count}</TableCell>
      <TableCell>
        <LoadingButton
          type="button"
          variant="outline"
          size="sm"
          onClick={onDetails}
        >
          {t("View details", "查看详情")}
        </LoadingButton>
      </TableCell>
    </TableRow>
  )
}

export default function Findings({ projectId }: { projectId: string }) {
  const { t, translateValue } = useI18n()
  const search = useWorkspaceSearch()
  const navigate = useWorkspaceNavigate()
  const status = search.finding_status ?? "OPEN"
  const page = (search.findings_page ?? 1) - 1
  const selectedFindingId = search.finding_id ?? null
  const findingsQuery = useQuery({
    queryKey: ["findings", projectId, status, page],
    queryFn: () =>
      IpResultsService.readFindings({
        projectId,
        status,
        skip: page * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
  })

  useEffect(() => {
    if (!findingsQuery.data) return
    const pageCount = Math.max(
      1,
      Math.ceil(findingsQuery.data.count / PAGE_SIZE),
    )
    if (page >= pageCount) {
      void navigate({
        search: (prev) => ({
          ...prev,
          findings_page: pageCount > 1 ? pageCount : undefined,
        }),
        replace: true,
      })
    }
  }, [findingsQuery.data, navigate, page])

  if (findingsQuery.isPending)
    return <p role="status">{t("Loading Findings…", "正在加载发现项…")}</p>
  if (findingsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>
          {t("Findings could not be loaded", "无法加载发现项")}
        </AlertTitle>
        <AlertDescription>
          {t("Please try again later.", "请稍后重试。")}
        </AlertDescription>
      </Alert>
    )
  }

  const findings = findingsQuery.data
  if (!findings.compatible) {
    return (
      <Stage4ResultNotice
        latestRunId={findings.latest_run_id}
        latestRunCompletedAt={findings.latest_run_completed_at}
      />
    )
  }

  return (
    <section className="space-y-4" aria-labelledby="findings-title">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle id="findings-title">
                {t("Findings", "发现项")}
              </CardTitle>
              <CardDescription>
                {t(
                  "Deterministic IP Findings from the latest compatible completed Run. OPEN Findings remain visible until positive matching evidence closes them.",
                  "来自最近一次兼容且已完成运行的确定性 IP 发现项。OPEN（未关闭）发现项会持续显示，直至明确的匹配证据将其关闭。",
                )}
                {findings.latest_run_id && (
                  <span className="block break-all font-mono text-xs">
                    {t("Published Run", "已发布运行")} {findings.latest_run_id}
                  </span>
                )}
              </CardDescription>
            </div>
            <div className="space-y-2">
              <label
                className="text-sm font-medium"
                htmlFor={`finding-status-${projectId}`}
              >
                {t("Finding status", "发现项状态")}
              </label>
              <Select
                value={status}
                onValueChange={(value) => {
                  void navigate({
                    search: (prev) => ({
                      ...prev,
                      finding_status: value as FindingStatus,
                      findings_page: undefined,
                      finding_id: undefined,
                      occurrence_page: undefined,
                      transition_page: undefined,
                    }),
                  })
                }}
              >
                <SelectTrigger
                  id={`finding-status-${projectId}`}
                  className="w-36"
                  aria-label={t("Finding status", "发现项状态")}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {FINDING_STATUSES.map((findingStatus) => (
                    <SelectItem key={findingStatus} value={findingStatus}>
                      {translateValue(findingStatus)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {findings.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t(
                `No ${status} Findings.`,
                `暂无 ${translateValue(status)} 发现项。`,
              )}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("Finding ID", "发现项 ID")}</TableHead>
                  <TableHead>{t("Type", "类型")}</TableHead>
                  <TableHead>{t("Status", "状态")}</TableHead>
                  <TableHead>{t("Canonical IP", "规范化 IP")}</TableHead>
                  <TableHead>
                    {t("Latest occurrence / transition", "最近出现 / 状态变更")}
                  </TableHead>
                  <TableHead>{t("Occurrences", "出现记录")}</TableHead>
                  <TableHead>{t("Transitions", "状态变更")}</TableHead>
                  <TableHead>{t("Details", "详情")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {findings.data.map((finding) => (
                  <FindingRow
                    key={finding.id}
                    finding={finding}
                    onDetails={() =>
                      navigate({
                        search: (prev) => ({
                          ...prev,
                          finding_id: finding.id,
                          occurrence_page: undefined,
                          transition_page: undefined,
                        }),
                      })
                    }
                  />
                ))}
              </TableBody>
            </Table>
          )}
          <ResultPagination
            label={t("Findings", "发现项")}
            count={findings.count}
            page={page}
            pageSize={PAGE_SIZE}
            onPageChange={(nextPage) =>
              navigate({
                search: (prev) => ({
                  ...prev,
                  findings_page: nextPage > 0 ? nextPage + 1 : undefined,
                }),
              })
            }
          />
        </CardContent>
      </Card>
      <FindingDetailDialog
        projectId={projectId}
        findingId={selectedFindingId}
        onOpenChange={(open) => {
          if (!open) {
            void navigate({
              search: (prev) => ({
                ...prev,
                finding_id: undefined,
                occurrence_page: undefined,
                transition_page: undefined,
              }),
            })
          }
        }}
      />
    </section>
  )
}
