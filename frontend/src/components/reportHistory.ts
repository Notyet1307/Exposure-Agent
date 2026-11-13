import { claimMemberships, orderChapters } from "@/components/reportChapters"
import type { V2Text } from "@/components/V2ReportContent"

const reportSectionIds = [
  "conclusion",
  "differences",
  "priority",
  "netflow",
  "next_steps",
  "appendix",
] as const
const addressSectionIds = [
  "known_facts",
  "possible_explanations",
  "missing_evidence",
  "next_checks",
] as const
const claimIdPattern = /^[a-z][a-z0-9_-]{0,63}$/
const addressKeyPattern = /^addr:[a-f0-9]{64}$/
const narrativeTypes = new Set(["explanation", "hypothesis", "gap", "action"])

export type HistorySnapshot = {
  id: string
  reportId: string
  revision: number
  status: string | null
  actorId: string | null
  recordedAt: string | null
  text: V2Text
}

export type HistoryParse =
  | { state: "invalid"; reason: string }
  | { state: "ok"; snapshots: HistorySnapshot[] }

export type HistoryComparison =
  | { kind: "structure_mismatch" }
  | {
      kind: "comparison"
      changedClaimIds: string[]
      changedCaseKeys: string[]
      affectedChapters: string[]
      confirmationOnly: boolean
      unchangedText: boolean
    }

const invalid = (reason: string): HistoryParse => ({
  state: "invalid",
  reason,
})
const object = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
const isText = (value: unknown): value is string =>
  typeof value === "string" &&
  value.trim().length > 0 &&
  value.trim().length <= 2000
const isRef = (value: unknown): value is string =>
  typeof value === "string" && value.length > 0 && value.length <= 256
const isRefList = (
  value: unknown,
  minimum = 1,
  maximum = 8,
): value is string[] =>
  Array.isArray(value) &&
  value.length >= minimum &&
  value.length <= maximum &&
  value.every(isRef)
const unique = (values: string[]) => new Set(values).size === values.length

function parseClaims(value: unknown): V2Text["claims"] | null {
  if (!Array.isArray(value) || value.length < 1 || value.length > 48)
    return null
  const claims: V2Text["claims"] = []
  for (const entry of value) {
    const claim = object(entry)
    if (!claim) return null
    if (typeof claim.id !== "string" || !claimIdPattern.test(claim.id))
      return null
    if (claim.type === "fact") {
      if (!isRefList(claim.fact_refs) || !isRefList(claim.evidence_refs))
        return null
      claims.push({
        id: claim.id,
        type: "fact",
        fact_refs: claim.fact_refs,
        evidence_refs: claim.evidence_refs,
      })
      continue
    }
    if (typeof claim.type !== "string" || !narrativeTypes.has(claim.type))
      return null
    if (!isText(claim.text) || !isRefList(claim.evidence_refs)) return null
    if (claim.fact_refs !== undefined && !isRefList(claim.fact_refs, 0))
      return null
    claims.push({
      id: claim.id,
      type: claim.type as "explanation" | "hypothesis" | "gap" | "action",
      text: claim.text,
      fact_refs: (claim.fact_refs as string[] | undefined) ?? [],
      evidence_refs: claim.evidence_refs,
    })
  }
  if (!unique(claims.map((claim) => claim.id))) return null
  return claims
}

function parseSections(value: unknown): V2Text["sections"] | null {
  if (!Array.isArray(value) || value.length < 4 || value.length > 6) return null
  const ids = value.map((entry) => object(entry)?.id)
  const expected =
    JSON.stringify(ids) === JSON.stringify(reportSectionIds) ||
    JSON.stringify(ids) === JSON.stringify(addressSectionIds)
  if (!expected) return null
  const sections: V2Text["sections"] = []
  for (const entry of value) {
    const section = object(entry)
    if (!section) return null
    const claimIds = section.claim_ids
    if (
      !Array.isArray(claimIds) ||
      claimIds.length < 1 ||
      claimIds.length > 16 ||
      !claimIds.every((id) => typeof id === "string")
    )
      return null
    sections.push({
      id: section.id as V2Text["sections"][number]["id"],
      claim_ids: claimIds as string[],
    })
  }
  return sections
}

function parseCases(value: unknown): V2Text["priority_cases"] | null {
  if (!Array.isArray(value) || value.length > 20) return null
  const cases: V2Text["priority_cases"] = []
  for (const entry of value) {
    const item = object(entry)
    if (!item) return null
    if (
      typeof item.address_key !== "string" ||
      !addressKeyPattern.test(item.address_key) ||
      !isText(item.why_review) ||
      !isText(item.next_check) ||
      !isRefList(item.evidence_refs)
    )
      return null
    cases.push({
      address_key: item.address_key,
      why_review: item.why_review,
      next_check: item.next_check,
      evidence_refs: item.evidence_refs,
    })
  }
  if (!unique(cases.map((item) => item.address_key))) return null
  return cases
}

function parseText(value: unknown): V2Text | null {
  const text = object(value)
  if (!text) return null
  const summaryValue = text.summary
  if (
    !Array.isArray(summaryValue) ||
    summaryValue.length < 1 ||
    summaryValue.length > 8 ||
    !summaryValue.every((id) => typeof id === "string")
  )
    return null
  const summary = summaryValue as string[]
  const sections = parseSections(text.sections)
  const claims = parseClaims(text.claims)
  const priorityCases = parseCases(text.priority_cases)
  const limitations = text.limitations
  if (
    !sections ||
    !claims ||
    !priorityCases ||
    !Array.isArray(limitations) ||
    limitations.length > 32 ||
    !limitations.every(isText)
  )
    return null
  const claimIds = new Set(claims.map((claim) => claim.id))
  const pointers = [
    ...summary,
    ...sections.flatMap((section) => section.claim_ids),
  ]
  if (!pointers.every((id) => claimIds.has(id))) return null
  return {
    summary,
    sections,
    claims,
    priority_cases: priorityCases,
    limitations: limitations as string[],
  }
}

export function parseReportHistory(
  value: unknown,
  reportId: string,
): HistoryParse {
  if (!Array.isArray(value)) return invalid("history is not an array")
  const revisions = new Set<number>()
  const rowIds = new Set<string>()
  const snapshots: HistorySnapshot[] = []
  for (const entry of value) {
    const row = object(entry)
    if (!row) return invalid("history row is not an object")
    if (row.report_id !== reportId)
      return invalid("history row belongs elsewhere")
    if (typeof row.id !== "string" || !row.id)
      return invalid("history row has no identity")
    if (rowIds.has(row.id)) return invalid("duplicate history row identity")
    if (
      typeof row.revision !== "number" ||
      !Number.isSafeInteger(row.revision) ||
      row.revision < 1
    )
      return invalid("history revision is not a positive integer")
    if (revisions.has(row.revision))
      return invalid("duplicate history revision")
    const text = parseText(row.text)
    if (!text) return invalid("history text is incomplete or inconsistent")
    rowIds.add(row.id)
    revisions.add(row.revision)
    snapshots.push({
      id: row.id,
      reportId,
      revision: row.revision,
      status: typeof row.status === "string" && row.status ? row.status : null,
      actorId:
        typeof row.actor_id === "string" && row.actor_id ? row.actor_id : null,
      recordedAt:
        typeof row.recorded_at === "string" &&
        !Number.isNaN(Date.parse(row.recorded_at))
          ? row.recorded_at
          : null,
      text,
    })
  }
  snapshots.sort((left, right) => right.revision - left.revision)
  return { state: "ok", snapshots }
}

const sorted = (values: string[]) => [...values].sort()
const equalLists = (left: string[], right: string[]) =>
  JSON.stringify(left) === JSON.stringify(right)

export function sameProtectedStructure(before: V2Text, after: V2Text): boolean {
  if (!equalLists(before.summary, after.summary)) return false
  if (before.sections.length !== after.sections.length) return false
  for (const [index, section] of before.sections.entries()) {
    const next = after.sections[index]
    if (!next || section.id !== next.id) return false
    if (!equalLists(section.claim_ids, next.claim_ids)) return false
  }
  const beforeClaims = new Map(before.claims.map((claim) => [claim.id, claim]))
  const afterClaims = new Map(after.claims.map((claim) => [claim.id, claim]))
  if (beforeClaims.size !== afterClaims.size) return false
  for (const [id, claim] of beforeClaims) {
    const next = afterClaims.get(id)
    if (!next || claim.type !== next.type) return false
    const leftRefs = "fact_refs" in claim ? (claim.fact_refs ?? []) : []
    const rightRefs = "fact_refs" in next ? (next.fact_refs ?? []) : []
    if (!equalLists(sorted(leftRefs), sorted(rightRefs))) return false
    if (!equalLists(sorted(claim.evidence_refs), sorted(next.evidence_refs)))
      return false
  }
  const beforeCases = new Map(
    before.priority_cases.map((item) => [item.address_key, item]),
  )
  const afterCases = new Map(
    after.priority_cases.map((item) => [item.address_key, item]),
  )
  if (beforeCases.size !== afterCases.size) return false
  for (const [key, item] of beforeCases) {
    const next = afterCases.get(key)
    if (
      !next ||
      !equalLists(sorted(item.evidence_refs), sorted(next.evidence_refs))
    )
      return false
  }
  return equalLists(before.limitations, after.limitations)
}

export function compareHistorySnapshots(
  before: HistorySnapshot,
  after: HistorySnapshot,
): HistoryComparison {
  if (!sameProtectedStructure(before.text, after.text))
    return { kind: "structure_mismatch" }
  const beforeClaims = new Map(
    before.text.claims.map((claim) => [claim.id, claim]),
  )
  const changedClaimIds: string[] = []
  for (const claim of after.text.claims) {
    if (claim.type === "fact") continue
    const previous = beforeClaims.get(claim.id)
    if (!previous || previous.type === "fact") continue
    if (previous.text !== claim.text) changedClaimIds.push(claim.id)
  }
  const beforeCases = new Map(
    before.text.priority_cases.map((item) => [item.address_key, item]),
  )
  const changedCaseKeys: string[] = []
  for (const item of after.text.priority_cases) {
    const previous = beforeCases.get(item.address_key)
    if (
      !previous ||
      previous.why_review !== item.why_review ||
      previous.next_check !== item.next_check
    )
      changedCaseKeys.push(item.address_key)
  }
  const memberships = claimMemberships(after.text)
  const affected = new Set<string>()
  for (const id of changedClaimIds)
    for (const chapter of memberships.get(id) ?? []) affected.add(chapter)
  if (changedCaseKeys.length) affected.add("priority_cases")
  return {
    kind: "comparison",
    changedClaimIds,
    changedCaseKeys,
    affectedChapters: orderChapters(affected),
    confirmationOnly:
      before.status === "DRAFT" &&
      after.status === "CONFIRMED" &&
      changedClaimIds.length === 0 &&
      changedCaseKeys.length === 0,
    unchangedText: changedClaimIds.length === 0 && changedCaseKeys.length === 0,
  }
}
