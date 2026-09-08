import { useQuery } from "@tanstack/react-query"
import { FileText } from "lucide-react"
import { useMemo, useState } from "react"

import { IpResultsService } from "@/client"
import { ReportDetailDialog } from "@/components/GovernanceReports"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { LineageScope } from "@/routes/_layout/projects.$projectId.runs.$runId.lineage"

const PROJECT_ID = "3a36675f-789c-4789-a5bd-f03ea7d8c6f7"
const RUN_ID = "becdfd4f-fdb4-47cb-90ad-2cf07fe0be8f"

type Locale = "zh" | "en"
type Section = "overview" | "matrix" | "lineage" | "report"

const text = {
  zh: {
    title: "客户阅读工作区",
    project: "手动验收 2026-09-08 · 合成样本",
    prototype: "只读合成原型 · 已发布历史运行",
    overview: "概览",
    matrix: "资产与差异",
    lineage: "血缘追溯",
    report: "报告",
    inputs: "输入",
    runs: "运行",
    reading: "结果阅读",
    management: "管理入口",
    language: "English",
    complete: "已完成",
    source: "数据来源",
    loading: "正在读取已发布事实…",
    error: "无法读取此历史运行的已发布事实。失败不代表没有资产、数据或风险。",
    assets: "资产",
    matched: "双来源匹配",
    customerOnly: "仅客户侧",
    atlasOnly: "仅 CloudAtlas",
    active: "有正向活动",
    unknown: "活动未知",
    trace: "追溯资产",
    all: "全部",
    differences: "仅差异",
    positive: "正向活动",
    customer: "客户资产表",
    atlas: "CloudAtlas",
    netflow: "NetFlow",
    status: "运行状态",
    reportIntro: "打开已发布的确定性报告。此操作只读取当前历史运行的不可变内容。",
    openReport: "阅读已发布报告",
    scope: "此界面只调整阅读路径；资产、血缘、路径、报告和合同语义均来自已发布 Run。",
  },
  en: {
    title: "Customer reading workspace",
    project: "Manual acceptance 2026-09-08 · synthetic sample",
    prototype: "Read-only synthetic prototype · published historical run",
    overview: "Overview",
    matrix: "Assets & differences",
    lineage: "Lineage trace",
    report: "Report",
    inputs: "Inputs",
    runs: "Runs",
    reading: "Results",
    management: "Management",
    language: "简体中文",
    complete: "Completed",
    source: "Sources",
    loading: "Reading published facts…",
    error: "Published facts for this historical run could not be read. A failure does not mean there are no assets, data, or risks.",
    assets: "Assets",
    matched: "Matched in two sources",
    customerOnly: "Customer only",
    atlasOnly: "CloudAtlas only",
    active: "Positive activity",
    unknown: "Activity unknown",
    trace: "Trace asset",
    all: "All",
    differences: "Differences",
    positive: "Positive activity",
    customer: "Customer upload",
    atlas: "CloudAtlas",
    netflow: "NetFlow",
    status: "Run status",
    reportIntro: "Open the published deterministic report. It reads immutable content for this historical run only.",
    openReport: "Read published report",
    scope: "This interface changes only the reading path; assets, lineage, paths, reports, and contracts come from the published Run.",
  },
} as const

export default function CustomerReadingWorkspace({ locale, initialSection = "overview", resourceId, onLocaleChange, onSectionChange }: { locale: Locale; initialSection?: Section; resourceId?: string; onLocaleChange: (locale: Locale) => void; onSectionChange: (section: Section, resourceId?: string) => void }) {
  const t = text[locale]
  const section = initialSection
  const [filter, setFilter] = useState<"all" | "differences" | "active">("all")
  const [reportOpen, setReportOpen] = useState(false)
  const sources = useQuery({ queryKey: ["customer-reader-sources", PROJECT_ID, RUN_ID], queryFn: () => IpResultsService.readGovernanceRunSources({ projectId: PROJECT_ID, governanceRunId: RUN_ID }), retry: false })
  const comparisons = useQuery({ queryKey: ["customer-reader-comparisons", PROJECT_ID, RUN_ID], queryFn: () => IpResultsService.readGovernanceRunIpSourceComparisons({ projectId: PROJECT_ID, governanceRunId: RUN_ID, skip: 0, limit: 25 }), retry: false })
  const rows = useMemo(() => (comparisons.data?.data ?? []).filter((row) => filter === "all" || (filter === "differences" ? row.classification !== "matched" : row.netflow_status === "ACTIVE")), [comparisons.data, filter])
  const openLineage = (id: string) => onSectionChange("lineage", id)
  const sourceCount = (name: "CUSTOMER_UPLOAD" | "CLOUDATLAS" | "NETFLOW") => sources.data?.sources.find((source) => source.source_type === name)?.record_count

  return <main className="min-w-0 space-y-4 pb-12">
      <header className="flex flex-wrap items-start justify-between gap-4"><div><div className="flex flex-wrap gap-2"><Badge variant="outline">{t.prototype}</Badge><Badge>{sources.data?.run_status === "COMPLETED" ? t.complete : (sources.data?.run_status ?? "…")}</Badge></div><h1 className="mt-2 text-2xl font-semibold tracking-tight">{section === "lineage" ? t.lineage : section === "matrix" ? t.matrix : section === "report" ? t.report : t.title}</h1><p className="mt-1 text-sm text-muted-foreground">{t.project} · {locale === "zh" ? "历史运行" : "Historical run"} {RUN_ID.slice(0, 8)}</p></div><Button type="button" variant="outline" size="sm" onClick={() => onLocaleChange(locale === "zh" ? "en" : "zh")}>{t.language}</Button></header>
      <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">{locale === "zh" ? "关于这个原型" : "About this prototype"}</summary><p className="mt-2">{t.scope}</p></details>
      {(sources.isPending || comparisons.isPending) && <p role="status">{t.loading}</p>}
      {(sources.isError || comparisons.isError) && <p className="rounded-lg border border-destructive p-4 text-sm text-destructive">{t.error}</p>}
      {section === "overview" && sources.data && comparisons.data && <section className="space-y-6"><div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><Metric value={String(comparisons.data.count)} label={t.assets} /><Metric value={String(comparisons.data.data.filter((row) => row.classification === "matched").length)} label={t.matched} /><Metric value={String(comparisons.data.data.filter((row) => row.classification === "customer_upload_only").length)} label={t.customerOnly} /><Metric value={String(comparisons.data.data.filter((row) => row.classification === "cloudatlas_only").length)} label={t.atlasOnly} /></div><section><h2 className="text-xl font-semibold">{t.source}</h2><div className="mt-3 grid gap-3 sm:grid-cols-3">{[[t.customer, sourceCount("CUSTOMER_UPLOAD")], [t.atlas, sourceCount("CLOUDATLAS")], [t.netflow, sourceCount("NETFLOW")]].map(([name, count]) => <div key={name} className="rounded-xl bg-muted/65 p-4"><p className="font-medium">{name}</p><p className="mt-1 text-sm text-muted-foreground">{count ?? "—"} {t.status}</p></div>)}</div></section><Button type="button" onClick={() => onSectionChange("matrix")}>{t.matrix}</Button></section>}
      {section === "matrix" && <section className="space-y-4"><h2 className="text-xl font-semibold">{t.matrix}</h2><div className="flex flex-wrap gap-2">{([["all", t.all], ["differences", t.differences], ["active", t.positive]] as const).map(([key, label]) => <Button key={key} size="sm" type="button" variant={filter === key ? "default" : "outline"} onClick={() => setFilter(key)}>{label}</Button>)}</div><div className="max-h-[58vh] overflow-auto rounded-lg border" tabIndex={0}><table className="w-full min-w-[48rem] text-sm"><thead className="sticky top-0 bg-muted text-left"><tr><th className="px-4 py-3">IP</th><th className="px-4 py-3">{t.customer}</th><th className="px-4 py-3">{t.atlas}</th><th className="px-4 py-3">{t.netflow}</th><th className="px-4 py-3" /></tr></thead><tbody>{rows.map((row) => <tr key={row.resource_id} className="border-t"><td className="px-4 py-3 font-mono">{row.canonical_ip}</td><td className="px-4 py-3">{row.customer_upload_present ? (locale === "zh" ? "有记录" : "Observed") : (locale === "zh" ? "未观测" : "Not observed")}</td><td className="px-4 py-3">{row.cloudatlas_present ? (locale === "zh" ? "有记录" : "Observed") : (locale === "zh" ? "未观测" : "Not observed")}</td><td className="px-4 py-3">{row.netflow_status === "ACTIVE" ? t.active : t.unknown}</td><td className="px-4 py-3 text-right"><Button type="button" size="sm" variant="outline" onClick={() => openLineage(row.resource_id)}>{t.trace}</Button></td></tr>)}</tbody></table></div></section>}
      {section === "lineage" && <section className="min-w-0 space-y-3"><div className="flex flex-wrap items-center gap-3 text-sm"><span>{resourceId ? `${locale === "zh" ? "单资产" : "Single asset"}: ${comparisons.data?.data.find(row => row.resource_id === resourceId)?.canonical_ip ?? resourceId}` : (locale === "zh" ? "全部资产总览" : "All-assets overview")}</span>{resourceId && <Button size="sm" variant="outline" onClick={() => onSectionChange("lineage")}>{locale === "zh" ? "返回血缘总览" : "Back to lineage overview"}</Button>}</div><LineageScope key={`${PROJECT_ID}/${RUN_ID}/${resourceId ?? "overview"}`} projectId={PROJECT_ID} runId={RUN_ID} resourceId={resourceId} readerMode readerLocale={locale} /></section>}
      {section === "report" && <section className="rounded-xl border p-5"><h2 className="text-xl font-semibold">{t.report}</h2><p className="mt-2 text-sm text-muted-foreground">{t.reportIntro}</p><Button type="button" className="mt-4" disabled={!sources.data} onClick={() => setReportOpen(true)}>{t.openReport}<FileText /></Button></section>}
      {reportOpen && sources.data && <ReportDetailDialog projectId={PROJECT_ID} reportId={sources.data.governance_report_id} expectedRunId={RUN_ID} expectedReportContractVersion={sources.data.report_contract_version} onOpenChange={setReportOpen} />}
  </main>
}

function Metric({ value, label }: { value: string; label: string }) {
  return <div className="border-l-2 border-primary/45 pl-3"><p className="text-2xl font-semibold">{value}</p><p className="text-sm text-muted-foreground">{label}</p></div>
}
