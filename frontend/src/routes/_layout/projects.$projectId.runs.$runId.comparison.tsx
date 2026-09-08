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
import { useI18n } from "@/lib/i18n"

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
  const { t, formatDate, translateValue } = useI18n()
  useEffect(() => {
    document.title = t(
      "Run source comparison - Exposure Agent",
      "运行来源比较 - Exposure Agent",
    )
  }, [t])
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
          {t("Back to dashboard", "返回仪表盘")}
        </Link>
        <h1 className="text-2xl font-bold tracking-tight">
          {t("Run source comparison", "运行来源比较")}
        </h1>
        <p className="break-all text-sm">
          {t("Run ID", "运行 ID")}: {runId}
        </p>
        <p className="break-all text-sm text-muted-foreground">
          {t("Project ID", "项目 ID")}: {projectId}
        </p>
        {ready && (
          <>
            <p className="break-all text-sm">
              {t("Report ID", "报告 ID")}: {sources.governance_report_id}
            </p>
            <Link
              to="/projects/$projectId/runs/$runId/lineage"
              params={{ projectId, runId }}
              className="inline-block text-sm underline underline-offset-4"
            >
              {t("Lineage", "血缘追溯")}
            </Link>
            <p className="break-all text-sm text-muted-foreground">
              {translateValue(sources.run_status)} · {t("Completed", "完成于")}{" "}
              {formatDate(sources.completed_at)} ·{" "}
              {sources.report_contract_version}
            </p>
          </>
        )}
        <p className="text-sm text-muted-foreground">
          {t(
            "Published facts for this explicit historical Run, not the latest Run or current inputs.",
            "此处展示所选历史运行的已发布事实，而非最新运行或当前输入。",
          )}
        </p>
      </header>

      {error || identityMismatch ? (
        <Alert variant="destructive">
          <AlertTitle className="line-clamp-none">
            {identityMismatch
              ? t("Run comparison identity mismatch", "运行比较身份不匹配")
              : unavailable
                ? t(
                    "Run comparison unavailable or incompatible",
                    "运行比较不可用或不兼容",
                  )
                : t("Run comparison request failed", "运行比较请求失败")}
          </AlertTitle>
          <AlertDescription>
            <p>
              {identityMismatch
                ? t(
                    "The responses do not identify the requested Run and the same Report version. No source or comparison facts are displayed.",
                    "响应未指向所请求的运行和同一报告版本。不展示任何来源或比较事实。",
                  )
                : unavailable
                  ? t(
                      "This explicit Run is unavailable or incompatible with source comparison. No other Run has been substituted.",
                      "所选运行不可用或不支持来源比较。未替换为其他运行。",
                    )
                  : t(
                      "The published facts could not be loaded. Please try again.",
                      "无法加载已发布事实，请重试。",
                    )}
            </p>
            <p>
              {t(
                "A failed request does not mean a source is ABSENT or an IP has UNKNOWN status.",
                "请求失败不代表来源未提供（ABSENT），也不代表 IP 状态未知（UNKNOWN）。",
              )}
            </p>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                void sourcesQuery.refetch()
                void comparisonQuery.refetch()
              }}
            >
              {t("Try again", "重试")}
            </Button>
          </AlertDescription>
        </Alert>
      ) : !ready ? (
        <p role="status">
          {t("Loading Run source comparison…", "正在加载运行来源比较…")}
        </p>
      ) : null}

      <section
        aria-label={t("Source overview", "来源概览")}
        className="min-w-0 space-y-3"
      >
        <h2 className="text-xl font-semibold">
          {t("Source overview", "来源概览")}
        </h2>
        <p className="text-sm text-muted-foreground">
          {t(
            "PRESENT means a source snapshot was published, including a snapshot with 0 raw records. ABSENT means no snapshot was published for this source in this Run; it is not a request failure. Raw record counts do not measure positive activity or traffic volume.",
            "PRESENT 表示已发布来源快照，包括原始记录数为 0 的快照。ABSENT 表示本次运行未发布该来源的快照，并非请求失败。原始记录数不衡量有效活动或流量大小。",
          )}
        </p>
        {ready && (
          <div className="grid min-w-0 gap-4 lg:grid-cols-3">
            {sources.sources.map((source) => (
              <Card
                key={source.source_type}
                role="region"
                aria-label={translateValue(SOURCE_NAMES[source.source_type])}
                className="min-w-0"
              >
                <CardHeader>
                  <CardTitle>
                    <h3>{translateValue(SOURCE_NAMES[source.source_type])}</h3>
                  </CardTitle>
                  <Badge
                    variant={
                      source.state === "PRESENT" ? "default" : "secondary"
                    }
                  >
                    {translateValue(source.state)}
                  </Badge>
                </CardHeader>
                <CardContent className="space-y-3 text-sm">
                  <dl className="space-y-2 [&_dd]:break-all [&_dt]:font-medium">
                    <div>
                      <dt>{t("Raw records", "原始记录数")}</dt>
                      <dd>
                        {source.record_count ?? t("Not available", "不可用")}
                      </dd>
                    </div>
                    <div>
                      <dt>{t("Snapshot ID", "快照 ID")}</dt>
                      <dd>
                        {source.snapshot_id ?? t("Not available", "不可用")}
                      </dd>
                    </div>
                    <div>
                      <dt>{t("Input ID", "输入 ID")}</dt>
                      <dd>{source.input_id ?? t("Not available", "不可用")}</dd>
                    </div>
                    <div>
                      <dt>
                        {t("Valid time start (UTC)", "有效时间起点（UTC）")}
                      </dt>
                      <dd>
                        {source.valid_time_start_utc
                          ? formatDate(source.valid_time_start_utc, "UTC")
                          : t("Not available", "不可用")}
                      </dd>
                    </div>
                    <div>
                      <dt>
                        {t("Valid time end (UTC)", "有效时间终点（UTC）")}
                      </dt>
                      <dd>
                        {source.valid_time_end_utc
                          ? formatDate(source.valid_time_end_utc, "UTC")
                          : t("Not available", "不可用")}
                      </dd>
                    </div>
                  </dl>
                  <details>
                    <summary className="cursor-pointer">
                      {t("Hashes and fingerprints", "哈希与指纹")}
                    </summary>
                    <dl className="mt-2 space-y-2 [&_dd]:break-all [&_dd]:font-mono [&_dd]:text-xs [&_dt]:font-medium">
                      <div>
                        <dt>{t("Content SHA-256", "内容 SHA-256")}</dt>
                        <dd>
                          {source.content_sha256 ??
                            t("Not available", "不可用")}
                        </dd>
                      </div>
                      <div>
                        <dt>{t("Schema fingerprint", "结构指纹")}</dt>
                        <dd>
                          {source.schema_fingerprint ??
                            t("Not available", "不可用")}
                        </dd>
                      </div>
                      <div>
                        <dt>{t("Method fingerprint", "方法指纹")}</dt>
                        <dd>
                          {source.method_fingerprint ??
                            t("Not available", "不可用")}
                        </dd>
                      </div>
                    </dl>
                  </details>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </section>

      <section
        aria-label={t("IP source comparison", "IP 来源比较")}
        className="min-w-0 space-y-4"
      >
        <h2 className="text-xl font-semibold">
          {t("IP source comparison", "IP 来源比较")}
        </h2>
        <p className="text-sm text-muted-foreground">
          {t(
            "Observed / Not observed describes evidence in the CustomerUpload and CloudAtlas snapshots. NetFlow ACTIVE means positive activity was observed. UNKNOWN means no positive activity evidence; it does not mean the IP is nonexistent, has zero traffic, or has zero risk.",
            "已观测 / 未观测描述客户上传和 CloudAtlas 快照中的证据。NetFlow ACTIVE 表示观测到有效活动。UNKNOWN 表示没有有效活动证据，不代表 IP 不存在、流量为零或风险为零。",
          )}
        </p>
        <div className="flex flex-wrap gap-3">
          <label className="grid min-w-0 max-w-full gap-1 text-sm">
            {t("Classification", "分类")}
            <select
              aria-label={t("Classification", "分类")}
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
              <option value="">{t("All classifications", "全部分类")}</option>
              {CLASSIFICATIONS.map((value) => (
                <option key={value} value={value}>
                  {translateValue(value)}
                </option>
              ))}
            </select>
          </label>
          <label className="grid min-w-0 max-w-full gap-1 text-sm">
            {t("NetFlow status", "NetFlow 状态")}
            <select
              aria-label={t("NetFlow status", "NetFlow 状态")}
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
              <option value="">
                {t("All NetFlow statuses", "全部 NetFlow 状态")}
              </option>
              {NETFLOW_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {translateValue(value)}
                </option>
              ))}
            </select>
          </label>
        </div>
        {ready && (
          <>
            {comparison.data.length === 0 ? (
              <p role="status" className="text-sm text-muted-foreground">
                {t(
                  "No IP source comparisons match this Run and filters. This does not establish zero traffic or zero risk.",
                  "没有符合此运行和筛选条件的 IP 来源比较结果。这不代表流量为零或风险为零。",
                )}
              </p>
            ) : (
              <section
                aria-label={t("IP source comparison table", "IP 来源比较表")}
                // biome-ignore lint/a11y/noNoninteractiveTabindex: Keyboard users must be able to scroll the matrix horizontally.
                tabIndex={0}
                className="max-w-full overflow-x-auto rounded-lg focus-visible:outline-2 focus-visible:outline-ring [&>[data-slot=table-container]]:overflow-visible"
              >
                <Table className="min-w-[700px]">
                  <TableHeader>
                    <TableRow>
                      <TableHead scope="col">
                        {t("Canonical IP", "规范化 IP")}
                      </TableHead>
                      <TableHead scope="col">
                        {translateValue("CustomerUpload")}
                      </TableHead>
                      <TableHead scope="col">CloudAtlas</TableHead>
                      <TableHead scope="col">NetFlow</TableHead>
                      <TableHead scope="col">
                        {t("Classification", "分类")}
                      </TableHead>
                      <TableHead scope="col">
                        {t("Lineage", "血缘追溯")}
                      </TableHead>
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
                            ? t("Observed", "已观测")
                            : t("Not observed", "未观测")}
                        </TableCell>
                        <TableCell>
                          {row.cloudatlas_present
                            ? t("Observed", "已观测")
                            : t("Not observed", "未观测")}
                        </TableCell>
                        <TableCell>
                          {translateValue(row.netflow_status)}
                          <p className="max-w-64 whitespace-normal text-xs text-muted-foreground">
                            {translateValue(row.netflow_reason)}
                          </p>
                        </TableCell>
                        <TableCell>
                          {translateValue(row.classification)}
                        </TableCell>
                        <TableCell>
                          <Link
                            to="/projects/$projectId/runs/$runId/lineage"
                            params={{ projectId, runId }}
                            search={{ resource_id: row.resource_id }}
                            aria-label={t(
                              `Trace asset ${row.canonical_ip}`,
                              `追溯资产 ${row.canonical_ip}`,
                            )}
                            className="underline underline-offset-4"
                          >
                            {t("Trace asset", "追溯资产")}
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
