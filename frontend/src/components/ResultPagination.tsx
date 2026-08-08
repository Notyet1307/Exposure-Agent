import { Button } from "@/components/ui/button"

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
  const pageCount = Math.max(1, Math.ceil(count / pageSize))
  if (pageCount <= 1) return null

  return (
    <nav
      className="flex items-center justify-end gap-3"
      aria-label={`${label} pagination`}
    >
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={page === 0}
        onClick={() => onPageChange(page - 1)}
      >
        Previous
      </Button>
      <span className="text-sm text-muted-foreground">
        Page {page + 1} of {pageCount}
      </span>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={page + 1 >= pageCount}
        onClick={() => onPageChange(page + 1)}
      >
        Next
      </Button>
    </nav>
  )
}
