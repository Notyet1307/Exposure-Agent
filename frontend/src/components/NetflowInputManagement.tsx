import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { useEffect, useMemo, useState } from "react"
import {
  type AnalysisPublic,
  type ContextPublic,
  NetflowProcessingService,
  ProjectsService,
} from "@/client"
import { NetflowAnalysisActions } from "@/components/NetflowAnalysisActions"
import { NetflowContextForm } from "@/components/NetflowContextForm"
import { ResultPagination } from "@/components/ResultPagination"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"
import { netflowText } from "@/lib/netflow-labels"

const SIZE = 25
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export function NetflowInputManagement({
  actor,
  projectId,
  datasetId,
  onDatasetChange,
  isAdmin,
  canWrite = isAdmin,
}: {
  actor: string
  projectId: string
  datasetId?: string
  onDatasetChange: (id: string) => void
  isAdmin: boolean
  canWrite?: boolean
}) {
  const { t, formatDate } = useI18n()
  const cache = useQueryClient()
  const [page, setPage] = useState(0)
  const [analysisPage, setAnalysisPage] = useState(0)
  const [selectedAnalysis, setSelectedAnalysis] = useState<AnalysisPublic>()
  const explicit = datasetId !== undefined
  const validExplicit = !explicit || uuid.test(datasetId ?? "")
  const key = useMemo(
    () => [
      "netflow-input-management",
      actor,
      projectId,
      datasetId ?? "current",
    ],
    [actor, datasetId, projectId],
  )
  useEffect(() => {
    setPage(0)
    setAnalysisPage(0)
    setSelectedAnalysis(undefined)
    return () => {
      void cache.cancelQueries({ queryKey: key })
      cache.removeQueries({ queryKey: key })
    }
  }, [cache, key])
  const datasets = useQuery({
    queryKey: [...key, "datasets", page],
    enabled: validExplicit,
    queryFn: () =>
      ProjectsService.readNetflowDatasets({
        projectId,
        skip: page * SIZE,
        limit: SIZE,
      }),
  })
  const selectedId = explicit
    ? datasetId
    : (datasets.data?.current_netflow_dataset?.id ??
      datasets.data?.current_netflow_dataset_id)
  const selected = selectedId
    ? (datasets.data?.data.find((row) => row.id === selectedId) ??
      (datasets.data?.current_netflow_dataset?.id === selectedId
        ? datasets.data.current_netflow_dataset
        : undefined))
    : undefined
  const contexts = useQuery({
    queryKey: [...key, "contexts", selectedId],
    enabled: validExplicit && Boolean(selectedId),
    queryFn: () =>
      NetflowProcessingService.readContexts({
        projectId,
        datasetId: selectedId!,
        limit: SIZE,
      }),
  })
  const currentId = contexts.data?.data[0]?.current_context_revision_id
  const currentContext = useQuery({
    queryKey: [...key, "context", selectedId, currentId],
    enabled: Boolean(selectedId && currentId),
    queryFn: async () => {
      const value = await NetflowProcessingService.readContexts({
        projectId,
        datasetId: selectedId!,
        contextRevisionId: currentId!,
        limit: 1,
      })
      const row = value.data[0]
      if (!row || row.context_revision_id !== currentId)
        throw new Error("Context identity mismatch")
      return row
    },
  })
  const analyses = useQuery({
    queryKey: [...key, "analyses", selectedId, analysisPage],
    enabled: Boolean(selectedId),
    queryFn: () =>
      NetflowProcessingService.readAnalyses({
        projectId,
        datasetId: selectedId!,
        skip: analysisPage * SIZE,
        limit: SIZE,
      }),
  })
  const refresh = () => {
    void cache.invalidateQueries({ queryKey: [...key, "contexts"] })
    void cache.invalidateQueries({ queryKey: [...key, "context"] })
    void cache.invalidateQueries({ queryKey: [...key, "analyses"] })
  }
  const current = currentContext.data
  const actionAnalysis =
    selectedAnalysis &&
    selectedAnalysis.context_revision_id === current?.context_revision_id
      ? selectedAnalysis
      : undefined
  if (!validExplicit)
    return (
      <p role="alert">
        {t(
          "The selected NetFlow upload is invalid.",
          "所选 NetFlow 上传无效。",
        )}{" "}
      </p>
    )
  return (
    <section
      className="space-y-4"
      aria-label={t("NetFlow data input", "NetFlow 数据接入")}
    >
      <header>
        <h2 className="text-lg font-semibold">
          {t("NetFlow processing", "NetFlow 处理")}
        </h2>
        <p className="text-sm text-muted-foreground">
          {t(
            "Upload acceptance and processing status are separate. Processing starts only after an explicit action.",
            "上传接受状态与处理状态分开显示；只有明确操作才会启动处理。",
          )}
        </p>
      </header>
      {datasets.isError ? (
        <p role="alert">
          {t(
            "NetFlow upload metadata could not be read.",
            "无法读取 NetFlow 上传元数据。",
          )}
        </p>
      ) : null}
      {!explicit && !datasets.isPending && !selectedId && (
        <div className="space-y-2">
          <p>
            {t(
              "Choose an accepted NetFlow upload.",
              "请选择已接受的 NetFlow 上传文件。",
            )}
          </p>
          {datasets.data?.data.map((row) => (
            <Button
              key={row.id}
              variant="outline"
              onClick={() => onDatasetChange(row.id)}
            >
              {row.display_filename} · {formatDate(row.created_at)}
            </Button>
          ))}
          <ResultPagination
            label={t("Uploads", "上传文件")}
            count={datasets.data?.count ?? 0}
            page={page}
            pageSize={SIZE}
            onPageChange={setPage}
          />
        </div>
      )}
      {selectedId && (
        <div className="space-y-4 rounded border p-4">
          <p className="text-sm">
            {selected
              ? `${selected.display_filename} · ${formatDate(selected.created_at)}`
              : t(
                  "Reading selected upload metadata…",
                  "正在读取所选上传元数据…",
                )}
          </p>
          {contexts.isError || currentContext.isError ? (
            <p role="alert">
              {t(
                "The current processing context could not be read.",
                "无法读取当前处理上下文。",
              )}
            </p>
          ) : null}
          <NetflowContextForm
            actor={actor}
            projectId={projectId}
            datasetId={selectedId}
            current={current as ContextPublic | undefined}
            currentResolved={
              !contexts.isPending && (!currentId || currentContext.isSuccess)
            }
            isAdmin={isAdmin && canWrite}
            onCreated={() => refresh()}
            onRefresh={refresh}
          />
          {current?.state === "CONFIRMED" && (
            <NetflowAnalysisActions
              actor={actor}
              projectId={projectId}
              datasetId={selectedId}
              contextId={current.context_revision_id}
              analysis={actionAnalysis}
              canWrite={canWrite}
              onAnalysis={(value) => {
                setSelectedAnalysis(value)
                refresh()
              }}
            />
          )}
          <div className="space-y-2">
            <h3 className="font-medium">
              {t("Processing history", "处理历史")}
            </h3>
            {analyses.isError ? (
              <p role="alert">
                {t(
                  "Processing history could not be read.",
                  "无法读取处理历史。",
                )}
              </p>
            ) : null}
            {analyses.data?.data.map((row) => (
              <div
                key={row.analysis_id}
                className="flex flex-wrap items-center justify-between gap-2 rounded border p-2 text-sm"
              >
                <span>
                  {netflowText(row.status, t)} ·{" "}
                  {formatDate(row.completed_at ?? row.created_at)}
                </span>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setSelectedAnalysis(row)}
                  >
                    {t("Select", "选择")}
                  </Button>
                  {row.pipeline_complete && row.can_read_result && (
                    <Link
                      className="underline"
                      to="/projects/$projectId/netflow-results"
                      params={{ projectId }}
                      search={{
                        analysis: row.analysis_id,
                        dataset: row.dataset_id,
                      }}
                    >
                      {t("Read result", "查看结果")}
                    </Link>
                  )}
                </div>
              </div>
            ))}
            <ResultPagination
              label={t("Processing history", "处理历史")}
              count={analyses.data?.count ?? 0}
              page={analysisPage}
              pageSize={SIZE}
              onPageChange={setAnalysisPage}
            />
          </div>
        </div>
      )}
    </section>
  )
}
