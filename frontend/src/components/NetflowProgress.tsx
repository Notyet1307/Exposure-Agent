import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useMemo, useRef } from "react"
import { type AnalysisPublic, NetflowBulkService } from "@/client"
import { useI18n } from "@/lib/i18n"
import { netflowText } from "@/lib/netflow-labels"
import {
  type NetflowProgressObservation,
  type NetflowProgressProblem,
  netflowProgressCancellation,
  netflowProgressIdentity,
  netflowProgressKey,
  netflowProgressProblem,
  netflowProgressTerminal,
  parseNetflowProgress,
} from "@/lib/netflow-progress"

export type NetflowProgressState = {
  enabled: boolean
  observation?: NetflowProgressObservation
  observedAt?: number
  problem?: NetflowProgressProblem
  error?: unknown
  isFetching: boolean
  refresh: () => void
}

export function useNetflowProgress({
  scope,
  projectId,
  analysis,
}: {
  scope: readonly unknown[]
  projectId: string
  analysis: AnalysisPublic | undefined
}): NetflowProgressState {
  const cache = useQueryClient()
  const identity = useMemo(() => {
    const value = netflowProgressIdentity(analysis)
    return value && value.project_id === projectId ? value : undefined
  }, [analysis, projectId])
  // A metadata-only refresh replaces `analysis` but not the immutable scope
  // and identity fields. Keeping this key reference stable keeps the cleanup
  // effect from cancelling the same semantic observation.
  const signature = JSON.stringify([scope, identity])
  const keyRef = useRef<
    { signature: string; key: readonly unknown[] } | undefined
  >(undefined)
  let stable = keyRef.current
  if (stable?.signature !== signature) {
    stable = { signature, key: netflowProgressKey(scope, identity) }
    keyRef.current = stable
  }
  const key = stable.key
  const query = useQuery({
    queryKey: key,
    enabled: Boolean(identity),
    retry: false,
    staleTime: 0,
    gcTime: 0,
    refetchInterval: (state) => {
      if (!identity) return false
      const problem = netflowProgressProblem(state.state.error)
      if (problem === "refusal") return false
      // A mismatched or malformed read proves nothing about the task, so keep
      // the same-task retry alive instead of freezing the last observation.
      if (problem === "identity") return 5000
      if (state.state.data && netflowProgressTerminal(state.state.data))
        return false
      return 5000
    },
    queryFn: () =>
      NetflowBulkService.progress({
        projectId,
        analysisId: identity!.analysis_id,
      }).then((value) => parseNetflowProgress(value, identity!)),
  })
  useEffect(
    () => () => {
      void cache.cancelQueries({ queryKey: key })
      cache.removeQueries({ queryKey: key })
    },
    [cache, key],
  )
  const problem = netflowProgressProblem(query.error)
  // Refusal and identity conflicts clear the content a reader may see. A
  // transient read error keeps only the last observation with that identity.
  const observation =
    problem === "refusal" || problem === "identity" ? undefined : query.data
  return {
    enabled: Boolean(identity),
    observation,
    observedAt: observation ? query.dataUpdatedAt : undefined,
    problem: query.isError ? problem : undefined,
    error: query.isError ? query.error : undefined,
    isFetching: query.isFetching,
    refresh: () => {
      if (identity) void query.refetch()
    },
  }
}

export function NetflowProgress({
  progress,
  requested = false,
}: {
  progress: NetflowProgressState
  requested?: boolean
}) {
  const { t, formatDate } = useI18n()
  if (!progress.enabled) return null
  const observation = progress.observation
  const cancellation = netflowProgressCancellation(observation, requested)
  const refusal = progress.problem === "refusal"
  const identityConflict = progress.problem === "identity"
  return (
    <section
      className="space-y-2 rounded-lg border p-4"
      aria-label={t("Processing progress", "处理进度")}
    >
      <h2 className="font-semibold">{t("Processing progress", "处理进度")}</h2>
      {observation ? (
        <div className="space-y-1 text-sm">
          <p>
            {t("Progress status", "进度状态")}:{" "}
            {netflowText(observation.status, t)}
          </p>
          <p>
            {t("Phase", "阶段")}: {netflowText(observation.phase, t)}
          </p>
          <p>
            {t("Files complete", "已完成文件")}:{" "}
            <output aria-label={t("Files complete", "已完成文件")}>
              {observation.files_completed} / {observation.files_total}
            </output>
          </p>
          <p>
            {t("Last heartbeat", "最近心跳")}:{" "}
            {observation.heartbeat_at
              ? formatDate(observation.heartbeat_at)
              : t("No heartbeat reported", "没有心跳")}
          </p>
          {progress.observedAt !== undefined && (
            <p className="text-muted-foreground">
              {t("Progress observed", "进度读取时间")}:{" "}
              {formatDate(new Date(progress.observedAt).toISOString())}
            </p>
          )}
        </div>
      ) : identityConflict ? (
        <p role="alert">
          {t(
            "Progress data did not match this fixed task and was cleared.",
            "进度数据与该固定任务不匹配，已清除。",
          )}
        </p>
      ) : refusal ? (
        <p role="alert">
          {t(
            "Bulk progress is unavailable for this fixed task.",
            "该固定任务没有可用的批量进度。",
          )}
        </p>
      ) : progress.isFetching ? (
        <p role="status">
          {t("Reading processing progress…", "正在读取处理进度…")}
        </p>
      ) : (
        <p role="status">
          {t(
            "Progress is temporarily unavailable. Retrying for the same task.",
            "进度暂时不可读，正在为同一任务重试。",
          )}
        </p>
      )}
      {cancellation === "confirmed" ? (
        <p className="text-sm font-medium">
          {t("Processing cancelled", "处理已取消")}
        </p>
      ) : cancellation === "requested" ? (
        <p className="text-sm font-medium">
          {t("Cancellation requested", "已请求取消")}
        </p>
      ) : null}
      {observation && progress.problem === "transient" && (
        <p role="status" className="text-sm text-muted-foreground">
          {t(
            "The last verified progress is shown; the latest read failed.",
            "显示上次已验证进度；最近一次读取失败。",
          )}
        </p>
      )}
    </section>
  )
}
