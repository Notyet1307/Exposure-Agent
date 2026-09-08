import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  FileText,
  Filter,
  Languages,
} from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import CustomerReadingWorkspace from "@/components/CustomerReadingWorkspace"
import { cn } from "@/lib/utils"

// Three variants of the project reading surface, switchable with ?prototype=customer&variant=A.
type Variant = "A" | "B" | "C"
type Locale = "zh" | "en"

const RUN_ID = "becdfd4f-fdb4-47cb-90ad-2cf07fe0be8f"
const REPORT_ID = "fb498db7-e67f-566e-9524-09adab2c8bfc"
const IPs = Array.from({ length: 22 }, (_, index) => `192.0.2.${index + 1}`)

const copy = {
  zh: {
    prototype: "只读合成原型 · 已验证运行",
    project: "手动验收 2026-09-08 · 合成样本",
    language: "English",
    overview: "概览",
    matrix: "资产矩阵",
    lineage: "资产血缘",
    report: "报告摘要",
    completed: "已完成",
    published: "已发布",
    source: "数据来源",
    matched: "双来源匹配",
    customerOnly: "仅客户侧",
    atlasOnly: "仅 CloudAtlas",
    active: "有正向活动",
    unknown: "活动未知",
    summary: "本次治理结果",
    summaryText: "22 个 IP 中，20 个在客户资产表与 CloudAtlas 中均有记录；2 个差异资产需要确认归属。",
    viewMatrix: "查看资产矩阵",
    trace: "追溯证据",
    details: "查看技术详情",
    hideDetails: "收起技术详情",
    sourceCoverage: "来源完整性",
    customer: "客户资产表",
    atlas: "CloudAtlas",
    netflow: "NetFlow",
    records: "条记录",
    selected: "已选择",
    all: "全部资产",
    differences: "仅差异资产",
    activity: "有正向活动",
    filter: "筛选",
    page: "第 {page} / {pages} 页",
    evidence: "证据详情",
    noPositive: "未发现正向活动证据；不代表 IP 不存在、无流量或无风险。",
    customerObserved: "客户侧已观测",
    atlasObserved: "CloudAtlas 已观测",
    unobserved: "未观测",
    reportNote: "原型摘要，不是正式报告；不改写历史报告或已发布事实。",
    findings: "结论与需确认项",
    findingOne: "192.0.2.21 仅在客户资产表中存在，CloudAtlas 未观测。",
    findingTwo: "192.0.2.22 仅在 CloudAtlas 中存在，客户资产表未报备。",
    findingThree: "192.0.2.10 与 192.0.2.11 有 NetFlow 正向活动。",
    openReport: "阅读正式报告",
    reportVersion: "报告版本 deterministic-report-v2",
    run: "运行",
    reportId: "报告 ID",
    hash: "Hash 与技术引用",
    showEvidence: "展开证据",
    asset: "资产",
    scope: "本页仅覆盖原型内容；应用外壳仍沿用当前英文。",
    relationship: "关系示意",
    relationshipHint: "用于阅读已发布证据的关系示意，不是正式血缘 DTO。选择节点可查看其详情。",
    result: "已发布结果",
    reportNode: "治理报告",
    nodeDetails: "节点详情",
    assetNode: "IP 资产",
    activityEvidence: "活动证据",
    openFormalReport: "阅读报告摘要",
    previous: "上一个原型",
    next: "下一个原型",
    variantA: "摘要优先",
    variantB: "资产工作台",
    variantC: "汇报阅读",
  },
  en: {
    prototype: "Read-only synthetic prototype · verified run",
    project: "Manual acceptance 2026-09-08 · synthetic sample",
    language: "简体中文",
    overview: "Overview",
    matrix: "Asset matrix",
    lineage: "Asset lineage",
    report: "Report summary",
    completed: "Completed",
    published: "Published",
    source: "Sources",
    matched: "Matched in two sources",
    customerOnly: "Customer only",
    atlasOnly: "CloudAtlas only",
    active: "Positive activity",
    unknown: "Activity unknown",
    summary: "This governance run",
    summaryText: "Of 22 IPs, 20 occur in both the customer upload and CloudAtlas. Two differences need ownership confirmation.",
    viewMatrix: "View asset matrix",
    trace: "Trace evidence",
    details: "Technical details",
    hideDetails: "Hide technical details",
    sourceCoverage: "Source coverage",
    customer: "Customer upload",
    atlas: "CloudAtlas",
    netflow: "NetFlow",
    records: "records",
    selected: "Selected",
    all: "All assets",
    differences: "Differences only",
    activity: "Positive activity",
    filter: "Filter",
    page: "Page {page} of {pages}",
    evidence: "Evidence details",
    noPositive: "No positive activity evidence was observed. This does not mean the IP does not exist, has no traffic, or has no risk.",
    customerObserved: "Observed in customer upload",
    atlasObserved: "Observed in CloudAtlas",
    unobserved: "Not observed",
    reportNote: "Prototype summary, not the formal report; historical reports and published facts are unchanged.",
    findings: "Conclusions and confirmations needed",
    findingOne: "192.0.2.21 appears only in the customer upload; it was not observed in CloudAtlas.",
    findingTwo: "192.0.2.22 appears only in CloudAtlas; it is not declared in the customer upload.",
    findingThree: "192.0.2.10 and 192.0.2.11 have positive NetFlow activity.",
    openReport: "Read formal report",
    reportVersion: "Report version deterministic-report-v2",
    run: "Run",
    reportId: "Report ID",
    hash: "Hashes and technical references",
    showEvidence: "Show evidence",
    asset: "Asset",
    scope: "Only the prototype content is bilingual; the current application shell remains English.",
    relationship: "Relationship view",
    relationshipHint: "A reading aid for published evidence, not a formal lineage DTO. Select a node to inspect its details.",
    result: "Published result",
    reportNode: "Governance report",
    nodeDetails: "Node details",
    assetNode: "IP asset",
    activityEvidence: "Activity evidence",
    openFormalReport: "Read report summary",
    previous: "Previous prototype",
    next: "Next prototype",
    variantA: "Summary first",
    variantB: "Asset workbench",
    variantC: "Reading brief",
  },
} as const

function assetState(ip: string) {
  const last = Number(ip.split(".").pop())
  return {
    ip,
    customer: last !== 22,
    atlas: last !== 21,
    active: last === 10 || last === 11,
  }
}

function sourceLabel(value: boolean, yes: string, no: string) {
  return <Badge variant={value ? "default" : "outline"}>{value ? yes : no}</Badge>
}

function Metric({ value, label, muted = false }: { value: string; label: string; muted?: boolean }) {
  return (
    <div className="border-l-2 border-primary/45 pl-3">
      <p className={cn("text-2xl font-semibold tracking-tight", muted && "text-muted-foreground")}>{value}</p>
      <p className="text-sm text-muted-foreground">{label}</p>
    </div>
  )
}

function SourceStrip({ t }: { t: (typeof copy)[Locale] }) {
  return (
    <section className="grid gap-3 sm:grid-cols-3" aria-label={t.sourceCoverage}>
      {[[t.customer, "21"], [t.atlas, "21"], [t.netflow, "2"]].map(([name, count]) => (
        <div key={name} className="flex items-center justify-between rounded-xl bg-muted/60 px-4 py-3">
          <span className="font-medium">{name}</span><span className="text-sm text-muted-foreground">{count} {t.records}</span>
        </div>
      ))}
    </section>
  )
}

function Matrix({ t, selectedIp, onSelect, compact = false }: { t: (typeof copy)[Locale]; selectedIp: string; onSelect: (ip: string) => void; compact?: boolean }) {
  const [filter, setFilter] = useState<"all" | "diff" | "active">("all")
  const [page, setPage] = useState(0)
  const filtered = useMemo(() => IPs.map(assetState).filter((asset) => filter === "all" || (filter === "diff" ? !asset.customer || !asset.atlas : asset.active)), [filter])
  const pageSize = compact ? 7 : 8
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize))
  const assets = filtered.slice(page * pageSize, (page + 1) * pageSize)
  const set = (next: typeof filter) => { setFilter(next); setPage(0) }
  return (
    <section className="min-w-0 space-y-3" aria-label={t.matrix}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2" aria-label={t.filter}>
          {[["all", t.all], ["diff", t.differences], ["active", t.activity]].map(([value, label]) => <Button key={value} type="button" size="sm" variant={filter === value ? "default" : "outline"} onClick={() => set(value as typeof filter)}>{label}</Button>)}
        </div>
        <span className="text-sm text-muted-foreground">{t.page.replace("{page}", String(page + 1)).replace("{pages}", String(pageCount))}</span>
      </div>
      <div className="max-h-[24rem] overflow-auto rounded-xl border" tabIndex={0} aria-label={t.matrix}>
        <table className="w-full min-w-[38rem] text-sm">
          <thead className="sticky top-0 bg-muted text-left text-muted-foreground"><tr><th className="px-4 py-3 font-medium">IP</th><th className="px-4 py-3 font-medium">{t.customer}</th><th className="px-4 py-3 font-medium">{t.atlas}</th><th className="px-4 py-3 font-medium">{t.netflow}</th><th className="px-4 py-3" /></tr></thead>
          <tbody>{assets.map((asset) => <tr key={asset.ip} className={cn("border-t", selectedIp === asset.ip && "bg-primary/10")}><td className="px-4 py-3 font-medium">{asset.ip}</td><td className="px-4 py-3">{sourceLabel(asset.customer, t.customerObserved, t.unobserved)}</td><td className="px-4 py-3">{sourceLabel(asset.atlas, t.atlasObserved, t.unobserved)}</td><td className="px-4 py-3">{asset.active ? <Badge>{t.active}</Badge> : <Badge variant="secondary">{t.unknown}</Badge>}</td><td className="px-4 py-3 text-right"><Button type="button" variant="ghost" size="sm" onClick={() => onSelect(asset.ip)}>{t.trace}<ChevronRight /></Button></td></tr>)}</tbody>
        </table>
      </div>
      <div className="flex justify-end gap-2"><Button type="button" variant="outline" size="icon-sm" aria-label="Previous" disabled={page === 0} onClick={() => setPage((value) => value - 1)}><ChevronLeft /></Button><Button type="button" variant="outline" size="icon-sm" aria-label="Next" disabled={page + 1 === pageCount} onClick={() => setPage((value) => value + 1)}><ChevronRight /></Button></div>
    </section>
  )
}

function CompactAssetList({ t, selectedIp, onSelect }: { t: (typeof copy)[Locale]; selectedIp: string; onSelect: (ip: string) => void }) {
  const [filter, setFilter] = useState<"all" | "diff" | "active">("all")
  const assets = IPs.map(assetState).filter((asset) => filter === "all" || (filter === "diff" ? !asset.customer || !asset.atlas : asset.active))
  return <section className="min-w-0" aria-label={t.matrix}><div className="mb-3 flex flex-wrap gap-2">{[["all", t.all], ["diff", t.differences], ["active", t.activity]].map(([value, label]) => <Button key={value} type="button" size="sm" variant={filter === value ? "default" : "outline"} onClick={() => setFilter(value as typeof filter)}>{label}</Button>)}</div><div className="max-h-[31rem] overflow-y-auto rounded-lg border" tabIndex={0}>{assets.map((asset) => <button key={asset.ip} type="button" onClick={() => onSelect(asset.ip)} className={cn("flex w-full items-center justify-between gap-2 border-b px-3 py-3 text-left last:border-b-0 hover:bg-accent focus-visible:ring-2", selectedIp === asset.ip && "bg-primary/10")}><span className="font-medium">{asset.ip}</span><span className="flex shrink-0 gap-1">{(!asset.customer || !asset.atlas) && <Badge variant="outline">{!asset.customer ? t.atlasOnly : t.customerOnly}</Badge>}{asset.active ? <Badge>{t.active}</Badge> : <Badge variant="secondary">{t.unknown}</Badge>}</span></button>)}</div></section>
}

function Evidence({ t, ip, onSelect, onReadReport }: { t: (typeof copy)[Locale]; ip: string; onSelect: (ip: string) => void; onReadReport: () => void }) {
  const asset = assetState(ip)
  const last = Number(ip.split(".").pop())
  const nearby = [Math.max(1, last - 1), last, Math.min(22, last + 1)].map((n) => `192.0.2.${n}`)
  const [node, setNode] = useState<"customer" | "asset" | "atlas" | "netflow" | "report">("asset")
  const detail = {
    customer: [t.customer, asset.customer ? t.customerObserved : t.unobserved],
    asset: [t.assetNode, ip],
    atlas: [t.atlas, asset.atlas ? t.atlasObserved : t.unobserved],
    netflow: [t.netflow, asset.active ? t.active : t.noPositive],
    report: [t.reportNode, t.reportVersion],
  }[node]
  const Node = ({ value, label, description }: { value: typeof node; label: string; description: string }) => <button type="button" onClick={() => setNode(value)} className={cn("min-w-0 rounded-lg border px-3 py-2 text-left transition-colors hover:bg-accent focus-visible:ring-2", node === value && "border-primary bg-primary/10")}><span className="block text-sm font-medium">{label}</span><span className="block truncate text-xs text-muted-foreground">{description}</span></button>
  return <section className="min-w-0 space-y-4" aria-label={t.lineage}>
    <div className="flex items-start justify-between gap-3"><div><h2 className="text-xl font-semibold">{t.lineage}</h2><p className="text-sm text-muted-foreground">{t.asset} · {ip}</p></div><Badge>{t.selected}</Badge></div>
    <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,.9fr)]">
      <div className="min-w-0 rounded-xl border bg-muted/20 p-4"><p className="font-medium">{t.relationship}</p><p className="mt-1 text-xs leading-5 text-muted-foreground">{t.relationshipHint}</p><div className="mt-4 grid grid-cols-3 gap-2"><Node value="customer" label={t.customer} description={asset.customer ? t.customerObserved : t.unobserved} /><Node value="atlas" label={t.atlas} description={asset.atlas ? t.atlasObserved : t.unobserved} /><Node value="netflow" label={t.netflow} description={asset.active ? t.active : t.unknown} /></div><div className="my-2 flex justify-center text-muted-foreground" aria-hidden="true"><ArrowDown className="size-4" /></div><div className="flex min-w-0 items-center justify-center gap-2"><Node value="asset" label={ip} description={t.assetNode} /><ArrowRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" /><Node value="report" label={t.reportNode} description="v2" /></div></div>
      <aside className="rounded-xl bg-muted/60 p-4" aria-live="polite"><p className="font-medium">{t.nodeDetails}</p><p className="mt-3 text-sm font-medium">{detail[0]}</p><p className="mt-1 text-sm leading-6 text-muted-foreground">{detail[1]}</p><Button type="button" variant="outline" size="sm" className="mt-4" onClick={onReadReport}>{t.openFormalReport}<FileText /></Button></aside>
    </div>
    <div className="flex flex-wrap gap-2">{nearby.map((candidate) => <Button key={candidate} size="sm" type="button" variant={candidate === ip ? "default" : "outline"} onClick={() => onSelect(candidate)}>{candidate}</Button>)}</div>
  </section>
}

function TechnicalDetails({ t }: { t: (typeof copy)[Locale] }) {
  return <details className="rounded-xl border px-4 py-3"><summary className="cursor-pointer font-medium">{t.hash}</summary><dl className="mt-3 grid gap-2 text-sm sm:grid-cols-[9rem_1fr]"><dt className="text-muted-foreground">{t.run}</dt><dd className="break-all font-mono text-xs">{RUN_ID}</dd><dt className="text-muted-foreground">{t.reportId}</dt><dd className="break-all font-mono text-xs">{REPORT_ID}</dd><dt className="text-muted-foreground">{t.customer} SHA-256</dt><dd className="break-all font-mono text-xs">9a42322bfd34…a63541e96</dd><dt className="text-muted-foreground">{t.atlas} SHA-256</dt><dd className="break-all font-mono text-xs">ea68f9676f9f…cfb58b303</dd><dt className="text-muted-foreground">{t.netflow} SHA-256</dt><dd className="break-all font-mono text-xs">69711e7a2fb8…675464294</dd></dl></details>
}

function VariantA({ t, selectedIp, onSelect }: { t: (typeof copy)[Locale]; selectedIp: string; onSelect: (ip: string) => void }) {
  const [tab, setTab] = useState<"overview" | "matrix" | "lineage" | "report">("overview")
  return <div className="space-y-6 pb-20">
    <nav className="flex max-w-full gap-1 overflow-x-auto border-b" aria-label="Prototype sections">{(["overview", "matrix", "lineage", "report"] as const).map((name) => <button key={name} type="button" className={cn("shrink-0 border-b-2 px-3 py-3 text-sm font-medium", tab === name ? "border-primary text-foreground" : "border-transparent text-muted-foreground")} onClick={() => setTab(name)}>{t[name]}</button>)}</nav>
    {tab === "overview" && <><section className="grid gap-6 lg:grid-cols-[minmax(0,1.35fr)_minmax(18rem,.65fr)]"><div><h1 className="text-3xl font-semibold tracking-tight">{t.summary}</h1><p className="mt-3 max-w-2xl text-base leading-7 text-muted-foreground">{t.summaryText}</p><Button type="button" className="mt-5" onClick={() => setTab("matrix")}>{t.viewMatrix}<ArrowRight /></Button></div><div className="grid grid-cols-2 gap-x-5 gap-y-5"><Metric value="22" label={t.all} /><Metric value="20" label={t.matched} /><Metric value="1" label={t.customerOnly} muted /><Metric value="1" label={t.atlasOnly} muted /></div></section><SourceStrip t={t} /><section className="border-t pt-5"><h2 className="text-xl font-semibold">{t.findings}</h2><div className="mt-3 grid gap-2"><button type="button" className="rounded-xl bg-muted/65 p-4 text-left text-sm hover:bg-muted" onClick={() => { onSelect("192.0.2.21"); setTab("lineage") }}>{t.findingOne}<ChevronRight className="float-right size-4" /></button><button type="button" className="rounded-xl bg-muted/65 p-4 text-left text-sm hover:bg-muted" onClick={() => { onSelect("192.0.2.22"); setTab("lineage") }}>{t.findingTwo}<ChevronRight className="float-right size-4" /></button></div></section></>}
    {tab === "matrix" && <Matrix t={t} selectedIp={selectedIp} onSelect={(ip) => { onSelect(ip); setTab("lineage") }} />}
    {tab === "lineage" && <><Evidence t={t} ip={selectedIp} onSelect={onSelect} onReadReport={() => setTab("report")} /><TechnicalDetails t={t} /></>}
    {tab === "report" && <ReadingBrief t={t} onTrace={(ip) => { onSelect(ip); setTab("lineage") }} />}
  </div>
}

function VariantB({ t, selectedIp, onSelect }: { t: (typeof copy)[Locale]; selectedIp: string; onSelect: (ip: string) => void }) {
  const [showReport, setShowReport] = useState(false)
  if (showReport) return <div className="pb-20"><Button type="button" variant="ghost" onClick={() => setShowReport(false)}><ArrowLeft />{t.matrix}</Button><ReadingBrief t={t} onTrace={onSelect} /></div>
  return <div className="space-y-5 pb-20"><header className="flex flex-wrap items-end justify-between gap-3"><div><h1 className="text-3xl font-semibold tracking-tight">{t.matrix}</h1><p className="mt-2 text-muted-foreground">{t.summaryText}</p></div><Badge>{t.published}</Badge></header><div className="grid min-h-[37rem] gap-5 lg:grid-cols-[minmax(21rem,.8fr)_minmax(0,1.2fr)]"><div className="min-w-0 rounded-xl border p-4"><div className="mb-3 flex items-center gap-2 text-sm font-medium"><Filter className="size-4" />{t.filter}</div><CompactAssetList t={t} selectedIp={selectedIp} onSelect={onSelect} /></div><div className="min-w-0 rounded-xl border p-5"><Evidence t={t} ip={selectedIp} onSelect={onSelect} onReadReport={() => setShowReport(true)} /><TechnicalDetails t={t} /></div></div></div>
}

function ReadingBrief({ t, onTrace }: { t: (typeof copy)[Locale]; onTrace: (ip: string) => void }) {
  return <article className="mx-auto max-w-3xl space-y-7 pb-20"><header><Badge>{t.published}</Badge><h1 className="mt-4 text-3xl font-semibold tracking-tight">{t.summary}</h1><p className="mt-3 text-base leading-7 text-muted-foreground">{t.summaryText}</p></header><section className="border-y py-5"><h2 className="text-xl font-semibold">{t.findings}</h2><ol className="mt-4 space-y-4"><li className="flex gap-3"><span className="mt-1 size-2 shrink-0 rounded-full bg-primary" /><div><p>{t.findingOne}</p><Button type="button" variant="link" size="sm" className="mt-1 h-auto p-0" onClick={() => onTrace("192.0.2.21")}>{t.trace}<ArrowRight /></Button></div></li><li className="flex gap-3"><span className="mt-1 size-2 shrink-0 rounded-full bg-primary" /><div><p>{t.findingTwo}</p><Button type="button" variant="link" size="sm" className="mt-1 h-auto p-0" onClick={() => onTrace("192.0.2.22")}>{t.trace}<ArrowRight /></Button></div></li><li className="flex gap-3"><span className="mt-1 size-2 shrink-0 rounded-full bg-primary" /><p>{t.findingThree}</p></li></ol></section><SourceStrip t={t} /><details className="rounded-xl bg-muted/55 p-4"><summary className="cursor-pointer font-medium">{t.showEvidence}</summary><p className="mt-3 text-sm leading-6 text-muted-foreground">{t.noPositive}</p><p className="mt-2 text-sm leading-6 text-muted-foreground">{t.reportVersion}</p></details><p className="text-sm text-muted-foreground">{t.reportNote}</p></article>
}

function VariantC({ t, selectedIp, onSelect }: { t: (typeof copy)[Locale]; selectedIp: string; onSelect: (ip: string) => void }) {
  const [tracing, setTracing] = useState<string | null>(null)
  const trace = (ip: string) => { onSelect(ip); setTracing(ip) }
  return <div className="pb-20">{tracing ? <div className="space-y-4"><Button type="button" variant="ghost" onClick={() => setTracing(null)}><ArrowLeft />{t.report}</Button><Evidence t={t} ip={tracing} onSelect={trace} onReadReport={() => setTracing(null)} /><TechnicalDetails t={t} /></div> : <><p className="mb-4 text-sm text-muted-foreground">{t.selected} {t.asset}: {selectedIp}</p><ReadingBrief t={t} onTrace={trace} /></>}</div>
}

export default function CustomerReadingPrototype({ variant, reader, readerSection, readerLocale, resourceId, onVariantChange, onReaderSectionChange, onReaderLocaleChange }: { variant: Variant; reader?: "full"; readerSection?: "overview" | "matrix" | "lineage" | "report"; readerLocale?: Locale; resourceId?: string; onVariantChange: (variant: Variant) => void; onReaderSectionChange: (section: "overview" | "matrix" | "lineage" | "report", resourceId?: string) => void; onReaderLocaleChange: (locale: Locale) => void }) {
  const [locale, setLocale] = useState<Locale>(() => (localStorage.getItem("customer-reading-locale") === "en" ? "en" : "zh"))
  const [selectedIp, setSelectedIp] = useState("192.0.2.21")
  const t = copy[locale]
  useEffect(() => { localStorage.setItem("customer-reading-locale", locale) }, [locale])
  useEffect(() => { if (readerLocale) setLocale(readerLocale) }, [readerLocale])
  useEffect(() => {
    if (reader === "full") return
    const move = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || (event.target instanceof HTMLElement && event.target.isContentEditable)) return
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return
      event.preventDefault()
      const all: Variant[] = ["A", "B", "C"]
      const at = all.indexOf(variant)
      onVariantChange(all[(at + (event.key === "ArrowRight" ? 1 : 2)) % all.length])
    }
    window.addEventListener("keydown", move)
    return () => window.removeEventListener("keydown", move)
  }, [onVariantChange, reader, variant])
  if (reader === "full") {
    return <CustomerReadingWorkspace locale={locale} initialSection={readerSection} resourceId={resourceId} onLocaleChange={(next) => { setLocale(next); onReaderLocaleChange(next) }} onSectionChange={onReaderSectionChange} />
  }
  const names: Record<Variant, string> = { A: t.variantA, B: t.variantB, C: t.variantC }
  const previous = ({ A: "C", B: "A", C: "B" } as const)[variant]
  const next = ({ A: "B", B: "C", C: "A" } as const)[variant]
  return <div className="space-y-6"><header className="flex flex-wrap items-start justify-between gap-4"><div><div className="mb-2 flex flex-wrap items-center gap-2"><Badge variant="outline">{t.prototype}</Badge><Badge>{t.completed}</Badge></div><h1 className="text-xl font-semibold tracking-tight">{t.project}</h1><p className="mt-1 text-sm text-muted-foreground">{t.scope}</p></div><Button type="button" variant="outline" size="sm" onClick={() => setLocale(locale === "zh" ? "en" : "zh")}><Languages />{t.language}</Button></header>{variant === "A" && <VariantA t={t} selectedIp={selectedIp} onSelect={setSelectedIp} />}{variant === "B" && <VariantB t={t} selectedIp={selectedIp} onSelect={setSelectedIp} />}{variant === "C" && <VariantC t={t} selectedIp={selectedIp} onSelect={setSelectedIp} />}<div className="fixed inset-x-0 bottom-5 z-30 flex justify-center px-4"><div className="flex items-center gap-2 rounded-full border bg-background/95 px-2 py-2 shadow-lg backdrop-blur"><Button type="button" size="icon-sm" variant="ghost" aria-label={t.previous} onClick={() => onVariantChange(previous)}><ArrowLeft /></Button><span className="min-w-36 text-center text-sm font-medium">{variant} · {names[variant]}</span><Button type="button" size="icon-sm" variant="ghost" aria-label={t.next} onClick={() => onVariantChange(next)}><ArrowRight /></Button></div></div></div>
}
