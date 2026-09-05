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

function warningSummary(
  warning: NetFlowDatasetPublic["warnings"][number],
): WarningSummary {
  const item = warning as Record<string, unknown>
  return {
    code: typeof item.code === "string" ? item.code : "Unknown warning",
    count: typeof item.count === "number" ? item.count : 0,
  }
}

function formatTime(value: string | null) {
  if (!value) return "Not available"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "Not available"
  return date.toISOString().replace("T", " ").replace(".000Z", " UTC")
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
  return (
    <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
      <div>
        <dt className="text-muted-foreground">Raw records</dt>
        <dd className="font-medium">{dataset.raw_record_count}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">Valid activity records</dt>
        <dd className="font-medium">{dataset.activity_valid_record_count}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">Isolated records</dt>
        <dd className="font-medium">{dataset.isolated_record_count}</dd>
      </div>
    </dl>
  )
}

function QualitySummary({ dataset }: { dataset: NetFlowDatasetPublic }) {
  const warnings = dataset.warnings.map(warningSummary)
  const visibleWarnings = warnings.slice(0, MAX_WARNING_SUMMARY)
  const hiddenWarningCount = warnings.length - visibleWarnings.length

  return (
    <div className="space-y-2 text-sm">
      <p className="font-medium">Quality summary</p>
      <dl className="grid gap-x-4 gap-y-2">
        <div>
          <dt className="text-muted-foreground">Warnings</dt>
          <dd>
            {visibleWarnings.length === 0 ? (
              "None"
            ) : (
              <ul className="space-y-1">
                {visibleWarnings.map((warning, index) => (
                  <li key={`${warning.code}-${index}`}>
                    {warning.code}: {warning.count}
                  </li>
                ))}
              </ul>
            )}
            {hiddenWarningCount > 0 && (
              <span className="text-muted-foreground">
                +{hiddenWarningCount} more warning types
              </span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Duplicate groups</dt>
          <dd>{dataset.duplicate_group_count}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Duplicate records</dt>
          <dd>{dataset.duplicate_record_count}</dd>
        </div>
      </dl>
      <p>
        <span className="text-muted-foreground">Valid time range: </span>
        {formatTime(dataset.valid_time_start_utc)} —{" "}
        {formatTime(dataset.valid_time_end_utc)}
      </p>
    </div>
  )
}

function DatasetDetails({ dataset }: { dataset: NetFlowDatasetPublic }) {
  return (
    <div className="space-y-3">
      <div>
        <p className="font-medium">{dataset.display_filename}</p>
        <p className="break-all font-mono text-xs text-muted-foreground">
          Dataset ID: {dataset.id}
        </p>
      </div>
      <dl>
        <div>
          <dt className="text-muted-foreground">RAW SHA-256</dt>
          <dd className="break-all font-mono text-xs">{dataset.raw_sha256}</dd>
        </div>
      </dl>
      <CountSummary dataset={dataset} />
      <QualitySummary dataset={dataset} />
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
  return (
    <LoadingButton
      type="button"
      variant="outline"
      size="sm"
      loading={pending}
      aria-label={`Select ${dataset.display_filename} as current NetFlowDataset`}
      onClick={onSelect}
    >
      <Check />
      Select
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
  if (datasets.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No NetFlowDatasets yet.</p>
    )
  }

  return (
    <>
      <div className="hidden overflow-x-auto lg:block">
        <Table className="table-fixed">
          <TableHeader>
            <TableRow>
              <TableHead className="w-1/5">Dataset</TableHead>
              <TableHead className="w-1/5">RAW SHA-256</TableHead>
              <TableHead className="w-[15%]">Records</TableHead>
              <TableHead className="w-[30%]">Quality</TableHead>
              <TableHead className="w-[15%] text-right">Action</TableHead>
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
                      Dataset ID: {dataset.id}
                    </p>
                    {isCurrent && <Badge className="mt-1">Current</Badge>}
                  </TableCell>
                  <TableCell className="max-w-xs break-all font-mono text-xs">
                    {dataset.raw_sha256}
                  </TableCell>
                  <TableCell>
                    <p>Raw: {dataset.raw_record_count}</p>
                    <p>Valid: {dataset.activity_valid_record_count}</p>
                    <p>Isolated: {dataset.isolated_record_count}</p>
                  </TableCell>
                  <TableCell className="break-all">
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
                {isCurrent && <Badge>Current</Badge>}
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
      setMessage("NetFlowDataset upload accepted successfully.")
      if (fileInputRef.current) fileInputRef.current.value = ""
      setPage(0)
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
    return <p role="status">Loading NetFlowDatasets…</p>
  if (datasetsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertCircle />
        <AlertTitle>NetFlowDatasets could not be loaded</AlertTitle>
        <AlertDescription>Please try again later.</AlertDescription>
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
          id="netflow-datasets-title"
          className="text-xl font-semibold tracking-tight"
        >
          NetFlowDatasets
        </h2>
        <p className="text-muted-foreground">
          Accepted NetFlow datasets are immutable. Authorized operators can
          change the Project current NetFlow selection.
        </p>
      </div>

      {currentDataset ? (
        <Card>
          <CardHeader>
            <CardTitle>Current NetFlowDataset</CardTitle>
            <CardDescription>Project current NetFlow selection</CardDescription>
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
                Clear current
              </LoadingButton>
            )}
          </CardContent>
        </Card>
      ) : (
        <Alert>
          <AlertCircle />
          <AlertTitle>No current NetFlowDataset</AlertTitle>
          <AlertDescription>
            This Project has no current NetFlow selection.
          </AlertDescription>
        </Alert>
      )}

      {canUpload ? (
        <Card>
          <CardHeader>
            <CardTitle>Upload NetFlowDataset</CardTitle>
            <CardDescription>
              Choose one .csv or .txt file. The server performs authoritative
              validation.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="flex flex-col gap-3 sm:flex-row sm:items-end"
              onSubmit={submitUpload}
            >
              <div className="flex-1 space-y-2">
                <Label htmlFor="netflow-dataset-file">
                  NetFlow dataset file
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
                Upload
              </LoadingButton>
            </form>
          </CardContent>
        </Card>
      ) : (
        !archived && (
          <p className="text-sm text-muted-foreground">
            You have read-only access to NetFlowDataset inputs for this Project.
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
          <CardTitle>Accepted NetFlowDatasets</CardTitle>
          <CardDescription>{datasets.count} total</CardDescription>
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
            label="NetFlowDatasets"
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
