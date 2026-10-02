import { useEffect, useRef, useState } from "react"
import { ApiError, type ScopeChange, SourceCorrelationsService } from "@/client"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { useI18n } from "@/lib/i18n"

export function NetflowScopeControl({
  actor,
  projectId,
  revisionId,
  onRevision,
}: {
  actor: string
  projectId: string
  revisionId: string
  onRevision: (id: string) => void
}) {
  const { t } = useI18n()
  const store = `exposure:netflow-scope:${actor}:${projectId}:${revisionId}`
  const [evidence, setEvidence] = useState("")
  const [state, setState] = useState<ScopeChange["scope_state"]>("CONFIRMED")
  const [pending, setPending] = useState<string>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<[string, string]>()
  const active = useRef(true)
  useEffect(() => {
    active.current = true
    try {
      setPending(sessionStorage.getItem(store) || undefined)
    } catch {
      setError(["Recovery storage is unavailable.", "恢复存储不可用。"])
    }
    return () => {
      active.current = false
    }
  }, [store])
  const submit = async (recover: boolean) => {
    if (busy || (recover ? !pending : Boolean(pending) || !evidence.trim()))
      return
    const key = pending ?? crypto.randomUUID()
    setBusy(true)
    setError(undefined)
    try {
      if (!recover) {
        sessionStorage.setItem(store, key)
        setPending(key)
      }
      const revision = recover
        ? await SourceCorrelationsService.scopeOperation({
            projectId,
            revisionId,
            key,
          })
        : await SourceCorrelationsService.scopeRevision({
            projectId,
            revisionId,
            idempotencyKey: key,
            requestBody: {
              expected_parent_id: revisionId,
              scope_state: state,
              evidence: evidence.trim(),
            },
          })
      if (!active.current) return
      sessionStorage.removeItem(store)
      setPending(undefined)
      onRevision(revision.correlation_revision_id)
    } catch (cause) {
      if (!active.current) return
      if (
        !recover &&
        cause instanceof ApiError &&
        [400, 401, 403, 404, 409, 410, 422].includes(cause.status)
      ) {
        sessionStorage.removeItem(store)
        setPending(undefined)
      }
      setError([
        "Scope change unavailable. An unknown result must be queried using the original operation.",
        "范围更正不可用。结果未知时必须查询原操作。",
      ])
    } finally {
      if (active.current) setBusy(false)
    }
  }
  return (
    <section className="space-y-3 rounded border p-4">
      <h3 className="font-semibold">
        {t("Admin same-space confirmation", "Admin 同空间确认")}
      </h3>
      <Label>
        {t("Scope state", "范围状态")}
        <select
          className="block rounded border bg-background p-2"
          value={state}
          disabled={busy || Boolean(pending)}
          onChange={(event) =>
            setState(event.target.value as ScopeChange["scope_state"])
          }
        >
          <option value="CONFIRMED">CONFIRMED</option>
          <option value="UNKNOWN">UNKNOWN</option>
          <option value="REVOKED">REVOKED</option>
        </select>
      </Label>
      <Label>
        {t("Same-space evidence", "同空间依据")}
        <textarea
          className="block min-h-24 w-full rounded border bg-background p-2"
          value={evidence}
          maxLength={2048}
          disabled={busy || Boolean(pending)}
          onChange={(event) => setEvidence(event.target.value)}
        />
      </Label>
      <Button
        disabled={busy || Boolean(pending) || !evidence.trim()}
        onClick={() => void submit(false)}
      >
        {t("Append scope revision", "追加范围修订")}
      </Button>
      {pending && (
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => void submit(true)}
        >
          {t("Query original scope operation", "查询原范围操作")}
        </Button>
      )}
      {error && <p role="alert">{t(...error)}</p>}
    </section>
  )
}
