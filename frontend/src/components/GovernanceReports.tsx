import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"

import {
  type AiGovernanceDraftPublic,
  ApiError,
  type GovernanceReportDetailPublic,
  GovernanceReportsService,
} from "@/client"
import { AnalysisReportsPanel } from "@/components/AnalysisReportsPanel"
import { TechnicalValue } from "@/components/TechnicalValue"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

import { useI18n } from "@/lib/i18n"

const HTML_EVIDENCE_LIMIT = 8
const MAX_DRAFT_FINDINGS = 8

function draftIdempotencyStorageKey(projectId: string, reportId: string) {
  return `exposure:ai-governance-draft:${projectId}:${reportId}:idempotency-key`
}

type DraftRequestRecovery = {
  idempotencyKey: string
  findingIds: string[]
}

function readDraftRequestRecovery(
  storageKey: string,
): DraftRequestRecovery | null {
  try {
    const serialized = window.sessionStorage.getItem(storageKey)
    if (serialized === null) return null
    const value: unknown = JSON.parse(serialized)
    if (value === null || typeof value !== "object" || Array.isArray(value)) {
      return null
    }
    const { idempotencyKey, findingIds } = value as {
      idempotencyKey?: unknown
      findingIds?: unknown
    }
    if (
      typeof idempotencyKey !== "string" ||
      !Array.isArray(findingIds) ||
      findingIds.length === 0 ||
      findingIds.length > MAX_DRAFT_FINDINGS ||
      findingIds.some((findingId) => typeof findingId !== "string")
    ) {
      return null
    }
    return { idempotencyKey, findingIds }
  } catch {
    return null
  }
}

function storeDraftRequestRecovery(
  storageKey: string,
  value: DraftRequestRecovery,
) {
  try {
    window.sessionStorage.setItem(storageKey, JSON.stringify(value))
  } catch {
    // The API remains usable when browser storage is unavailable; only
    // remount recovery is disabled for that tab.
  }
}

function clearDraftIdempotencyKey(storageKey: string) {
  try {
    window.sessionStorage.removeItem(storageKey)
  } catch {
    // Nothing durable was available to clear.
  }
}

function isActiveDraftGenerationConflict(error: unknown): boolean {
  if (!(error instanceof ApiError) || error.status !== 409) return false
  const body = asObject(error.body)
  const detail = body ? asObject(body.detail) : null
  return detail?.code === "draft_generation_active"
}

type JsonObject = Record<string, unknown>

function asObject(value: unknown): JsonObject | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonObject)
    : null
}

export function getVerifiedReportContent(
  detail: GovernanceReportDetailPublic,
  projectId: string,
  reportId: string,
  expectedRunId?: string,
  expectedReportContractVersion?: string,
): JsonObject | null {
  const root = asObject(detail.canonical_content)
  const report = root ? objectField(root, "report") : null
  const identity = report ? objectField(report, "report_identity") : null
  if (
    detail.id !== reportId ||
    !identity ||
    identity.project_id !== projectId ||
    identity.governance_run_id !== detail.governance_run_id ||
    identity.report_contract_version !== detail.report_contract_version ||
    root?.schema_version !== detail.report_contract_version ||
    (expectedRunId !== undefined &&
      detail.governance_run_id !== expectedRunId) ||
    (expectedReportContractVersion !== undefined &&
      detail.report_contract_version !== expectedReportContractVersion)
  ) {
    return null
  }
  return report
}

function objectField(value: JsonObject, key: string): JsonObject | null {
  return asObject(value[key])
}

function objectArray(value: JsonObject, key: string): JsonObject[] {
  const items = value[key]
  return Array.isArray(items)
    ? items.flatMap((item) => {
        const object = asObject(item)
        return object ? [object] : []
      })
    : []
}

function stringField(value: JsonObject, key: string, fallback = "—") {
  const field = value[key]
  return typeof field === "string" && field.length > 0 ? field : fallback
}

function numberField(value: JsonObject, key: string) {
  const field = value[key]
  return typeof field === "number" && Number.isFinite(field) ? field : 0
}

function CountList({
  items,
  typeKey,
}: {
  items: JsonObject[]
  typeKey: "finding_type" | "transition_type"
}) {
  const { t, translateValue } = useI18n()
  if (items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {t("No counts published.", "未发布计数。")}
      </p>
    )
  }
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm">
      {items.map((item, index) => (
        <li key={`${stringField(item, typeKey)}-${index}`}>
          <span className="font-mono">
            {translateValue(stringField(item, typeKey))}
          </span>
          : {numberField(item, "count")}
        </li>
      ))}
    </ul>
  )
}

function ReportSection({
  id,
  title,
  children,
}: {
  id: string
  title: string
  children: React.ReactNode
}) {
  return (
    <section
      id={id}
      className="min-w-0 scroll-mt-6 space-y-3 rounded-lg border p-4 [overflow-wrap:anywhere]"
    >
      <h2 className="text-lg font-semibold">{title}</h2>
      {children}
    </section>
  )
}

function InputCompleteness({ section }: { section: JsonObject }) {
  const { t, translateValue } = useI18n()
  const sources = objectArray(section, "sources")
  return (
    <div className="space-y-3">
      <p className="text-sm">
        {section.complete === true
          ? t(
              "All bounded input summaries are marked complete.",
              "所有有界输入摘要均标记为完整。",
            )
          : t(
              "The published report does not mark all inputs complete.",
              "已发布报告未将所有输入标记为完整。",
            )}
      </p>
      <ul className="grid min-w-0 gap-3 sm:grid-cols-2">
        {sources.map((source, index) => (
          <li
            className="min-w-0 space-y-2 rounded-md border p-3 text-sm"
            key={`${stringField(source, "source_type")}-${index}`}
          >
            <p className="font-medium">
              {translateValue(stringField(source, "source_type"))}
            </p>
            <p>
              {t("Records", "记录数")}: {numberField(source, "record_count")}
            </p>
            <details className="min-w-0">
              <summary className="cursor-pointer">
                {t("View evidence", "查看依据")}
              </summary>
              <dl className="mt-2 grid min-w-0 gap-2">
                <div className="min-w-0">
                  <dt>{t("Snapshot reference", "快照引用")}</dt>
                  <dd>
                    <TechnicalValue
                      value={stringField(source, "source_snapshot_id", "")}
                    />
                  </dd>
                </div>
                <div className="min-w-0">
                  <dt>{t("Content SHA-256", "内容 SHA-256")}</dt>
                  <dd>
                    <TechnicalValue
                      value={stringField(source, "content_sha256", "")}
                    />
                  </dd>
                </div>
                <div>
                  <dt>{t("Schema", "结构版本")}</dt>
                  <dd className="break-all">
                    {stringField(source, "schema_version")}
                  </dd>
                </div>
              </dl>
            </details>
          </li>
        ))}
      </ul>
    </div>
  )
}

function EvidenceCards({
  evidencePlan,
  evidenceCount,
}: {
  evidencePlan: JsonObject
  evidenceCount: number
}) {
  const { t, translateValue } = useI18n()
  const allEntries = objectArray(evidencePlan, "entries")
  const entries = allEntries.slice(0, HTML_EVIDENCE_LIMIT)
  if (entries.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {t(
          "No Evidence examples were selected for this report.",
          "此报告未选择证据示例。",
        )}
      </p>
    )
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        {t(
          `Showing ${entries.length} of ${evidenceCount} bounded Evidence reference${evidenceCount === 1 ? "" : "s"}. The HTML view never renders more than ${HTML_EVIDENCE_LIMIT} cards.`,
          `显示 ${evidenceCount} 个有界证据引用中的 ${entries.length} 个。HTML 视图最多展示 ${HTML_EVIDENCE_LIMIT} 张卡片。`,
        )}
      </p>
      <div className="grid min-w-0 gap-3 lg:grid-cols-2">
        {entries.map((entry, index) => {
          const reference = objectField(entry, "evidence_reference") ?? {}
          return (
            <article
              id={`report-evidence-${index + 1}`}
              data-testid="evidence-card"
              className="min-w-0 space-y-2 rounded-md border p-3 text-sm"
              key={`${stringField(entry, "finding_id")}-${index}`}
            >
              <h3 className="break-all font-semibold">
                {stringField(entry, "canonical_ip")} ·{" "}
                {translateValue(stringField(entry, "finding_type"))}
              </h3>
              <dl className="grid gap-1">
                <div>
                  <dt className="inline font-medium">
                    {t("Coverage: ", "覆盖范围：")}
                  </dt>
                  <dd className="inline">
                    {translateValue(stringField(entry, "coverage"))}
                  </dd>
                </div>
                <div>
                  <dt className="inline font-medium">
                    {t("Transition: ", "状态变更：")}
                  </dt>
                  <dd className="inline">
                    {translateValue(
                      stringField(
                        entry,
                        "transition_type",
                        t("None in this Run", "此运行中无变更"),
                      ),
                    )}
                  </dd>
                </div>
              </dl>
              <details className="min-w-0">
                <summary className="cursor-pointer">
                  {t("View evidence", "查看依据")} · {index + 1}
                </summary>
                <dl className="mt-2 grid min-w-0 gap-2">
                  <div>
                    <dt className="font-medium">{t("Finding", "发现项")}</dt>
                    <dd>
                      <TechnicalValue
                        value={stringField(entry, "finding_id", "")}
                      />
                    </dd>
                  </div>
                  <div>
                    <dt className="font-medium">
                      {t("Governance Run", "治理运行")}
                    </dt>
                    <dd>
                      <TechnicalValue
                        value={stringField(reference, "governance_run_id", "")}
                      />
                    </dd>
                  </div>
                  <div>
                    <dt className="font-medium">
                      {t("Source fact", "来源事实")}
                    </dt>
                    <dd>
                      {translateValue(stringField(reference, "fact_type"))} /{" "}
                      <TechnicalValue
                        value={stringField(reference, "fact_id", "")}
                      />
                    </dd>
                  </div>
                </dl>
              </details>
              <p className="flex flex-wrap gap-3 text-sm">
                <a className="underline" href="#report-source-references">
                  {t("Evidence provenance", "证据来源追溯")}
                </a>
                <a className="underline" href="#report-open-backlog">
                  {t("Finding context", "发现项上下文")}
                </a>
              </p>
            </article>
          )
        })}
      </div>
    </div>
  )
}

type EligibleDraftFinding = {
  id: string
  canonicalIp: string
}

function eligibleDraftFindings(
  detail: GovernanceReportDetailPublic,
): EligibleDraftFinding[] {
  const root = asObject(detail.canonical_content)
  const evidencePlan = root ? objectField(root, "evidence_plan") : null
  if (!evidencePlan) return []
  const persistedEvidence = new Set(
    (detail.evidence ?? []).map(
      (evidence) => `${evidence.fact_type}:${evidence.fact_id}`,
    ),
  )
  return objectArray(evidencePlan, "entries").flatMap((entry) => {
    const reference = objectField(entry, "evidence_reference")
    const id = stringField(entry, "finding_id", "")
    const factType = reference ? stringField(reference, "fact_type", "") : ""
    const factId = reference ? stringField(reference, "fact_id", "") : ""
    if (
      entry.finding_type !== "UNOBSERVED_ASSET" ||
      !id ||
      !persistedEvidence.has(`${factType}:${factId}`)
    ) {
      return []
    }
    return [{ id, canonicalIp: stringField(entry, "canonical_ip") }]
  })
}

function DraftGeneration({
  detail,
  projectId,
}: {
  detail: GovernanceReportDetailPublic
  projectId: string
}) {
  const { t, translateValue } = useI18n()
  const queryClient = useQueryClient()
  const [selectedFindingIds, setSelectedFindingIds] = useState<Set<string>>(
    new Set(),
  )
  const storageKey = draftIdempotencyStorageKey(projectId, detail.id)
  const [pendingRequest, setPendingRequest] =
    useState<DraftRequestRecovery | null>(() =>
      readDraftRequestRecovery(storageKey),
    )
  const eligibleFindings = eligibleDraftFindings(detail)
  const supportsAiDraft =
    detail.report_contract_version === "deterministic-report-v1"
  const clearPendingRequest = () => {
    clearDraftIdempotencyKey(storageKey)
    setPendingRequest(null)
  }
  const generationMutation = useMutation({
    mutationFn: ({ findingIds, key }: { findingIds: string[]; key: string }) =>
      GovernanceReportsService.requestAiGovernanceDraft({
        projectId,
        reportId: detail.id,
        requestBody: { finding_ids: findingIds },
        idempotencyKey: key,
      }),
    onSuccess: (draft) => {
      // A response to this exact request key proves that the recovered key is
      // bound to the returned draft. A bound Session needs no further replay.
      if (draft.session_id !== null) clearPendingRequest()
    },
    onSettled: async (_data, error) => {
      const queryKey = ["governance-report", projectId, detail.id]
      try {
        // A request error is ambiguous until the persisted report is read
        // again. A no-draft read, or the definitive active-generation
        // conflict with its active draft, releases this browser key.
        await queryClient.invalidateQueries({ queryKey, refetchType: "none" })
        const refreshed = await queryClient.fetchQuery({
          queryKey,
          queryFn: () =>
            GovernanceReportsService.readGovernanceReport({
              projectId,
              reportId: detail.id,
            }),
        })
        const hasActiveDraft =
          refreshed.ai_governance_drafts?.some(
            (draft) => draft.status === "GENERATING",
          ) ?? false
        if (
          error &&
          ((refreshed.ai_governance_drafts?.length ?? 0) === 0 ||
            (hasActiveDraft && isActiveDraftGenerationConflict(error)))
        ) {
          clearPendingRequest()
        }
      } catch {
        // Keep the key if the post-request read did not conclusively rule out
        // a persisted draft or Session.
      }
    },
  })
  const latestDraft: AiGovernanceDraftPublic | undefined =
    detail.ai_governance_drafts?.[0] ?? generationMutation.data
  const generationAfterFailureBlocked =
    detail.ai_governance_drafts?.some((draft) => draft.status === "FAILED") ??
    false
  const activeDraft =
    latestDraft?.status === "GENERATING" ? latestDraft : undefined
  useEffect(() => {
    setSelectedFindingIds(new Set())
    setPendingRequest(readDraftRequestRecovery(storageKey))
  }, [storageKey])

  const toggleFinding = (findingId: string, checked: boolean) => {
    // Once a request key has been issued, the response may be ambiguous.  The
    // key and original selection are the only safe recovery handle until a
    // replay of that key confirms the resulting draft state.
    if (pendingRequest) return
    setSelectedFindingIds((current) => {
      const next = new Set(current)
      if (checked) {
        if (next.size < MAX_DRAFT_FINDINGS) next.add(findingId)
      } else {
        next.delete(findingId)
      }
      return next
    })
  }

  const requestDraft = () => {
    if (
      generationAfterFailureBlocked ||
      pendingRequest !== null ||
      selectedFindingIds.size === 0 ||
      generationMutation.isPending
    )
      return
    const request = {
      idempotencyKey: crypto.randomUUID(),
      findingIds: [...selectedFindingIds],
    }
    setPendingRequest(request)
    storeDraftRequestRecovery(storageKey, request)
    generationMutation.mutate({
      findingIds: request.findingIds,
      key: request.idempotencyKey,
    })
  }

  const resumePendingRequest = () => {
    if (!pendingRequest || generationMutation.isPending) return
    generationMutation.mutate({
      findingIds: pendingRequest.findingIds,
      key: pendingRequest.idempotencyKey,
    })
  }

  return (
    <ReportSection
      id="ai-governance-draft"
      title={t("AI governance draft", "AI 治理草稿")}
    >
      <p className="text-sm text-muted-foreground">
        {supportsAiDraft
          ? t(
              "Select one to eight eligible unobserved assets. Nothing is selected automatically, and the deterministic report remains unchanged.",
              "请选择一至八个符合条件的未观测资产。不会自动选择任何项，确定性报告保持不变。",
            )
          : t(
              `AI governance drafts are not supported for ${detail.report_contract_version}.`,
              `${detail.report_contract_version} 不支持 AI 治理草稿。`,
            )}
      </p>
      {!supportsAiDraft ? null : generationAfterFailureBlocked ? (
        <p className="text-sm text-muted-foreground">
          {t(
            "A new draft attempt after failure is not available in this release.",
            "此版本不支持在失败后重新尝试生成草稿。",
          )}
        </p>
      ) : pendingRequest ? (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">
            {t(
              "A previous request is pending. Replaying it sends the same idempotency key and exactly the Findings selected before reload.",
              "先前请求仍待处理。重放将发送相同的幂等键，以及重新加载前选择的原始发现项集合。",
            )}
          </p>
          <Button
            disabled={generationMutation.isPending}
            onClick={resumePendingRequest}
            type="button"
            variant="outline"
          >
            {generationMutation.isPending
              ? t("Resuming draft request…", "正在恢复草稿请求…")
              : t("Resume your draft request", "恢复您的草稿请求")}
          </Button>
        </div>
      ) : activeDraft ? (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">
            {t("Draft generation is already active.", "草稿生成已在进行中。")}
          </p>
          {activeDraft.session_id === null && (
            <p className="text-sm text-muted-foreground">
              {t(
                "This browser does not have a recoverable request for the active draft.",
                "此浏览器没有可用于恢复当前草稿的请求。",
              )}
            </p>
          )}
        </div>
      ) : !detail.can_request_ai_governance_draft ? (
        <p className="text-sm text-muted-foreground">
          {t(
            "A Project Operator can request an AI governance draft.",
            "项目操作员可请求 AI 治理草稿。",
          )}
        </p>
      ) : (
        <>
          {eligibleFindings.length === 0 ? (
            <p className="text-sm">
              {t(
                "No eligible unobserved-asset Findings are available.",
                "暂无符合条件的未观测资产发现项。",
              )}
            </p>
          ) : (
            <div className="space-y-2">
              {eligibleFindings.map((finding) => {
                const selected = selectedFindingIds.has(finding.id)
                return (
                  <div
                    className="flex min-w-0 flex-wrap items-start gap-2 rounded-md border p-2 text-sm"
                    key={finding.id}
                  >
                    <Checkbox
                      checked={selected}
                      disabled={
                        generationMutation.isPending ||
                        pendingRequest !== null ||
                        (!selected &&
                          selectedFindingIds.size >= MAX_DRAFT_FINDINGS)
                      }
                      id={`ai-draft-finding-${finding.id}`}
                      onCheckedChange={(checked) =>
                        toggleFinding(finding.id, checked === true)
                      }
                    />
                    <label
                      className="min-w-0 cursor-pointer break-all font-mono"
                      htmlFor={`ai-draft-finding-${finding.id}`}
                    >
                      {finding.canonicalIp}
                    </label>
                    <details className="min-w-0 basis-full">
                      <summary className="cursor-pointer">
                        {t("View evidence", "查看依据")}
                      </summary>
                      <TechnicalValue
                        value={finding.id}
                        label={t("Finding", "发现项")}
                      />
                    </details>
                  </div>
                )
              })}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <Button
              disabled={
                selectedFindingIds.size === 0 || generationMutation.isPending
              }
              onClick={requestDraft}
              type="button"
            >
              {generationMutation.isPending
                ? t("Requesting draft…", "正在请求草稿…")
                : t("Request AI draft", "请求 AI 草稿")}
            </Button>
            <span className="text-sm text-muted-foreground">
              {t(
                `${selectedFindingIds.size} of ${MAX_DRAFT_FINDINGS} selected`,
                `已选择 ${selectedFindingIds.size} 项，上限 ${MAX_DRAFT_FINDINGS} 项`,
              )}
            </span>
          </div>
        </>
      )}
      {generationMutation.isError && (
        <Alert variant="destructive">
          <AlertTitle>
            {t("Draft request could not be started", "无法启动草稿请求")}
          </AlertTitle>
          <AlertDescription>
            {pendingRequest
              ? t(
                  "The original request, including its selected Findings, is retained in this browser tab and can be replayed safely.",
                  "原始请求及其所选发现项保留在此浏览器标签页中，可安全重放。",
                )
              : t(
                  "No draft was persisted. You can update the selection or prerequisites and try again.",
                  "未持久化任何草稿。您可以更新所选项或前置条件后重试。",
                )}
          </AlertDescription>
        </Alert>
      )}
      {latestDraft && (
        <div className="rounded-md border p-3 text-sm" role="status">
          <p>
            {t("Generation", "生成状态")}{" "}
            <Badge>{translateValue(latestDraft.status)}</Badge>
          </p>
          <details className="mt-2 min-w-0">
            <summary className="cursor-pointer">
              {t("View evidence", "查看依据")}
            </summary>
            <p className="mt-2">
              <TechnicalValue
                value={latestDraft.id}
                label={t("Draft", "草稿")}
              />
            </p>
            {latestDraft.session_id && (
              <p>
                <TechnicalValue
                  value={latestDraft.session_id}
                  label={t("Session", "会话")}
                />
              </p>
            )}
          </details>
          {latestDraft.failure_code && (
            <p>
              {t("Failure:", "失败：")}{" "}
              {translateValue(latestDraft.failure_code)}
            </p>
          )}
        </div>
      )}
    </ReportSection>
  )
}

function PublishedReport({
  detail,
  projectId,
}: {
  detail: GovernanceReportDetailPublic
  projectId: string
}) {
  const { t, formatDate, translateValue } = useI18n()
  const root = asObject(detail.canonical_content)
  const report = root ? objectField(root, "report") : null
  const evidencePlan = root ? objectField(root, "evidence_plan") : null
  const identity = report ? objectField(report, "report_identity") : null
  const completeness = report ? objectField(report, "input_completeness") : null
  const summary = report ? objectField(report, "ip_consistency_summary") : null
  const lifecycle = report
    ? objectField(report, "current_run_lifecycle_changes")
    : null
  const backlog = report ? objectField(report, "open_backlog_as_of_run") : null
  const evidenceBoundary = report
    ? objectField(report, "bounded_evidence_examples")
    : null
  const directions = report
    ? objectField(report, "finding_type_directions_and_limitations")
    : null
  const provenance = report ? objectField(report, "provenance") : null

  if (
    !identity ||
    !completeness ||
    !summary ||
    !lifecycle ||
    !backlog ||
    !evidenceBoundary ||
    !directions ||
    !provenance ||
    !evidencePlan
  ) {
    return (
      <Alert variant="destructive">
        <AlertTitle>
          {t(
            "Published report content is not readable",
            "无法读取已发布报告内容",
          )}
        </AlertTitle>
        <AlertDescription>
          {t(
            "The fixed report contract is incomplete. No partial report is shown.",
            "固定报告合同不完整。不显示部分报告。",
          )}
        </AlertDescription>
      </Alert>
    )
  }

  const isZeroFindingMatch =
    completeness.complete === true &&
    summary.all_observed_ip_identities_matched === true &&
    numberField(summary, "current_run_finding_count") === 0
  const presentDirections = objectArray(directions, "directions").filter(
    (direction) => direction.present === true,
  )
  const limitations = Array.isArray(directions.limitations)
    ? directions.limitations.filter(
        (limitation): limitation is string => typeof limitation === "string",
      )
    : []
  const sourceSnapshotIds = Array.isArray(provenance.source_snapshot_ids)
    ? provenance.source_snapshot_ids
    : []
  const sourceSnapshotHashes = Array.isArray(provenance.source_snapshot_hashes)
    ? provenance.source_snapshot_hashes
    : []
  const snapshotReferences = sourceSnapshotIds.flatMap((snapshotId, index) =>
    typeof snapshotId === "string"
      ? [
          {
            id: snapshotId,
            hash:
              typeof sourceSnapshotHashes[index] === "string"
                ? sourceSnapshotHashes[index]
                : "",
          },
        ]
      : [],
  )

  return (
    <article
      className="min-w-0 space-y-4 [overflow-wrap:anywhere]"
      aria-label={t("Immutable governance report", "不可变治理报告")}
    >
      <ReportSection
        id="report-ip-summary"
        title={t("IP consistency summary", "IP 一致性摘要")}
      >
        <p className="text-sm text-muted-foreground">
          {t("Data as of Run completion:", "数据截至运行完成时间：")}{" "}
          {formatDate(stringField(identity, "run_completed_at"))}
        </p>
        <div className="space-y-3 text-sm">
          <p>
            {t("Customer observed assets:", "客户观测资产：")}{" "}
            {numberField(summary, "customer_observed_asset_count")} ·{" "}
            {t("CloudAtlas observed assets:", "CloudAtlas 观测资产：")}{" "}
            {numberField(summary, "cloudatlas_observed_asset_count")} ·{" "}
            {t("Matched assets:", "匹配资产：")}{" "}
            {numberField(summary, "matched_asset_count")} ·{" "}
            {t("Current-Run Findings:", "当前运行发现项：")}{" "}
            {numberField(summary, "current_run_finding_count")}
          </p>
          {isZeroFindingMatch ? (
            <Alert>
              <AlertTitle>
                {t("Complete dual-source IP match", "双来源 IP 完全匹配")}
              </AlertTitle>
              <AlertDescription>
                {t(
                  "With CustomerUpload and CloudAtlas inputs complete, all IP identities observed by those sources matched; this Run produced zero Findings.",
                  "CustomerUpload 和 CloudAtlas 输入完整，两者观测到的所有 IP 标识均匹配；此运行未产生发现项。",
                )}
              </AlertDescription>
            </Alert>
          ) : (
            <p>
              {t(
                "The report identifies unmatched observed IP identities.",
                "报告识别了未匹配的已观测 IP 标识。",
              )}
            </p>
          )}
          <CountList
            items={objectArray(summary, "finding_counts")}
            typeKey="finding_type"
          />
        </div>
      </ReportSection>
      <ReportSection
        id="report-input-completeness"
        title={t("Input completeness", "输入完整性")}
      >
        <InputCompleteness section={completeness} />
      </ReportSection>

      <ReportSection
        id="report-lifecycle-changes"
        title={t("Current-Run lifecycle changes", "当前运行的生命周期变更")}
      >
        <p className="text-sm">
          {t("Published transitions in this Run:", "此运行已发布的状态变更：")}{" "}
          {numberField(lifecycle, "total")}
        </p>
        <CountList
          items={objectArray(lifecycle, "transition_counts")}
          typeKey="transition_type"
        />
      </ReportSection>

      <ReportSection
        id="report-open-backlog"
        title={t("Open backlog as of Run", "截至此运行的未关闭发现项积压")}
      >
        <p className="text-sm">
          {t(
            "OPEN Findings as of this Run:",
            "截至此运行的 OPEN（未关闭）发现项：",
          )}{" "}
          {numberField(backlog, "total")}
        </p>
        <CountList
          items={objectArray(backlog, "finding_counts")}
          typeKey="finding_type"
        />
        <details className="min-w-0 text-sm">
          <summary className="cursor-pointer">
            {t("View evidence", "查看依据")}
          </summary>
          <div className="mt-2">
            <TechnicalValue
              value={stringField(backlog, "as_of_governance_run_id", "")}
              label={t("Governance Run", "治理运行")}
            />
          </div>
        </details>
      </ReportSection>

      <ReportSection
        id="report-directions-limitations"
        title={t(
          "Finding-type directions and limitations",
          "发现项类型的处理方向与局限性",
        )}
      >
        {presentDirections.length > 0 ? (
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {presentDirections.map((direction, index) => (
              <li key={`${stringField(direction, "finding_type")}-${index}`}>
                <span className="font-mono">
                  {stringField(direction, "finding_type")}
                </span>
                : {stringField(direction, "direction")}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm">
            {t(
              "This report has no Finding to handle.",
              "此报告没有需要处理的发现项。",
            )}
          </p>
        )}
        <h3 className="font-semibold">{t("Limitations", "局限性")}</h3>
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
      </ReportSection>
      <ReportSection
        id="report-evidence"
        title={t("Bounded Evidence examples", "有界证据示例")}
      >
        <p className="text-sm text-muted-foreground">
          {t("Selection owner:", "选择责任方：")}{" "}
          {stringField(evidenceBoundary, "selection_owner")} ·
          {t("published HTML maximum:", "已发布 HTML 最大条目数：")}{" "}
          {numberField(evidenceBoundary, "max_rendered_entries")}
        </p>
        <EvidenceCards
          evidencePlan={evidencePlan}
          evidenceCount={detail.evidence_count}
        />
      </ReportSection>
      <details className="min-w-0 space-y-3 rounded-lg border p-4">
        <summary className="cursor-pointer font-semibold">
          {t("View evidence", "查看依据")} · {t("Report identity", "报告身份")}
        </summary>
        <ReportSection
          id="report-identity"
          title={t("Report identity and generation mode", "报告身份与生成方式")}
        >
          <dl className="grid gap-3 text-sm md:grid-cols-2">
            <div className="min-w-0">
              <dt className="font-medium">{t("Project", "项目")}</dt>
              <dd>
                <TechnicalValue
                  value={stringField(identity, "project_id", "")}
                />
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="font-medium">{t("Report", "报告")}</dt>
              <dd>
                <TechnicalValue value={detail.id} />
              </dd>
            </div>
            <div>
              <dt className="font-medium">{t("Governance Run", "治理运行")}</dt>
              <dd>
                <TechnicalValue
                  value={stringField(identity, "governance_run_id", "")}
                />
              </dd>
            </div>
            <div>
              <dt className="font-medium">
                {t("Run completed", "运行完成时间")}
              </dt>
              <dd>{formatDate(stringField(identity, "run_completed_at"))}</dd>
            </div>
            <div>
              <dt className="font-medium">
                {t("Generation mode", "生成方式")}
              </dt>
              <dd>
                <Badge>
                  {translateValue(stringField(identity, "generation_mode"))}
                </Badge>
              </dd>
            </div>
            <div>
              <dt className="font-medium">
                {t("Report contract", "报告合同")}
              </dt>
              <dd className="break-all font-mono">
                {stringField(identity, "report_contract_version")}
              </dd>
            </div>
            <div>
              <dt className="font-medium">
                {t("HTML Artifact SHA-256", "HTML 产物 SHA-256")}
              </dt>
              <dd>
                <TechnicalValue value={detail.html_sha256} />
              </dd>
            </div>
            <div>
              <dt className="font-medium">
                {t("CSV Artifact SHA-256", "CSV 产物 SHA-256")}
              </dt>
              <dd>
                <TechnicalValue value={detail.csv_sha256} />
              </dd>
            </div>
          </dl>
        </ReportSection>
      </details>

      <details
        id="report-provenance"
        className="min-w-0 scroll-mt-6 space-y-3 rounded-lg border p-4"
      >
        <summary className="cursor-pointer font-semibold">
          {t("View evidence", "查看依据")} · {t("Provenance", "来源追溯")}
        </summary>
        <ReportSection
          id="report-source-references"
          title={t("Provenance", "来源追溯")}
        >
          <dl className="grid gap-3 text-sm md:grid-cols-2">
            <div>
              <dt className="font-medium">{t("Governance Run", "治理运行")}</dt>
              <dd>
                <TechnicalValue
                  value={stringField(provenance, "governance_run_id", "")}
                />
              </dd>
            </div>
            <div>
              <dt className="font-medium">
                {t("Processing contract", "处理合同")}
              </dt>
              <dd className="break-all font-mono">
                {stringField(provenance, "processing_contract_version")}
              </dd>
            </div>
            <div>
              <dt className="font-medium">
                {t("Finding lifecycle facts", "发现项生命周期事实")}
              </dt>
              <dd>{numberField(provenance, "finding_lifecycle_fact_count")}</dd>
            </div>
          </dl>
          <ul className="space-y-2 text-sm">
            {snapshotReferences.map((snapshot, index) => (
              <li
                className="rounded-md border p-2"
                key={`${snapshot.id}-${index}`}
              >
                <TechnicalValue
                  value={snapshot.id}
                  label={t("Snapshot reference", "快照引用")}
                />
                <TechnicalValue value={snapshot.hash} label="SHA-256" />
              </li>
            ))}
          </ul>
        </ReportSection>
      </details>
      <DraftGeneration detail={detail} projectId={projectId} />
    </article>
  )
}

export function useGovernanceReport(
  projectId: string,
  reportId: string | null,
) {
  return useQuery({
    queryKey: ["governance-report", projectId, reportId],
    queryFn: () =>
      GovernanceReportsService.readGovernanceReport({
        projectId,
        reportId: reportId as string,
      }),
    enabled: reportId !== null,
    refetchInterval: (query) => {
      const draft = query.state.data?.ai_governance_drafts?.[0]
      return draft?.status === "GENERATING" && draft.session_id === null
        ? 2000
        : false
    },
  })
}

function ReportReader({
  projectId,
  reportId,
  expectedRunId,
  expectedReportContractVersion,
}: {
  projectId: string
  reportId: string
  expectedRunId?: string
  expectedReportContractVersion?: string
}) {
  const { t } = useI18n()
  const detailQuery = useGovernanceReport(projectId, reportId)
  if (detailQuery.isPending)
    return <p role="status">{t("Loading report…", "正在加载报告…")}</p>
  const loadError = detailQuery.isError ? (
    <Alert variant="destructive">
      <AlertTitle>{t("Report could not be loaded", "无法加载报告")}</AlertTitle>
      <AlertDescription>
        {t("Please try again later.", "请稍后重试。")}
      </AlertDescription>
    </Alert>
  ) : null
  const detail = detailQuery.data
  if (
    !detail ||
    (detailQuery.error instanceof ApiError &&
      (detailQuery.error.status === 401 ||
        detailQuery.error.status === 403 ||
        detailQuery.error.status === 404))
  ) {
    return loadError
  }
  if (
    !getVerifiedReportContent(
      detail,
      projectId,
      reportId,
      expectedRunId,
      expectedReportContractVersion,
    )
  ) {
    return (
      <Alert variant="destructive">
        <AlertTitle>
          {t("Report identity mismatch", "报告身份不匹配")}
        </AlertTitle>
        <AlertDescription>
          {t(
            "The response does not identify the requested Project, Run and Report contract. No report content is displayed.",
            "响应未标识所请求的项目、运行与报告合同。不显示任何报告内容。",
          )}
        </AlertDescription>
      </Alert>
    )
  }
  return (
    <>
      {loadError}
      <AnalysisReportsPanel
        key={`${projectId}:${detail.governance_run_id}:${reportId}`}
        projectId={projectId}
        runId={detail.governance_run_id}
        reportId={reportId}
        reportContractVersion={detail.report_contract_version}
      />
      <PublishedReport detail={detail} projectId={projectId} />
    </>
  )
}

export function ReportDetailDialog({
  projectId,
  reportId,
  onOpenChange,
  expectedRunId,
  expectedReportContractVersion,
  onCloseAutoFocus,
}: {
  projectId: string
  reportId: string | null
  onOpenChange: (open: boolean) => void
  expectedRunId?: string
  expectedReportContractVersion?: string
  onCloseAutoFocus?: (event: Event) => void
}) {
  const { t } = useI18n()

  return (
    <Dialog open={reportId !== null} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-h-[92vh] min-w-0 max-w-[calc(100%-2rem)] overflow-y-auto sm:max-w-6xl"
        onCloseAutoFocus={onCloseAutoFocus}
      >
        <DialogHeader>
          <DialogTitle>
            {t("Published deterministic report", "已发布的确定性报告")}
          </DialogTitle>
          <DialogDescription>
            {t(
              "This immutable view renders only bounded canonical report content; it does not load CSV or raw source payloads.",
              "此不可变视图仅呈现有界的规范报告内容，不加载 CSV 或原始来源数据。报告原文保持不变。",
            )}
          </DialogDescription>
        </DialogHeader>
        {reportId !== null && (
          <ReportReader
            projectId={projectId}
            reportId={reportId}
            expectedRunId={expectedRunId}
            expectedReportContractVersion={expectedReportContractVersion}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

export default function GovernanceReports({
  projectId,
  runId,
  reportId,
}: {
  projectId: string
  runId: string
  reportId: string
}) {
  const { t } = useI18n()
  return (
    <section className="min-w-0 space-y-4" aria-labelledby="reports-title">
      <h2 id="reports-title" className="text-xl font-semibold">
        {t("Published deterministic report", "已发布的确定性报告")}
      </h2>
      <p className="text-sm text-muted-foreground">
        {t(
          "This immutable view renders only bounded canonical report content; it does not load CSV or raw source payloads.",
          "此不可变视图仅呈现有界的规范报告内容，不加载 CSV 或原始来源数据。报告原文保持不变。",
        )}
      </p>
      <ReportReader
        key={`${projectId}:${runId}:${reportId}`}
        projectId={projectId}
        reportId={reportId}
        expectedRunId={runId}
      />
    </section>
  )
}
