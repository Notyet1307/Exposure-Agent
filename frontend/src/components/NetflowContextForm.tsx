import { useEffect, useRef, useState } from "react"
import { type ContextPublic, NetflowProcessingService } from "@/client"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useI18n } from "@/lib/i18n"
import { netflowErrorCode, netflowRequestRejected } from "@/lib/netflow-errors"
import { netflowText } from "@/lib/netflow-labels"

export function NetflowContextForm({
  actor,
  projectId,
  datasetId,
  current,
  currentResolved,
  isAdmin,
  onCreated,
  onRefresh,
}: {
  actor: string
  projectId: string
  datasetId: string
  current: ContextPublic | undefined
  currentResolved: boolean
  isAdmin: boolean
  onRefresh: () => void
  onCreated: (context: ContextPublic) => void
}) {
  const { t } = useI18n()
  const store = `exposure:netflow-context:${actor}:${projectId}:${datasetId}`
  const [namespace, setNamespace] = useState(current?.network_namespace ?? "")
  const [state, setState] = useState<
    "CONFIRMED" | "UNKNOWN" | "CONFLICT" | "REVOKED"
  >("UNKNOWN")
  const [sourceEvidence, setSourceEvidence] = useState("")
  const [collectionScope, setCollectionScope] = useState("")
  const [collectionScopeEvidence, setCollectionScopeEvidence] = useState("")
  const [nat, setNat] = useState<"none" | "mapped" | "unknown">("unknown")
  const [natEvidence, setNatEvidence] = useState("")
  const [observationId, setObservationId] = useState("")
  const [view, setView] = useState<"PUBLIC_EDGE" | "INTERNAL" | "UNKNOWN">(
    "UNKNOWN",
  )
  const [sampling, setSampling] = useState<"unknown" | "unsampled" | "sampled">(
    "unknown",
  )
  const [rate, setRate] = useState("")
  const [pending, setPending] = useState<string>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<[string, string]>()
  const [conflict, setConflict] = useState(false)
  const alive = useRef(true)
  const scopeRef = useRef(store)
  scopeRef.current = store
  useEffect(() => {
    alive.current = true
    setNamespace((value) => value || current?.network_namespace || "")
    try {
      setPending(sessionStorage.getItem(store) || undefined)
    } catch {
      setError(["Recovery storage is unavailable.", "恢复存储不可用。"])
    }
    return () => {
      alive.current = false
    }
  }, [current?.network_namespace, store])
  const submit = async (recover = false) => {
    if (
      busy ||
      !isAdmin ||
      !currentResolved ||
      (recover ? !pending : Boolean(pending))
    )
      return
    if (
      !recover &&
      (!namespace.trim() ||
        !sourceEvidence.trim() ||
        !observationId.trim() ||
        (nat !== "unknown" && !natEvidence.trim()) ||
        (sampling === "sampled" &&
          (!rate || Number(rate) <= 0 || Number(rate) > 1)))
    ) {
      setError([
        "Complete the required context evidence before confirming.",
        "请先填写必填的上下文依据。",
      ])
      return
    }
    const key = pending ?? crypto.randomUUID()
    const captured = store
    setBusy(true)
    setError(undefined)
    setConflict(false)
    try {
      if (!recover) {
        sessionStorage.setItem(store, key)
        setPending(key)
      }
      const result = recover
        ? await NetflowProcessingService.contextOperation({
            projectId,
            datasetId,
            key,
          })
        : await NetflowProcessingService.createContext({
            projectId,
            datasetId,
            idempotencyKey: key,
            requestBody: {
              expected_parent_id: current?.current_context_revision_id ?? null,
              network_namespace: namespace.trim(),
              state,
              collection_scope: collectionScope.trim() || null,
              collection_scope_evidence: collectionScopeEvidence.trim() || null,
              endpoint_selection: "declared_source",
              source_position_evidence: sourceEvidence.trim(),
              nat_context: nat,
              nat_evidence: natEvidence.trim() || null,
              observation_point: { id: observationId.trim(), view },
              sampling: {
                mode: sampling,
                rate:
                  sampling === "unknown"
                    ? null
                    : sampling === "unsampled"
                      ? 1
                      : Number(rate),
              },
            },
          })
      if (!alive.current || scopeRef.current !== captured) return
      sessionStorage.removeItem(store)
      setPending(undefined)
      onCreated(result)
    } catch (cause) {
      if (!alive.current || scopeRef.current !== captured) return
      const code = netflowErrorCode(cause)
      const rejected = netflowRequestRejected(cause)
      if (!recover && rejected) {
        sessionStorage.removeItem(store)
        setPending(undefined)
      }
      setConflict(code === "netflow_revision_conflict")
      setError(
        code
          ? [netflowText(code, (en) => en), netflowText(code, (_, zh) => zh)]
          : rejected
            ? [
                "The context was rejected. Check the supplied fields and your access before trying again.",
                "上下文提交被拒绝，请检查填写字段和权限后重试。",
              ]
            : [
                "The result is uncertain. Query the original operation before trying again.",
                "操作结果尚不确定，再次操作前请查询原操作。",
              ],
      )
    } finally {
      if (alive.current && scopeRef.current === captured) setBusy(false)
    }
  }
  if (!isAdmin)
    return (
      <p className="mt-3 text-sm text-muted-foreground">
        {t(
          "An Admin must confirm the processing context before analysis can start.",
          "需要管理员确认处理上下文后才能启动分析。",
        )}
      </p>
    )
  return (
    <section
      className="mt-3 space-y-3 rounded border p-3"
      aria-label={t("Create processing context", "创建处理上下文")}
    >
      <h3 className="font-semibold">
        {t(
          current ? "Correct processing context" : "Confirm processing context",
          current ? "更正处理上下文" : "确认处理上下文",
        )}
      </h3>
      <p className="text-sm text-muted-foreground">
        {t(
          "Unknown is the initial state. This records supplied evidence; it does not start analysis.",
          "初始状态为未知。此处记录提供的依据，不会启动分析。",
        )}
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Label>
          {t("Network namespace", "网络空间")}
          <Input
            value={namespace}
            maxLength={64}
            onChange={(e) => setNamespace(e.target.value)}
            disabled={busy || Boolean(pending)}
          />
        </Label>
        <Label>
          {t("Observation point ID", "观测点 ID")}
          <Input
            value={observationId}
            maxLength={128}
            onChange={(e) => setObservationId(e.target.value)}
            disabled={busy || Boolean(pending)}
          />
        </Label>
      </div>
      <Label>
        {t("Context state", "上下文状态")}
        <select
          className="mt-1 block w-full rounded border bg-background p-2"
          value={state}
          onChange={(e) => setState(e.target.value as typeof state)}
          disabled={busy || Boolean(pending)}
        >
          <option value="UNKNOWN">{t("Unknown", "未知")}</option>
          <option value="CONFIRMED">{t("Confirmed", "已确认")}</option>
          <option value="CONFLICT">
            {t("Conflicting declarations", "声明冲突")}
          </option>
          <option value="REVOKED">{t("Revoked", "已撤销")}</option>
        </select>
      </Label>
      <Label>
        {t("Source-side position evidence", "源侧位置依据")}
        <textarea
          className="mt-1 min-h-20 w-full rounded border bg-background p-2"
          value={sourceEvidence}
          maxLength={2048}
          onChange={(e) => setSourceEvidence(e.target.value)}
          disabled={busy || Boolean(pending)}
        />
      </Label>
      <div className="grid gap-3 sm:grid-cols-2">
        <Label>
          {t("Collection scope (optional)", "采集范围（可选）")}
          <Input
            value={collectionScope}
            maxLength={128}
            onChange={(e) => setCollectionScope(e.target.value)}
            disabled={busy || Boolean(pending)}
          />
        </Label>
        <Label>
          {t("Collection scope evidence", "采集范围确认依据")}
          <Input
            value={collectionScopeEvidence}
            maxLength={2048}
            onChange={(e) => setCollectionScopeEvidence(e.target.value)}
            disabled={busy || Boolean(pending)}
          />
        </Label>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Label>
          {t("NAT situation", "NAT 情况")}
          <select
            className="mt-1 block w-full rounded border bg-background p-2"
            value={nat}
            onChange={(e) => setNat(e.target.value as typeof nat)}
            disabled={busy || Boolean(pending)}
          >
            <option value="unknown">{t("Unknown", "未知")}</option>
            <option value="none">
              {t("No NAT (evidence required)", "无 NAT（需要依据）")}
            </option>
            <option value="mapped">
              {t("NAT mapping exists", "存在 NAT 映射")}
            </option>
          </select>
        </Label>
        <Label>
          {t("Observation view", "观测视角")}
          <select
            className="mt-1 block w-full rounded border bg-background p-2"
            value={view}
            onChange={(e) => setView(e.target.value as typeof view)}
            disabled={busy || Boolean(pending)}
          >
            <option value="UNKNOWN">{t("Unknown", "未知")}</option>
            <option value="PUBLIC_EDGE">{t("Public edge", "公网边界")}</option>
            <option value="INTERNAL">{t("Internal", "内网")}</option>
          </select>
        </Label>
        <Label>
          {t("Sampling", "采样情况")}
          <select
            className="mt-1 block w-full rounded border bg-background p-2"
            value={sampling}
            onChange={(e) => setSampling(e.target.value as typeof sampling)}
            disabled={busy || Boolean(pending)}
          >
            <option value="unknown">{t("Unknown", "未知")}</option>
            <option value="unsampled">{t("Unsampled", "未采样")}</option>
            <option value="sampled">{t("Sampled", "已采样")}</option>
          </select>
        </Label>
      </div>
      <Label>
        {t("NAT evidence (optional when unknown)", "NAT 依据（未知时可选）")}
        <textarea
          className="mt-1 min-h-20 w-full rounded border bg-background p-2"
          value={natEvidence}
          maxLength={2048}
          onChange={(e) => setNatEvidence(e.target.value)}
          disabled={busy || Boolean(pending)}
        />
      </Label>
      {sampling === "sampled" && (
        <Label>
          {t("Sampling rate (0–1)", "采样率（0–1）")}
          <Input
            type="number"
            min="0.000001"
            max="1"
            step="any"
            value={rate}
            onChange={(e) => setRate(e.target.value)}
            disabled={busy || Boolean(pending)}
          />
        </Label>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          disabled={busy || Boolean(pending) || !currentResolved}
          onClick={() => void submit()}
        >
          {t("Append context version", "追加上下文版本")}
        </Button>
        {pending && (
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => void submit(true)}
          >
            {t("Query original context operation", "查询原上下文操作")}
          </Button>
        )}
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {t(...error)}
        </p>
      )}
      {conflict && (
        <Button
          variant="outline"
          onClick={() => {
            onRefresh()
            setConflict(false)
          }}
        >
          {t("Read latest context", "重读最新上下文")}
        </Button>
      )}
      {!currentResolved && (
        <p role="status" className="text-sm text-muted-foreground">
          {t(
            "Reading the current context before a change can be saved…",
            "正在读取当前上下文，暂不能保存更正…",
          )}
        </p>
      )}
    </section>
  )
}
