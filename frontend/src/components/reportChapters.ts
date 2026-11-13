import type { V2Text } from "@/components/V2ReportContent"

export const chapterTitles: Record<string, [string, string]> = {
  summary: ["Report summary", "报告摘要"],
  conclusion: ["This comparison's conclusion", "本轮核对结论"],
  differences: ["Main differences and their meaning", "主要差异及业务含义"],
  priority: ["Objects to verify first", "建议核实的重点对象"],
  netflow: ["NetFlow observations and limits", "NetFlow 佐证与限制"],
  next_steps: ["Suggested next steps", "下一步建议"],
  appendix: ["Data scope and evidence", "数据范围与证据附录"],
  known_facts: ["Known facts", "已知事实"],
  possible_explanations: ["Possible explanations", "可能解释"],
  missing_evidence: ["Missing evidence", "尚缺依据"],
  next_checks: ["Suggested checks", "建议核实"],
  priority_cases: ["Suggested verification order", "建议核实顺序"],
  unplaced: ["Not placed in a chapter", "未归属章节"],
  facts: ["Fixed comparison facts", "固定核对事实"],
  address_facts: ["Fixed address facts", "固定地址事实"],
  limits: ["Data limits", "资料限制"],
  sources: ["Fixed source versions", "固定来源版本"],
}

export type ChapterGroup = {
  id: string
  title: [string, string]
  canonicalIds: string[]
  sharedIds: string[]
}

export type ChapterMembership = {
  groups: ChapterGroup[]
  canonical: Map<string, string>
  memberships: Map<string, string[]>
  summaryIds: string[]
  unplacedIds: string[]
}

const summaryGroup = "summary"
const unplacedGroup = "unplaced"

const isNarrative = (claim: V2Text["claims"][number]) => claim.type !== "fact"

const uniqueOrdered = (ids: Iterable<string>) => [...new Set(ids)]

export function claimMemberships(text: V2Text): Map<string, string[]> {
  const editable = new Set(
    text.claims.filter(isNarrative).map((claim) => claim.id),
  )
  const memberships = new Map<string, string[]>()
  for (const id of editable) memberships.set(id, [])
  for (const id of text.summary) {
    if (!editable.has(id)) continue
    const chapters = memberships.get(id)!
    if (!chapters.includes(summaryGroup)) chapters.push(summaryGroup)
  }
  for (const section of text.sections)
    for (const id of section.claim_ids)
      if (editable.has(id)) {
        const chapters = memberships.get(id)!
        if (!chapters.includes(section.id)) chapters.push(section.id)
      }
  for (const chapters of memberships.values())
    if (chapters.length === 0) chapters.push(unplacedGroup)
  return memberships
}

export function buildChapterMembership(text: V2Text): ChapterMembership {
  const editables = uniqueOrdered(
    text.claims.filter(isNarrative).map((claim) => claim.id),
  )
  const inSection = new Set(
    text.sections.flatMap((section) => section.claim_ids),
  )
  const summaryIds = uniqueOrdered(
    text.summary.filter((id) => editables.includes(id)),
  )
  const summaryOnly = summaryIds.filter((id) => !inSection.has(id))
  const unplacedIds = editables.filter(
    (id) => !inSection.has(id) && !summaryIds.includes(id),
  )
  const memberships = claimMemberships(text)
  const groupIds: Array<{ id: string; ids: string[] }> = []
  if (summaryOnly.length) groupIds.push({ id: summaryGroup, ids: summaryOnly })
  for (const section of text.sections) {
    const ids = uniqueOrdered(
      section.claim_ids.filter((id) => editables.includes(id)),
    )
    if (ids.length) groupIds.push({ id: section.id, ids })
  }
  if (unplacedIds.length) groupIds.push({ id: unplacedGroup, ids: unplacedIds })
  const canonical = new Map<string, string>()
  for (const group of groupIds)
    for (const id of group.ids)
      if (!canonical.has(id)) canonical.set(id, group.id)
  return {
    groups: groupIds.map((group) => ({
      id: group.id,
      title: chapterTitles[group.id],
      canonicalIds: group.ids.filter((id) => canonical.get(id) === group.id),
      sharedIds: group.ids.filter((id) => canonical.get(id) !== group.id),
    })),
    canonical,
    memberships,
    summaryIds,
    unplacedIds,
  }
}

export const chapterOrder = [
  summaryGroup,
  "conclusion",
  "differences",
  "priority",
  "netflow",
  "next_steps",
  "appendix",
  "known_facts",
  "possible_explanations",
  "missing_evidence",
  "next_checks",
  "priority_cases",
  unplacedGroup,
]

export function orderChapters(ids: Iterable<string>): string[] {
  const seen = new Set(ids)
  return chapterOrder.filter((id) => seen.has(id))
}
