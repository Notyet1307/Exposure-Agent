import { AlertCircle } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { useI18n } from "@/lib/i18n"

export function Stage4ResultNotice({
  latestRunId,
  latestRunCompletedAt,
}: {
  latestRunId: string | null
  latestRunCompletedAt: string | null
}) {
  const { t, formatDate } = useI18n()
  return (
    <Alert>
      <AlertCircle />
      <AlertTitle>
        {t("Stage 4 results are not available yet", "阶段 4 结果尚未就绪")}
      </AlertTitle>
      <AlertDescription>
        {latestRunId
          ? t(
              "The latest completed Run contains only Stage 3 results. Create a new Run to publish IP Assets and Findings.",
              "最近完成的运行仅包含阶段 3 结果。请创建新运行以发布 IP 资产和发现项。",
            )
          : t(
              "Create a new Run after the Project inputs are ready to publish IP Assets and Findings.",
              "项目输入就绪后，请创建新运行以发布 IP 资产和发现项。",
            )}
        {latestRunCompletedAt && (
          <span className="mt-1 block">
            {t("Latest completed Run:", "最近完成的运行：")}{" "}
            {formatDate(latestRunCompletedAt)}
          </span>
        )}
      </AlertDescription>
    </Alert>
  )
}
