import { AlertCircle } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { useLocale } from "@/components/LocaleProvider"

export function Stage4ResultNotice({
  latestRunId,
  latestRunCompletedAt,
}: {
  latestRunId: string | null
  latestRunCompletedAt: string | null
}) {
  const { text } = useLocale()
  return (
    <Alert>
      <AlertCircle />
      <AlertTitle>{text("第 4 阶段结果尚不可用", "Stage 4 results are not available yet")}</AlertTitle>
      <AlertDescription>
        {latestRunId
          ? text("最新完成运行仅包含第 3 阶段结果。请新建运行以发布 IP 资产和发现项。", "The latest completed Run contains only Stage 3 results. Create a new Run to publish IP Assets and Findings.")
          : text("项目输入就绪后，请新建运行以发布 IP 资产和发现项。", "Create a new Run after the Project inputs are ready to publish IP Assets and Findings.")}
        {latestRunCompletedAt && (
          <span className="mt-1 block">
            {text("最新完成运行：", "Latest completed Run:")}{" "}
            {new Date(latestRunCompletedAt).toLocaleString()}
          </span>
        )}
      </AlertDescription>
    </Alert>
  )
}
