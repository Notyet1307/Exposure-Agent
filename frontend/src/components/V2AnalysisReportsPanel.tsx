import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useMemo, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { AnalysisReportsService as API, ApiError } from "@/client"
import { ResultPagination } from "@/components/ResultPagination"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import { type V2Report, V2ReportContent } from "@/components/V2ReportContent"
import { comparisonUuid } from "@/lib/comparisonReturn"
import { useI18n } from "@/lib/i18n"
import { requestDigest } from "@/lib/ledgerIntent"

type Props = {
  actor: string
  projectId: string
  resultId: string
  bindingId: string | null | undefined
  addressKey?: string
}
type Body = Parameters<typeof API.createV2AnalysisReport>[0]["requestBody"]
type Pending = { key: string; digest: string; body: Body }
const accessLost = (error: unknown) => {
  if (!(error instanceof ApiError)) return false
  if ([401, 403, 404, 410].includes(error.status)) return true
  const detail = (error.body as { detail?: unknown }).detail
  const code =
    detail && typeof detail === "object" && "code" in detail
      ? String(detail.code)
      : ""
  return [
    "v2_report_material_unavailable",
    "v2_report_material_expired",
  ].includes(code)
}

export function V2AnalysisReportsPanel({
  actor,
  projectId,
  resultId,
  bindingId,
  addressKey,
}: Props) {
  const { t, language } = useI18n()
  const cache = useQueryClient()
  const alive = useRef(true)
  const scope = useRef("")
  const [includeFlow, setIncludeFlow] = useState(!!bindingId)
  const [audience, setAudience] = useState<"management" | "operations">(
    addressKey ? "operations" : "management",
  )
  const [reportLanguage, setReportLanguage] = useState<"zh" | "en">(
    language === "en" ? "en" : "zh",
  )
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState<string>()
  const [full, setFull] = useState(false)
  const [busy, setBusy] = useState(false)
  const submitting = useRef(false)
  const [error, setError] = useState("")
  const [expired, setExpired] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editRevision, setEditRevision] = useState(0)
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [caseEdits, setCaseEdits] = useState<
    Record<string, { why_review: string; next_check: string }>
  >({})
  const [printReport, setPrintReport] = useState<V2Report>()
  const supplement = includeFlow ? bindingId : null
  const body: Body = useMemo(
    () => ({
      subject_kind: "core_comparison_v2",
      result_id: resultId,
      supplement_binding_id: supplement ?? null,
      audience,
      language: reportLanguage,
      address_key: addressKey ?? null,
    }),
    [resultId, supplement, audience, reportLanguage, addressKey],
  )
  const prefix = useMemo(
    () => [
      "v2-ai-report",
      actor,
      projectId,
      resultId,
      supplement,
      audience,
      reportLanguage,
      addressKey,
    ],
    [
      actor,
      projectId,
      resultId,
      supplement,
      audience,
      reportLanguage,
      addressKey,
    ],
  )
  const scopeKey = JSON.stringify(prefix)
  const store = `exposure:v2-report:${JSON.stringify(prefix)}`
  const [pending, setPending] = useState<Pending | null>(null)
  const enabled = bindingId !== undefined && !expired
  const options = {
    retry: false,
    gcTime: 0,
    staleTime: 0,
    refetchOnWindowFocus: true,
  }
  const verify = (report: V2Report) => {
    if (
      !comparisonUuid.test(report.id) ||
      report.project_id !== projectId ||
      report.result_id !== resultId ||
      report.supplement_binding_id !== (supplement ?? null) ||
      report.address_key !== (addressKey ?? null) ||
      report.audience !== audience ||
      report.language !== reportLanguage ||
      report.subject_kind !== "core_comparison_v2"
    )
      throw new Error("report_identity_mismatch")
    return report
  }
  const ready = useQuery({
    ...options,
    queryKey: [...prefix, "readiness"],
    enabled,
    queryFn: async () => {
      const value = await API.readV2ReportReadiness({
        projectId,
        resultId,
        supplementBindingId: supplement,
        audience,
        language: reportLanguage,
        addressKey,
      })
      if (
        value.project_id !== projectId ||
        value.result_id !== resultId ||
        value.supplement_binding_id !== (supplement ?? null)
      )
        throw new Error("report_identity_mismatch")
      return value
    },
  })
  const versions = useQuery({
    ...options,
    queryKey: [...prefix, "versions", page],
    enabled,
    refetchInterval: (query) =>
      query.state.data?.data.some((record) => record.status === "GENERATING")
        ? 2000
        : false,
    queryFn: async () => {
      const data = await API.readV2AnalysisReports({
        projectId,
        resultId,
        supplementBindingId: supplement,
        audience,
        language: reportLanguage,
        addressKey,
        skip: page * 25,
        limit: 25,
      })
      data.data.forEach(verify)
      return data
    },
  })
  const detail = useQuery({
    ...options,
    queryKey: [...prefix, "detail", selected],
    enabled: enabled && !!selected,
    refetchInterval: (query) =>
      query.state.data?.status === "GENERATING" ? 2000 : 5000,
    queryFn: async () =>
      verify(
        await API.readV2AnalysisReport({
          projectId,
          analysisReportId: selected!,
        }),
      ),
  })
  const report =
    detail.isSuccess &&
    !detail.isError &&
    !versions.isError &&
    detail.data.readable &&
    !expired
      ? detail.data
      : undefined
  const history = useQuery({
    ...options,
    queryKey: [...prefix, "revisions", selected, report?.revision],
    enabled: !!report && full && report.status !== "GENERATING",
    queryFn: () =>
      API.readV2ReportRevisions({ projectId, analysisReportId: report!.id }),
  })
  useEffect(() => {
    alive.current = true
    scope.current = scopeKey
    setSelected(undefined)
    setPage(0)
    setFull(false)
    setEditing(false)
    setEdits({})
    setCaseEdits({})
    setError("")
    setExpired(false)
    setPrintReport(undefined)
    try {
      const value = JSON.parse(sessionStorage.getItem(store) ?? "null")
      setPending(
        value &&
          comparisonUuid.test(value.key) &&
          /^[a-f0-9]{64}$/.test(value.digest) &&
          JSON.stringify(value.body) === JSON.stringify(body)
          ? value
          : null,
      )
    } catch {
      setPending(null)
    }
    return () => {
      alive.current = false
      void cache.cancelQueries({ queryKey: prefix })
      cache.removeQueries({ queryKey: prefix })
      document.body.removeAttribute("data-v2-print")
    }
  }, [cache, prefix, store, body, scopeKey])
  useEffect(() => {
    if (
      !selected &&
      versions.isSuccess &&
      !versions.isError &&
      versions.data.data[0]
    )
      setSelected(versions.data.data[0].id)
  }, [selected, versions.isSuccess, versions.isError, versions.data])
  useEffect(() => {
    if (
      !detail.isError &&
      !versions.isError &&
      !history.isError &&
      (detail.data === undefined || detail.data.readable)
    )
      return
    setEditing(false)
    setEdits({})
    setCaseEdits({})
    setPrintReport(undefined)
    if (
      (detail.data && !detail.data.readable) ||
      accessLost(detail.error) ||
      accessLost(versions.error) ||
      accessLost(history.error)
    ) {
      setExpired(true)
      void cache.cancelQueries({ queryKey: prefix })
      cache.removeQueries({ queryKey: prefix })
    }
  }, [
    detail.isError,
    detail.data,
    detail.error,
    versions.isError,
    versions.error,
    history.isError,
    history.error,
    cache,
    prefix,
  ])
  useEffect(() => {
    if (!detail.data?.valid_until) return
    let timer: ReturnType<typeof setTimeout>
    const check = () => {
      const remaining = Date.parse(detail.data!.valid_until!) - Date.now()
      if (remaining <= 0) {
        setExpired(true)
        setEditing(false)
        setEdits({})
        setCaseEdits({})
        setPrintReport(undefined)
        void cache.cancelQueries({ queryKey: prefix })
        cache.removeQueries({ queryKey: prefix })
      } else timer = setTimeout(check, Math.min(remaining, 2147483647))
    }
    check()
    return () => clearTimeout(timer)
  }, [detail.data?.valid_until, cache, prefix])
  const clearIntent = () => {
    setPending(null)
    sessionStorage.removeItem(store)
  }
  const accept = (value: V2Report) => {
    verify(value)
    if (!alive.current || scope.current !== scopeKey) return
    clearIntent()
    setSelected(value.id)
    cache.setQueryData([...prefix, "detail", value.id], value)
    void cache.invalidateQueries({ queryKey: [...prefix, "versions"] })
  }
  const generate = async (original?: Pending) => {
    if (submitting.current || (pending && !original)) return
    submitting.current = true
    setBusy(true)
    setError("")
    let intent = original
    try {
      if (!intent)
        intent = {
          key: crypto.randomUUID(),
          digest: await requestDigest(body),
          body,
        }
      if (!alive.current) return
      if (
        intent.digest !== (await requestDigest(body)) ||
        JSON.stringify(intent.body) !== JSON.stringify(body)
      )
        throw new Error("report_intent_mismatch")
      setPending(intent)
      sessionStorage.setItem(store, JSON.stringify(intent))
      accept(
        await API.createV2AnalysisReport({
          projectId,
          idempotencyKey: intent.key,
          requestBody: intent.body,
        }),
      )
    } catch (reason) {
      if (!alive.current) return
      if (
        reason instanceof ApiError &&
        reason.status >= 400 &&
        reason.status < 500
      )
        clearIntent()
      setError(
        t(
          "Generation was not confirmed. Read the original receipt before starting another request.",
          "生成结果尚未确认。请先读取原回执，再开始新请求。",
        ),
      )
    } finally {
      submitting.current = false
      if (alive.current) setBusy(false)
    }
  }
  const recover = async () => {
    if (!pending || submitting.current) return
    submitting.current = true
    setBusy(true)
    setError("")
    try {
      accept(await API.readV2ReportOperation({ projectId, key: pending.key }))
    } catch (reason) {
      if (alive.current)
        setError(
          reason instanceof ApiError && reason.status === 404
            ? t(
                "The original request was not found. You can explicitly resend the same request.",
                "未找到原请求，可显式重发同一请求。",
              )
            : t(
                "The original receipt could not be read. Keep the same request identity.",
                "原回执暂不可读，请保留同一请求身份。",
              ),
        )
    } finally {
      submitting.current = false
      if (alive.current) setBusy(false)
    }
  }
  const startEdit = () => {
    if (!report?.text) return
    setEditRevision(report.revision)
    setEdits(
      Object.fromEntries(
        report.text.claims
          .filter((claim) => claim.type !== "fact")
          .map((claim) => [claim.id, "text" in claim ? claim.text : ""]),
      ),
    )
    setCaseEdits(
      Object.fromEntries(
        report.text.priority_cases.map((value) => [
          value.address_key,
          { why_review: value.why_review, next_check: value.next_check },
        ]),
      ),
    )
    setEditing(true)
    setFull(true)
  }
  const write = async (confirm = false) => {
    if (!report || submitting.current) return
    submitting.current = true
    setBusy(true)
    setError("")
    try {
      const value = confirm
        ? await API.confirmV2AnalysisReport({
            projectId,
            analysisReportId: report.id,
            requestBody: { expected_revision: report.revision },
          })
        : await API.updateV2AnalysisReport({
            projectId,
            analysisReportId: report.id,
            requestBody: {
              expected_revision: editRevision,
              edits,
              case_edits: caseEdits,
            },
          })
      verify(value)
      if (!alive.current) return
      setEditing(false)
      setEdits({})
      setCaseEdits({})
      cache.setQueryData([...prefix, "detail", value.id], value)
      void cache.invalidateQueries({ queryKey: [...prefix, "versions"] })
    } catch (reason) {
      if (!alive.current) return
      if (accessLost(reason)) {
        setEditing(false)
        setEdits({})
        setCaseEdits({})
        setPrintReport(undefined)
        setExpired(true)
        void cache.cancelQueries({ queryKey: prefix })
        cache.removeQueries({ queryKey: prefix })
      }
      setError(
        t(
          "This version could not be saved or confirmed. Re-read it to check permissions, material access or a revision conflict.",
          "无法保存或确认此版本。请重读，核对权限、材料可读性或修订冲突。",
        ),
      )
    } finally {
      submitting.current = false
      if (alive.current) setBusy(false)
    }
  }
  const print = async () => {
    if (!report || submitting.current) return
    submitting.current = true
    setBusy(true)
    setError("")
    try {
      const value = verify(
        await API.readV2AnalysisReport({
          projectId,
          analysisReportId: report.id,
        }),
      )
      if (!alive.current) return
      cache.setQueryData([...prefix, "detail", value.id], value)
      if (!value.readable || !value.material)
        throw new Error("report_unreadable")
      setPrintReport(value)
      await new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      )
      if (
        !alive.current ||
        (value.valid_until && Date.parse(value.valid_until) <= Date.now())
      )
        throw new Error("report_expired")
      document.body.dataset.v2Print = value.id
      window.print()
    } catch {
      if (alive.current) {
        setPrintReport(undefined)
        setExpired(true)
        setEditing(false)
        setEdits({})
        setCaseEdits({})
        void cache.cancelQueries({ queryKey: prefix })
        cache.removeQueries({ queryKey: prefix })
        setError(
          t(
            "The report could not be reauthorized for printing. Re-read the fixed version.",
            "无法重新验证报告的打印权限，请重读固定版本。",
          ),
        )
      }
    } finally {
      document.body.removeAttribute("data-v2-print")
      submitting.current = false
      if (alive.current) {
        setBusy(false)
        setPrintReport(undefined)
      }
    }
  }
  const statusLabels: Record<string, [string, string]> = {
    GENERATING: ["Generating", "生成中"],
    DRAFT: ["Draft; review required", "草稿，待人工复核"],
    CONFIRMED: ["Confirmed report version", "已确认报告版本"],
    FAILED: ["AI generation failed", "AI 生成失败"],
  }
  const readinessLabels: Record<string, [string, string]> = {
    NO_PERMISSION: [
      "An Operator can generate or edit reports; this account is read-only.",
      "Operator 可生成或编辑报告；当前账户只读。",
    ],
    NOT_CONFIGURED: [
      "No model connection is configured.",
      "尚未配置模型连接。",
    ],
    NOT_ENABLED: ["The model connection is not enabled.", "模型连接尚未启用。"],
    NOT_QUALIFIED: [
      "The model connection has not passed the required qualification.",
      "模型连接尚未通过所需资格验证。",
    ],
    MATERIAL_UNAVAILABLE: [
      "The selected fixed materials are unavailable. Choose a readable scope.",
      "所选固定材料不可用，请选择可读范围。",
    ],
    MODEL_UNAVAILABLE: [
      "The model connection is unavailable.",
      "模型连接暂不可用。",
    ],
    READY: [
      "Generate only when you choose to; browsing and refreshing are read-only.",
      "只有明确生成才会调用模型；浏览和刷新只读。",
    ],
  }
  const dirty =
    report?.text &&
    (JSON.stringify(edits) !==
      JSON.stringify(
        Object.fromEntries(
          report.text.claims
            .filter((claim) => claim.type !== "fact")
            .map((claim) => [claim.id, "text" in claim ? claim.text : ""]),
        ),
      ) ||
      JSON.stringify(caseEdits) !==
        JSON.stringify(
          Object.fromEntries(
            report.text.priority_cases.map((value) => [
              value.address_key,
              { why_review: value.why_review, next_check: value.next_check },
            ]),
          ),
        ))
  const heading = addressKey
    ? t("Explain this difference", "解释此差异")
    : t("AI interpretation for this comparison", "本轮 AI 解读")
  const printId = printReport ? `v2-print-${printReport.id}` : ""
  return (
    <section aria-label={heading} className="min-w-0 space-y-5 border-t pt-5">
      <h2 className="text-xl font-semibold">{heading}</h2>
      <div className="flex flex-wrap items-end gap-4">
        {!addressKey && (
          <Label>
            {t("Audience", "阅读对象")}
            <select
              className="block rounded border bg-background p-2"
              value={audience}
              disabled={busy || editing || !!pending}
              onChange={(event) =>
                setAudience(
                  event.target.value === "operations"
                    ? "operations"
                    : "management",
                )
              }
            >
              <option value="management">{t("Management", "管理阅读")}</option>
              <option value="operations">{t("Operations", "运营阅读")}</option>
            </select>
          </Label>
        )}
        <Label>
          {t("Report language", "报告语言")}
          <select
            className="block rounded border bg-background p-2"
            value={reportLanguage}
            disabled={busy || editing || !!pending}
            onChange={(event) =>
              setReportLanguage(event.target.value === "en" ? "en" : "zh")
            }
          >
            <option value="zh">中文</option>
            <option value="en">English</option>
          </select>
        </Label>
        {bindingId && (
          <Label className="flex items-center gap-2">
            <Checkbox
              checked={includeFlow}
              disabled={busy || editing || !!pending}
              onCheckedChange={(value) => setIncludeFlow(value === true)}
            />
            {t("Use this fixed NetFlow supplement", "使用此固定 NetFlow 辅证")}
          </Label>
        )}
        <Button
          disabled={
            !ready.data?.can_create ||
            ready.isError ||
            busy ||
            editing ||
            !!pending ||
            report?.status === "GENERATING" ||
            !enabled
          }
          onClick={() => void generate()}
        >
          {addressKey
            ? t("Generate this explanation", "生成此解释")
            : t("Generate AI interpretation report", "生成 AI 解读报告")}
        </Button>
      </div>
      <p
        role={ready.isError ? "alert" : "status"}
        className="max-w-prose text-sm text-muted-foreground"
      >
        {bindingId === undefined
          ? t(
              "Reading the fixed supplement selection…",
              "正在读取固定辅证选择…",
            )
          : ready.isError
            ? t(
                "Generation readiness could not be read; this does not affect the core result.",
                "无法读取生成就绪状态；核心结果不受影响。",
              )
            : ready.data
              ? t(...readinessLabels[ready.data.state])
              : t("Reading generation readiness…", "正在读取生成就绪状态…")}
      </p>
      {pending && (
        <div className="space-y-3 rounded border p-3">
          <p>
            {t(
              "An original operation needs to be checked.",
              "有一个原操作需要核对。",
            )}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={busy}
              variant="outline"
              onClick={() => void recover()}
            >
              {t("Read original report receipt", "读取原报告回执")}
            </Button>
            <Button
              disabled={busy}
              variant="outline"
              onClick={() => void generate(pending)}
            >
              {t("Resend the same report request", "重发同一报告请求")}
            </Button>
          </div>
        </div>
      )}
      {error && <p role="alert">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => {
            setExpired(false)
            void ready.refetch()
            void versions.refetch()
            if (selected) void detail.refetch()
          }}
        >
          {t("Re-read report state", "重读报告状态")}
        </Button>
        {report && (
          <Button size="sm" variant="outline" onClick={() => setFull(!full)}>
            {full
              ? t("Show summary", "查看摘要")
              : t("View full report", "查看完整报告")}
          </Button>
        )}
      </div>
      {versions.isError ? (
        <p role="alert">
          {t("Report versions could not be read.", "无法读取报告版本。")}
        </p>
      ) : versions.isPending ? (
        <p role="status">
          {t("Reading report versions…", "正在读取报告版本…")}
        </p>
      ) : versions.data.count === 0 ? (
        <p>
          {t(
            "No report for this fixed scope yet. Facts and evidence remain available below.",
            "此固定范围尚无报告；下方事实与依据仍可阅读。",
          )}
        </p>
      ) : (
        <>
          <Label className="block min-w-0 space-y-2">
            {t("Saved report version", "已保存报告版本")}
            <select
              className="block max-w-full rounded border bg-background p-2"
              value={selected ?? ""}
              disabled={editing || busy}
              onChange={(event) => {
                setSelected(event.target.value)
                setError("")
                setFull(false)
              }}
            >
              {versions.data.data.map((value) => (
                <option key={value.id} value={value.id}>
                  {value.created_at} · {t(...statusLabels[value.status])} ·{" "}
                  {value.revision}
                </option>
              ))}
            </select>
          </Label>
          <ResultPagination
            label={t("Report versions", "报告版本")}
            count={versions.data.count}
            page={page}
            pageSize={25}
            onPageChange={(next) => {
              setSelected(undefined)
              setPage(next)
            }}
          />
        </>
      )}
      {(expired ||
        detail.isError ||
        (detail.data && !detail.data.readable)) && (
        <p role="alert">
          {t(
            "This report is unreadable under its fixed material permissions or cutoff. Its summary, original, revisions and printing are unavailable. The C+A core remains readable.",
            "此报告的固定材料权限或期限不再允许读取；摘要、原稿、修订和打印均不可用。客户与云图核心仍可阅读。",
          )}
        </p>
      )}
      {report && (
        <div className="space-y-5">
          <p role="status" className="font-medium">
            {t(...statusLabels[report.status])}
          </p>
          {report.status === "GENERATING" ? (
            <p>
              {t(
                "The reserved task is being observed. Refreshing does not create another task.",
                "正在读取已预约任务的状态；刷新不会创建另一个任务。",
              )}
            </p>
          ) : (
            <>
              {report.materials_changed === true && (
                <p>
                  {t(
                    "Current inputs have updates. This report still uses its original fixed result.",
                    "当前输入有更新；此报告仍使用原固定结果。",
                  )}
                </p>
              )}
              {report.materials_changed === null && (
                <p>
                  {t(
                    "Current-input updates could not be confirmed.",
                    "暂无法确认当前输入是否有更新。",
                  )}
                </p>
              )}
              <V2ReportContent report={report} compact={!full} />
              {full && (
                <div className="space-y-3">
                  <div className="flex flex-wrap gap-2">
                    {report.status === "DRAFT" &&
                      versions.data?.can_create &&
                      !editing && (
                        <>
                          <Button
                            variant="outline"
                            disabled={busy}
                            onClick={startEdit}
                          >
                            {t("Edit interpretation", "编辑解读")}
                          </Button>
                          <Button
                            disabled={busy}
                            onClick={() => void write(true)}
                          >
                            {t("Confirm this report version", "确认此报告版本")}
                          </Button>
                        </>
                      )}
                    <Button
                      variant="outline"
                      disabled={busy || editing || !report.material}
                      onClick={() => void print()}
                    >
                      {t("Print report", "打印报告")}
                    </Button>
                  </div>
                  <p className="max-w-prose text-sm text-muted-foreground">
                    {t(
                      "Confirmation approves this report version; it does not prove ownership, a vulnerability or completed remediation. Printed files cannot be remotely recalled; keep them within the permitted use and retention period.",
                      "确认仅针对此报告版本，不证明资产归属、漏洞或已完成处置。已打印文件无法远程收回，请遵守材料用途与留存期限。",
                    )}
                  </p>
                  {editing && (
                    <form
                      className="space-y-4"
                      onSubmit={(event) => {
                        event.preventDefault()
                        void write()
                      }}
                    >
                      <p>
                        {t(
                          "Only interpretation and suggested checks are editable; facts and references remain fixed.",
                          "仅可编辑解释与建议核实；事实和引用保持固定。",
                        )}
                      </p>
                      {editRevision !== report.revision && (
                        <p role="alert">
                          {t(
                            "This report has another revision. Your text is retained; saving against the old revision will be rejected.",
                            "报告已有另一份修订。你的文字仍保留，但不能覆盖新修订。",
                          )}
                        </p>
                      )}
                      {Object.entries(edits).map(([id, value]) => (
                        <Label key={id} className="block space-y-2">
                          {t("Interpretation", "解读正文")} · {id}
                          <textarea
                            aria-label={`${t("Interpretation", "解读正文")} · ${id}`}
                            id={`${report.id}-claim-${id}`}
                            className="block min-h-24 w-full rounded border bg-background p-3"
                            value={value}
                            maxLength={2000}
                            disabled={busy}
                            onChange={(event) =>
                              setEdits({ ...edits, [id]: event.target.value })
                            }
                          />
                        </Label>
                      ))}
                      {Object.entries(caseEdits).map(([key, value]) => (
                        <div key={key} className="space-y-3">
                          {(["why_review", "next_check"] as const).map(
                            (field) => (
                              <Label key={field} className="block space-y-2">
                                {field === "why_review"
                                  ? t(
                                      "Why verify this object",
                                      "为何核实此对象",
                                    )
                                  : t("What to verify next", "下一步核实什么")}
                                <textarea
                                  className="block min-h-20 w-full rounded border bg-background p-3"
                                  value={value[field]}
                                  maxLength={2000}
                                  disabled={busy}
                                  onChange={(event) =>
                                    setCaseEdits({
                                      ...caseEdits,
                                      [key]: {
                                        ...value,
                                        [field]: event.target.value,
                                      },
                                    })
                                  }
                                />
                              </Label>
                            ),
                          )}
                        </div>
                      ))}
                      <div className="flex gap-2">
                        <Button type="submit" disabled={busy || !dirty}>
                          {t("Save report revision", "保存报告修订")}
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          disabled={busy}
                          onClick={() => {
                            setEditing(false)
                            setEdits({})
                            setCaseEdits({})
                          }}
                        >
                          {t("Cancel edits", "取消编辑")}
                        </Button>
                      </div>
                    </form>
                  )}
                  {report.original_output && (
                    <details className="space-y-3">
                      <summary className="cursor-pointer">
                        {t("Original AI draft", "AI 原稿")}
                      </summary>
                      <V2ReportContent
                        report={{
                          ...report,
                          text: report.original_output.text,
                        }}
                      />
                    </details>
                  )}
                  <details className="space-y-3">
                    <summary className="cursor-pointer">
                      {t("Human revision history", "人工修订历史")}
                    </summary>
                    {history.isError ? (
                      <p role="alert">
                        {t(
                          "Revision history cannot be read.",
                          "修订历史不可读。",
                        )}
                      </p>
                    ) : (
                      history.data?.map((value, index) => (
                        <pre
                          key={index}
                          className="max-h-60 overflow-auto whitespace-pre-wrap break-all text-xs"
                        >
                          {JSON.stringify(value, null, 2)}
                        </pre>
                      ))
                    )}
                  </details>
                </div>
              )}
            </>
          )}
        </div>
      )}
      {printReport &&
        createPortal(
          <article id={printId} className="hidden print:block">
            <h1 className="mb-5 text-2xl font-bold">{heading}</h1>
            <p className="mb-4">{t(...statusLabels[printReport.status])}</p>
            <V2ReportContent report={printReport} print />
          </article>,
          document.body,
        )}
      {printReport && (
        <style>{`@media print {
          body[data-v2-print="${printReport.id}"] {background:#fff!important;color:#000!important}
          body[data-v2-print="${printReport.id}"] > :not(#${printId}) {display:none!important}
          body[data-v2-print="${printReport.id}"] #${printId},
          body[data-v2-print="${printReport.id}"] #${printId} * {visibility:visible;color:#000!important;background:transparent!important;box-shadow:none!important}
          body[data-v2-print="${printReport.id}"] #${printId} {display:block;position:static;width:100%;padding:16px}
          #${printId} details {display:none}
          #${printId} section {break-inside:avoid}
          #${printId} a {text-decoration:none}
        }`}</style>
      )}
    </section>
  )
}
