import { useQuery } from "@tanstack/react-query"
import { Link, useRouterState } from "@tanstack/react-router"
import { useEffect, useRef } from "react"
import { ModelConnectionsService } from "@/client"
import { Button } from "@/components/ui/button"
import useAuth from "@/hooks/useAuth"
import { useI18n } from "@/lib/i18n"

// Only focus after the target's authorized content is mounted; polling must not steal focus.
export function useAiSectionAnchor(id: string, ready: boolean) {
  const hash = useRouterState({ select: (state) => state.location.hash })
  const heading = useRef<HTMLHeadingElement>(null)
  const focused = useRef(false)
  useEffect(() => {
    if (hash.replace(/^#/, "") !== id) {
      focused.current = false
      return
    }
    if (ready && !focused.current && heading.current) {
      focused.current = true
      heading.current.focus({ preventScroll: true })
      heading.current.scrollIntoView({ block: "start" })
    }
  }, [hash, id, ready])
  return heading
}

export function AiModelStatus() {
  const { user, userError } = useAuth()
  const { t } = useI18n()
  const query = useQuery({
    queryKey: ["model-connection-status", user?.id],
    queryFn: () => ModelConnectionsService.status(),
    enabled: !!user && !userError,
    retry: false,
  })
  const data = !userError && query.isSuccess ? query.data : undefined
  const state = !data
    ? t("Status unknown", "状态未知")
    : data.ready
      ? t("Available", "可用")
      : data.state === "disabled"
        ? t("Disabled", "已禁用")
        : data.state === "unavailable"
          ? t("Unavailable", "暂不可用")
          : data.configured
            ? t("Not ready", "尚未就绪")
            : t("Not configured", "未配置")
  return (
    <div className="space-y-2 text-sm">
      <p aria-live="polite" className="flex flex-wrap gap-x-3 gap-y-1">
        <span className="font-medium">
          {t("Model for new tasks", "新任务的模型")}
        </span>
        <span>
          {query.isPending && !userError
            ? t("Reading status…", "正在读取状态…")
            : state}
        </span>
        {data?.model_identity && (
          <span className="break-all text-muted-foreground">
            {data.model_identity}
          </span>
        )}
        {data?.active_version_id && (
          <span className="text-muted-foreground">
            {t("Connection version", "连接版本")}{" "}
            {data.active_version_id.slice(0, 8)}
          </span>
        )}
        {data?.state === "legacy" && (
          <span className="text-muted-foreground">
            {t("Deployment connection", "现有部署连接")}
          </span>
        )}
      </p>
      <p className="max-w-prose text-muted-foreground">
        {data?.ready
          ? t(
              "Project permissions and allowed materials are checked for every request. Saved results keep their own connection version.",
              "每次请求仍检查项目权限和材料范围。已保存结果保留其原连接版本。",
            )
          : t(
              "Facts, saved reports and manual records remain available. Check the model connection before starting new AI work.",
              "事实、历史报告和人工记录仍可使用。发起新的 AI 工作前，请先检查模型连接。",
            )}
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <Link
          to="/ai-settings"
          search={{}}
          className="underline underline-offset-4 focus-visible:outline-2"
        >
          {user?.is_superuser
            ? t("Manage model connection", "管理模型连接")
            : t("View model status", "查看模型状态")}
        </Link>
        {(query.isError || userError) && (
          <Button
            size="sm"
            variant="outline"
            disabled={query.isFetching || !!userError}
            onClick={() => void query.refetch()}
          >
            {t("Read status again", "重新读取状态")}
          </Button>
        )}
      </div>
    </div>
  )
}

export function AiWorkspace({
  projectId,
  runId,
}: {
  projectId: string
  runId: string
}) {
  const { t } = useI18n()
  return (
    <section
      aria-labelledby="workspace-ai-title"
      className="space-y-4 rounded-lg border p-4 md:p-5"
    >
      <div className="space-y-1">
        <h3 id="workspace-ai-title" className="text-lg font-semibold">
          {t("AI workspace for this Run", "本轮 AI 工作区")}
        </h3>
        <p className="max-w-prose text-sm text-muted-foreground">
          {t(
            "Read the published facts, investigate one asset, then review an analysis draft. Opening these views does not generate a task.",
            "从已发布事实出发，核查单个资产，再审阅分析草稿。打开这些入口不会生成任务。",
          )}
        </p>
      </div>
      <AiModelStatus />
      <nav
        className="flex flex-wrap gap-3"
        aria-label={t("AI workflow", "AI 工作流")}
      >
        <Button asChild className="h-auto whitespace-normal text-black">
          <Link
            to="/"
            search={{ project: projectId, run: runId, view: "reports" }}
            hash="analysis-reports-title"
          >
            {t("Open this Run's AI interpretation", "打开本轮 AI 解读")}
          </Link>
        </Button>
        <Button asChild variant="outline" className="h-auto whitespace-normal">
          <Link
            to="/projects/$projectId/runs/$runId/comparison"
            params={{ projectId, runId }}
            search={{ project: projectId, run: runId }}
          >
            {t("Browse assets and investigations", "查看资产与核查")}
          </Link>
        </Button>
      </nav>
    </section>
  )
}
