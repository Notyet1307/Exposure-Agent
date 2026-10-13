import { useEffect, useRef, useState } from "react"
import {
  type AnalysisPublic,
  NetflowBulkService,
  NetflowProcessingService,
} from "@/client"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"
import { netflowErrorCode, netflowRequestRejected } from "@/lib/netflow-errors"

export function NetflowAnalysisActions({
  actor,
  projectId,
  datasetId,
  contextId,
  analysis,
  canWrite,
  onAnalysis,
}: {
  actor: string
  projectId: string
  datasetId: string
  contextId: string
  analysis: AnalysisPublic | undefined
  canWrite: boolean
  onAnalysis: (value: AnalysisPublic) => void
}) {
  const { t } = useI18n()
  const store = `exposure:netflow-analysis:${actor}:${projectId}:${datasetId}:${contextId}:${analysis?.analysis_id ?? "new"}`
  const [pending, setPending] = useState<{
    key: string
    action: "create" | "reconcile"
  }>()
  const [busy, setBusy] = useState(false)
  const [cancelRequested, setCancelRequested] = useState(false)
  const [error, setError] = useState<[string, string]>()
  const active = useRef(true)
  useEffect(() => {
    active.current = true
    try {
      const value = JSON.parse(sessionStorage.getItem(store) ?? "null")
      if (
        value &&
        typeof value.key === "string" &&
        (value.action === "create" || value.action === "reconcile")
      )
        setPending(value)
    } catch {
      setError(["Recovery storage is unavailable.", "恢复存储不可用。"])
    }
    return () => {
      active.current = false
    }
  }, [store])
  const perform = async (action: "create" | "reconcile", recover = false) => {
    if (busy || (!recover && (!canWrite || pending)) || (recover && !pending))
      return
    if (
      !recover &&
      action === "create" &&
      analysis &&
      analysis.status !== "FAILED"
    )
      return
    if (action === "reconcile" && !analysis) return
    const key = pending?.key ?? crypto.randomUUID()
    setBusy(true)
    setError(undefined)
    try {
      if (!recover) {
        sessionStorage.setItem(store, JSON.stringify({ key, action }))
        setPending({ key, action })
      }
      const result =
        action === "create"
          ? recover
            ? await NetflowProcessingService.analysisOperation({
                projectId,
                datasetId,
                key,
              })
            : await NetflowProcessingService.createAnalysis({
                projectId,
                datasetId,
                idempotencyKey: key,
                requestBody: {
                  context_revision_id: contextId,
                  retry_of_analysis_id: analysis?.analysis_id ?? null,
                },
              })
          : recover
            ? await NetflowProcessingService.reconcileOperation({
                projectId,
                analysisId: analysis!.analysis_id,
                key,
              })
            : await NetflowProcessingService.reconcileAnalysis({
                projectId,
                analysisId: analysis!.analysis_id,
                idempotencyKey: key,
              })
      if (!active.current) return
      sessionStorage.removeItem(store)
      setPending(undefined)
      onAnalysis(result)
    } catch (cause) {
      if (!active.current) return
      if (!recover && netflowRequestRejected(cause)) {
        sessionStorage.removeItem(store)
        setPending(undefined)
      }
      if (netflowErrorCode(cause) === "bulk_capacity_busy") {
        setError([
          "Another bulk batch is still active. Wait for it to finish, then retry.",
          "另一个批量任务仍在处理。请等待完成后重试。",
        ])
        return
      }
      setError([
        "Analysis action unavailable. Query the original operation before another attempt.",
        "分析操作不可用；再次尝试前查询原操作。",
      ])
    } finally {
      if (active.current) setBusy(false)
    }
  }
  return (
    <div className="mt-3 space-y-2">
      <p className="text-xs text-muted-foreground">
        {t(
          "Processing runs only on explicit action. A retry keeps its failed parent; recovery never creates a replacement Session.",
          "仅明确操作才启动处理；重试固定失败父记录，恢复不创建替代 Session。",
        )}
      </p>
      <div className="flex flex-wrap gap-2">
        {(!analysis || analysis.status === "FAILED") && (
          <Button
            variant="outline"
            disabled={!canWrite || busy || Boolean(pending)}
            onClick={() => void perform("create")}
          >
            {analysis
              ? t("Retry this failed Analysis", "重试此失败 Analysis")
              : t("Start selected context analysis", "分析所选上下文")}
          </Button>
        )}
        {analysis &&
          ["PENDING", "RUNNING", "UNKNOWN"].includes(analysis.status) && (
            <Button
              variant="outline"
              disabled={!canWrite || busy || Boolean(pending)}
              onClick={() => void perform("reconcile")}
            >
              {t("Reconcile original Analysis", "恢复原 Analysis")}
            </Button>
          )}
        {analysis?.provenance.backend === "netflow-bulk-v1" &&
          ["PENDING", "RUNNING", "UNKNOWN"].includes(analysis.status) && (
            <Button
              variant="outline"
              disabled={
                !canWrite || busy || cancelRequested || Boolean(pending)
              }
              onClick={async () => {
                if (busy || !canWrite) return
                setBusy(true)
                setError(undefined)
                try {
                  const value = await NetflowBulkService.cancel({
                    projectId,
                    analysisId: analysis.analysis_id,
                  })
                  if (!active.current) return
                  setCancelRequested(value.cancel_requested === true)
                  const updated = await NetflowProcessingService.readAnalysis({
                    projectId,
                    analysisId: analysis.analysis_id,
                  })
                  if (active.current) onAnalysis(updated)
                } catch {
                  if (active.current)
                    setError([
                      "Cancellation could not be confirmed. Refresh the original task before retrying.",
                      "未能确认取消结果。请刷新原任务后重试。",
                    ])
                } finally {
                  if (active.current) setBusy(false)
                }
              }}
            >
              {cancelRequested
                ? t("Cancellation requested", "已请求取消")
                : t("Cancel bulk processing", "取消批量处理")}
            </Button>
          )}
        {pending && (
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => void perform(pending.action, true)}
          >
            {t("Query original analysis operation", "查询原分析操作")}
          </Button>
        )}
      </div>
      {error && <p role="alert">{t(...error)}</p>}
    </div>
  )
}
