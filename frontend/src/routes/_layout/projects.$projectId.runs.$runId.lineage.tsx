import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { createContext, type ReactNode, useContext, useEffect, useRef, useState } from "react"

import {
  ApiError,
  type GovernanceRunLineagePublic,
  IpResultsService,
  type LineageEdgePublic,
  type LineageEvidenceReferencesPublic,
  type LineageObservationReferencesPublic,
} from "@/client"
import { ReportDetailDialog } from "@/components/GovernanceReports"
import { useLocale } from "@/components/LocaleProvider"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

type LineageNode = GovernanceRunLineagePublic["nodes"][number]
type LineageSearch = { resource_id?: string }
type ReaderLocale = "zh" | "en"
const LineageLocaleContext = createContext<ReaderLocale>("en")
type Localize = (chinese: string, english: string) => string
const chineseFieldLabels: Record<string, string> = {
  "Source type": "来源类型", "Pinned state": "固定状态", "Input ID": "输入 ID", "Snapshot ID": "快照 ID", "Content SHA-256": "内容 SHA-256", "Schema fingerprint": "模式指纹", "Method fingerprint": "方法指纹", "Record count": "记录数", "Valid time start (UTC)": "有效时间开始（UTC）", "Valid time end (UTC)": "有效时间结束（UTC）", "Meaning": "含义", "Run ID": "运行 ID", "Processing contract": "处理合同", "Comparison contract": "比较合同", "Report contract": "报告合同", "Resource ID": "资源 ID", "CustomerUpload presence": "客户资产表存在性", "CloudAtlas presence": "CloudAtlas 存在性", "Classification": "分类", "Classification reason": "分类原因", "NetFlow status": "NetFlow 状态", "NetFlow reason": "NetFlow 原因", "Content hash": "内容哈希", "Comparison fact ID": "比较事实 ID", "Finding ID": "发现 ID", "Finding type": "发现类型", "This Run occurrence ID": "本次运行事件 ID", "This Run transition ID": "本次运行变更 ID", "Transition type": "变更类型", "Snapshot references": "快照引用", "Report ID": "报告 ID", "Generation mode": "生成模式", "HTML SHA-256": "HTML SHA-256", "CSV SHA-256": "CSV SHA-256", "Summary scope": "摘要范围", "Run total comparisons": "运行比较结果总数", "Run total Finding events": "运行发现事件总数", "Comparison coverage": "比较结果覆盖范围", "Finding coverage": "发现事件覆盖范围", "Truncated": "是否截断", "Projection version": "投影版本", "Input contract": "输入合同", "Comparison output hash": "比较输出哈希", "IP": "IP", "customer_observed_asset_count": "客户侧观测资产数", "cloudatlas_observed_asset_count": "CloudAtlas 侧观测资产数", "matched_asset_count": "匹配资产数", "current_run_finding_count": "本次运行发现项数", "current_run_transition_count": "本次运行变更数", "open_backlog_count": "开放待处理项数",
}
const chineseEdges: Record<LineageEdgePublic["kind"], string> = {
 SOURCE_SNAPSHOT: "固定输入来源及其快照。",
 SNAPSHOT_PROCESS: "批次上下文；不证明每条判断都使用了该来源。",
 ABSENT_SOURCE_PROCESS: "未提供此输入；不表示存在正向数据输入。",
 PROCESS_COMPARISON: "本次运行的处理合同下生成的比较结果。",
 PROCESS_FINDING: "本次运行的处理合同下产生的发现事件。",
 PROCESS_REPORT: "处理合同下的已发布报告。",
 COMPARISON_REPORT_CONTEXT: "比较结果与报告上下文的关联；不证明因果或证据已纳入。",
 FINDING_REPORT_CONTEXT: "发现事件与报告上下文的关联；不证明因果或证据已纳入。",
}

const GROUPS = [
  { kind: "SOURCE", title: "Sources" },
  { kind: "SNAPSHOT", title: "Snapshots" },
  { kind: "PROCESS", title: "Processing contract" },
  { kind: "COMPARISON", title: "Results: Comparisons" },
  { kind: "FINDING", title: "Results: Finding events" },
  { kind: "REPORT", title: "Report" },
] as const
const EDGE_STYLES: Record<
  LineageEdgePublic["kind"],
  { dash: string; meaning: string }
> = {
  SOURCE_SNAPSHOT: { dash: "none", meaning: "Pinned source and snapshot" },
  SNAPSHOT_PROCESS: {
    dash: "12 3",
    meaning: "Batch context; not proof that every judgment used this source",
  },
  ABSENT_SOURCE_PROCESS: {
    dash: "2 6",
    meaning: "Input not provided; not positive data input",
  },
  PROCESS_COMPARISON: {
    dash: "8 3",
    meaning: "Comparison under this Run's processing contract",
  },
  PROCESS_FINDING: {
    dash: "8 3 2 3",
    meaning: "This Run's Finding event under the processing contract",
  },
  PROCESS_REPORT: {
    dash: "16 4",
    meaning: "Published report under the processing contract",
  },
  COMPARISON_REPORT_CONTEXT: {
    dash: "3 3",
    meaning:
      "Report context: association, not causation or proof of Evidence inclusion",
  },
  FINDING_REPORT_CONTEXT: {
    dash: "3 3 10 3",
    meaning:
      "Report context: association, not causation or proof of Evidence inclusion",
  },
}

export const Route = createFileRoute(
  "/_layout/projects/$projectId/runs/$runId/lineage",
)({
  component: RunLineage,
  validateSearch: (search: Record<string, unknown>): LineageSearch => ({
    resource_id:
      search.resource_id === undefined
        ? undefined
        : typeof search.resource_id === "string"
          ? search.resource_id
          : "",
  }),
  head: () => ({ meta: [{ title: "Run lineage - Exposure Agent" }] }),
})

function nodeIdentifier(node: LineageNode): string {
  switch (node.kind) {
    case "SOURCE":
      return node.source_type
    case "SNAPSHOT":
      return node.snapshot_id
    case "PROCESS":
      return node.governance_run_id
    case "COMPARISON":
      return node.canonical_ip
    case "FINDING":
      return `${node.canonical_ip} · ${node.finding_id}`
    case "REPORT":
      return node.governance_report_id
  }
}

function groupTitle(kind: LineageNode["kind"], text: Localize) {
  const titles: Record<LineageNode["kind"], [string, string]> = {
    SOURCE: ["来源", "Sources"],
    SNAPSHOT: ["快照", "Snapshots"],
    PROCESS: ["处理契约", "Processing contract"],
    COMPARISON: ["结果：比较", "Results: Comparisons"],
    FINDING: ["结果：发现事件", "Results: Finding events"],
    REPORT: ["报告", "Report"],
  }
  return text(...titles[kind])
}

function nodeKindLabel(kind: LineageNode["kind"], text: Localize) {
  const labels: Record<LineageNode["kind"], [string, string]> = {
    SOURCE: ["来源", "SOURCE"],
    SNAPSHOT: ["快照", "SNAPSHOT"],
    PROCESS: ["处理契约", "PROCESS"],
    COMPARISON: ["比较结果", "COMPARISON"],
    FINDING: ["发现事件", "FINDING"],
    REPORT: ["报告", "REPORT"],
  }
  return text(...labels[kind])
}

function RunLineage() {
  const { text } = useLocale()
  const { projectId, runId } = Route.useParams()
  const { resource_id: resourceId } = Route.useSearch()
  const scope = JSON.stringify([projectId, runId, resourceId])
  const heading = useRef<HTMLHeadingElement>(null)
  const previousScope = useRef(scope)
  useEffect(() => {
    if (previousScope.current !== scope) {
      heading.current?.focus()
      previousScope.current = scope
    }
  }, [scope])
  useEffect(() => {
    document.title = text("运行血缘 - Exposure Agent", "Run lineage - Exposure Agent")
  }, [text])

  return (
    <div className="min-w-0 max-w-full space-y-6 overflow-hidden">
      <header className="space-y-2">
        <h1
          ref={heading}
          tabIndex={-1}
          className="text-2xl font-bold tracking-tight focus-visible:outline-2 focus-visible:outline-ring"
        >
          {text("运行血缘", "Run lineage")}
        </h1>
        <p className="break-all text-sm">{text("项目 ID：", "Project ID: ")}{projectId}</p>
        <p className="break-all text-sm">{text("运行 ID：", "Run ID: ")}{runId}</p>
        <p className="break-all font-medium">
          {resourceId === undefined
            ? text("总览", "Overview")
            : text(`单个资源：${resourceId}`, `Single resource: ${resourceId}`)}
        </p>
        <p className="text-sm text-muted-foreground">
          {text(
            "展示此明确历史治理运行的已发布事实，而非最新运行或当前输入。",
            "Published facts for this explicit historical Run, not the latest Run or current inputs.",
          )}
        </p>
        <nav
          aria-label={text("血缘导航", "Lineage navigation")}
          className="flex flex-wrap gap-4 text-sm"
        >
          <Link
            to="/projects/$projectId/runs/$runId/comparison"
            params={{ projectId, runId }}
            search={{}}
            className="underline underline-offset-4"
          >
            {text("查看来源比较", "View source comparison")}
          </Link>
          {resourceId !== undefined && (
            <Link
              to="/projects/$projectId/runs/$runId/lineage"
              params={{ projectId, runId }}
              search={{}}
              className="underline underline-offset-4"
            >
              {text("返回总览", "Back to overview")}
            </Link>
          )}
        </nav>
      </header>
      <LineageScope
        key={scope}
        projectId={projectId}
        runId={runId}
        resourceId={resourceId}
      />
    </div>
  )
}

export function LineageScope({
  projectId,
  runId,
  resourceId,
  readerMode = false,
  readerLocale: _readerLocale = "en",
}: {
  projectId: string
  runId: string
  resourceId?: string
  readerMode?: boolean
  readerLocale?: ReaderLocale
}) {
  const { locale, text } = useLocale()
  const invalidResource = resourceId !== undefined && resourceId.trim() === ""
  const query = useQuery({
    queryKey: ["governance-run-lineage", projectId, runId, resourceId],
    queryFn: () =>
      IpResultsService.readGovernanceRunLineage({
        projectId,
        governanceRunId: runId,
        resourceId,
      }),
    enabled: !invalidResource,
    retry: false,
  })
  const data = query.data
  const identityMismatch =
    data &&
    (data.project_id !== projectId ||
      data.governance_run_id !== runId ||
      data.view !== (resourceId === undefined ? "OVERVIEW" : "RESOURCE") ||
      data.resource_id !== (resourceId ?? null) ||
      data.nodes.some(
        (node) =>
          (node.kind === "PROCESS" &&
            (node.governance_run_id !== runId ||
              node.report_contract_version !== data.report_contract_version ||
              node.processing_contract_version !==
                data.processing_contract_version)) ||
          (node.kind === "REPORT" &&
            (node.governance_report_id !== data.governance_report_id ||
              node.report_contract_version !== data.report_contract_version)) ||
          (resourceId !== undefined &&
            (node.kind === "COMPARISON" || node.kind === "FINDING") &&
            node.resource_id !== resourceId) ||
          ("evidence" in node &&
            node.evidence.data.some(
              (reference) => reference.governance_run_id !== runId,
            )),
      ))
  const status =
    query.error instanceof ApiError ? query.error.status : undefined
  if (invalidResource || query.error || identityMismatch) {
    const invalid = invalidResource || status === 422
    return (
      <Alert variant="destructive">
        <AlertTitle className="line-clamp-none">
          {identityMismatch
            ? text("运行血缘身份不匹配", "Run lineage identity mismatch")
            : invalid
              ? text("血缘参数无效", "Invalid lineage parameters")
              : status === 404
                ? text("已发布血缘不可用", "Published lineage unavailable")
                : text("运行血缘请求失败", "Run lineage request failed")}
        </AlertTitle>
        <AlertDescription>
          <p>
            {identityMismatch
              ? text("响应与请求的项目、治理运行、资源范围或报告契约不一致，因此不显示血缘事实。", "The response does not match the requested Project, Run, resource scope and Report contract. No lineage facts are displayed.")
              : invalid
                ? text("请求参数无效；资源范围未被替换为总览。", "The requested parameters are invalid. The resource scope has not been replaced with an overview.")
                : status === 404
                  ? text("此治理运行或资源的已发布血缘不可用。", "Published lineage for this Run or resource is unavailable.")
                  : text("无法加载已发布事实，请重试。", "The published facts could not be loaded. Please try again.")}
          </p>
          <p>
            {text("请求失败不等于空图、ABSENT 来源或 UNKNOWN 结果。", "A failed request is not an empty graph, an ABSENT source or an UNKNOWN result.")}
          </p>
          {!invalid && status !== 404 && (
            <Button
              type="button"
              variant="outline"
              onClick={() => void query.refetch()}
            >
              {text("重试", "Try again")}
            </Button>
          )}
        </AlertDescription>
      </Alert>
    )
  }
  if (!data) return <p role="status">{text("正在加载运行血缘…", "Loading Run lineage…")}</p>
  return <PublishedLineage
    data={data}
    readerMode={readerMode}
    readerLocale={locale === "zh" ? "zh" : "en"}
  />
}

// Traverse each direction independently: an upstream Process must never open a sibling result branch.
function directedPaths(
  edges: LineageEdgePublic[],
  selected: string,
  direction: "upstream" | "downstream",
) {
  const reached = new Set([selected])
  const path = new Set<string>()
  const pending = [selected]
  for (let index = 0; index < pending.length; index++) {
    const key = pending[index]
    for (const edge of edges) {
      const from = direction === "upstream" ? edge.to : edge.from
      const to = direction === "upstream" ? edge.from : edge.to
      if (from !== key) continue
      path.add(edge.key)
      if (!reached.has(to)) {
        reached.add(to)
        pending.push(to)
      }
    }
  }
  reached.delete(selected)
  return { reached, path }
}

// Reader mode keeps the route's full projection semantics while changing only the
// desktop arrangement: accessible node directory, bounded graph, then detail pane.
function ReaderPublishedLineage({ data, locale }: { data: GovernanceRunLineagePublic; locale: ReaderLocale }) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [reportOpen, setReportOpen] = useState(false)
  const [zoom, setZoom] = useState(1)
  const canvas = useRef<HTMLElement>(null)
  const reportTrigger = useRef<HTMLButtonElement | null>(null)
  const clearButton = useRef<HTMLButtonElement>(null)
  const nodeButtons = useRef(new Map<string, HTMLButtonElement>())
  const selected = data.nodes.find((node) => node.key === selectedKey)
  const upstream = directedPaths(data.edges, selected?.key ?? "", "upstream")
  const downstream = directedPaths(data.edges, selected?.key ?? "", "downstream")
  const highlightedEdges = new Set([...upstream.path, ...downstream.path])
  const nodes = new Map(data.nodes.map((node) => [node.key, node]))
  const grouped = GROUPS.map((group) => ({
    ...group,
    nodes: data.nodes.filter((node) => node.kind === group.kind),
  }))
  const positions = new Map(
    grouped.flatMap((group, column) =>
      group.nodes.map(
        (node, row) =>
          [node.key, { x: 30 + column * 240, y: 65 + row * 90 }] as const,
      ),
    ),
  )
  const graphHeight = Math.max(240, ...grouped.map((group) => group.nodes.length * 90 + 80))
  const openReport = (trigger: HTMLButtonElement) => {
    reportTrigger.current = trigger
    setReportOpen(true)
  }
  const select = (key: string) => setSelectedKey(key)
  const zh = locale === "zh"
  const kind = (value: LineageNode["kind"]) => zh ? ({ SOURCE: "来源", SNAPSHOT: "快照", PROCESS: "处理合同", COMPARISON: "比较结果", FINDING: "发现事件", REPORT: "报告" }[value]) : value
  return <LineageLocaleContext.Provider value={locale}><>
    <section aria-label={zh ? "血缘范围与覆盖情况" : "Lineage scope and coverage"} className="mb-4 min-w-0 space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-center gap-2"><Badge variant="secondary">{data.status}</Badge><span className="text-sm">{data.run_status} · {data.report_contract_version}</span></div>
      <p className="text-sm">{data.status === "PARTIAL" ? (zh ? "这是有界、截断的投影；不表示发布失败，也不评价 NetFlow 质量。" : "Bounded, truncated projection; not a publication failure or NetFlow quality judgment.") : data.status === "EMPTY" ? (zh ? "此范围没有可展示的比较结果或发现事件；来源、处理合同和报告仍可用。这不表示没有资产、流量或风险。" : "This scope has no displayable Comparisons or Finding events; sources, processing contract and report remain available. This does not mean no assets, traffic or risk.") : (zh ? "此投影未截断；这不证明输入覆盖完整或风险为零。" : "This projection is not truncated; this does not prove complete input coverage or zero risk.")}</p>
      <dl className="grid grid-cols-2 gap-2 text-sm md:grid-cols-5 [&_dt]:font-medium [&_dd]:break-all"><Field label="Run total comparisons">{data.totals.comparison_count}</Field><Field label="Run total Finding events">{data.totals.finding_event_count}</Field><Field label="Comparison coverage">{data.coverage.comparison_returned} / {data.coverage.comparison_count}</Field><Field label="Finding coverage">{data.coverage.finding_returned} / {data.coverage.finding_event_count}</Field><Field label="Truncated">{zh ? (data.truncated ? "是" : "否") : String(data.truncated)}</Field></dl>
      {data.truncation_reasons.length > 0 && <p className="text-sm text-muted-foreground">{zh ? "截断原因：" : "Truncation reasons: "}{data.truncation_reasons.join(", ")}</p>}
      <details className="text-sm"><summary className="cursor-pointer font-medium">{zh ? "投影合同与哈希" : "Projection contracts and hash"}</summary><dl className="mt-2 grid gap-2 sm:grid-cols-2"><Field label="Projection version">{data.projection_version}</Field><Field label="Input contract">{data.input_contract_version}</Field><Field label="Processing contract">{data.processing_contract_version}</Field><Field label="Comparison output hash">{data.comparison_output_hash}</Field></dl></details>
      <details className="text-sm"><summary className="cursor-pointer font-medium">{zh ? "关系图例" : "Relationship legend"}</summary><ul className="mt-2 space-y-2 text-xs">{Object.entries(EDGE_STYLES).map(([edge, style]) => <li key={edge}><svg aria-hidden="true" width="48" height="14" className="mr-2 inline-block"><line x1="0" y1="7" x2="48" y2="7" stroke="currentColor" strokeWidth="2" strokeDasharray={style.dash} /></svg><strong>{edge}</strong>: {zh ? chineseEdges[edge as LineageEdgePublic["kind"]] : style.meaning}</li>)}</ul></details>
    </section>
    <div className="grid min-w-0 items-start gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(17rem,.75fr)]">
      <details className="min-w-0 rounded-lg border p-3 lg:col-span-2">
        <summary className="cursor-pointer font-semibold">{zh ? "血缘节点" : "Lineage nodes"} ({data.nodes.length})</summary>
        <p className="mt-2 text-xs text-muted-foreground">{zh ? "选择节点以查看已发布事实和有向关联。" : "Select a node to read its facts and directed associations."}</p>
        <Button ref={clearButton} type="button" variant="outline" size="sm" className="mt-3" onClick={() => { setSelectedKey(null); clearButton.current?.focus() }}>{zh ? "清除选择" : "Clear selection"}</Button>
        <div className="mt-3 max-h-[58vh] space-y-3 overflow-y-auto pr-1">{grouped.map((group) => <section key={group.kind}><h3 className="text-sm font-semibold">{zh ? ({ SOURCE: "来源", SNAPSHOT: "快照", PROCESS: "处理合同", COMPARISON: "比较结果", FINDING: "发现事件", REPORT: "报告" }[group.kind]) : group.title}</h3><ul className="mt-1 space-y-1">{group.nodes.map((node) => <li key={node.key}><button ref={(button) => { if (button) nodeButtons.current.set(node.key, button); else nodeButtons.current.delete(node.key) }} type="button" aria-pressed={selected?.key === node.key} onClick={() => select(node.key)} className="w-full rounded-md border px-2 py-1.5 text-left text-xs focus-visible:outline-2 focus-visible:outline-ring aria-pressed:border-foreground aria-pressed:bg-muted"><span className="block font-medium">{kind(node.kind)}</span><span className="block break-all">{nodeIdentifier(node)}</span></button></li>)}</ul></section>)}</div>
      </details>
      <section ref={canvas} aria-label={zh ? "血缘图" : "Lineage graph"} tabIndex={0} className="max-h-[68vh] min-w-0 overflow-auto rounded-lg border focus-visible:outline-2 focus-visible:outline-ring">
        <div className="sticky left-0 top-0 z-10 flex justify-end gap-2 border-b bg-background/95 p-2"><Button type="button" size="sm" variant="outline" onClick={() => setZoom(Math.max(.15, Math.min(1, ((canvas.current?.clientWidth ?? 1470) - 4) / 1470)))}>{zh ? "适配宽度" : "Fit width"}</Button><Button type="button" size="sm" variant="outline" onClick={() => setZoom(1)}>100%</Button><Button type="button" size="sm" variant="outline" onClick={() => setZoom(1.2)}>120%</Button></div>
        <svg aria-hidden="true" width={1470 * zoom} height={graphHeight * zoom} className="text-foreground"><g transform={`scale(${zoom})`}>{grouped.map((group, column) => <text key={group.kind} x={30 + column * 240} y="28" fill="currentColor" fontSize="14">{zh ? ({ SOURCE: "来源", SNAPSHOT: "快照", PROCESS: "处理合同", COMPARISON: "比较结果", FINDING: "发现事件", REPORT: "报告" }[group.kind]) : group.title}</text>)}{data.edges.map((edge) => { const start = positions.get(edge.from); const end = positions.get(edge.to); if (!start || !end) return null; const active = highlightedEdges.has(edge.key); const x1 = start.x + 195; const y1 = start.y + 26; const x2 = end.x; const y2 = end.y + 26; const line = end.x - start.x > 240 ? `M ${x1} ${y1} H ${x1 + 12} V 45 H ${x2 - 12} V ${y2} H ${x2}` : `M ${x1} ${y1} C ${x1 + 30} ${y1}, ${x2 - 30} ${y2}, ${x2} ${y2}`; return <g key={edge.key} opacity={selected && !active ? .3 : 1}><path d={line} fill="none" stroke="currentColor" strokeWidth={active ? 4 : 1.5} strokeDasharray={EDGE_STYLES[edge.kind].dash} /><path d={`M ${x2 - 7} ${y2 - 4} L ${x2} ${y2} L ${x2 - 7} ${y2 + 4}`} fill="none" stroke="currentColor" strokeWidth={active ? 3 : 1.5} /></g> })}{data.nodes.map((node) => { const position = positions.get(node.key); if (!position) return null; const active = node.key === selected?.key || upstream.reached.has(node.key) || downstream.reached.has(node.key); return <foreignObject key={node.key} x={position.x} y={position.y} width="195" height="54" opacity={selected && !active ? .4 : 1}><button type="button" tabIndex={-1} aria-label={`${kind(node.kind)} ${nodeIdentifier(node)}`} className={`h-full w-full rounded-md border-foreground bg-background px-2 text-left text-xs ${node.key === selected?.key ? "border-4" : active ? "border-2" : "border"}`} onClick={() => select(node.key)}><span className="block">{kind(node.kind)}</span><span className="block truncate text-[11px]">{nodeIdentifier(node)}</span></button></foreignObject> })}</g></svg>
      </section>
      <aside tabIndex={0} aria-label={zh ? "节点与路径详情" : "Node and path details"} className="min-w-0 space-y-4 lg:sticky lg:top-4 lg:max-h-[68vh] lg:overflow-y-auto lg:pr-1">
        {selected ? <><section aria-label={zh ? "节点详情" : "Node details"} className="min-w-0 space-y-3 rounded-lg border p-4"><h2 className="text-xl font-semibold">{zh ? "节点详情" : "Node details"}</h2><h3 className="break-all font-medium">{kind(selected.kind)} {nodeIdentifier(selected)}</h3><NodeDetails node={selected} openReport={openReport} /></section><section aria-label={zh ? "已选路径" : "Selected paths"} className="min-w-0 space-y-3 rounded-lg border p-4"><h2 className="text-xl font-semibold">{zh ? "已选路径" : "Selected paths"}</h2><p className="text-sm">{zh ? "仅显示有向上游和下游关联；报告上下文不表示因果或证据纳入证明。" : "Directed upstream and downstream associations only; report context is not causation or proof of Evidence inclusion."}</p>{[{ title: zh ? "上游关联" : "Upstream associations", path: upstream.path }, { title: zh ? "下游关联" : "Downstream associations", path: downstream.path }].map(({ title, path }) => <section key={title} aria-label={title}><h3 className="font-semibold">{title}</h3>{path.size === 0 ? <p className="text-sm">{zh ? "此方向没有已返回的关联。" : "No returned associations in this direction."}</p> : <ul className="list-inside list-disc space-y-2 text-sm">{data.edges.filter((edge) => path.has(edge.key)).map((edge) => { const from = nodes.get(edge.from); const to = nodes.get(edge.to); return <li key={edge.key} className="break-all"><strong>{edge.kind}</strong>: {from ? `${kind(from.kind)} ${nodeIdentifier(from)}` : edge.from} → {to ? `${kind(to.kind)} ${nodeIdentifier(to)}` : edge.to}. {zh ? chineseEdges[edge.kind] : EDGE_STYLES[edge.kind].meaning}</li> })}</ul>}</section>)}</section></> : <section className="rounded-lg border p-4 text-sm text-muted-foreground">{zh ? "尚未选择节点。请选择图或目录中的节点以阅读已发布详情。" : "No node selected. Select a graph or directory node to read its published details."}</section>}
      </aside>
    </div>
    {reportOpen && <ReportDetailDialog projectId={data.project_id} reportId={data.governance_report_id} expectedRunId={data.governance_run_id} expectedReportContractVersion={data.report_contract_version} onOpenChange={setReportOpen} onCloseAutoFocus={(event) => { event.preventDefault(); if (reportTrigger.current?.isConnected) reportTrigger.current.focus(); else clearButton.current?.focus() }} />}
  </></LineageLocaleContext.Provider>
}

function PublishedLineage({
  data,
  readerMode = false,
  readerLocale: _readerLocale = "en",
}: {
  data: GovernanceRunLineagePublic
  readerMode?: boolean
  readerLocale?: ReaderLocale
}) {
  const { locale, text } = useLocale()
  const zh = locale === "zh"
  if (readerMode) {
    return <ReaderPublishedLineage data={data} locale={zh ? "zh" : "en"} />
  }
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [reportOpen, setReportOpen] = useState(false)
  const reportTrigger = useRef<HTMLButtonElement | null>(null)
  const clearButton = useRef<HTMLButtonElement>(null)
  const nodeButtons = useRef(new Map<string, HTMLButtonElement>())
  const selected = data.nodes.find((node) => node.key === selectedKey)
  const upstream = directedPaths(data.edges, selected?.key ?? "", "upstream")
  const downstream = directedPaths(
    data.edges,
    selected?.key ?? "",
    "downstream",
  )
  const highlightedEdges = new Set([...upstream.path, ...downstream.path])
  const nodes = new Map(data.nodes.map((node) => [node.key, node]))
  const grouped = GROUPS.map((group) => ({
    ...group,
    nodes: data.nodes.filter((node) => node.kind === group.kind),
  }))
  const positions = new Map(
    grouped.flatMap((group, column) =>
      group.nodes.map(
        (node, row) =>
          [node.key, { x: 30 + column * 240, y: 65 + row * 90 }] as const,
      ),
    ),
  )
  const graphHeight = Math.max(
    240,
    ...grouped.map((group) => group.nodes.length * 90 + 80),
  )
  const openReport = (trigger: HTMLButtonElement) => {
    reportTrigger.current = trigger
    setReportOpen(true)
  }

  return (
    <LineageLocaleContext.Provider value={zh ? "zh" : "en"}>
      <>
      <section
        aria-label={text("血缘范围与覆盖情况", "Lineage scope and coverage")}
        className="min-w-0 space-y-3"
      >
        <p className="break-all text-sm">
          {text("报告 ID：", "Report ID: ")}{data.governance_report_id}
        </p>
        <p className="break-all text-sm">
          {data.run_status} · {text("完成于", "Completed")} {new Date(data.completed_at).toLocaleString(locale)} ·{" "}
          {data.report_contract_version}
        </p>
        <p role="status" className="text-sm">
          <Badge variant="secondary">{data.status}</Badge>{" "}
          {data.status === "EMPTY"
            ? text("此范围没有可展示的比较结果或发现事件；来源、处理契约和报告仍可用。这不表示没有资产、流量或风险。", "This scope has no displayable Comparisons or Finding events; sources, processing contract and report remain available. This does not mean no assets, traffic or risk.")
            : data.status === "PARTIAL"
              ? text("这是有界、截断的投影；不表示发布失败，也不评价 NetFlow 质量。", "Bounded, truncated projection; not a publication failure or NetFlow quality judgment.")
              : text("此投影未截断；这不证明输入覆盖完整或风险为零。", "This projection is not truncated; this does not prove complete input coverage or zero risk.")}
        </p>
        <dl className="grid gap-2 text-sm sm:grid-cols-2 [&_dt]:font-medium [&_dd]:break-all">
          <Field label="Run total comparisons">
            {data.totals.comparison_count}
          </Field>
          <Field label="Run total Finding events">
            {data.totals.finding_event_count}
          </Field>
          <Field label="Comparison coverage">
            {text(
              `${data.coverage.comparison_returned} / ${data.coverage.comparison_count} 已返回 / 范围总数`,
              `${data.coverage.comparison_returned} / ${data.coverage.comparison_count} returned / scope total`,
            )}
          </Field>
          <Field label="Finding event coverage">
            {text(
              `${data.coverage.finding_returned} / ${data.coverage.finding_event_count} 已返回 / 范围总数`,
              `${data.coverage.finding_returned} / ${data.coverage.finding_event_count} returned / scope total`,
            )}
          </Field>
          <Field label="Truncated">{zh ? (data.truncated ? "是" : "否") : String(data.truncated)}</Field>
        </dl>
        {data.truncation_reasons.length > 0 && (
          <div>
            <h2 className="font-medium">{text("截断原因", "Truncation reasons")}</h2>
            <ul className="list-inside list-disc break-all text-sm">
              {data.truncation_reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </div>
        )}
        <p className="text-sm text-muted-foreground">
          {text("总览最多返回 20 条比较结果和 20 条发现事件，两者独立选择，未必指向相同资产。每组引用最多返回 20 条。若要追溯总览以外的资源，请使用完整来源比较矩阵或缩小范围；这不承诺返回完整引用。", "Overview returns at most 20 Comparisons and 20 Finding events, selected independently; they need not identify the same assets. References return at most 20 per group. Use the full source comparison matrix to trace a resource outside this overview or narrow the scope; this does not promise complete references.")}
        </p>
        <p className="text-sm text-muted-foreground">
          {text("finding_event_count 统计本次运行中有事件的不同发现项，不统计发生记录、状态变更、历史待处理项或报告样本。", "finding_event_count counts distinct Findings with events in this Run, not occurrences, transitions, historical backlog or report samples.")}
        </p>
        <details className="text-sm">
          <summary className="cursor-pointer">
            {text("投影契约与哈希", "Projection contracts and hash")}
          </summary>
          <dl className="mt-2 space-y-2 [&_dd]:break-all [&_dt]:font-medium">
            <Field label="Projection version">{data.projection_version}</Field>
            <Field label="Input contract">{data.input_contract_version}</Field>
            <Field label="Processing contract">
              {data.processing_contract_version}
            </Field>
            <Field label="Comparison output hash">
              {data.comparison_output_hash}
            </Field>
          </dl>
        </details>
        {selected?.kind !== "REPORT" && (
          <Button
            type="button"
            onClick={(event) => openReport(event.currentTarget)}
          >
            {text("阅读报告", "Read report")}
          </Button>
        )}
      </section>

      <section aria-label={text("关联语义", "Association semantics")} className="space-y-3">
        <h2 className="text-xl font-semibold">
          {text("已发布关联，不代表因果", "Published associations, not causation")}
        </h2>
        <p className="font-medium">
          {text("路径表示已发布事实之间的关联，不能证明某一来源触发了发现项。", "Paths represent associations between published facts; they do not prove that a source triggered a Finding.")}
        </p>
        <p className="text-sm">
          {text("处理节点表示本次运行的处理契约，不是执行步骤或 DAG。比较结果与发现事件是并列结果，不存在比较结果 → 发现事件的连接。", "Process is this Run's processing contract, not execution steps or a DAG. Comparison and Finding are parallel results; there is no Comparison → Finding connection.")}
        </p>
        <p className="text-sm">
          {text("PRESENT 表示存在固定快照，包括记录数为 0 的快照。ABSENT 表示未提供输入。UNKNOWN 使用返回原因，不表示不存在、流量为零或风险为零。零证据表示没有对应的样本引用，不表示事实缺失、未纳入报告或没有风险。", "PRESENT means a pinned snapshot exists, including one with 0 records. ABSENT means input was not provided. UNKNOWN uses the returned reason and does not mean nonexistent, zero traffic or zero risk. Zero Evidence means no corresponding sample references, not missing facts, exclusion from the report or no risk.")}
        </p>
        <details open>
          <summary className="cursor-pointer font-medium">
            {text("边的语义与线条样式", "Edge semantics and line styles")}
          </summary>
          <ul className="mt-2 space-y-2 text-sm">
            {Object.entries(EDGE_STYLES).map(([kind, style]) => (
              <li key={kind} className="min-w-0 break-words">
                <svg
                  aria-hidden="true"
                  width="64"
                  height="16"
                  className="mr-2 inline-block"
                >
                  <line
                    x1="0"
                    y1="8"
                    x2="64"
                    y2="8"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeDasharray={style.dash}
                  />
                </svg>
                <strong className="break-all">{kind}</strong>: {zh ? chineseEdges[kind as LineageEdgePublic["kind"]] : style.meaning}
              </li>
            ))}
          </ul>
        </details>
      </section>

      <section
        aria-label={text("血缘图", "Lineage graph")}
        // biome-ignore lint/a11y/noNoninteractiveTabindex: Keyboard users need to scroll this visual graph; equivalent nodes and paths follow in the DOM.
        tabIndex={0}
        className="max-h-[60vh] max-w-full overflow-auto rounded-lg border focus-visible:outline-2 focus-visible:outline-ring"
      >
        <svg
          aria-hidden="true"
          width="1470"
          height={graphHeight}
          className="text-foreground"
        >
          {grouped.map((group, column) => (
            <text
              key={group.kind}
              x={30 + column * 240}
              y="28"
              fill="currentColor"
              fontSize="14"
            >
              {groupTitle(group.kind, text)}
            </text>
          ))}
          {data.edges.map((edge) => {
            const start = positions.get(edge.from)
            const end = positions.get(edge.to)
            if (!start || !end) return null
            const active = highlightedEdges.has(edge.key)
            const x1 = start.x + 195
            const y1 = start.y + 26
            const x2 = end.x
            const y2 = end.y + 26
            // Skip intervening result columns without drawing through sibling nodes.
            const line =
              end.x - start.x > 240
                ? `M ${x1} ${y1} H ${x1 + 12} V 45 H ${x2 - 12} V ${y2} H ${x2}`
                : `M ${x1} ${y1} C ${x1 + 30} ${y1}, ${x2 - 30} ${y2}, ${x2} ${y2}`
            return (
              <g key={edge.key} opacity={selected && !active ? 0.3 : 1}>
                <path
                  d={line}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={active ? 4 : 1.5}
                  strokeDasharray={EDGE_STYLES[edge.kind].dash}
                />
                <path
                  d={`M ${x2 - 7} ${y2 - 4} L ${x2} ${y2} L ${x2 - 7} ${y2 + 4}`}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={active ? 3 : 1.5}
                />
              </g>
            )
          })}
          {data.nodes.map((node) => {
            const position = positions.get(node.key)
            if (!position) return null
            const active =
              node.key === selected?.key ||
              upstream.reached.has(node.key) ||
              downstream.reached.has(node.key)
            const label = nodeIdentifier(node)
            return (
              <foreignObject
                key={node.key}
                x={position.x}
                y={position.y}
                width="195"
                height="54"
                opacity={selected && !active ? 0.4 : 1}
              >
                <button
                  type="button"
                  tabIndex={-1}
                  aria-label={`${nodeKindLabel(node.kind, text)} ${label}`}
                  className={`h-full w-full cursor-pointer rounded-md border-foreground bg-background px-2 text-left text-xs ${node.key === selected?.key ? "border-4" : active ? "border-2" : "border"}`}
                  onClick={() => {
                    setSelectedKey(node.key)
                    nodeButtons.current.get(node.key)?.focus()
                  }}
                >
                  <span className="block">
                    {nodeKindLabel(node.kind, text)}
                    {node.key === selected?.key
                      ? text(" · 已选择", " · Selected")
                      : active
                        ? text(" · 路径", " · Path")
                        : ""}
                  </span>
                  <span className="block truncate text-[11px]">{label}</span>
                </button>
              </foreignObject>
            )
          })}
        </svg>
      </section>

      <div className="grid min-w-0 items-start gap-6 lg:grid-cols-2">
        <section aria-label={text("血缘节点", "Lineage nodes")} className="min-w-0 space-y-3">
          <h2 className="text-xl font-semibold">{text("血缘节点", "Lineage nodes")}</h2>
          <p className="text-sm text-muted-foreground">
            {text("选择节点以阅读其事实和有向上游/下游关联。可使用 Tab 或 Shift+Tab 导航，按 Enter 或空格选择。", "Select a node to read its facts and directed upstream/downstream associations. Tab or Shift+Tab navigates; Enter or Space selects.")}
          </p>
          <Button
            ref={clearButton}
            type="button"
            variant="outline"
            onClick={() => {
              setSelectedKey(null)
              clearButton.current?.focus()
            }}
          >
            {text("清除选择", "Clear selection")}
          </Button>
          <p role="status" className="text-sm">
            {selected
              ? text(`已选择 ${nodeKindLabel(selected.kind, text)} ${nodeIdentifier(selected)}`, `Selected ${nodeKindLabel(selected.kind, text)} ${nodeIdentifier(selected)}`)
              : text("尚未选择节点", "No node selected")}
          </p>
          <div className="grid min-w-0 gap-4 md:grid-cols-2">
            {grouped.map((group) => (
              <section
                key={group.kind}
                aria-label={groupTitle(group.kind, text)}
                className="min-w-0 space-y-2"
              >
                <h3 className="font-semibold">{groupTitle(group.kind, text)}</h3>
                <ul className="space-y-2">
                  {group.nodes.map((node) => (
                    <li key={node.key} className="min-w-0">
                      <button
                        ref={(button) => {
                          if (button) nodeButtons.current.set(node.key, button)
                          else nodeButtons.current.delete(node.key)
                        }}
                        type="button"
                        aria-pressed={selected?.key === node.key}
                        aria-label={`${nodeKindLabel(node.kind, text)} ${nodeIdentifier(node)}`}
                        onClick={() => setSelectedKey(node.key)}
                        className="w-full min-w-0 rounded-md border p-3 text-left text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring aria-pressed:border-foreground aria-pressed:bg-muted"
                      >
                        <span className="block font-semibold">
                          {nodeKindLabel(node.kind, text)}
                          {selected?.key === node.key
                            ? text(" · 已选择", " · Selected")
                            : upstream.reached.has(node.key)
                              ? text(" · 上游", " · Upstream")
                              : downstream.reached.has(node.key)
                                ? text(" · 下游", " · Downstream")
                                : ""}
                        </span>
                        <span className="block break-all">
                          {nodeIdentifier(node)}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </section>

        {selected && (
          <div className="min-w-0 space-y-4 lg:sticky lg:top-4">
            <section
              aria-label={text("节点详情", "Node details")}
              className="min-w-0 space-y-3 rounded-lg border p-4"
            >
              <h2 className="text-xl font-semibold">{text("节点详情", "Node details")}</h2>
              <h3 className="break-all font-medium">
                {nodeKindLabel(selected.kind, text)} {nodeIdentifier(selected)}
              </h3>
              <NodeDetails node={selected} openReport={openReport} />
            </section>
            <section
              aria-label={text("已选路径", "Selected paths")}
              className="min-w-0 space-y-3 rounded-lg border p-4"
            >
              <h2 className="text-xl font-semibold">{text("已选路径", "Selected paths")}</h2>
              <p className="text-sm">
                {text("仅显示有向上游和下游关联；报告上下文不表示因果或证据纳入证明。", "Directed upstream and downstream associations only; report context is not causation or proof of Evidence inclusion.")}
              </p>
              {[
                { title: text("上游关联", "Upstream associations"), path: upstream.path },
                { title: text("下游关联", "Downstream associations"), path: downstream.path },
              ].map(({ title, path }) => (
                <section key={title} aria-label={title}>
                  <h3 className="font-semibold">{title}</h3>
                  {path.size === 0 ? (
                    <p className="text-sm">
                      {text("此方向没有已返回的关联。", "No returned associations in this direction.")}
                    </p>
                  ) : (
                    <ul className="list-inside list-disc space-y-2 text-sm">
                      {data.edges
                        .filter((edge) => path.has(edge.key))
                        .map((edge) => {
                          const from = nodes.get(edge.from)
                          const to = nodes.get(edge.to)
                          return (
                            <li key={edge.key} className="break-all">
                              <strong>{edge.kind}</strong>:{" "}
                              {from
                                ? `${nodeKindLabel(from.kind, text)} ${nodeIdentifier(from)}`
                                : edge.from}{" "}
                              →{" "}
                              {to
                                ? `${nodeKindLabel(to.kind, text)} ${nodeIdentifier(to)}`
                                : edge.to}
                              . {zh ? chineseEdges[edge.kind] : EDGE_STYLES[edge.kind].meaning}
                            </li>
                          )
                        })}
                    </ul>
                  )}
                </section>
              ))}
            </section>
          </div>
        )}
      </div>

      {reportOpen && (
        <ReportDetailDialog
          projectId={data.project_id}
          reportId={data.governance_report_id}
          expectedRunId={data.governance_run_id}
          expectedReportContractVersion={data.report_contract_version}
          onOpenChange={setReportOpen}
          onCloseAutoFocus={(event) => {
            event.preventDefault()
            if (reportTrigger.current?.isConnected)
              reportTrigger.current.focus()
            else clearButton.current?.focus()
          }}
        />
      )}
      </>
    </LineageLocaleContext.Provider>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  const locale = useContext(LineageLocaleContext)
  return (
    <div className="min-w-0">
      <dt>{locale === "zh" ? (chineseFieldLabels[label] ?? label) : label}</dt>
      <dd className="select-text">{children}</dd>
    </div>
  )
}

function ObservationReferences({
  references,
}: {
  references: LineageObservationReferencesPublic
}) {
  const locale = useContext(LineageLocaleContext)
  const text: Localize = (chinese, english) => (locale === "zh" ? chinese : english)
  return (
    <section aria-label={text("观测引用", "Observation references")} className="space-y-2 text-sm">
      <h3 className="font-semibold">{text("观测引用", "Observation references")}</h3>
      <p>
        {text(`数量：${references.count} · 已返回：${references.data.length} · 已截断：${references.truncated ? "是" : "否"}`, `Count: ${references.count} · Returned: ${references.data.length} · Truncated: ${String(references.truncated)}`)}
      </p>
      {references.data.length === 0 ? (
        <p>{text("没有已返回的观测引用。", "No returned Observation references.")}</p>
      ) : (
        <ul className="space-y-2">
          {references.data.map((reference) => (
            <li key={reference.observation_id} className="break-all">
              {text("观测 ID：", "Observation ID: ")}{reference.observation_id} · {text("快照 ID：", "Snapshot ID: ")}
              {reference.source_snapshot_id}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function EvidenceReferences({
  references,
}: {
  references: LineageEvidenceReferencesPublic
}) {
  const locale = useContext(LineageLocaleContext)
  const text: Localize = (chinese, english) => (locale === "zh" ? chinese : english)
  return (
    <section aria-label={text("证据引用", "Evidence references")} className="space-y-2 text-sm">
      <h3 className="font-semibold">{text("证据引用", "Evidence references")}</h3>
      <p>
        {text(`数量：${references.count} · 已返回：${references.data.length} · 已截断：${references.truncated ? "是" : "否"}`, `Count: ${references.count} · Returned: ${references.data.length} · Truncated: ${String(references.truncated)}`)}
      </p>
      {references.data.length === 0 ? (
        <p>
          {text("没有已返回的证据样本引用。这不表示事实缺失、未纳入报告或没有风险。", "No returned Evidence sample references. This does not imply missing facts, exclusion from the report or no risk.")}
        </p>
      ) : (
        <ul className="space-y-2">
          {references.data.map((reference) => (
            <li key={reference.id} className="break-all">
              {text("证据 ID：", "Evidence ID: ")}{reference.id} · {text("运行 ID：", "Run ID: ")}
              {reference.governance_run_id} · {text("事实类型：", "Fact type: ")}{reference.fact_type} ·
              {text("事实 ID：", "Fact ID: ")}{reference.fact_id}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function NodeDetails({
  node,
  openReport,
}: {
  node: LineageNode
  openReport: (trigger: HTMLButtonElement) => void
}) {
  const locale = useContext(LineageLocaleContext)
  const text: Localize = (chinese, english) => (locale === "zh" ? chinese : english)
  let fields: ReactNode
  switch (node.kind) {
    case "SOURCE":
      fields = (
        <>
          <Field label="Source type">{node.source_type}</Field>
          <Field label="Pinned state">{node.state}</Field>
          <Field label="Input ID">{node.input_id ?? text("未提供", "Not provided")}</Field>
        </>
      )
      break
    case "SNAPSHOT":
      fields = (
        <>
          <Field label="Snapshot ID">{node.snapshot_id}</Field>
          <Field label="Source type">{node.source_type}</Field>
          <Field label="Content SHA-256">{node.content_sha256}</Field>
          <Field label="Schema fingerprint">{node.schema_fingerprint}</Field>
          <Field label="Method fingerprint">
            {node.method_fingerprint ?? text("未提供", "Not provided")}
          </Field>
          <Field label="Record count">{node.record_count}</Field>
          <Field label="Valid time start (UTC)">
            {node.valid_time_start_utc ?? text("未提供", "Not provided")}
          </Field>
          <Field label="Valid time end (UTC)">
            {node.valid_time_end_utc ?? text("未提供", "Not provided")}
          </Field>
        </>
      )
      break
    case "PROCESS":
      fields = (
        <>
          <Field label="Meaning">
            {text("本次运行的处理契约，不是执行步骤或 DAG。", "This Run's processing contract, not execution steps or a DAG")}
          </Field>
          <Field label="Run ID">{node.governance_run_id}</Field>
          <Field label="Processing contract">
            {node.processing_contract_version}
          </Field>
          <Field label="Comparison contract">
            {node.comparison_contract_version}
          </Field>
          <Field label="Report contract">{node.report_contract_version}</Field>
        </>
      )
      break
    case "COMPARISON":
      fields = (
        <>
          <Field label="IP">{node.canonical_ip}</Field>
          <Field label="Resource ID">{node.resource_id}</Field>
          <Field label="CustomerUpload presence">
            {node.customer_upload_present ? text("已观测", "Observed") : text("未观测", "Not observed")}
          </Field>
          <Field label="CloudAtlas presence">
            {node.cloudatlas_present ? text("已观测", "Observed") : text("未观测", "Not observed")}
          </Field>
          <Field label="Classification">{node.classification}</Field>
          <Field label="Classification reason">
            {node.classification_reason}
          </Field>
          <Field label="NetFlow status">{node.netflow_status}</Field>
          <Field label="NetFlow reason">{node.netflow_reason}</Field>
          <Field label="Content hash">{node.content_hash}</Field>
          <Field label="Comparison fact ID">
            {node.comparison_fact_id ??
              text("不适用：v1 比较结果是只读投影，不是持久化的比较事实。这不表示其报告中存在三来源比较章节。", "Not applicable: a v1 comparison is a read-only projection, not a persisted comparison fact. This does not claim a three-source comparison chapter in its report.")}
          </Field>
        </>
      )
      break
    case "FINDING":
      fields = (
        <>
          <Field label="IP">{node.canonical_ip}</Field>
          <Field label="Resource ID">{node.resource_id}</Field>
          <Field label="Finding ID">{node.finding_id}</Field>
          <Field label="Finding type">{node.finding_type}</Field>
          <Field label="This Run occurrence ID">
            {node.occurrence_id ?? text("不适用", "Not applicable")}
          </Field>
          <Field label="This Run transition ID">
            {node.transition_id ?? text("不适用", "Not applicable")}
          </Field>
          <Field label="Transition type">
            {node.transition_type ?? text("不适用", "Not applicable")}
          </Field>
          <Field label="Snapshot references">
            {node.source_snapshot_ids.length === 0 ? (
              text("没有快照引用", "No Snapshot references")
            ) : (
              <ul>
                {node.source_snapshot_ids.map((id) => (
                  <li key={id}>{id}</li>
                ))}
              </ul>
            )}
          </Field>
        </>
      )
      break
    case "REPORT":
      fields = (
        <>
          <Field label="Report ID">{node.governance_report_id}</Field>
          <Field label="Report contract">{node.report_contract_version}</Field>
          <Field label="Generation mode">{node.generation_mode}</Field>
          <Field label="HTML SHA-256">{node.html_sha256}</Field>
          <Field label="CSV SHA-256">{node.csv_sha256}</Field>
          <Field label="Summary scope">
            {text("完整运行报告摘要，单资源视图也包含在内；并非此资产的统计数据。", "Full Run report summary, including in the single-resource view; not statistics for this asset")}
          </Field>
          <Field label="customer_observed_asset_count">
            {node.summary.customer_observed_asset_count}
          </Field>
          <Field label="cloudatlas_observed_asset_count">
            {node.summary.cloudatlas_observed_asset_count}
          </Field>
          <Field label="matched_asset_count">
            {node.summary.matched_asset_count}
          </Field>
          <Field label="current_run_finding_count">
            {node.summary.current_run_finding_count}
          </Field>
          <Field label="current_run_transition_count">
            {node.summary.current_run_transition_count}
          </Field>
          <Field label="open_backlog_count">
            {node.summary.open_backlog_count}
          </Field>
        </>
      )
      break
  }
  return (
    <>
      <dl className="space-y-3 text-sm [&_dt]:font-medium [&_dd]:break-all">
        {fields}
      </dl>
      {node.kind === "FINDING" && (
        <p className="text-sm">
          {text("仅为本次运行中的历史事件，不代表发现项当前状态。", "Historical events in this Run only; not the Finding's current status.")}
        </p>
      )}
      {"observations" in node && (
        <ObservationReferences references={node.observations} />
      )}
      {"evidence" in node && <EvidenceReferences references={node.evidence} />}
      {node.kind === "REPORT" && (
        <Button
          type="button"
          onClick={(event) => openReport(event.currentTarget)}
        >
          {text("阅读报告", "Read report")}
        </Button>
      )}
    </>
  )
}
