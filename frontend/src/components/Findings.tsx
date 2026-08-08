import { useQuery } from "@tanstack/react-query"
import { useEffect, useState } from "react"

import {
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

const PAGE_SIZE = 25
const TRACE_PAGE_SIZE = 20
const FINDING_STATUSES = ["OPEN", "CLOSED"] as const
type FindingStatus = (typeof FINDING_STATUSES)[number]

function findingLabel(findingType: string) {
  if (findingType === "UNREPORTED_ASSET") return "Unreported asset"
  if (findingType === "UNOBSERVED_ASSET") return "Unobserved asset"
  return findingType
}

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString() : "—"
}

function ObservationTable({
  observations,
}: {
  observations: IPObservationPublic[] | undefined
}) {
  if (!observations || observations.length === 0) {
    return <p className="text-sm text-muted-foreground">No observations.</p>
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Raw IP</TableHead>
          <TableHead>Canonical IP</TableHead>
          <TableHead>Source</TableHead>
          <TableHead>Location</TableHead>
          <TableHead>CloudAtlas ID</TableHead>
          <TableHead>CloudAtlas status</TableHead>
          <TableHead>Snapshot</TableHead>
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
}: {
  snapshotIds: string[] | undefined
  snapshots: SourceSnapshotPublic[] | undefined
}) {
  const references = snapshots ?? []
  if (references.length === 0 && (!snapshotIds || snapshotIds.length === 0)) {
    return (
      <p className="text-sm text-muted-foreground">No Snapshot references.</p>
    )
  }
  return (
    <div className="space-y-2">
      {references.map((snapshot) => (
        <div key={snapshot.id} className="rounded-md border p-2 text-xs">
          <div className="font-medium">{snapshot.source_type}</div>
          <div className="break-all font-mono">Snapshot {snapshot.id}</div>
          <div>
            {snapshot.record_count} records · SHA-256 {snapshot.content_sha256}
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
            Snapshot {snapshotId}
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
  return (
    <div className="space-y-3 rounded-md border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium">{title}</h3>
        <span className="text-xs text-muted-foreground">
          Run {trace.governance_run_id} · {formatDate(trace.created_at)}
        </span>
      </div>
      <ObservationTable observations={trace.observations} />
      <div>
        <p className="mb-2 text-sm font-medium">
          Confirmed Snapshot references
        </p>
        <SnapshotReferences
          snapshotIds={trace.source_snapshot_ids}
          snapshots={trace.source_snapshots}
        />
      </div>
    </div>
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
  const [occurrencePage, setOccurrencePage] = useState(0)
  const [transitionPage, setTransitionPage] = useState(0)
  useEffect(() => {
    if (findingId === null) return
    setOccurrencePage(0)
    setTransitionPage(0)
  }, [findingId])
  const detailQuery = useQuery({
    queryKey: ["finding", projectId, findingId, occurrencePage, transitionPage],
    queryFn: () =>
      IpResultsService.readFinding({
        projectId,
        findingId: findingId as string,
        occurrenceSkip: occurrencePage * TRACE_PAGE_SIZE,
        transitionSkip: transitionPage * TRACE_PAGE_SIZE,
        traceLimit: TRACE_PAGE_SIZE,
      }),
    enabled: findingId !== null,
  })

  return (
    <Dialog
      open={findingId !== null}
      onOpenChange={(open) => onOpenChange(open)}
    >
      <DialogContent className="max-h-[90vh] max-w-[calc(100%-2rem)] overflow-y-auto sm:max-w-6xl">
        <DialogHeader>
          <DialogTitle>Finding details</DialogTitle>
          <DialogDescription>
            Occurrences, lifecycle transitions, source observations, and
            confirmed Snapshot references are bounded by the server.
          </DialogDescription>
        </DialogHeader>
        {detailQuery.isPending && <p role="status">Loading Finding details…</p>}
        {detailQuery.isError && (
          <Alert variant="destructive">
            <AlertTitle>Finding details could not be loaded</AlertTitle>
            <AlertDescription>Please try again later.</AlertDescription>
          </Alert>
        )}
        {detailQuery.data && (
          <div className="space-y-4">
            <div className="grid gap-3 text-sm md:grid-cols-4">
              <div>
                <p className="font-medium">Finding ID</p>
                <p className="break-all font-mono text-xs">
                  {detailQuery.data.id}
                </p>
              </div>
              <div>
                <p className="font-medium">Canonical IP</p>
                <p className="font-mono">{detailQuery.data.canonical_ip}</p>
              </div>
              <div>
                <p className="font-medium">Status</p>
                <Badge>{detailQuery.data.status}</Badge>
              </div>
              <div>
                <p className="font-medium">Last occurrence</p>
                <p>{formatDate(detailQuery.data.latest_occurrence_at)}</p>
                {detailQuery.data.latest_occurrence_run_id && (
                  <p className="break-all font-mono text-xs text-muted-foreground">
                    Run {detailQuery.data.latest_occurrence_run_id}
                  </p>
                )}
              </div>
            </div>
            <div>
              <p className="mb-2 text-sm font-medium">Occurrences</p>
              {(detailQuery.data.occurrences ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No Finding Occurrences.
                </p>
              ) : (
                <div className="space-y-3">
                  {(detailQuery.data.occurrences ?? []).map((occurrence) => (
                    <TraceSection
                      key={occurrence.id}
                      title="Occurrence"
                      trace={occurrence}
                    />
                  ))}
                  <ResultPagination
                    label="Finding occurrences"
                    count={detailQuery.data.occurrence_count}
                    page={occurrencePage}
                    pageSize={TRACE_PAGE_SIZE}
                    onPageChange={setOccurrencePage}
                  />
                </div>
              )}
            </div>
            <div>
              <p className="mb-2 text-sm font-medium">Transitions</p>
              {(detailQuery.data.transitions ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No Finding Transitions.
                </p>
              ) : (
                <div className="space-y-3">
                  {(detailQuery.data.transitions ?? []).map((transition) => (
                    <TraceSection
                      key={transition.id}
                      title={`Transition · ${transition.transition_type}`}
                      trace={transition}
                    />
                  ))}
                  <ResultPagination
                    label="Finding transitions"
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
}: {
  finding: FindingPublic
  onDetails: () => void
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
        <div>{findingLabel(finding.finding_type)}</div>
        <div className="font-mono text-xs text-muted-foreground">
          {finding.finding_type}
        </div>
      </TableCell>
      <TableCell>
        <Badge variant={finding.status === "OPEN" ? "destructive" : "default"}>
          {finding.status}
        </Badge>
      </TableCell>
      <TableCell className="font-mono">{finding.canonical_ip}</TableCell>
      <TableCell>
        <div>{formatDate(latestActivity ?? null)}</div>
        {finding.latest_occurrence_run_id && (
          <div className="break-all font-mono text-xs text-muted-foreground">
            Last occurrence Run {finding.latest_occurrence_run_id}
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
          View details
        </LoadingButton>
      </TableCell>
    </TableRow>
  )
}

export default function Findings({ projectId }: { projectId: string }) {
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

  if (findingsQuery.isPending) return <p role="status">Loading Findings…</p>
  if (findingsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Findings could not be loaded</AlertTitle>
        <AlertDescription>Please try again later.</AlertDescription>
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
              <CardTitle id="findings-title">Findings</CardTitle>
              <CardDescription>
                Deterministic IP Findings from the latest compatible completed
                Run. OPEN Findings remain visible until positive matching
                evidence closes them.
                {findings.latest_run_id && (
                  <span className="block break-all font-mono text-xs">
                    Published Run {findings.latest_run_id}
                  </span>
                )}
              </CardDescription>
            </div>
            <div className="space-y-2">
              <label
                className="text-sm font-medium"
                htmlFor={`finding-status-${projectId}`}
              >
                Finding status
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
                  aria-label="Finding status"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {FINDING_STATUSES.map((findingStatus) => (
                    <SelectItem key={findingStatus} value={findingStatus}>
                      {findingStatus}
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
              No {status} Findings.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Finding ID</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Canonical IP</TableHead>
                  <TableHead>Latest occurrence / transition</TableHead>
                  <TableHead>Occurrences</TableHead>
                  <TableHead>Transitions</TableHead>
                  <TableHead>Details</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {findings.data.map((finding) => (
                  <FindingRow
                    key={finding.id}
                    finding={finding}
                    onDetails={() => setSelectedFindingId(finding.id)}
                  />
                ))}
              </TableBody>
            </Table>
          )}
          <ResultPagination
            label="Findings"
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
