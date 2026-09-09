import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { z } from "zod"

import { AiInvestigationsService } from "@/client"
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
const investigationSchema = z
  .object({
    id: z.string().min(1),
    project_id: z.string(),
    resource_id: z.string(),
    run_id: z.string(),
    finding_id: z.string().nullable(),
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
      items: z.array(
        z.object({
          citation_id: z.string().min(1),
          fact: z.record(z.string(), z.unknown()),
        }),
      ),
    }),
  })
  .refine((value) =>
    value.status === "COMPLETED"
      ? value.output !== null
      : value.output === null,
  )

type Investigation = z.infer<typeof investigationSchema>
type Scope = {
  projectId: string
  resourceId: string
  runId: string
  findingId?: string
}
type Recovery = { idempotencyKey: string; investigationId: string | null }

function readRecovery(storageKey: string): Recovery | null {
  try {
    const value = z
      .object({
        idempotencyKey: z.string().uuid(),
        investigationId: z.string().min(1).nullable(),
      })
      .safeParse(
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
    result.material.scope.finding_id !== (scope.findingId ?? null)
  ) {
    throw new Error("Investigation scope mismatch")
  }
  const citations = new Set(
    result.material.items.map((item) => item.citation_id),
  )
  if (
    citations.size !== result.material.items.length ||
    result.output?.facts.some((fact) =>
      fact.citation_ids.some((id) => !citations.has(id)),
    )
  ) {
    throw new Error("Investigation citation mismatch")
  }
  return result
}

export function AiInvestigationPanel(scope: Scope) {
  const { t, formatDate } = useI18n()
  const queryClient = useQueryClient()
  const storageKey = `exposure:ai-investigation:${scope.projectId}:${scope.resourceId}:${scope.runId}:${scope.findingId ?? "asset"}:idempotency-key`
  const [recovery, setRecovery] = useState(() => readRecovery(storageKey))
  const [storageFailed, setStorageFailed] = useState(false)
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
      return result
    },
    enabled: !!selectedId,
    retry: false,
    refetchInterval: (query) =>
      !query.state.data || query.state.data.status === "GENERATING"
        ? 2000
        : false,
  })
  const persistRecovery = (value: Recovery) => {
    // Do not send a new request unless its recovery identity survives reload.
    window.sessionStorage.setItem(storageKey, JSON.stringify(value))
    setRecovery(value)
  }
  const start = useMutation({
    mutationFn: async (newAttempt: boolean) => {
      const pending =
        !newAttempt && recovery
          ? recovery
          : { idempotencyKey: crypto.randomUUID(), investigationId: null }
      try {
        persistRecovery(pending)
        setStorageFailed(false)
      } catch {
        setStorageFailed(true)
        throw new Error("Investigation recovery storage unavailable")
      }
      const result = verifyScope(
        await AiInvestigationsService.createAiInvestigation({
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
      persistRecovery({ ...pending, investigationId: result.id })
      return result
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey })
    },
  })
  const current = list.isSuccess && detail.isSuccess ? detail.data : undefined
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
  const visibleRecords = records.map((item) =>
    current && item.id === current.id ? current : item,
  )
  if (current && !visibleRecords.some((item) => item.id === current.id))
    visibleRecords.unshift(current)

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
            <dd className="break-all font-mono">{value}</dd>
          </div>
        ))}
      </dl>
      {list.isSuccess && list.data.count > records.length && (
        <p className="text-xs text-muted-foreground">
          {t(
            `Showing the latest ${records.length} of ${list.data.count} saved investigations.`,
            `显示最近 ${records.length} 条核查，共 ${list.data.count} 条。`,
          )}
        </p>
      )}
      {list.isPending && (
        <p role="status">
          {t("Loading saved investigations…", "正在加载已保存的核查…")}
        </p>
      )}
      {(list.isError || detail.isError) && (
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
            start.mutate(!unknownStart && current?.status === "FAILED")
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
      {(unknownStart || start.isError) && (
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
      {selectedId && detail.isPending && (
        <p role="status">
          {t("Reading persisted execution status…", "正在读取持久化执行状态…")}
        </p>
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
            <p className="break-all font-mono text-xs">
              {t("Investigation", "核查")} {item.id}
            </p>
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
                          {fact.citation_ids.map((citation) => (
                            <li key={citation} className="min-w-0">
                              <details>
                                <summary className="cursor-pointer break-all font-mono">
                                  {citation}
                                </summary>
                                <p className="my-1">
                                  {t("Published material", "已发布材料")} ·{" "}
                                  {formatDate(item.material.published_at)}
                                </p>
                                <pre className="whitespace-pre-wrap break-all rounded bg-muted p-2 text-xs">
                                  {JSON.stringify(
                                    item.material.items.find(
                                      (material) =>
                                        material.citation_id === citation,
                                    )?.fact,
                                    null,
                                    2,
                                  )}
                                </pre>
                              </details>
                            </li>
                          ))}
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
          </article>
        ))}
    </section>
  )
}
