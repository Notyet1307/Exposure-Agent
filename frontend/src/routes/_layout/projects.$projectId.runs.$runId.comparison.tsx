import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { useEffect } from "react"

import { ApiError, IpResultsService } from "@/client"
import { ResultPagination } from "@/components/ResultPagination"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

const PAGE_SIZE = 25
const CLASSIFICATIONS = [
  "matched",
  "customer_upload_only",
  "cloudatlas_only",
  "neither_source_observed",
] as const
const NETFLOW_STATUSES = ["ACTIVE", "UNKNOWN"] as const
const SOURCE_NAMES = {
  CUSTOMER_UPLOAD: "CustomerUpload",
  CLOUDATLAS: "CloudAtlas",
  NETFLOW: "NetFlow",
}

type ComparisonSearch = {
  classification?: (typeof CLASSIFICATIONS)[number]
  netflow_status?: (typeof NETFLOW_STATUSES)[number]
  page?: number
}

export const Route = createFileRoute(
  "/_layout/projects/$projectId/runs/$runId/comparison",
)({
  component: RunSourceComparison,
  validateSearch: (search: Record<string, unknown>): ComparisonSearch => {
    const page =
      typeof search.page === "number" || typeof search.page === "string"
        ? Number(search.page)
        : Number.NaN
    return {
      classification: CLASSIFICATIONS.find(
        (value) => value === search.classification,
      ),
      netflow_status: NETFLOW_STATUSES.find(
        (value) => value === search.netflow_status,
      ),
      page:
        Number.isSafeInteger(page) &&
        page > 1 &&
        page <= Math.floor(Number.MAX_SAFE_INTEGER / PAGE_SIZE)
          ? page
          : undefined,
    }
  },
  head: () => ({
    meta: [{ title: "Run source comparison - Exposure Agent" }],
  }),
})

function RunSourceComparison() {
  const { projectId, runId } = Route.useParams()
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  const page = search.page ?? 1
  const sourcesQuery = useQuery({
    queryKey: ["governance-run-sources", projectId, runId],
    queryFn: () =>
      IpResultsService.readGovernanceRunSources({
        projectId,
        governanceRunId: runId,
      }),
    retry: false,
  })
  const comparisonQuery = useQuery({
    queryKey: [
      "governance-run-ip-source-comparisons",
      projectId,
      runId,
      search.classification,
      search.netflow_status,
      page,
    ],
    queryFn: () =>
      IpResultsService.readGovernanceRunIpSourceComparisons({
        projectId,
        governanceRunId: runId,
        classification: search.classification,
        netflowStatus: search.netflow_status,
        skip: (page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
    retry: false,
  })
  const sources = sourcesQuery.data
  const comparison = comparisonQuery.data
  const identityMismatch =
    (sources &&
      (sources.project_id !== projectId ||
        sources.governance_run_id !== runId)) ||
    (comparison &&
      (comparison.project_id !== projectId ||
        comparison.governance_run_id !== runId)) ||
    (sources &&
      comparison &&
      (sources.governance_report_id !== comparison.governance_report_id ||
        sources.report_contract_version !== comparison.report_contract_version))
  const error = sourcesQuery.error ?? comparisonQuery.error
  const ready = sources && comparison && !error && !identityMismatch
  const unavailable =
    (sourcesQuery.error instanceof ApiError &&
      sourcesQuery.error.status === 404) ||
    (comparisonQuery.error instanceof ApiError &&
      comparisonQuery.error.status === 404)

  useEffect(() => {
    if (!ready) return
    const pageCount = Math.max(1, Math.ceil(comparison.count / PAGE_SIZE))
    if (page > pageCount) {
      void navigate({
        search: (previous) => ({
          ...previous,
          page: pageCount === 1 ? undefined : pageCount,
        }),
        replace: true,
      })
    }
  }, [comparison, navigate, page, ready])

  return (
    <div className="min-w-0 max-w-full space-y-6 overflow-hidden">
      <header className="space-y-2">
        <Link to="/" className="text-sm underline underline-offset-4">
          Back to dashboard
        </Link>
        <h1 className="text-2xl font-bold tracking-tight">
          Run source comparison
        </h1>
        <p className="break-all text-sm">Run ID: {runId}</p>
        <p className="break-all text-sm text-muted-foreground">
          Project ID: {projectId}
        </p>
        {ready && (
          <>
            <p className="break-all text-sm">
              Report ID: {sources.governance_report_id}
            </p>
            <Link
              to="/projects/$projectId/runs/$runId/lineage"
              params={{ projectId, runId }}
              className="inline-block text-sm underline underline-offset-4"
            >
              Lineage
            </Link>
            <p className="break-all text-sm text-muted-foreground">
              {sources.run_status} · Completed {sources.completed_at} ·{" "}
              {sources.report_contract_version}
            </p>
          </>
        )}
        <p className="text-sm text-muted-foreground">
          Published facts for this explicit historical Run, not the latest Run
          or current inputs.
        </p>
      </header>

      {error || identityMismatch ? (
        <Alert variant="destructive">
          <AlertTitle className="line-clamp-none">
            {identityMismatch
              ? "Run comparison identity mismatch"
              : unavailable
                ? "Run comparison unavailable or incompatible"
                : "Run comparison request failed"}
          </AlertTitle>
          <AlertDescription>
            <p>
              {identityMismatch
                ? "The responses do not identify the requested Run and the same Report version. No source or comparison facts are displayed."
                : unavailable
                  ? "This explicit Run is unavailable or incompatible with source comparison. No other Run has been substituted."
                  : "The published facts could not be loaded. Please try again."}
            </p>
            <p>
              A failed request does not mean a source is ABSENT or an IP has
              UNKNOWN status.
            </p>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                void sourcesQuery.refetch()
                void comparisonQuery.refetch()
              }}
            >
              Try again
            </Button>
          </AlertDescription>
        </Alert>
      ) : !ready ? (
        <p role="status">Loading Run source comparison…</p>
      ) : null}

      <section aria-label="Source overview" className="min-w-0 space-y-3">
        <h2 className="text-xl font-semibold">Source overview</h2>
        <p className="text-sm text-muted-foreground">
          PRESENT means a source snapshot was published, including a snapshot
          with 0 raw records. ABSENT means no snapshot was published for this
          source in this Run; it is not a request failure. Raw record counts do
          not measure positive activity or traffic volume.
        </p>
        {ready && (
          <div className="grid min-w-0 gap-4 lg:grid-cols-3">
            {sources.sources.map((source) => (
              <Card
                key={source.source_type}
                role="region"
                aria-label={SOURCE_NAMES[source.source_type]}
                className="min-w-0"
              >
                <CardHeader>
                  <CardTitle>
                    <h3>{SOURCE_NAMES[source.source_type]}</h3>
                  </CardTitle>
                  <Badge
                    variant={
                      source.state === "PRESENT" ? "default" : "secondary"
                    }
                  >
                    {source.state}
                  </Badge>
                </CardHeader>
                <CardContent className="space-y-3 text-sm">
                  <dl className="space-y-2 [&_dd]:break-all [&_dt]:font-medium">
                    <div>
                      <dt>Raw records</dt>
                      <dd>{source.record_count ?? "Not available"}</dd>
                    </div>
                    <div>
                      <dt>Snapshot ID</dt>
                      <dd>{source.snapshot_id ?? "Not available"}</dd>
                    </div>
                    <div>
                      <dt>Input ID</dt>
                      <dd>{source.input_id ?? "Not available"}</dd>
                    </div>
                    <div>
                      <dt>Valid time start (UTC)</dt>
                      <dd>{source.valid_time_start_utc ?? "Not available"}</dd>
                    </div>
                    <div>
                      <dt>Valid time end (UTC)</dt>
                      <dd>{source.valid_time_end_utc ?? "Not available"}</dd>
                    </div>
                  </dl>
                  <details>
                    <summary className="cursor-pointer">
                      Hashes and fingerprints
                    </summary>
                    <dl className="mt-2 space-y-2 [&_dd]:break-all [&_dd]:font-mono [&_dd]:text-xs [&_dt]:font-medium">
                      <div>
                        <dt>Content SHA-256</dt>
                        <dd>{source.content_sha256 ?? "Not available"}</dd>
                      </div>
                      <div>
                        <dt>Schema fingerprint</dt>
                        <dd>{source.schema_fingerprint ?? "Not available"}</dd>
                      </div>
                      <div>
                        <dt>Method fingerprint</dt>
                        <dd>{source.method_fingerprint ?? "Not available"}</dd>
                      </div>
                    </dl>
                  </details>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </section>

      <section aria-label="IP source comparison" className="min-w-0 space-y-4">
        <h2 className="text-xl font-semibold">IP source comparison</h2>
        <p className="text-sm text-muted-foreground">
          Observed / Not observed describes evidence in the CustomerUpload and
          CloudAtlas snapshots. NetFlow ACTIVE means positive activity was
          observed. UNKNOWN means no positive activity evidence; it does not
          mean the IP is nonexistent, has zero traffic, or has zero risk.
        </p>
        <div className="flex flex-wrap gap-3">
          <label className="grid min-w-0 max-w-full gap-1 text-sm">
            Classification
            <select
              aria-label="Classification"
              className="h-9 min-w-0 max-w-full rounded-md border bg-background px-3"
              value={search.classification ?? ""}
              onChange={(event) => {
                const classification = CLASSIFICATIONS.find(
                  (value) => value === event.target.value,
                )
                void navigate({
                  search: { ...search, classification, page: undefined },
                })
              }}
            >
              <option value="">All classifications</option>
              {CLASSIFICATIONS.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label className="grid min-w-0 max-w-full gap-1 text-sm">
            NetFlow status
            <select
              aria-label="NetFlow status"
              className="h-9 min-w-0 max-w-full rounded-md border bg-background px-3"
              value={search.netflow_status ?? ""}
              onChange={(event) => {
                const netflow_status = NETFLOW_STATUSES.find(
                  (value) => value === event.target.value,
                )
                void navigate({
                  search: { ...search, netflow_status, page: undefined },
                })
              }}
            >
              <option value="">All NetFlow statuses</option>
              {NETFLOW_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
        </div>
        {ready && (
          <>
            {comparison.data.length === 0 ? (
              <p role="status" className="text-sm text-muted-foreground">
                No IP source comparisons match this Run and filters. This does
                not establish zero traffic or zero risk.
              </p>
            ) : (
              <section
                aria-label="IP source comparison table"
                // biome-ignore lint/a11y/noNoninteractiveTabindex: Keyboard users must be able to scroll the matrix horizontally.
                tabIndex={0}
                className="max-w-full overflow-x-auto rounded-lg focus-visible:outline-2 focus-visible:outline-ring [&>[data-slot=table-container]]:overflow-visible"
              >
                <Table className="min-w-[700px]">
                  <TableHeader>
                    <TableRow>
                      <TableHead scope="col">Canonical IP</TableHead>
                      <TableHead scope="col">CustomerUpload</TableHead>
                      <TableHead scope="col">CloudAtlas</TableHead>
                      <TableHead scope="col">NetFlow</TableHead>
                      <TableHead scope="col">Classification</TableHead>
                      <TableHead scope="col">Lineage</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {comparison.data.map((row) => (
                      <TableRow key={row.resource_id}>
                        <TableCell className="font-mono">
                          {row.canonical_ip}
                        </TableCell>
                        <TableCell>
                          {row.customer_upload_present
                            ? "Observed"
                            : "Not observed"}
                        </TableCell>
                        <TableCell>
                          {row.cloudatlas_present ? "Observed" : "Not observed"}
                        </TableCell>
                        <TableCell>
                          {row.netflow_status}
                          <p className="max-w-64 whitespace-normal text-xs text-muted-foreground">
                            {row.netflow_reason}
                          </p>
                        </TableCell>
                        <TableCell>{row.classification}</TableCell>
                        <TableCell>
                          <Link
                            to="/projects/$projectId/runs/$runId/lineage"
                            params={{ projectId, runId }}
                            search={{ resource_id: row.resource_id }}
                            aria-label={`Trace asset ${row.canonical_ip}`}
                            className="underline underline-offset-4"
                          >
                            Trace asset
                          </Link>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </section>
            )}
            <ResultPagination
              label="Comparison"
              page={page - 1}
              count={comparison.count}
              pageSize={PAGE_SIZE}
              onPageChange={(nextPage) => {
                void navigate({
                  search: {
                    ...search,
                    page: nextPage === 0 ? undefined : nextPage + 1,
                  },
                })
              }}
            />
          </>
        )}
      </section>
    </div>
  )
}
