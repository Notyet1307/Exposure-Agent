import { Link } from "@tanstack/react-router"
import { useEffect } from "react"
import { Button } from "@/components/ui/button"
import type { AssetSearch } from "@/lib/assetSearch"
import { useI18n } from "@/lib/i18n"

export default function AssetViews({
  projectId,
  search,
}: {
  projectId: string
  search: AssetSearch
}) {
  const { t } = useI18n()
  useEffect(() => {
    document.title = t(
      "CloudAtlas ledger - Exposure",
      "云图原生资产账 - Exposure",
    )
  }, [t])
  return (
    <header className="space-y-3">
      <h1 className="text-2xl font-bold">
        {t("CloudAtlas ledger", "云图原生资产账")}
      </h1>
      {search.asset_error && (
        <p role="alert">
          {search.asset_error === "invalid"
            ? t(
                "Invalid asset view. Choose a view explicitly; no asset data has been read.",
                "资产视图值无效。请明确选择视图；尚未读取资产数据。",
              )
            : t(
                "Conflicting link contexts. Synced versions and historical snapshots cannot be combined. Choose a new context explicitly.",
                "链接上下文冲突。已同步版本与历史快照不能混用，请明确选择新的阅读上下文。",
              )}
        </p>
      )}
      <nav
        aria-label={t("Asset view", "资产视图")}
        className="flex flex-wrap gap-2"
      >
        <Button
          asChild
          variant={search.asset_view === "synced" ? "default" : "outline"}
        >
          <Link
            to="/projects/$projectId/cloudatlas-ledger"
            params={{ projectId }}
            search={{ asset_view: "synced" }}
            aria-current={search.asset_view === "synced" ? "page" : undefined}
          >
            {t("Synced assets", "已同步资产")}
          </Link>
        </Button>
        <Button
          asChild
          variant={search.asset_view === "history" ? "default" : "outline"}
        >
          <Link
            to="/projects/$projectId/cloudatlas-ledger"
            params={{ projectId }}
            search={{ asset_view: "history" }}
            aria-current={search.asset_view === "history" ? "page" : undefined}
          >
            {t("Historical Run snapshots", "历史 Run 快照")}
          </Link>
        </Button>
      </nav>
    </header>
  )
}
