import { createFileRoute } from "@tanstack/react-router"
import NetflowResults, {
  type NetflowResultsSearch,
} from "@/components/NetflowResults"
import useAuth from "@/hooks/useAuth"

export const Route = createFileRoute(
  "/_layout/projects/$projectId/netflow-results",
)({
  validateSearch: (search: Record<string, unknown>): NetflowResultsSearch => {
    let invalid = false
    const id = (key: string) => {
      const value = search[key]
      if (value === undefined) return undefined
      if (
        typeof value !== "string" ||
        !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
          value,
        )
      )
        invalid = true
      return typeof value === "string" ? value : undefined
    }
    const number = (key: string, max = Number.MAX_SAFE_INTEGER) => {
      const value = search[key]
      if (value === undefined) return undefined
      if (
        !/^(0|[1-9][0-9]*)$/.test(String(value)) ||
        !Number.isSafeInteger(Number(value)) ||
        Number(value) > max
      )
        invalid = true
      return Number(value)
    }
    const text = (key: string) =>
      typeof search[key] === "string" ? (search[key] as string) : undefined
    const result: NetflowResultsSearch = {
      analysis: id("analysis"),
      dataset: id("dataset"),
      collectionScope: text("collectionScope"),
      history: search.history === true || search.history === "true",
      tab: search.tab === "peers" ? "peers" : "observations",
      resultPage: number("resultPage") ?? 0,
      datasetPage: number("datasetPage") ?? 0,
      batchPage: number("batchPage") ?? 0,
      ip: text("ip"),
      protocol: number("protocol", 255),
      port: number("port", 65535),
      object: text("object"),
      peer: text("peer"),
      evidence: search.evidence === true || search.evidence === "true",
      evidencePage: number("evidencePage") ?? 0,
      sort: search.sort === "ip_desc" ? "ip_desc" : "ip_asc",
    }
    return { ...result, invalid }
  },
  component: ResultsRoute,
})

function ResultsRoute() {
  const { projectId } = Route.useParams()
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  const { user } = useAuth()
  return user ? (
    <NetflowResults
      key={`${user.id}:${projectId}:${search.analysis ?? "none"}:${search.dataset ?? "none"}`}
      actor={user.id}
      projectId={projectId}
      search={search}
      navigate={navigate}
    />
  ) : null
}
