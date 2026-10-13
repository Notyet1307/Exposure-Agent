import { useEffect, useRef, useState } from "react"
import { NetflowBulkService } from "@/client"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useI18n } from "@/lib/i18n"
import { netflowRequestRejected } from "@/lib/netflow-errors"

export function NetflowBulkRegistration({
  projectId,
  onRegistered,
}: {
  projectId: string
  onRegistered: (dataset: string) => void
}) {
  const { t } = useI18n()
  const [source, setSource] = useState("")
  const [ready, setReady] = useState("")
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(false)
  const operation = useRef<string | undefined>(undefined)
  const active = useRef(true)
  useEffect(() => {
    active.current = true
    return () => {
      active.current = false
    }
  }, [])
  const valid =
    /^[a-z][a-z0-9_-]{0,63}$/.test(source) && /^[0-9a-f]{64}$/.test(ready)
  return (
    <details className="space-y-3">
      <summary className="cursor-pointer font-medium">
        {t("Register a server batch", "登记服务器批次")}
      </summary>
      <p className="text-sm text-muted-foreground">
        {t(
          "Use the source and sealed batch identifier provided by your operator. Confirm its collection context before starting analysis.",
          "使用运维提供的来源和已封存批次编号。登记后确认采集上下文，再启动分析。",
        )}
      </p>
      <form
        className="space-y-3"
        onSubmit={async (event) => {
          event.preventDefault()
          if (!valid || pending) return
          operation.current ??= crypto.randomUUID()
          setPending(true)
          setError(false)
          try {
            const result = await NetflowBulkService.register({
              projectId,
              idempotencyKey: operation.current,
              requestBody: { source_id: source, ready_id: ready },
            })
            if (!active.current) return
            if (
              result.project_id !== projectId ||
              result.source_id !== source ||
              result.ready_id !== ready
            )
              throw new Error("Registration identity mismatch")
            operation.current = undefined
            onRegistered(result.dataset_id)
          } catch (cause) {
            if (!active.current) return
            if (netflowRequestRejected(cause)) operation.current = undefined
            setError(true)
          } finally {
            if (active.current) setPending(false)
          }
        }}
      >
        <div className="space-y-1">
          <Label htmlFor="bulk-source">
            {t("Source identifier", "来源编号")}
          </Label>
          <Input
            id="bulk-source"
            value={source}
            maxLength={64}
            disabled={pending || Boolean(operation.current)}
            onChange={(event) => setSource(event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="bulk-ready">
            {t("Sealed batch identifier", "封存批次编号")}
          </Label>
          <Input
            id="bulk-ready"
            value={ready}
            maxLength={64}
            disabled={pending || Boolean(operation.current)}
            onChange={(event) => setReady(event.target.value.trim())}
          />
        </div>
        <Button type="submit" variant="outline" disabled={!valid || pending}>
          {pending
            ? t("Registering…", "正在登记…")
            : operation.current
              ? t("Recover this registration", "恢复此登记")
              : t("Register batch", "登记批次")}
        </Button>
        {error && (
          <p role="alert">
            {t(
              "Registration could not be confirmed. Check the source and batch identifiers, then retry this registration.",
              "未能确认登记结果。请核对来源及批次编号，再重试此登记。",
            )}
          </p>
        )}
      </form>
    </details>
  )
}
