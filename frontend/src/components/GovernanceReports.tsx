import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"

import {
  type AiGovernanceDraftPublic,
  ApiError,
  type GovernanceReportDetailPublic,
  type GovernanceReportSummaryPublic,
  GovernanceReportsService,
} from "@/client"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useLocale } from "@/components/LocaleProvider"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

const REPORT_PAGE_SIZE = 20
const HTML_EVIDENCE_LIMIT = 8
const MAX_DRAFT_FINDINGS = 8
type Localize = (chinese: string, english: string) => string

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

function formatDate(value: string, locale: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(locale)
}

function CountList({
  items,
  typeKey,
  text,
}: {
  items: JsonObject[]
  typeKey: "finding_type" | "transition_type"
  text: Localize
}) {
  if (items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {text("未发布统计。", "No counts published.")}
      </p>
    )
  }
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm">
      {items.map((item, index) => (
        <li key={`${stringField(item, typeKey)}-${index}`}>
          <span className="font-mono">{stringField(item, typeKey)}</span>:{" "}
          {numberField(item, "count")}
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
    <section id={id} className="scroll-mt-6 space-y-3 rounded-lg border p-4">
      <h2 className="text-lg font-semibold">{title}</h2>
      {children}
    </section>
  )
}

function InputCompleteness({
  section,
  text,
}: {
  section: JsonObject
  text: Localize
}) {
  const sources = objectArray(section, "sources")
  return (
    <div className="space-y-3">
      <p className="text-sm">
        {section.complete === true
          ? text("所有有界输入摘要均标记为完整。", "All bounded input summaries are marked complete.")
          : text("已发布报告未将所有输入标记为完整。", "The published report does not mark all inputs complete.")}
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{text("来源", "Source")}</TableHead>
            <TableHead>{text("快照引用", "Snapshot reference")}</TableHead>
            <TableHead>{text("内容 SHA-256", "Content SHA-256")}</TableHead>
            <TableHead>{text("架构", "Schema")}</TableHead>
            <TableHead>{text("记录数", "Records")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sources.map((source, index) => (
            <TableRow key={`${stringField(source, "source_type")}-${index}`}>
              <TableCell>{stringField(source, "source_type")}</TableCell>
              <TableCell className="break-all font-mono text-xs">
                {stringField(source, "source_snapshot_id")}
              </TableCell>
              <TableCell className="break-all font-mono text-xs">
                {stringField(source, "content_sha256")}
              </TableCell>
              <TableCell className="break-all">
                {stringField(source, "schema_version")}
              </TableCell>
              <TableCell>{numberField(source, "record_count")}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function EvidenceCards({
  evidencePlan,
  evidenceCount,
  text,
}: {
  evidencePlan: JsonObject
  evidenceCount: number
  text: Localize
}) {
  const allEntries = objectArray(evidencePlan, "entries")
  const entries = allEntries.slice(0, HTML_EVIDENCE_LIMIT)
  if (entries.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {text("该报告未选择证据示例。", "No Evidence examples were selected for this report.")}
      </p>
    )
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        {text(
          `显示 ${evidenceCount} 条有界证据引用中的 ${entries.length} 条。HTML 视图最多展示 ${HTML_EVIDENCE_LIMIT} 张卡片。`,
          `Showing ${entries.length} of ${evidenceCount} bounded Evidence reference${evidenceCount === 1 ? "" : "s"}. The HTML view never renders more than ${HTML_EVIDENCE_LIMIT} cards.`,
        )}
      </p>
      <div className="grid gap-3 lg:grid-cols-2">
        {entries.map((entry, index) => {
          const reference = objectField(entry, "evidence_reference") ?? {}
          return (
            <article
              id={`report-evidence-${index + 1}`}
              data-testid="evidence-card"
              className="space-y-2 rounded-md border p-3 text-sm"
              key={`${stringField(entry, "finding_id")}-${index}`}
            >
              <h3 className="font-semibold">
                {text(`证据 ${index + 1}`, `Evidence ${index + 1}`)}
              </h3>
              <dl className="grid gap-1">
                <div>
                  <dt className="inline font-medium">{text("覆盖范围：", "Coverage: ")}</dt>
                  <dd className="inline">{stringField(entry, "coverage")}</dd>
                </div>
                <div>
                  <dt className="inline font-medium">{text("发现项：", "Finding: ")}</dt>
                  <dd className="inline break-all font-mono text-xs">
                    {stringField(entry, "finding_id")}
                  </dd>
                </div>
                <div>
                  <dt className="inline font-medium">{text("类型 / IP：", "Type / IP: ")}</dt>
                  <dd className="inline break-all">
                    {stringField(entry, "finding_type")} /{" "}
                    <span className="font-mono">
                      {stringField(entry, "canonical_ip")}
                    </span>
                  </dd>
                </div>
                <div>
                  <dt className="inline font-medium">{text("状态变更：", "Transition: ")}</dt>
                  <dd className="inline">
                    {stringField(entry, "transition_type", text("本次运行无变更", "None in this Run"))}
                  </dd>
                </div>
                <div>
                  <dt className="inline font-medium">{text("来源事实：", "Source fact: ")}</dt>
                  <dd className="inline break-all font-mono text-xs">
                    {stringField(reference, "fact_type")} /{" "}
                    {stringField(reference, "fact_id")}
                  </dd>
                </div>
              </dl>
              <p className="flex flex-wrap gap-3 text-sm">
                <a className="underline" href="#report-provenance">
                  {text("证据溯源", "Evidence provenance")}
                </a>
                <a className="underline" href="#report-open-backlog">
                  {text("发现项上下文", "Finding context")}
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
  const { text } = useLocale()
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
      title={text("AI 治理草稿", "AI governance draft")}
    >
      <p className="text-sm text-muted-foreground">
        {supportsAiDraft
          ? text(
              "请选择 1 至 8 个符合条件的未观测资产。系统不会自动选择，确定性报告保持不变。",
              "Select one to eight eligible unobserved assets. Nothing is selected automatically, and the deterministic report remains unchanged.",
            )
          : text(
              `报告契约 ${detail.report_contract_version} 不支持 AI 治理草稿。`,
              `AI governance drafts are not supported for ${detail.report_contract_version}.`,
            )}
      </p>
      {!supportsAiDraft ? null : generationAfterFailureBlocked ? (
        <p className="text-sm text-muted-foreground">
          {text(
            "本版本不支持在失败后再次生成草稿。",
            "A new draft attempt after failure is not available in this release.",
          )}
        </p>
      ) : pendingRequest ? (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">
            {text(
              "上一次请求仍在等待。恢复请求会使用相同的幂等键，并保留刷新前选择的发现项。",
              "A previous request is pending. Replaying it sends the same idempotency key and exactly the Findings selected before reload.",
            )}
          </p>
          <Button
            disabled={generationMutation.isPending}
            onClick={resumePendingRequest}
            type="button"
            variant="outline"
          >
            {generationMutation.isPending
              ? text("正在恢复草稿请求…", "Resuming draft request…")
              : text("恢复草稿请求", "Resume your draft request")}
          </Button>
        </div>
      ) : activeDraft ? (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">
            {text("草稿正在生成。", "Draft generation is already active.")}
          </p>
          {activeDraft.session_id === null && (
            <p className="text-sm text-muted-foreground">
              {text(
                "此浏览器没有可恢复的活动草稿请求。",
                "This browser does not have a recoverable request for the active draft.",
              )}
            </p>
          )}
        </div>
      ) : !detail.can_request_ai_governance_draft ? (
        <p className="text-sm text-muted-foreground">
          {text(
            "项目操作员可以请求 AI 治理草稿。",
            "A Project Operator can request an AI governance draft.",
          )}
        </p>
      ) : (
        <>
          {eligibleFindings.length === 0 ? (
            <p className="text-sm">
              {text(
                "没有可用于生成草稿的未观测资产发现项。",
                "No eligible unobserved-asset Findings are available.",
              )}
            </p>
          ) : (
            <div className="space-y-2">
              {eligibleFindings.map((finding) => {
                const selected = selectedFindingIds.has(finding.id)
                return (
                  <div
                    className="flex cursor-pointer items-center gap-2 rounded-md border p-2 text-sm"
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
                      className="flex cursor-pointer items-center gap-2"
                      htmlFor={`ai-draft-finding-${finding.id}`}
                    >
                      <span className="font-mono text-xs">{finding.id}</span>
                      <span className="text-muted-foreground">
                        {finding.canonicalIp}
                      </span>
                    </label>
                  </div>
                )
              })}
            </div>
          )}
          <div className="flex items-center gap-3">
            <Button
              disabled={
                selectedFindingIds.size === 0 || generationMutation.isPending
              }
              onClick={requestDraft}
              type="button"
            >
              {generationMutation.isPending
                ? text("正在请求草稿…", "Requesting draft…")
                : text("请求 AI 草稿", "Request AI draft")}
            </Button>
            <span className="text-sm text-muted-foreground">
              {text(
                `已选择 ${selectedFindingIds.size}/${MAX_DRAFT_FINDINGS} 项`,
                `${selectedFindingIds.size} of ${MAX_DRAFT_FINDINGS} selected`,
              )}
            </span>
          </div>
        </>
      )}
      {generationMutation.isError && (
        <Alert variant="destructive">
          <AlertTitle>{text("无法开始草稿请求", "Draft request could not be started")}</AlertTitle>
          <AlertDescription>
            {pendingRequest
              ? text(
                  "原始请求及所选发现项已保留在当前浏览器标签页，可安全恢复。",
                  "The original request, including its selected Findings, is retained in this browser tab and can be replayed safely.",
                )
              : text(
                  "未持久化任何草稿。请调整选择或前置条件后重试。",
                  "No draft was persisted. You can update the selection or prerequisites and try again.",
                )}
          </AlertDescription>
        </Alert>
      )}
      {latestDraft && (
        <div className="rounded-md border p-3 text-sm" role="status">
          <p>
            {text("生成状态", "Generation")} <Badge>{latestDraft.status}</Badge>
          </p>
          <p className="break-all font-mono text-xs">
            {text("草稿", "Draft")} {latestDraft.id}
          </p>
          {latestDraft.session_id && (
            <p className="break-all font-mono text-xs">
              {text("会话", "Session")} {latestDraft.session_id}
            </p>
          )}
          {latestDraft.failure_code && (
            <p>{text("失败：", "Failure: ")}{latestDraft.failure_code}</p>
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
  const { locale, text } = useLocale()
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
        <AlertTitle>{text("无法读取已发布报告内容", "Published report content is not readable")}</AlertTitle>
        <AlertDescription>
          {text(
            "固定报告契约不完整，因此不显示部分报告。",
            "The fixed report contract is incomplete. No partial report is shown.",
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
                : "—",
          },
        ]
      : [],
  )

  return (
    <article
      className="space-y-4"
      aria-label={text("不可变治理报告", "Immutable governance report")}
    >
      <DraftGeneration detail={detail} projectId={projectId} />
      <ReportSection
        id="report-identity"
        title={text("报告身份与生成方式", "Report identity and generation mode")}
      >
        <dl className="grid gap-3 text-sm md:grid-cols-2">
          <div>
            <dt className="font-medium">{text("治理运行", "Governance Run")}</dt>
            <dd className="break-all font-mono">
              {stringField(identity, "governance_run_id")}
            </dd>
          </div>
          <div>
            <dt className="font-medium">{text("运行完成时间", "Run completed")}</dt>
            <dd>{formatDate(stringField(identity, "run_completed_at"), locale)}</dd>
          </div>
          <div>
            <dt className="font-medium">{text("生成方式", "Generation mode")}</dt>
            <dd>
              <Badge>{stringField(identity, "generation_mode")}</Badge>
            </dd>
          </div>
          <div>
            <dt className="font-medium">{text("报告契约", "Report contract")}</dt>
            <dd className="break-all font-mono">
              {stringField(identity, "report_contract_version")}
            </dd>
          </div>
          <div>
            <dt className="font-medium">{text("HTML 制品 SHA-256", "HTML Artifact SHA-256")}</dt>
            <dd className="break-all font-mono text-xs">
              {detail.html_sha256}
            </dd>
          </div>
          <div>
            <dt className="font-medium">{text("CSV 制品 SHA-256", "CSV Artifact SHA-256")}</dt>
            <dd className="break-all font-mono text-xs">{detail.csv_sha256}</dd>
          </div>
        </dl>
      </ReportSection>

      <ReportSection
        id="report-input-completeness"
        title={text("输入完整性", "Input completeness")}
      >
        <InputCompleteness section={completeness} text={text} />
      </ReportSection>

      <ReportSection
        id="report-ip-summary"
        title={text("IP 一致性摘要", "IP consistency summary")}
      >
        <div className="space-y-3 text-sm">
          <p>
            {text(
              `客户侧观测资产：${numberField(summary, "customer_observed_asset_count")} · CloudAtlas 观测资产：${numberField(summary, "cloudatlas_observed_asset_count")} · 匹配资产：${numberField(summary, "matched_asset_count")} · 本次运行发现项：${numberField(summary, "current_run_finding_count")}`,
              `Customer observed assets: ${numberField(summary, "customer_observed_asset_count")} · CloudAtlas observed assets: ${numberField(summary, "cloudatlas_observed_asset_count")} · Matched assets: ${numberField(summary, "matched_asset_count")} · Current-Run Findings: ${numberField(summary, "current_run_finding_count")}`,
            )}
          </p>
          {isZeroFindingMatch ? (
            <Alert>
              <AlertTitle>{text("双来源 IP 完整匹配", "Complete dual-source IP match")}</AlertTitle>
              <AlertDescription>
                {text(
                  "客户上传与 CloudAtlas 输入完整时，两个来源观测到的所有 IP 身份均已匹配；本次运行未产生发现项。",
                  "With CustomerUpload and CloudAtlas inputs complete, all IP identities observed by those sources matched; this Run produced zero Findings.",
                )}
              </AlertDescription>
            </Alert>
          ) : (
            <p>{text("报告识别到未匹配的观测 IP 身份。", "The report identifies unmatched observed IP identities.")}</p>
          )}
          <CountList
            items={objectArray(summary, "finding_counts")}
            typeKey="finding_type"
            text={text}
          />
        </div>
      </ReportSection>

      <ReportSection
        id="report-lifecycle-changes"
        title={text("本次运行生命周期变更", "Current-Run lifecycle changes")}
      >
        <p className="text-sm">
          {text(
            `本次运行已发布的状态变更：${numberField(lifecycle, "total")}`,
            `Published transitions in this Run: ${numberField(lifecycle, "total")}`,
          )}
        </p>
        <CountList
          items={objectArray(lifecycle, "transition_counts")}
          typeKey="transition_type"
          text={text}
        />
      </ReportSection>

      <ReportSection
        id="report-open-backlog"
        title={text("截至本次运行的待处理项", "Open backlog as of Run")}
      >
        <p className="text-sm">
          {text("截至治理运行的开放发现项 ", "OPEN Findings as of Run ")}
          <span className="break-all font-mono">
            {stringField(backlog, "as_of_governance_run_id")}
          </span>
          : {numberField(backlog, "total")}
        </p>
        <CountList
          items={objectArray(backlog, "finding_counts")}
          typeKey="finding_type"
          text={text}
        />
      </ReportSection>

      <ReportSection
        id="report-evidence"
        title={text("有界证据示例", "Bounded Evidence examples")}
      >
        <p className="text-sm text-muted-foreground">
          {text(
            `选择主体：${stringField(evidenceBoundary, "selection_owner")} · 已发布 HTML 最大展示数：${numberField(evidenceBoundary, "max_rendered_entries")}`,
            `Selection owner: ${stringField(evidenceBoundary, "selection_owner")} · published HTML maximum: ${numberField(evidenceBoundary, "max_rendered_entries")}`,
          )}
        </p>
        <EvidenceCards
          evidencePlan={evidencePlan}
          evidenceCount={detail.evidence_count}
          text={text}
        />
      </ReportSection>

      <ReportSection
        id="report-directions-limitations"
        title={text("发现项类型处置方向与限制", "Finding-type directions and limitations")}
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
          <p className="text-sm">{text("此报告没有需要处理的发现项。", "This report has no Finding to handle.")}</p>
        )}
        <h3 className="font-semibold">{text("限制", "Limitations")}</h3>
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
      </ReportSection>

      <ReportSection id="report-provenance" title={text("溯源信息", "Provenance")}>
        <dl className="grid gap-3 text-sm md:grid-cols-2">
          <div>
            <dt className="font-medium">{text("治理运行", "Governance Run")}</dt>
            <dd className="break-all font-mono">
              {stringField(provenance, "governance_run_id")}
            </dd>
          </div>
          <div>
            <dt className="font-medium">{text("处理契约", "Processing contract")}</dt>
            <dd className="break-all font-mono">
              {stringField(provenance, "processing_contract_version")}
            </dd>
          </div>
          <div>
            <dt className="font-medium">{text("发现项生命周期事实", "Finding lifecycle facts")}</dt>
            <dd>{numberField(provenance, "finding_lifecycle_fact_count")}</dd>
          </div>
        </dl>
        <ul className="space-y-2 text-sm">
          {snapshotReferences.map((snapshot, index) => (
            <li
              className="rounded-md border p-2"
              key={`${snapshot.id}-${index}`}
            >
              {text("快照引用 ", "Snapshot reference ")}
              <span className="break-all font-mono">{snapshot.id}</span>
              <span className="block break-all font-mono text-xs text-muted-foreground">
                SHA-256 {snapshot.hash}
              </span>
            </li>
          ))}
        </ul>
      </ReportSection>
    </article>
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
  const { text } = useLocale()
  const detailQuery = useQuery({
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
  const detail = detailQuery.data
  const root = detail ? asObject(detail.canonical_content) : null
  const report = root ? objectField(root, "report") : null
  const identity = report ? objectField(report, "report_identity") : null
  const identityMismatch =
    detail &&
    (detail.id !== reportId ||
      !identity ||
      identity.project_id !== projectId ||
      identity.governance_run_id !== detail.governance_run_id ||
      identity.report_contract_version !== detail.report_contract_version ||
      root?.schema_version !== detail.report_contract_version ||
      (expectedRunId !== undefined &&
        detail.governance_run_id !== expectedRunId) ||
      (expectedReportContractVersion !== undefined &&
        detail.report_contract_version !== expectedReportContractVersion))

  return (
    <Dialog open={reportId !== null} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-h-[92vh] max-w-[calc(100%-2rem)] overflow-y-auto sm:max-w-6xl"
        onCloseAutoFocus={onCloseAutoFocus}
      >
        <DialogHeader>
          <DialogTitle>{text("已发布的确定性治理报告", "Published deterministic report")}</DialogTitle>
          <DialogDescription>
            {text(
              "此不可变视图仅呈现有界的规范报告内容，不加载 CSV 或原始来源载荷。",
              "This immutable view renders only bounded canonical report content; it does not load CSV or raw source payloads.",
            )}
          </DialogDescription>
        </DialogHeader>
        {detailQuery.isPending && (
          <p role="status">{text("正在加载报告…", "Loading report…")}</p>
        )}
        {detailQuery.isError && (
          <Alert variant="destructive">
            <AlertTitle>{text("无法加载报告", "Report could not be loaded")}</AlertTitle>
            <AlertDescription>{text("请稍后重试。", "Please try again later.")}</AlertDescription>
          </Alert>
        )}
        {identityMismatch && (
          <Alert variant="destructive">
            <AlertTitle>{text("报告身份不匹配", "Report identity mismatch")}</AlertTitle>
            <AlertDescription>
              {text(
                "响应无法标识所请求的项目、治理运行和报告契约，因此不显示报告内容。",
                "The response does not identify the requested Project, Run and Report contract. No report content is displayed.",
              )}
            </AlertDescription>
          </Alert>
        )}
        {detail && !identityMismatch && (
          <PublishedReport detail={detail} projectId={projectId} />
        )}
      </DialogContent>
    </Dialog>
  )
}

function ReportRow({
  report,
  onRead,
  locale,
  text,
}: {
  report: GovernanceReportSummaryPublic
  onRead: () => void
  locale: string
  text: Localize
}) {
  return (
    <TableRow>
      <TableCell className="break-all font-mono text-xs">
        {report.governance_run_id}
      </TableCell>
      <TableCell>{formatDate(report.run_completed_at, locale)}</TableCell>
      <TableCell>
        <Badge>{report.generation_mode}</Badge>
      </TableCell>
      <TableCell className="break-all font-mono text-xs">
        {report.report_contract_version}
      </TableCell>
      <TableCell className="max-w-72 break-all font-mono text-xs">
        {report.html_sha256}
      </TableCell>
      <TableCell>
        <Button type="button" variant="outline" size="sm" onClick={onRead}>
          {text("阅读报告", "Read report")}
        </Button>
      </TableCell>
    </TableRow>
  )
}

export default function GovernanceReports({
  projectId,
}: {
  projectId: string
}) {
  const { locale, text } = useLocale()
  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>([
    null,
  ])
  const [pageIndex, setPageIndex] = useState(0)
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null)
  const cursor = cursorHistory[pageIndex] ?? null
  const reportsQuery = useQuery({
    queryKey: ["governance-reports", projectId, cursor],
    queryFn: () =>
      GovernanceReportsService.readGovernanceReports({
        projectId,
        limit: REPORT_PAGE_SIZE,
        cursor,
      }),
    staleTime: Number.POSITIVE_INFINITY,
  })

  if (reportsQuery.isPending) {
    return <p role="status">{text("正在加载治理报告…", "Loading Reports…")}</p>
  }
  if (reportsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>{text("无法加载治理报告", "Reports could not be loaded")}</AlertTitle>
        <AlertDescription>{text("请稍后重试。", "Please try again later.")}</AlertDescription>
      </Alert>
    )
  }

  const reports = reportsQuery.data
  return (
    <section className="space-y-4" aria-labelledby="reports-title">
      <Card>
        <CardHeader>
          <CardTitle id="reports-title">{text("治理报告", "Reports")}</CardTitle>
          <CardDescription>
            {text(
              `此项目已发布 ${reports.count} 份不可变确定性治理报告`,
              `Published immutable deterministic reports for this Project · ${reports.count} total`,
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {reports.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {text("暂无已发布的治理报告。", "No published reports are available.")}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{text("治理运行", "Governance Run")}</TableHead>
                  <TableHead>{text("完成时间", "Completed")}</TableHead>
                  <TableHead>{text("生成方式", "Generation mode")}</TableHead>
                  <TableHead>{text("报告契约", "Report contract")}</TableHead>
                  <TableHead>{text("HTML 制品 SHA-256", "HTML Artifact SHA-256")}</TableHead>
                  <TableHead>{text("报告", "Report")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {reports.data.map((report) => (
                  <ReportRow
                    key={report.id}
                    report={report}
                    locale={locale}
                    text={text}
                    onRead={() => setSelectedReportId(report.id)}
                  />
                ))}
              </TableBody>
            </Table>
          )}
          {(pageIndex > 0 || reports.next_cursor !== null) && (
            <nav
              className="flex items-center justify-end gap-3"
              aria-label={text("报告分页", "Reports pagination")}
            >
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={pageIndex === 0}
                onClick={() => setPageIndex((current) => current - 1)}
              >
                {text("上一页", "Previous")}
              </Button>
              <span className="text-sm text-muted-foreground">
                {text(`第 ${pageIndex + 1} 页`, `Page ${pageIndex + 1}`)}
              </span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={reports.next_cursor === null}
                onClick={() => {
                  if (reports.next_cursor === null) return
                  setCursorHistory((history) => [
                    ...history.slice(0, pageIndex + 1),
                    reports.next_cursor,
                  ])
                  setPageIndex((current) => current + 1)
                }}
              >
                {text("下一页", "Next")}
              </Button>
            </nav>
          )}
        </CardContent>
      </Card>
      <ReportDetailDialog
        projectId={projectId}
        reportId={selectedReportId}
        onOpenChange={(open) => {
          if (!open) setSelectedReportId(null)
        }}
      />
    </section>
  )
}
