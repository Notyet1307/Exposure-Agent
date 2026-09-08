import { Button } from "@/components/ui/button"
import { useLocale } from "@/components/LocaleProvider"

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
  const { text } = useLocale()
  const pageCount = Math.max(1, Math.ceil(count / pageSize))
  if (pageCount <= 1) return null

  return (
    <nav
      className="flex items-center justify-end gap-3"
      aria-label={text(`${label} 分页`, `${label} pagination`)}
    >
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={page === 0}
        onClick={() => onPageChange(page - 1)}
      >
        {text("上一页", "Previous")}
      </Button>
      <span className="text-sm text-muted-foreground">
        {text(`第 ${page + 1}/${pageCount} 页`, `Page ${page + 1} of ${pageCount}`)}
      </span>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={page + 1 >= pageCount}
        onClick={() => onPageChange(page + 1)}
      >
        {text("下一页", "Next")}
      </Button>
    </nav>
  )
}
