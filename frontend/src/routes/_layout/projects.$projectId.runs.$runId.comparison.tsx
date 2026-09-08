import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { useEffect } from "react"

import { ApiError, IpResultsService } from "@/client"
import { ResultPagination } from "@/components/ResultPagination"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useLocale } from "@/components/LocaleProvider"
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
  const { text } = useLocale()
  useEffect(() => { document.title = text("三来源比较 - Exposure-Agent", "Run source comparison - Exposure Agent") })
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
          {text("返回工作台", "Back to dashboard")}
        </Link>
        <h1 className="text-2xl font-bold tracking-tight">
          {text("运行来源比较", "Run source comparison")}
        </h1>
        <p className="break-all text-sm">{text("运行 ID", "Run ID")}: {runId}</p>
        <p className="break-all text-sm text-muted-foreground">
          {text("项目 ID", "Project ID")}: {projectId}
        </p>
        {ready && (
          <>
            <p className="break-all text-sm">
              {text("报告 ID", "Report ID")}: {sources.governance_report_id}
            </p>
            <Link
              to="/projects/$projectId/runs/$runId/lineage"
              params={{ projectId, runId }}
              className="inline-block text-sm underline underline-offset-4"
            >
              {text("血缘", "Lineage")}
            </Link>
            <p className="break-all text-sm text-muted-foreground">
              {sources.run_status}{text(" · 完成于 ", " · Completed ")}{sources.completed_at} ·{" "}
              {sources.report_contract_version}
            </p>
          </>
        )}
        <p className="text-sm text-muted-foreground">
          {text("此处仅显示指定历史运行的已发布事实，不会替换为最新运行或当前输入。", "Published facts for this explicit historical Run, not the latest Run or current inputs.")}
        </p>
      </header>

      {error || identityMismatch ? (
        <Alert variant="destructive">
          <AlertTitle className="line-clamp-none">
            {identityMismatch
              ? text("运行比较结果的身份不匹配", "Run comparison identity mismatch")
              : unavailable
                ? text("运行比较结果不可用或不兼容", "Run comparison unavailable or incompatible")
                : text("运行比较请求失败", "Run comparison request failed")}
          </AlertTitle>
          <AlertDescription>
            <p>
              {identityMismatch
                ? text("响应未对应请求的运行及同一报告版本，因此不展示来源或比较事实。", "The responses do not identify the requested Run and the same Report version. No source or comparison facts are displayed.")
                : unavailable
                  ? text("指定运行不可用或不兼容来源比较，系统未替换为其他运行。", "This explicit Run is unavailable or incompatible with source comparison. No other Run has been substituted.")
                  : text("已发布事实加载失败，请重试。", "The published facts could not be loaded. Please try again.")}
            </p>
            <p>{text("请求失败不表示来源未提供（ABSENT），也不表示 IP 的活动状态未知（UNKNOWN）。", "A failed request does not mean a source is ABSENT or an IP has UNKNOWN status.")}</p>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                void sourcesQuery.refetch()
                void comparisonQuery.refetch()
              }}
            >{text("重试", "Try again")}</Button>
          </AlertDescription>
        </Alert>
      ) : !ready ? (
        <p role="status">{text("正在加载运行来源比较…", "Loading Run source comparison…")}</p>
      ) : null}

      <section aria-label={text("来源概览", "Source overview")} className="min-w-0 space-y-3">
        <h2 className="text-xl font-semibold">{text("来源概览", "Source overview")}</h2>
        <p className="text-sm text-muted-foreground">{text("已提供（PRESENT）表示已发布来源快照，包括原始记录数为 0 的快照；未提供（ABSENT）表示本次运行没有该来源快照，而不是请求失败。原始记录数不等于正向活动数量或流量。", "PRESENT means a source snapshot was published, including a snapshot with 0 raw records. ABSENT means no snapshot was published for this source in this Run; it is not a request failure. Raw record counts do not measure positive activity or traffic volume.")}</p>
        {ready && (
          <div className="grid min-w-0 gap-4 lg:grid-cols-3">
            {sources.sources.map((source) => (
              <Card
                key={source.source_type}
                role="region"
                aria-label={source.source_type === "CUSTOMER_UPLOAD" ? text("客户资产表", SOURCE_NAMES[source.source_type]) : SOURCE_NAMES[source.source_type]}
                className="min-w-0"
              >
                <CardHeader>
                  <CardTitle>
                    <h3>{source.source_type === "CUSTOMER_UPLOAD" ? text("客户资产表", SOURCE_NAMES[source.source_type]) : SOURCE_NAMES[source.source_type]}</h3>
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
                      <dt>{text("原始记录数", "Raw records")}</dt>
                      <dd>{source.record_count ?? text("不可用", "Not available")}</dd>
                    </div>
                    <div>
                      <dt>{text("快照 ID", "Snapshot ID")}</dt>
                      <dd>{source.snapshot_id ?? text("不可用", "Not available")}</dd>
                    </div>
                    <div>
                      <dt>{text("输入 ID", "Input ID")}</dt>
                      <dd>{source.input_id ?? text("不可用", "Not available")}</dd>
                    </div>
                    <div>
                      <dt>{text("有效时间起点（UTC）", "Valid time start (UTC)")}</dt>
                      <dd>{source.valid_time_start_utc ?? text("不可用", "Not available")}</dd>
                    </div>
                    <div>
                      <dt>{text("有效时间终点（UTC）", "Valid time end (UTC)")}</dt>
                      <dd>{source.valid_time_end_utc ?? text("不可用", "Not available")}</dd>
                    </div>
                  </dl>
                  <details>
                    <summary className="cursor-pointer">{text("哈希与指纹", "Hashes and fingerprints")}</summary>
                    <dl className="mt-2 space-y-2 [&_dd]:break-all [&_dd]:font-mono [&_dd]:text-xs [&_dt]:font-medium">
                      <div>
                        <dt>{text("内容 SHA-256", "Content SHA-256")}</dt>
                        <dd>{source.content_sha256 ?? text("不可用", "Not available")}</dd>
                      </div>
                      <div>
                        <dt>{text("模式指纹", "Schema fingerprint")}</dt>
                        <dd>{source.schema_fingerprint ?? text("不可用", "Not available")}</dd>
                      </div>
                      <div>
                        <dt>{text("方法指纹", "Method fingerprint")}</dt>
                        <dd>{source.method_fingerprint ?? text("不可用", "Not available")}</dd>
                      </div>
                    </dl>
                  </details>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </section>

      <section aria-label={text("IP 来源比较", "IP source comparison")} className="min-w-0 space-y-4">
        <h2 className="text-xl font-semibold">{text("IP 来源比较", "IP source comparison")}</h2>
        <p className="text-sm text-muted-foreground">{text("已观测与未观测描述客户资产表及 CloudAtlas 快照中的证据。NetFlow 有活动（ACTIVE）表示观测到正向活动；未知（UNKNOWN）表示没有正向活动证据，不代表 IP 不存在、零流量或零风险。", "Observed / Not observed describes evidence in the CustomerUpload and CloudAtlas snapshots. NetFlow ACTIVE means positive activity was observed. UNKNOWN means no positive activity evidence; it does not mean the IP is nonexistent, has zero traffic, or has zero risk.")}</p>
        <div className="flex flex-wrap gap-3">
          <label className="grid min-w-0 max-w-full gap-1 text-sm">
            {text("分类", "Classification")}
            <select
              aria-label={text("分类", "Classification")}
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
              <option value="">{text("全部分类", "All classifications")}</option>
              {CLASSIFICATIONS.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label className="grid min-w-0 max-w-full gap-1 text-sm">{text("NetFlow 状态", "NetFlow status")}<select
              aria-label={text("NetFlow 状态", "NetFlow status")}
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
              <option value="">{text("全部 NetFlow 状态", "All NetFlow statuses")}</option>
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
              <p role="status" className="text-sm text-muted-foreground">{text("本次运行中暂无符合筛选条件的 IP 来源比较结果；这不代表零流量或零风险。", "No IP source comparisons match this Run and filters. This does not establish zero traffic or zero risk.")}</p>
            ) : (
              <section
                aria-label={text("IP 来源比较表", "IP source comparison table")}
                // biome-ignore lint/a11y/noNoninteractiveTabindex: Keyboard users must be able to scroll the matrix horizontally.
                tabIndex={0}
                className="max-w-full overflow-x-auto rounded-lg focus-visible:outline-2 focus-visible:outline-ring [&>[data-slot=table-container]]:overflow-visible"
              >
                <Table className="min-w-[700px]">
                  <TableHeader>
                    <TableRow>
                      <TableHead scope="col">{text("规范化 IP", "Canonical IP")}</TableHead>
                      <TableHead scope="col">{text("客户资产表", "CustomerUpload")}</TableHead>
                      <TableHead scope="col">CloudAtlas</TableHead>
                      <TableHead scope="col">NetFlow</TableHead>
                      <TableHead scope="col">{text("分类", "Classification")}</TableHead>
                      <TableHead scope="col">{text("血缘追溯", "Lineage")}</TableHead>
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
                            ? text("已观测", "Observed")
                            : text("未观测", "Not observed")}
                        </TableCell>
                        <TableCell>
                          {row.cloudatlas_present ? text("已观测", "Observed") : text("未观测", "Not observed")}
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
                          >{text("追溯资产", "Trace asset")}</Link>
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
