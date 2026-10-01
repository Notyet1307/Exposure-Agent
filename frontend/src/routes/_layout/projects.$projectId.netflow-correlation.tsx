import { createFileRoute } from "@tanstack/react-router"
import { useEffect } from "react"
import NetflowCorrelation, {
  type NetflowCorrelationSearch,
} from "@/components/NetflowCorrelation"
import useAuth from "@/hooks/useAuth"
import { useI18n } from "@/lib/i18n"

const text = (value: unknown) =>
  typeof value === "string" && value ? value : undefined
const integer = (value: unknown) => {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : undefined
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
  ): NetflowCorrelationSearch => ({
    dataset: text(search.dataset),
    context: text(search.context),
    analysis: text(search.analysis),
    revision: text(search.revision),
    namespace: text(search.namespace),
    customerUpload: text(search.customerUpload),
    cloudMode: cloudMode(search.cloudMode),
    cloudSnapshot: text(search.cloudSnapshot),
    cloudLedgerRevision: integer(search.cloudLedgerRevision),
    cloudScopeRevision: integer(search.cloudScopeRevision),
    cloudSource: text(search.cloudSource),
    cloudIpVersion: text(search.cloudIpVersion),
    cloudPortVersion: text(search.cloudPortVersion),
    tab: tab(search.tab),
    taskId: text(search.taskId),
    addressIp: text(search.addressIp),
    addressKey: text(search.addressKey),
    addressPage: integer(search.addressPage),
    servicePage: integer(search.servicePage),
    peerPage: integer(search.peerPage),
    taskPage: integer(search.taskPage),
    taskStatus: taskStatus(search.taskStatus),
    feedbackRevision: text(search.feedbackRevision),
    evidencePage: integer(search.evidencePage),
    evidenceSource: evidenceSource(search.evidenceSource),
    comparisonPage: integer(search.comparisonPage),
    positiveSources: text(search.positiveSources),
    unmatchedNetflow:
      typeof search.unmatchedNetflow === "boolean"
        ? search.unmatchedNetflow
        : undefined,
    hasReviewTask:
      typeof search.hasReviewTask === "boolean"
        ? search.hasReviewTask
        : undefined,
    sort: search.sort === "ip_desc" ? "ip_desc" : "ip_asc",
    peerIp: text(search.peerIp),
    peerProtocol: integer(search.peerProtocol),
    peerPort: integer(search.peerPort),
    taskScope:
      search.taskScope === "object" || search.taskScope === "dataset"
        ? search.taskScope
        : undefined,
    taskKind: text(search.taskKind),
    objectKey: text(search.objectKey),
  }),
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
