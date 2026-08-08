import { AlertCircle } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"

export function Stage4ResultNotice({
  latestRunId,
  latestRunCompletedAt,
}: {
  latestRunId: string | null
  latestRunCompletedAt: string | null
}) {
  return (
    <Alert>
      <AlertCircle />
      <AlertTitle>Stage 4 results are not available yet</AlertTitle>
      <AlertDescription>
        {latestRunId
          ? "The latest completed Run contains only Stage 3 results. Create a new Run to publish IP Assets and Findings."
          : "Create a new Run after the Project inputs are ready to publish IP Assets and Findings."}
        {latestRunCompletedAt && (
          <span className="mt-1 block">
            Latest completed Run:{" "}
            {new Date(latestRunCompletedAt).toLocaleString()}
          </span>
        )}
      </AlertDescription>
    </Alert>
  )
}
