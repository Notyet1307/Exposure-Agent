import { useMemo, useState } from "react"

import {
  buildChapterMembership,
  chapterTitles,
} from "@/components/reportChapters"
import {
  compareHistorySnapshots,
  type HistorySnapshot,
  parseReportHistory,
  sameProtectedStructure,
} from "@/components/reportHistory"
import { Button } from "@/components/ui/button"
import type { V2Text } from "@/components/V2ReportContent"
import { useI18n } from "@/lib/i18n"

const statusLabel = (status: string | null): [string, string] => {
  if (status === "DRAFT") return ["Draft", "草稿"]
  if (status === "CONFIRMED") return ["Confirmed", "已确认"]
  return ["Status unavailable", "状态不可用"]
}

const claimTypeLabel: Record<string, [string, string]> = {
  explanation: ["Explanation to verify", "待核实解释"],
  hypothesis: ["Hypothesis", "可能解释"],
  gap: ["Missing evidence", "尚缺依据"],
  action: ["Suggested check", "建议核实"],
}

function SnapshotClaim({ claim }: { claim: V2Text["claims"][number] }) {
  const { t } = useI18n()
  if (claim.type === "fact")
    return (
      <div className="min-w-0 space-y-1">
        <p className="text-sm font-medium">
          {t("Fixed fact reference", "固定事实引用")}
        </p>
        <p className="break-words text-sm [overflow-wrap:anywhere]">
          {claim.fact_refs.join(" · ")}
        </p>
        <p className="break-words text-xs text-muted-foreground [overflow-wrap:anywhere]">
          {t("Evidence", "依据")} {claim.evidence_refs.join(" · ")}
        </p>
      </div>
    )
  return (
    <div className="min-w-0 space-y-1">
      <p className="text-sm font-medium">{t(...claimTypeLabel[claim.type])}</p>
      <p className="max-w-prose whitespace-pre-wrap break-words text-sm [overflow-wrap:anywhere]">
        {claim.text}
      </p>
      {(claim.fact_refs ?? []).length > 0 && (
        <p className="break-words text-xs text-muted-foreground [overflow-wrap:anywhere]">
          {t("Facts", "事实")} {(claim.fact_refs ?? []).join(" · ")}
        </p>
      )}
      <p className="break-words text-xs text-muted-foreground [overflow-wrap:anywhere]">
        {t("Evidence", "依据")} {claim.evidence_refs.join(" · ")}
      </p>
    </div>
  )
}

function SnapshotText({ text }: { text: V2Text }) {
  const { t } = useI18n()
  const claims = new Map(text.claims.map((claim) => [claim.id, claim]))
  const { unplacedIds } = buildChapterMembership(text)
  return (
    <div className="min-w-0 space-y-4 text-sm">
      <section className="min-w-0 space-y-2">
        <h5 className="font-medium">{t(...chapterTitles.summary)}</h5>
        {[...new Set(text.summary)].map((id) =>
          claims.has(id) ? (
            <SnapshotClaim key={`summary-${id}`} claim={claims.get(id)!} />
          ) : null,
        )}
      </section>
      {text.sections.map((section) => (
        <section key={section.id} className="min-w-0 space-y-2">
          <h5 className="font-medium">{t(...chapterTitles[section.id])}</h5>
          {[...new Set(section.claim_ids)].map((id) =>
            claims.has(id) ? (
              <SnapshotClaim
                key={`${section.id}-${id}`}
                claim={claims.get(id)!}
              />
            ) : null,
          )}
        </section>
      ))}
      {unplacedIds.length > 0 && (
        <section className="min-w-0 space-y-2">
          <h5 className="font-medium">{t(...chapterTitles.unplaced)}</h5>
          {unplacedIds.map((id) =>
            claims.has(id) ? (
              <SnapshotClaim key={`unplaced-${id}`} claim={claims.get(id)!} />
            ) : null,
          )}
        </section>
      )}
      {text.priority_cases.length > 0 && (
        <section className="min-w-0 space-y-2">
          <h5 className="font-medium">{t(...chapterTitles.priority_cases)}</h5>
          <ol className="list-decimal space-y-3 pl-5">
            {text.priority_cases.map((item) => (
              <li key={item.address_key} className="min-w-0 space-y-1">
                <p className="break-words text-xs text-muted-foreground [overflow-wrap:anywhere]">
                  {item.address_key}
                </p>
                <p className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
                  {item.why_review}
                </p>
                <p className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
                  {item.next_check}
                </p>
                <p className="break-words text-xs text-muted-foreground [overflow-wrap:anywhere]">
                  {t("Evidence", "依据")} {item.evidence_refs.join(" · ")}
                </p>
              </li>
            ))}
          </ol>
        </section>
      )}
      {text.limitations.length > 0 && (
        <section className="min-w-0 space-y-2">
          <h5 className="font-medium">{t(...chapterTitles.limits)}</h5>
          <ul className="list-disc space-y-1 pl-5">
            {text.limitations.map((limit, index) => (
              <li
                key={`limit-${index}`}
                className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]"
              >
                {limit}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

function SnapshotColumn({
  label,
  snapshot,
}: {
  label: string
  snapshot: HistorySnapshot
}) {
  const { t } = useI18n()
  return (
    <section
      aria-label={label}
      className="min-w-0 space-y-3 rounded border p-3"
    >
      <div className="space-y-1">
        <h4 className="font-semibold">
          {t(`Revision ${snapshot.revision}`, `修订 ${snapshot.revision}`)}
        </h4>
        <p className="text-xs text-muted-foreground">
          {t(...statusLabel(snapshot.status))}
        </p>
      </div>
      <SnapshotText text={snapshot.text} />
    </section>
  )
}

export function V2ReportHistory({
  reportId,
  verifiedText,
  status,
  value,
  onRetry,
}: {
  reportId: string
  verifiedText: V2Text | null
  status: "pending" | "error" | "success"
  value: unknown[] | undefined
  onRetry: () => void
}) {
  const { t, formatDate } = useI18n()
  const parsed = useMemo(
    () => parseReportHistory(value, reportId),
    [value, reportId],
  )
  const [selected, setSelected] = useState<number | null>(null)
  if (status === "pending")
    return (
      <p role="status">{t("Reading revision history…", "正在读取修订历史…")}</p>
    )
  if (status === "error")
    return (
      <div className="space-y-2">
        <p role="status">
          {t(
            "Revision history could not be read. No snapshot content is shown.",
            "无法读取修订历史，不显示任何快照内容。",
          )}
        </p>
        <Button type="button" size="sm" variant="outline" onClick={onRetry}>
          {t("Re-read revision history", "重读修订历史")}
        </Button>
      </div>
    )
  if (parsed.state === "invalid")
    return (
      <p role="alert">
        {t(
          "Revision history is invalid for this report. It is not treated as empty, and no snapshot body is shown.",
          "此报告的修订历史无效。系统不会将其视为空历史，也不显示任何快照正文。",
        )}
      </p>
    )
  const snapshots = parsed.snapshots
  if (snapshots.length === 0)
    return (
      <p>
        {t(
          "No revision history is available for this report yet.",
          "此报告暂无修订历史。",
        )}
      </p>
    )
  const current =
    snapshots.find((snapshot) => snapshot.revision === selected) ?? snapshots[0]
  const previous = snapshots.find(
    (snapshot) => snapshot.revision === current.revision - 1,
  )
  const selectedMatches =
    !!verifiedText && sameProtectedStructure(verifiedText, current.text)
  const previousMatches =
    !!verifiedText &&
    !!previous &&
    sameProtectedStructure(verifiedText, previous.text)
  const comparison =
    previous && selectedMatches && previousMatches
      ? compareHistorySnapshots(previous, current)
      : null
  return (
    <div className="min-w-0 space-y-4">
      <div className="space-y-2">
        <h4 className="font-medium">{t("Recorded snapshots", "已记录快照")}</h4>
        <ol className="max-h-64 space-y-1 overflow-auto pr-1">
          {snapshots.map((snapshot) => {
            const active = snapshot.revision === current.revision
            return (
              <li key={snapshot.id} className="min-w-0">
                <button
                  type="button"
                  aria-pressed={active}
                  onClick={() => setSelected(snapshot.revision)}
                  className={`w-full min-w-0 rounded border p-2 text-left text-xs ${
                    active ? "bg-muted font-medium" : "bg-background"
                  }`}
                >
                  <span className="block">
                    {t(
                      `Revision ${snapshot.revision}`,
                      `修订 ${snapshot.revision}`,
                    )}{" "}
                    · {t(...statusLabel(snapshot.status))} ·{" "}
                    {snapshot.recordedAt
                      ? formatDate(snapshot.recordedAt, "UTC")
                      : t("Time unavailable", "时间不可用")}{" "}
                    · {t("Author unavailable", "作者不可用")}
                  </span>
                  {snapshot.actorId && (
                    <span className="block break-words text-muted-foreground [overflow-wrap:anywhere]">
                      {t(
                        "Recorded actor identifier (not a display name)",
                        "记录的操作用户标识（不是显示名称）",
                      )}{" "}
                      {snapshot.actorId}
                    </span>
                  )}
                </button>
              </li>
            )
          })}
        </ol>
      </div>
      {!verifiedText ? (
        <p role="alert">
          {t(
            "This report's current verified fixed structure is unavailable, so no revision body can be validated or shown.",
            "此报告当前经核验的固定结构不可用，因此无法校验或显示任何修订正文。",
          )}
        </p>
      ) : !selectedMatches ? (
        <p role="alert">
          {t(
            `Revision ${current.revision} does not match this report's current verified fixed structure. Its body is suppressed, and no changed or unchanged text is claimed.`,
            `修订 ${current.revision} 与此报告当前经核验的固定结构不一致。已隐藏其正文，也不声称任何变更或未变更。`,
          )}
        </p>
      ) : current.revision === 1 ? (
        <div className="space-y-3">
          <p role="status">
            {t(
              "This is the first recorded revision. No earlier revision is shown.",
              "这是首个已记录修订，不显示更早的修订。",
            )}
          </p>
          <SnapshotColumn
            label={t("Initial revision", "首个修订")}
            snapshot={current}
          />
        </div>
      ) : !previous ? (
        <div className="space-y-3">
          <p role="alert">
            {t(
              `Revision ${current.revision - 1} is not available, so no comparison is shown across the gap.`,
              `修订 ${current.revision - 1} 不可用，因此不跨缺口进行对比。`,
            )}
          </p>
          <SnapshotColumn
            label={t(
              `Selected revision ${current.revision}`,
              `所选修订 ${current.revision}`,
            )}
            snapshot={current}
          />
        </div>
      ) : !previousMatches ? (
        <div className="space-y-3">
          <p role="alert">
            {t(
              `Revision ${previous.revision} does not match this report's current verified fixed structure, so no comparison is shown. Only the selected revision ${current.revision} body is shown, and no changed or unchanged text is claimed.`,
              `修订 ${previous.revision} 与此报告当前经核验的固定结构不一致，因此不进行对比。仅显示所选修订 ${current.revision} 的正文，也不声称任何变更或未变更。`,
            )}
          </p>
          <SnapshotColumn
            label={t(
              `Selected revision ${current.revision}`,
              `所选修订 ${current.revision}`,
            )}
            snapshot={current}
          />
        </div>
      ) : comparison?.kind === "structure_mismatch" ? (
        <p role="alert">
          {t(
            "These adjacent snapshots do not share the same fixed report structure. Their bodies are suppressed and no changed or unchanged text is claimed.",
            "这两个相邻快照的固定报告结构不一致。已隐藏其正文，也不声称任何变更或未变更。",
          )}
        </p>
      ) : comparison ? (
        <div className="space-y-3">
          {comparison.confirmationOnly ? (
            <p role="status">
              {t(
                "This adjacent step only confirmed the same text. Confirmation does not prove the narrative is correct.",
                "此相邻步骤只是确认了相同正文；确认不证明解读正确。",
              )}
            </p>
          ) : comparison.unchangedText ? (
            <p role="status">
              {t(
                "No narrative text changed between these adjacent revisions. Equal text alone does not prove a confirmation.",
                "这两个相邻修订的叙述正文没有变化；正文相同本身不证明发生过确认。",
              )}
            </p>
          ) : (
            <div className="space-y-1" role="status">
              <p>
                {t(
                  "Full text changed between these adjacent revisions.",
                  "这两个相邻修订的正文有变化。",
                )}
              </p>
              <p>
                {t("Affected chapters", "涉及章节")}:{" "}
                {comparison.affectedChapters
                  .map((id) => t(...chapterTitles[id]))
                  .join(" · ") || t("Not derived", "未推导")}
              </p>
            </div>
          )}
          <div className="grid min-w-0 gap-3 lg:grid-cols-2">
            <SnapshotColumn
              label={t(
                `Before revision ${previous.revision}`,
                `修订 ${previous.revision} 之前`,
              )}
              snapshot={previous}
            />
            <SnapshotColumn
              label={t(
                `After revision ${current.revision}`,
                `修订 ${current.revision} 之后`,
              )}
              snapshot={current}
            />
          </div>
        </div>
      ) : null}
    </div>
  )
}
