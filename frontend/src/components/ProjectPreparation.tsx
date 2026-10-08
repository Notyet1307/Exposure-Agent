import { Link, useRouterState } from "@tanstack/react-router"
import { useEffect, useRef } from "react"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"

export default function ProjectPreparation({
  projectId,
  archived,
}: {
  projectId: string
  archived: boolean
}) {
  const { t } = useI18n()
  const heading = useRef<HTMLHeadingElement>(null)
  const hash = useRouterState({ select: (state) => state.location.hash })
  useEffect(() => {
    const id = hash.replace(/^#/, "")
    const target = [
      "customer-inputs",
      "cloudatlas-inputs",
      "netflow-inputs",
      "netflow-processing",
    ].includes(id)
      ? document.getElementById(id)
      : heading.current
    target?.focus()
  }, [hash])
  return (
    <header className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-2">
          <h1
            id="preparation-title"
            tabIndex={-1}
            ref={heading}
            className="text-2xl font-semibold"
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
      <nav
        aria-label={t("Data sources", "数据来源")}
        className="flex flex-wrap gap-4 text-sm"
      >
        <a className="underline underline-offset-4" href="#customer-inputs">
          {t("Customer asset ledger", "客户资产台账")}
        </a>
        <a className="underline underline-offset-4" href="#cloudatlas-inputs">
          {t("CloudAtlas", "云图")}
        </a>
        <a className="underline underline-offset-4" href="#netflow-inputs">
          {t("NetFlow", "NetFlow")}
        </a>
      </nav>
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
