import { createFileRoute } from "@tanstack/react-router"
import { useEffect } from "react"
import NetflowCorrelation, {
  type NetflowCorrelationSearch,
} from "@/components/NetflowCorrelation"
import useAuth from "@/hooks/useAuth"
import { useI18n } from "@/lib/i18n"

const uuid = (key: string, value: unknown, errors: string[]) => {
  if (value === undefined) return undefined
  if (
    typeof value !== "string" ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      value,
    )
  )
    errors.push(key)
  return typeof value === "string" && value ? value : undefined
}
const text = (key: string, value: unknown, errors: string[]) => {
  if (value === undefined) return undefined
  if (typeof value !== "string" || !/^[a-z][a-z0-9_-]{0,63}$/.test(value))
    errors.push(key)
  return typeof value === "string" && value ? value : undefined
}
const integer = (key: string, value: unknown, errors: string[]) => {
  if (value === undefined) return undefined
  if (typeof value !== "string" && typeof value !== "number") {
    errors.push(key)
    return undefined
  }
  if (typeof value === "string" && !/^(0|[1-9][0-9]*)$/.test(value)) {
    errors.push(key)
    return undefined
  }
  const parsed = Number(value)
  if (!Number.isSafeInteger(parsed) || parsed < 0) errors.push(key)
  return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : undefined
}
const tab = (value: unknown): NetflowCorrelationSearch["tab"] =>
  value === "summary" ||
  value === "addresses" ||
  value === "peers" ||
  value === "tasks"
    ? value
    : undefined
const cloudMode = (value: unknown): NetflowCorrelationSearch["cloudMode"] =>
  value === "none" || value === "legacy" || value === "external"
    ? value
    : undefined
const evidenceSource = (
  value: unknown,
): NetflowCorrelationSearch["evidenceSource"] =>
  value === "customer" || value === "cloud" || value === "netflow"
    ? value
    : undefined
const taskStatus = (value: unknown): NetflowCorrelationSearch["taskStatus"] => {
  switch (value) {
    case "AWAITING_FEEDBACK":
    case "MATERIAL_INCOMPLETE":
    case "INVALID_MATERIAL":
    case "MATERIAL_CONFLICT":
    case "AWAITING_DEPENDENCY_MATERIAL":
    case "FIELDS_COMPLETE_PENDING_REVIEW":
      return value
    default:
      return undefined
  }
}

export const Route = createFileRoute(
  "/_layout/projects/$projectId/netflow-correlation",
)({
  validateSearch: (
    search: Record<string, unknown>,
  ): NetflowCorrelationSearch => {
    const identityErrors: string[] = []
    const mode = cloudMode(search.cloudMode)
    const customerOriginal =
      search.customerOriginal === undefined
        ? undefined
        : typeof search.customerOriginal === "boolean"
          ? search.customerOriginal
          : undefined
    if (search.cloudMode !== undefined && mode === undefined)
      identityErrors.push("cloudMode")
    if (search.customerOriginal !== undefined && customerOriginal === undefined)
      identityErrors.push("customerOriginal")
    if (customerOriginal === false) identityErrors.push("customerOriginal")
    if (customerOriginal && search.customerRevision !== undefined)
      identityErrors.push("customerRevision")
    return {
      dataset: uuid("dataset", search.dataset, identityErrors),
      context: uuid("context", search.context, identityErrors),
      analysis: uuid("analysis", search.analysis, identityErrors),
      revision: uuid("revision", search.revision, identityErrors),
      namespace: text("namespace", search.namespace, identityErrors),
      customerUpload: uuid(
        "customerUpload",
        search.customerUpload,
        identityErrors,
      ),
      customerRevision: uuid(
        "customerRevision",
        search.customerRevision,
        identityErrors,
      ),
      customerOriginal,
      historyRun: uuid("historyRun", search.historyRun, identityErrors),
      cloudMode: mode,
      cloudSnapshot: uuid(
        "cloudSnapshot",
        search.cloudSnapshot,
        identityErrors,
      ),
      cloudLedgerRevision: integer(
        "cloudLedgerRevision",
        search.cloudLedgerRevision,
        identityErrors,
      ),
      cloudScopeRevision: integer(
        "cloudScopeRevision",
        search.cloudScopeRevision,
        identityErrors,
      ),
      cloudSource: uuid("cloudSource", search.cloudSource, identityErrors),
      cloudIpVersion: uuid(
        "cloudIpVersion",
        search.cloudIpVersion,
        identityErrors,
      ),
      cloudPortVersion: uuid(
        "cloudPortVersion",
        search.cloudPortVersion,
        identityErrors,
      ),
      tab: tab(search.tab),
      taskId: typeof search.taskId === "string" ? search.taskId : undefined,
      addressIp:
        typeof search.addressIp === "string" ? search.addressIp : undefined,
      addressKey:
        typeof search.addressKey === "string" ? search.addressKey : undefined,
      addressPage: integer("addressPage", search.addressPage, []),
      servicePage: integer("servicePage", search.servicePage, []),
      peerPage: integer("peerPage", search.peerPage, []),
      taskPage: integer("taskPage", search.taskPage, []),
      taskStatus: taskStatus(search.taskStatus),
      feedbackRevision: uuid(
        "feedbackRevision",
        search.feedbackRevision,
        identityErrors,
      ),
      evidencePage: integer("evidencePage", search.evidencePage, []),
      evidenceSource: evidenceSource(search.evidenceSource),
      comparisonPage: integer("comparisonPage", search.comparisonPage, []),
      comparison:
        search.comparison === "differences" || search.comparison === "common"
          ? search.comparison
          : "all",
      positiveSources:
        typeof search.positiveSources === "string"
          ? search.positiveSources
          : undefined,
      unmatchedNetflow:
        typeof search.unmatchedNetflow === "boolean"
          ? search.unmatchedNetflow
          : undefined,
      hasReviewTask:
        typeof search.hasReviewTask === "boolean"
          ? search.hasReviewTask
          : undefined,
      sort: search.sort === "ip_desc" ? "ip_desc" : "ip_asc",
      peerIp: typeof search.peerIp === "string" ? search.peerIp : undefined,
      peerProtocol: integer("peerProtocol", search.peerProtocol, []),
      peerPort: integer("peerPort", search.peerPort, []),
      taskScope:
        search.taskScope === "object" || search.taskScope === "dataset"
          ? search.taskScope
          : undefined,
      taskKind:
        typeof search.taskKind === "string" ? search.taskKind : undefined,
      objectKey:
        typeof search.objectKey === "string" ? search.objectKey : undefined,
      identityErrors,
    }
  },
  component: NetflowCorrelationRoute,
})

function NetflowCorrelationRoute() {
  const { projectId } = Route.useParams()
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  const { user } = useAuth()
  const { t } = useI18n()
  useEffect(() => {
    document.title = t(
      "NetFlow source correlation - Exposure",
      "NetFlow 来源关联 - Exposure",
    )
  }, [t])
  return user ? (
    <NetflowCorrelation
      key={JSON.stringify([
        user.id,
        projectId,
        search.dataset,
        search.context,
        search.analysis,
        search.revision,
        search.namespace,
        search.customerUpload,
        search.customerRevision,
        search.customerOriginal,
        search.historyRun,
        search.cloudMode,
        search.cloudSnapshot,
        search.cloudLedgerRevision,
        search.cloudScopeRevision,
        search.cloudSource,
        search.cloudIpVersion,
        search.cloudPortVersion,
      ])}
      actor={user.id}
      projectId={projectId}
      search={search}
      navigate={navigate}
    />
  ) : null
}
