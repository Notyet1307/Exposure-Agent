import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Play } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { type GovernanceRunPublic, GovernanceRunsService } from "@/client"
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

function hashSummary(value: string) {
  return `${value.slice(0, 12)}…`
}

function RunDetails({ run }: { run: GovernanceRunPublic }) {
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
      </CardContent>
    </Card>
  )
}

export default function GovernanceRuns({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const triggerId = useRef<string | null>(null)
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
    onError: () =>
      setMessage(
        "The Governance Session could not be started. Retrying will reuse the same Trigger ID.",
      ),
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

  return (
    <section className="space-y-4" aria-labelledby="governance-runs-title">
      <Card>
        <CardHeader>
          <CardTitle id="governance-runs-title">Governance Runs</CardTitle>
          <CardDescription>
            Run LOAD_CUSTOMER, PULL_CLOUDATLAS, then atomically PUBLISH two
            immutable SourceSnapshots.
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
        runs.data.map((run) => <RunDetails key={run.id} run={run} />)
      )}
    </section>
  )
}
