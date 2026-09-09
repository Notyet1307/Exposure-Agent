import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Play, Repeat2, RotateCcw } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import {
  ApiError,
  type GovernanceRunPublic,
  GovernanceRunsService,
} from "@/client"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
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

function hashSummary(value: string) {
  return `${value.slice(0, 12)}…`
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
            {t("Run", "运行")} {run.id.slice(0, 8)}
          </CardTitle>
          <Badge variant={run.status === "COMPLETED" ? "default" : "secondary"}>
            {translateValue(run.status)}
          </Badge>
        </div>
        <CardDescription>
          {t("Triggered", "触发于")} {formatDate(run.created_at)} · Runner{" "}
          {run.runner_build_version}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-3 text-sm md:grid-cols-2">
          <div>
            <p className="font-medium">{t("Customer input", "客户输入")}</p>
            <p className="break-all text-muted-foreground">
              {t("CustomerUpload", "客户上传")} {run.customer_upload_id}
            </p>
            <p className="font-mono text-xs">
              {hashSummary(run.customer_upload_sha256)} ·{" "}
              {t("Profile v", "配置版本 v")}
              {run.customer_upload_profile_version}
            </p>
          </div>
          <div>
            <p className="font-medium">
              {t("CloudAtlas input", "CloudAtlas 输入")}
            </p>
            <p className="break-all text-muted-foreground">
              {t("SourceInstance", "来源实例")} {run.source_instance_id}
            </p>
            <p className="font-mono text-xs">
              {hashSummary(run.cloudatlas_validated_fingerprint)} ·{" "}
              {run.cloudatlas_method}
            </p>
          </div>
        </div>

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
                <TableCell>
                  {step.output_hash ? hashSummary(step.output_hash) : "—"}
                  {step.error_code
                    ? ` · ${translateValue(step.error_code)}`
                    : ""}
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
                  className="rounded-md border p-3 text-sm"
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
                  <p className="font-mono text-xs">
                    SHA-256 {hashSummary(snapshot.content_sha256)}
                  </p>
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

export default function GovernanceRuns({ projectId }: { projectId: string }) {
  const { t, translateValue } = useI18n()
  const queryClient = useQueryClient()
  const triggerId = useRef<string | null>(null)
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
      query.state.data?.data.some((run) => run.status === "RUNNING")
        ? 2000
        : false,
  })
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
      triggerId.current = null
      rerunIds.current = {}
      setSessionPending(false)
    }
    if (
      sessionPending &&
      data &&
      data.count > runCountBeforeTrigger.current &&
      !data.data.some((run) => run.status === "RUNNING")
    ) {
      setSessionPending(false)
    }
  }, [runsQuery.data, sessionPending])
  const triggerMutation = useMutation({
    mutationFn: () => {
      triggerId.current ??= crypto.randomUUID()
      return GovernanceRunsService.triggerGovernanceRun({
        projectId,
        idempotencyKey: triggerId.current,
      })
    },
    onSuccess: async (result) => {
      setMessage(
        result.governance_run_id
          ? "The existing idempotent Run was found."
          : "Governance Session accepted. Waiting for the Runner to start.",
      )
      setSessionPending(result.governance_run_id === null)
      triggerId.current = null
      await queryClient.invalidateQueries({ queryKey })
    },
    onError: async (error) => {
      const code = rejectionCode(error)
      if (code === "run_launch_terminal_use_new_trigger") {
        triggerId.current = null
        rerunIds.current = {}
        setSessionPending(false)
      }
      setMessage(
        code === "run_launch_terminal_use_new_trigger"
          ? BLOCKING_MESSAGES[code]
          : "The Governance Session could not be started. Retrying will reuse the same Trigger ID.",
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
          <CardTitle id="governance-runs-title">
            {t("Governance Runs", "治理运行")}
          </CardTitle>
          <CardDescription>
            {t(
              "Run LOAD_CUSTOMER, PULL_CLOUDATLAS, NORMALIZE, RESOLVE, CHECK_FINDINGS, then atomically PUBLISH immutable CustomerUpload and CloudAtlas SourceSnapshots, with an optional third NetFlow SourceSnapshot.",
              "依次执行 LOAD_CUSTOMER（加载客户输入）、PULL_CLOUDATLAS（拉取 CloudAtlas）、NORMALIZE（标准化）、RESOLVE（解析资产）、CHECK_FINDINGS（检查发现项），最后通过 PUBLISH 原子发布不可变的客户上传与 CloudAtlas 来源快照，并可包含第三种 NetFlow 来源快照。",
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <Badge variant={runs.ready ? "default" : "secondary"}>
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
            {runs.can_trigger && (
              <LoadingButton
                type="button"
                loading={triggerMutation.isPending}
                disabled={!runs.ready}
                onClick={() => {
                  setMessage(null)
                  runCountBeforeTrigger.current = runs.count
                  triggerMutation.mutate()
                }}
              >
                <Play />
                {t("Trigger Run", "触发运行")}
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
