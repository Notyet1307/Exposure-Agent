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
import { useLocale } from "@/components/LocaleProvider"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

const READINESS_MESSAGES = (text: (zh: string, en: string) => string): Record<string, string> => ({
  run_project_archived: text("已归档项目不能启动治理运行。", "Archived Projects cannot start a Governance Run."),
  run_customer_upload_not_ready:
    text("请先选择一份已通过校验的客户资产表。", "Select an accepted CustomerUpload before starting a Run."),
  run_cloudatlas_source_not_ready:
    text("请先验证并启用 CloudAtlas 来源。", "Enable and validate the CloudAtlas source before starting a Run."),
  run_cloudatlas_credential_not_ready:
    text("尚未配置部署环境的 CloudAtlas 运行凭据。", "The deployment CloudAtlas Run credential is not configured."),
})

const BLOCKING_MESSAGES = (text: (zh: string, en: string) => string): Record<string, string> => ({
  run_session_state_unknown:
    text("原会话状态未知，暂不能重试、重新运行或启动新运行。", "The original Session state is unknown. Retry, Rerun, and new Runs are blocked."),
  run_session_still_running:
    text("原会话仍在运行，占用本项目的运行名额。", "The original Session is still running and keeps the Project Run slot."),
  run_session_not_recoverable:
    text("原会话无法恢复，请明确选择重新运行。", "The original Session cannot be recovered. Use an explicit Rerun."),
  run_retry_customer_input_changed:
    text("已固定的客户资产表发生变化，无法重试；重新运行会使用当前输入。", "The fixed CustomerUpload changed. Retry is unavailable; Rerun uses current input."),
  run_retry_cloudatlas_input_changed:
    text("已固定的 CloudAtlas 输入发生变化，无法重试；重新运行会使用当前输入。", "The fixed CloudAtlas input changed. Retry is unavailable; Rerun uses current input."),
  run_retry_cloudatlas_input_unavailable:
    text("当前无法验证已固定的 CloudAtlas 输入。", "The fixed CloudAtlas input cannot currently be verified."),
  run_cloudatlas_credential_not_ready:
    text("尚未配置部署环境的 CloudAtlas 运行凭据。", "The deployment CloudAtlas Run credential is not configured."),
  run_cloudatlas_source_not_ready:
    text("重试前需要重新验证 CloudAtlas 来源。", "The CloudAtlas source requires fresh validation before Retry."),
  run_retry_newer_run_exists:
    text("已有更新的运行，本次运行永久保留为历史记录。", "A newer Run makes this Run permanently historical."),
  run_launch_in_progress: text("治理执行器正在启动。", "A Governance Runner launch is already in progress."),
  run_launch_terminal_use_new_trigger:
    text("上次启动在创建运行前已结束，请使用新的触发 ID。", "The previous launch ended before creating a Run. Use a new Trigger ID."),
})

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
  const { locale, text } = useLocale()
  const labels: Record<string, string> = { RUNNING: "运行中", COMPLETED: "已完成", COMPLETED_WITH_WARNINGS: "已完成（有警告）", FAILED_SOURCE: "来源读取失败", FAILED_DATA: "输入数据失败", FAILED_PROCESSING: "处理失败", FAILED_REPORT: "报告生成失败", SUCCEEDED: "成功", FAILED: "失败", PENDING: "待执行", LOAD_CUSTOMER: "加载客户资产", PULL_CLOUDATLAS: "读取 CloudAtlas", LOAD_NETFLOW: "加载 NetFlow", NORMALIZE: "规范化", RESOLVE: "关联资产", CHECK_FINDINGS: "检查发现项", PUBLISH: "发布", CUSTOMER_UPLOAD: "客户资产表", CLOUDATLAS: "CloudAtlas", NETFLOW: "NetFlow" }
  const label = (value: string) => text(labels[value] ?? value, value)
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-base">{text("运行", "Run")} {run.id.slice(0, 8)}</CardTitle>
          <Badge variant={run.status === "COMPLETED" ? "default" : "secondary"}>
            <span title={run.status}>{label(run.status)}</span>
          </Badge>
        </div>
        <CardDescription>
          {text("触发于", "Triggered")} {new Date(run.created_at).toLocaleString(locale === "zh" ? "zh-CN" : "en-US")} · {text("执行器", "Runner")}{" "}
          {run.runner_build_version}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-3 text-sm md:grid-cols-2">
          <div>
            <p className="font-medium">{text("客户输入", "Customer input")}</p>
            <p className="break-all text-muted-foreground">{text("客户资产表", "CustomerUpload")}{run.customer_upload_id}
            </p>
            <p className="font-mono text-xs">
              {hashSummary(run.customer_upload_sha256)}{text("· 配置版本 v", "· Profile v")}{run.customer_upload_profile_version}
            </p>
          </div>
          <div>
            <p className="font-medium">{text("CloudAtlas 输入", "CloudAtlas input")}</p>
            <p className="break-all text-muted-foreground">{text("来源实例", "SourceInstance")}{run.source_instance_id}
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
              <TableHead>{text("步骤", "Step")}</TableHead>
              <TableHead>{text("状态", "Status")}</TableHead>
              <TableHead>{text("尝试次数", "Attempt")}</TableHead>
              <TableHead>{text("结果", "Result")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {run.steps.map((step) => (
              <TableRow key={step.step_code}>
                <TableCell className="font-medium"><span title={step.step_code}>{label(step.step_code)}</span></TableCell>
                <TableCell>
                  <Badge variant="secondary"><span title={step.status}>{label(step.status)}</span></Badge>
                </TableCell>
                <TableCell>{step.attempt}</TableCell>
                <TableCell>
                  {step.output_hash ? hashSummary(step.output_hash) : "—"}
                  {step.error_code ? ` · ${step.error_code}` : ""}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>

        <div>
          <p className="mb-2 text-sm font-medium">{text("来源快照", "SourceSnapshots")}</p>
          {run.snapshots.length === 0 ? (
            <p className="text-sm text-muted-foreground">{text("尚无快照。", "No snapshots yet.")}</p>
          ) : (
            <div className="grid gap-2 md:grid-cols-2">
              {run.snapshots.map((snapshot) => (
                <div
                  key={snapshot.id}
                  className="rounded-md border p-3 text-sm"
                >
                  <p className="font-medium"><span title={snapshot.source_type}>{label(snapshot.source_type)}</span></p>
                  <p>{snapshot.record_count}{text(" 条记录", " records")}</p>
                  <p className="font-mono text-xs">
                    SHA-256 {hashSummary(snapshot.content_sha256)}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>

        <p className="text-sm">{text("复用快照数：", "Snapshots reused: ")}{run.reused_snapshot_count ?? 0}
        </p>
        {(run.status === "COMPLETED" ||
          run.status === "COMPLETED_WITH_WARNINGS") &&
          run.completed_at !== null && (
            <div className="flex flex-wrap gap-4">
              <Link
                to="/projects/$projectId/runs/$runId/comparison"
                params={{ projectId, runId: run.id }}
                className="inline-block text-sm underline underline-offset-4"
              >{text("查看三来源比较", "View source comparison")}</Link>
              <Link
                to="/projects/$projectId/runs/$runId/lineage"
                params={{ projectId, runId: run.id }}
                className="inline-block text-sm underline underline-offset-4"
              >{text("血缘追溯", "Lineage")}</Link>
            </div>
          )}
        {run.blocking_code && (
          <Alert>
            <AlertTitle>{text("恢复状态", "Recovery status")}</AlertTitle>
            <AlertDescription>
              {BLOCKING_MESSAGES(text)[run.blocking_code] ??
                text("当前无法恢复。", "Recovery is currently blocked.")}
            </AlertDescription>
          </Alert>
        )}
        {(run.can_retry || run.can_rerun) && (
          <div className="flex flex-wrap gap-2">
            {run.can_retry && (
              <LoadingButton type="button" loading={retrying} onClick={onRetry}>
                <RotateCcw />{text("在同一会话中重试", "Retry same Session")}</LoadingButton>
            )}
            {run.can_rerun && (
              <LoadingButton
                type="button"
                variant="outline"
                loading={rerunning}
                onClick={onRerun}
              >
                <Repeat2 />{text("使用当前输入重新运行", "Rerun with current inputs")}</LoadingButton>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default function GovernanceRuns({ projectId }: { projectId: string }) {
  const { text } = useLocale()
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
          ? text("已找到同一幂等请求对应的运行。", "The existing idempotent Run was found.")
          : text("治理会话已受理，正在等待执行器启动。", "Governance Session accepted. Waiting for the Runner to start."),
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
          ? BLOCKING_MESSAGES(text)[code]
          : text("治理会话启动失败，重试将复用同一触发 ID。", "The Governance Session could not be started. Retrying will reuse the same Trigger ID."),
      )
      await queryClient.invalidateQueries({ queryKey })
    },
  })
  const retryMutation = useMutation({
    mutationFn: (runId: string) =>
      GovernanceRunsService.retryGovernanceRun({ projectId, runId }),
    onSuccess: async () => {
      setMessage(text("已受理对同一治理运行与会话的重试。", "Retry accepted for the same Governance Run and Session."))
      await queryClient.invalidateQueries({ queryKey })
    },
    onError: async () => {
      setMessage(text("重试被拒绝，请查看下方恢复状态。", "Retry was rejected. Review the stable recovery status below."))
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
      setMessage(text("已受理重新运行，将使用当前输入和新的触发 ID。", "Rerun accepted with current inputs and a new Trigger ID."))
      setSessionPending(true)
      runCountBeforeTrigger.current = runsQuery.data?.count ?? 0
      await queryClient.invalidateQueries({ queryKey })
    },
    onError: async (error, runId) => {
      const code = rejectionCode(error)
      if (code === "run_launch_terminal_use_new_trigger") {
        delete rerunIds.current[runId]
        setMessage(BLOCKING_MESSAGES(text)[code])
      } else {
        setMessage(
          text("重新运行被拒绝，请查看下方恢复状态。", "Rerun was rejected. Review the stable recovery status below."),
        )
      }
      await queryClient.invalidateQueries({ queryKey })
    },
  })

  if (runsQuery.isPending) return <p role="status">{text("正在加载治理运行…", "Loading Governance Runs…")}</p>
  if (runsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>{text("无法加载治理运行", "Governance Runs could not be loaded")}</AlertTitle>
        <AlertDescription>{text("请稍后重试。", "Please try again later.")}</AlertDescription>
      </Alert>
    )
  }

  const runs = runsQuery.data
  const readinessMessage = runs.readiness_code
    ? (READINESS_MESSAGES(text)[runs.readiness_code] ?? text("运行输入尚未就绪。", "Run inputs are not ready."))
    : null
  const launchBlockingMessage = runs.launch_blocking_code
    ? (BLOCKING_MESSAGES(text)[runs.launch_blocking_code] ??
      text("当前无法启动治理执行器。", "The Governance Runner launch is currently blocked."))
    : null

  return (
    <section className="space-y-4" aria-labelledby="governance-runs-title">
      <Card>
        <CardHeader>
          <CardTitle id="governance-runs-title">{text("治理运行", "Governance Runs")}</CardTitle>
          <CardDescription>{text("依次加载客户资产、获取 CloudAtlas 数据、规范化、关联资产、检查发现项，并原子发布不可变来源快照；已选择 NetFlow 时也固定其快照。", "Run LOAD_CUSTOMER, PULL_CLOUDATLAS, NORMALIZE, RESOLVE, CHECK_FINDINGS, then atomically PUBLISH immutable CustomerUpload and CloudAtlas SourceSnapshots, with an optional third NetFlow SourceSnapshot.")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <Badge variant={runs.ready ? "default" : "secondary"}>
                {runs.ready ? text("输入已就绪", "Inputs ready") : text("尚未就绪", "Not ready")}
              </Badge>
              {readinessMessage && (
                <p className="mt-2 text-sm text-muted-foreground">
                  {readinessMessage}
                </p>
              )}
              {launchBlockingMessage && (
                <Alert className="mt-2">
                  <AlertTitle>{text("启动状态", "Launch status")}</AlertTitle>
                  <AlertDescription>{launchBlockingMessage}</AlertDescription>
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
                {text("触发运行", "Trigger Run")}
              </LoadingButton>
            )}
          </div>
          {message && (
            <p className="text-sm" role="status">
              {message}
            </p>
          )}
        </CardContent>
      </Card>

      {runs.data.length === 0 ? (
        <p className="text-sm text-muted-foreground">{text("尚无治理运行。", "No Governance Runs yet.")}</p>
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
