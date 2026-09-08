import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertCircle, Check, Upload } from "lucide-react"
import { type FormEvent, useEffect, useRef, useState } from "react"

import {
  ApiError,
  type NetFlowDatasetPublic,
  type NetFlowDatasetsPublic,
  ProjectsService,
} from "@/client"
import { useLocale } from "@/components/LocaleProvider"
import { ResultPagination } from "@/components/ResultPagination"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
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

const PAGE_SIZE = 10
const MAX_WARNING_SUMMARY = 5

type WarningSummary = {
  code: string
  count: number
}

type Text = (zh: string, en: string) => string

function warningSummary(
  warning: NetFlowDatasetPublic["warnings"][number],
): WarningSummary {
  const item = warning as Record<string, unknown>
  return {
    code: typeof item.code === "string" ? item.code : "unknown_warning",
    count: typeof item.count === "number" ? item.count : 0,
  }
}

function warningLabel(code: string, text: Text) {
  return (
    {
      netflow_invalid_count: text("无效计数", "Invalid count"),
      netflow_invalid_ip: text("无效 IP", "Invalid IP"),
      netflow_invalid_port: text("无效端口", "Invalid port"),
      netflow_invalid_protocol: text("无效协议", "Invalid protocol"),
      netflow_invalid_tcp_flags: text("无效 TCP 标志", "Invalid TCP flags"),
      netflow_invalid_time: text("无效时间", "Invalid time"),
      netflow_invalid_time_range: text("无效时间范围", "Invalid time range"),
      netflow_unknown_protocol: text("未知协议", "Unknown protocol"),
      netflow_duplicate_records: text("重复记录", "Duplicate records"),
      netflow_ignored_input_columns: text("已忽略的输入列", "Ignored input columns"),
    }[code] ?? text("未识别的质量警告", "Unrecognized quality warning")
  )
}

function formatTime(value: string | null, locale: string, text: Text) {
  if (!value) return text("暂无", "Not available")
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return text("暂无", "Not available")
  if (locale === "en") return date.toISOString().replace("T", " ").replace(".000Z", " UTC")
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium", timeStyle: "medium", timeZone: "UTC",
  }).format(date) + " UTC"
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

function CountSummary({ dataset, text }: { dataset: NetFlowDatasetPublic; text: Text }) {
  return (
    <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
      <div>
        <dt className="text-muted-foreground">{text("原始记录", "Raw records")}</dt>
        <dd className="font-medium">{dataset.raw_record_count}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">{text("有效正向活动记录", "Valid activity records")}</dt>
        <dd className="font-medium">{dataset.activity_valid_record_count}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">{text("隔离记录", "Isolated records")}</dt>
        <dd className="font-medium">{dataset.isolated_record_count}</dd>
      </div>
    </dl>
  )
}

function QualitySummary({ dataset, text, locale }: { dataset: NetFlowDatasetPublic; text: Text; locale: string }) {
  const warnings = dataset.warnings.map(warningSummary)
  const visibleWarnings = warnings.slice(0, MAX_WARNING_SUMMARY)
  const hiddenWarningCount = warnings.length - visibleWarnings.length

  return (
    <div className="space-y-2 text-sm">
      <p className="font-medium">{text("质量摘要", "Quality summary")}</p>
      <dl className="grid gap-x-4 gap-y-2">
        <div>
          <dt className="text-muted-foreground">{text("警告", "Warnings")}</dt>
          <dd>
            {visibleWarnings.length === 0 ? (
              text("无", "None")
            ) : (
              <ul className="space-y-1">
                {visibleWarnings.map((warning, index) => (
                  <li key={`${warning.code}-${index}`}>
                    {text(`${warningLabel(warning.code, text)}（${warning.code}）：${warning.count}`, `${warning.code}: ${warning.count}`)}
                  </li>
                ))}
              </ul>
            )}
            {hiddenWarningCount > 0 && (
              <span className="text-muted-foreground">
                {text(`另有 ${hiddenWarningCount} 类警告`, `+${hiddenWarningCount} more warning types`)}
              </span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{text("重复组", "Duplicate groups")}</dt>
          <dd>{dataset.duplicate_group_count}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{text("重复记录", "Duplicate records")}</dt>
          <dd>{dataset.duplicate_record_count}</dd>
        </div>
      </dl>
      <p>
        <span className="text-muted-foreground">{text("有效时间范围：", "Valid time range: ")}</span>
        {formatTime(dataset.valid_time_start_utc, locale, text)} —{" "}
        {formatTime(dataset.valid_time_end_utc, locale, text)}
      </p>
      <p className="text-muted-foreground">
        {text(
          "未知或没有正向活动证据不代表零流量或零风险。",
          "UNKNOWN or no positive activity evidence does not mean zero traffic or zero risk.",
        )}
      </p>
    </div>
  )
}

function DatasetDetails({ dataset, text, locale }: { dataset: NetFlowDatasetPublic; text: Text; locale: string }) {
  return (
    <div className="space-y-3">
      <div>
        <p className="font-medium">{dataset.display_filename}</p>
        <p className="break-all font-mono text-xs text-muted-foreground">
          {text("数据集 ID：", "Dataset ID: ")}{dataset.id}
        </p>
      </div>
      <dl>
        <div>
        <dt className="text-muted-foreground">{text("原始文件 SHA-256", "RAW SHA-256")}</dt>
          <dd className="break-all font-mono text-xs">{dataset.raw_sha256}</dd>
        </div>
      </dl>
      <CountSummary dataset={dataset} text={text} />
      <QualitySummary dataset={dataset} text={text} locale={locale} />
    </div>
  )
}

function DatasetAction({
  dataset,
  pending,
  onSelect,
  text,
}: {
  dataset: NetFlowDatasetPublic
  pending: boolean
  onSelect: () => void
  text: Text
}) {
  return (
    <LoadingButton
      type="button"
      variant="outline"
      size="sm"
      loading={pending}
      aria-label={text(`将 ${dataset.display_filename} 设为当前 NetFlow 数据集`, `Select ${dataset.display_filename} as current NetFlowDataset`)}
      onClick={onSelect}
    >
      <Check />
      {text("选择", "Select")}
    </LoadingButton>
  )
}

function DatasetTable({
  datasets,
  currentId,
  canSelect,
  selectingId,
  onSelect,
  text,
  locale,
}: {
  datasets: NetFlowDatasetPublic[]
  currentId: string | null
  canSelect: boolean
  selectingId: string | null
  onSelect: (datasetId: string) => void
  text: Text
  locale: string
}) {
  if (datasets.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">{text("尚无 NetFlow 数据集。", "No NetFlowDatasets yet.")}</p>
    )
  }

  return (
    <>
      <div className="hidden overflow-x-auto lg:block">
        <Table className="table-fixed">
          <TableHeader>
            <TableRow>
              <TableHead className="w-1/5">{text("数据集", "Dataset")}</TableHead>
              <TableHead className="w-1/5">{text("原始文件 SHA-256", "RAW SHA-256")}</TableHead>
              <TableHead className="w-[15%]">{text("记录", "Records")}</TableHead>
              <TableHead className="w-[30%]">{text("质量", "Quality")}</TableHead>
              <TableHead className="w-[15%] text-right">{text("操作", "Action")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {datasets.map((dataset) => {
              const isCurrent = dataset.id === currentId
              return (
                <TableRow key={dataset.id}>
                  <TableCell>
                    <p className="font-medium">{dataset.display_filename}</p>
                    <p className="break-all font-mono text-xs text-muted-foreground">
                      {text("数据集 ID：", "Dataset ID: ")}{dataset.id}
                    </p>
                    {isCurrent && <Badge className="mt-1">{text("当前", "Current")}</Badge>}
                  </TableCell>
                  <TableCell className="max-w-xs break-all font-mono text-xs">
                    {dataset.raw_sha256}
                  </TableCell>
                  <TableCell>
                    <p>{text("原始：", "Raw: ")}{dataset.raw_record_count}</p>
                    <p>{text("有效：", "Valid: ")}{dataset.activity_valid_record_count}</p>
                    <p>{text("隔离：", "Isolated: ")}{dataset.isolated_record_count}</p>
                  </TableCell>
                  <TableCell className="break-all">
                    <QualitySummary dataset={dataset} text={text} locale={locale} />
                  </TableCell>
                  <TableCell className="text-right">
                    {!isCurrent && canSelect && (
                      <DatasetAction
                        dataset={dataset}
                        pending={selectingId === dataset.id}
                        onSelect={() => onSelect(dataset.id)}
                        text={text}
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
                <DatasetDetails dataset={dataset} text={text} locale={locale} />
                {isCurrent && <Badge>{text("当前", "Current")}</Badge>}
                {!isCurrent && canSelect && (
                  <DatasetAction
                    dataset={dataset}
                    pending={selectingId === dataset.id}
                    onSelect={() => onSelect(dataset.id)}
                    text={text}
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
  const { locale, text } = useLocale()
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [page, setPage] = useState(0)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    setPage(0)
    setMessage(null)
  }, [])

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
      setMessage(text("NetFlow 数据集上传已接受。", "NetFlowDataset upload accepted successfully."))
      if (fileInputRef.current) fileInputRef.current.value = ""
      setPage(0)
      await invalidateAfterMutation()
    },
    onError: (error: Error) =>
      setMessage(
        safeServerMessage(
          error,
          text("无法接受 NetFlow 数据集上传。", "The NetFlowDataset upload could not be accepted."),
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
      setMessage(text("当前 NetFlow 数据集已更新。", "Current NetFlowDataset updated successfully."))
      await invalidateAfterMutation()
    },
    onError: (error: Error) =>
      setMessage(
        safeServerMessage(
          error,
          text("无法更改当前 NetFlow 数据集。", "The current NetFlowDataset could not be changed."),
        ),
      ),
  })

  const clearMutation = useMutation({
    mutationFn: () =>
      ProjectsService.clearCurrentNetflowDataset({
        projectId,
      }),
    onSuccess: async () => {
      setMessage(text("当前 NetFlow 数据集已清除。", "Current NetFlowDataset cleared successfully."))
      await invalidateAfterMutation()
    },
    onError: (error: Error) =>
      setMessage(
        safeServerMessage(
          error,
          text("无法清除当前 NetFlow 数据集。", "The current NetFlowDataset could not be cleared."),
        ),
      ),
  })

  if (datasetsQuery.isPending)
    return <p role="status">{text("正在加载 NetFlow 数据集…", "Loading NetFlowDatasets…")}</p>
  if (datasetsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertCircle />
        <AlertTitle>{text("无法加载 NetFlow 数据集", "NetFlowDatasets could not be loaded")}</AlertTitle>
        <AlertDescription>{text("请稍后重试。", "Please try again later.")}</AlertDescription>
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
      setMessage(text("请选择一个 .csv 或 .txt 文件上传。", "Choose one .csv or .txt file to upload."))
      return
    }
    setMessage(null)
    uploadMutation.mutate(file)
  }

  return (
    <section aria-labelledby="netflow-datasets-title" className="space-y-6">
      <div>
        <h2
          id="netflow-datasets-title"
          className="text-xl font-semibold tracking-tight"
        >
          {text("NetFlow 数据集", "NetFlowDatasets")}
        </h2>
        <p className="text-muted-foreground">
          {text("已接受的 NetFlow 数据集不可变。获授权的操作员可更改项目当前 NetFlow 选择。", "Accepted NetFlow datasets are immutable. Authorized operators can change the Project current NetFlow selection.")}
        </p>
      </div>

      {currentDataset ? (
        <Card>
          <CardHeader>
            <CardTitle>{text("当前 NetFlow 数据集", "Current NetFlowDataset")}</CardTitle>
            <CardDescription>{text("项目当前 NetFlow 选择", "Project current NetFlow selection")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <DatasetDetails dataset={currentDataset} text={text} locale={locale} />
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
                {text("清除当前选择", "Clear current")}
              </LoadingButton>
            )}
          </CardContent>
        </Card>
      ) : (
        <Alert>
          <AlertCircle />
          <AlertTitle>{text("没有当前 NetFlow 数据集", "No current NetFlowDataset")}</AlertTitle>
          <AlertDescription>
            {text("此项目没有当前 NetFlow 选择。", "This Project has no current NetFlow selection.")}
          </AlertDescription>
        </Alert>
      )}

      {canUpload ? (
        <Card>
          <CardHeader>
            <CardTitle>{text("上传 NetFlow 数据集", "Upload NetFlowDataset")}</CardTitle>
            <CardDescription>
              {text("请选择一个 .csv 或 .txt 文件。服务器会执行权威验证。", "Choose one .csv or .txt file. The server performs authoritative validation.")}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="flex flex-col gap-3 sm:flex-row sm:items-end"
              onSubmit={submitUpload}
            >
              <div className="flex-1 space-y-2">
                <Label htmlFor="netflow-dataset-file">
                  {text("NetFlow 数据集文件", "NetFlow dataset file")}
                </Label>
                <Input
                  ref={fileInputRef}
                  id="netflow-dataset-file"
                  name="file"
                  type="file"
                  accept=".csv,.txt,text/csv,text/plain"
                  disabled={uploadMutation.isPending}
                />
              </div>
              <LoadingButton type="submit" loading={uploadMutation.isPending}>
                <Upload />
                {text("上传", "Upload")}
              </LoadingButton>
            </form>
          </CardContent>
        </Card>
      ) : (
        !archived && (
          <p className="text-sm text-muted-foreground">
            {text("你对此项目的 NetFlow 数据集输入只有只读权限。", "You have read-only access to NetFlowDataset inputs for this Project.")}
          </p>
        )
      )}

      {message && (
        <p role="status" className="text-sm">
          {message}
        </p>
      )}

      <Card>
        <CardHeader>
          <CardTitle>{text("已接受的 NetFlow 数据集", "Accepted NetFlowDatasets")}</CardTitle>
          <CardDescription>{text(`共 ${datasets.count} 个`, `${datasets.count} total`)}</CardDescription>
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
            text={text}
            locale={locale}
          />
          <ResultPagination
            label={text("NetFlow 数据集", "NetFlowDatasets")}
            count={datasets.count}
            page={page}
            pageSize={PAGE_SIZE}
            onPageChange={setPage}
          />
        </CardContent>
      </Card>
    </section>
  )
}
