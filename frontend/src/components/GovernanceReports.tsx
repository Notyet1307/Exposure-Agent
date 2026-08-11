import { useQuery } from "@tanstack/react-query"
import { useState } from "react"

import {
  type GovernanceReportDetailPublic,
  type GovernanceReportSummaryPublic,
  GovernanceReportsService,
} from "@/client"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

const REPORT_PAGE_SIZE = 20
const HTML_EVIDENCE_LIMIT = 8

type JsonObject = Record<string, unknown>

function asObject(value: unknown): JsonObject | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonObject)
    : null
}

function objectField(value: JsonObject, key: string): JsonObject | null {
  return asObject(value[key])
}

function objectArray(value: JsonObject, key: string): JsonObject[] {
  const items = value[key]
  return Array.isArray(items)
    ? items.flatMap((item) => {
        const object = asObject(item)
        return object ? [object] : []
      })
    : []
}

function stringField(value: JsonObject, key: string, fallback = "—") {
  const field = value[key]
  return typeof field === "string" && field.length > 0 ? field : fallback
}

function numberField(value: JsonObject, key: string) {
  const field = value[key]
  return typeof field === "number" && Number.isFinite(field) ? field : 0
}

function formatDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function CountList({
  items,
  typeKey,
}: {
  items: JsonObject[]
  typeKey: "finding_type" | "transition_type"
}) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">No counts published.</p>
  }
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm">
      {items.map((item, index) => (
        <li key={`${stringField(item, typeKey)}-${index}`}>
          <span className="font-mono">{stringField(item, typeKey)}</span>:{" "}
          {numberField(item, "count")}
        </li>
      ))}
    </ul>
  )
}

function ReportSection({
  id,
  title,
  children,
}: {
  id: string
  title: string
  children: React.ReactNode
}) {
  return (
    <section id={id} className="scroll-mt-6 space-y-3 rounded-lg border p-4">
      <h2 className="text-lg font-semibold">{title}</h2>
      {children}
    </section>
  )
}

function InputCompleteness({ section }: { section: JsonObject }) {
  const sources = objectArray(section, "sources")
  return (
    <div className="space-y-3">
      <p className="text-sm">
        {section.complete === true
          ? "Both bounded input summaries are marked complete."
          : "The published report does not mark both inputs complete."}
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Source</TableHead>
            <TableHead>Snapshot reference</TableHead>
            <TableHead>Content SHA-256</TableHead>
            <TableHead>Schema</TableHead>
            <TableHead>Records</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sources.map((source, index) => (
            <TableRow key={`${stringField(source, "source_type")}-${index}`}>
              <TableCell>{stringField(source, "source_type")}</TableCell>
              <TableCell className="break-all font-mono text-xs">
                {stringField(source, "source_snapshot_id")}
              </TableCell>
              <TableCell className="break-all font-mono text-xs">
                {stringField(source, "content_sha256")}
              </TableCell>
              <TableCell className="break-all">
                {stringField(source, "schema_version")}
              </TableCell>
              <TableCell>{numberField(source, "record_count")}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function EvidenceCards({
  evidencePlan,
  evidenceCount,
}: {
  evidencePlan: JsonObject
  evidenceCount: number
}) {
  const allEntries = objectArray(evidencePlan, "entries")
  const entries = allEntries.slice(0, HTML_EVIDENCE_LIMIT)
  if (entries.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No Evidence examples were selected for this report.
      </p>
    )
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Showing {entries.length} of {evidenceCount} bounded Evidence reference
        {evidenceCount === 1 ? "" : "s"}. The HTML view never renders more than{" "}
        {HTML_EVIDENCE_LIMIT} cards.
      </p>
      <div className="grid gap-3 lg:grid-cols-2">
        {entries.map((entry, index) => {
          const reference = objectField(entry, "evidence_reference") ?? {}
          return (
            <article
              id={`report-evidence-${index + 1}`}
              data-testid="evidence-card"
              className="space-y-2 rounded-md border p-3 text-sm"
              key={`${stringField(entry, "finding_id")}-${index}`}
            >
              <h3 className="font-semibold">Evidence {index + 1}</h3>
              <dl className="grid gap-1">
                <div>
                  <dt className="inline font-medium">Coverage: </dt>
                  <dd className="inline">{stringField(entry, "coverage")}</dd>
                </div>
                <div>
                  <dt className="inline font-medium">Finding: </dt>
                  <dd className="inline break-all font-mono text-xs">
                    {stringField(entry, "finding_id")}
                  </dd>
                </div>
                <div>
                  <dt className="inline font-medium">Type / IP: </dt>
                  <dd className="inline break-all">
                    {stringField(entry, "finding_type")} /{" "}
                    <span className="font-mono">
                      {stringField(entry, "canonical_ip")}
                    </span>
                  </dd>
                </div>
                <div>
                  <dt className="inline font-medium">Transition: </dt>
                  <dd className="inline">
                    {stringField(entry, "transition_type", "None in this Run")}
                  </dd>
                </div>
                <div>
                  <dt className="inline font-medium">Source fact: </dt>
                  <dd className="inline break-all font-mono text-xs">
                    {stringField(reference, "fact_type")} /{" "}
                    {stringField(reference, "fact_id")}
                  </dd>
                </div>
              </dl>
              <p className="flex flex-wrap gap-3 text-sm">
                <a className="underline" href="#report-provenance">
                  Evidence provenance
                </a>
                <a className="underline" href="#report-open-backlog">
                  Finding context
                </a>
              </p>
            </article>
          )
        })}
      </div>
    </div>
  )
}

function PublishedReport({ detail }: { detail: GovernanceReportDetailPublic }) {
  const root = asObject(detail.canonical_content)
  const report = root ? objectField(root, "report") : null
  const evidencePlan = root ? objectField(root, "evidence_plan") : null
  const identity = report ? objectField(report, "report_identity") : null
  const completeness = report ? objectField(report, "input_completeness") : null
  const summary = report ? objectField(report, "ip_consistency_summary") : null
  const lifecycle = report
    ? objectField(report, "current_run_lifecycle_changes")
    : null
  const backlog = report ? objectField(report, "open_backlog_as_of_run") : null
  const evidenceBoundary = report
    ? objectField(report, "bounded_evidence_examples")
    : null
  const directions = report
    ? objectField(report, "finding_type_directions_and_limitations")
    : null
  const provenance = report ? objectField(report, "provenance") : null

  if (
    !identity ||
    !completeness ||
    !summary ||
    !lifecycle ||
    !backlog ||
    !evidenceBoundary ||
    !directions ||
    !provenance ||
    !evidencePlan
  ) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Published report content is not readable</AlertTitle>
        <AlertDescription>
          The fixed report contract is incomplete. No partial report is shown.
        </AlertDescription>
      </Alert>
    )
  }

  const isZeroFindingMatch =
    completeness.complete === true &&
    summary.all_observed_ip_identities_matched === true &&
    numberField(summary, "current_run_finding_count") === 0
  const presentDirections = objectArray(directions, "directions").filter(
    (direction) => direction.present === true,
  )
  const limitations = Array.isArray(directions.limitations)
    ? directions.limitations.filter(
        (limitation): limitation is string => typeof limitation === "string",
      )
    : []
  const sourceSnapshotIds = Array.isArray(provenance.source_snapshot_ids)
    ? provenance.source_snapshot_ids
    : []
  const sourceSnapshotHashes = Array.isArray(provenance.source_snapshot_hashes)
    ? provenance.source_snapshot_hashes
    : []
  const snapshotReferences = sourceSnapshotIds.flatMap((snapshotId, index) =>
    typeof snapshotId === "string"
      ? [
          {
            id: snapshotId,
            hash:
              typeof sourceSnapshotHashes[index] === "string"
                ? sourceSnapshotHashes[index]
                : "—",
          },
        ]
      : [],
  )

  return (
    <article className="space-y-4" aria-label="Immutable governance report">
      <ReportSection
        id="report-identity"
        title="Report identity and generation mode"
      >
        <dl className="grid gap-3 text-sm md:grid-cols-2">
          <div>
            <dt className="font-medium">Governance Run</dt>
            <dd className="break-all font-mono">
              {stringField(identity, "governance_run_id")}
            </dd>
          </div>
          <div>
            <dt className="font-medium">Run completed</dt>
            <dd>{formatDate(stringField(identity, "run_completed_at"))}</dd>
          </div>
          <div>
            <dt className="font-medium">Generation mode</dt>
            <dd>
              <Badge>{stringField(identity, "generation_mode")}</Badge>
            </dd>
          </div>
          <div>
            <dt className="font-medium">Report contract</dt>
            <dd className="break-all font-mono">
              {stringField(identity, "report_contract_version")}
            </dd>
          </div>
          <div>
            <dt className="font-medium">HTML Artifact SHA-256</dt>
            <dd className="break-all font-mono text-xs">
              {detail.html_sha256}
            </dd>
          </div>
          <div>
            <dt className="font-medium">CSV Artifact SHA-256</dt>
            <dd className="break-all font-mono text-xs">{detail.csv_sha256}</dd>
          </div>
        </dl>
      </ReportSection>

      <ReportSection id="report-input-completeness" title="Input completeness">
        <InputCompleteness section={completeness} />
      </ReportSection>

      <ReportSection id="report-ip-summary" title="IP consistency summary">
        <div className="space-y-3 text-sm">
          <p>
            Customer observed assets:{" "}
            {numberField(summary, "customer_observed_asset_count")} · CloudAtlas
            observed assets:{" "}
            {numberField(summary, "cloudatlas_observed_asset_count")} · Matched
            assets: {numberField(summary, "matched_asset_count")} · Current-Run
            Findings: {numberField(summary, "current_run_finding_count")}
          </p>
          {isZeroFindingMatch ? (
            <Alert>
              <AlertTitle>Complete-input IP match</AlertTitle>
              <AlertDescription>
                With both inputs complete, all observed IP identities matched;
                this Run produced zero Findings.
              </AlertDescription>
            </Alert>
          ) : (
            <p>The report identifies unmatched observed IP identities.</p>
          )}
          <CountList
            items={objectArray(summary, "finding_counts")}
            typeKey="finding_type"
          />
        </div>
      </ReportSection>

      <ReportSection
        id="report-lifecycle-changes"
        title="Current-Run lifecycle changes"
      >
        <p className="text-sm">
          Published transitions in this Run: {numberField(lifecycle, "total")}
        </p>
        <CountList
          items={objectArray(lifecycle, "transition_counts")}
          typeKey="transition_type"
        />
      </ReportSection>

      <ReportSection id="report-open-backlog" title="Open backlog as of Run">
        <p className="text-sm">
          OPEN Findings as of Run{" "}
          <span className="break-all font-mono">
            {stringField(backlog, "as_of_governance_run_id")}
          </span>
          : {numberField(backlog, "total")}
        </p>
        <CountList
          items={objectArray(backlog, "finding_counts")}
          typeKey="finding_type"
        />
      </ReportSection>

      <ReportSection id="report-evidence" title="Bounded Evidence examples">
        <p className="text-sm text-muted-foreground">
          Selection owner: {stringField(evidenceBoundary, "selection_owner")} ·
          published HTML maximum:{" "}
          {numberField(evidenceBoundary, "max_rendered_entries")}
        </p>
        <EvidenceCards
          evidencePlan={evidencePlan}
          evidenceCount={detail.evidence_count}
        />
      </ReportSection>

      <ReportSection
        id="report-directions-limitations"
        title="Finding-type directions and limitations"
      >
        {presentDirections.length > 0 ? (
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {presentDirections.map((direction, index) => (
              <li key={`${stringField(direction, "finding_type")}-${index}`}>
                <span className="font-mono">
                  {stringField(direction, "finding_type")}
                </span>
                : {stringField(direction, "direction")}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm">This report has no Finding to handle.</p>
        )}
        <h3 className="font-semibold">Limitations</h3>
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
      </ReportSection>

      <ReportSection id="report-provenance" title="Provenance">
        <dl className="grid gap-3 text-sm md:grid-cols-2">
          <div>
            <dt className="font-medium">Governance Run</dt>
            <dd className="break-all font-mono">
              {stringField(provenance, "governance_run_id")}
            </dd>
          </div>
          <div>
            <dt className="font-medium">Processing contract</dt>
            <dd className="break-all font-mono">
              {stringField(provenance, "processing_contract_version")}
            </dd>
          </div>
          <div>
            <dt className="font-medium">Finding lifecycle facts</dt>
            <dd>{numberField(provenance, "finding_lifecycle_fact_count")}</dd>
          </div>
        </dl>
        <ul className="space-y-2 text-sm">
          {snapshotReferences.map((snapshot, index) => (
            <li
              className="rounded-md border p-2"
              key={`${snapshot.id}-${index}`}
            >
              Snapshot reference{" "}
              <span className="break-all font-mono">{snapshot.id}</span>
              <span className="block break-all font-mono text-xs text-muted-foreground">
                SHA-256 {snapshot.hash}
              </span>
            </li>
          ))}
        </ul>
      </ReportSection>
    </article>
  )
}

function ReportDetailDialog({
  projectId,
  reportId,
  onOpenChange,
}: {
  projectId: string
  reportId: string | null
  onOpenChange: (open: boolean) => void
}) {
  const detailQuery = useQuery({
    queryKey: ["governance-report", projectId, reportId],
    queryFn: () =>
      GovernanceReportsService.readGovernanceReport({
        projectId,
        reportId: reportId as string,
      }),
    enabled: reportId !== null,
  })

  return (
    <Dialog open={reportId !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-[calc(100%-2rem)] overflow-y-auto sm:max-w-6xl">
        <DialogHeader>
          <DialogTitle>Published deterministic report</DialogTitle>
          <DialogDescription>
            This immutable view renders only bounded canonical report content;
            it does not load CSV or raw source payloads.
          </DialogDescription>
        </DialogHeader>
        {detailQuery.isPending && <p role="status">Loading report…</p>}
        {detailQuery.isError && (
          <Alert variant="destructive">
            <AlertTitle>Report could not be loaded</AlertTitle>
            <AlertDescription>Please try again later.</AlertDescription>
          </Alert>
        )}
        {detailQuery.data && <PublishedReport detail={detailQuery.data} />}
      </DialogContent>
    </Dialog>
  )
}

function ReportRow({
  report,
  onRead,
}: {
  report: GovernanceReportSummaryPublic
  onRead: () => void
}) {
  return (
    <TableRow>
      <TableCell className="break-all font-mono text-xs">
        {report.governance_run_id}
      </TableCell>
      <TableCell>{formatDate(report.run_completed_at)}</TableCell>
      <TableCell>
        <Badge>{report.generation_mode}</Badge>
      </TableCell>
      <TableCell className="break-all font-mono text-xs">
        {report.report_contract_version}
      </TableCell>
      <TableCell className="max-w-72 break-all font-mono text-xs">
        {report.html_sha256}
      </TableCell>
      <TableCell>
        <Button type="button" variant="outline" size="sm" onClick={onRead}>
          Read report
        </Button>
      </TableCell>
    </TableRow>
  )
}

export default function GovernanceReports({
  projectId,
}: {
  projectId: string
}) {
  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>([
    null,
  ])
  const [pageIndex, setPageIndex] = useState(0)
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null)
  const cursor = cursorHistory[pageIndex] ?? null
  const reportsQuery = useQuery({
    queryKey: ["governance-reports", projectId, cursor],
    queryFn: () =>
      GovernanceReportsService.readGovernanceReports({
        projectId,
        limit: REPORT_PAGE_SIZE,
        cursor,
      }),
    staleTime: Number.POSITIVE_INFINITY,
  })

  if (reportsQuery.isPending) return <p role="status">Loading Reports…</p>
  if (reportsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Reports could not be loaded</AlertTitle>
        <AlertDescription>Please try again later.</AlertDescription>
      </Alert>
    )
  }

  const reports = reportsQuery.data
  return (
    <section className="space-y-4" aria-labelledby="reports-title">
      <Card>
        <CardHeader>
          <CardTitle id="reports-title">Reports</CardTitle>
          <CardDescription>
            Published immutable deterministic reports for this Project ·{" "}
            {reports.count} total
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {reports.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No published reports are available.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Governance Run</TableHead>
                  <TableHead>Completed</TableHead>
                  <TableHead>Generation mode</TableHead>
                  <TableHead>Report contract</TableHead>
                  <TableHead>HTML Artifact SHA-256</TableHead>
                  <TableHead>Report</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {reports.data.map((report) => (
                  <ReportRow
                    key={report.id}
                    report={report}
                    onRead={() => setSelectedReportId(report.id)}
                  />
                ))}
              </TableBody>
            </Table>
          )}
          {(pageIndex > 0 || reports.next_cursor !== null) && (
            <nav
              className="flex items-center justify-end gap-3"
              aria-label="Reports pagination"
            >
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={pageIndex === 0}
                onClick={() => setPageIndex((current) => current - 1)}
              >
                Previous
              </Button>
              <span className="text-sm text-muted-foreground">
                Page {pageIndex + 1}
              </span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={reports.next_cursor === null}
                onClick={() => {
                  if (reports.next_cursor === null) return
                  setCursorHistory((history) => [
                    ...history.slice(0, pageIndex + 1),
                    reports.next_cursor,
                  ])
                  setPageIndex((current) => current + 1)
                }}
              >
                Next
              </Button>
            </nav>
          )}
        </CardContent>
      </Card>
      <ReportDetailDialog
        projectId={projectId}
        reportId={selectedReportId}
        onOpenChange={(open) => {
          if (!open) setSelectedReportId(null)
        }}
      />
    </section>
  )
}
