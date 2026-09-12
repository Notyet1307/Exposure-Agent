import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate, useParams, useSearch } from "@tanstack/react-router"

import {
  ApiError,
  GovernanceReportsService,
  IpResultsService,
  ProjectsService,
} from "@/client"

const views = [
  "create",
  "overview",
  "reports",
  "inputs",
  "cloudatlas",
  "runs",
  "assets",
  "findings",
] as const
export const CLASSIFICATIONS = [
  "matched",
  "customer_upload_only",
  "cloudatlas_only",
  "neither_source_observed",
] as const

export type WorkspaceSearch = {
  project?: string
  run?: string
  view?: (typeof views)[number]
  classification?: (typeof CLASSIFICATIONS)[number]
  netflow_status?: "ACTIVE" | "UNKNOWN"
  page?: number
  resource_id?: string
  upload_page?: number
  netflow_page?: number
  assets_page?: number
  asset_id?: string
  asset_page?: number
  findings_page?: number
  finding_status?: "OPEN" | "CLOSED"
  finding_id?: string
  investigation_run?: string
  occurrence_page?: number
  transition_page?: number
}

function pageNumber(value: unknown, size: number) {
  const page =
    typeof value === "string" || typeof value === "number"
      ? Number(value)
      : Number.NaN
  return Number.isSafeInteger(page) &&
    page > 1 &&
    page <= Math.floor(Number.MAX_SAFE_INTEGER / size)
    ? page
    : undefined
}

export function validateWorkspaceSearch(
  search: Record<string, unknown>,
): WorkspaceSearch {
  return {
    project: typeof search.project === "string" ? search.project : undefined,
    run: typeof search.run === "string" ? search.run : undefined,
    view: views.find((view) => view === search.view),
    classification: CLASSIFICATIONS.find(
      (value) => value === search.classification,
    ),
    netflow_status:
      search.netflow_status === "ACTIVE" || search.netflow_status === "UNKNOWN"
        ? search.netflow_status
        : undefined,
    page: pageNumber(search.page, 25),
    resource_id:
      search.resource_id === undefined
        ? undefined
        : typeof search.resource_id === "string"
          ? search.resource_id
          : "",
    upload_page: pageNumber(search.upload_page, 10),
    netflow_page: pageNumber(search.netflow_page, 10),
    assets_page: pageNumber(search.assets_page, 25),
    asset_id: typeof search.asset_id === "string" ? search.asset_id : undefined,
    asset_page: pageNumber(search.asset_page, 25),
    findings_page: pageNumber(search.findings_page, 25),
    finding_status:
      search.finding_status === "OPEN" || search.finding_status === "CLOSED"
        ? search.finding_status
        : undefined,
    finding_id:
      typeof search.finding_id === "string" ? search.finding_id : undefined,
    investigation_run:
      typeof search.investigation_run === "string"
        ? search.investigation_run
        : undefined,
    occurrence_page: pageNumber(search.occurrence_page, 20),
    transition_page: pageNumber(search.transition_page, 20),
  }
}

export function useWorkspaceSearch() {
  return useSearch({ from: "/_layout" })
}

export function useWorkspaceNavigate() {
  return useNavigate({ from: "/" })
}

async function readAccessibleProjects() {
  const result = await ProjectsService.readProjects({ skip: 0, limit: 100 })
  while (result.data.length < result.count) {
    const next = await ProjectsService.readProjects({
      skip: result.data.length,
      limit: 100,
    })
    if (next.data.length === 0) break
    result.data.push(...next.data)
  }
  return result
}

async function readPublishedReports(projectId: string) {
  const result = await GovernanceReportsService.readGovernanceReports({
    projectId,
    limit: 50,
  })
  let cursor = result.next_cursor
  while (cursor !== null) {
    const next = await GovernanceReportsService.readGovernanceReports({
      projectId,
      limit: 50,
      cursor,
    })
    result.data.push(...next.data)
    cursor = next.next_cursor
  }
  return result
}

export function useWorkspaceContext() {
  const search = useWorkspaceSearch()
  const params = useParams({ strict: false })
  const projectId = params.projectId ?? search.project
  const runId = params.runId ?? search.run
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: readAccessibleProjects,
  })
  const project = projects.data?.data.find((item) => item.id === projectId)
  const reports = useQuery({
    queryKey: ["workspace-published-reports", projectId],
    queryFn: () => readPublishedReports(projectId!),
    enabled: !!project,
    retry: false,
  })
  const queryClient = useQueryClient()
  const latest = useQuery({
    queryKey: [
      "workspace-compatible-run",
      projectId,
      reports.data?.data.map((item) => item.id),
    ],
    queryFn: async () => {
      for (const report of reports.data!.data) {
        try {
          const sources = await queryClient.fetchQuery({
            queryKey: [
              "governance-run-sources",
              projectId,
              report.governance_run_id,
            ],
            queryFn: () =>
              IpResultsService.readGovernanceRunSources({
                projectId: projectId!,
                governanceRunId: report.governance_run_id,
              }),
            retry: false,
          })
          if (
            sources.project_id !== projectId ||
            sources.governance_run_id !== report.governance_run_id ||
            sources.governance_report_id !== report.id ||
            sources.report_contract_version !== report.report_contract_version
          ) {
            throw new Error("Published result identity mismatch")
          }
          return report.governance_run_id
        } catch (error) {
          if (!(error instanceof ApiError) || error.status !== 404) throw error
        }
      }
      return null
    },
    enabled:
      !!project &&
      projects.isSuccess &&
      !projects.isFetching &&
      reports.isSuccess &&
      !reports.isFetching &&
      runId === undefined,
    retry: false,
  })
  return {
    search,
    projectId,
    runId,
    project,
    projects,
    reports,
    latest,
    report: reports.data?.data.find((item) => item.governance_run_id === runId),
  }
}
