import { useNavigate, useRouterState, useSearch } from "@tanstack/react-router"
import { useEffect } from "react"

import { CreateProjectLink } from "@/components/CreateProject"
import { TechnicalValue } from "@/components/TechnicalValue"
import { useI18n } from "@/lib/i18n"
import { useWorkspaceContext } from "@/lib/workspace"

export default function WorkspaceSelector() {
  const { t, formatDate } = useI18n()
  const navigate = useNavigate()
  const rootPage = useRouterState({
    select: (state) => state.location.pathname === "/",
  })
  const ledgerPage = useRouterState({
    select: (state) =>
      /\/(customer-ledger|cloudatlas-ledger|netflow-ledger)$/.test(
        state.location.pathname,
      ),
  })
  const netflowLedgerPage = useRouterState({
    select: (state) => state.location.pathname.endsWith("/netflow-ledger"),
  })
  const cloudLedgerPage = useRouterState({
    select: (state) => state.location.pathname.endsWith("/cloudatlas-ledger"),
  })
  const externalAssetsPage = useRouterState({
    select: (state) => state.location.pathname.endsWith("/external-assets"),
  })
  const netflowCorrelationPage = useRouterState({
    select: (state) => state.location.pathname.endsWith("/netflow-correlation"),
  })
  const netflowResultsPage = useRouterState({
    select: (state) => state.location.pathname.endsWith("/netflow-results"),
  })
  const { search, projectId, runId, project, projects, reports, latest } =
    useWorkspaceContext()
  const historicalRoot =
    rootPage &&
    ((search.view === undefined && search.run !== undefined) ||
      ["overview", "reports", "assets", "findings", "runs"].includes(
        search.view ?? "",
      ))
  const historicalPage = historicalRoot || (!rootPage && runId !== undefined)
  const assetView = useSearch({ strict: false }).asset_view
  const cloudAssetPage =
    cloudLedgerPage ||
    externalAssetsPage ||
    (rootPage && search.view === "cloudatlas-ledger")
  const projectChoices = projects.isSuccess ? projects.data.data : undefined
  const runChoices =
    projectChoices && project && reports.isSuccess
      ? reports.data.data
      : undefined
  useEffect(() => {
    if (
      rootPage &&
      !["create", "cloudatlas-ledger"].includes(search.view ?? "") &&
      projectId === undefined &&
      projects.isSuccess &&
      !projects.isFetching &&
      projects.data.data[0]
    ) {
      void navigate({
        to: "/",
        search: { ...search, project: projects.data.data[0].id },
        replace: true,
      })
    }
  }, [
    rootPage,
    navigate,
    projectId,
    projects.data,
    projects.isSuccess,
    projects.isFetching,
    search,
  ])
  useEffect(() => {
    if (
      historicalRoot &&
      !["create", "inputs", "runs", "cloudatlas", "cloudatlas-ledger"].includes(
        search.view ?? "",
      ) &&
      projectId !== undefined &&
      runId === undefined &&
      projects.isSuccess &&
      !projects.isFetching &&
      reports.isSuccess &&
      !reports.isFetching &&
      latest.isSuccess &&
      !latest.isFetching &&
      latest.data
    ) {
      void navigate({
        to: "/",
        search: { ...search, project: projectId, run: latest.data },
        replace: true,
      })
    }
  }, [
    historicalRoot,
    latest.data,
    latest.isSuccess,
    latest.isFetching,
    projects.isSuccess,
    projects.isFetching,
    reports.isSuccess,
    reports.isFetching,
    navigate,
    projectId,
    runId,
    search,
  ])
  return (
    <div className="flex min-w-0 flex-1 flex-wrap items-center gap-3">
      <CreateProjectLink />
      <label className="flex min-w-0 items-center gap-2 text-sm">
        <span>{t("Project", "项目")}</span>
        <select
          className="min-w-0 max-w-52 rounded-md border bg-background p-2"
          aria-label={t("Project", "项目")}
          value={projectId ?? ""}
          disabled={!projectChoices}
          onChange={(event) => {
            if (netflowResultsPage) {
              void navigate({
                to: "/projects/$projectId/netflow-results",
                params: { projectId: event.target.value },
                search: {},
              })
            } else if (netflowCorrelationPage) {
              void navigate({
                to: "/projects/$projectId/netflow-correlation",
                params: { projectId: event.target.value },
                search: {},
              })
            } else if (cloudAssetPage) {
              void navigate({
                to: "/projects/$projectId/cloudatlas-ledger",
                params: { projectId: event.target.value },
                search: {
                  asset_view: assetView === "history" ? "history" : "synced",
                },
              })
            } else if (netflowLedgerPage) {
              void navigate({
                to: "/projects/$projectId/netflow-ledger",
                params: { projectId: event.target.value },
                search: {
                  dataset: undefined,
                  revision: undefined,
                  page: 0,
                  ip: undefined,
                  candidate: false,
                  profile_ip: undefined,
                  customer_upload: undefined,
                  customer_revision: undefined,
                  cloud_snapshot: undefined,
                  cloud_revision: undefined,
                },
              })
            } else if (ledgerPage) {
              void navigate({
                to: "/projects/$projectId/customer-ledger",
                params: { projectId: event.target.value },
                search: {
                  ledger_page: 1,
                  ledger_archived: false,
                  ledger_upload: undefined,
                  ledger_revision: undefined,
                  ledger_query: undefined,
                  ledger_ip: undefined,
                },
              })
            } else {
              void navigate({
                to: "/",
                search: { project: event.target.value, view: search.view },
              })
            }
          }}
        >
          <option value="" disabled>
            {t("Select a project", "选择项目")}
          </option>
          {projectId !== undefined &&
            !projectChoices?.some((item) => item.id === projectId) && (
              <option value={projectId}>
                {t("Project unavailable", "项目不可用")}
              </option>
            )}
          {projectChoices?.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
              {project.archived_at ? t(" (Archived)", "（已归档）") : ""}
            </option>
          ))}
        </select>
      </label>
      {historicalPage &&
        !ledgerPage &&
        !cloudAssetPage &&
        !netflowCorrelationPage &&
        !netflowResultsPage && (
          <label className="flex min-w-0 items-center gap-2 text-sm">
            <span>{t("Published run", "已发布运行")}</span>
            <select
              className="min-w-0 max-w-72 rounded-md border bg-background p-2"
              aria-label={t("Published run", "已发布运行")}
              value={runId ?? ""}
              disabled={!runChoices?.length}
              onChange={(event) => {
                void navigate({
                  to: "/",
                  search: {
                    project: projectId,
                    run: event.target.value,
                    view: search.view,
                  },
                })
              }}
            >
              <option value="" disabled>
                {reports.isFetching || latest.isFetching
                  ? t("Loading…", "正在加载…")
                  : t("No compatible published result", "暂无兼容的已发布结果")}
              </option>
              {runId !== undefined &&
                !runChoices?.some(
                  (item) => item.governance_run_id === runId,
                ) && (
                  <option value={runId}>
                    {t("Run unavailable", "运行不可用")}
                  </option>
                )}
              {runChoices?.map((report) => (
                <option key={report.id} value={report.governance_run_id}>
                  {formatDate(report.run_completed_at)}
                </option>
              ))}
            </select>
          </label>
        )}
      {historicalPage &&
        !ledgerPage &&
        !cloudAssetPage &&
        !netflowCorrelationPage &&
        !netflowResultsPage &&
        runId !== undefined && (
          <details className="min-w-0 max-w-full text-sm">
            <summary className="cursor-pointer">
              {t("Selected run details", "所选批次详情")}
            </summary>
            <TechnicalValue value={runId} label={t("Run ID", "运行 ID")} />
          </details>
        )}
    </div>
  )
}
