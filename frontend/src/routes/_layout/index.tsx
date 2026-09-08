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
import CustomerReadingPrototype from "@/components/CustomerReadingPrototype"
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
import { useLocale } from "@/components/LocaleProvider"

const UPLOAD_PAGE_SIZE = 10
const PROJECT_PAGE_SIZE = 100

type DashboardSearch = {
  prototype?: "customer"
  variant?: "A" | "B" | "C"
  reader?: "full"
  reader_section?: "overview" | "matrix" | "lineage" | "report"
  resource_id?: string
  project_id?: string
  tab?: "inputs" | "cloudatlas" | "runs" | "assets" | "findings" | "reports"
}

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
  validateSearch: (search: Record<string, unknown>): DashboardSearch => ({
    prototype: search.prototype === "customer" ? "customer" : undefined,
    variant:
      search.variant === "A" || search.variant === "B" || search.variant === "C"
        ? search.variant
        : undefined,
    reader: search.reader === "full" ? "full" : undefined,
    reader_section:
      search.reader_section === "overview" ||
      search.reader_section === "matrix" ||
      search.reader_section === "lineage" ||
      search.reader_section === "report"
        ? search.reader_section
        : undefined,
    resource_id: typeof search.resource_id === "string" ? search.resource_id : undefined,
    project_id: typeof search.project_id === "string" ? search.project_id : undefined,
    tab:
      search.tab === "inputs" ||
      search.tab === "cloudatlas" ||
      search.tab === "runs" ||
      search.tab === "assets" ||
      search.tab === "findings" ||
      search.tab === "reports"
        ? search.tab
        : undefined,
  }),
  head: () => ({
    meta: [
      {
        title: "Project inputs - Exposure Agent",
      },
    ],
  }),
})

function safeUploadErrorMessage(error: Error, text: (zh: string, en: string) => string): string {
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
  return text("上传未被接受，请重试。", "The upload could not be accepted. Please try again.")
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
  const { text } = useLocale()
  if (warnings.length === 0)
    return <span className="text-muted-foreground">{text("无", "None")}</span>
  return (
    <ul className="space-y-1">
      {warnings.map((warning) => (
        <li key={`${warning.code}-${warning.field ?? "none"}`}>
          {warning.code}
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
  const { text } = useLocale()
  if (uploads.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">{text("尚无已接受的上传文件。", "No accepted uploads yet.")}</p>
    )
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{text("文件", "File")}</TableHead>
          <TableHead>SHA-256</TableHead>
          <TableHead>{text("记录数", "Records")}</TableHead><TableHead>{text("配置", "Profile")}</TableHead><TableHead>{text("警告", "Warnings")}</TableHead><TableHead>{text("接受时间", "Accepted")}</TableHead><TableHead>{text("状态", "Status")}</TableHead><TableHead>{text("操作", "Action")}</TableHead>
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
              <TableCell>
                {new Date(upload.created_at).toLocaleString()}
              </TableCell>
              <TableCell>
                {isCurrent ? (
                  <Badge>{text("当前", "Current")}</Badge>
                ) : (
                  <span className="text-muted-foreground">{text("可选", "Available")}</span>
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
                    设为当前输入
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
  const { text } = useLocale()
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
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
      setFileMessage(text("上传已接受。", "Upload accepted successfully."))
      if (fileInputRef.current) fileInputRef.current.value = ""
      setPage(0)
      await queryClient.invalidateQueries({
        queryKey: ["customer-uploads", project.id],
      })
    },
    onError: (error: Error) => setFileMessage(safeUploadErrorMessage(error, text)),
  })
  const selectionMutation = useMutation({
    mutationFn: (uploadId: string) =>
      ProjectsService.selectCurrentCustomerUpload({
        projectId: project.id,
        uploadId,
      }),
    onSuccess: async () => {
      setSelectionMessage(text("当前项目输入已更新。", "Current Project input updated successfully."))
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
      setSelectionMessage(text("无法更改当前项目输入。", "The current Project input could not be changed.")),
  })

  if (profileQuery.isPending || uploadsQuery.isPending) {
    return <p role="status">{text("正在加载项目输入…", "Loading Project inputs…")}</p>
  }
  if (profileQuery.isError || uploadsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertCircle />
        <AlertTitle>{text("无法加载项目输入", "Project inputs could not be loaded")}</AlertTitle><AlertDescription>{text("请稍后重试。", "Please try again later.")}</AlertDescription>
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
      setFileMessage(text("请选择一个 XLSX 文件上传。", "Choose one XLSX file to upload."))
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
          <AlertTitle>{text("已归档项目", "Archived Project")}</AlertTitle>
          <AlertDescription>
            {text("现有输入仍可查看，但该项目不能接受上传。", "Existing inputs remain visible, but this Project cannot accept uploads.")}
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>{text("当前客户上传配置", "Current CustomerUpload Profile")}</CardTitle>
          <CardDescription>{text("配置 ID", "Profile ID")}<span className="font-mono">{profile.id}</span>{text(" · 版本", " · Version")}{" "}
            {profile.version}
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-5 md:grid-cols-3">
          <HeaderList
            title={text("必填表头", "Required headers")}
            headers={profile.required_headers}
          />
          <HeaderList
            title={text("缺失时提示警告的表头", "Warning headers")}
            headers={profile.warning_headers}
          />
          <HeaderList
            title={text("可选表头", "Optional headers")}
            headers={profile.optional_headers}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{text("当前项目输入", "Current Project input")}</CardTitle>
          <CardDescription>{text("治理使用已明确选择并通过校验的客户资产表。", "Governance uses one explicitly selected accepted CustomerUpload.")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {uploads.current_customer_upload_id ? (
            <p>{text("当前客户资产表 ID", "Current CustomerUpload ID")}{" "}
              <span className="break-all font-mono text-sm">
                {uploads.current_customer_upload_id}
              </span>
            </p>
          ) : (
            <Alert>
              <AlertCircle />
              <AlertTitle>{text("尚未就绪", "Not ready")}</AlertTitle>
              <AlertDescription>{text("项目输入尚未就绪，请选择一份已通过校验的客户资产表。", "Project input is not ready. Select one accepted CustomerUpload.")}</AlertDescription>
            </Alert>
          )}
          {selectionMessage && (
            <p className="text-sm" role="status">
              {selectionMessage}
            </p>
          )}
        </CardContent>
      </Card>

      {uploads.can_upload ? (
        <Card>
          <CardHeader>
            <CardTitle>{text("上传 XLSX", "Upload XLSX")}</CardTitle>
            <CardDescription>{text("选择一个 .xlsx 文件，所有正式校验均由服务器执行。", "Choose one .xlsx file. The server performs all authoritative validation.")}</CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="flex flex-col gap-3 sm:flex-row sm:items-end"
              onSubmit={submitUpload}
            >
              <div className="flex-1 space-y-2">
                <Label htmlFor="customer-upload">{text("XLSX 文件", "XLSX file")}</Label>
                <Input
                  ref={fileInputRef}
                  id="customer-upload"
                  name="file"
                  type="file"
                  accept=".xlsx"
                  disabled={uploadMutation.isPending}
                />
              </div>
              <LoadingButton type="submit" loading={uploadMutation.isPending}>
                <Upload />
                {text("上传", "Upload")}
              </LoadingButton>
            </form>
            {fileMessage && (
              <p className="mt-3 text-sm" role="status">
                {fileMessage}
              </p>
            )}
          </CardContent>
        </Card>
      ) : (
        !project.archived_at && (
          <p className="text-sm text-muted-foreground">{text("你对本项目的客户资产表只有只读权限。", "You have read-only access to CustomerUpload inputs for this Project.")}</p>
        )
      )}

      <Card>
        <CardHeader>
          <CardTitle>{text("已接受的上传文件", "Accepted uploads")}</CardTitle>
          <CardDescription>{uploads.count}{text(" 条", " total")}</CardDescription>
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
              >{text("上一页", "Previous")}</Button>
              <span className="text-sm">{text("页码 ", "Page ")}{page + 1}</span>
              <Button
                type="button"
                variant="outline"
                disabled={!canGoForward}
                onClick={() => setPage((current) => current + 1)}
              >{text("下一页", "Next")}</Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function ProjectWorkspace({
  project,
  defaultTab = "inputs",
}: {
  project: ProjectPublic
  defaultTab?: DashboardSearch["tab"]
}) {
  const { text } = useLocale()

  return (
    <Tabs defaultValue={defaultTab} className="space-y-4">
      <TabsList className="flex h-auto w-full flex-wrap justify-start gap-1 md:w-fit">
        <TabsTrigger value="inputs">{text("输入数据", "Inputs")}</TabsTrigger>
        <TabsTrigger value="cloudatlas">CloudAtlas</TabsTrigger>
        <TabsTrigger value="runs">{text("治理运行", "Runs")}</TabsTrigger>
        <TabsTrigger value="assets">{text("资产", "Assets")}</TabsTrigger>
        <TabsTrigger value="findings">{text("发现项", "Findings")}</TabsTrigger>
        <TabsTrigger value="reports">{text("报告", "Reports")}</TabsTrigger>
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
  const { locale } = useLocale()
  useEffect(() => { document.title = locale === "zh" ? "项目工作区 - Exposure-Agent" : "Project workspace - Exposure-Agent" })
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  if (import.meta.env.DEV && search.prototype === "customer" && !search.tab) {
    return (
      <CustomerReadingPrototype
        variant={search.variant ?? "A"}
        reader={search.reader}
        readerSection={search.reader_section}
        resourceId={search.resource_id}
        onVariantChange={(variant) => {
          void navigate({
            search: (previous) => ({ ...previous, variant }),
            replace: true,
          })
        }}
        onReaderSectionChange={(reader_section, resource_id) => {
          void navigate({
            search: (previous) => ({ ...previous, reader: "full", reader_section, resource_id }),
            replace: true,
          })
        }}
      />
    )
  }
  return <ProjectDashboard />
}

function ProjectDashboard() {
  const { text } = useLocale()

  const search = Route.useSearch()
  const { user: currentUser } = useAuth()
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(
    search.project_id ?? null,
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

  if (projectsQuery.isPending) return <p role="status">{text("正在加载项目…", "Loading Projects…")}</p>
  if (projectsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertCircle />
        <AlertTitle>{text("项目加载失败", "Projects could not be loaded")}</AlertTitle>
        <AlertDescription>{text("请稍后重试。", "Please try again later.")}</AlertDescription>
      </Alert>
    )
  }
  if (projectsQuery.data.data.length === 0) {
    return (
      <div className="space-y-2">
        <h1 className="text-2xl font-bold tracking-tight">{text("项目输入", "Project inputs")}</h1>
        <p className="text-muted-foreground">{text("欢迎回来。", "Welcome back, nice to see you again!")}</p>
        <p className="text-muted-foreground">{text("暂无可访问的项目。", "No accessible Projects are available.")}</p>
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
        <h1 className="text-2xl font-bold tracking-tight">{text("项目工作区", "Project workspace")}</h1>
        <p className="text-muted-foreground">{text("选择项目，管理输入数据、来源、治理运行、资产、发现项与报告。", "Welcome back, nice to see you again! Select a Project to manage its inputs, sources, Runs, Assets, Findings, and Reports.")}{currentUser?.full_name
            ? ` Signed in as ${currentUser.full_name}.`
            : ""}
        </p>
      </div>
      <div className="max-w-md space-y-2">
        <Label id="project-label">{text("项目", "Project")}</Label>
        <Select value={selectedProject.id} onValueChange={setSelectedProjectId}>
          <SelectTrigger className="w-full" aria-labelledby="project-label">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {projectsQuery.data.data.map((project) => (
              <SelectItem key={project.id} value={project.id}>
                {project.name}
                {project.archived_at ? " (Archived)" : ""}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <ProjectWorkspace
        key={`${selectedProject.id}-${search.tab ?? "inputs"}`}
        project={selectedProject}
        defaultTab={search.tab}
      />
    </div>
  )
}
