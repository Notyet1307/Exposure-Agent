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
import { DiagnosticDetails } from "@/components/DiagnosticDetails"
import Findings from "@/components/Findings"
import GovernanceReports from "@/components/GovernanceReports"
import GovernanceRuns from "@/components/GovernanceRuns"
import InputReadinessSummary from "@/components/InputReadinessSummary"
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
import { apiErrorDetail, parseWarningDetail } from "@/lib/diagnostics"
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

function uploadError(error: Error): { message: string; detail: unknown } {
  const detail = apiErrorDetail(error)
  const message =
    detail && typeof detail === "object"
      ? (detail as { message?: unknown }).message
      : undefined
  return {
    message:
      typeof message === "string"
        ? message
        : "The upload could not be accepted. Please try again.",
    detail,
  }
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

const warningFieldLabels: Record<string, [string, string]> = {
  asset_ip: ["Asset IP", "资产 IP"],
  start_port: ["Start port", "起始端口"],
  end_port: ["End port", "结束端口"],
  is_web: ["Web interface", "是否 Web 界面"],
  web_url: ["Web URL", "Web 界面 URL"],
  service_type: ["Service", "服务类型"],
  asset_owner: ["Declared owner", "原声明负责人"],
  asset_department: ["Asset department", "资产所属部门"],
  port_owner: ["Port owner", "端口负责人"],
  department: ["Department", "部门"],
  serial: ["Source number", "原序号"],
}

function warningFieldLabel(
  value: string,
  t: (english: string, chinese: string) => string,
) {
  const label = warningFieldLabels[value]
  return label ? t(label[0], label[1]) : value
}

function WarningSummary({
  warnings,
}: {
  warnings: readonly CustomerUploadWarningPublic[]
}) {
  const { t, translateValue } = useI18n()
  if (warnings.length === 0)
    return <span className="text-muted-foreground">{t("None", "无")}</span>
  return (
    <ul className="space-y-2">
      {warnings.map((warning, index) => {
        const detail = parseWarningDetail(
          (warning as { detail?: unknown }).detail,
        )
        return (
          <li key={`${warning.code}-${warning.field ?? "none"}-${index}`}>
            <div>
              {translateValue(warning.code)}
              {warning.field ? ` (${warningFieldLabel(warning.field, t)})` : ""}
              : {warning.count}
            </div>
            {warning.code === "extra_columns_ignored" && detail ? (
              <div className="mt-1 text-xs text-muted-foreground">
                <p>
                  {t(
                    "Ignored columns (original positions):",
                    "已忽略列（原始位置）：",
                  )}
                </p>
                <ul className="list-disc pl-4">
                  {detail.names.map((item) => (
                    <li key={`${item.column}-${item.name}`}>
                      {item.name || t("(unnamed column)", "（未命名列）")}{" "}
                      <span>
                        ({t("column", "第")} {item.column})
                      </span>
                      {item.nearMatch && (
                        <span>
                          {" "}
                          {t("Did you mean", "是否指")}{" "}
                          {warningFieldLabel(item.nearMatch, t)}?
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
                {detail.omittedCount > 0 && (
                  <p>
                    {t(
                      `${detail.omittedCount} more columns omitted.`,
                      `另有 ${detail.omittedCount} 列未显示。`,
                    )}
                  </p>
                )}
                {detail.namesTruncated && (
                  <p>
                    {t(
                      "Some column names are shortened to 64 characters.",
                      "部分列名超过 64 个字符，已截断显示。",
                    )}
                  </p>
                )}
              </div>
            ) : warning.code === "extra_columns_ignored" ? (
              <p className="mt-1 text-xs text-muted-foreground">
                {t(
                  "Column details are unavailable for this historical warning.",
                  "此历史警告没有列明细。",
                )}
              </p>
            ) : null}
          </li>
        )
      })}
    </ul>
  )
}

function UploadRows({
  uploads,
  currentUploadId,
  canSelect,
  actionsDisabled,
  selectingUploadId,
  onSelect,
}: {
  uploads: CustomerUploadPublic[]
  currentUploadId: string | null
  canSelect: boolean
  actionsDisabled: boolean
  selectingUploadId: string | null
  onSelect: (candidate: Candidate, trigger: HTMLButtonElement) => void
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
          const candidate = candidateFromUpload(upload)
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
                    disabled={actionsDisabled || selectingUploadId !== null}
                    onClick={(event) =>
                      onSelect(candidate, event.currentTarget)
                    }
                  >
                    {currentUploadId
                      ? t("Preview replacement", "预览替换")
                      : t("Preview selection", "预览选择")}
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

type Candidate = Readonly<{
  id: string
  name: string
  profileId: string
  profileVersion: number
  recordCount: number
  warnings: readonly CustomerUploadWarningPublic[]
}>

type PreviewValue = Readonly<{
  candidate: Candidate
  request: ReplacementRequest
  impact: ReplacementPreview
}>

type FlowIssue = Readonly<{ message: string; diagnostic?: unknown }>

type CandidateErrorReason = "read" | "version" | "profile" | "key" | "rejected"

type Flow =
  | { kind: "idle" }
  | { kind: "file"; file: File | null; issue?: FlowIssue }
  | { kind: "uploading"; file: File }
  | { kind: "candidate"; candidate: Candidate; replacement: boolean }
  | { kind: "previewing"; candidate: Candidate }
  | { kind: "preview"; value: PreviewValue; issue?: FlowIssue }
  | {
      kind: "candidate-error"
      candidate: Candidate | null
      candidateId: string
      reason: CandidateErrorReason
      issue?: FlowIssue
      diagnostic?: unknown
    }
  | { kind: "already-current"; candidate: Candidate }
  | { kind: "preparing"; value: PreviewValue }
  | {
      kind: "operation"
      intent: ReplacementIntent
      candidate: Candidate | null
      phase: "applying" | "unknown" | "missing"
      recoveryError?: boolean
      diagnostic?: unknown
    }
  | { kind: "confirmed"; receipt: ReplacementReceipt }

const focusHeading =
  "scroll-mt-32 outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"

function candidateFromUpload(upload: CustomerUploadPublic): Candidate {
  return {
    id: upload.id,
    name: upload.display_filename,
    profileId: upload.profile_id,
    profileVersion: upload.profile_version,
    recordCount: upload.record_count,
    warnings: upload.warnings,
  }
}

function readSavedIntent(storage: string): ReplacementIntent | null {
  try {
    const item = JSON.parse(
      sessionStorage.getItem(storage) ?? "null",
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
}

function clearStoredIntent(storage: string) {
  sessionStorage.removeItem(storage)
}

function errorCode(error: unknown): string | null {
  const detail = apiErrorDetail(error)
  if (!detail || typeof detail !== "object" || Array.isArray(detail))
    return null
  const code = (detail as { code?: unknown }).code
  return typeof code === "string" ? code : null
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
  const chooseFileButton = useRef<HTMLButtonElement>(null)
  const candidateHeading = useRef<HTMLDivElement>(null)
  const previewHeading = useRef<HTMLDivElement>(null)
  const errorHeading = useRef<HTMLDivElement>(null)
  const alreadyCurrentHeading = useRef<HTMLDivElement>(null)
  const recoveryHeading = useRef<HTMLDivElement>(null)
  const confirmedHeading = useRef<HTMLDivElement>(null)
  const previewTrigger = useRef<HTMLButtonElement | null>(null)
  const returnPreviewFocus = useRef(false)
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
  const replacementStorage = `exposure:customer-replacement:${actorId}:${project.id}`
  const alive = useRef(true)
  const flowTicket = useRef(0)
  const operationTicket = useRef(0)
  const busy = useRef<"upload" | "preview" | "prepare" | "apply" | null>(null)
  const recoveryPending = useRef(false)
  const [flow, setFlow] = useState<Flow>(() => {
    const intent = readSavedIntent(replacementStorage)
    return intent
      ? { kind: "operation", intent, candidate: null, phase: "unknown" }
      : { kind: "idle" }
  })
  const flowRef = useRef(flow)
  flowRef.current = flow
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
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
  const writable = useRef(false)
  writable.current = !!uploadsQuery.data?.can_select && !uploadsQuery.isError
  const hasCurrentInput = useRef(false)
  hasCurrentInput.current = !!uploadsQuery.data?.current_customer_upload_id
  useEffect(() => {
    const readDenied =
      uploadsQuery.isError &&
      uploadsQuery.error instanceof ApiError &&
      [401, 403, 404].includes(uploadsQuery.error.status)
    const readOnly = uploadsQuery.data?.can_select === false
    if (!readDenied && !readOnly) return
    if (fileInputRef.current) fileInputRef.current.value = ""
    if (!readDenied && flowRef.current.kind === "operation") {
      // A readable Project can lose write access while a submitted operation
      // is still resolvable through its saved receipt.
      flowTicket.current += 1
      return
    }
    flowTicket.current += 1
    operationTicket.current += 1
    busy.current = null
    clearStoredIntent(replacementStorage)
    setFlow((current) =>
      current.kind === "confirmed" ? current : { kind: "idle" },
    )
  }, [
    uploadsQuery.data?.can_select,
    uploadsQuery.isError,
    uploadsQuery.error,
    replacementStorage,
  ])

  const uploadMutation = useMutation({
    mutationFn: ({ file }: { file: File; ticket: number }) =>
      ProjectsService.createCustomerUpload({
        projectId: project.id,
        formData: { file },
      }),
    onSuccess: async (upload, { ticket: uploadTicket }) => {
      if (!alive.current || flowTicket.current !== uploadTicket) return
      busy.current = null
      setFlow({
        kind: "candidate",
        candidate: candidateFromUpload(upload),
        replacement: hasCurrentInput.current,
      })
      if (fileInputRef.current) fileInputRef.current.value = ""
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["customer-uploads", project.id],
        }),
        queryClient.invalidateQueries({
          queryKey: ["input-summary", project.id],
        }),
      ])
    },
    onError: (error: Error, { file, ticket: uploadTicket }) => {
      if (!alive.current || flowTicket.current !== uploadTicket) return
      busy.current = null
      const failure = uploadError(error)
      setFlow({
        kind: "file",
        file,
        issue: { message: failure.message, diagnostic: failure.detail },
      })
    },
  })
  const selectionMutation = useMutation({
    mutationFn: async ({
      candidate,
      ticket: previewTicket,
    }: {
      candidate: Candidate
      ticket: number
    }) => {
      const current = await CustomerLedgerService.readCustomerLedger({
        projectId: project.id,
        skip: 0,
        limit: 1,
      })
      const request: ReplacementRequest = {
        candidate_upload_id: candidate.id,
        expected_upload_id: current.current_upload_id,
        expected_revision_id: current.current_revision_id,
        expected_profile_id: current.current_profile_id,
      }
      if (
        current.current_upload_id !== null &&
        current.current_upload_id === candidate.id
      )
        return {
          kind: "already-current" as const,
          candidate,
          ticket: previewTicket,
        }
      const impact =
        await CustomerLedgerService.previewCustomerUploadReplacement({
          projectId: project.id,
          requestBody: request,
        })
      return {
        kind: "preview" as const,
        candidate,
        request,
        impact,
        ticket: previewTicket,
      }
    },
    onSuccess: (result) => {
      if (
        !alive.current ||
        flowTicket.current !== result.ticket ||
        busy.current !== "preview"
      )
        return
      busy.current = null
      if (!writable.current) {
        setFlow({
          kind: "candidate-error",
          candidate: result.candidate,
          candidateId: result.candidate.id,
          reason: "read",
          issue: {
            message: t(
              "The current input could not be refreshed. Nothing was applied.",
              "无法刷新当前输入，尚未应用任何内容。",
            ),
          },
          diagnostic: {
            code: "current_input_unavailable",
            message:
              "The current input could not be refreshed. Nothing was applied.",
          },
        })
        return
      }
      if (result.kind === "already-current") {
        setFlow({ kind: "already-current", candidate: result.candidate })
        return
      }
      const { request, impact, candidate } = result
      if (
        impact.candidate_upload_id !== request.candidate_upload_id ||
        impact.current_upload_id !== request.expected_upload_id ||
        impact.current_revision_id !== request.expected_revision_id ||
        impact.profile_id !== request.expected_profile_id
      ) {
        setFlow({
          kind: "candidate-error",
          candidate,
          candidateId: candidate.id,
          reason: "read",
          issue: {
            message: t(
              "The preview response did not match the request identity. Nothing was applied.",
              "预览响应与请求身份不一致，尚未应用任何内容。",
            ),
          },
          diagnostic: {
            code: "preview_identity_mismatch",
            message:
              "The preview response did not match the request identity. Nothing was applied.",
          },
        })
        return
      }
      setFlow({
        kind: "preview",
        value: { candidate, request, impact },
      })
    },
    onError: (error, { candidate, ticket: previewTicket }) => {
      if (
        !alive.current ||
        flowTicket.current !== previewTicket ||
        busy.current !== "preview"
      )
        return
      busy.current = null
      setFlow({
        kind: "candidate-error",
        candidate,
        candidateId: candidate.id,
        reason: "read",
        diagnostic: apiErrorDetail(error),
      })
    },
  })
  const previewCandidate = (
    candidate: Candidate,
    trigger: HTMLButtonElement | null,
  ) => {
    if (busy.current || !writable.current) return
    // Previewing an accepted upload abandons any local file choice.
    if (fileInputRef.current?.value) fileInputRef.current.value = ""
    previewTrigger.current = trigger
    const previewTicket = ++flowTicket.current
    busy.current = "preview"
    setFlow({ kind: "previewing", candidate })
    selectionMutation.mutate({ candidate, ticket: previewTicket })
  }
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
  const finishConfirmed = (receipt: ReplacementReceipt) => {
    clearStoredIntent(replacementStorage)
    busy.current = null
    operationTicket.current += 1
    setFlow({ kind: "confirmed", receipt })
    void Promise.all([
      queryClient.invalidateQueries({
        queryKey: ["customer-uploads", project.id],
      }),
      queryClient.invalidateQueries({
        queryKey: ["customer-ledger", actorId, project.id],
      }),
      queryClient.invalidateQueries({
        queryKey: ["governance-runs", project.id],
      }),
      queryClient.invalidateQueries({
        queryKey: ["input-summary", project.id],
      }),
    ]).catch(() => undefined)
  }
  const applyReplacement = useMutation({
    mutationFn: async ({
      intent,
    }: {
      intent: ReplacementIntent
      candidate: Candidate | null
      ticket: number
    }) => {
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
    onSuccess: (receipt, { ticket: applyTicket }) => {
      if (!alive.current || operationTicket.current !== applyTicket) return
      finishConfirmed(receipt)
    },
    onError: (error, { intent, candidate, ticket: applyTicket }) => {
      if (!alive.current || operationTicket.current !== applyTicket) return
      busy.current = null
      const detail = apiErrorDetail(error)
      const status = error instanceof ApiError ? error.status : null
      if (status !== null && [400, 401, 403, 404, 409, 422].includes(status)) {
        clearStoredIntent(replacementStorage)
        operationTicket.current += 1
        const code = errorCode(error)
        if (
          status === 409 &&
          (code === "ledger_version_conflict" ||
            code === "ledger_profile_changed")
        ) {
          setFlow({
            kind: "candidate-error",
            candidate,
            candidateId: intent.request.candidate_upload_id,
            reason: code === "ledger_profile_changed" ? "profile" : "version",
            diagnostic: detail,
          })
          return
        }
        setFlow({
          kind: "candidate-error",
          candidate,
          candidateId: intent.request.candidate_upload_id,
          reason:
            status === 409 && code === "ledger_key_conflict"
              ? "key"
              : "rejected",
          diagnostic: detail,
        })
        return
      }
      setFlow({
        kind: "operation",
        intent,
        candidate,
        phase: "unknown",
        diagnostic: detail,
      })
    },
  })
  const startReplacement = async () => {
    if (flow.kind !== "preview" || busy.current || !writable.current) return
    const value = flow.value
    const prepareTicket = ++operationTicket.current
    busy.current = "prepare"
    setFlow({ kind: "preparing", value })
    try {
      const digest = await requestDigest(value.request)
      if (
        !alive.current ||
        busy.current !== "prepare" ||
        operationTicket.current !== prepareTicket
      )
        return
      const intent: ReplacementIntent = {
        key: crypto.randomUUID(),
        request: value.request,
        digest,
      }
      try {
        sessionStorage.setItem(replacementStorage, JSON.stringify(intent))
      } catch {
        busy.current = null
        setFlow({
          kind: "preview",
          value,
          issue: {
            message: t(
              "The request could not be saved. Nothing was submitted.",
              "无法保存操作身份，尚未提交替换。",
            ),
          },
        })
        return
      }
      busy.current = "apply"
      setFlow({
        kind: "operation",
        intent,
        candidate: value.candidate,
        phase: "applying",
      })
      applyReplacement.mutate({
        intent,
        candidate: value.candidate,
        ticket: prepareTicket,
      })
    } catch {
      if (
        !alive.current ||
        busy.current !== "prepare" ||
        operationTicket.current !== prepareTicket
      )
        return
      busy.current = null
      setFlow({
        kind: "preview",
        value,
        issue: {
          message: t(
            "The request could not be saved. Nothing was submitted.",
            "无法保存操作身份，尚未提交替换。",
          ),
        },
      })
    }
  }
  const recoverReplacement = useMutation({
    mutationFn: async ({
      intent,
    }: {
      intent: ReplacementIntent
      ticket: number
    }) =>
      validReceipt(
        await CustomerLedgerService.readCustomerUploadReplacement({
          projectId: project.id,
          operationKey: intent.key,
        }),
        intent,
      ),
    onSuccess: (receipt, { ticket: recoverTicket }) => {
      if (!alive.current || operationTicket.current !== recoverTicket) return
      finishConfirmed(receipt)
    },
    onError: (error, { intent, ticket: recoverTicket }) => {
      if (!alive.current || operationTicket.current !== recoverTicket) return
      const detail = apiErrorDetail(error)
      const missing =
        error instanceof ApiError &&
        error.status === 404 &&
        errorCode(error) === "ledger_replacement_not_found"
      setFlow((current) => {
        if (current.kind !== "operation" || current.intent.key !== intent.key)
          return current
        if (current.phase === "applying") return current
        return {
          ...current,
          phase: missing ? "missing" : "unknown",
          recoveryError: !missing,
          diagnostic: detail,
        }
      })
    },
    onSettled: () => {
      recoveryPending.current = false
    },
  })
  const recoverOperation = (intent: ReplacementIntent) => {
    if (recoveryPending.current) return
    recoveryPending.current = true
    recoverReplacement.mutate({ intent, ticket: operationTicket.current })
  }
  const resendReplacement = (
    intent: ReplacementIntent,
    candidate: Candidate | null,
  ) => {
    if (busy.current || recoveryPending.current || !writable.current) return
    const applyTicket = ++operationTicket.current
    busy.current = "apply"
    setFlow({
      kind: "operation",
      intent,
      candidate,
      phase: "applying",
    })
    applyReplacement.mutate({ intent, candidate, ticket: applyTicket })
  }
  const cancelPreview = () => {
    if (flow.kind !== "preview") return
    flowTicket.current += 1
    busy.current = null
    if (fileInputRef.current?.value) fileInputRef.current.value = ""
    returnPreviewFocus.current = true
    setFlow({ kind: "idle" })
  }
  const submitUpload = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const file = flow.kind === "file" ? flow.file : null
    if (!file) {
      setFlow({
        kind: "file",
        file: null,
        issue: {
          message: t(
            "Choose one XLSX file to upload.",
            "请选择一个 XLSX 文件上传。",
          ),
        },
      })
      return
    }
    if (busy.current) return
    const uploadTicket = ++flowTicket.current
    busy.current = "upload"
    setFlow({ kind: "uploading", file })
    uploadMutation.mutate({ file, ticket: uploadTicket })
  }

  const focusKey =
    flow.kind === "file" && flow.issue
      ? "file-issue"
      : flow.kind === "candidate"
        ? `candidate:${flow.candidate.id}`
        : flow.kind === "preview"
          ? `preview:${flow.value.candidate.id}`
          : flow.kind === "candidate-error"
            ? `error:${flow.reason}:${flow.candidateId}`
            : flow.kind === "already-current"
              ? `already-current:${flow.candidate.id}`
              : flow.kind === "operation" && flow.phase !== "applying"
                ? `recovery:${flow.phase}:${flow.intent.key}`
                : flow.kind === "confirmed"
                  ? `confirmed:${flow.receipt.id}`
                  : null
  const focusTarget =
    flow.kind === "file" || flow.kind === "candidate-error"
      ? errorHeading
      : flow.kind === "candidate"
        ? candidateHeading
        : flow.kind === "preview"
          ? previewHeading
          : flow.kind === "already-current"
            ? alreadyCurrentHeading
            : flow.kind === "operation"
              ? recoveryHeading
              : flow.kind === "confirmed"
                ? confirmedHeading
                : null
  useEffect(() => {
    if (!focusKey) return
    const target = focusTarget?.current
    if (!target) return
    target.scrollIntoView({ block: "start" })
    target.focus()
  }, [focusKey, focusTarget])
  useEffect(() => {
    if (flow.kind !== "idle" || !returnPreviewFocus.current) return
    returnPreviewFocus.current = false
    const trigger = previewTrigger.current
    previewTrigger.current = null
    if (trigger?.isConnected) trigger.focus()
    else chooseFileButton.current?.focus()
  }, [flow.kind])

  if (profileQuery.isPending || uploadsQuery.isPending) {
    return (
      <p role="status">{t("Loading Project inputs…", "正在加载项目输入…")}</p>
    )
  }
  if (profileQuery.isError) {
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
  const currentUpload = uploads?.data.find(
    (upload) => upload.id === uploads.current_customer_upload_id,
  )
  const canGoBack = page > 0
  const canGoForward =
    uploads !== undefined && (page + 1) * UPLOAD_PAGE_SIZE < uploads.count
  const blocksWrites =
    flow.kind === "uploading" ||
    flow.kind === "previewing" ||
    flow.kind === "preparing" ||
    flow.kind === "operation"
  const previewValue =
    flow.kind === "preview"
      ? flow.value
      : flow.kind === "preparing"
        ? flow.value
        : null
  const candidateErrorCopy =
    flow.kind !== "candidate-error"
      ? null
      : flow.reason === "read"
        ? t(
            "The latest ledger could not be previewed. Nothing was applied; read the latest version and try again.",
            "无法读取最新台账预览，尚未应用任何内容；请重新读取最新版本后重试。",
          )
        : flow.reason === "version"
          ? t(
              "The current version or profile changed. This request was rejected; preview the latest version again.",
              "当前版本或配置已变化，本次请求被拒绝，请重新预览最新版本。",
            )
          : flow.reason === "profile"
            ? t(
                "The current profile changed. This request was rejected; preview the latest version again.",
                "当前配置已变化，本次请求被拒绝，请重新预览最新版本。",
              )
            : flow.reason === "key"
              ? t(
                  "This operation key was already used for a different request. The rejected request was not retried; preview the file again to start a new request.",
                  "此操作标识已用于不同的请求。被拒绝的请求未自动重试；请重新预览该文件以发起新请求。",
                )
              : t(
                  "The request was rejected. Nothing was applied; check access and the accepted file before previewing again.",
                  "请求被拒绝，尚未应用任何内容；请核对权限与已接受文件后重新预览。",
                )

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
          <CardTitle role="heading" aria-level={3}>
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
          {uploadsQuery.isError ? (
            <Alert variant="destructive">
              <AlertCircle />
              <AlertTitle>
                {t("Current input could not be read", "无法读取当前输入")}
              </AlertTitle>
              <AlertDescription className="space-y-2">
                <p>
                  {t(
                    "The latest ownership could not be read. This separate failure does not change the submitted operation.",
                    "无法读取最新当前输入；此独立失败不会改变已提交操作。",
                  )}
                </p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => void uploadsQuery.refetch()}
                >
                  {t("Retry current input", "重试读取当前输入")}
                </Button>
              </AlertDescription>
            </Alert>
          ) : uploads?.current_customer_upload_id ? (
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
        </CardContent>
      </Card>

      {uploads?.can_upload ? (
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
                    disabled={
                      flow.kind === "uploading" ||
                      flow.kind === "preparing" ||
                      flow.kind === "operation"
                    }
                    onChange={(event) => {
                      const file = event.target.files?.[0] ?? null
                      flowTicket.current += 1
                      if (busy.current === "preview") busy.current = null
                      setFlow(file ? { kind: "file", file } : { kind: "idle" })
                    }}
                  />
                  <Button
                    ref={chooseFileButton}
                    type="button"
                    variant="outline"
                    disabled={
                      flow.kind === "uploading" ||
                      flow.kind === "preparing" ||
                      flow.kind === "operation"
                    }
                    onClick={() => fileInputRef.current?.click()}
                  >
                    {t("Choose file", "选择文件")}
                  </Button>
                  <span className="min-w-0 break-all text-sm">
                    {flow.kind === "file"
                      ? (flow.file?.name ?? t("No file chosen", "未选择文件"))
                      : flow.kind === "uploading"
                        ? flow.file.name
                        : t("No file chosen", "未选择文件")}
                  </span>
                </div>
              </div>
              <LoadingButton
                type="submit"
                loading={flow.kind === "uploading"}
                disabled={
                  flow.kind === "previewing" ||
                  flow.kind === "preparing" ||
                  flow.kind === "operation"
                }
              >
                <Upload />
                {t("Upload", "上传")}
              </LoadingButton>
            </form>
            {flow.kind === "file" && flow.issue && (
              <div
                ref={errorHeading}
                role="status"
                tabIndex={-1}
                data-testid="import-error-summary"
                className={`mt-3 text-sm ${focusHeading}`}
              >
                <p>{message(flow.issue.message)}</p>
                <DiagnosticDetails detail={flow.issue.diagnostic} />
              </div>
            )}
          </CardContent>
        </Card>
      ) : uploads && !project.archived_at ? (
        <p className="text-sm text-muted-foreground">
          {t(
            "You have read-only access to CustomerUpload inputs for this Project.",
            "您对此项目的客户上传输入仅有只读权限。",
          )}
        </p>
      ) : null}

      {flow.kind === "candidate" && (
        <Card aria-live="polite" data-testid="upload-candidate">
          <CardHeader>
            <CardTitle
              ref={candidateHeading}
              role="heading"
              aria-level={3}
              tabIndex={-1}
              className={focusHeading}
            >
              {t("Accepted file", "已接受文件")}
            </CardTitle>
            <CardDescription>
              {message(
                flow.replacement
                  ? t(
                      "Upload accepted. Preview the replacement before applying it.",
                      "上传已接受。应用前请先预览替换。",
                    )
                  : t(
                      "Upload accepted. Preview this file and set it as the current input.",
                      "上传已接受。请预览此文件并将其设为当前输入。",
                    ),
              )}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1">
              <p className="break-all font-medium">{flow.candidate.name}</p>
              <p className="text-sm text-muted-foreground">
                {t(
                  `${flow.candidate.recordCount} records`,
                  `${flow.candidate.recordCount} 条记录`,
                )}{" "}
                · {t("Profile v", "配置版本 v")}
                {flow.candidate.profileVersion}
              </p>
              <TechnicalValue
                value={flow.candidate.id}
                label={t("CustomerUpload ID", "客户上传 ID")}
              />
            </div>
            <div>
              <h3 className="text-sm font-medium">{t("Warnings", "警告")}</h3>
              <WarningSummary warnings={flow.candidate.warnings} />
            </div>
            <Button
              type="button"
              variant="outline"
              disabled={
                !uploads?.can_select ||
                !writable.current ||
                busy.current !== null
              }
              onClick={(event) =>
                previewCandidate(flow.candidate, event.currentTarget)
              }
            >
              {t("Preview this file", "预览此文件")}
            </Button>
          </CardContent>
        </Card>
      )}

      {flow.kind === "previewing" && (
        <Card aria-live="polite">
          <CardHeader>
            <CardTitle
              ref={previewHeading}
              role="heading"
              aria-level={3}
              tabIndex={-1}
              className={focusHeading}
            >
              {t("Reading preview…", "正在读取预览…")}
            </CardTitle>
            <CardDescription>
              {t(
                "The server is reading the latest current input and building the impact preview.",
                "服务器正在读取最新当前输入并生成影响预览。",
              )}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="break-all font-medium">{flow.candidate.name}</p>
            <TechnicalValue
              value={flow.candidate.id}
              label={t("CustomerUpload ID", "客户上传 ID")}
            />
          </CardContent>
        </Card>
      )}

      {previewValue && (
        <Card aria-live="polite" data-testid="replacement-preview">
          <CardHeader>
            <CardTitle
              ref={previewHeading}
              role="heading"
              aria-level={3}
              tabIndex={-1}
              className={focusHeading}
            >
              {previewValue.request.expected_upload_id === null
                ? t("Selection preview", "选择预览")
                : t("Replacement preview", "替换预览")}
            </CardTitle>
            <CardDescription>
              {previewValue.request.expected_upload_id === null
                ? t(
                    "Setting this file as the current input makes it the complete current register and clears local edits for it. It does not change history.",
                    "将此文件设为当前输入后，它将成为完整的当前台账，并清除该文件的本地修订；不会改变历史版本。",
                  )
                : t(
                    "Apply replaces the complete current register and clears local edits for the new file. It does not change history.",
                    "应用会以新文件完整替换当前台账，并清除新文件的本地修订；不会改变历史版本。",
                  )}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1">
              <p className="break-all font-medium">
                {previewValue.candidate.name}
              </p>
              <p className="text-sm text-muted-foreground">
                {t(
                  `${previewValue.candidate.recordCount} records`,
                  `${previewValue.candidate.recordCount} 条记录`,
                )}{" "}
                · {t("Profile v", "配置版本 v")}
                {previewValue.candidate.profileVersion}
              </p>
              <TechnicalValue
                value={previewValue.candidate.id}
                label={t("CustomerUpload ID", "客户上传 ID")}
              />
            </div>
            <dl className="grid gap-3 text-sm sm:grid-cols-3">
              <div>
                <dt className="text-muted-foreground">
                  {t("Current records / IPs", "当前条目 / IP")}
                </dt>
                <dd>
                  {previewValue.impact.current_record_count} /{" "}
                  {previewValue.impact.current_unique_ips}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">
                  {t("New records / IPs", "新条目 / IP")}
                </dt>
                <dd>
                  {previewValue.impact.candidate_record_count} /{" "}
                  {previewValue.impact.candidate_unique_ips}
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
                  {previewValue.impact.added_ips} /{" "}
                  {previewValue.impact.removed_ips} /{" "}
                  {previewValue.impact.changed_ip_declarations}
                </dd>
              </div>
            </dl>
            <div>
              <h3 className="text-sm font-medium">{t("Warnings", "警告")}</h3>
              <WarningSummary warnings={previewValue.candidate.warnings} />
            </div>
            {flow.kind === "preview" && flow.issue && (
              <div className="text-sm" role="status">
                <p>{message(flow.issue.message)}</p>
                <DiagnosticDetails detail={flow.issue.diagnostic} />
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              <LoadingButton
                type="button"
                loading={flow.kind === "preparing"}
                disabled={
                  flow.kind === "preparing" ||
                  !uploads?.can_select ||
                  !writable.current ||
                  busy.current !== null
                }
                onClick={() => void startReplacement()}
              >
                {previewValue.request.expected_upload_id === null
                  ? t("Set as current input", "设为当前输入")
                  : t("Apply replacement", "应用替换")}
              </LoadingButton>
              <Button
                type="button"
                variant="outline"
                disabled={flow.kind === "preparing"}
                onClick={cancelPreview}
              >
                {t("Cancel", "取消")}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {flow.kind === "candidate-error" && (
        <Card aria-live="assertive" data-testid="import-error">
          <CardHeader>
            <CardTitle
              ref={errorHeading}
              role="heading"
              aria-level={3}
              tabIndex={-1}
              className={focusHeading}
            >
              {flow.reason === "read"
                ? t("Preview could not be read", "无法读取预览")
                : flow.reason === "version"
                  ? t("Current version changed", "当前版本已变化")
                  : flow.reason === "profile"
                    ? t("Current profile changed", "当前配置已变化")
                    : flow.reason === "key"
                      ? t("Operation key conflict", "操作标识冲突")
                      : t("Request rejected", "请求被拒绝")}
            </CardTitle>
            <CardDescription>{candidateErrorCopy}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {flow.candidate && (
              <div className="space-y-1">
                <p className="break-all font-medium">{flow.candidate.name}</p>
                <TechnicalValue
                  value={flow.candidate.id}
                  label={t("CustomerUpload ID", "客户上传 ID")}
                />
              </div>
            )}
            {flow.issue && (
              <p className="text-sm">{message(flow.issue.message)}</p>
            )}
            <DiagnosticDetails detail={flow.diagnostic} />
            {flow.candidate && (
              <Button
                type="button"
                variant="outline"
                disabled={!uploads?.can_select || !writable.current}
                onClick={(event) => {
                  if (flow.candidate)
                    previewCandidate(flow.candidate, event.currentTarget)
                }}
              >
                {flow.reason === "version" || flow.reason === "profile"
                  ? t(
                      "Read latest version and preview again",
                      "读取最新版本并重新预览",
                    )
                  : t("Preview this file again", "重新预览此文件")}
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      {flow.kind === "already-current" && (
        <Card aria-live="polite" data-testid="already-current">
          <CardHeader>
            <CardTitle
              ref={alreadyCurrentHeading}
              role="heading"
              aria-level={3}
              tabIndex={-1}
              className={focusHeading}
            >
              {t("File is already current", "文件已是当前输入")}
            </CardTitle>
            <CardDescription>
              {t(
                "This file is already the current input. No preview or apply is needed; existing manual revisions are unchanged.",
                "此文件已是当前输入，无需预览或应用；现有本地修订保持不变。",
              )}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-1">
            <p className="break-all font-medium">{flow.candidate.name}</p>
            <TechnicalValue
              value={flow.candidate.id}
              label={t("CustomerUpload ID", "客户上传 ID")}
            />
          </CardContent>
        </Card>
      )}

      {flow.kind === "operation" && (
        <Alert data-testid="operation-state">
          <AlertTitle
            ref={recoveryHeading}
            role="heading"
            aria-level={3}
            tabIndex={-1}
            className={focusHeading}
          >
            {flow.phase === "applying"
              ? flow.intent.request.expected_upload_id === null
                ? t("Setting current input…", "正在设置当前输入…")
                : t("Applying replacement…", "正在应用替换…")
              : flow.intent.request.expected_upload_id === null
                ? t("Selection outcome unknown", "选择结果未知")
                : t("Replacement outcome unknown", "替换结果未知")}
          </AlertTitle>
          <AlertDescription className="space-y-3">
            {flow.candidate && (
              <div className="space-y-1">
                <p className="break-all font-medium">{flow.candidate.name}</p>
                <TechnicalValue
                  value={flow.candidate.id}
                  label={t("CustomerUpload ID", "客户上传 ID")}
                />
              </div>
            )}
            <p>
              {flow.phase === "applying"
                ? t(
                    "The request is being submitted. New uploads and previews are disabled until its outcome is known; you can read its saved receipt.",
                    "请求正在提交。在结果明确前，新的上传和预览已禁用；可读取已保存的回执。",
                  )
                : flow.phase === "missing"
                  ? t(
                      "No completed receipt yet. You may explicitly resend the same request with its original identity; the server will recover any committed operation.",
                      "尚无完成回执。可明确复用原标识重新提交同一请求，服务端会恢复任何已提交操作。",
                    )
                  : flow.recoveryError
                    ? t(
                        "Could not read the operation. Keep its identity and retry this read.",
                        "无法读取操作回执。已保留原标识，请重试读取。",
                      )
                    : t(
                        "The outcome is unknown. Read the saved operation before submitting again.",
                        "结果尚未确认，请先读取已保存的操作，再决定是否重新提交。",
                      )}
            </p>
            <DiagnosticDetails detail={flow.diagnostic} />
            <div className="flex flex-wrap items-center gap-2">
              <LoadingButton
                type="button"
                size="sm"
                variant="outline"
                loading={recoverReplacement.isPending}
                disabled={recoverReplacement.isPending}
                onClick={() => recoverOperation(flow.intent)}
              >
                {t("Recover result", "恢复结果")}
              </LoadingButton>
              {flow.phase === "missing" && (
                <LoadingButton
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={
                    recoveryPending.current ||
                    !uploads?.can_select ||
                    !writable.current
                  }
                  onClick={() => resendReplacement(flow.intent, flow.candidate)}
                >
                  {t("Resend original request", "复用原请求提交")}
                </LoadingButton>
              )}
            </div>
          </AlertDescription>
        </Alert>
      )}

      {flow.kind === "confirmed" && (
        <Card aria-live="polite" data-testid="operation-confirmed">
          <CardHeader>
            <CardTitle
              ref={confirmedHeading}
              role="heading"
              aria-level={3}
              tabIndex={-1}
              className={focusHeading}
            >
              {t("Operation confirmed.", "操作已确认。")}
            </CardTitle>
            <CardDescription>
              {t(
                "This confirmation covers the submitted operation only.",
                "此确认仅针对已提交的操作。",
              )}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Button asChild variant="outline">
              <Link
                to="/projects/$projectId/netflow-correlation"
                params={{ projectId: project.id }}
                search={{}}
              >
                {t("Go to comparison results", "前往比对结果")}
              </Link>
            </Button>
            <p className="text-sm text-muted-foreground">
              {t(
                "Opening comparison results only navigates. It does not generate comparison results or run a comparison.",
                "打开比对结果仅进行导航，不会生成比对结果或运行比对。",
              )}
            </p>
          </CardContent>
        </Card>
      )}

      {uploads && (
        <Card>
          <CardHeader>
            <CardTitle>{t("Accepted uploads", "已接受的上传")}</CardTitle>
            <CardDescription>
              <p>{t(`${uploads.count} total`, `共 ${uploads.count} 项`)}</p>
              <p className="mt-1">
                {t(
                  "Derived XLSX files materialize supported fields only. The absence of an extra-column warning is not evidence that unsupported columns are retained.",
                  "派生 XLSX 仅写入受支持字段。没有额外列警告并不代表未受支持的列已被保留。",
                )}
              </p>
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <UploadRows
              uploads={uploads.data}
              currentUploadId={uploads.current_customer_upload_id}
              canSelect={uploads.can_select}
              actionsDisabled={blocksWrites || !writable.current}
              selectingUploadId={
                flow.kind === "previewing"
                  ? flow.candidate.id
                  : flow.kind === "preparing"
                    ? flow.value.candidate.id
                    : null
              }
              onSelect={(candidate, trigger) =>
                previewCandidate(candidate, trigger)
              }
            />
            {(canGoBack || canGoForward) && (
              <div className="flex items-center justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={!canGoBack || blocksWrites}
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
                  disabled={!canGoForward || blocksWrites}
                  onClick={() => setPage((current) => current + 1)}
                >
                  {t("Next", "下一页")}
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}
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
        <h1 className="workspace-page-title">
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
        <h1 className="workspace-page-title">
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
          <InputReadinessSummary
            key={`input-summary:${user.id}:${project.id}`}
            actorId={user.id}
            projectId={project.id}
          />
          <div
            id="customer-inputs"
            tabIndex={-1}
            className="workspace-inputs scroll-mt-32"
          >
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
            <h2 id="cloud-access-title" className="text-base font-semibold">
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
        <h1 className="workspace-page-title">{project.name}</h1>
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
