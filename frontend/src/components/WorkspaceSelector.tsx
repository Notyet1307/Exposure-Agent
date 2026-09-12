import { useNavigate } from "@tanstack/react-router"
import { useEffect } from "react"

import { CreateProjectLink } from "@/components/CreateProject"
import { TechnicalValue } from "@/components/TechnicalValue"
import { useI18n } from "@/lib/i18n"
import { useWorkspaceContext } from "@/lib/workspace"

export default function WorkspaceSelector() {
  const { t, formatDate } = useI18n()
  const navigate = useNavigate()
  const { search, projectId, runId, project, projects, reports, latest } =
    useWorkspaceContext()
  const projectChoices = projects.isSuccess ? projects.data.data : undefined
  const runChoices =
    projectChoices && project && reports.isSuccess
      ? reports.data.data
      : undefined
  useEffect(() => {
    if (
      search.view !== "create" &&
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
    navigate,
    projectId,
    projects.data,
    projects.isSuccess,
    projects.isFetching,
    search,
  ])
  useEffect(() => {
    if (
      !["create", "inputs", "runs", "cloudatlas"].includes(search.view ?? "") &&
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
            void navigate({
              to: "/",
              search: { project: event.target.value, view: search.view },
            })
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
            !runChoices?.some((item) => item.governance_run_id === runId) && (
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
      {runId !== undefined && (
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
