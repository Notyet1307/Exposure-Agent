import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { type ReactNode, useEffect, useRef, useState } from "react"

import {
  ApiError,
  type GovernanceRunLineagePublic,
  IpResultsService,
  type LineageEdgePublic,
  type LineageEvidenceReferencesPublic,
  type LineageObservationReferencesPublic,
} from "@/client"
import { ReportDetailDialog } from "@/components/GovernanceReports"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"

type LineageNode = GovernanceRunLineagePublic["nodes"][number]
type LineageSearch = { resource_id?: string }
const GROUPS = [
  { kind: "SOURCE", title: ["Sources", "来源"] },
  { kind: "SNAPSHOT", title: ["Snapshots", "快照"] },
  { kind: "PROCESS", title: ["Processing contract", "处理合同"] },
  { kind: "COMPARISON", title: ["Results: Comparisons", "结果：比较"] },
  { kind: "FINDING", title: ["Results: Finding events", "结果：发现项事件"] },
  { kind: "REPORT", title: ["Report", "报告"] },
] as const
const EDGE_STYLES: Record<
  LineageEdgePublic["kind"],
  { dash: string; meaning: [string, string] }
> = {
  SOURCE_SNAPSHOT: {
    dash: "none",
    meaning: ["Pinned source and snapshot", "固定的来源与快照"],
  },
  SNAPSHOT_PROCESS: {
    dash: "12 3",
    meaning: [
      "Batch context; not proof that every judgment used this source",
      "批次上下文；不证明每项判断均使用了此来源",
    ],
  },
  ABSENT_SOURCE_PROCESS: {
    dash: "2 6",
    meaning: [
      "Input not provided; not positive data input",
      "未提供输入；不表示存在有效数据输入",
    ],
  },
  PROCESS_COMPARISON: {
    dash: "8 3",
    meaning: [
      "Comparison under this Run's processing contract",
      "本次运行处理合同下的比较结果",
    ],
  },
  PROCESS_FINDING: {
    dash: "8 3 2 3",
    meaning: [
      "This Run's Finding event under the processing contract",
      "处理合同下的本次运行发现项事件",
    ],
  },
  PROCESS_REPORT: {
    dash: "16 4",
    meaning: [
      "Published report under the processing contract",
      "处理合同下的已发布报告",
    ],
  },
  COMPARISON_REPORT_CONTEXT: {
    dash: "3 3",
    meaning: [
      "Report context: association, not causation or proof of Evidence inclusion",
      "报告上下文：关联，非因果，也不证明证据已被纳入",
    ],
  },
  FINDING_REPORT_CONTEXT: {
    dash: "3 3 10 3",
    meaning: [
      "Report context: association, not causation or proof of Evidence inclusion",
      "报告上下文：关联，非因果，也不证明证据已被纳入",
    ],
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

function RunLineage() {
  const { t } = useI18n()
  useEffect(() => {
    document.title = t(
      "Run lineage - Exposure Agent",
      "运行血缘 - Exposure Agent",
    )
  }, [t])
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

  return (
    <div className="min-w-0 max-w-full space-y-6 overflow-hidden">
      <header className="space-y-2">
        <h1
          ref={heading}
          tabIndex={-1}
          className="text-2xl font-bold tracking-tight focus-visible:outline-2 focus-visible:outline-ring"
        >
          {t("Run lineage", "运行血缘")}
        </h1>
        <p className="break-all text-sm">
          {t("Project ID", "项目 ID")}: {projectId}
        </p>
        <p className="break-all text-sm">
          {t("Run ID", "运行 ID")}: {runId}
        </p>
        <p className="break-all font-medium">
          {resourceId === undefined
            ? t("Overview", "概览")
            : t(`Single resource: ${resourceId}`, `单资产范围：${resourceId}`)}
        </p>
        <p className="text-sm text-muted-foreground">
          {t(
            "Published facts for this explicit historical Run, not the latest Run or current inputs.",
            "此处展示所选历史运行的已发布事实，而非最新运行或当前输入。",
          )}
        </p>
        <nav
          aria-label={t("Lineage navigation", "血缘导航")}
          className="flex flex-wrap gap-4 text-sm"
        >
          <Link
            to="/projects/$projectId/runs/$runId/comparison"
            params={{ projectId, runId }}
            search={{}}
            className="underline underline-offset-4"
          >
            {t("View source comparison", "查看来源比较")}
          </Link>
          {resourceId !== undefined && (
            <Link
              to="/projects/$projectId/runs/$runId/lineage"
              params={{ projectId, runId }}
              search={{}}
              className="underline underline-offset-4"
            >
              {t("Back to overview", "返回概览")}
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

function LineageScope({
  projectId,
  runId,
  resourceId,
}: {
  projectId: string
  runId: string
  resourceId?: string
}) {
  const { t } = useI18n()
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
            ? t("Run lineage identity mismatch", "运行血缘身份不匹配")
            : invalid
              ? t("Invalid lineage parameters", "血缘参数无效")
              : status === 404
                ? t("Published lineage unavailable", "已发布血缘不可用")
                : t("Run lineage request failed", "运行血缘请求失败")}
        </AlertTitle>
        <AlertDescription>
          <p>
            {identityMismatch
              ? t(
                  "The response does not match the requested Project, Run, resource scope and Report contract. No lineage facts are displayed.",
                  "响应与所请求的项目、运行、资产范围和报告合同不匹配。不展示任何血缘事实。",
                )
              : invalid
                ? t(
                    "The requested parameters are invalid. The resource scope has not been replaced with an overview.",
                    "请求参数无效。未将资产范围替换为概览。",
                  )
                : status === 404
                  ? t(
                      "Published lineage for this Run or resource is unavailable.",
                      "此运行或资产的已发布血缘不可用。",
                    )
                  : t(
                      "The published facts could not be loaded. Please try again.",
                      "无法加载已发布事实，请重试。",
                    )}
          </p>
          <p>
            {t(
              "A failed request is not an empty graph, an ABSENT source or an UNKNOWN result.",
              "请求失败不代表空图、来源未提供（ABSENT）或结果未知（UNKNOWN）。",
            )}
          </p>
          {!invalid && status !== 404 && (
            <Button
              type="button"
              variant="outline"
              onClick={() => void query.refetch()}
            >
              {t("Try again", "重试")}
            </Button>
          )}
        </AlertDescription>
      </Alert>
    )
  }
  if (!data)
    return <p role="status">{t("Loading Run lineage…", "正在加载运行血缘…")}</p>
  return <PublishedLineage data={data} />
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

function PublishedLineage({ data }: { data: GovernanceRunLineagePublic }) {
  const { t, formatDate, translateValue } = useI18n()
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
    <>
      <section
        aria-label={t("Lineage scope and coverage", "血缘范围与覆盖")}
        className="min-w-0 space-y-3"
      >
        <p className="break-all text-sm">
          {t("Report ID", "报告 ID")}: {data.governance_report_id}
        </p>
        <p className="break-all text-sm">
          {translateValue(data.run_status)} · {t("Completed", "完成于")}{" "}
          {formatDate(data.completed_at)} · {data.report_contract_version}
        </p>
        <p role="status" className="text-sm">
          <Badge variant="secondary">{translateValue(data.status)}</Badge>{" "}
          {data.status === "EMPTY"
            ? t(
                "This scope has no displayable Comparisons or Finding events; sources, processing contract and report remain available. This does not mean no assets, traffic or risk.",
                "此范围没有可展示的比较或发现项事件；来源、处理合同和报告仍可查看。这不代表没有资产、流量或风险。",
              )
            : data.status === "PARTIAL"
              ? t(
                  "Bounded, truncated projection; not a publication failure or NetFlow quality judgment.",
                  "这是有界且已截断的投影，并非发布失败，也不是对 NetFlow 质量的判断。",
                )
              : t(
                  "This projection is not truncated; this does not prove complete input coverage or zero risk.",
                  "此投影未被截断；这不证明输入覆盖完整或风险为零。",
                )}
        </p>
        <dl className="grid gap-2 text-sm sm:grid-cols-2 [&_dt]:font-medium [&_dd]:break-all">
          <Field label={t("Run total comparisons", "运行比较总数")}>
            {data.totals.comparison_count}
          </Field>
          <Field label={t("Run total Finding events", "运行发现项事件总数")}>
            {data.totals.finding_event_count}
          </Field>
          <Field label={t("Comparison coverage", "比较覆盖情况")}>
            {data.coverage.comparison_returned} /{" "}
            {data.coverage.comparison_count}{" "}
            {t("returned / scope total", "已返回 / 范围总数")}
          </Field>
          <Field label={t("Finding event coverage", "发现项事件覆盖情况")}>
            {data.coverage.finding_returned} /{" "}
            {data.coverage.finding_event_count}{" "}
            {t("returned / scope total", "已返回 / 范围总数")}
          </Field>
          <Field label={t("Truncated", "是否截断")}>
            {t(String(data.truncated), data.truncated ? "是" : "否")}
          </Field>
        </dl>
        {data.truncation_reasons.length > 0 && (
          <div>
            <h2 className="font-medium">
              {t("Truncation reasons", "截断原因")}
            </h2>
            <ul className="list-inside list-disc break-all text-sm">
              {data.truncation_reasons.map((reason) => (
                <li key={reason}>{translateValue(reason)}</li>
              ))}
            </ul>
          </div>
        )}
        <p className="text-sm text-muted-foreground">
          {t(
            "Overview returns at most 20 Comparisons and 20 Finding events, selected independently; they need not identify the same assets. References return at most 20 per group. Use the full source comparison matrix to trace a resource outside this overview or narrow the scope; this does not promise complete references.",
            "概览最多返回 20 条比较和 20 条发现项事件，两者独立选取，不一定指向相同资产。每组引用最多返回 20 条。可使用完整来源比较矩阵追溯概览之外的资产，或缩小范围；这不保证引用完整。",
          )}
        </p>
        <p className="text-sm text-muted-foreground">
          {t(
            "finding_event_count counts distinct Findings with events in this Run, not occurrences, transitions, historical backlog or report samples.",
            "finding_event_count 统计本次运行中发生事件的去重发现项数量，而非出现次数、状态转换次数、历史积压或报告样本数。",
          )}
        </p>
        <details className="text-sm">
          <summary className="cursor-pointer">
            {t("Projection contracts and hash", "投影合同与哈希")}
          </summary>
          <dl className="mt-2 space-y-2 [&_dd]:break-all [&_dt]:font-medium">
            <Field label={t("Projection version", "投影版本")}>
              {data.projection_version}
            </Field>
            <Field label={t("Input contract", "输入合同")}>
              {data.input_contract_version}
            </Field>
            <Field label={t("Processing contract", "处理合同")}>
              {data.processing_contract_version}
            </Field>
            <Field label={t("Comparison output hash", "比较输出哈希")}>
              {data.comparison_output_hash}
            </Field>
          </dl>
        </details>
        {selected?.kind !== "REPORT" && (
          <Button
            type="button"
            onClick={(event) => openReport(event.currentTarget)}
          >
            {t("Read report", "阅读报告")}
          </Button>
        )}
      </section>

      <section
        aria-label={t("Association semantics", "关联语义")}
        className="space-y-3"
      >
        <h2 className="text-xl font-semibold">
          {t("Published associations, not causation", "已发布关联，非因果")}
        </h2>
        <p className="font-medium">
          {t(
            "Paths represent associations between published facts; they do not prove that a source triggered a Finding.",
            "路径表示已发布事实之间的关联，不证明某个来源触发了发现项。",
          )}
        </p>
        <p className="text-sm">
          {t(
            "Process is this Run's processing contract, not execution steps or a DAG. Comparison and Finding are parallel results; there is no Comparison → Finding connection.",
            "处理节点代表本次运行的处理合同，而非执行步骤或 DAG。比较和发现项是并列结果；不存在比较 → 发现项的连接。",
          )}
        </p>
        <p className="text-sm">
          {t(
            "PRESENT means a pinned snapshot exists, including one with 0 records. ABSENT means input was not provided. UNKNOWN uses the returned reason and does not mean nonexistent, zero traffic or zero risk. Zero Evidence means no corresponding sample references, not missing facts, exclusion from the report or no risk.",
            "PRESENT 表示存在固定快照，包括记录数为 0 的快照。ABSENT 表示未提供输入。UNKNOWN 以返回的原因为准，不代表不存在、流量为零或风险为零。证据数为零表示没有相应的样本引用，不代表事实缺失、未纳入报告或没有风险。",
          )}
        </p>
        <details open>
          <summary className="cursor-pointer font-medium">
            {t("Edge semantics and line styles", "关系语义与线型")}
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
                <strong className="break-all">{kind}</strong>:{" "}
                {t(...style.meaning)}
              </li>
            ))}
          </ul>
        </details>
      </section>

      <section
        aria-label={t("Lineage graph", "血缘图")}
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
              {t(group.title[0], group.title[1])}
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
                  aria-label={`${translateValue(node.kind)} ${label}`}
                  className={`h-full w-full cursor-pointer rounded-md border-foreground bg-background px-2 text-left text-xs ${node.key === selected?.key ? "border-4" : active ? "border-2" : "border"}`}
                  onClick={() => {
                    setSelectedKey(node.key)
                    nodeButtons.current.get(node.key)?.focus()
                  }}
                >
                  <span className="block">
                    {translateValue(node.kind)}
                    {node.key === selected?.key
                      ? t(" · Selected", " · 已选中")
                      : active
                        ? t(" · Path", " · 路径")
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
        <section
          aria-label={t("Lineage nodes", "血缘节点")}
          className="min-w-0 space-y-3"
        >
          <h2 className="text-xl font-semibold">
            {t("Lineage nodes", "血缘节点")}
          </h2>
          <p className="text-sm text-muted-foreground">
            {t(
              "Select a node to read its facts and directed upstream/downstream associations. Tab or Shift+Tab navigates; Enter or Space selects.",
              "选择节点以阅读事实及有向上游/下游关联。使用 Tab 或 Shift+Tab 导航，按 Enter 或空格选择。",
            )}
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
            {t("Clear selection", "清除选择")}
          </Button>
          <p role="status" className="text-sm">
            {selected
              ? t(
                  `Selected ${selected.kind} ${nodeIdentifier(selected)}`,
                  `已选中 ${translateValue(selected.kind)} ${nodeIdentifier(selected)}`,
                )
              : t("No node selected", "未选择节点")}
          </p>
          <div className="grid min-w-0 gap-4 md:grid-cols-2">
            {grouped.map((group) => (
              <section
                key={group.kind}
                aria-label={t(group.title[0], group.title[1])}
                className="min-w-0 space-y-2"
              >
                <h3 className="font-semibold">
                  {t(group.title[0], group.title[1])}
                </h3>
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
                        aria-label={`${translateValue(node.kind)} ${nodeIdentifier(node)}`}
                        onClick={() => setSelectedKey(node.key)}
                        className="w-full min-w-0 rounded-md border p-3 text-left text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring aria-pressed:border-foreground aria-pressed:bg-muted"
                      >
                        <span className="block font-semibold">
                          {translateValue(node.kind)}
                          {selected?.key === node.key
                            ? t(" · Selected", " · 已选中")
                            : upstream.reached.has(node.key)
                              ? t(" · Upstream", " · 上游")
                              : downstream.reached.has(node.key)
                                ? t(" · Downstream", " · 下游")
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
              aria-label={t("Node details", "节点详情")}
              className="min-w-0 space-y-3 rounded-lg border p-4"
            >
              <h2 className="text-xl font-semibold">
                {t("Node details", "节点详情")}
              </h2>
              <h3 className="break-all font-medium">
                {translateValue(selected.kind)} {nodeIdentifier(selected)}
              </h3>
              <NodeDetails node={selected} openReport={openReport} />
            </section>
            <section
              aria-label={t("Selected paths", "所选路径")}
              className="min-w-0 space-y-3 rounded-lg border p-4"
            >
              <h2 className="text-xl font-semibold">
                {t("Selected paths", "所选路径")}
              </h2>
              <p className="text-sm">
                {t(
                  "Directed upstream and downstream associations only; report context is not causation or proof of Evidence inclusion.",
                  "仅展示有向上游和下游关联；报告上下文不代表因果，也不证明证据已被纳入。",
                )}
              </p>
              {[
                {
                  title: "Upstream associations",
                  chinese: "上游关联",
                  path: upstream.path,
                },
                {
                  title: "Downstream associations",
                  chinese: "下游关联",
                  path: downstream.path,
                },
              ].map(({ title, chinese, path }) => (
                <section key={title} aria-label={t(title, chinese)}>
                  <h3 className="font-semibold">{t(title, chinese)}</h3>
                  {path.size === 0 ? (
                    <p className="text-sm">
                      {t(
                        "No returned associations in this direction.",
                        "此方向没有返回的关联。",
                      )}
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
                                ? `${translateValue(from.kind)} ${nodeIdentifier(from)}`
                                : edge.from}{" "}
                              →{" "}
                              {to
                                ? `${translateValue(to.kind)} ${nodeIdentifier(to)}`
                                : edge.to}
                              . {t(...EDGE_STYLES[edge.kind].meaning)}
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
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt>{label}</dt>
      <dd className="select-text">{children}</dd>
    </div>
  )
}

function ObservationReferences({
  references,
}: {
  references: LineageObservationReferencesPublic
}) {
  const { t } = useI18n()
  return (
    <section
      aria-label={t("Observation references", "观测引用")}
      className="space-y-2 text-sm"
    >
      <h3 className="font-semibold">
        {t("Observation references", "观测引用")}
      </h3>
      <p>
        {t("Count", "总数")}: {references.count} · {t("Returned", "已返回")}:{" "}
        {references.data.length} · {t("Truncated", "是否截断")}:{" "}
        {t(String(references.truncated), references.truncated ? "是" : "否")}
      </p>
      {references.data.length === 0 ? (
        <p>
          {t("No returned Observation references.", "没有返回的观测引用。")}
        </p>
      ) : (
        <ul className="space-y-2">
          {references.data.map((reference) => (
            <li key={reference.observation_id} className="break-all">
              {t("Observation ID", "观测 ID")}: {reference.observation_id} ·{" "}
              {t("Snapshot ID", "快照 ID")}: {reference.source_snapshot_id}
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
  const { t, translateValue } = useI18n()
  return (
    <section
      aria-label={t("Evidence references", "证据引用")}
      className="space-y-2 text-sm"
    >
      <h3 className="font-semibold">{t("Evidence references", "证据引用")}</h3>
      <p>
        {t("Count", "总数")}: {references.count} · {t("Returned", "已返回")}:{" "}
        {references.data.length} · {t("Truncated", "是否截断")}:{" "}
        {t(String(references.truncated), references.truncated ? "是" : "否")}
      </p>
      {references.data.length === 0 ? (
        <p>
          {t(
            "No returned Evidence sample references. This does not imply missing facts, exclusion from the report or no risk.",
            "没有返回的证据样本引用。这不代表事实缺失、未纳入报告或没有风险。",
          )}
        </p>
      ) : (
        <ul className="space-y-2">
          {references.data.map((reference) => (
            <li key={reference.id} className="break-all">
              {t("Evidence ID", "证据 ID")}: {reference.id} ·{" "}
              {t("Run ID", "运行 ID")}: {reference.governance_run_id} ·{" "}
              {t("Fact type", "事实类型")}:{" "}
              {translateValue(reference.fact_type)} · {t("Fact ID", "事实 ID")}:{" "}
              {reference.fact_id}
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
  const { t, formatDate, translateValue } = useI18n()
  let fields: ReactNode
  switch (node.kind) {
    case "SOURCE":
      fields = (
        <>
          <Field label={t("Source type", "来源类型")}>
            {translateValue(node.source_type)}
          </Field>
          <Field label={t("Pinned state", "固定状态")}>
            {translateValue(node.state)}
          </Field>
          <Field label={t("Input ID", "输入 ID")}>
            {node.input_id ?? t("Not provided", "未提供")}
          </Field>
        </>
      )
      break
    case "SNAPSHOT":
      fields = (
        <>
          <Field label={t("Snapshot ID", "快照 ID")}>{node.snapshot_id}</Field>
          <Field label={t("Source type", "来源类型")}>
            {translateValue(node.source_type)}
          </Field>
          <Field label={t("Content SHA-256", "内容 SHA-256")}>
            {node.content_sha256}
          </Field>
          <Field label={t("Schema fingerprint", "结构指纹")}>
            {node.schema_fingerprint}
          </Field>
          <Field label={t("Method fingerprint", "方法指纹")}>
            {node.method_fingerprint ?? t("Not provided", "未提供")}
          </Field>
          <Field label={t("Record count", "记录数")}>{node.record_count}</Field>
          <Field label={t("Valid time start (UTC)", "有效时间起点（UTC）")}>
            {node.valid_time_start_utc
              ? formatDate(node.valid_time_start_utc, "UTC")
              : t("Not provided", "未提供")}
          </Field>
          <Field label={t("Valid time end (UTC)", "有效时间终点（UTC）")}>
            {node.valid_time_end_utc
              ? formatDate(node.valid_time_end_utc, "UTC")
              : t("Not provided", "未提供")}
          </Field>
        </>
      )
      break
    case "PROCESS":
      fields = (
        <>
          <Field label={t("Meaning", "含义")}>
            {t(
              "This Run's processing contract, not execution steps or a DAG",
              "本次运行的处理合同，而非执行步骤或 DAG",
            )}
          </Field>
          <Field label={t("Run ID", "运行 ID")}>{node.governance_run_id}</Field>
          <Field label={t("Processing contract", "处理合同")}>
            {node.processing_contract_version}
          </Field>
          <Field label={t("Comparison contract", "比较合同")}>
            {node.comparison_contract_version}
          </Field>
          <Field label={t("Report contract", "报告合同")}>
            {node.report_contract_version}
          </Field>
        </>
      )
      break
    case "COMPARISON":
      fields = (
        <>
          <Field label="IP">{node.canonical_ip}</Field>
          <Field label={t("Resource ID", "资产 ID")}>{node.resource_id}</Field>
          <Field label={t("CustomerUpload presence", "客户上传观测情况")}>
            {node.customer_upload_present
              ? t("Observed", "已观测")
              : t("Not observed", "未观测")}
          </Field>
          <Field label={t("CloudAtlas presence", "CloudAtlas 观测情况")}>
            {node.cloudatlas_present
              ? t("Observed", "已观测")
              : t("Not observed", "未观测")}
          </Field>
          <Field label={t("Classification", "分类")}>
            {translateValue(node.classification)}
          </Field>
          <Field label={t("Classification reason", "分类原因")}>
            {translateValue(node.classification_reason)}
          </Field>
          <Field label={t("NetFlow status", "NetFlow 状态")}>
            {translateValue(node.netflow_status)}
          </Field>
          <Field label={t("NetFlow reason", "NetFlow 原因")}>
            {translateValue(node.netflow_reason)}
          </Field>
          <Field label={t("Content hash", "内容哈希")}>
            {node.content_hash}
          </Field>
          <Field label={t("Comparison fact ID", "比较事实 ID")}>
            {node.comparison_fact_id ??
              t(
                "Not applicable: a v1 comparison is a read-only projection, not a persisted comparison fact. This does not claim a three-source comparison chapter in its report.",
                "不适用：v1 比较是只读投影，而非持久化比较事实。这不表示其报告包含三来源比较章节。",
              )}
          </Field>
        </>
      )
      break
    case "FINDING":
      fields = (
        <>
          <Field label="IP">{node.canonical_ip}</Field>
          <Field label={t("Resource ID", "资产 ID")}>{node.resource_id}</Field>
          <Field label={t("Finding ID", "发现项 ID")}>{node.finding_id}</Field>
          <Field label={t("Finding type", "发现项类型")}>
            {translateValue(node.finding_type)}
          </Field>
          <Field label={t("This Run occurrence ID", "本次运行出现记录 ID")}>
            {node.occurrence_id ?? t("Not applicable", "不适用")}
          </Field>
          <Field label={t("This Run transition ID", "本次运行状态转换 ID")}>
            {node.transition_id ?? t("Not applicable", "不适用")}
          </Field>
          <Field label={t("Transition type", "状态转换类型")}>
            {node.transition_type
              ? translateValue(node.transition_type)
              : t("Not applicable", "不适用")}
          </Field>
          <Field label={t("Snapshot references", "快照引用")}>
            {node.source_snapshot_ids.length === 0 ? (
              t("No Snapshot references", "没有快照引用")
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
          <Field label={t("Report ID", "报告 ID")}>
            {node.governance_report_id}
          </Field>
          <Field label={t("Report contract", "报告合同")}>
            {node.report_contract_version}
          </Field>
          <Field label={t("Generation mode", "生成模式")}>
            {translateValue(node.generation_mode)}
          </Field>
          <Field label={t("HTML SHA-256", "HTML SHA-256")}>
            {node.html_sha256}
          </Field>
          <Field label={t("CSV SHA-256", "CSV SHA-256")}>
            {node.csv_sha256}
          </Field>
          <Field label={t("Summary scope", "摘要范围")}>
            {t(
              "Full Run report summary, including in the single-resource view; not statistics for this asset",
              "完整运行的报告摘要，单资产视图中也如此；并非此资产的统计",
            )}
          </Field>
          <Field
            label={t(
              "customer_observed_asset_count",
              "客户上传已观测资产数（customer_observed_asset_count）",
            )}
          >
            {node.summary.customer_observed_asset_count}
          </Field>
          <Field
            label={t(
              "cloudatlas_observed_asset_count",
              "CloudAtlas 已观测资产数（cloudatlas_observed_asset_count）",
            )}
          >
            {node.summary.cloudatlas_observed_asset_count}
          </Field>
          <Field
            label={t(
              "matched_asset_count",
              "双来源匹配资产数（matched_asset_count）",
            )}
          >
            {node.summary.matched_asset_count}
          </Field>
          <Field
            label={t(
              "current_run_finding_count",
              "本次运行发现项数（current_run_finding_count）",
            )}
          >
            {node.summary.current_run_finding_count}
          </Field>
          <Field
            label={t(
              "current_run_transition_count",
              "本次运行状态转换数（current_run_transition_count）",
            )}
          >
            {node.summary.current_run_transition_count}
          </Field>
          <Field
            label={t(
              "open_backlog_count",
              "未关闭积压数（open_backlog_count）",
            )}
          >
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
          {t(
            "Historical events in this Run only; not the Finding's current status.",
            "仅展示本次运行中的历史事件，而非发现项的当前状态。",
          )}
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
          {t("Read report", "阅读报告")}
        </Button>
      )}
    </>
  )
}
