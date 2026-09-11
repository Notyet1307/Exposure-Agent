import { Link } from "@tanstack/react-router"
import { z } from "zod"

import {
  getVerifiedReportContent,
  useGovernanceReport,
} from "@/components/GovernanceReports"
import { TechnicalValue } from "@/components/TechnicalValue"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useI18n } from "@/lib/i18n"

const count = z.number().int().nonnegative()
const comparisonSummarySchema = z.object({
  resource_count: count,
  classification_counts: z.object({
    matched: count,
    customer_upload_only: count,
    cloudatlas_only: count,
    neither_source_observed: count,
  }),
  netflow_status_counts: z.object({
    ACTIVE: count,
    UNKNOWN: count,
  }),
  netflow_reason_counts: z.object({
    positive_activity_observed: count,
    netflow_input_absent: count,
    no_positive_activity_evidence: count,
  }),
})

export default function WorkspaceOverview({
  projectId,
  runId,
  reportId,
}: {
  projectId: string
  runId: string
  reportId: string
}) {
  const { t, formatDate, translateValue } = useI18n()
  const detailQuery = useGovernanceReport(projectId, reportId)
  if (detailQuery.isPending) {
    return <p role="status">{t("Loading overview…", "正在加载概览…")}</p>
  }
  if (detailQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>
          {t("Overview could not be loaded", "无法加载概览")}
        </AlertTitle>
        <AlertDescription>
          {t(
            "Please try again later. No summary is shown.",
            "请稍后重试。不显示摘要。",
          )}
        </AlertDescription>
      </Alert>
    )
  }
  const detail = detailQuery.data
  const report = getVerifiedReportContent(detail, projectId, reportId, runId)
  const legacy = detail.report_contract_version === "deterministic-report-v1"
  const summary = comparisonSummarySchema.safeParse(
    report?.ip_source_comparison_summary,
  )
  if (
    !report ||
    (!legacy &&
      (detail.report_contract_version !== "deterministic-report-v2" ||
        !summary.success))
  ) {
    return (
      <Alert variant="destructive">
        <AlertTitle>
          {t("Published summary is not readable", "无法读取已发布摘要")}
        </AlertTitle>
        <AlertDescription>
          {t(
            "The report identity or mandatory summary does not match the published contract. No partial summary is shown.",
            "报告身份或必需的摘要不符合已发布合同。不显示部分摘要。",
          )}
        </AlertDescription>
      </Alert>
    )
  }

  return (
    <section className="space-y-4" aria-labelledby="workspace-overview-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="workspace-overview-title" className="text-xl font-semibold">
            {t("Published overview", "已发布结果概览")}
          </h2>
          <p className="text-sm text-muted-foreground">
            {t("Run completed", "运行完成时间")} ·{" "}
            {formatDate(detail.run_completed_at)}
          </p>
        </div>
        <nav
          className="flex flex-wrap gap-2"
          aria-label={t("Explore published results", "浏览已发布结果")}
        >
          <Button asChild variant="outline">
            <Link
              to="/projects/$projectId/runs/$runId/comparison"
              params={{ projectId, runId }}
              search={{ project: projectId, run: runId }}
            >
              {t("View all assets & differences", "查看全部资产与差异")}
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link
              to="/projects/$projectId/runs/$runId/lineage"
              params={{ projectId, runId }}
              search={{ project: projectId, run: runId }}
            >
              {t("Lineage", "血缘")}
            </Link>
          </Button>
        </nav>
      </div>
      {!legacy && (
        <section
          className="space-y-3 rounded-lg border p-4"
          aria-label={t("Priority review", "优先核查")}
        >
          <h3 className="font-semibold">{t("Priority review", "优先核查")}</h3>
          <div className="flex flex-col items-start gap-3">
            {(["cloudatlas_only", "customer_upload_only"] as const).map(
              (classification) => (
                <Link
                  key={classification}
                  to="/projects/$projectId/runs/$runId/comparison"
                  params={{ projectId, runId }}
                  search={{
                    project: projectId,
                    run: runId,
                    classification,
                    netflow_status: "ACTIVE",
                  }}
                  className="break-words text-sm underline underline-offset-4 focus-visible:outline-2"
                >
                  {classification === "cloudatlas_only"
                    ? t(
                        "Not registered, externally observed with activity",
                        "台账未登记，外部已观测且有活动",
                      )
                    : t(
                        "Registered, not externally observed but active",
                        "台账已登记，外部未观测但有活动",
                      )}
                </Link>
              ),
            )}
          </div>
          <p className="text-sm text-muted-foreground">
            {t(
              "Review clues, not risk ratings or a complete risk list. Published totals below describe separate dimensions, not these combined filters.",
              "这些入口是核查线索，不是风险等级或完整风险清单。下方批次总数分别描述各维度，不是这些组合筛选的数量。",
            )}
          </p>
        </section>
      )}
      {legacy ? (
        <Alert>
          <AlertTitle>
            {t("Three-source summary: N/A", "三来源汇总：不适用")}
          </AlertTitle>
          <AlertDescription>
            {t(
              "This legacy report-v1 did not publish a three-source summary. Missing counts are not zero; read its original report for available results.",
              "此旧版 report-v1 未发布三来源汇总。缺失的计数不代表零；可用结果请阅读原始报告。",
            )}
          </AlertDescription>
        </Alert>
      ) : summary.success ? (
        <>
          <Card>
            <CardHeader>
              <CardTitle>
                {t("Three-source comparison", "三来源比较")}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
                <div>
                  <dt className="text-sm text-muted-foreground">
                    {t("Compared resources", "比较资源总数")}
                  </dt>
                  <dd className="text-2xl font-semibold tabular-nums">
                    {summary.data.resource_count}
                  </dd>
                </div>
                {Object.entries(summary.data.classification_counts).map(
                  ([classification, value]) => (
                    <div key={classification}>
                      <dt className="text-sm text-muted-foreground">
                        {translateValue(classification)}
                      </dt>
                      <dd className="text-2xl font-semibold tabular-nums">
                        {value}
                      </dd>
                    </div>
                  ),
                )}
              </dl>
              <p className="text-sm text-muted-foreground">
                {t(
                  "Full published Run totals, independent of matrix filters and pagination. Classification compares CustomerUpload and CloudAtlas presence; NetFlow adds positive activity evidence only.",
                  "完整的已发布运行总计，不受矩阵筛选和分页影响。分类比较 CustomerUpload 与 CloudAtlas 的存在性；NetFlow 仅补充正向活动证据。",
                )}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>{t("NetFlow activity", "NetFlow 活动")}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <dl className="grid gap-4 sm:grid-cols-2">
                {Object.entries(summary.data.netflow_status_counts).map(
                  ([status, value]) => (
                    <div key={status}>
                      <dt className="text-sm text-muted-foreground">
                        {translateValue(status)}
                      </dt>
                      <dd className="text-2xl font-semibold tabular-nums">
                        {value}
                      </dd>
                    </div>
                  ),
                )}
              </dl>
              <p className="text-sm text-muted-foreground">
                {t(
                  "UNKNOWN does not mean inactive or absent. Activity evidence does not change Finding lifecycle.",
                  "UNKNOWN（未知）不代表无活动或不存在。活动证据不改变发现项生命周期。",
                )}
              </p>
              <details className="text-sm">
                <summary className="cursor-pointer font-medium">
                  {t("Activity evidence reasons", "活动证据原因")}
                </summary>
                <dl className="mt-2 space-y-2">
                  {Object.entries(summary.data.netflow_reason_counts).map(
                    ([reason, value]) => (
                      <div
                        key={reason}
                        className="flex flex-wrap justify-between gap-2"
                      >
                        <dt>{translateValue(reason)}</dt>
                        <dd className="tabular-nums">{value}</dd>
                      </div>
                    ),
                  )}
                </dl>
              </details>
            </CardContent>
          </Card>
        </>
      ) : null}
      <details className="rounded-lg border p-3 text-sm">
        <summary className="cursor-pointer font-medium">
          {t("Published report identity", "已发布报告身份")}
        </summary>
        <dl className="mt-3 space-y-2">
          <div>
            <dt>{t("Governance Run", "治理运行")}</dt>
            <dd>
              <TechnicalValue value={runId} label={t("Run ID", "运行 ID")} />
            </dd>
          </div>
          <div>
            <dt>{t("Report", "报告")}</dt>
            <dd>
              <TechnicalValue
                value={reportId}
                label={t("Report ID", "报告 ID")}
              />
            </dd>
          </div>
          <div>
            <dt>{t("Report contract", "报告合同")}</dt>
            <dd className="break-all font-mono">
              {detail.report_contract_version}
            </dd>
          </div>
        </dl>
      </details>
    </section>
  )
}
