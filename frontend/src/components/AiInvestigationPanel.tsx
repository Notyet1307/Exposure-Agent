import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { z } from "zod"

import { AiInvestigationsService, ApiError } from "@/client"
import { TechnicalValue } from "@/components/TechnicalValue"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"

const outputSchema = z.object({
  facts: z.array(
    z.object({
      text: z.string().min(1),
      citation_ids: z.array(z.string().min(1)).min(1),
    }),
  ),
  explanations: z.array(z.string().min(1)),
  gaps: z.array(z.string().min(1)),
  next_steps: z.array(z.string().min(1)),
})
const materialItemSchema = z.object({
  citation_id: z.string().min(1),
  fact: z.record(z.string(), z.unknown()),
})
const toolReadSchema = z.object({
  id: z.string().uuid(),
  tool_name: z.enum([
    "read_asset_facts",
    "read_asset_history",
    "read_cloudatlas_asset",
  ]),
  queried_at: z.string().datetime({ offset: true }),
  completed_at: z.string().datetime({ offset: true }).nullable(),
  status: z.enum(["RUNNING", "SUCCEEDED", "FAILED"]),
  failure_code: z.string().nullable(),
  project_id: z.string(),
  resource_id: z.string(),
  run_id: z.string(),
  items: z.array(materialItemSchema),
  result: z.record(z.string(), z.unknown()).default({}),
})
const investigationSchema = z
  .object({
    id: z.string().min(1),
    project_id: z.string(),
    resource_id: z.string(),
    run_id: z.string(),
    finding_id: z.string().nullable(),
    parent_investigation_id: z.string().uuid().nullable(),
    question: z.string().trim().min(1).max(2000).nullable(),
    tool_reads: z.array(toolReadSchema),
    status: z.enum(["GENERATING", "COMPLETED", "FAILED"]),
    created_at: z.string(),
    completed_at: z.string().nullable(),
    failure_code: z.string().nullable(),
    output: outputSchema.nullable(),
    material: z.object({
      version: z.literal("ai-investigation-material/v1"),
      project_id: z.string(),
      scope: z.object({
        resource_id: z.string(),
        run_id: z.string(),
        finding_id: z.string().nullable(),
      }),
      published_at: z.string(),
      report_id: z.string(),
      report_contract_version: z.string(),
      truncated: z.boolean(),
      items: z.array(materialItemSchema),
    }),
  })
  .refine((value) =>
    value.status === "COMPLETED"
      ? value.output !== null
      : value.output === null,
  )
  .refine(
    (value) =>
      (value.parent_investigation_id === null) === (value.question === null),
  )

type Investigation = z.infer<typeof investigationSchema>
type Scope = {
  projectId: string
  resourceId: string
  runId: string
  findingId?: string
}
const recoverySchema = z
  .object({
    idempotencyKey: z.string().uuid(),
    investigationId: z.string().min(1).nullable(),
    parentInvestigationId: z.string().uuid().nullable().default(null),
    question: z.string().trim().min(1).max(2000).nullable().default(null),
  })
  .refine(
    (value) =>
      (value.parentInvestigationId === null) === (value.question === null),
  )
type Recovery = z.infer<typeof recoverySchema>
type Operation = Pick<Recovery, "parentInvestigationId" | "question">

function readRecovery(storageKey: string): Recovery | null {
  try {
    const value = recoverySchema.safeParse(
      JSON.parse(window.sessionStorage.getItem(storageKey) ?? "null"),
    )
    return value.success ? value.data : null
  } catch {
    return null
  }
}

function verifyScope(value: unknown, scope: Scope): Investigation {
  const result = investigationSchema.parse(value)
  if (
    result.project_id !== scope.projectId ||
    result.resource_id !== scope.resourceId ||
    result.run_id !== scope.runId ||
    result.finding_id !== (scope.findingId ?? null) ||
    result.material.project_id !== scope.projectId ||
    result.material.scope.resource_id !== scope.resourceId ||
    result.material.scope.run_id !== scope.runId ||
    result.material.scope.finding_id !== (scope.findingId ?? null) ||
    result.tool_reads.some(
      (read) =>
        read.project_id !== scope.projectId ||
        read.resource_id !== scope.resourceId ||
        read.run_id !== scope.runId ||
        (read.status !== "SUCCEEDED" && read.items.length > 0),
    )
  )
    throw new Error("Investigation scope mismatch")
  const items = [
    ...result.material.items,
    ...result.tool_reads
      .filter((read) => read.status === "SUCCEEDED")
      .flatMap((read) => read.items),
  ]
  const citations = new Map<string, string>()
  for (const item of items) {
    const fact = JSON.stringify(item.fact, (_key, value: unknown) =>
      value && typeof value === "object" && !Array.isArray(value)
        ? Object.fromEntries(
            Object.entries(value).sort(([left], [right]) =>
              left.localeCompare(right),
            ),
          )
        : value,
    )
    if (
      citations.has(item.citation_id) &&
      citations.get(item.citation_id) !== fact
    )
      throw new Error("Investigation conflicting citation")
    citations.set(item.citation_id, fact)
  }
  if (
    result.output?.facts.some((fact) =>
      fact.citation_ids.some((id) => !citations.has(id)),
    )
  )
    throw new Error("Investigation citation mismatch")
  return result
}

export function MaterialFields({ value }: { value: unknown }) {
  const { t } = useI18n()
  if (value === null || value === undefined)
    return <span>{t("Not recorded", "未记录")}</span>
  if (typeof value === "boolean")
    return <span>{value ? t("Yes", "是") : t("No", "否")}</span>
  if (Array.isArray(value))
    return value.length ? (
      <ul className="space-y-2 pl-3">
        {value.map((entry, index) => (
          <li key={index}>
            <MaterialFields value={entry} />
          </li>
        ))}
      </ul>
    ) : (
      <span>{t("No records", "无记录")}</span>
    )
  if (typeof value === "object")
    return (
      <dl className="min-w-0 space-y-1">
        {Object.entries(value).map(([key, entry]) => {
          const technical =
            key === "id" ||
            key === "identity" ||
            key === "hash" ||
            key === "sha256" ||
            key === "fingerprint" ||
            key === "schema_version" ||
            key.endsWith("_hash") ||
            key.endsWith("_hashes") ||
            key.endsWith("_id") ||
            key.endsWith("_ids") ||
            key.endsWith("_sha256") ||
            key.endsWith("_fingerprint") ||
            key.endsWith("_contract_version")
          return (
            <div key={key} className="min-w-0">
              <dt className="font-medium">{key.replace(/_/g, " ")}</dt>
              <dd className="break-all pl-2">
                {technical && entry != null ? (
                  <details>
                    <summary className="cursor-pointer font-medium">
                      {t("Technical details", "技术详情")}
                    </summary>
                    {Array.isArray(entry) && entry.length === 0
                      ? t("No records", "无记录")
                      : (Array.isArray(entry) ? entry : [entry]).map(
                          (identity, index) => (
                            <div key={index}>
                              <TechnicalValue
                                value={
                                  typeof identity === "string"
                                    ? identity
                                    : JSON.stringify(identity)
                                }
                              />
                            </div>
                          ),
                        )}
                  </details>
                ) : (
                  <MaterialFields value={entry} />
                )}
              </dd>
            </div>
          )
        })}
      </dl>
    )
  return <span className="break-all">{String(value)}</span>
}

function ReadSource({
  name,
}: {
  name: z.infer<typeof toolReadSchema>["tool_name"]
}) {
  const { t } = useI18n()
  return name === "read_cloudatlas_asset"
    ? t("Live CloudAtlas query", "CloudAtlas 实时查询")
    : name === "read_asset_history"
      ? t("Historical published snapshot", "历史已发布快照")
      : t("Published base material", "已发布基础材料")
}

export function AiInvestigationPanel(scope: Scope) {
  const { t, formatDate } = useI18n()
  const queryClient = useQueryClient()
  const storageKey = `exposure:ai-investigation:${scope.projectId}:${scope.resourceId}:${scope.runId}:${scope.findingId ?? "asset"}:idempotency-key`
  const [recovery, setRecovery] = useState(() => readRecovery(storageKey))
  const [storageFailed, setStorageFailed] = useState(false)
  const [questions, setQuestions] = useState<Record<string, string>>({})
  const queryKey = [
    "ai-investigations",
    scope.projectId,
    scope.resourceId,
    scope.runId,
    scope.findingId ?? null,
  ]
  const list = useQuery({
    queryKey,
    queryFn: async () => {
      const response = z
        .object({
          data: z.array(z.unknown()),
          count: z.number(),
          can_create: z.boolean(),
        })
        .parse(
          await AiInvestigationsService.readAiInvestigations({
            projectId: scope.projectId,
            resourceId: scope.resourceId,
            runId: scope.runId,
            findingId: scope.findingId,
            limit: 20,
          }),
        )
      return {
        ...response,
        data: response.data.map((item) => verifyScope(item, scope)),
      }
    },
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.data.some((item) => item.status === "GENERATING")
        ? 2000
        : false,
  })
  const selectedId = recovery?.investigationId ?? list.data?.data[0]?.id
  const detail = useQuery({
    queryKey: [...queryKey, selectedId],
    queryFn: async () => {
      if (!selectedId) throw new Error("Investigation identity missing")
      const result = verifyScope(
        await AiInvestigationsService.readAiInvestigation({
          projectId: scope.projectId,
          investigationId: selectedId,
        }),
        scope,
      )
      if (result.id !== selectedId)
        throw new Error("Investigation identity mismatch")
      if (
        recovery?.investigationId === result.id &&
        (result.parent_investigation_id !== recovery.parentInvestigationId ||
          result.question !== recovery.question)
      )
        throw new Error("Investigation operation mismatch")
      return result
    },
    enabled: !!selectedId && list.isSuccess,
    retry: false,
    refetchInterval: (query) =>
      !query.state.data || query.state.data.status === "GENERATING"
        ? 2000
        : false,
  })
  const persistRecovery = (value: Recovery) => {
    // Do not send a new request unless its full operation survives reload.
    window.sessionStorage.setItem(storageKey, JSON.stringify(value))
    setRecovery(value)
  }
  const start = useMutation({
    mutationFn: async (operation: Operation | null) => {
      const pending = operation
        ? {
            ...operation,
            idempotencyKey: crypto.randomUUID(),
            investigationId: null,
          }
        : recovery
      if (!pending) throw new Error("Investigation recovery missing")
      try {
        persistRecovery(pending)
        setStorageFailed(false)
      } catch {
        setStorageFailed(true)
        throw new Error("Investigation recovery storage unavailable")
      }
      const result = verifyScope(
        pending.parentInvestigationId && pending.question
          ? await AiInvestigationsService.createAiInvestigationFollowup({
              projectId: scope.projectId,
              investigationId: pending.parentInvestigationId,
              idempotencyKey: pending.idempotencyKey,
              requestBody: { question: pending.question },
            })
          : await AiInvestigationsService.createAiInvestigation({
              projectId: scope.projectId,
              idempotencyKey: pending.idempotencyKey,
              requestBody: {
                resource_id: scope.resourceId,
                run_id: scope.runId,
                finding_id: scope.findingId ?? null,
              },
            }),
        scope,
      )
      if (pending.investigationId && result.id !== pending.investigationId)
        throw new Error("Investigation identity mismatch")
      if (
        result.parent_investigation_id !== pending.parentInvestigationId ||
        result.question !== pending.question
      )
        throw new Error("Investigation operation mismatch")
      persistRecovery({ ...pending, investigationId: result.id })
      return result
    },
    onSuccess: (result) => {
      queryClient.setQueryData([...queryKey, result.id], result)
      setQuestions({})
      void queryClient.invalidateQueries({ queryKey })
    },
    onError: (error) => {
      // Confirmed API rejection is not an unknown launch; keep timeouts replayable.
      if (
        !(error instanceof ApiError) ||
        ![400, 401, 403, 404, 409, 422].includes(error.status)
      )
        return
      try {
        window.sessionStorage.removeItem(storageKey)
        setRecovery(null)
      } catch {
        setStorageFailed(true)
      }
      void queryClient.invalidateQueries({ queryKey })
    },
  })
  const current = list.isSuccess && detail.isSuccess ? detail.data : undefined
  const ancestors = useQuery({
    queryKey: [...queryKey, current?.id, "ancestors"],
    enabled: !!current?.parent_investigation_id,
    retry: false,
    queryFn: async () => {
      const turns: Investigation[] = []
      const seen = new Set([current?.id])
      let parentId = current?.parent_investigation_id
      while (parentId) {
        if (seen.has(parentId) || turns.length >= 7)
          throw new Error("Investigation conversation limit")
        seen.add(parentId)
        const parent = verifyScope(
          await AiInvestigationsService.readAiInvestigation({
            projectId: scope.projectId,
            investigationId: parentId,
          }),
          scope,
        )
        if (parent.id !== parentId || parent.status !== "COMPLETED")
          throw new Error("Investigation parent mismatch")
        turns.unshift(parent)
        parentId = parent.parent_investigation_id
      }
      return turns
    },
  })
  const unknownStart = recovery !== null && recovery.investigationId === null
  const canReplay =
    unknownStart || (recovery !== null && current?.status === "GENERATING")
  const canStart =
    list.isSuccess &&
    !list.isFetching &&
    list.data.can_create &&
    !start.isPending &&
    (canReplay || (!selectedId && !recovery) || current?.status === "FAILED")
  // A cached successful response is hidden after any failed scope-authorized read.
  const records = list.isSuccess ? list.data.data : []
  const visibleRecords =
    list.isSuccess && !ancestors.isError
      ? [
          ...new Map(
            [
              ...records,
              ...(current?.parent_investigation_id && ancestors.isSuccess
                ? ancestors.data
                : []),
              ...(current ? [current] : []),
            ].map((item) => [item.id, item]),
          ).values(),
        ].sort(
          (left, right) =>
            left.created_at.localeCompare(right.created_at) ||
            left.id.localeCompare(right.id),
        )
      : []
  const canFollowup =
    list.isSuccess &&
    !list.isFetching &&
    list.data.can_create &&
    !start.isPending &&
    !unknownStart &&
    !detail.isError &&
    !ancestors.isError &&
    !visibleRecords.some((item) => item.status === "GENERATING")
  const turnLimitReached =
    current?.parent_investigation_id &&
    ancestors.isSuccess &&
    ancestors.data.length >= 7
      ? current.id
      : null
  const rejection =
    start.error instanceof ApiError &&
    start.error.status >= 400 &&
    start.error.status < 500
      ? z
          .object({ detail: z.object({ code: z.string() }) })
          .safeParse(start.error.body)
      : null

  return (
    <section
      className="min-w-0 space-y-3 rounded-lg border p-4"
      aria-label={t("AI investigation", "AI 核查")}
    >
      <h2 className="text-lg font-semibold">
        {t("AI investigation", "AI 核查")}
      </h2>
      <p className="text-sm text-muted-foreground">
        {t(
          "Read-only AI analysis of this fixed published Run. Explanations require verification; this does not change findings or published facts.",
          "仅对固定的已发布运行进行只读 AI 分析。解释仍待验证，不修改发现项或已发布事实。",
        )}
      </p>
      <details className="min-w-0 text-xs">
        <summary className="cursor-pointer font-medium">
          {t("Fixed scope · technical details", "固定范围 · 技术详情")}
        </summary>
        <dl className="grid min-w-0 gap-2 text-xs sm:grid-cols-2">
          {[
            [t("Project", "项目"), scope.projectId],
            [t("Resource", "资源"), scope.resourceId],
            [t("Published Run", "已发布运行"), scope.runId],
            ...(scope.findingId
              ? [[t("Finding", "发现项"), scope.findingId]]
              : []),
          ].map(([label, value]) => (
            <div key={label} className="min-w-0">
              <dt className="font-medium">{label}</dt>
              <dd>
                <TechnicalValue value={value} label={label} />
              </dd>
            </div>
          ))}
        </dl>
      </details>
      {list.isSuccess && list.data.count > records.length && (
        <p className="text-xs text-muted-foreground">
          {t(
            `Showing the latest ${records.length} of ${list.data.count} saved investigations, plus prior turns of the selected result.`,
            `显示最近 ${records.length} 条核查（共 ${list.data.count} 条），以及选中结果的前序核查。`,
          )}
        </p>
      )}
      {list.isPending && (
        <p role="status">
          {t("Loading saved investigations…", "正在加载已保存的核查…")}
        </p>
      )}
      {(list.isError || detail.isError || ancestors.isError) && (
        <Alert variant="destructive">
          <AlertTitle>
            {t("Investigation could not be read", "无法读取核查")}
          </AlertTitle>
          <AlertDescription>
            {t(
              "The result is unavailable; no completion is assumed. Refresh to read again.",
              "结果不可用，不视为已完成。请刷新后重新读取。",
            )}
          </AlertDescription>
        </Alert>
      )}
      {list.isSuccess && !list.data.can_create && (
        <p className="text-sm text-muted-foreground">
          {t(
            "Read-only access. An Operator can start an investigation.",
            "当前为只读权限，Operator 可发起核查。",
          )}
        </p>
      )}
      {list.isSuccess && list.data.can_create && (
        <Button
          type="button"
          disabled={!canStart}
          onClick={() =>
            start.mutate(
              canReplay
                ? null
                : {
                    parentInvestigationId:
                      current?.parent_investigation_id ?? null,
                    question: current?.question ?? null,
                  },
            )
          }
        >
          {start.isPending
            ? t("Starting investigation…", "正在发起核查…")
            : canReplay
              ? t("Check previous request", "确认上次请求")
              : current?.status === "FAILED"
                ? t("Start a new attempt", "手动重新核查")
                : t("Investigate this asset", "核查此资产")}
        </Button>
      )}
      {rejection?.success && (
        <Alert variant="destructive">
          <AlertTitle>{t("Request rejected", "请求被拒绝")}</AlertTitle>
          <AlertDescription>
            {rejection.data.detail.code === "investigation_turn_limit"
              ? t(
                  "This conversation reached the eight-turn limit. Saved results remain readable.",
                  "此对话已达到八轮上限，已保存结果仍可回读。",
                )
              : t(
                  "The server could not accept this request within its authorization, material or execution limits. Saved results are unchanged.",
                  "服务端因权限、材料或执行边界未接受请求，已保存结果未改变。",
                )}
            <code className="block break-all">
              {rejection.data.detail.code}
            </code>
          </AlertDescription>
        </Alert>
      )}
      {(unknownStart || start.isError) && !rejection?.success && (
        <Alert>
          <AlertTitle>
            {storageFailed
              ? t("Browser storage unavailable", "浏览器存储不可用")
              : t("Start not yet confirmed", "尚未确认启动状态")}
          </AlertTitle>
          <AlertDescription>
            {storageFailed
              ? t(
                  "Enable session storage before starting; no new request was sent.",
                  "请启用会话存储后再发起；未发送新请求。",
                )
              : t(
                  "Check the previous request with the same identity. Do not start another attempt while its outcome is unknown.",
                  "请使用同一请求身份确认上次请求。结果未知时不会另开核查。",
                )}
          </AlertDescription>
        </Alert>
      )}
      {unknownStart && recovery.question && (
        <div className="space-y-1 text-sm">
          <p className="break-words">
            {t("Pending question", "待确认追问")}: {recovery.question}
          </p>
          <details className="text-xs">
            <summary className="cursor-pointer">
              {t(
                "Parent investigation · technical details",
                "上轮核查 · 技术详情",
              )}
            </summary>
            <TechnicalValue
              value={recovery.parentInvestigationId ?? ""}
              label={t("Parent investigation", "上轮核查")}
            />
          </details>
        </div>
      )}
      {selectedId && detail.isPending && (
        <p role="status">
          {t("Reading persisted execution status…", "正在读取持久化执行状态…")}
        </p>
      )}
      {current?.parent_investigation_id && ancestors.isPending && (
        <p role="status">{t("Loading prior turns…", "正在加载前序核查…")}</p>
      )}
      {list.isSuccess && visibleRecords.length === 0 && !unknownStart && (
        <p className="text-sm text-muted-foreground">
          {t(
            "No saved investigations for this scope.",
            "此范围暂无已保存的核查。",
          )}
        </p>
      )}
      {visibleRecords
        .filter((item) => !(item.id === selectedId && detail.isError))
        .map((item) => (
          <article key={item.id} className="min-w-0 space-y-3 border-t pt-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge>
                {item.status === "COMPLETED"
                  ? t("Completed", "已完成")
                  : item.status === "FAILED"
                    ? t("Failed", "失败")
                    : t("Generating", "生成中")}
              </Badge>
              <span className="text-xs">{formatDate(item.created_at)}</span>
            </div>
            <details className="min-w-0 text-xs">
              <summary className="cursor-pointer font-medium">
                {t("Investigation identifiers", "核查标识")}
              </summary>
              <TechnicalValue
                value={item.id}
                label={t("Investigation", "核查")}
              />
              {item.parent_investigation_id && (
                <p>
                  {t("Parent investigation", "上轮核查")}:{" "}
                  <TechnicalValue
                    value={item.parent_investigation_id}
                    label={t("Parent investigation", "上轮核查")}
                  />
                </p>
              )}
            </details>
            {item.question && (
              <div className="space-y-1 text-sm">
                <h3 className="font-medium">
                  {t("Saved question", "已保存追问")}
                </h3>
                <p className="whitespace-pre-wrap break-words">
                  {item.question}
                </p>
              </div>
            )}
            {item.status === "GENERATING" && (
              <p role="status" className="text-sm">
                {t(
                  "Awaiting a confirmed result. Unknown execution state is not success and does not trigger another session.",
                  "等待确认结果。未知执行状态不代表成功，也不会触发新会话。",
                )}
              </p>
            )}
            {item.failure_code && (
              <p className="break-all text-sm">
                {t("Execution message", "执行状态说明")}:{" "}
                <code>{item.failure_code}</code>
              </p>
            )}
            {item.status === "FAILED" && (
              <p className="text-sm">
                {t(
                  "This attempt failed. Published facts remain available and unchanged.",
                  "本次核查失败，已发布事实仍可使用且未被修改。",
                )}
              </p>
            )}
            {item.tool_reads.length > 0 && (
              <div className="space-y-2">
                <h3 className="font-medium">
                  {t("Tool reads", "工具读取记录")}
                </h3>
                <p className="text-xs text-muted-foreground">
                  {t(
                    "Historical snapshots describe earlier published Runs. Live queries describe query time, not the base Run, and do not change its facts or statistics.",
                    "历史快照描述此前已发布运行；实时查询描述查询时刻，不代表基础运行，也不修改其事实或统计。",
                  )}
                </p>
                {item.tool_reads.map((read) => (
                  <div
                    key={read.id}
                    className="min-w-0 space-y-1 rounded border p-2 text-xs"
                  >
                    <p className="font-medium">
                      <ReadSource name={read.tool_name} /> ·{" "}
                      {read.status === "SUCCEEDED"
                        ? t("Succeeded", "成功")
                        : read.status === "FAILED"
                          ? t("Failed", "失败")
                          : t("Reading", "读取中")}
                    </p>
                    <p>
                      {t("Queried", "查询时间")}: {formatDate(read.queried_at)}
                    </p>
                    <p>
                      {t("Finished", "结束时间")}:{" "}
                      {read.completed_at
                        ? formatDate(read.completed_at)
                        : t("Not recorded", "未记录")}
                    </p>
                    <details>
                      <summary className="cursor-pointer">
                        {t("Read identifiers", "读取标识")}
                      </summary>
                      <TechnicalValue
                        value={read.id}
                        label={t("Read record", "读取记录")}
                      />
                      <p>
                        {t("Fixed base Run", "固定基础运行")}:{" "}
                        <TechnicalValue
                          value={read.run_id}
                          label={t("Fixed base Run", "固定基础运行")}
                        />
                      </p>
                    </details>
                    {read.failure_code && (
                      <p className="break-all">
                        {t("Read failure", "读取失败")}: {read.failure_code}
                      </p>
                    )}
                    {read.status === "RUNNING" ? (
                      <p role="status">
                        {t(
                          "Read not yet confirmed; no facts or citations available.",
                          "读取尚未确认，暂无事实或引用。",
                        )}
                      </p>
                    ) : read.status === "FAILED" ? (
                      <p>
                        {t(
                          "No facts or citations from this failed read.",
                          "失败读取不产生事实或引用。",
                        )}
                      </p>
                    ) : read.items.length === 0 ? (
                      <p>
                        {t(
                          "No matching material returned; this is a gap, not proof of absence.",
                          "未返回匹配材料：这是资料缺口，不代表资产不存在。",
                        )}
                      </p>
                    ) : (
                      read.items.map((material) => (
                        <details key={material.citation_id}>
                          <summary className="cursor-pointer break-words">
                            <ReadSource name={read.tool_name} /> ·{" "}
                            {formatDate(read.queried_at)}
                          </summary>
                          <TechnicalValue
                            value={material.citation_id}
                            label={t("Citation", "引用")}
                          />
                          <MaterialFields value={material.fact} />
                        </details>
                      ))
                    )}
                    {Object.keys(read.result).length > 0 &&
                      (read.items.length === 0 ? (
                        <MaterialFields value={read.result} />
                      ) : (
                        <details>
                          <summary className="cursor-pointer">
                            {t("Read outcome and source", "读取结果与来源")}
                          </summary>
                          <MaterialFields value={read.result} />
                        </details>
                      ))}
                  </div>
                ))}
              </div>
            )}
            {item.status === "COMPLETED" && item.output && (
              <>
                <h3 className="font-medium">
                  {t("Cited facts", "有引用的事实")}
                </h3>
                {item.output.facts.length === 0 ? (
                  <p className="text-sm">
                    {t("No facts returned.", "未返回事实。")}
                  </p>
                ) : (
                  <ul className="list-disc space-y-2 pl-5 text-sm">
                    {item.output.facts.map((fact, index) => (
                      <li
                        key={`${item.id}-fact-${index}`}
                        className="break-words"
                      >
                        {fact.text}
                        <ul
                          className="mt-1 space-y-1 text-xs text-muted-foreground"
                          aria-label={t("Material citations", "材料引用")}
                        >
                          {fact.citation_ids.map((citation) => {
                            const base = item.material.items.find(
                              (entry) => entry.citation_id === citation,
                            )
                            const read = base
                              ? undefined
                              : item.tool_reads.find(
                                  (entry) =>
                                    entry.status === "SUCCEEDED" &&
                                    entry.items.some(
                                      (material) =>
                                        material.citation_id === citation,
                                    ),
                                )
                            const material =
                              base ??
                              read?.items.find(
                                (entry) => entry.citation_id === citation,
                              )
                            return (
                              <li key={citation} className="min-w-0">
                                <details>
                                  <summary className="cursor-pointer break-words">
                                    {read ? (
                                      <ReadSource name={read.tool_name} />
                                    ) : (
                                      t(
                                        "Published base material",
                                        "已发布基础材料",
                                      )
                                    )}{" "}
                                    ·{" "}
                                    {read
                                      ? t("Queried", "查询时间")
                                      : t("Published", "发布时间")}
                                    :{" "}
                                    {formatDate(
                                      read?.queried_at ??
                                        item.material.published_at,
                                    )}
                                  </summary>
                                  <TechnicalValue
                                    value={citation}
                                    label={t("Citation", "引用")}
                                  />
                                  <div className="rounded bg-muted p-2 text-xs">
                                    <MaterialFields value={material?.fact} />
                                  </div>
                                </details>
                              </li>
                            )
                          })}
                        </ul>
                      </li>
                    ))}
                  </ul>
                )}
                {(
                  [
                    [
                      t("Explanations to verify", "待验证解释"),
                      item.output.explanations,
                    ],
                    [t("Information gaps", "信息缺口"), item.output.gaps],
                    [t("Next steps", "下一步建议"), item.output.next_steps],
                  ] satisfies [string, string[]][]
                ).map(([title, entries]) => (
                  <div key={title} className="space-y-1">
                    <h3 className="font-medium">{title}</h3>
                    {entries.length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        {t("None returned.", "未返回内容。")}
                      </p>
                    ) : (
                      <ul className="list-disc space-y-1 pl-5 text-sm">
                        {entries.map((text, index) => (
                          <li
                            className="break-words"
                            key={`${item.id}-${title}-${index}`}
                          >
                            {text}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                ))}
                {item.material.truncated && (
                  <p className="text-sm text-muted-foreground">
                    {t(
                      "Material was bounded; additional records were not included.",
                      "材料受数量边界限制，未纳入其他记录。",
                    )}
                  </p>
                )}
              </>
            )}
            {item.status === "COMPLETED" &&
              list.isSuccess &&
              list.data.can_create && (
                <form
                  className="min-w-0 space-y-2"
                  onSubmit={(event) => {
                    event.preventDefault()
                    const question = (questions[item.id] ?? "").trim()
                    if (
                      canFollowup &&
                      item.id !== turnLimitReached &&
                      question &&
                      question.length <= 2000
                    )
                      start.mutate({ parentInvestigationId: item.id, question })
                  }}
                >
                  <label
                    className="block text-sm font-medium"
                    htmlFor={`followup-${item.id}`}
                  >
                    {t("Follow-up question", "继续追问")}
                  </label>
                  <textarea
                    id={`followup-${item.id}`}
                    className="block min-h-20 w-full min-w-0 rounded-md border bg-background p-2 text-sm"
                    maxLength={2000}
                    required
                    disabled={!canFollowup || item.id === turnLimitReached}
                    value={questions[item.id] ?? ""}
                    onChange={(event) =>
                      setQuestions((previous) => ({
                        ...previous,
                        [item.id]: event.target.value,
                      }))
                    }
                  />
                  <p className="break-all text-xs text-muted-foreground">
                    {t("Replying to", "追问对应核查")}:{" "}
                    {formatDate(item.created_at)} ·{" "}
                    {(questions[item.id] ?? "").length}/2000
                  </p>
                  {item.id === turnLimitReached && (
                    <p className="text-sm">
                      {t(
                        "This conversation reached the eight-turn limit. Saved results remain readable.",
                        "此对话已达到八轮上限，已保存结果仍可回读。",
                      )}
                    </p>
                  )}
                  <Button
                    type="submit"
                    disabled={
                      !canFollowup ||
                      item.id === turnLimitReached ||
                      !(questions[item.id] ?? "").trim()
                    }
                  >
                    {t("Submit follow-up", "提交追问")}
                  </Button>
                </form>
              )}
          </article>
        ))}
    </section>
  )
}
