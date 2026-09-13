import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useEffect, useId, useRef, useState } from "react"
import { z } from "zod"

import {
  type AnalysisReportPublic,
  AnalysisReportsService,
  type AnalysisReportText,
  ApiError,
} from "@/client"
import { MaterialFields } from "@/components/AiInvestigationPanel"
import { AiModelStatus, useAiSectionAnchor } from "@/components/AiWorkflow"
import { TechnicalValue } from "@/components/TechnicalValue"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import useAuth from "@/hooks/useAuth"
import { useI18n } from "@/lib/i18n"

const materialSchema = z.object({
  captured_at: z.string(),
  report_id: z.string(),
  report_contract_version: z.string(),
  summary: z.record(z.string(), z.unknown()),
  items: z.array(
    z.object({
      citation_id: z.string(),
      kind: z.string(),
      identity: z.string(),
      recorded_at: z.string().nullable(),
      data: z.record(z.string(), z.unknown()),
    }),
  ),
  gaps: z.array(z.string()),
  truncated: z.boolean(),
})

const textFields = [
  ["business_summary", "Business summary", "业务摘要"],
  ["key_differences", "Key differences", "重点差异"],
  [
    "investigation_progress",
    "Investigation and verification progress",
    "核查与验证进展",
  ],
  ["next_steps", "Next steps", "下一步"],
] as const

type Scope = {
  projectId: string
  runId: string
  reportId: string
  reportContractVersion: string
}

const recoverySchema = z.object({
  key: z.string().uuid(),
  reportId: z.string().nullable(),
})

function readRecovery(storageKey: string) {
  try {
    const parsed = recoverySchema.safeParse(
      JSON.parse(window.sessionStorage.getItem(storageKey) ?? "null"),
    )
    return parsed.success ? parsed.data : null
  } catch {
    return null
  }
}

export function AnalysisReportsPanel(scope: Scope) {
  const { user, userError } = useAuth()
  const { t } = useI18n()
  if (userError)
    return (
      <p role="alert">
        {t("Permissions could not be read.", "无法读取权限。")}
      </p>
    )
  if (!user)
    return <p role="status">{t("Checking permissions…", "正在读取权限…")}</p>
  return (
    <AnalysisReportsPanelForActor
      key={`${user.id}:${scope.projectId}:${scope.runId}:${scope.reportId}:${scope.reportContractVersion}`}
      {...scope}
      actor={user.id}
    />
  )
}

function AnalysisReportsPanelForActor(scope: Scope & { actor: string }) {
  const { t, formatDate, translateValue } = useI18n()
  const formId = useId()
  const queryClient = useQueryClient()
  const queryKey = [
    "analysis-reports",
    scope.actor,
    scope.projectId,
    scope.runId,
    scope.reportId,
    scope.reportContractVersion,
  ]
  const storageKey = `exposure:analysis-report:${scope.actor}:${scope.projectId}:${scope.runId}:idempotency-key`
  const active = useRef(true)
  const [token] = useState(() => localStorage.getItem("access_token"))
  const currentActor = useCallback(
    () => active.current && token === localStorage.getItem("access_token"),
    [token],
  )
  useEffect(() => {
    active.current = true
    return () => {
      active.current = false
    }
  }, [])
  const [recovery, setRecovery] = useState(() => readRecovery(storageKey))
  const requestKey = recovery?.key
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [editing, setEditing] = useState<{
    id: string
    revision: number
    text: AnalysisReportText
  } | null>(null)
  const verifyScope = (value: AnalysisReportPublic) => {
    const material = materialSchema.parse(value.material)
    if (
      value.project_id !== scope.projectId ||
      value.run_id !== scope.runId ||
      material.report_id !== scope.reportId ||
      material.report_contract_version !== scope.reportContractVersion
    )
      throw new Error("Analysis report scope mismatch")
    const ids = new Set(material.items.map((item) => item.citation_id))
    if (
      ids.size !== material.items.length ||
      value.original_output?.citation_ids.some((id) => !ids.has(id))
    )
      throw new Error("Analysis report citation mismatch")
    return { ...value, material }
  }
  const list = useQuery({
    queryKey,
    queryFn: async () => {
      const response = await AnalysisReportsService.readAnalysisReports({
        projectId: scope.projectId,
        runId: scope.runId,
      })
      return { ...response, data: response.data.map(verifyScope) }
    },
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.data.some((item) => item.status === "GENERATING")
        ? 2000
        : false,
  })
  const sectionHeading = useAiSectionAnchor(
    "analysis-reports-title",
    list.isSuccess,
  )
  const records = list.isSuccess ? list.data.data : []
  // Pin the initial version only after a fresh authorized read. Later appends never replace it.
  useEffect(() => {
    if (
      selectedId === null &&
      list.isSuccess &&
      !list.isFetching &&
      list.data.data[0]
    )
      setSelectedId(list.data.data[0].id)
  }, [selectedId, list.isSuccess, list.isFetching, list.data])
  const detail = useQuery({
    queryKey: [...queryKey, selectedId],
    queryFn: async () => {
      if (!selectedId) throw new Error("Analysis report identity missing")
      const result = verifyScope(
        await AnalysisReportsService.readAnalysisReport({
          projectId: scope.projectId,
          analysisReportId: selectedId,
        }),
      )
      if (result.id !== selectedId)
        throw new Error("Analysis report identity mismatch")
      return result
    },
    enabled: !!selectedId && list.isSuccess,
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.status === "GENERATING" ? 2000 : false,
  })
  const current = list.isSuccess && detail.isSuccess ? detail.data : undefined
  useEffect(() => {
    if (
      !currentActor() ||
      !recovery?.reportId ||
      !list.isSuccess ||
      list.isFetching
    )
      return
    const reserved = list.data.data.find(
      (item) => item.id === recovery.reportId,
    )
    if (!reserved || reserved.status === "GENERATING") return
    try {
      window.sessionStorage.removeItem(storageKey)
      setRecovery(null)
    } catch {
      /* Keep the same reservation replayable if storage cannot be cleared. */
    }
  }, [
    recovery,
    list.isSuccess,
    list.isFetching,
    list.data,
    storageKey,
    currentActor,
  ])
  const writable = list.isSuccess && list.data.can_create
  const fresh =
    list.isSuccess &&
    !list.isFetching &&
    (!selectedId || (detail.isSuccess && !detail.isFetching))
  const invalidate = () =>
    currentActor() && queryClient.invalidateQueries({ queryKey })
  const reject = (error: unknown) => {
    if (!currentActor()) return
    if (
      error instanceof ApiError &&
      [401, 403, 404, 409].includes(error.status)
    )
      void invalidate()
  }
  const generate = useMutation({
    mutationFn: async () => {
      if (!currentActor()) throw new Error("Account changed")
      const pending = recovery ?? { key: crypto.randomUUID(), reportId: null }
      // Persist before dispatch so an ambiguous response can be replayed after reload.
      window.sessionStorage.setItem(storageKey, JSON.stringify(pending))
      setRecovery(pending)
      const result = verifyScope(
        await AnalysisReportsService.createAnalysisReport({
          projectId: scope.projectId,
          idempotencyKey: pending.key,
          requestBody: { run_id: scope.runId },
        }),
      )
      if (!currentActor()) throw new Error("Account changed")
      if (pending.reportId && pending.reportId !== result.id)
        throw new Error("Analysis report reservation mismatch")
      const reserved = { ...pending, reportId: result.id }
      setRecovery(reserved)
      try {
        window.sessionStorage.setItem(storageKey, JSON.stringify(reserved))
      } catch {
        /* The key saved before dispatch still safely replays this reservation after reload. */
      }
      return result
    },
    onSuccess: (result) => {
      if (!currentActor()) return
      queryClient.setQueryData([...queryKey, result.id], result)
      if (selectedId === null) setSelectedId(result.id)
      void invalidate()
    },
    onError: (error) => {
      if (!currentActor()) return
      if (
        !recovery?.reportId &&
        error instanceof ApiError &&
        [400, 401, 403, 404, 409, 422].includes(error.status)
      ) {
        try {
          window.sessionStorage.removeItem(storageKey)
          setRecovery(null)
        } catch {
          /* Keep the request replayable if browser storage is unavailable. */
        }
      }
      reject(error)
    },
  })
  const save = useMutation({
    mutationFn: async () => {
      if (!currentActor()) throw new Error("Account changed")
      if (!editing) throw new Error("No analysis report edit")
      const result = verifyScope(
        await AnalysisReportsService.updateAnalysisReport({
          projectId: scope.projectId,
          analysisReportId: editing.id,
          requestBody: {
            expected_revision: editing.revision,
            text: editing.text,
          },
        }),
      )
      if (result.id !== editing.id)
        throw new Error("Analysis report identity mismatch")
      if (!currentActor()) throw new Error("Account changed")
      return result
    },
    onSuccess: (result) => {
      if (!currentActor()) return
      queryClient.setQueryData([...queryKey, result.id], result)
      setEditing(null)
      void invalidate()
    },
    onError: (error) => reject(error),
  })
  const confirm = useMutation({
    mutationFn: async () => {
      if (!currentActor()) throw new Error("Account changed")
      if (!current) throw new Error("No analysis report selected")
      const result = verifyScope(
        await AnalysisReportsService.confirmAnalysisReport({
          projectId: scope.projectId,
          analysisReportId: current.id,
          requestBody: { expected_revision: current.revision },
        }),
      )
      if (result.id !== current.id)
        throw new Error("Analysis report identity mismatch")
      if (!currentActor()) throw new Error("Account changed")
      return result
    },
    onSuccess: (result) => {
      if (!currentActor()) return
      queryClient.setQueryData([...queryKey, result.id], result)
      void invalidate()
    },
    onError: (error) => reject(error),
  })
  const busy = generate.isPending || save.isPending || confirm.isPending
  const canGenerate =
    writable &&
    fresh &&
    !busy &&
    (!!requestKey || !records.some((item) => item.status === "GENERATING"))
  const staleEdit =
    !!editing &&
    (editing.id !== current?.id ||
      editing.revision !== current?.revision ||
      current?.status !== "DRAFT")
  const statusLabels: Record<string, string> = {
    GENERATING: t("Generating", "生成中"),
    DRAFT: t("Draft", "草稿"),
    CONFIRMED: t("Human-confirmed", "已人工确认"),
    FAILED: t("Generation failed", "生成失败"),
  }
  const materialLabels: Record<string, string> = {
    BASE_RUN_SUMMARY: t("Published base summary", "已发布基础摘要"),
    INVESTIGATION: t("AI investigation", "AI 核查"),
    OBTAINED_TOOL_READ: t("Read-only query", "只读查询"),
    MANUAL_REVIEW: t("Manual review", "人工记录"),
  }
  const renderText = (text: AnalysisReportText) =>
    textFields.map(([field, en, zh]) => (
      <div key={field} className="min-w-0 max-w-prose space-y-1">
        <h4 className="font-medium">{t(en, zh)}</h4>
        <p className="whitespace-pre-wrap break-words leading-relaxed [overflow-wrap:anywhere]">
          {text[field]}
        </p>
      </div>
    ))
  const generateButton = writable && (
    <Button
      type="button"
      className="h-auto whitespace-normal"
      disabled={!canGenerate}
      onClick={() => generate.mutate()}
    >
      {generate.isPending
        ? t("Starting report…", "正在发起报告…")
        : requestKey
          ? t("Resume report request", "恢复报告请求")
          : t("Generate new analysis draft", "生成新的分析草稿")}
    </Button>
  )

  return (
    <section
      className="min-w-0 space-y-4 rounded-lg border p-4"
      aria-label={t("AI analysis reports", "AI 分析报告")}
    >
      <AiModelStatus />
      <header className="min-w-0 space-y-3">
        <h2
          ref={sectionHeading}
          id="analysis-reports-title"
          tabIndex={-1}
          className="scroll-mt-28 text-xl font-semibold"
        >
          {t("AI analysis reports", "AI 分析报告")}
        </h2>
        <p className="text-sm text-muted-foreground">
          {t(
            "Manually generated from authorized bounded materials. AI explanations and human confirmation do not change published statistics or Findings. Only allowlisted local synthetic data may reach the external test model; customer data stays within the private deployment model boundary.",
            "基于授权有界材料手动生成。AI 解释与人工确认不改变已发布统计或发现项；外部测试模型仅接收白名单内的本地合成数据，客户数据仅使用部署内模型。",
          )}
        </p>
        {current?.materials_changed ? (
          <Alert className="border-amber-500 bg-amber-500/10">
            <AlertTitle>
              {t(
                "New materials are NOT included in this version",
                "新材料尚未纳入当前版本",
              )}
            </AlertTitle>
            <AlertDescription className="space-y-2">
              <p>
                {t(
                  "This version retains its original material scope, even when newer drafts exist. Generate a new draft to include currently available materials.",
                  "即使已有新草稿，此版本仍保留原材料范围。请生成新草稿以纳入当前可用材料。",
                )}
              </p>
              {generateButton}
            </AlertDescription>
          </Alert>
        ) : (
          generateButton
        )}
        <Button
          type="button"
          variant="outline"
          disabled={list.isFetching || detail.isFetching || busy}
          onClick={() => void invalidate()}
        >
          {t("Refresh analysis reports", "刷新分析报告")}
        </Button>
      </header>
      {list.isPending && (
        <p role="status">
          {t("Loading analysis versions…", "正在加载分析版本…")}
        </p>
      )}
      {(list.isError || detail.isError) && (
        <Alert variant="destructive">
          <AlertTitle>
            {t("Analysis report could not be read", "无法读取分析报告")}
          </AlertTitle>
          <AlertDescription>
            {t(
              "Refresh to read again. The selected version has not been replaced and no completion is assumed.",
              "请刷新后重新读取。未替换所选版本，也不推定已完成。",
            )}
          </AlertDescription>
        </Alert>
      )}
      {list.isSuccess && !writable && (
        <p className="text-sm text-muted-foreground">
          {t(
            "Read-only access. An Operator can generate, edit and confirm reports.",
            "当前为只读权限，Operator 可生成、编辑与确认报告。",
          )}
        </p>
      )}
      {list.isSuccess && list.data.count === 0 && (
        <p>
          {t(
            "No analysis report versions for this Run. A report can be generated without investigation records; missing materials must remain explicit gaps.",
            "此运行暂无分析报告版本。没有核查记录也可生成报告；缺失材料必须明确列为缺口。",
          )}
        </p>
      )}
      {generate.isError && (
        <Alert variant="destructive">
          <AlertTitle>
            {t("Report generation was not confirmed", "尚未确认报告生成")}
          </AlertTitle>
          <AlertDescription>
            {t(
              "Previous versions remain unchanged. Refresh the list; resume an unknown request with the same key rather than creating a duplicate. Browser session storage is required before dispatch.",
              "旧版本保持不变。请刷新列表；未知请求使用原幂等键恢复，避免重复生成。发起前需要浏览器会话存储可用。",
            )}
          </AlertDescription>
        </Alert>
      )}
      {generate.isSuccess && (
        <p role="status">
          {t(
            "Request recorded. Select its new version from the list; the report you were reading has not been replaced.",
            "请求已记录。可从列表选择新版本；当前阅读的报告未被替换。",
          )}
        </p>
      )}
      {(records.length > 0 || selectedId) && (
        <div className="min-w-0 space-y-1">
          <label htmlFor={`${formId}-version`} className="text-sm font-medium">
            {t("Analysis version", "分析版本")}
          </label>
          <select
            id={`${formId}-version`}
            className="block w-full min-w-0 max-w-full rounded-md border bg-background p-2 text-sm"
            value={selectedId ?? ""}
            disabled={busy || !!editing}
            onChange={(event) => {
              setSelectedId(event.target.value)
              save.reset()
              confirm.reset()
            }}
          >
            {!selectedId && (
              <option value="">{t("Select a version", "选择版本")}</option>
            )}
            {selectedId && !records.some((item) => item.id === selectedId) && (
              <option value={selectedId}>
                {t("Selected version unavailable", "所选版本不可用")}
              </option>
            )}
            {records.map((item) => (
              <option key={item.id} value={item.id}>
                {formatDate(item.created_at)} ·{" "}
                {statusLabels[item.status] ?? t("Unknown status", "未知状态")} ·{" "}
                {t("Revision", "修订号")} {item.revision}
                {item.connection_version_id
                  ? ` · ${t("Connection", "连接版本")} ${item.connection_version_id.slice(0, 8)}`
                  : ` · ${t("Legacy connection", "历史连接")}`}
              </option>
            ))}
          </select>
          {selectedId && (
            <details className="text-xs">
              <summary className="cursor-pointer">
                {t("Selected version identifier", "所选版本标识")}
              </summary>
              <TechnicalValue value={selectedId} label={t("Version", "版本")} />
            </details>
          )}
        </div>
      )}
      {selectedId && list.isSuccess && detail.isPending && (
        <p role="status">
          {t("Loading selected report…", "正在加载所选报告…")}
        </p>
      )}
      {current && (
        <article className="min-w-0 space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">
              {statusLabels[current.status] ?? t("Unknown status", "未知状态")}
            </Badge>
            <span className="text-sm">
              {t("Revision", "修订号")} {current.revision}
            </span>
            <span className="text-sm text-muted-foreground">
              {current.connection_version_id
                ? t(
                    `Connection ${current.connection_version_id.slice(0, 8)}`,
                    `连接版本 ${current.connection_version_id.slice(0, 8)}`,
                  )
                : t("Legacy connection", "历史连接")}
            </span>
          </div>
          {current.status === "GENERATING" && (
            <p role="status">
              {t(
                "Generation is still pending. No analysis or confirmation is assumed; previous versions remain available.",
                "生成尚未完成，不推定已有分析或确认；旧版本仍可查阅。",
              )}
            </p>
          )}
          {current.status === "GENERATING" && current.failure_code && (
            <Alert>
              <AlertTitle>
                {t("Generation outcome is still unknown", "生成结果仍未知")}
              </AlertTitle>
              <AlertDescription className="break-all">
                {t(
                  "Refresh or resume the same reserved request. A new execution is not started implicitly.",
                  "请刷新或恢复同一预留请求，不会隐式发起新的执行。",
                )}
                <p>
                  {t("Status code", "状态代码")}: {current.failure_code}
                </p>
              </AlertDescription>
            </Alert>
          )}
          {current.status === "FAILED" && (
            <Alert variant="destructive">
              <AlertTitle>
                {t("This version failed to generate", "此版本生成失败")}
              </AlertTitle>
              <AlertDescription className="break-all">
                {t(
                  "No completed analysis is available for this attempt. Select an earlier version or generate a new draft.",
                  "此次尝试没有已完成的分析。可选择旧版本或生成新草稿。",
                )}
                {current.failure_code && (
                  <p>
                    {t("Failure code", "失败代码")}: {current.failure_code}
                  </p>
                )}
              </AlertDescription>
            </Alert>
          )}
          {current.text && (
            <section
              aria-label={t("Report narrative", "报告正文")}
              className="min-w-0 space-y-3 text-sm"
            >
              {renderText(current.text)}
            </section>
          )}
          <p className="text-sm">
            {t(
              "Absent NetFlow and empty NetFlow are different evidence gaps; neither means zero risk. Later queries and verification do not rewrite the base Run.",
              "NetFlow 缺失与空数据是不同的证据缺口，均不代表零风险。后来的查询与验证不改写基础运行。",
            )}
          </p>
          <dl className="grid min-w-0 gap-3 text-xs sm:grid-cols-2">
            {[
              [
                t("Material captured", "材料截取时间"),
                formatDate(current.material.captured_at, "UTC"),
              ],
              [t("Created", "创建时间"), formatDate(current.created_at, "UTC")],
              [
                t("AI completed", "AI 完成时间"),
                current.completed_at
                  ? formatDate(current.completed_at, "UTC")
                  : t("Not recorded", "未记录"),
              ],
              [
                t("Edited", "编辑时间"),
                current.edited_at
                  ? formatDate(current.edited_at, "UTC")
                  : t("Not recorded", "未记录"),
              ],
              [
                t("Confirmed", "确认时间"),
                current.confirmed_at
                  ? formatDate(current.confirmed_at, "UTC")
                  : t("Not confirmed", "未经确认"),
              ],
            ].map(([label, value]) => (
              <div key={label} className="min-w-0">
                <dt className="font-medium">{label}</dt>
                <dd className="select-text break-all">{value}</dd>
              </div>
            ))}
          </dl>
          {current.connection_version_id && (
            <details className="text-xs">
              <summary className="cursor-pointer">
                {t("Connection version identifier", "连接版本标识")}
              </summary>
              <TechnicalValue
                value={current.connection_version_id}
                label={t("Connection version", "连接版本")}
              />
            </details>
          )}
          <details className="min-w-0 text-xs">
            <summary className="cursor-pointer font-medium">
              {t("Report identifiers and authors", "报告标识与作者")}
            </summary>
            <dl className="mt-2 grid min-w-0 gap-3 sm:grid-cols-2">
              {[
                [t("Version", "版本"), current.id],
                [t("Project", "项目"), current.project_id],
                [t("Fixed base Run", "固定基础运行"), current.run_id],
                [
                  t("Deterministic report", "确定性报告"),
                  current.material.report_id,
                ],
                [
                  t("Report contract", "报告合同"),
                  current.material.report_contract_version,
                ],
                [t("Created by", "创建人"), current.created_by_id],
                [
                  t("Edited by", "编辑人"),
                  current.edited_by_id ?? t("Not edited", "未经编辑"),
                ],
                [
                  t("Confirmed by", "确认人"),
                  current.confirmed_by_id ?? t("Not confirmed", "未经确认"),
                ],
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
          {current.original_output && (
            <details className="min-w-0 rounded-md border p-3">
              <summary className="cursor-pointer font-medium">
                {t(
                  "Original AI draft · preserved unchanged",
                  "AI 原稿 · 保留不变",
                )}
              </summary>
              <div className="mt-3 min-w-0 space-y-3 text-sm">
                <p>
                  {t(
                    "This is the AI output at generation time, including its gap assessments. It is preserved for comparison and does not change when the narrative is edited or confirmed.",
                    "这里保留生成时的 AI 正文和缺口判断，供对照追溯；不会随正文编辑或确认而更新。",
                  )}
                </p>
                {renderText(current.original_output.text)}
                {current.original_output.gaps.length > 0 && (
                  <div className="space-y-2">
                    <h4 className="font-medium">
                      {t(
                        "AI-noted gaps in original draft",
                        "原稿中的 AI 缺口判断",
                      )}
                    </h4>
                    {current.original_output.gaps.map((gap, index) => (
                      <p
                        key={`ai-${index}`}
                        className="break-words [overflow-wrap:anywhere]"
                      >
                        {gap}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            </details>
          )}
          {(save.isError || confirm.isError) && (
            <Alert variant="destructive">
              <AlertTitle>
                {t("Report change was not confirmed", "尚未确认报告变更")}
              </AlertTitle>
              <AlertDescription>
                {(save.error instanceof ApiError &&
                  save.error.status === 409) ||
                (confirm.error instanceof ApiError &&
                  confirm.error.status === 409)
                  ? t(
                      "The version changed. Your input is retained; review the refreshed report before making another change.",
                      "版本已发生变化。已保留输入；请检查刷新后的报告再修改。",
                    )
                  : t(
                      "Your input is retained. Refresh to check the saved version before trying again.",
                      "已保留输入。请刷新确认已保存版本后再尝试。",
                    )}
              </AlertDescription>
            </Alert>
          )}
          {writable && current.status === "DRAFT" && !editing && (
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={!fresh || busy || !current.text}
                onClick={() => {
                  if (current.text)
                    setEditing({
                      id: current.id,
                      revision: current.revision,
                      text: { ...current.text },
                    })
                  save.reset()
                  confirm.reset()
                }}
              >
                {t("Edit narrative", "编辑正文")}
              </Button>
              <Button
                type="button"
                disabled={!fresh || busy || !current.text}
                onClick={() => confirm.mutate()}
              >
                {t("Confirm this version", "确认此版本")}
              </Button>
              <p className="w-full text-sm text-muted-foreground">
                {t(
                  "Confirmation is a separate persistent action and locks this version's narrative. It does not confirm that recommended actions were completed.",
                  "确认是独立的持久操作，并锁定此版本正文；不代表建议动作已经完成。",
                )}
              </p>
            </div>
          )}
          {writable && editing && (
            <form
              className="min-w-0 max-w-prose space-y-4 text-sm"
              onSubmit={(event) => {
                event.preventDefault()
                if (!staleEdit && fresh && !busy) save.mutate()
              }}
            >
              <h3 className="font-medium">
                {t("Edit narrative only", "仅编辑正文")}
              </h3>
              {staleEdit && (
                <p role="alert">
                  {t(
                    "This edit is based on an older revision. Copy any text you need, then cancel and reopen the current draft.",
                    "此编辑基于旧修订。请复制需保留的文字，取消后重新打开当前草稿。",
                  )}
                </p>
              )}
              {textFields.map(([field, en, zh]) => (
                <div key={field} className="min-w-0 space-y-1">
                  <label
                    htmlFor={`${formId}-${field}`}
                    className="block text-sm font-medium"
                  >
                    {t(en, zh)}
                  </label>
                  <textarea
                    id={`${formId}-${field}`}
                    className="block min-h-56 w-full min-w-0 resize-y rounded-md border bg-background p-3 text-sm leading-relaxed"
                    rows={10}
                    required
                    maxLength={8000}
                    disabled={busy}
                    value={editing.text[field]}
                    onChange={(event) =>
                      setEditing({
                        ...editing,
                        text: { ...editing.text, [field]: event.target.value },
                      })
                    }
                  />
                </div>
              ))}
              <div className="flex flex-wrap gap-2">
                <Button
                  type="submit"
                  disabled={
                    !fresh ||
                    busy ||
                    staleEdit ||
                    textFields.some(([field]) => !editing.text[field].trim())
                  }
                >
                  {t("Save narrative", "保存正文")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => {
                    setEditing(null)
                    save.reset()
                  }}
                >
                  {t("Cancel edit", "取消编辑")}
                </Button>
              </div>
            </form>
          )}
          <section
            aria-label={t("Fixed deterministic summary", "固定确定性摘要")}
            className="min-w-0 space-y-2 rounded-md border p-3 text-sm"
          >
            <h3 className="font-medium">
              {t(
                "Fixed deterministic summary · base Run",
                "固定确定性摘要 · 基础运行",
              )}
            </h3>
            <p>
              {t(
                "Complete server-produced statistics, not recounted by AI or editable with the narrative.",
                "完整服务端确定性统计，不由 AI 重新计数，也不能随正文编辑。",
              )}
            </p>
            {Object.keys(current.material.summary).length ? (
              <>
                <a className="inline-block underline" href="#report-ip-summary">
                  {t(
                    "Read published counts, sources and limitations",
                    "阅读已发布统计、来源与局限性",
                  )}
                </a>
                {current.material.summary.ip_source_comparison_summary !=
                  null && (
                  <dl className="grid min-w-0 grid-cols-2 gap-2">
                    {[
                      ["resource_count", "Compared resources", "比较资源总数"],
                      ["matched", "Matched", "双方均观测"],
                      [
                        "customer_upload_only",
                        "Customer upload only",
                        "仅台账观测",
                      ],
                      ["cloudatlas_only", "CloudAtlas only", "仅外部观测"],
                      [
                        "neither_source_observed",
                        "Neither source observed",
                        "双方均未观测",
                      ],
                      ["ACTIVE", "ACTIVE", "ACTIVE（有活动）"],
                      ["UNKNOWN", "UNKNOWN", "UNKNOWN（未知）"],
                    ].map(([key, en, zh]) => {
                      const group =
                        key === "resource_count"
                          ? []
                          : [
                              key === "ACTIVE" || key === "UNKNOWN"
                                ? "netflow_status_counts"
                                : "classification_counts",
                            ]
                      const value = [...group, key].reduce<unknown>(
                        (entry, field) =>
                          entry !== null && typeof entry === "object"
                            ? (entry as Record<string, unknown>)[field]
                            : undefined,
                        current.material.summary.ip_source_comparison_summary,
                      )
                      return (
                        <div key={key} className="min-w-0">
                          <dt>{t(en, zh)}</dt>
                          <dd className="font-medium tabular-nums">
                            {typeof value === "number" &&
                            Number.isInteger(value) &&
                            value >= 0
                              ? value
                              : t("Not recorded", "未记录")}
                          </dd>
                        </div>
                      )
                    })}
                  </dl>
                )}
                {current.material.summary.input_capabilities != null && (
                  <dl className="grid min-w-0 gap-2 sm:grid-cols-3">
                    {[
                      ["status", "NetFlow processing", "NetFlow 处理状态"],
                      ["input_state", "NetFlow input", "NetFlow 输入"],
                      ["coverage", "NetFlow coverage", "NetFlow 覆盖范围"],
                    ].map(([key, en, zh]) => {
                      const value = ["netflow", key].reduce<unknown>(
                        (entry, field) =>
                          entry !== null && typeof entry === "object"
                            ? (entry as Record<string, unknown>)[field]
                            : undefined,
                        current.material.summary.input_capabilities,
                      )
                      return (
                        <div key={key} className="min-w-0">
                          <dt>{t(en, zh)}</dt>
                          <dd>
                            {typeof value === "string"
                              ? translateValue(value)
                              : t("Not recorded", "未记录")}
                          </dd>
                        </div>
                      )
                    })}
                  </dl>
                )}
                <details className="min-w-0">
                  <summary className="cursor-pointer font-medium">
                    {t("View fixed source material", "查看固定来源材料")}
                  </summary>
                  <div className="mt-2">
                    <MaterialFields value={current.material.summary} />
                  </div>
                </details>
              </>
            ) : (
              <p>
                {t(
                  "No deterministic summary material was recorded. No statistics are inferred.",
                  "未记录确定性摘要材料，不推断任何统计。",
                )}
              </p>
            )}
          </section>
          <section
            aria-label={t("Frozen materials and citations", "固定材料与引用")}
            className="min-w-0 space-y-2 text-sm"
          >
            <h3 className="font-medium">
              {t("Frozen materials and citations", "固定材料与引用")}
            </h3>
            <p>
              {t(
                "Historical Runs, later queries, investigations and manual verification describe their own recorded times, not the base Run's statistics. Full identities and captured content remain fixed in this version.",
                "历史运行、后来查询、核查与人工验证分别描述其记录时刻，不代表基础运行统计。完整身份与截取内容在此版本中保持固定。",
              )}
            </p>
            {current.material.items.length === 0 && (
              <p>
                {t(
                  "No citation materials were captured. This is a material gap, not proof of no risk.",
                  "未截取任何引用材料。这是资料缺口，不代表没有风险。",
                )}
              </p>
            )}
            {current.original_output &&
              current.original_output.citation_ids.length === 0 && (
                <p>
                  {t(
                    "The AI original cites no materials.",
                    "AI 原稿未引用材料。",
                  )}
                </p>
              )}
            {current.material.items.map((item) => (
              <details
                key={item.citation_id}
                className="min-w-0 rounded-md border p-3"
              >
                <summary className="cursor-pointer break-words font-medium">
                  {current.original_output?.citation_ids.includes(
                    item.citation_id,
                  )
                    ? t("Cited source", "已引用来源")
                    : t("Available material", "可用材料")}{" "}
                  ·{" "}
                  {materialLabels[item.kind] ??
                    t("Recorded material", "已记录材料")}{" "}
                  ·{" "}
                  {item.recorded_at
                    ? formatDate(item.recorded_at, "UTC")
                    : t("Time not recorded", "时间未记录")}
                </summary>
                <dl className="my-2 min-w-0 space-y-1 text-xs">
                  <dt>{t("Citation", "引用")}</dt>
                  <dd>
                    <TechnicalValue
                      value={item.citation_id}
                      label={t("Citation", "引用")}
                    />
                  </dd>
                  <dt>{t("Material kind", "材料类型")}</dt>
                  <dd>{item.kind}</dd>
                  <dt>{t("Full record identity", "完整记录身份")}</dt>
                  <dd>
                    <TechnicalValue
                      value={item.identity}
                      label={t("Full record identity", "完整记录身份")}
                    />
                  </dd>
                  <dt>{t("Recorded time", "记录时间")}</dt>
                  <dd>
                    {item.recorded_at ? (
                      <time dateTime={item.recorded_at}>
                        {formatDate(item.recorded_at, "UTC")}
                      </time>
                    ) : (
                      t("Not recorded", "未记录")
                    )}
                  </dd>
                </dl>
                <MaterialFields value={item.data} />
              </details>
            ))}
            {current.material.truncated && (
              <p role="status">
                {t(
                  "Material limits were reached; not all available records are included.",
                  "已达到材料上限，未纳入全部可用记录。",
                )}
              </p>
            )}
            {current.material.gaps.length > 0 && (
              <div className="space-y-2 rounded-md border p-3">
                <h4 className="font-medium">
                  {t("Material gaps", "材料缺口")}
                </h4>
                {current.material.gaps.map((gap, index) => (
                  <p
                    key={`material-${index}`}
                    className="break-words [overflow-wrap:anywhere]"
                  >
                    {gap}
                  </p>
                ))}
              </div>
            )}
          </section>
        </article>
      )}
    </section>
  )
}
