import { Link } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"
import { comparisonReturnFields } from "@/lib/comparisonReturn"
import { useI18n } from "@/lib/i18n"

export function ComparisonReturnLink({
  projectId,
  search,
}: {
  projectId: string
  search: object
}) {
  const { t } = useI18n()
  const back = comparisonReturnFields(search)
  if (!back.back_result) return null
  return (
    <Button asChild variant="outline">
      <Link
        to="/projects/$projectId/netflow-correlation"
        params={{ projectId }}
        search={{
          result: back.back_result,
          binding: back.back_binding,
          core_class: back.back_class,
          core_page: back.back_page,
          core_ip: back.back_ip,
          core_sort: back.back_sort,
          core_address: back.back_address,
          core_evidence: back.back_evidence,
          core_evidence_page: back.back_evidence_page,
          core_extra_page: back.back_extra_page,
        }}
      >
        {t("Return to comparison results", "返回比对结果")}
      </Link>
    </Button>
  )
}
