import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { AlertCircle, Archive, Upload } from "lucide-react"
import { type FormEvent, useEffect, useRef, useState } from "react"

import {
  ApiError,
  type CustomerUploadPublic,
  type CustomerUploadWarningPublic,
  type ProjectPublic,
  ProjectsService,
} from "@/client"
import CloudAtlasSources from "@/components/CloudAtlasSources"
import Findings from "@/components/Findings"
import GovernanceReports from "@/components/GovernanceReports"
import GovernanceRuns from "@/components/GovernanceRuns"
import IPAssets from "@/components/IPAssets"
import NetFlowDatasets from "@/components/NetFlowDatasets"
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
import WorkspaceOverview from "@/components/WorkspaceOverview"
import { useI18n } from "@/lib/i18n"
import {
  useWorkspaceContext,
  useWorkspaceNavigate,
  useWorkspaceSearch,
} from "@/lib/workspace"

const UPLOAD_PAGE_SIZE = 10

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  head: () => ({
    meta: [
      {
        title: "Project inputs - Exposure Agent",
      },
    ],
  }),
})

function safeUploadErrorMessage(error: Error): string {
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
  return "The upload could not be accepted. Please try again."
}

function HeaderList({ title, headers }: { title: string; headers: string[] }) {
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium">{title}</h3>
      <div className="flex flex-wrap gap-2">
        {headers.map((header) => (
          <Badge key={header} variant="secondary">
            {header}
          </Badge>
        ))}
      </div>
    </div>
  )
}

function WarningSummary({
  warnings,
}: {
  warnings: CustomerUploadWarningPublic[]
}) {
  const { t, translateValue } = useI18n()
  if (warnings.length === 0)
    return <span className="text-muted-foreground">{t("None", "无")}</span>
  return (
    <ul className="space-y-1">
      {warnings.map((warning) => (
        <li key={`${warning.code}-${warning.field ?? "none"}`}>
          {translateValue(warning.code)}
          {warning.field ? ` (${warning.field})` : ""}: {warning.count}
        </li>
      ))}
    </ul>
  )
}

function UploadRows({
  uploads,
  currentUploadId,
  canSelect,
  selectingUploadId,
  onSelect,
}: {
  uploads: CustomerUploadPublic[]
  currentUploadId: string | null
  canSelect: boolean
  selectingUploadId: string | null
  onSelect: (uploadId: string) => void
}) {
  const { t, formatDate } = useI18n()
  if (uploads.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {t("No accepted uploads yet.", "尚无已接受的上传。")}
      </p>
    )
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("File", "文件")}</TableHead>
          <TableHead>{t("Records", "记录数")}</TableHead>
          <TableHead>{t("Profile", "配置")}</TableHead>
          <TableHead>{t("Warnings", "警告")}</TableHead>
          <TableHead>{t("Accepted", "接受时间")}</TableHead>
          <TableHead>{t("Status", "状态")}</TableHead>
          <TableHead>{t("Action", "操作")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {uploads.map((upload) => {
          const isCurrent = upload.id === currentUploadId
          return (
            <TableRow key={upload.id}>
              <TableCell className="max-w-72 whitespace-normal break-words font-medium">
                {upload.display_filename}
                <details className="mt-2 text-sm font-normal">
                  <summary className="cursor-pointer">
                    {t("Upload details", "上传详情")}
                  </summary>
                  <dl className="mt-2 space-y-2">
                    <div>
                      <dt>{t("CustomerUpload ID", "客户上传 ID")}</dt>
                      <dd>
                        <TechnicalValue value={upload.id} />
                      </dd>
                    </div>
                    <div>
                      <dt>SHA-256</dt>
                      <dd>
                        <TechnicalValue value={upload.raw_sha256} />
                      </dd>
                    </div>
                    <div>
                      <dt>{t("Profile ID", "配置 ID")}</dt>
                      <dd>
                        <TechnicalValue value={upload.profile_id} />
                      </dd>
                    </div>
                  </dl>
                </details>
              </TableCell>
              <TableCell>{upload.record_count}</TableCell>
              <TableCell>
                <div>v{upload.profile_version}</div>
              </TableCell>
              <TableCell className="whitespace-normal">
                <WarningSummary warnings={upload.warnings} />
              </TableCell>
              <TableCell>{formatDate(upload.created_at)}</TableCell>
              <TableCell>
                {isCurrent ? (
                  <Badge>{t("Current", "当前")}</Badge>
                ) : (
                  <span className="text-muted-foreground">
                    {t("Available", "可用")}
                  </span>
                )}
              </TableCell>
              <TableCell>
                {canSelect && !isCurrent && (
                  <LoadingButton
                    type="button"
                    variant="outline"
                    size="sm"
                    loading={selectingUploadId === upload.id}
                    disabled={selectingUploadId !== null}
                    onClick={() => onSelect(upload.id)}
                  >
                    {t("Set as current input", "设为当前输入")}
                  </LoadingButton>
                )}
              </TableCell>
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}

function ProjectInputs({ project }: { project: ProjectPublic }) {
  const { t, message, formatDate } = useI18n()
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [selectedFilename, setSelectedFilename] = useState<string | null>(null)
  const search = useWorkspaceSearch()
  const navigate = useWorkspaceNavigate()
  const page = (search.upload_page ?? 1) - 1
  const setPage = (value: number | ((current: number) => number)) => {
    const next = typeof value === "function" ? value(page) : value
    void navigate({
      search: (previous) => ({
        ...previous,
        upload_page: next === 0 ? undefined : next + 1,
      }),
    })
  }
  const [fileMessage, setFileMessage] = useState<string | null>(null)
  const [selectionMessage, setSelectionMessage] = useState<string | null>(null)

  const profileQuery = useQuery({
    queryKey: ["customer-upload-profile", project.id],
    queryFn: () =>
      ProjectsService.readCurrentCustomerUploadProfile({
        projectId: project.id,
      }),
  })
  const uploadsQuery = useQuery({
    queryKey: ["customer-uploads", project.id, page],
    queryFn: () =>
      ProjectsService.readCustomerUploads({
        projectId: project.id,
        skip: page * UPLOAD_PAGE_SIZE,
        limit: UPLOAD_PAGE_SIZE,
      }),
  })
  const uploadMutation = useMutation({
    mutationFn: (file: File) =>
      ProjectsService.createCustomerUpload({
        projectId: project.id,
        formData: { file },
      }),
    onSuccess: async () => {
      setFileMessage("Upload accepted successfully.")
      if (fileInputRef.current) fileInputRef.current.value = ""
      setSelectedFilename(null)
      setPage(0)
      await queryClient.invalidateQueries({
        queryKey: ["customer-uploads", project.id],
      })
    },
    onError: (error: Error) => setFileMessage(safeUploadErrorMessage(error)),
  })
  const selectionMutation = useMutation({
    mutationFn: (uploadId: string) =>
      ProjectsService.selectCurrentCustomerUpload({
        projectId: project.id,
        uploadId,
      }),
    onSuccess: async () => {
      setSelectionMessage("Current Project input updated successfully.")
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["customer-uploads", project.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["governance-runs", project.id],
        }),
      ])
    },
    onError: () =>
      setSelectionMessage("The current Project input could not be changed."),
  })

  if (profileQuery.isPending || uploadsQuery.isPending) {
    return (
      <p role="status">{t("Loading Project inputs…", "正在加载项目输入…")}</p>
    )
  }
  if (profileQuery.isError || uploadsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertCircle />
        <AlertTitle>
          {t("Project inputs could not be loaded", "无法加载项目输入")}
        </AlertTitle>
        <AlertDescription>
          {t("Please try again later.", "请稍后重试。")}
        </AlertDescription>
      </Alert>
    )
  }

  const profile = profileQuery.data
  const uploads = uploadsQuery.data
  const currentUpload = uploads.data.find(
    (upload) => upload.id === uploads.current_customer_upload_id,
  )
  const canGoBack = page > 0
  const canGoForward = (page + 1) * UPLOAD_PAGE_SIZE < uploads.count

  const submitUpload = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const file = fileInputRef.current?.files?.[0]
    if (!file) {
      setFileMessage("Choose one XLSX file to upload.")
      return
    }
    setFileMessage(null)
    uploadMutation.mutate(file)
  }

  return (
    <div className="space-y-6">
      {project.archived_at && (
        <Alert>
          <Archive />
          <AlertTitle>{t("Archived Project", "已归档项目")}</AlertTitle>
          <AlertDescription>
            {t(
              "Existing inputs remain visible, but this Project cannot accept uploads.",
              "现有输入仍可查看，但此项目不再接受上传。",
            )}
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>
            {t("Current CustomerUpload Profile", "当前客户上传配置")}
          </CardTitle>
          <CardDescription>
            {t("Version", "版本")} {profile.version}
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-5 md:grid-cols-3">
          <HeaderList
            title={t("Required headers", "必需表头")}
            headers={profile.required_headers}
          />
          <HeaderList
            title={t("Warning headers", "警告表头")}
            headers={profile.warning_headers}
          />
          <HeaderList
            title={t("Optional headers", "可选表头")}
            headers={profile.optional_headers}
          />
          <details className="min-w-0 text-sm md:col-span-3">
            <summary className="cursor-pointer">
              {t("Profile details", "配置详情")}
            </summary>
            <div className="mt-2">
              <TechnicalValue
                value={profile.id}
                label={t("Profile ID", "配置 ID")}
              />
            </div>
          </details>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("Current Project input", "项目当前输入")}</CardTitle>
          <CardDescription>
            {t(
              "Governance uses one explicitly selected accepted CustomerUpload.",
              "治理使用一个明确选定且已接受的客户上传。",
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {uploads.current_customer_upload_id ? (
            <div className="space-y-2">
              <p className="break-words font-medium">
                {currentUpload?.display_filename ??
                  t("Current selected input", "当前已选输入")}
              </p>
              {currentUpload && (
                <p className="text-sm text-muted-foreground">
                  {formatDate(currentUpload.created_at)} ·{" "}
                  {t(
                    `${currentUpload.record_count} records`,
                    `${currentUpload.record_count} 条记录`,
                  )}{" "}
                  · {t("Profile v", "配置版本 v")}
                  {currentUpload.profile_version}
                </p>
              )}
              <details className="text-sm">
                <summary className="cursor-pointer">
                  {t("Current input details", "当前输入详情")}
                </summary>
                <div className="mt-2">
                  <TechnicalValue
                    value={uploads.current_customer_upload_id}
                    label={t("Current CustomerUpload ID", "当前客户上传 ID")}
                  />
                </div>
              </details>
            </div>
          ) : (
            <Alert>
              <AlertCircle />
              <AlertTitle>{t("Not ready", "尚未就绪")}</AlertTitle>
              <AlertDescription>
                {t(
                  "Project input is not ready. Select one accepted CustomerUpload.",
                  "项目输入尚未就绪。请选择一个已接受的客户上传。",
                )}
              </AlertDescription>
            </Alert>
          )}
          {selectionMessage && (
            <p className="text-sm" role="status">
              {message(selectionMessage)}
            </p>
          )}
        </CardContent>
      </Card>

      {uploads.can_upload ? (
        <Card>
          <CardHeader>
            <CardTitle>{t("Upload XLSX", "上传 XLSX")}</CardTitle>
            <CardDescription>
              {t(
                "Choose one .xlsx file. The server performs all authoritative validation.",
                "请选择一个 .xlsx 文件。服务器执行所有权威校验。",
              )}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="flex flex-col gap-3 sm:flex-row sm:items-end"
              onSubmit={submitUpload}
            >
              <div className="min-w-0 flex-1 space-y-2">
                <Label htmlFor="customer-upload">
                  {t("XLSX file", "XLSX 文件")}
                </Label>
                <div className="flex items-center gap-3">
                  <input
                    ref={fileInputRef}
                    id="customer-upload"
                    name="file"
                    type="file"
                    accept=".xlsx"
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
            {fileMessage && (
              <p className="mt-3 text-sm" role="status">
                {message(fileMessage)}
              </p>
            )}
          </CardContent>
        </Card>
      ) : (
        !project.archived_at && (
          <p className="text-sm text-muted-foreground">
            {t(
              "You have read-only access to CustomerUpload inputs for this Project.",
              "您对此项目的客户上传输入仅有只读权限。",
            )}
          </p>
        )
      )}

      <Card>
        <CardHeader>
          <CardTitle>{t("Accepted uploads", "已接受的上传")}</CardTitle>
          <CardDescription>
            {t(`${uploads.count} total`, `共 ${uploads.count} 项`)}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <UploadRows
            uploads={uploads.data}
            currentUploadId={uploads.current_customer_upload_id}
            canSelect={uploads.can_select}
            selectingUploadId={
              selectionMutation.isPending
                ? (selectionMutation.variables ?? null)
                : null
            }
            onSelect={(uploadId) => {
              setSelectionMessage(null)
              selectionMutation.mutate(uploadId)
            }}
          />
          {(canGoBack || canGoForward) && (
            <div className="flex items-center justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={!canGoBack}
                onClick={() => setPage((current) => current - 1)}
              >
                {t("Previous", "上一页")}
              </Button>
              <span className="text-sm">
                {t(`Page ${page + 1}`, `第 ${page + 1} 页`)}
              </span>
              <Button
                type="button"
                variant="outline"
                disabled={!canGoForward}
                onClick={() => setPage((current) => current + 1)}
              >
                {t("Next", "下一页")}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function Dashboard() {
  const { t } = useI18n()
  const {
    search,
    projectId,
    runId,
    project,
    projects,
    reports,
    latest,
    report,
  } = useWorkspaceContext()
  const view = search.view ?? "overview"
  useEffect(() => {
    document.title = t(
      "Project workspace - Exposure Agent",
      "项目工作区 - Exposure Agent",
    )
  }, [t])
  if (projects.isPending)
    return <p role="status">{t("Loading Projects…", "正在加载项目…")}</p>
  if (projects.isError)
    return (
      <Alert variant="destructive">
        <AlertTitle>
          {t("Projects could not be loaded", "无法加载项目")}
        </AlertTitle>
        <AlertDescription>
          {t("Please try again later.", "请稍后重试。")}
        </AlertDescription>
      </Alert>
    )
  if (!projects.data.data.length)
    return (
      <p>{t("No accessible Projects are available.", "暂无可访问的项目。")}</p>
    )
  if (!project)
    return (
      <p role="status">
        {projectId === undefined
          ? t("Selecting a Project…", "正在选择项目…")
          : t(
              "Project unavailable. Select an accessible Project.",
              "项目不可用，请选择可访问的项目。",
            )}
      </p>
    )

  let content: React.ReactNode
  switch (view) {
    case "inputs":
      content = (
        <>
          <ProjectInputs key={project.id} project={project} />
          <NetFlowDatasets
            key={`netflow:${project.id}`}
            projectId={project.id}
            archived={project.archived_at !== null}
          />
        </>
      )
      break
    case "cloudatlas":
      content = <CloudAtlasSources key={project.id} projectId={project.id} />
      break
    case "runs":
      content = <GovernanceRuns key={project.id} projectId={project.id} />
      break
    case "assets":
      content = <IPAssets key={project.id} projectId={project.id} />
      break
    case "findings":
      content = <Findings key={project.id} projectId={project.id} />
      break
    default:
      if (reports.isError || (latest.isError && runId === undefined)) {
        content = (
          <Alert variant="destructive">
            <AlertTitle>
              {t("Published results could not be loaded", "无法加载已发布结果")}
            </AlertTitle>
            <AlertDescription>
              {t(
                "No other Run has been substituted. Try again.",
                "未替换为其他运行，请重试。",
              )}
              <Button
                variant="outline"
                onClick={() => {
                  void reports.refetch()
                  if (runId === undefined) void latest.refetch()
                }}
              >
                {t("Try again", "重试")}
              </Button>
            </AlertDescription>
          </Alert>
        )
      } else if (
        reports.isPending ||
        (runId === undefined &&
          (reports.isFetching || latest.isPending || latest.isFetching))
      ) {
        content = (
          <p role="status">
            {t("Loading published results…", "正在加载已发布结果…")}
          </p>
        )
      } else if (!runId || !report) {
        content = (
          <Alert>
            <AlertTitle>
              {runId
                ? t("Published Run unavailable", "已发布运行不可用")
                : t("Results are being prepared", "结果准备中")}
            </AlertTitle>
            <AlertDescription>
              {runId
                ? t(
                    "This explicit Run is unavailable. No other Run has been substituted.",
                    "所选运行不可用，未替换为其他运行。",
                  )
                : t(
                    "No compatible published result is available. Use input, source and run management to prepare a result.",
                    "暂无兼容的已发布结果，可通过输入、来源和运行管理准备结果。",
                  )}
            </AlertDescription>
          </Alert>
        )
      } else {
        content =
          view === "reports" ? (
            <GovernanceReports
              key={`${project.id}:${runId}`}
              projectId={project.id}
              runId={runId}
              reportId={report.id}
            />
          ) : (
            <WorkspaceOverview
              key={`${project.id}:${runId}`}
              projectId={project.id}
              runId={runId}
              reportId={report.id}
            />
          )
      }
  }
  return (
    <div className="min-w-0 space-y-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">{project.name}</h1>
        {view !== "overview" && view !== "reports" && (
          <p className="text-sm text-muted-foreground">
            {t(
              "Current project management. Published reading context is preserved; current inputs and Findings are not historical Run facts.",
              "当前项目管理。已保留发布结果阅读上下文；当前输入和发现项并非历史运行事实。",
            )}
          </p>
        )}
      </header>
      {content}
    </div>
  )
}
