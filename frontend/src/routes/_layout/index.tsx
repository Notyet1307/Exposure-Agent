import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { AlertCircle, Archive, Upload } from "lucide-react"
import { type FormEvent, useEffect, useRef, useState } from "react"

import {
  ApiError,
  type CustomerUploadPublic,
  type CustomerUploadWarningPublic,
  type ProjectPublic,
  type ProjectsPublic,
  ProjectsService,
} from "@/client"
import CloudAtlasSources from "@/components/CloudAtlasSources"
import Findings from "@/components/Findings"
import GovernanceReports from "@/components/GovernanceReports"
import GovernanceRuns from "@/components/GovernanceRuns"
import IPAssets from "@/components/IPAssets"
import NetFlowDatasets from "@/components/NetFlowDatasets"
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
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useAuth from "@/hooks/useAuth"
import { useI18n } from "@/lib/i18n"

const UPLOAD_PAGE_SIZE = 10
const PROJECT_PAGE_SIZE = 100

async function readAccessibleProjects(): Promise<ProjectsPublic> {
  const firstPage = await ProjectsService.readProjects({
    skip: 0,
    limit: PROJECT_PAGE_SIZE,
  })
  const data = [...firstPage.data]

  while (data.length < firstPage.count) {
    const nextPage = await ProjectsService.readProjects({
      skip: data.length,
      limit: PROJECT_PAGE_SIZE,
    })
    if (nextPage.data.length === 0) break
    data.push(...nextPage.data)
  }

  return { data, count: firstPage.count }
}

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
          <TableHead>SHA-256</TableHead>
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
              <TableCell className="font-medium">
                {upload.display_filename}
              </TableCell>
              <TableCell className="max-w-72 whitespace-normal break-all font-mono text-xs">
                {upload.raw_sha256}
              </TableCell>
              <TableCell>{upload.record_count}</TableCell>
              <TableCell>
                <div>v{upload.profile_version}</div>
                <div className="max-w-48 break-all text-xs text-muted-foreground">
                  {upload.profile_id}
                </div>
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
  const { t, message } = useI18n()
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [selectedFilename, setSelectedFilename] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const [fileMessage, setFileMessage] = useState<string | null>(null)
  const [selectionMessage, setSelectionMessage] = useState<string | null>(null)

  useEffect(() => {
    setPage(0)
    setFileMessage(null)
    setSelectionMessage(null)
  }, [])

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
            {t("Profile ID", "配置 ID")}{" "}
            <span className="font-mono">{profile.id}</span> ·{" "}
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
            <p>
              {t("Current CustomerUpload ID", "当前客户上传 ID")}{" "}
              <span className="break-all font-mono text-sm">
                {uploads.current_customer_upload_id}
              </span>
            </p>
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
              <div className="flex-1 space-y-2">
                <Label htmlFor="customer-upload">
                  {t("XLSX file", "XLSX 文件")}
                </Label>
                <div className="flex items-center gap-3">
                  <Input
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

function ProjectWorkspace({ project }: { project: ProjectPublic }) {
  const { t } = useI18n()
  return (
    <Tabs defaultValue="inputs" className="space-y-4">
      <TabsList className="flex h-auto w-full flex-wrap justify-start gap-1 md:w-fit">
        <TabsTrigger value="inputs">{t("Inputs", "输入")}</TabsTrigger>
        <TabsTrigger value="cloudatlas">CloudAtlas</TabsTrigger>
        <TabsTrigger value="runs">{t("Runs", "运行")}</TabsTrigger>
        <TabsTrigger value="assets">{t("Assets", "资产")}</TabsTrigger>
        <TabsTrigger value="findings">{t("Findings", "发现项")}</TabsTrigger>
        <TabsTrigger value="reports">{t("Reports", "报告")}</TabsTrigger>
      </TabsList>
      <TabsContent value="inputs">
        <ProjectInputs project={project} />
        <NetFlowDatasets
          projectId={project.id}
          archived={project.archived_at !== null}
        />
      </TabsContent>
      <TabsContent value="cloudatlas">
        <CloudAtlasSources projectId={project.id} />
      </TabsContent>
      <TabsContent value="runs">
        <GovernanceRuns projectId={project.id} />
      </TabsContent>
      <TabsContent value="assets">
        <IPAssets projectId={project.id} />
      </TabsContent>
      <TabsContent value="findings">
        <Findings projectId={project.id} />
      </TabsContent>
      <TabsContent value="reports">
        <GovernanceReports projectId={project.id} />
      </TabsContent>
    </Tabs>
  )
}

function Dashboard() {
  const { t } = useI18n()
  useEffect(() => {
    document.title = t(
      "Project inputs - Exposure Agent",
      "项目输入 - Exposure Agent",
    )
  }, [t])
  const { user: currentUser } = useAuth()
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(
    null,
  )
  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: readAccessibleProjects,
  })

  useEffect(() => {
    const firstProject = projectsQuery.data?.data[0]
    if (
      firstProject &&
      !projectsQuery.data?.data.some(
        (project) => project.id === selectedProjectId,
      )
    ) {
      setSelectedProjectId(firstProject.id)
    }
  }, [projectsQuery.data, selectedProjectId])

  if (projectsQuery.isPending)
    return <p role="status">{t("Loading Projects…", "正在加载项目…")}</p>
  if (projectsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertCircle />
        <AlertTitle>
          {t("Projects could not be loaded", "无法加载项目")}
        </AlertTitle>
        <AlertDescription>
          {t("Please try again later.", "请稍后重试。")}
        </AlertDescription>
      </Alert>
    )
  }
  if (projectsQuery.data.data.length === 0) {
    return (
      <div className="space-y-2">
        <h1 className="text-2xl font-bold tracking-tight">
          {t("Project inputs", "项目输入")}
        </h1>
        <p className="text-muted-foreground">
          {t(
            "Welcome back, nice to see you again!",
            "欢迎回来，很高兴再次见到您！",
          )}
        </p>
        <p className="text-muted-foreground">
          {t("No accessible Projects are available.", "暂无可访问的项目。")}
        </p>
      </div>
    )
  }

  const selectedProject =
    projectsQuery.data.data.find(
      (project) => project.id === selectedProjectId,
    ) ?? projectsQuery.data.data[0]

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          {t("Project workspace", "项目工作区")}
        </h1>
        <p className="text-muted-foreground">
          {t(
            "Welcome back, nice to see you again! Select a Project to manage its inputs, sources, Runs, Assets, Findings, and Reports.",
            "欢迎回来，很高兴再次见到您！选择项目以管理其输入、来源、运行、资产、发现项和报告。",
          )}
          {currentUser?.full_name
            ? t(
                ` Signed in as ${currentUser.full_name}.`,
                ` 当前登录：${currentUser.full_name}。`,
              )
            : ""}
        </p>
      </div>
      <div className="max-w-md space-y-2">
        <Label id="project-label">{t("Project", "项目")}</Label>
        <Select value={selectedProject.id} onValueChange={setSelectedProjectId}>
          <SelectTrigger className="w-full" aria-labelledby="project-label">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {projectsQuery.data.data.map((project) => (
              <SelectItem key={project.id} value={project.id}>
                {project.name}
                {project.archived_at ? t(" (Archived)", "（已归档）") : ""}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <ProjectWorkspace key={selectedProject.id} project={selectedProject} />
    </div>
  )
}
