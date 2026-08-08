import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
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

const READINESS_MESSAGES: Record<string, string> = {
  run_project_archived: "Archived Projects cannot start a Governance Run.",
  run_customer_upload_not_ready:
    "Select an accepted CustomerUpload before starting a Run.",
  run_cloudatlas_source_not_ready:
    "Enable and validate the CloudAtlas source before starting a Run.",
  run_cloudatlas_credential_not_ready:
    "The deployment CloudAtlas Run credential is not configured.",
}

const BLOCKING_MESSAGES: Record<string, string> = {
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
  run_launch_in_progress: "A Governance Runner launch is already in progress.",
  run_launch_terminal_use_new_trigger:
    "The previous launch ended before creating a Run. Use a new Trigger ID.",
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
  onRetry,
  onRerun,
  retrying,
  rerunning,
}: {
  run: GovernanceRunPublic
  onRetry: () => void
  onRerun: () => void
  retrying: boolean
  rerunning: boolean
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-base">Run {run.id.slice(0, 8)}</CardTitle>
          <Badge variant={run.status === "COMPLETED" ? "default" : "secondary"}>
            {run.status}
          </Badge>
        </div>
        <CardDescription>
          Triggered {new Date(run.created_at).toLocaleString()} · Runner{" "}
          {run.runner_build_version}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-3 text-sm md:grid-cols-2">
          <div>
            <p className="font-medium">Customer input</p>
            <p className="break-all text-muted-foreground">
              CustomerUpload {run.customer_upload_id}
            </p>
            <p className="font-mono text-xs">
              {hashSummary(run.customer_upload_sha256)} · Profile v
              {run.customer_upload_profile_version}
            </p>
          </div>
          <div>
            <p className="font-medium">CloudAtlas input</p>
            <p className="break-all text-muted-foreground">
              SourceInstance {run.source_instance_id}
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
              <TableHead>Step</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Attempt</TableHead>
              <TableHead>Result</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {run.steps.map((step) => (
              <TableRow key={step.step_code}>
                <TableCell className="font-medium">{step.step_code}</TableCell>
                <TableCell>
                  <Badge variant="secondary">{step.status}</Badge>
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
          <p className="mb-2 text-sm font-medium">SourceSnapshots</p>
          {run.snapshots.length === 0 ? (
            <p className="text-sm text-muted-foreground">No snapshots yet.</p>
          ) : (
            <div className="grid gap-2 md:grid-cols-2">
              {run.snapshots.map((snapshot) => (
                <div
                  key={snapshot.id}
                  className="rounded-md border p-3 text-sm"
                >
                  <p className="font-medium">{snapshot.source_type}</p>
                  <p>{snapshot.record_count} records</p>
                  <p className="font-mono text-xs">
                    SHA-256 {hashSummary(snapshot.content_sha256)}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>

        <p className="text-sm">
          Snapshots reused: {run.reused_snapshot_count ?? 0}
        </p>
        {run.blocking_code && (
          <Alert>
            <AlertTitle>Recovery status</AlertTitle>
            <AlertDescription>
              {BLOCKING_MESSAGES[run.blocking_code] ??
                "Recovery is currently blocked."}
            </AlertDescription>
          </Alert>
        )}
        {(run.can_retry || run.can_rerun) && (
          <div className="flex flex-wrap gap-2">
            {run.can_retry && (
              <LoadingButton type="button" loading={retrying} onClick={onRetry}>
                <RotateCcw />
                Retry same Session
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
                Rerun with current inputs
              </LoadingButton>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default function GovernanceRuns({ projectId }: { projectId: string }) {
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

  if (runsQuery.isPending) return <p role="status">Loading Governance Runs…</p>
  if (runsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Governance Runs could not be loaded</AlertTitle>
        <AlertDescription>Please try again later.</AlertDescription>
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
          <CardTitle id="governance-runs-title">Governance Runs</CardTitle>
          <CardDescription>
            Run LOAD_CUSTOMER, PULL_CLOUDATLAS, NORMALIZE, RESOLVE,
            CHECK_FINDINGS, then atomically PUBLISH two immutable
            SourceSnapshots.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <Badge variant={runs.ready ? "default" : "secondary"}>
                {runs.ready ? "Inputs ready" : "Not ready"}
              </Badge>
              {readinessMessage && (
                <p className="mt-2 text-sm text-muted-foreground">
                  {readinessMessage}
                </p>
              )}
              {launchBlockingMessage && (
                <Alert className="mt-2">
                  <AlertTitle>Launch status</AlertTitle>
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
                Trigger Run
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
        <p className="text-sm text-muted-foreground">No Governance Runs yet.</p>
      ) : (
        runs.data.map((run) => (
          <RunDetails
            key={run.id}
            run={run}
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
