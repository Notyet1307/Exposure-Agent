import { useQuery } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"

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
import { useLocale } from "@/components/LocaleProvider"
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

const PAGE_SIZE = 25
const TRACE_PAGE_SIZE = 20
const FINDING_STATUSES = ["OPEN", "CLOSED"] as const
type FindingStatus = (typeof FINDING_STATUSES)[number]
type Localize = (chinese: string, english: string) => string

function findingLabel(findingType: string, text: Localize) {
  if (findingType === "UNREPORTED_ASSET") {
    return text("未报备资产", "Unreported asset")
  }
  if (findingType === "UNOBSERVED_ASSET") {
    return text("未观测资产", "Unobserved asset")
  }
  return findingType
}

function findingStatusLabel(status: string, text: Localize) {
  if (status === "OPEN") return text("未关闭（OPEN）", "OPEN")
  if (status === "CLOSED") return text("已关闭（CLOSED）", "CLOSED")
  return status
}

function formatDate(value: string | null, locale: string) {
  return value ? new Date(value).toLocaleString(locale) : "—"
}

function ObservationTable({
  observations,
  text,
}: {
  observations: IPObservationPublic[] | undefined
  text: Localize
}) {
  if (!observations || observations.length === 0) {
    return <p className="text-sm text-muted-foreground">{text("暂无观测记录。", "No observations.")}</p>
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{text("原始 IP", "Raw IP")}</TableHead>
          <TableHead>{text("规范 IP", "Canonical IP")}</TableHead>
          <TableHead>{text("来源", "Source")}</TableHead>
          <TableHead>{text("位置", "Location")}</TableHead>
          <TableHead>{text("CloudAtlas ID", "CloudAtlas ID")}</TableHead>
          <TableHead>{text("CloudAtlas 状态", "CloudAtlas status")}</TableHead>
          <TableHead>{text("快照", "Snapshot")}</TableHead>
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
            <TableCell>{observation.source_type}</TableCell>
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
  text,
}: {
  snapshotIds: string[] | undefined
  snapshots: SourceSnapshotPublic[] | undefined
  text: Localize
}) {
  const references = snapshots ?? []
  if (references.length === 0 && (!snapshotIds || snapshotIds.length === 0)) {
    return (
      <p className="text-sm text-muted-foreground">{text("没有快照引用。", "No Snapshot references.")}</p>
    )
  }
  return (
    <div className="space-y-2">
      {references.map((snapshot) => (
        <div key={snapshot.id} className="rounded-md border p-2 text-xs">
          <div className="font-medium">{snapshot.source_type}</div>
          <div className="break-all font-mono">{text("快照 ", "Snapshot ")}{snapshot.id}</div>
          <div className="break-all">
            {text(`${snapshot.record_count} 条记录`, `${snapshot.record_count} records`)} · SHA-256 {snapshot.content_sha256}
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
            {text("快照 ", "Snapshot ")}{snapshotId}
          </div>
        ))}
    </div>
  )
}

function TraceSection({
  title,
  trace,
  locale,
  text,
}: {
  title: string
  trace: FindingOccurrencePublic | FindingTransitionPublic
  locale: string
  text: Localize
}) {
  return (
    <div className="space-y-3 rounded-md border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium">{title}</h3>
        <span className="break-all text-xs text-muted-foreground">
          {text("治理运行 ", "Run ")}{trace.governance_run_id} · {formatDate(trace.created_at, locale)}
        </span>
      </div>
      <ObservationTable observations={trace.observations} text={text} />
      <div>
        <p className="mb-2 text-sm font-medium">
          {text("已确认的快照引用", "Confirmed Snapshot references")}
        </p>
        <SnapshotReferences
          snapshotIds={trace.source_snapshot_ids}
          snapshots={trace.source_snapshots}
          text={text}
        />
      </div>
    </div>
  )
}

function netflowEmptyMessage(
  status: Exclude<
    FindingDetailPublic["netflow_context"]["status"],
    "POSITIVE_ACTIVITY"
  >,
  text: Localize,
) {
  switch (status) {
    case "NOT_APPLICABLE":
      return text(
        "本次运行不适用于该发现项；这并不说明该资源是否存在流量。",
        "Not applicable to this Finding in this Run. This does not describe whether the resource has traffic.",
      )
    case "INPUT_UNMODELED":
      return text("该历史运行未建模 NetFlow 输入。", "This historical Run did not model NetFlow input.")
    case "INPUT_ABSENT":
      return text("本次运行未提供 NetFlow 输入。", "No NetFlow input was provided for this Run.")
    case "ACTIVITY_UNMODELED":
      return text("该历史运行未建模 NetFlow 活动契约。", "This historical Run did not model the NetFlow activity contract.")
    case "NO_POSITIVE_ACTIVITY":
      return text(
        "本次运行没有该资源的正向 NetFlow 活动证据；这不代表没有流量或风险为零。",
        "This Run has no positive NetFlow activity evidence for this resource. This does not mean no traffic or zero risk.",
      )
  }
}

function NetFlowContext({
  context,
}: {
  context: FindingDetailPublic["netflow_context"]
}) {
  const { locale, text } = useLocale()
  const activity = context.activity
  return (
    <section
      aria-labelledby="finding-netflow-title"
      className="min-w-0 space-y-3 rounded-md border p-3 text-sm"
    >
      <h3 id="finding-netflow-title" className="font-medium">
        {text("最近已发布治理运行的 NetFlow 活动", "Latest published Run NetFlow activity")}
      </h3>
      <p className="break-all font-mono text-xs">
        {text("治理运行 ", "Run ")}{context.governance_run_id}
      </p>
      <p className="text-muted-foreground">
        {text(
          "活动仅为补充上下文，不能证明该发现项仍然适用，也不会改变其状态或生命周期。",
          "Activity is supplementary context only. It does not establish that the Finding still applies or change its status or lifecycle.",
        )}
      </p>
      {activity ? (
        <>
          <p className="text-xs text-muted-foreground">
            {text(
              `活动时间使用您的本地时区（${Intl.DateTimeFormat().resolvedOptions().timeZone}）。`,
              `Activity times use your local time zone (${Intl.DateTimeFormat().resolvedOptions().timeZone}).`,
            )}
          </p>
          <dl className="grid min-w-0 gap-3 sm:grid-cols-2">
            <div>
              <dt className="font-medium">{text("采样流记录", "Sampled flow records")}</dt>
              <dd>{activity.flow_count}</dd>
              <dd className="text-xs text-muted-foreground">
                {text("并非不同的连接、会话或事件数量。", "Not distinct connections, sessions, or events.")}
              </dd>
            </div>
            <div>
              <dt className="font-medium">{text("首次活动", "First activity")}</dt>
              <dd>
                {activity.first_seen_utc === null
                  ? text("未提供", "Not provided")
                  : formatDate(activity.first_seen_utc, locale)}
              </dd>
            </div>
            <div>
              <dt className="font-medium">{text("最后活动", "Last activity")}</dt>
              <dd>
                {activity.last_seen_utc === null
                  ? text("未提供", "Not provided")
                  : formatDate(activity.last_seen_utc, locale)}
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="font-medium">{text("活动 ID", "Activity ID")}</dt>
              <dd className="break-all font-mono text-xs">
                {activity.activity_id}
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="font-medium">{text("NETFLOW 快照 ID", "NETFLOW Snapshot ID")}</dt>
              <dd className="break-all font-mono text-xs">
                {activity.source_snapshot_id}
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="font-medium">{text("聚合契约", "Aggregation contract")}</dt>
              <dd className="break-all font-mono text-xs">
                {activity.aggregation_contract_version}
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="font-medium">{text("内容 SHA-256", "Content SHA-256")}</dt>
              <dd className="break-all font-mono text-xs">
                {activity.content_sha256}
              </dd>
            </div>
          </dl>
        </>
      ) : context.status !== "POSITIVE_ACTIVITY" ? (
        <p className="text-muted-foreground">
          {netflowEmptyMessage(context.status, text)}
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
  const { locale, text } = useLocale()
  const [occurrencePage, setOccurrencePage] = useState(0)
  const [transitionPage, setTransitionPage] = useState(0)
  const returnFocusRef = useRef<HTMLElement | null>(null)
  useEffect(() => {
    if (findingId === null) {
      setOccurrencePage(0)
      setTransitionPage(0)
    }
  }, [findingId])
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
          <DialogTitle>{text("发现项详情", "Finding details")}</DialogTitle>
          <DialogDescription>
            {text(
              "发生记录、生命周期变更、来源观测和已确认快照引用均由服务端限定范围。",
              "Occurrences, lifecycle transitions, source observations, and confirmed Snapshot references are bounded by the server.",
            )}
          </DialogDescription>
        </DialogHeader>
        {detailQuery.isPending && <p role="status">{text("正在加载发现项详情…", "Loading Finding details…")}</p>}
        {detailQuery.isError && (
          <Alert variant="destructive">
            <AlertTitle>{text("无法加载发现项详情", "Finding details could not be loaded")}</AlertTitle>
            <AlertDescription>{text("请稍后重试。", "Please try again later.")}</AlertDescription>
          </Alert>
        )}
        {detailQuery.data && (
          <div className="min-w-0 space-y-4">
            <div className="grid gap-3 text-sm md:grid-cols-4">
              <div>
                <p className="font-medium">{text("发现项 ID", "Finding ID")}</p>
                <p className="break-all font-mono text-xs">
                  {detailQuery.data.id}
                </p>
              </div>
              <div>
                <p className="font-medium">{text("规范 IP", "Canonical IP")}</p>
                <p className="break-all font-mono">
                  {detailQuery.data.canonical_ip}
                </p>
              </div>
              <div>
                <p className="font-medium">{text("状态", "Status")}</p>
                <Badge>{findingStatusLabel(detailQuery.data.status, text)}</Badge>
              </div>
              <div>
                <p className="font-medium">{text("最近发生时间", "Last occurrence")}</p>
                <p>{formatDate(detailQuery.data.latest_occurrence_at, locale)}</p>
                {detailQuery.data.latest_occurrence_run_id && (
                  <p className="break-all font-mono text-xs text-muted-foreground">
                    {text("治理运行 ", "Run ")}{detailQuery.data.latest_occurrence_run_id}
                  </p>
                )}
              </div>
            </div>
            <NetFlowContext context={detailQuery.data.netflow_context} />
            <div>
              <p className="mb-2 text-sm font-medium">{text("发生记录", "Occurrences")}</p>
              {(detailQuery.data.occurrences ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  {text("没有发现项发生记录。", "No Finding Occurrences.")}
                </p>
              ) : (
                <div className="space-y-3">
                  {(detailQuery.data.occurrences ?? []).map((occurrence) => (
                    <TraceSection
                      key={occurrence.id}
                      title={text("发生记录", "Occurrence")}
                      trace={occurrence}
                      locale={locale}
                      text={text}
                    />
                  ))}
                  <ResultPagination
                    label={text("发现项发生记录", "Finding occurrences")}
                    count={detailQuery.data.occurrence_count}
                    page={occurrencePage}
                    pageSize={TRACE_PAGE_SIZE}
                    onPageChange={setOccurrencePage}
                  />
                </div>
              )}
            </div>
            <div>
              <p className="mb-2 text-sm font-medium">{text("状态变更", "Transitions")}</p>
              {(detailQuery.data.transitions ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  {text("没有发现项状态变更。", "No Finding Transitions.")}
                </p>
              ) : (
                <div className="space-y-3">
                  {(detailQuery.data.transitions ?? []).map((transition) => (
                    <TraceSection
                      key={transition.id}
                      title={text("状态变更", "Transition") + ` · ${transition.transition_type}`}
                      trace={transition}
                      locale={locale}
                      text={text}
                    />
                  ))}
                  <ResultPagination
                    label={text("发现项状态变更", "Finding transitions")}
                    count={detailQuery.data.transition_count}
                    page={transitionPage}
                    pageSize={TRACE_PAGE_SIZE}
                    onPageChange={setTransitionPage}
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
  locale,
  text,
}: {
  finding: FindingPublic
  onDetails: () => void
  locale: string
  text: Localize
}) {
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
        <div>{findingLabel(finding.finding_type, text)}</div>
        <div className="font-mono text-xs text-muted-foreground">
          {finding.finding_type}
        </div>
      </TableCell>
      <TableCell>
        <Badge variant={finding.status === "OPEN" ? "destructive" : "default"}>
          {findingStatusLabel(finding.status, text)}
        </Badge>
      </TableCell>
      <TableCell className="font-mono">{finding.canonical_ip}</TableCell>
      <TableCell>
        <div>{formatDate(latestActivity ?? null, locale)}</div>
        {finding.latest_occurrence_run_id && (
          <div className="break-all font-mono text-xs text-muted-foreground">
            {text("最近发生的治理运行 ", "Last occurrence Run ")}{finding.latest_occurrence_run_id}
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
          {text("查看详情", "View details")}
        </LoadingButton>
      </TableCell>
    </TableRow>
  )
}

export default function Findings({ projectId }: { projectId: string }) {
  const { locale, text } = useLocale()
  const [status, setStatus] = useState<FindingStatus>("OPEN")
  const [page, setPage] = useState(0)
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(
    null,
  )
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
    if (page >= pageCount) setPage(pageCount - 1)
  }, [findingsQuery.data, page])

  if (findingsQuery.isPending) return <p role="status">{text("正在加载发现项…", "Loading Findings…")}</p>
  if (findingsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>{text("无法加载发现项", "Findings could not be loaded")}</AlertTitle>
        <AlertDescription>{text("请稍后重试。", "Please try again later.")}</AlertDescription>
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
              <CardTitle id="findings-title">{text("发现项", "Findings")}</CardTitle>
              <CardDescription>
                {text(
                  "最近一次兼容且已完成的治理运行生成的确定性 IP 发现项。开放发现项会持续显示，直到有正向匹配证据将其关闭。",
                  "Deterministic IP Findings from the latest compatible completed Run. OPEN Findings remain visible until positive matching evidence closes them.",
                )}
                {findings.latest_run_id && (
                  <span className="block break-all font-mono text-xs">
                    {text("已发布治理运行 ", "Published Run ")}{findings.latest_run_id}
                  </span>
                )}
              </CardDescription>
            </div>
            <div className="space-y-2">
              <label
                className="text-sm font-medium"
                htmlFor={`finding-status-${projectId}`}
              >
                {text("发现项状态", "Finding status")}
              </label>
              <Select
                value={status}
                onValueChange={(value) => {
                  setStatus(value as FindingStatus)
                  setPage(0)
                }}
              >
                <SelectTrigger
                  id={`finding-status-${projectId}`}
                  className="w-36"
                  aria-label={text("发现项状态", "Finding status")}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {FINDING_STATUSES.map((findingStatus) => (
                    <SelectItem key={findingStatus} value={findingStatus}>
                      {findingStatusLabel(findingStatus, text)}
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
              {text(`没有${status === "OPEN" ? "开放" : "已关闭"}发现项。`, `No ${status} Findings.`)}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{text("发现项 ID", "Finding ID")}</TableHead>
                  <TableHead>{text("类型", "Type")}</TableHead>
                  <TableHead>{text("状态", "Status")}</TableHead>
                  <TableHead>{text("规范 IP", "Canonical IP")}</TableHead>
                  <TableHead>{text("最近发生 / 变更", "Latest occurrence / transition")}</TableHead>
                  <TableHead>{text("发生记录", "Occurrences")}</TableHead>
                  <TableHead>{text("状态变更", "Transitions")}</TableHead>
                  <TableHead>{text("详情", "Details")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {findings.data.map((finding) => (
                  <FindingRow
                    key={finding.id}
                    finding={finding}
                    locale={locale}
                    text={text}
                    onDetails={() => setSelectedFindingId(finding.id)}
                  />
                ))}
              </TableBody>
            </Table>
          )}
          <ResultPagination
            label={text("发现项", "Findings")}
            count={findings.count}
            page={page}
            pageSize={PAGE_SIZE}
            onPageChange={setPage}
          />
        </CardContent>
      </Card>
      <FindingDetailDialog
        projectId={projectId}
        findingId={selectedFindingId}
        onOpenChange={(open) => {
          if (!open) setSelectedFindingId(null)
        }}
      />
    </section>
  )
}
