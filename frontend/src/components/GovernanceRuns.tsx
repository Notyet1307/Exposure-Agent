import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, useNavigate } from "@tanstack/react-router"
import { Play, Repeat2, RotateCcw } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { z } from "zod"
import {
  ApiError,
  type GovernanceRunPublic,
  GovernanceRunsService,
} from "@/client"
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
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import useAuth, { isInactiveAccountError } from "@/hooks/useAuth"
import { useI18n } from "@/lib/i18n"

const READINESS_MESSAGES: Record<string, string> = Object.setPrototypeOf(
  {
    run_project_archived: "Archived Projects cannot start a Governance Run.",
    run_customer_upload_not_ready:
      "Select an accepted CustomerUpload before starting a Run.",
    run_cloudatlas_source_not_ready:
      "Enable and validate the CloudAtlas source before starting a Run.",
    run_cloudatlas_credential_not_ready:
      "The deployment CloudAtlas Run credential is not configured.",
  },
  null,
)

const BLOCKING_MESSAGES: Record<string, string> = Object.setPrototypeOf(
  {
    run_session_state_unknown:
      "The original Session state is unknown. Retry, Rerun, and new Runs are blocked.",
    run_session_still_running:
      "The original Session is still running and keeps the Project Run slot.",
    run_session_not_recoverable:
      "The original Session cannot be recovered. Use an explicit Rerun.",
    run_retry_customer_input_changed:
      "The fixed CustomerUpload changed. Retry is unavailable; Rerun uses current input.",
    run_retry_cloudatlas_input_changed:
      "The fixed CloudAtlas input changed. Retry is unavailable; Rerun uses current input.",
    run_retry_cloudatlas_input_unavailable:
      "The fixed CloudAtlas input cannot currently be verified.",
    run_cloudatlas_credential_not_ready:
      "The deployment CloudAtlas Run credential is not configured.",
    run_cloudatlas_source_not_ready:
      "The CloudAtlas source requires fresh validation before Retry.",
    run_retry_newer_run_exists:
      "A newer Run makes this Run permanently historical.",
    run_launch_in_progress:
      "A Governance Runner launch is already in progress.",
    run_launch_terminal_use_new_trigger:
      "The previous launch ended before creating a Run. Use a new Trigger ID.",
  },
  null,
)

const MESSAGE_ZH: Record<string, string> = {
  "The comparison failed. Its inputs and run record are preserved.":
    "本轮比对失败，输入和运行记录已保留。",
  "Inputs changed. Review and confirm the current versions again.":
    "输入已变化，请重新查看并确认当前版本。",
  "This request is bound to different inputs. Keep the saved request; no new comparison was started.":
    "此请求已绑定其他输入，请保留原请求；没有另启新的比对。",
  "The result is not confirmed. Resume the same saved request; do not start another comparison.":
    "结果尚未确认，请恢复同一已保存请求，不要另启新的比对。",

  "Archived Projects cannot start a Governance Run.":
    "已归档项目无法启动治理运行。",
  "Select an accepted CustomerUpload before starting a Run.":
    "启动运行前，请选择一个已接受的客户上传。",
  "Enable and validate the CloudAtlas source before starting a Run.":
    "启动运行前，请启用并验证 CloudAtlas 来源。",
  "The deployment CloudAtlas Run credential is not configured.":
    "部署环境尚未配置 CloudAtlas 运行凭据。",
  "The original Session state is unknown. Retry, Rerun, and new Runs are blocked.":
    "原会话状态未知，重试、重新运行和新运行均已阻止。",
  "The original Session is still running and keeps the Project Run slot.":
    "原会话仍在运行，并继续占用项目运行名额。",
  "The original Session cannot be recovered. Use an explicit Rerun.":
    "原会话无法恢复，请明确选择重新运行。",
  "The fixed CustomerUpload changed. Retry is unavailable; Rerun uses current input.":
    "固定的客户上传已更改，无法重试；重新运行将使用当前输入。",
  "The fixed CloudAtlas input changed. Retry is unavailable; Rerun uses current input.":
    "固定的 CloudAtlas 输入已更改，无法重试；重新运行将使用当前输入。",
  "The fixed CloudAtlas input cannot currently be verified.":
    "当前无法核验固定的 CloudAtlas 输入。",
  "The CloudAtlas source requires fresh validation before Retry.":
    "重试前需要重新验证 CloudAtlas 来源。",
  "A newer Run makes this Run permanently historical.":
    "已有更新的运行，此运行已永久成为历史运行。",
  "A Governance Runner launch is already in progress.":
    "治理 Runner 已在启动中。",
  "The previous launch ended before creating a Run. Use a new Trigger ID.":
    "上次启动在创建运行前已结束，请使用新的触发 ID。",
  "Recovery is currently blocked.": "当前无法恢复。",
  "The existing idempotent Run was found.": "已找到现有的幂等运行。",
  "Governance Session accepted. Waiting for the Runner to start.":
    "治理会话已接受，正在等待 Runner 启动。",
  "The Governance Session could not be started. Retrying will reuse the same Trigger ID.":
    "无法启动治理会话，重试将复用相同的触发 ID。",
  "Retry accepted for the same Governance Run and Session.":
    "已接受重试，将使用相同的治理运行和会话。",
  "Retry was rejected. Review the stable recovery status below.":
    "重试被拒绝，请查看下方确定的恢复状态。",
  "Rerun accepted with current inputs and a new Trigger ID.":
    "已接受重新运行，将使用当前输入和新的触发 ID。",
  "Rerun was rejected. Review the stable recovery status below.":
    "重新运行被拒绝，请查看下方确定的恢复状态。",
  "Run inputs are not ready.": "运行输入尚未就绪。",
  "The Governance Runner launch is currently blocked.":
    "当前无法启动治理 Runner。",
}

function rejectionCode(error: unknown) {
  if (!(error instanceof ApiError)) return null
  const body = error.body
  if (typeof body !== "object" || body === null) return null
  const detail = (body as { detail?: unknown }).detail
  if (typeof detail !== "object" || detail === null) return null
  const code = (detail as { code?: unknown }).code
  return typeof code === "string" ? code : null
}

function RunDetails({
  run,
  projectId,
  onRetry,
  onRerun,
  retrying,
  rerunning,
}: {
  run: GovernanceRunPublic
  projectId: string
  onRetry: () => void
  onRerun: () => void
  retrying: boolean
  rerunning: boolean
}) {
  const { t, formatDate, translateValue } = useI18n()
  const blockingMessage = run.blocking_code
    ? (BLOCKING_MESSAGES[run.blocking_code] ?? "Recovery is currently blocked.")
    : null
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-base">
            {t("Run", "运行")} · {formatDate(run.created_at)}
          </CardTitle>
          <Badge variant={run.status === "COMPLETED" ? "default" : "secondary"}>
            {translateValue(run.status)}
          </Badge>
        </div>
        <CardDescription>
          {run.completed_at
            ? `${t("Completed", "完成于")} ${formatDate(run.completed_at)}`
            : `${t("Triggered", "触发于")} ${formatDate(run.created_at)}`}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-3 text-sm md:grid-cols-2">
          <div>
            <p className="font-medium">{t("Customer input", "客户输入")}</p>
            <p className="text-muted-foreground">
              {t("Profile v", "配置版本 v")}
              {run.customer_upload_profile_version}
            </p>
          </div>
          <div>
            <p className="font-medium">
              {t("CloudAtlas input", "CloudAtlas 输入")}
            </p>
            <p className="break-all text-muted-foreground">
              {run.cloudatlas_method}
            </p>
          </div>
        </div>
        <details className="text-sm">
          <summary className="cursor-pointer">
            {t("Run technical details", "运行技术详情")}
          </summary>
          <dl className="mt-3 grid min-w-0 gap-3 md:grid-cols-2">
            {(
              [
                [t("Run ID", "运行 ID"), run.id],
                [t("Trigger ID", "触发 ID"), run.trigger_id],
                [t("Session ID", "会话 ID"), run.session_id],
                [t("CustomerUpload ID", "客户上传 ID"), run.customer_upload_id],
                [
                  t("Customer input SHA-256", "客户输入 SHA-256"),
                  run.customer_upload_sha256,
                ],
                [t("Profile ID", "配置 ID"), run.customer_upload_profile_id],
                [
                  t("Source instance ID", "来源实例 ID"),
                  run.source_instance_id,
                ],
                [
                  t("CloudAtlas fingerprint", "CloudAtlas 指纹"),
                  run.cloudatlas_validated_fingerprint,
                ],
                [
                  t("CloudAtlas capability set ID", "CloudAtlas 能力集 ID"),
                  run.cloudatlas_capset_id,
                ],
                [t("Package SHA-256", "包 SHA-256"), run.package_sha256],
                [
                  t("Descriptor SHA-256", "描述文件 SHA-256"),
                  run.descriptor_sha256,
                ],
                [t("Runner build", "Runner 构建"), run.runner_build_version],
                [
                  t("Processing contract", "处理契约"),
                  run.processing_contract_version,
                ],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="min-w-0">
                <dt>{label}</dt>
                <dd>
                  <TechnicalValue value={value ?? ""} label={label} />
                </dd>
              </div>
            ))}
          </dl>
        </details>

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("Step", "步骤")}</TableHead>
              <TableHead>{t("Status", "状态")}</TableHead>
              <TableHead>{t("Attempt", "尝试次数")}</TableHead>
              <TableHead>{t("Result", "结果")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {run.steps.map((step) => (
              <TableRow key={step.step_code}>
                <TableCell className="font-medium">
                  {translateValue(step.step_code)}
                </TableCell>
                <TableCell>
                  <Badge variant="secondary">
                    {translateValue(step.status)}
                  </Badge>
                </TableCell>
                <TableCell>{step.attempt}</TableCell>
                <TableCell className="max-w-72 whitespace-normal break-words">
                  {step.output_hash ? t("Output recorded", "已记录输出") : "—"}
                  {step.error_code
                    ? ` · ${translateValue(step.error_code)}`
                    : ""}
                  {(step.input_hash || step.output_hash) && (
                    <details className="mt-2">
                      <summary className="cursor-pointer">
                        {t("Step details", "步骤详情")}
                      </summary>
                      <dl className="mt-2 space-y-2">
                        {step.input_hash && (
                          <div>
                            <dt>{t("Input hash", "输入哈希")}</dt>
                            <dd>
                              <TechnicalValue value={step.input_hash} />
                            </dd>
                          </div>
                        )}
                        {step.output_hash && (
                          <div>
                            <dt>{t("Output hash", "输出哈希")}</dt>
                            <dd>
                              <TechnicalValue value={step.output_hash} />
                            </dd>
                          </div>
                        )}
                      </dl>
                    </details>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>

        <div>
          <p className="mb-2 text-sm font-medium">
            {t("SourceSnapshots", "来源快照")}
          </p>
          {run.snapshots.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t("No snapshots yet.", "尚无快照。")}
            </p>
          ) : (
            <div className="grid gap-2 md:grid-cols-2">
              {run.snapshots.map((snapshot) => (
                <div
                  key={snapshot.id}
                  className="min-w-0 rounded-md border p-3 text-sm"
                >
                  <p className="font-medium">
                    {translateValue(snapshot.source_type)}
                  </p>
                  <p>
                    {t(
                      `${snapshot.record_count} records`,
                      `${snapshot.record_count} 条记录`,
                    )}
                  </p>
                  <p className="text-muted-foreground">
                    {formatDate(snapshot.created_at)}
                  </p>
                  <details className="mt-2">
                    <summary className="cursor-pointer">
                      {t("Snapshot details", "快照详情")}
                    </summary>
                    <dl className="mt-2 space-y-2">
                      <div>
                        <dt>{t("Snapshot ID", "快照 ID")}</dt>
                        <dd>
                          <TechnicalValue value={snapshot.id} />
                        </dd>
                      </div>
                      <div>
                        <dt>SHA-256</dt>
                        <dd>
                          <TechnicalValue value={snapshot.content_sha256} />
                        </dd>
                      </div>
                      <div>
                        <dt>{t("Schema fingerprint", "结构指纹")}</dt>
                        <dd>
                          <TechnicalValue value={snapshot.schema_fingerprint} />
                        </dd>
                      </div>
                      {snapshot.method_fingerprint && (
                        <div>
                          <dt>{t("Method fingerprint", "方法指纹")}</dt>
                          <dd>
                            <TechnicalValue
                              value={snapshot.method_fingerprint}
                            />
                          </dd>
                        </div>
                      )}
                    </dl>
                  </details>
                </div>
              ))}
            </div>
          )}
        </div>

        <p className="text-sm">
          {t("Snapshots reused:", "复用快照数：")}{" "}
          {run.reused_snapshot_count ?? 0}
        </p>
        {(run.status === "COMPLETED" ||
          run.status === "COMPLETED_WITH_WARNINGS") &&
          run.completed_at !== null && (
            <div className="flex flex-wrap gap-4">
              <Link
                to="/projects/$projectId/runs/$runId/comparison"
                params={{ projectId, runId: run.id }}
                search={(previous) => ({
                  ...previous,
                  project: projectId,
                  run: run.id,
                  view: "overview",
                  page: undefined,
                  resource_id: undefined,
                  classification: undefined,
                  netflow_status: undefined,
                })}
                className="inline-block text-sm underline underline-offset-4"
              >
                {t("View source comparison", "查看来源比较")}
              </Link>
              <Link
                to="/projects/$projectId/runs/$runId/lineage"
                params={{ projectId, runId: run.id }}
                search={(previous) => ({
                  ...previous,
                  project: projectId,
                  run: run.id,
                  view: "overview",
                  page: undefined,
                  resource_id: undefined,
                  classification: undefined,
                  netflow_status: undefined,
                })}
                className="inline-block text-sm underline underline-offset-4"
              >
                {t("Lineage", "血缘")}
              </Link>
            </div>
          )}
        {blockingMessage && run.blocking_code && (
          <Alert>
            <AlertTitle>{t("Recovery status", "恢复状态")}</AlertTitle>
            <AlertDescription>
              {t(
                blockingMessage,
                `${MESSAGE_ZH[blockingMessage] ?? blockingMessage} (${translateValue(run.blocking_code)})`,
              )}
            </AlertDescription>
          </Alert>
        )}
        {(run.can_retry || run.can_rerun) && (
          <div className="flex flex-wrap gap-2">
            {run.can_retry && (
              <LoadingButton type="button" loading={retrying} onClick={onRetry}>
                <RotateCcw />
                {t("Retry same Session", "重试相同会话")}
              </LoadingButton>
            )}
            {run.can_rerun && (
              <LoadingButton
                type="button"
                variant="outline"
                loading={rerunning}
                onClick={onRerun}
              >
                <Repeat2 />
                {t("Rerun with current inputs", "使用当前输入重新运行")}
              </LoadingButton>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

const runIntentSchema = z
  .object({
    key: z.string().uuid(),
    confirmationHash: z.string().regex(/^[0-9a-f]{64}$/),
    runId: z.string().uuid().nullable(),
    controlId: z.string().nullable(),
  })
  .strict()

export default function GovernanceRuns({ projectId }: { projectId: string }) {
  const { user, userError, refetchUser, logout } = useAuth()
  const { t } = useI18n()
  if (userError)
    return (
      <Alert variant="destructive">
        <AlertDescription>
          {t(
            "Permissions could not be read. Retry or sign in again before continuing.",
            "无法读取权限。请重试或重新登录后再操作。",
          )}
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => void refetchUser()}>
              {t("Retry permission check", "重新读取权限")}
            </Button>
            <Button variant="ghost" onClick={logout}>
              {t("Sign in again", "重新登录")}
            </Button>
          </div>
        </AlertDescription>
      </Alert>
    )
  if (!user)
    return <p role="status">{t("Checking permissions…", "正在读取权限…")}</p>
  return (
    <RunManager
      key={`${user.id}:${projectId}`}
      projectId={projectId}
      actor={user.id}
    />
  )
}

function RunManager({
  projectId,
  actor,
}: {
  projectId: string
  actor: string
}) {
  const { t, translateValue } = useI18n()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const storageKey = `exposure:comparison-start:${actor}:${projectId}`
  const [initial] = useState(() => {
    try {
      const raw = sessionStorage.getItem(storageKey)
      return {
        intent: raw ? runIntentSchema.parse(JSON.parse(raw)) : null,
        error: false,
      }
    } catch {
      return { intent: null, error: true }
    }
  })
  const [intent, setIntent] = useState(initial.intent)
  const [storageFailed, setStorageFailed] = useState(initial.error)
  const [confirmedHash, setConfirmedHash] = useState<string | null>(null)
  const entryTitle = useRef<HTMLDivElement>(null)
  const confirmationTitle = useRef<HTMLHeadingElement>(null)
  const entryFocused = useRef(false)
  const active = useRef(true)
  useEffect(() => {
    active.current = true
    return () => {
      active.current = false
    }
  }, [])
  const clearIntent = useCallback(() => {
    try {
      sessionStorage.removeItem(storageKey)
      setIntent(null)
      setConfirmedHash(null)
    } catch {
      setStorageFailed(true)
    }
  }, [storageKey])
  const rerunIds = useRef<Record<string, string>>({})
  const runCountBeforeTrigger = useRef(0)
  const [message, setMessage] = useState<string | null>(null)
  const [sessionPending, setSessionPending] = useState(false)
  const queryKey = ["governance-runs", projectId]
  const runsQuery = useQuery({
    queryKey,
    queryFn: () => GovernanceRunsService.readGovernanceRuns({ projectId }),
    refetchInterval: (query) =>
      sessionPending ||
      intent !== null ||
      query.state.data?.data.some((run) => run.status === "RUNNING")
        ? 2000
        : false,
  })
  useEffect(() => {
    if (runsQuery.isSuccess && !entryFocused.current) {
      ;(confirmationTitle.current ?? entryTitle.current)?.focus()
      entryFocused.current = true
    }
  }, [runsQuery.isSuccess])
  const completedRunId = runsQuery.data?.data.find(
    (run) =>
      (run.status === "COMPLETED" ||
        run.status === "COMPLETED_WITH_WARNINGS") &&
      run.completed_at !== null,
  )?.id
  useEffect(() => {
    if (completedRunId) {
      void queryClient.invalidateQueries({
        queryKey: ["workspace-published-reports", projectId],
      })
    }
  }, [completedRunId, projectId, queryClient])
  useEffect(() => {
    const data = runsQuery.data
    if (data?.launch_blocking_code === "run_launch_terminal_use_new_trigger") {
      if (intent) clearIntent()
      rerunIds.current = {}
      setSessionPending(false)
    }
    if (
      sessionPending &&
      !intent &&
      data &&
      data.count > runCountBeforeTrigger.current &&
      !data.data.some((run) => run.status === "RUNNING")
    ) {
      setSessionPending(false)
    }
  }, [runsQuery.data, sessionPending, clearIntent, intent])
  useEffect(() => {
    if (!intent || !runsQuery.data || !active.current) return
    const run = runsQuery.data.data.find(
      (item) => item.trigger_id === intent.key,
    )
    if (!run) return
    if (intent.runId && run.id !== intent.runId) {
      setStorageFailed(true)
      return
    }
    if (run.published) {
      try {
        sessionStorage.removeItem(storageKey)
      } catch {
        setStorageFailed(true)
        return
      }
      setIntent(null)
      toast.success(
        t(
          "Comparison published. Review the asset differences.",
          "本轮比对已完成，可以查看资产差异。",
        ),
      )
      const explicitRun = new URLSearchParams(window.location.search).get("run")
      if (!explicitRun || explicitRun === run.id)
        void navigate({
          to: "/",
          search: { project: projectId, run: run.id, view: "overview" },
          hash: "workspace-overview-title",
        })
    } else if (
      run.status === "FAILED_DATA" ||
      run.status === "FAILED_PROCESSING"
    ) {
      setMessage(
        "The comparison failed. Its inputs and run record are preserved.",
      )
      clearIntent()
      setSessionPending(false)
    }
  }, [intent, runsQuery.data, navigate, projectId, storageKey, clearIntent, t])
  const triggerMutation = useMutation({
    mutationFn: async () => {
      const pending =
        intent ??
        runIntentSchema.parse({
          key: crypto.randomUUID(),
          confirmationHash: confirmedHash,
          runId: null,
          controlId: null,
        })
      try {
        sessionStorage.setItem(storageKey, JSON.stringify(pending))
      } catch {
        setStorageFailed(true)
        throw new Error("Recovery storage unavailable")
      }
      setIntent(pending)
      const token = localStorage.getItem("access_token")
      try {
        const result = await GovernanceRunsService.triggerGovernanceRun({
          projectId,
          idempotencyKey: pending.key,
          requestBody: { confirmation_input_hash: pending.confirmationHash },
        })
        if (
          (pending.runId && result.governance_run_id !== pending.runId) ||
          (pending.controlId &&
            result.agent_compose_run_id !== pending.controlId)
        )
          throw new Error("Run recovery identity mismatch")
        return { result, pending, token }
      } catch (failure) {
        if (token !== localStorage.getItem("access_token"))
          throw new Error("Account changed")
        throw failure
      }
    },
    onSuccess: async ({ result, pending, token }) => {
      if (!active.current || token !== localStorage.getItem("access_token"))
        return
      const reserved = {
        ...pending,
        runId: result.governance_run_id,
        controlId: result.agent_compose_run_id,
      }
      try {
        sessionStorage.setItem(storageKey, JSON.stringify(reserved))
      } catch {
        /* The original saved key and hash remain replayable. */
      }
      setIntent(reserved)
      setMessage(
        result.governance_run_id
          ? "The existing idempotent Run was found."
          : "Governance Session accepted. Waiting for the Runner to start.",
      )
      setSessionPending(true)
      await queryClient.invalidateQueries({ queryKey })
    },
    onError: async (error) => {
      if (!active.current) return
      const code = rejectionCode(error)
      if (
        code === "run_launch_terminal_use_new_trigger" ||
        code === "run_inputs_changed" ||
        (error instanceof ApiError &&
          !isInactiveAccountError(error) &&
          [400, 422].includes(error.status))
      ) {
        clearIntent()
        setSessionPending(false)
      }
      setMessage(
        code === "run_inputs_changed"
          ? "Inputs changed. Review and confirm the current versions again."
          : code === "run_confirmation_conflict"
            ? "This request is bound to different inputs. Keep the saved request; no new comparison was started."
            : code === "run_launch_terminal_use_new_trigger"
              ? BLOCKING_MESSAGES[code]
              : "The result is not confirmed. Resume the same saved request; do not start another comparison.",
      )
      await queryClient.invalidateQueries({ queryKey })
    },
  })
  const retryMutation = useMutation({
    mutationFn: (runId: string) =>
      GovernanceRunsService.retryGovernanceRun({ projectId, runId }),
    onSuccess: async () => {
      setMessage("Retry accepted for the same Governance Run and Session.")
      await queryClient.invalidateQueries({ queryKey })
    },
    onError: async () => {
      setMessage("Retry was rejected. Review the stable recovery status below.")
      await queryClient.invalidateQueries({ queryKey })
    },
  })
  const rerunMutation = useMutation({
    mutationFn: (runId: string) => {
      rerunIds.current[runId] ??= crypto.randomUUID()
      return GovernanceRunsService.rerunGovernanceRun({
        projectId,
        runId,
        idempotencyKey: rerunIds.current[runId],
      })
    },
    onSuccess: async (_result, runId) => {
      delete rerunIds.current[runId]
      setMessage("Rerun accepted with current inputs and a new Trigger ID.")
      setSessionPending(true)
      runCountBeforeTrigger.current = runsQuery.data?.count ?? 0
      await queryClient.invalidateQueries({ queryKey })
    },
    onError: async (error, runId) => {
      const code = rejectionCode(error)
      if (code === "run_launch_terminal_use_new_trigger") {
        delete rerunIds.current[runId]
        setMessage(BLOCKING_MESSAGES[code])
      } else {
        setMessage(
          "Rerun was rejected. Review the stable recovery status below.",
        )
      }
      await queryClient.invalidateQueries({ queryKey })
    },
  })

  if (runsQuery.isPending)
    return (
      <p role="status">{t("Loading Governance Runs…", "正在加载治理运行…")}</p>
    )
  if (runsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>
          {t("Governance Runs could not be loaded", "无法加载治理运行")}
        </AlertTitle>
        <AlertDescription>
          {t("Please try again later.", "请稍后重试。")}
        </AlertDescription>
      </Alert>
    )
  }

  const runs = runsQuery.data
  const readinessMessage = runs.readiness_code
    ? (READINESS_MESSAGES[runs.readiness_code] ?? "Run inputs are not ready.")
    : null
  const launchBlockingMessage = runs.launch_blocking_code
    ? (BLOCKING_MESSAGES[runs.launch_blocking_code] ??
      "The Governance Runner launch is currently blocked.")
    : null

  return (
    <section className="space-y-4" aria-labelledby="governance-runs-title">
      <Card>
        <CardHeader>
          <CardTitle
            ref={entryTitle}
            tabIndex={-1}
            role="heading"
            aria-level={2}
            id="governance-runs-title"
          >
            {t("Governance Runs", "治理运行")}
          </CardTitle>
          <CardDescription>
            {t(
              "Compare the selected register and external observations, with optional NetFlow activity. A result appears only after publication succeeds.",
              "比对已选台账与外部观测，可附加 NetFlow 活动。发布成功后才展示本轮结果。",
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {runs.input_preview && (
            <div className="space-y-3 rounded-lg bg-muted/50 p-4">
              <h3
                ref={confirmationTitle}
                tabIndex={-1}
                className="font-semibold"
              >
                {t("Confirm these input versions", "确认本轮输入版本")}
              </h3>
              <dl className="grid gap-3 text-sm sm:grid-cols-3">
                <div>
                  <dt className="text-muted-foreground">
                    {t("Asset register", "资产台账")}
                  </dt>
                  <dd className="break-words">
                    {runs.input_preview.customer_filename} · v
                    {runs.input_preview.customer_profile_version} ·{" "}
                    {runs.input_preview.customer_record_count}{" "}
                    {t("records", "条")}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">
                    {t("External observations", "外部观测")}
                  </dt>
                  <dd className="break-words">
                    {runs.input_preview.source_instance_name}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">NetFlow</dt>
                  <dd className="break-words">
                    {runs.input_preview.netflow_filename
                      ? `${runs.input_preview.netflow_filename} · ${runs.input_preview.netflow_record_count} ${t("records", "条")}`
                      : t(
                          "Not selected · two-source comparison",
                          "未选择 · 两来源比对",
                        )}
                  </dd>
                </div>
              </dl>
              <details>
                <summary className="cursor-pointer text-sm">
                  {t("Input identities", "输入版本详情")}
                </summary>
                <div className="space-y-2 py-2">
                  <TechnicalValue
                    value={runs.input_preview.customer_upload_id}
                    label={t("Asset register version", "台账版本")}
                  />
                  <TechnicalValue
                    value={runs.input_preview.source_fingerprint}
                    label={t("Source validation identity", "来源验证身份")}
                  />
                  {runs.input_preview.netflow_dataset_id && (
                    <TechnicalValue
                      value={runs.input_preview.netflow_dataset_id}
                      label={t("NetFlow version", "NetFlow 版本")}
                    />
                  )}
                </div>
              </details>
              {(runs.can_operate ?? runs.can_trigger) && !intent && (
                <label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm">
                  <input
                    type="checkbox"
                    checked={
                      confirmedHash ===
                      runs.input_preview.confirmation_input_hash
                    }
                    onChange={(event) =>
                      setConfirmedHash(
                        event.target.checked
                          ? runs.input_preview!.confirmation_input_hash
                          : null,
                      )
                    }
                  />
                  {t(
                    "Use these versions for this comparison",
                    "使用以上版本进行本轮比对",
                  )}
                </label>
              )}
            </div>
          )}
          {intent && (
            <p role="status" className="text-sm">
              {t(
                "A saved request is being tracked. Refresh only reads its status. Resume explicitly if needed; this may submit the original intent if it never reached the server.",
                "正在追踪已保存的请求。刷新只读取状态；必要时显式恢复，若原请求从未到达服务端，恢复会提交同一次已确认意图。",
              )}
            </p>
          )}
          {storageFailed && (
            <Alert variant="destructive">
              <AlertDescription>
                {t(
                  "Recovery storage is unavailable or invalid. No new request will be sent until browser storage is restored.",
                  "恢复存储不可用或内容异常。恢复浏览器存储前不会发送新的请求。",
                )}
              </AlertDescription>
            </Alert>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <Badge
                className={runs.ready ? "text-black" : undefined}
                variant={runs.ready ? "default" : "secondary"}
              >
                {runs.ready
                  ? t("Inputs ready", "输入已就绪")
                  : t("Not ready", "尚未就绪")}
              </Badge>
              {readinessMessage && runs.readiness_code && (
                <p className="mt-2 text-sm text-muted-foreground">
                  {t(
                    readinessMessage,
                    `${MESSAGE_ZH[readinessMessage] ?? readinessMessage} (${translateValue(runs.readiness_code)})`,
                  )}
                </p>
              )}
              {launchBlockingMessage && runs.launch_blocking_code && (
                <Alert className="mt-2">
                  <AlertTitle>{t("Launch status", "启动状态")}</AlertTitle>
                  <AlertDescription>
                    {t(
                      launchBlockingMessage,
                      `${MESSAGE_ZH[launchBlockingMessage] ?? launchBlockingMessage} (${translateValue(runs.launch_blocking_code)})`,
                    )}
                  </AlertDescription>
                </Alert>
              )}
            </div>
            {(runs.can_operate ?? runs.can_trigger) && intent && (
              <Button
                disabled={storageFailed || triggerMutation.isPending}
                onClick={() => triggerMutation.mutate()}
              >
                {t("Resume saved request", "恢复原启动请求")}
              </Button>
            )}
            {runs.can_trigger && !intent && (
              <LoadingButton
                type="button"
                className="text-black"
                loading={triggerMutation.isPending}
                disabled={
                  !runs.ready ||
                  storageFailed ||
                  !runs.input_preview ||
                  confirmedHash !== runs.input_preview.confirmation_input_hash
                }
                onClick={() => {
                  setMessage(null)
                  runCountBeforeTrigger.current = runs.count
                  triggerMutation.mutate()
                }}
              >
                <Play />
                {t("Trigger Run", "开始比对")}
              </LoadingButton>
            )}
          </div>
          {message && (
            <p className="text-sm" role="status">
              {t(message, MESSAGE_ZH[message] ?? message)}
            </p>
          )}
        </CardContent>
      </Card>

      {runs.data.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {t("No Governance Runs yet.", "尚无治理运行。")}
        </p>
      ) : (
        runs.data.map((run) => (
          <RunDetails
            key={run.id}
            run={run}
            projectId={projectId}
            onRetry={() => {
              setMessage(null)
              retryMutation.mutate(run.id)
            }}
            onRerun={() => {
              setMessage(null)
              rerunMutation.mutate(run.id)
            }}
            retrying={
              retryMutation.isPending && retryMutation.variables === run.id
            }
            rerunning={
              rerunMutation.isPending && rerunMutation.variables === run.id
            }
          />
        ))
      )}
    </section>
  )
}
