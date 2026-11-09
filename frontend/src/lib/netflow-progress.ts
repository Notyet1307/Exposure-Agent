import { ApiError } from "@/client"
import { netflowErrorCode } from "@/lib/netflow-errors"

export type NetflowProgressBackend = "netflow-bulk-v1"

export type NetflowProgressIdentity = {
  backend: NetflowProgressBackend
  project_id: string
  analysis_id: string
  dataset_id: string
  context_revision_id: string
  network_namespace: string
  test_fixture: boolean
}

export type NetflowProgressObservation = {
  status: string
  phase: string
  cancel_requested: boolean
  heartbeat_at: string | null
  lease_until: string | null
  files_completed: number
  files_total: number
  rows_normalized: number
  metrics: Record<string, unknown>
}

export type NetflowProgressProblem = "refusal" | "identity" | "transient"

export type NetflowProgressCancellation = "none" | "requested" | "confirmed"

export class NetflowProgressIdentityError extends Error {
  constructor() {
    super("Netflow progress identity mismatch")
    this.name = "NetflowProgressIdentityError"
  }
}

export class NetflowProgressShapeError extends Error {
  constructor() {
    super("Netflow progress response is malformed")
    this.name = "NetflowProgressShapeError"
  }
}

type ProgressSource = {
  project_id?: unknown
  analysis_id?: unknown
  dataset_id?: unknown
  context_revision_id?: unknown
  network_namespace?: unknown
  test_fixture?: unknown
  provenance?: unknown
}

const record = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value)

// The caller always passes an AnalysisPublic it has already bound to the page.
// This boundary check rejects anything that cannot be the known bulk contract
// without inventing fields the public analysis does not carry.
export function netflowProgressIdentity(
  analysis: ProgressSource | undefined,
): NetflowProgressIdentity | undefined {
  if (!analysis || !record(analysis.provenance)) return undefined
  const backend = analysis.provenance.backend
  if (backend !== "netflow-bulk-v1") return undefined
  const fields = [
    analysis.project_id,
    analysis.analysis_id,
    analysis.dataset_id,
    analysis.context_revision_id,
    analysis.network_namespace,
  ]
  if (fields.some((value) => typeof value !== "string" || !value.length))
    return undefined
  if (typeof analysis.test_fixture !== "boolean") return undefined
  return {
    backend,
    project_id: analysis.project_id as string,
    analysis_id: analysis.analysis_id as string,
    dataset_id: analysis.dataset_id as string,
    context_revision_id: analysis.context_revision_id as string,
    network_namespace: analysis.network_namespace as string,
    test_fixture: analysis.test_fixture,
  }
}

export function netflowProgressKey(
  scope: readonly unknown[],
  identity: NetflowProgressIdentity | undefined,
) {
  return [
    "netflow-progress",
    ...scope,
    identity?.backend ?? "none",
    identity?.project_id ?? "none",
    identity?.analysis_id ?? "none",
    identity?.dataset_id ?? "none",
    identity?.context_revision_id ?? "none",
    identity?.network_namespace ?? "none",
    identity?.test_fixture ?? "none",
  ]
}

const identityFields = [
  "project_id",
  "analysis_id",
  "dataset_id",
  "context_revision_id",
  "network_namespace",
  "test_fixture",
] as const

const count = (value: unknown) =>
  Number.isInteger(value) && (value as number) >= 0
    ? (value as number)
    : undefined

// Parses the untrusted progress payload into the one observation the UI may
// render. A payload that names another task is a mismatch, never data.
export function parseNetflowProgress(
  value: unknown,
  expected: NetflowProgressIdentity,
): NetflowProgressObservation {
  if (!record(value) || !record(value.provenance))
    throw new NetflowProgressShapeError()
  if (
    identityFields.some((key) => value[key] !== expected[key]) ||
    value.provenance.backend !== expected.backend
  )
    throw new NetflowProgressIdentityError()
  if (
    typeof value.status !== "string" ||
    !value.status ||
    typeof value.phase !== "string" ||
    !value.phase ||
    typeof value.cancel_requested !== "boolean"
  )
    throw new NetflowProgressShapeError()
  const heartbeat = value.heartbeat_at
  const lease = value.lease_until
  if (
    (heartbeat !== null && typeof heartbeat !== "string") ||
    (lease !== null && typeof lease !== "string")
  )
    throw new NetflowProgressShapeError()
  const files_completed = count(value.files_completed)
  const files_total = count(value.files_total)
  const rows_normalized = count(value.rows_normalized)
  if (
    files_completed === undefined ||
    files_total === undefined ||
    rows_normalized === undefined
  )
    throw new NetflowProgressShapeError()
  if (files_completed > files_total) throw new NetflowProgressShapeError()
  if (!record(value.metrics) && value.metrics !== undefined)
    throw new NetflowProgressShapeError()
  return {
    status: value.status,
    phase: value.phase,
    cancel_requested: value.cancel_requested,
    heartbeat_at: heartbeat,
    lease_until: lease,
    files_completed,
    files_total,
    rows_normalized,
    metrics: record(value.metrics) ? value.metrics : {},
  }
}

export function netflowProgressProblem(
  error: unknown,
): NetflowProgressProblem | undefined {
  if (
    error instanceof NetflowProgressIdentityError ||
    error instanceof NetflowProgressShapeError
  )
    return "identity"
  if (error instanceof ApiError) {
    if ([401, 403, 404, 410].includes(error.status)) return "refusal"
    if (
      error.status === 409 &&
      ["netflow_context_revoked", "netflow_artifact_integrity_failed"].includes(
        netflowErrorCode(error) ?? "",
      )
    )
      return "refusal"
  }
  return error === undefined || error === null ? undefined : "transient"
}

// Terminal only when the status and phase agree and the counters are whole.
// An unknown or contradictory phase keeps the observation non-terminal.
export function netflowProgressTerminal(
  observation: NetflowProgressObservation,
) {
  if (
    observation.status === "SUCCEEDED" ||
    observation.status === "SUCCEEDED_WITH_WARNINGS"
  )
    return (
      observation.phase === "SUCCEEDED" &&
      observation.files_completed === observation.files_total
    )
  if (observation.status === "FAILED")
    return observation.phase === "FAILED" || observation.phase === "CANCELLED"
  return false
}

// A local acknowledgement is only a request until one observation both failed
// and recorded the cancelled phase. Any terminal non-cancel observation wins.
export function netflowProgressCancellation(
  observation: NetflowProgressObservation | undefined,
  locallyRequested: boolean,
): NetflowProgressCancellation {
  if (observation?.status === "FAILED" && observation.phase === "CANCELLED")
    return "confirmed"
  // A terminal observation is the authority even if it still carries the
  // server's cancel flag: failed/succeeded is not "requested" any more.
  if (observation && netflowProgressTerminal(observation)) return "none"
  if (observation?.cancel_requested === true) return "requested"
  return locallyRequested ? "requested" : "none"
}
