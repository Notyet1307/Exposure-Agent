import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"

export function ResultPagination({
  label,
  count,
  page,
  pageSize,
  onPageChange,
}: {
  label: string
  count: number
  page: number
  pageSize: number
  onPageChange: (page: number) => void
}) {
  const { t } = useI18n()
  const localizedLabel =
    label === "Comparison" ? t("Comparison", "比较") : label
  const pageCount = Math.max(1, Math.ceil(count / pageSize))
  if (pageCount <= 1) return null

  return (
    <nav
      className="flex items-center justify-end gap-3"
      aria-label={t(`${label} pagination`, `${localizedLabel}分页`)}
    >
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={page === 0}
        onClick={() => onPageChange(page - 1)}
      >
        {t("Previous", "上一页")}
      </Button>
      <span className="text-sm text-muted-foreground">
        {t(
          `Page ${page + 1} of ${pageCount}`,
          `第 ${page + 1} 页，共 ${pageCount} 页`,
        )}
      </span>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={page + 1 >= pageCount}
        onClick={() => onPageChange(page + 1)}
      >
        {t("Next", "下一页")}
      </Button>
    </nav>
  )
}
