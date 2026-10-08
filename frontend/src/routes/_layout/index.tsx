import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link, Navigate } from "@tanstack/react-router"
import { AlertCircle, Archive, Upload } from "lucide-react"
import { type FormEvent, useEffect, useRef, useState } from "react"

import {
  ApiError,
  CustomerLedgerService,
  type CustomerUploadPublic,
  type CustomerUploadWarningPublic,
  type ProjectPublic,
  ProjectsService,
  type ReplacementPreview,
  type ReplacementReceipt,
  type ReplacementRequest,
} from "@/client"
import CloudAtlasSources from "@/components/CloudAtlasSources"
import CreateProject, { CreateProjectLink } from "@/components/CreateProject"
import Findings from "@/components/Findings"
import GovernanceReports from "@/components/GovernanceReports"
import GovernanceRuns from "@/components/GovernanceRuns"
import IPAssets from "@/components/IPAssets"
import NetFlowDatasets from "@/components/NetFlowDatasets"
import { NetflowInputManagement } from "@/components/NetflowInputManagement"
import ProjectPreparation from "@/components/ProjectPreparation"
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
import useAuth from "@/hooks/useAuth"
import { useI18n } from "@/lib/i18n"
import { requestDigest } from "@/lib/ledgerIntent"
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
                    {t("Preview replacement", "预览替换")}
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

type ReplacementIntent = {
  key: string
  digest: string
  request: ReplacementRequest
}

function ProjectInputs({
  project,
  actorId,
}: {
  project: ProjectPublic
  actorId: string
}) {
  const { t, message, formatDate } = useI18n()
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const currentInputTitle = useRef<HTMLDivElement>(null)
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
  const replacementStorage = `exposure:customer-replacement:${actorId}:${project.id}`
  const alive = useRef(true)
  const starting = useRef(false)
  const [preparing, setPreparing] = useState(false)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  const [pendingReplacement, setPendingReplacement] =
    useState<ReplacementIntent | null>(() => {
      try {
        const item = JSON.parse(
          sessionStorage.getItem(replacementStorage) ?? "null",
        ) as ReplacementIntent | null
        const id = (value: unknown, nullable = false) =>
          (nullable && value === null) ||
          (typeof value === "string" && /^[0-9a-f-]{36}$/i.test(value))
        return item &&
          /^[A-Za-z0-9_-]{1,128}$/.test(item.key) &&
          /^[a-f0-9]{64}$/.test(item.digest) &&
          id(item.request?.candidate_upload_id) &&
          id(item.request?.expected_profile_id) &&
          id(item.request?.expected_upload_id, true) &&
          id(item.request?.expected_revision_id, true)
          ? item
          : null
      } catch {
        return null
      }
    })
  const [canReplay, setCanReplay] = useState(false)
  const [replacement, setReplacement] = useState<{
    request: ReplacementRequest
    preview: ReplacementPreview
  } | null>(null)

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
  const writable = useRef(false)
  writable.current = !!uploadsQuery.data?.can_select && !uploadsQuery.isError
  const clearIntent = () => {
    sessionStorage.removeItem(replacementStorage)
    setPendingReplacement(null)
    setCanReplay(false)
  }
  useEffect(() => {
    if (
      uploadsQuery.data?.can_select === false ||
      (uploadsQuery.isError &&
        uploadsQuery.error instanceof ApiError &&
        [401, 403, 404].includes(uploadsQuery.error.status))
    ) {
      setReplacement(null)
      setPendingReplacement(null)
      setCanReplay(false)
      sessionStorage.removeItem(replacementStorage)
    }
  }, [
    uploadsQuery.data?.can_select,
    uploadsQuery.isError,
    uploadsQuery.error,
    replacementStorage,
  ])
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
    mutationFn: async (uploadId: string) => {
      const current = await CustomerLedgerService.readCustomerLedger({
        projectId: project.id,
        skip: 0,
        limit: 1,
      })
      const request: ReplacementRequest = {
        candidate_upload_id: uploadId,
        expected_upload_id: current.current_upload_id,
        expected_revision_id: current.current_revision_id,
        expected_profile_id: current.current_profile_id,
      }
      const preview =
        await CustomerLedgerService.previewCustomerUploadReplacement({
          projectId: project.id,
          requestBody: request,
        })
      return { request, preview }
    },
    onSuccess: (result) => {
      if (!alive.current || !writable.current) return
      setReplacement(result)
      setSelectionMessage(null)
    },
    onError: () => {
      if (alive.current)
        setSelectionMessage(
          t(
            "Could not read the replacement preview. Reload the current version and try again.",
            "无法读取替换预览，请重新读取当前版本后重试。",
          ),
        )
    },
  })
  const validReceipt = (
    receipt: ReplacementReceipt,
    intent: ReplacementIntent,
  ) => {
    if (
      receipt.project_id !== project.id ||
      receipt.created_by !== actorId ||
      receipt.candidate_upload_id !== intent.request.candidate_upload_id ||
      receipt.expected_upload_id !== intent.request.expected_upload_id ||
      receipt.expected_revision_id !== intent.request.expected_revision_id ||
      receipt.expected_profile_id !== intent.request.expected_profile_id ||
      receipt.request_sha256 !== intent.digest
    )
      throw new Error("Replacement receipt identity mismatch")
    return receipt
  }
  const replacementSaved = async () => {
    if (!alive.current || !writable.current) return
    clearIntent()
    setReplacement(null)
    setSelectionMessage(
      t(
        "Replacement confirmed. Current data has been reloaded; history is unchanged.",
        "替换操作已确认。已重新读取当前数据，历史版本保持不变。",
      ),
    )
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ["customer-uploads", project.id],
      }),
      queryClient.invalidateQueries({
        queryKey: ["customer-ledger", actorId, project.id],
      }),
      queryClient.invalidateQueries({
        queryKey: ["governance-runs", project.id],
      }),
    ])
    if (alive.current) currentInputTitle.current?.focus()
  }
  const applyReplacement = useMutation({
    mutationFn: async (intent: ReplacementIntent) => {
      if ((await requestDigest(intent.request)) !== intent.digest)
        throw new Error("Invalid saved request")
      return validReceipt(
        await CustomerLedgerService.applyCustomerUploadReplacement({
          projectId: project.id,
          idempotencyKey: intent.key,
          requestBody: intent.request,
        }),
        intent,
      )
    },
    onSuccess: replacementSaved,
    onError: (error) => {
      if (!alive.current) return
      setCanReplay(false)
      if (
        error instanceof ApiError &&
        [400, 401, 403, 404, 409, 422].includes(error.status)
      ) {
        clearIntent()
        setSelectionMessage(
          error.status === 409
            ? t(
                "The current version or profile changed. This request was rejected; preview the latest version again.",
                "当前版本或配置已变化，本次请求被拒绝，请重新预览最新版本。",
              )
            : t(
                "Replacement was rejected. Check access and the accepted file before previewing again.",
                "替换请求被拒绝，请核对权限与已接受文件后重新预览。",
              ),
        )
      } else {
        setSelectionMessage(
          t(
            "The replacement outcome is unknown. Read the saved operation before submitting again.",
            "替换结果尚未确认，请先读取原操作回执，再决定是否重新提交。",
          ),
        )
      }
    },
  })
  const startReplacement = async () => {
    if (
      !replacement ||
      pendingReplacement ||
      starting.current ||
      !writable.current
    )
      return
    starting.current = true
    setPreparing(true)
    try {
      const intent = {
        key: crypto.randomUUID(),
        request: replacement.request,
        digest: await requestDigest(replacement.request),
      }
      if (!alive.current || !writable.current) return
      sessionStorage.setItem(replacementStorage, JSON.stringify(intent))
      setPendingReplacement(intent)
      setCanReplay(false)
      setReplacement(null)
      applyReplacement.mutate(intent)
    } catch {
      if (alive.current)
        setSelectionMessage(
          t(
            "The request could not be saved. Nothing was submitted.",
            "无法保存操作身份，尚未提交替换。",
          ),
        )
    } finally {
      starting.current = false
      if (alive.current) setPreparing(false)
    }
  }
  const recoverReplacement = useMutation({
    mutationFn: async (intent: ReplacementIntent) =>
      validReceipt(
        await CustomerLedgerService.readCustomerUploadReplacement({
          projectId: project.id,
          operationKey: intent.key,
        }),
        intent,
      ),
    onSuccess: replacementSaved,
    onError: (error) => {
      if (!alive.current) return
      const missing = error instanceof ApiError && error.status === 404
      setCanReplay(missing && writable.current)
      setSelectionMessage(
        missing
          ? t(
              "No completed receipt yet. You may explicitly resend the same request with its original identity; the server will recover any committed operation.",
              "尚无完成回执。可明确复用原标识重新提交同一请求，服务端会恢复任何已提交操作。",
            )
          : t(
              "Could not read the operation. Keep its identity and retry this read.",
              "无法读取操作回执。已保留原标识，请重试读取。",
            ),
      )
    },
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
          <CardTitle
            ref={currentInputTitle}
            role="heading"
            aria-level={3}
            tabIndex={-1}
          >
            {t("Current Project input", "项目当前输入")}
          </CardTitle>
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

      {replacement && (
        <Card aria-live="polite">
          <CardHeader>
            <CardTitle>{t("Replacement preview", "替换预览")}</CardTitle>
            <CardDescription>
              {t(
                "Apply replaces the complete current register and clears local edits for the new file. It does not change history.",
                "应用会以新文件完整替换当前台账，并清除新文件的本地修订；不会改变历史版本。",
              )}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <dl className="grid gap-3 text-sm sm:grid-cols-3">
              <div>
                <dt className="text-muted-foreground">
                  {t("Current records / IPs", "当前条目 / IP")}
                </dt>
                <dd>
                  {replacement.preview.current_record_count} /{" "}
                  {replacement.preview.current_unique_ips}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">
                  {t("New records / IPs", "新条目 / IP")}
                </dt>
                <dd>
                  {replacement.preview.candidate_record_count} /{" "}
                  {replacement.preview.candidate_unique_ips}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">
                  {t(
                    "Added / removed / changed IPs",
                    "新增 / 移出 / 声明变化 IP",
                  )}
                </dt>
                <dd>
                  {replacement.preview.added_ips} /{" "}
                  {replacement.preview.removed_ips} /{" "}
                  {replacement.preview.changed_ip_declarations}
                </dd>
              </div>
            </dl>
            <div className="flex flex-wrap gap-2">
              <LoadingButton
                type="button"
                loading={preparing || applyReplacement.isPending}
                disabled={!!pendingReplacement || !uploads.can_select}
                onClick={() => void startReplacement()}
              >
                {t("Apply replacement", "应用替换")}
              </LoadingButton>
              <Button
                type="button"
                variant="outline"
                disabled={preparing || applyReplacement.isPending}
                onClick={() => {
                  setReplacement(null)
                }}
              >
                {t("Cancel", "取消")}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {pendingReplacement && (
        <Alert>
          <AlertTitle>
            {applyReplacement.isPending
              ? t("Applying replacement…", "正在应用替换…")
              : t("Replacement outcome unknown", "替换结果未知")}
          </AlertTitle>
          <AlertDescription className="flex flex-wrap items-center gap-2">
            <span>
              {t(
                "Recover the saved request before starting another replacement.",
                "请先恢复已保存的请求，再开始新的替换。",
              )}
            </span>
            <LoadingButton
              type="button"
              size="sm"
              variant="outline"
              loading={recoverReplacement.isPending}
              disabled={applyReplacement.isPending}
              onClick={() => recoverReplacement.mutate(pendingReplacement)}
            >
              {t("Recover result", "恢复结果")}
            </LoadingButton>
            {canReplay && (
              <LoadingButton
                type="button"
                size="sm"
                variant="outline"
                loading={applyReplacement.isPending}
                disabled={recoverReplacement.isPending || !uploads.can_select}
                onClick={() => {
                  setCanReplay(false)
                  applyReplacement.mutate(pendingReplacement)
                }}
              >
                {t("Resend original request", "复用原请求提交")}
              </LoadingButton>
            )}
          </AlertDescription>
        </Alert>
      )}

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
            canSelect={uploads.can_select && !pendingReplacement && !preparing}
            selectingUploadId={
              selectionMutation.isPending
                ? (selectionMutation.variables ?? null)
                : null
            }
            onSelect={(uploadId) => {
              if (pendingReplacement || preparing) return
              setSelectionMessage(null)
              setReplacement(null)
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
  const { user } = useAuth()
  const navigate = useWorkspaceNavigate()
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
  if (!user) return null
  if (view === "create") return <CreateProject />
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
  if (view === "cloudatlas-ledger")
    return project ? (
      <Navigate
        to="/projects/$projectId/cloudatlas-ledger"
        params={{ projectId: project.id }}
        search={{ asset_view: "synced" }}
        replace
      />
    ) : (
      <section className="space-y-3">
        <h1 className="text-2xl font-bold">
          {t("Internet exposure assets", "互联网暴露面资产")}
        </h1>
        <p role="status">
          {t(
            "Select an accessible project above to read synced assets. No Run or customer input is required.",
            "请使用上方项目选择器选择可访问项目，阅读已同步资产；无需 Run 或客户输入。",
          )}
        </p>
        {!projects.data.data.length && <CreateProjectLink />}
      </section>
    )
  if (!projects.data.data.length)
    return (
      <section className="mx-auto max-w-2xl space-y-5 py-10">
        <h1 className="text-3xl font-semibold tracking-tight">
          {t("Your first comparison starts here", "从这里开始首轮比对")}
        </h1>
        <p className="text-muted-foreground">
          {t(
            "No accessible projects yet. Create one to prepare your asset register and external observations. If you cannot create projects, ask an administrator for access.",
            "暂无可访问的项目。创建项目后准备资产台账和外部观测；没有创建权限时，请联系管理员授予访问权限。",
          )}
        </p>
        <CreateProjectLink />
      </section>
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

  if (search.view === undefined && search.run === undefined) {
    return (
      <Navigate
        to="/projects/$projectId/netflow-correlation"
        params={{ projectId: project.id }}
        search={{}}
        replace
      />
    )
  }

  let content: React.ReactNode
  switch (view) {
    case "inputs":
    case "cloudatlas":
      content = (
        <>
          <ProjectPreparation
            key={`preparation:${project.id}`}
            projectId={project.id}
            archived={project.archived_at !== null}
          />
          <div id="customer-inputs" tabIndex={-1} className="scroll-mt-32">
            <ProjectInputs
              key={`${user.id}:${project.id}`}
              actorId={user.id}
              project={project}
            />
          </div>
          <section
            id="cloudatlas-inputs"
            tabIndex={-1}
            className="scroll-mt-32 space-y-3 border-t pt-6"
            aria-labelledby="cloud-access-title"
          >
            <h2 id="cloud-access-title" className="text-xl font-semibold">
              {t("CloudAtlas data access", "云图数据接入")}
            </h2>
            <p className="max-w-prose text-sm text-muted-foreground">
              {t(
                "Source configuration, sync scope, attempts and published versions use the same controls as the CloudAtlas data page. Opening them only reads local records.",
                "来源配置、同步范围、执行记录和已发布版本，与云图数据页使用同一套操作入口。打开只读取本地记录。",
              )}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button asChild variant="outline">
                <Link
                  to="/projects/$projectId/cloudatlas-ledger"
                  params={{ projectId: project.id }}
                  search={{ asset_view: "synced", external_manage: "sources" }}
                >
                  {t("Configure sources and sync", "配置来源与同步")}
                </Link>
              </Button>
              <Button asChild variant="outline">
                <Link
                  to="/projects/$projectId/cloudatlas-ledger"
                  params={{ projectId: project.id }}
                  search={{ asset_view: "synced" }}
                >
                  {t("Read current CloudAtlas assets", "阅读当前云图资产")}
                </Link>
              </Button>
            </div>
            <details className="space-y-3 text-sm">
              <summary className="cursor-pointer">
                {t("Historical Run source settings", "旧 Run 来源配置（兼容）")}
              </summary>
              <CloudAtlasSources
                key={`${user.id}:${project.id}`}
                projectId={project.id}
              />
            </details>
          </section>
          <div id="netflow-inputs" tabIndex={-1} className="scroll-mt-32">
            <NetFlowDatasets
              key={`netflow:${project.id}`}
              projectId={project.id}
              archived={project.archived_at !== null}
            />
            <div
              id="netflow-processing"
              tabIndex={-1}
              className="mt-5 scroll-mt-32"
            >
              <NetflowInputManagement
                key={`${user.id}:${project.id}:${search.processing_dataset ?? "current"}`}
                actor={user.id}
                projectId={project.id}
                datasetId={search.processing_dataset}
                isAdmin={!!user.is_superuser}
                canWrite={!project.archived_at}
                onDatasetChange={(id) => {
                  void navigate({
                    search: (previous) => ({
                      ...previous,
                      processing_dataset: id,
                    }),
                    hash: "netflow-processing",
                    replace: true,
                  })
                }}
              />
            </div>
          </div>
        </>
      )
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
          (reports.isFetching ||
            latest.isPending ||
            latest.isFetching ||
            latest.data !== null))
      ) {
        content = (
          <p role="status">
            {t("Loading published results…", "正在加载已发布结果…")}
          </p>
        )
      } else if (runId === undefined || !report) {
        content =
          runId === undefined ? (
            <ProjectPreparation
              key={`preparation:${project.id}`}
              projectId={project.id}
              archived={project.archived_at !== null}
            />
          ) : (
            <Alert>
              <AlertTitle>
                {t("Published Run unavailable", "已发布运行不可用")}
              </AlertTitle>
              <AlertDescription>
                {t(
                  "This explicit Run is unavailable. No other Run has been substituted.",
                  "所选运行不可用，未替换为其他运行。",
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
      <header className="flex flex-wrap items-start justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight">{project.name}</h1>
        {view === "overview" && report && (
          <Button asChild variant="outline">
            <Link to="/" search={{ project: project.id, view: "inputs" }}>
              {t("Start a new comparison", "开始新一轮比对")}
            </Link>
          </Button>
        )}
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
