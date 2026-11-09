import { useEffect, useRef, useState } from "react"
import {
  type AnalysisPublic,
  NetflowBulkService,
  NetflowProcessingService,
} from "@/client"
import {
  NetflowProgress,
  type NetflowProgressState,
} from "@/components/NetflowProgress"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"
import { netflowErrorCode, netflowRequestRejected } from "@/lib/netflow-errors"
import { netflowProgressCancellation } from "@/lib/netflow-progress"

export function NetflowAnalysisActions({
  actor,
  projectId,
  datasetId,
  contextId,
  analysis,
  canWrite,
  onAnalysis,
  progress,
  onRefresh,
}: {
  actor: string
  projectId: string
  datasetId: string
  contextId: string
  analysis: AnalysisPublic | undefined
  canWrite: boolean
  onAnalysis: (value: AnalysisPublic) => void
  progress?: NetflowProgressState
  onRefresh?: () => void
}) {
  const { t } = useI18n()
  const store = `exposure:netflow-analysis:${actor}:${projectId}:${datasetId}:${contextId}:${analysis?.analysis_id ?? "new"}`
  const [pending, setPending] = useState<{
    key: string
    action: "create" | "reconcile"
  }>()
  const [busy, setBusy] = useState(false)
  const [acknowledged, setAcknowledged] = useState<{ analysis: string }>()
  const [error, setError] = useState<[string, string]>()
  const active = useRef(true)
  // The cleanup below can run without unmounting this component, so a plain
  // boolean would be set back to true for the next task and accept the old
  // response. The epoch belongs to exactly one task identity.
  const epoch = useRef(0)
  const taskRef = useRef<string | undefined>(analysis?.analysis_id)
  taskRef.current = analysis?.analysis_id
  useEffect(() => {
    active.current = true
    epoch.current += 1
    // A different task starts with its own idle actions. The previous task's
    // guarded finally/catch cannot reset this state after the switch.
    setBusy(false)
    setError(undefined)
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
      epoch.current += 1
    }
  }, [store])
  const current = (token: number) => active.current && token === epoch.current
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
    const token = epoch.current
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
      if (!current(token)) return
      // Reconcile names one original task. A response for another task may
      // refresh the parent, but it must never replace the mounted analysis.
      if (
        action === "reconcile" &&
        result.analysis_id !== analysis?.analysis_id
      ) {
        sessionStorage.removeItem(store)
        setPending(undefined)
        onRefresh?.()
        setError([
          "Analysis action returned another task. The original task stays selected.",
          "分析操作返回了另一任务；原任务仍保持选中。",
        ])
        return
      }
      sessionStorage.removeItem(store)
      setPending(undefined)
      onAnalysis(result)
    } catch (cause) {
      if (!current(token)) return
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
      if (current(token)) setBusy(false)
    }
  }
  const locallyRequested =
    acknowledged !== undefined &&
    acknowledged.analysis === analysis?.analysis_id
  const cancellation = netflowProgressCancellation(
    progress?.observation,
    locallyRequested,
  )
  return (
    <div className="mt-3 space-y-2">
      {progress && (
        <NetflowProgress progress={progress} requested={locallyRequested} />
      )}
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
                !canWrite || busy || cancellation !== "none" || Boolean(pending)
              }
              onClick={async () => {
                if (busy || !canWrite || cancellation !== "none") return
                const task = analysis
                if (!task) return
                const token = epoch.current
                setBusy(true)
                setError(undefined)
                try {
                  const value = await NetflowBulkService.cancel({
                    projectId,
                    analysisId: task.analysis_id,
                  })
                  if (!current(token) || taskRef.current !== task.analysis_id)
                    return
                  const response = value as {
                    analysis_id?: unknown
                    cancel_requested?: unknown
                  }
                  if (response.analysis_id !== task.analysis_id)
                    throw new Error("Cancel response identity mismatch")
                  // A false acknowledgement is a successful read, not a cancel
                  // request. Keep the action available and let refresh decide.
                  if (response.cancel_requested === true)
                    setAcknowledged({ analysis: task.analysis_id })
                  progress?.refresh()
                  onRefresh?.()
                } catch {
                  if (current(token) && taskRef.current === task.analysis_id)
                    setError([
                      "Cancellation could not be confirmed. Refresh the original task before retrying.",
                      "未能确认取消结果。请刷新原任务后重试。",
                    ])
                } finally {
                  if (current(token)) setBusy(false)
                }
              }}
            >
              {cancellation === "requested"
                ? t("Cancellation requested", "已请求取消")
                : cancellation === "confirmed"
                  ? t("Processing cancelled", "处理已取消")
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
