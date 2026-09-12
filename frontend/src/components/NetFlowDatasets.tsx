import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertCircle, Check, Upload } from "lucide-react"
import { type FormEvent, useEffect, useRef, useState } from "react"

import {
  ApiError,
  type NetFlowDatasetPublic,
  type NetFlowDatasetsPublic,
  ProjectsService,
} from "@/client"
import { ResultPagination } from "@/components/ResultPagination"
import { TechnicalValue } from "@/components/TechnicalValue"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useI18n } from "@/lib/i18n"
import { useWorkspaceNavigate, useWorkspaceSearch } from "@/lib/workspace"

const PAGE_SIZE = 10
const MAX_WARNING_SUMMARY = 5

type WarningSummary = {
  code: string
  count: number
}

function warningSummary(
  warning: NetFlowDatasetPublic["warnings"][number],
): WarningSummary {
  const item = warning as Record<string, unknown>
  return {
    code: typeof item.code === "string" ? item.code : "Unknown warning",
    count: typeof item.count === "number" ? item.count : 0,
  }
}

function safeServerMessage(error: Error, fallback: string) {
  if (
    error instanceof ApiError &&
    error.body &&
    typeof error.body === "object"
  ) {
    const detail = (error.body as { detail?: unknown }).detail
    if (detail && typeof detail === "object") {
      const message = (detail as { message?: unknown }).message
      if (typeof message === "string") return message
    }
  }
  return fallback
}

function CountSummary({ dataset }: { dataset: NetFlowDatasetPublic }) {
  const { t } = useI18n()
  return (
    <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
      <div>
        <dt className="text-muted-foreground">
          {t("Raw records", "原始记录数")}
        </dt>
        <dd className="font-medium">{dataset.raw_record_count}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">
          {t("Valid activity records", "有效活动记录数")}
        </dt>
        <dd className="font-medium">{dataset.activity_valid_record_count}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">
          {t("Isolated records", "隔离记录数")}
        </dt>
        <dd className="font-medium">{dataset.isolated_record_count}</dd>
      </div>
    </dl>
  )
}

function QualitySummary({ dataset }: { dataset: NetFlowDatasetPublic }) {
  const { t, formatDate, language, translateValue } = useI18n()
  const formatTime = (value: string | null) => {
    if (!value || Number.isNaN(new Date(value).getTime())) {
      return t("Not available", "不可用")
    }
    return language === "en"
      ? new Date(value).toISOString().replace("T", " ").replace(".000Z", " UTC")
      : formatDate(value, "UTC")
  }
  const warnings = dataset.warnings.map(warningSummary)
  const visibleWarnings = warnings.slice(0, MAX_WARNING_SUMMARY)
  const hiddenWarningCount = warnings.length - visibleWarnings.length

  return (
    <div className="space-y-2 text-sm">
      <p className="font-medium">{t("Quality summary", "质量摘要")}</p>
      <dl className="grid gap-x-4 gap-y-2">
        <div>
          <dt className="text-muted-foreground">{t("Warnings", "警告")}</dt>
          <dd>
            {visibleWarnings.length === 0 ? (
              t("None", "无")
            ) : (
              <ul className="space-y-1">
                {visibleWarnings.map((warning, index) => (
                  <li key={`${warning.code}-${index}`}>
                    {warning.code === "Unknown warning"
                      ? t("Unknown warning", "未知警告")
                      : translateValue(warning.code)}
                    : {warning.count}
                  </li>
                ))}
              </ul>
            )}
            {hiddenWarningCount > 0 && (
              <span className="text-muted-foreground">
                {t(
                  `+${hiddenWarningCount} more warning types`,
                  `另有 ${hiddenWarningCount} 种警告`,
                )}
              </span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">
            {t("Duplicate groups", "重复组数")}
          </dt>
          <dd>{dataset.duplicate_group_count}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">
            {t("Duplicate records", "重复记录数")}
          </dt>
          <dd>{dataset.duplicate_record_count}</dd>
        </div>
      </dl>
      <p>
        <span className="text-muted-foreground">
          {t("Valid time range: ", "有效时间范围：")}
        </span>
        {formatTime(dataset.valid_time_start_utc)} —{" "}
        {formatTime(dataset.valid_time_end_utc)}
      </p>
    </div>
  )
}

function DatasetIdentity({ dataset }: { dataset: NetFlowDatasetPublic }) {
  const { t } = useI18n()
  return (
    <details className="min-w-0 text-sm">
      <summary className="cursor-pointer">
        {t("Dataset details", "数据集详情")}
      </summary>
      <dl className="mt-2 space-y-2">
        <div>
          <dt>{t("Dataset ID", "数据集 ID")}</dt>
          <dd>
            <TechnicalValue
              value={dataset.id}
              label={t("Dataset ID", "数据集 ID")}
            />
          </dd>
        </div>
        <div>
          <dt>{t("RAW SHA-256", "原始 SHA-256")}</dt>
          <dd>
            <TechnicalValue
              value={dataset.raw_sha256}
              label={t("RAW SHA-256", "原始 SHA-256")}
            />
          </dd>
        </div>
      </dl>
    </details>
  )
}

function DatasetDetails({ dataset }: { dataset: NetFlowDatasetPublic }) {
  const { t, formatDate } = useI18n()
  return (
    <div className="space-y-3">
      <div>
        <p className="break-all font-medium">{dataset.display_filename}</p>
        <p className="text-sm text-muted-foreground">
          {t("Accepted: ", "接受时间：")}
          {formatDate(dataset.created_at)}
        </p>
      </div>
      <CountSummary dataset={dataset} />
      <QualitySummary dataset={dataset} />
      <DatasetIdentity dataset={dataset} />
    </div>
  )
}

function DatasetAction({
  dataset,
  pending,
  onSelect,
}: {
  dataset: NetFlowDatasetPublic
  pending: boolean
  onSelect: () => void
}) {
  const { t } = useI18n()
  return (
    <LoadingButton
      type="button"
      variant="outline"
      size="sm"
      loading={pending}
      aria-label={t(
        `Select ${dataset.display_filename} as current NetFlowDataset`,
        `将 ${dataset.display_filename} 设为当前 NetFlow 数据集`,
      )}
      onClick={onSelect}
    >
      <Check />
      {t("Select", "选择")}
    </LoadingButton>
  )
}

function DatasetTable({
  datasets,
  currentId,
  canSelect,
  selectingId,
  onSelect,
}: {
  datasets: NetFlowDatasetPublic[]
  currentId: string | null
  canSelect: boolean
  selectingId: string | null
  onSelect: (datasetId: string) => void
}) {
  const { t, formatDate } = useI18n()
  if (datasets.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {t("No NetFlowDatasets yet.", "尚无 NetFlow 数据集。")}
      </p>
    )
  }

  return (
    <>
      <div className="hidden overflow-x-auto lg:block">
        <Table className="table-fixed">
          <TableHeader>
            <TableRow>
              <TableHead className="w-[35%]">
                {t("Dataset", "数据集")}
              </TableHead>
              <TableHead className="w-1/5">{t("Records", "记录数")}</TableHead>
              <TableHead className="w-[30%]">{t("Quality", "质量")}</TableHead>
              <TableHead className="w-[15%] text-right">
                {t("Action", "操作")}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {datasets.map((dataset) => {
              const isCurrent = dataset.id === currentId
              return (
                <TableRow key={dataset.id}>
                  <TableCell className="whitespace-normal">
                    <p className="break-all font-medium">
                      {dataset.display_filename}
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {t("Accepted: ", "接受时间：")}
                      {formatDate(dataset.created_at)}
                    </p>
                    {isCurrent && (
                      <Badge className="mt-1">{t("Current", "当前")}</Badge>
                    )}
                    <DatasetIdentity dataset={dataset} />
                  </TableCell>
                  <TableCell>
                    <p>
                      {t("Raw:", "原始：")} {dataset.raw_record_count}
                    </p>
                    <p>
                      {t("Valid:", "有效：")}{" "}
                      {dataset.activity_valid_record_count}
                    </p>
                    <p>
                      {t("Isolated:", "隔离：")} {dataset.isolated_record_count}
                    </p>
                  </TableCell>
                  <TableCell className="whitespace-normal break-all">
                    <QualitySummary dataset={dataset} />
                  </TableCell>
                  <TableCell className="text-right">
                    {!isCurrent && canSelect && (
                      <DatasetAction
                        dataset={dataset}
                        pending={selectingId === dataset.id}
                        onSelect={() => onSelect(dataset.id)}
                      />
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
      <div className="space-y-3 lg:hidden">
        {datasets.map((dataset) => {
          const isCurrent = dataset.id === currentId
          return (
            <Card key={dataset.id}>
              <CardContent className="space-y-4 pt-6">
                <DatasetDetails dataset={dataset} />
                {isCurrent && <Badge>{t("Current", "当前")}</Badge>}
                {!isCurrent && canSelect && (
                  <DatasetAction
                    dataset={dataset}
                    pending={selectingId === dataset.id}
                    onSelect={() => onSelect(dataset.id)}
                  />
                )}
              </CardContent>
            </Card>
          )
        })}
      </div>
    </>
  )
}

export default function NetFlowDatasets({
  projectId,
  archived = false,
}: {
  projectId: string
  archived?: boolean
}) {
  const { t, message: translateMessage } = useI18n()
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const inputHeading = useRef<HTMLHeadingElement>(null)
  const [selectedFilename, setSelectedFilename] = useState<string | null>(null)
  const search = useWorkspaceSearch()
  const navigate = useWorkspaceNavigate()
  const page = (search.netflow_page ?? 1) - 1
  const [message, setMessage] = useState<string | null>(null)

  const queryKey = ["netflow-datasets", projectId, page]
  const datasetsQuery = useQuery<NetFlowDatasetsPublic>({
    queryKey,
    queryFn: () =>
      ProjectsService.readNetflowDatasets({
        projectId,
        skip: page * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
  })

  useEffect(() => {
    if (!datasetsQuery.data) return
    const pageCount = Math.max(
      1,
      Math.ceil(datasetsQuery.data.count / PAGE_SIZE),
    )
    if (page >= pageCount) {
      void navigate({
        search: (prev) => ({
          ...prev,
          netflow_page: pageCount > 1 ? pageCount : undefined,
        }),
        replace: true,
      })
    }
  }, [datasetsQuery.data, navigate, page])

  const invalidateAfterMutation = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ["netflow-datasets", projectId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["governance-runs", projectId],
      }),
    ])
  }

  const uploadMutation = useMutation({
    mutationFn: (file: File) =>
      ProjectsService.createNetflowDataset({
        projectId,
        formData: { file },
      }),
    onSuccess: async () => {
      setMessage("NetFlowDataset upload accepted successfully.")
      if (fileInputRef.current) fileInputRef.current.value = ""
      setSelectedFilename(null)
      void navigate({
        search: (prev) => ({ ...prev, netflow_page: undefined }),
      })
      await invalidateAfterMutation()
    },
    onError: (error: Error) =>
      setMessage(
        safeServerMessage(
          error,
          "The NetFlowDataset upload could not be accepted.",
        ),
      ),
  })

  const selectionMutation = useMutation({
    mutationFn: (datasetId: string) =>
      ProjectsService.selectCurrentNetflowDataset({
        projectId,
        datasetId,
      }),
    onSuccess: async () => {
      setMessage("Current NetFlowDataset updated successfully.")
      await invalidateAfterMutation()
      inputHeading.current?.focus()
    },
    onError: (error: Error) =>
      setMessage(
        safeServerMessage(
          error,
          "The current NetFlowDataset could not be changed.",
        ),
      ),
  })

  const clearMutation = useMutation({
    mutationFn: () =>
      ProjectsService.clearCurrentNetflowDataset({
        projectId,
      }),
    onSuccess: async () => {
      setMessage("Current NetFlowDataset cleared successfully.")
      await invalidateAfterMutation()
      inputHeading.current?.focus()
    },
    onError: (error: Error) =>
      setMessage(
        safeServerMessage(
          error,
          "The current NetFlowDataset could not be cleared.",
        ),
      ),
  })

  if (datasetsQuery.isPending)
    return (
      <p role="status">
        {t("Loading NetFlowDatasets…", "正在加载 NetFlow 数据集…")}
      </p>
    )
  if (datasetsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertCircle />
        <AlertTitle>
          {t("NetFlowDatasets could not be loaded", "无法加载 NetFlow 数据集")}
        </AlertTitle>
        <AlertDescription>
          {t("Please try again later.", "请稍后重试。")}
        </AlertDescription>
      </Alert>
    )
  }

  const datasets = datasetsQuery.data
  const canUpload = !archived && datasets.can_upload
  const canSelect = !archived && datasets.can_select
  const currentDataset = datasets.current_netflow_dataset
  const currentId = currentDataset?.id ?? datasets.current_netflow_dataset_id

  const submitUpload = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const file = fileInputRef.current?.files?.[0]
    if (!file) {
      setMessage("Choose one .csv or .txt file to upload.")
      return
    }
    setMessage(null)
    uploadMutation.mutate(file)
  }

  return (
    <section aria-labelledby="netflow-datasets-title" className="space-y-6">
      <div>
        <h2
          ref={inputHeading}
          tabIndex={-1}
          id="netflow-datasets-title"
          className="text-xl font-semibold tracking-tight"
        >
          {t("NetFlowDatasets", "NetFlow 数据集")}
        </h2>
        <p className="text-muted-foreground">
          {t(
            "Accepted NetFlow datasets are immutable. Authorized operators can change the Project current NetFlow selection.",
            "已接受的 NetFlow 数据集不可修改。获得授权的操作员可更改项目当前选择的 NetFlow 数据集。",
          )}
        </p>
      </div>

      {currentDataset ? (
        <Card>
          <CardHeader>
            <CardTitle>
              {t("Current NetFlowDataset", "当前 NetFlow 数据集")}
            </CardTitle>
            <CardDescription>
              {t(
                "Project current NetFlow selection",
                "项目当前选择的 NetFlow 数据集",
              )}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <DatasetDetails dataset={currentDataset} />
            {canSelect && (
              <LoadingButton
                type="button"
                variant="outline"
                loading={clearMutation.isPending}
                onClick={() => {
                  setMessage(null)
                  clearMutation.mutate()
                }}
              >
                {t("Clear current", "清除当前选择")}
              </LoadingButton>
            )}
          </CardContent>
        </Card>
      ) : (
        <Alert>
          <AlertCircle />
          <AlertTitle>
            {t("No current NetFlowDataset", "未选择当前 NetFlow 数据集")}
          </AlertTitle>
          <AlertDescription>
            {t(
              "This Project has no current NetFlow selection.",
              "此项目尚未选择当前 NetFlow 数据集。",
            )}
          </AlertDescription>
        </Alert>
      )}

      {canUpload ? (
        <Card>
          <CardHeader>
            <CardTitle>
              {t("Upload NetFlowDataset", "上传 NetFlow 数据集")}
            </CardTitle>
            <CardDescription>
              {t(
                "Choose one .csv or .txt file. The server performs authoritative validation.",
                "请选择一个 .csv 或 .txt 文件。服务器执行权威校验。",
              )}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="flex flex-col gap-3 sm:flex-row sm:items-end"
              onSubmit={submitUpload}
            >
              <div className="min-w-0 flex-1 space-y-2">
                <Label htmlFor="netflow-dataset-file">
                  {t("NetFlow dataset file", "NetFlow 数据集文件")}
                </Label>
                <div className="flex items-center gap-3">
                  <input
                    ref={fileInputRef}
                    id="netflow-dataset-file"
                    name="file"
                    type="file"
                    accept=".csv,.txt,text/csv,text/plain"
                    className="sr-only"
                    tabIndex={-1}
                    disabled={uploadMutation.isPending}
                    onChange={(event) =>
                      setSelectedFilename(event.target.files?.[0]?.name ?? null)
                    }
                  />
                  <Button
                    type="button"
                    variant="outline"
                    disabled={uploadMutation.isPending}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    {t("Choose file", "选择文件")}
                  </Button>
                  <span className="min-w-0 break-all text-sm">
                    {selectedFilename ?? t("No file chosen", "未选择文件")}
                  </span>
                </div>
              </div>
              <LoadingButton type="submit" loading={uploadMutation.isPending}>
                <Upload />
                {t("Upload", "上传")}
              </LoadingButton>
            </form>
          </CardContent>
        </Card>
      ) : (
        !archived && (
          <p className="text-sm text-muted-foreground">
            {t(
              "You have read-only access to NetFlowDataset inputs for this Project.",
              "您对此项目的 NetFlow 数据集输入仅有只读权限。",
            )}
          </p>
        )
      )}

      {message && (
        <p role="status" className="text-sm">
          {translateMessage(message)}
        </p>
      )}

      <Card>
        <CardHeader>
          <CardTitle>
            {t("Accepted NetFlowDatasets", "已接受的 NetFlow 数据集")}
          </CardTitle>
          <CardDescription>
            {t(`${datasets.count} total`, `共 ${datasets.count} 项`)}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <DatasetTable
            datasets={datasets.data}
            currentId={currentId}
            canSelect={canSelect}
            selectingId={
              selectionMutation.isPending
                ? (selectionMutation.variables ?? null)
                : null
            }
            onSelect={(datasetId) => {
              setMessage(null)
              selectionMutation.mutate(datasetId)
            }}
          />
          <ResultPagination
            label={t("NetFlowDatasets", "NetFlow 数据集")}
            count={datasets.count}
            page={page}
            pageSize={PAGE_SIZE}
            onPageChange={(nextPage) =>
              navigate({
                search: (prev) => ({
                  ...prev,
                  netflow_page: nextPage > 0 ? nextPage + 1 : undefined,
                }),
              })
            }
          />
        </CardContent>
      </Card>
    </section>
  )
}
