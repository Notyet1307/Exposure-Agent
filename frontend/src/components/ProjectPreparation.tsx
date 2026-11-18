import { Link, useRouterState } from "@tanstack/react-router"
import { useEffect, useRef } from "react"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"

export default function ProjectPreparation({
  projectId,
  projectName,
  archived,
}: {
  projectId: string
  projectName?: string
  archived: boolean
}) {
  const { t } = useI18n()
  const heading = useRef<HTMLHeadingElement>(null)
  const hash = useRouterState({ select: (state) => state.location.hash })
  useEffect(() => {
    const id = hash.replace(/^#/, "")
    if (
      ![
        "customer-inputs",
        "cloudatlas-inputs",
        "netflow-inputs",
        "netflow-processing",
      ].includes(id)
    ) {
      heading.current?.focus()
    }
  }, [hash])
  return (
    <header className="workspace-page-header">
      {projectName && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <h2 className="rounded-md border bg-muted/50 px-2 py-0.5 text-xs font-medium text-foreground">
            {projectName}
          </h2>
          <span>
            {t(
              "Current project management. Published reading context is preserved.",
              "当前项目管理，已保留发布结果阅读上下文。",
            )}
          </span>
        </div>
      )}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-2">
          <h1
            id="preparation-title"
            tabIndex={-1}
            ref={heading}
            className="workspace-page-title"
          >
            {t("Data access", "数据接入")}
          </h1>
          <p className="max-w-prose text-sm text-muted-foreground">
            {t(
              "Configure sources, apply customer files, and review processing records. Connection and upload success do not mean published data is ready.",
              "配置来源、应用客户清单，并查看处理记录。连接正常或文件上传成功，不等于已发布资料可用。",
            )}
          </p>
        </div>
        <Button asChild>
          <Link
            to="/projects/$projectId/netflow-correlation"
            params={{ projectId }}
            search={{}}
          >
            {t("View comparison results", "查看比对结果")}
          </Link>
        </Button>
      </div>
      {archived && (
        <p role="status">
          {t(
            "This project is archived and read-only.",
            "此项目已归档，只能阅读。",
          )}
        </p>
      )}
    </header>
  )
}
