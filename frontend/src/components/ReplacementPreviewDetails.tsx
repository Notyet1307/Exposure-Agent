import {
  type UseQueryResult,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { AlertCircle } from "lucide-react"
import { useCallback, useEffect, useId, useRef, useState } from "react"

import {
  ApiError,
  CustomerLedgerService,
  type ReplacementGroupPage,
  type ReplacementPreview,
  type ReplacementRecordPage,
  type ReplacementRequest,
} from "@/client"
import {
  CustomerRecordFields,
  customerFields,
  isDetailNumberCell,
} from "@/components/CustomerRecordFields"
import { DiagnosticDetails } from "@/components/DiagnosticDetails"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { apiErrorDetail } from "@/lib/diagnostics"
import { useI18n } from "@/lib/i18n"

const GROUP_PAGE_SIZE = 25
const RECORD_PAGE_SIZE = 10
const recognizedFields = new Set<string>(customerFields.map(([name]) => name))
const temporalKinds = new Set(["datetime", "date", "time", "timedelta"])
const uuidPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

type DetailCategory = "added" | "removed" | "changed"
type DetailSide = "current" | "candidate"

type DetailFailure =
  | { kind: "denied" }
  | { kind: "identity" }
  | { kind: "group-missing" }
  | { kind: "conflict" }

class DetailContractError extends Error {}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
}

function isPosition(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0
}

function isUuid(value: unknown): value is string {
  return typeof value === "string" && uuidPattern.test(value)
}

function isTemporal(value: unknown): boolean {
  const cell = asRecord(value)
  if (!cell) return false
  return (
    typeof cell.kind === "string" &&
    temporalKinds.has(cell.kind) &&
    typeof cell.value === "string"
  )
}

function isCellValue(value: unknown): boolean {
  return (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean" ||
    isTemporal(value) ||
    isDetailNumberCell(value)
  )
}

function expectedBasis(request: ReplacementRequest) {
  return {
    candidate_upload_id: request.candidate_upload_id,
    expected_upload_id: request.expected_upload_id ?? null,
    expected_revision_id: request.expected_revision_id ?? null,
    expected_profile_id: request.expected_profile_id,
  }
}

function basisMatches(value: unknown, request: ReplacementRequest): boolean {
  const basis = asRecord(value)
  if (!basis) return false
  const expected = expectedBasis(request)
  return (
    basis.candidate_upload_id === expected.candidate_upload_id &&
    basis.expected_upload_id === expected.expected_upload_id &&
    basis.expected_revision_id === expected.expected_revision_id &&
    basis.expected_profile_id === expected.expected_profile_id
  )
}

function pageSizeMatches(
  total: number,
  skip: number,
  limit: number,
  size: number,
): boolean {
  return size === Math.max(0, Math.min(limit, total - skip))
}

function categoryCountMatches(
  category: DetailCategory,
  currentRecords: number,
  candidateRecords: number,
): boolean {
  if (category === "added") {
    return currentRecords === 0 && candidateRecords > 0
  }
  if (category === "removed") {
    return candidateRecords === 0 && currentRecords > 0
  }
  return currentRecords > 0 && candidateRecords > 0
}

function validGroupPage(
  value: unknown,
  {
    actorId,
    projectId,
    request,
    category,
    skip,
    limit,
    expectedTotal,
  }: {
    actorId: string
    projectId: string
    request: ReplacementRequest
    category: DetailCategory
    skip: number
    limit: number
    expectedTotal: number
  },
): value is ReplacementGroupPage {
  const page = asRecord(value)
  if (!page) return false
  if (page.actor_id !== actorId || page.project_id !== projectId) return false
  if (!basisMatches(page.basis, request)) return false
  if (page.kind !== "groups" || page.category !== category) return false
  if (page.skip !== skip || page.limit !== limit) return false
  if (!isCount(page.total_groups) || page.total_groups !== expectedTotal) {
    return false
  }
  const selector = asRecord(page.selector)
  if (
    selector?.kind !== "groups" ||
    selector.category !== category ||
    selector.skip !== skip ||
    selector.limit !== limit
  ) {
    return false
  }
  if (!Array.isArray(page.groups)) return false
  if (!pageSizeMatches(page.total_groups, skip, limit, page.groups.length)) {
    return false
  }
  const seen = new Set<string>()
  for (const rawGroup of page.groups) {
    const group = asRecord(rawGroup)
    if (!group) return false
    if (typeof group.canonical_ip !== "string" || group.canonical_ip === "") {
      return false
    }
    if (seen.has(group.canonical_ip)) return false
    seen.add(group.canonical_ip)
    if (!isCount(group.current_records) || !isCount(group.candidate_records)) {
      return false
    }
    if (
      !categoryCountMatches(
        category,
        group.current_records,
        group.candidate_records,
      )
    ) {
      return false
    }
  }
  return true
}

function validRecordPage(
  value: unknown,
  {
    actorId,
    projectId,
    request,
    category,
    canonicalIp,
    side,
    skip,
    limit,
    expectedTotal,
  }: {
    actorId: string
    projectId: string
    request: ReplacementRequest
    category: DetailCategory
    canonicalIp: string
    side: DetailSide
    skip: number
    limit: number
    expectedTotal: number
  },
): value is ReplacementRecordPage {
  const page = asRecord(value)
  if (!page) return false
  if (page.actor_id !== actorId || page.project_id !== projectId) return false
  if (!basisMatches(page.basis, request)) return false
  if (
    page.kind !== "records" ||
    page.category !== category ||
    page.canonical_ip !== canonicalIp ||
    page.side !== side ||
    page.skip !== skip ||
    page.limit !== limit
  ) {
    return false
  }
  if (!isCount(page.total_records) || page.total_records !== expectedTotal) {
    return false
  }
  const selector = asRecord(page.selector)
  if (
    selector?.kind !== "records" ||
    selector.category !== category ||
    selector.canonical_ip !== canonicalIp ||
    selector.side !== side ||
    selector.skip !== skip ||
    selector.limit !== limit
  ) {
    return false
  }
  if (!Array.isArray(page.records)) return false
  if (!pageSizeMatches(page.total_records, skip, limit, page.records.length)) {
    return false
  }
  const seen = new Set<string>()
  for (const rawRecord of page.records) {
    const record = asRecord(rawRecord)
    if (!record) return false
    if (!isUuid(record.entry_id) || seen.has(record.entry_id)) return false
    seen.add(record.entry_id)
    if (!isPosition(record.position)) return false
    if (record.canonical_ip !== canonicalIp) return false
    const fields = asRecord(record.fields)
    if (!fields) return false
    for (const [name, fieldValue] of Object.entries(fields)) {
      if (!recognizedFields.has(name) || !isCellValue(fieldValue)) return false
    }
  }
  return true
}

function errorCode(error: unknown): string | null {
  const detail = apiErrorDetail(error)
  if (!detail || typeof detail !== "object" || Array.isArray(detail))
    return null
  const code = (detail as { code?: unknown }).code
  return typeof code === "string" ? code : null
}

function errorDetailMessage(error: ApiError): string | null {
  const body = error.body
  if (!body || typeof body !== "object" || Array.isArray(body)) return null
  const detail = (body as { detail?: unknown }).detail
  return typeof detail === "string" ? detail : null
}

type DetailErrorOutcome =
  | { kind: "identity" }
  | { kind: "group-missing" }
  | { kind: "conflict"; reason: "version" | "profile" }
  | { kind: "denied" }

function detailErrorOutcome(error: Error): DetailErrorOutcome | null {
  if (error instanceof DetailContractError) return { kind: "identity" }
  if (!(error instanceof ApiError)) return null
  const code = errorCode(error)
  if (error.status === 409) {
    if (code === "ledger_version_conflict")
      return { kind: "conflict", reason: "version" }
    if (code === "ledger_profile_changed")
      return { kind: "conflict", reason: "profile" }
    return null
  }
  if (error.status === 404 && code === "ledger_diff_group_not_found") {
    return { kind: "group-missing" }
  }
  if (error.status === 400 && errorDetailMessage(error) === "Inactive user") {
    return { kind: "denied" }
  }
  if ([401, 403, 404].includes(error.status)) return { kind: "denied" }
  if (error.status === 422) return { kind: "identity" }
  return null
}

function DetailPager({
  label,
  page,
  pageSize,
  total,
  onPageChange,
}: {
  label: string
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
}) {
  const { t } = useI18n()
  const previous = useRef<HTMLButtonElement>(null)
  const next = useRef<HTMLButtonElement>(null)
  const status = useRef<HTMLSpanElement>(null)
  const pendingFocus = useRef<{
    target: "previous" | "next"
    page: number
  } | null>(null)
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  const first = page * pageSize + 1
  const last = Math.min(total, first + pageSize - 1)
  useEffect(() => {
    const pending = pendingFocus.current
    if (!pending || pending.page !== page) return
    pendingFocus.current = null
    const target =
      pending.target === "previous" ? previous.current : next.current
    if (target && !target.disabled) target.focus()
    else status.current?.focus()
  }, [page])
  if (total === 0) return null
  const change = (nextPage: number) => {
    pendingFocus.current = {
      target: nextPage < page ? "previous" : "next",
      page: nextPage,
    }
    onPageChange(nextPage)
  }
  return (
    <nav
      className="flex flex-wrap items-center justify-end gap-2"
      aria-label={t(`${label} pagination`, `${label}分页`)}
    >
      {pageCount > 1 && (
        <Button
          ref={previous}
          type="button"
          size="sm"
          variant="outline"
          disabled={page === 0}
          onClick={() => change(page - 1)}
        >
          {t("Previous", "上一页")}
        </Button>
      )}
      <span
        ref={status}
        role="status"
        aria-live="polite"
        tabIndex={-1}
        className="text-sm text-muted-foreground"
      >
        {t(`${first}–${last} of ${total}`, `${first}–${last}，共 ${total} 条`)}
      </span>
      {pageCount > 1 && (
        <Button
          ref={next}
          type="button"
          size="sm"
          variant="outline"
          disabled={page + 1 >= pageCount}
          onClick={() => change(page + 1)}
        >
          {t("Next", "下一页")}
        </Button>
      )}
    </nav>
  )
}

export type ReplacementPreviewDetailsProps = {
  actorId: string
  projectId: string
  request: ReplacementRequest
  summary: ReplacementPreview
  generation: string
  onConflict: (generation: string, reason: "version" | "profile") => void
}

export function ReplacementPreviewDetails({
  actorId,
  projectId,
  request,
  summary,
  generation,
  onConflict,
}: ReplacementPreviewDetailsProps) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const panelId = useId().replace(/:/g, "")
  const [category, setCategory] = useState<DetailCategory | null>(null)
  const [groupPage, setGroupPage] = useState(0)
  const [openGroup, setOpenGroup] = useState<{
    canonicalIp: string
    currentRecords: number
    candidateRecords: number
    currentPage: number
    candidatePage: number
  } | null>(null)
  const [failure, setFailure] = useState<DetailFailure | null>(null)
  const alive = useRef(true)
  const failureHeading = useRef<HTMLDivElement>(null)
  const categoryButtons = useRef<Record<string, HTMLButtonElement | null>>({})
  const groupButtons = useRef<Record<string, HTMLButtonElement | null>>({})
  const returnCategoryFocus = useRef<DetailCategory | null>(null)
  const returnGroupFocus = useRef<string | null>(null)

  const categoryTotals: Record<DetailCategory, number> = {
    added: summary.added_ips,
    removed: summary.removed_ips,
    changed: summary.changed_ip_declarations,
  }
  const noDifference =
    categoryTotals.added === 0 &&
    categoryTotals.removed === 0 &&
    categoryTotals.changed === 0
  const firstImport = (request.expected_upload_id ?? null) === null
  const basis = expectedBasis(request)

  const clearDetailCaches = useCallback(() => {
    const prefix = ["replacement-detail", actorId, projectId, generation]
    const currentPrefix = [
      "replacement-detail-current",
      actorId,
      projectId,
      generation,
    ]
    void queryClient.cancelQueries({ queryKey: prefix })
    queryClient.removeQueries({ queryKey: prefix })
    void queryClient.cancelQueries({ queryKey: currentPrefix })
    queryClient.removeQueries({ queryKey: currentPrefix })
  }, [queryClient, actorId, projectId, generation])

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
      clearDetailCaches()
    }
  }, [clearDetailCaches])

  useEffect(() => {
    if (category !== null || returnCategoryFocus.current === null) return
    const target = returnCategoryFocus.current
    returnCategoryFocus.current = null
    categoryButtons.current[target]?.focus()
  }, [category])

  useEffect(() => {
    if (openGroup !== null || returnGroupFocus.current === null) return
    const target = returnGroupFocus.current
    returnGroupFocus.current = null
    groupButtons.current[target]?.focus()
  }, [openGroup])

  useEffect(() => {
    if (!failure) return
    failureHeading.current?.focus()
  }, [failure])

  const failClosed = useCallback(
    (kind: DetailFailure["kind"]) => {
      if (!alive.current) return
      setFailure({ kind })
      setOpenGroup(null)
      clearDetailCaches()
    },
    [clearDetailCaches],
  )

  const conflict = useCallback(
    (reason: "version" | "profile") => {
      if (!alive.current) return
      setFailure({ kind: "conflict" })
      setOpenGroup(null)
      clearDetailCaches()
      onConflict(generation, reason)
    },
    [clearDetailCaches, generation, onConflict],
  )

  const reactToError = useCallback(
    (error: Error) => {
      if (!alive.current) return
      const outcome = detailErrorOutcome(error)
      if (outcome === null) return
      if (outcome.kind === "conflict") conflict(outcome.reason)
      else failClosed(outcome.kind)
    },
    [conflict, failClosed],
  )

  const latestBasis = useQuery({
    queryKey: ["replacement-detail-current", actorId, projectId, generation],
    queryFn: async () => {
      const page = await CustomerLedgerService.readCustomerLedger({
        projectId,
        skip: 0,
        limit: 1,
      })
      if (page.project_id !== projectId) throw new DetailContractError()
      return page
    },
    retry: false,
    staleTime: 0,
    refetchOnWindowFocus: true,
  })

  useEffect(() => {
    if (!alive.current || failure !== null || !latestBasis.isSuccess) return
    const page = latestBasis.data
    if (page.current_profile_id !== request.expected_profile_id) {
      conflict("profile")
      return
    }
    if (
      (page.current_upload_id ?? null) !==
        (request.expected_upload_id ?? null) ||
      (page.current_revision_id ?? null) !==
        (request.expected_revision_id ?? null)
    ) {
      conflict("version")
    }
  }, [failure, latestBasis.data, latestBasis.isSuccess, request, conflict])

  useEffect(() => {
    if (latestBasis.error) reactToError(latestBasis.error)
  }, [latestBasis.error, reactToError])

  const groupsQuery = useQuery({
    queryKey: [
      "replacement-detail",
      actorId,
      projectId,
      generation,
      "groups",
      basis.candidate_upload_id,
      basis.expected_upload_id,
      basis.expected_revision_id,
      basis.expected_profile_id,
      category,
      groupPage,
    ],
    enabled: category !== null && failure === null,
    retry: false,
    staleTime: 0,
    queryFn: async () => {
      if (category === null) throw new DetailContractError()
      const skip = groupPage * GROUP_PAGE_SIZE
      const page =
        await CustomerLedgerService.readCustomerUploadReplacementDetails({
          projectId,
          requestBody: {
            basis,
            selector: {
              kind: "groups",
              category,
              skip,
              limit: GROUP_PAGE_SIZE,
            },
          },
        })
      if (
        !validGroupPage(page, {
          actorId,
          projectId,
          request,
          category,
          skip,
          limit: GROUP_PAGE_SIZE,
          expectedTotal: categoryTotals[category],
        })
      ) {
        throw new DetailContractError()
      }
      return page
    },
  })

  useEffect(() => {
    if (groupsQuery.error) reactToError(groupsQuery.error)
  }, [groupsQuery.error, reactToError])

  const recordQuery = (side: DetailSide) => {
    const pageNumber =
      side === "current"
        ? (openGroup?.currentPage ?? 0)
        : (openGroup?.candidatePage ?? 0)
    return {
      queryKey: [
        "replacement-detail",
        actorId,
        projectId,
        generation,
        "records",
        basis.candidate_upload_id,
        basis.expected_upload_id,
        basis.expected_revision_id,
        basis.expected_profile_id,
        category,
        openGroup?.canonicalIp ?? "",
        side,
        pageNumber,
      ],
      enabled: category !== null && openGroup !== null && failure === null,
      retry: false,
      staleTime: 0,
      queryFn: async () => {
        if (category === null || openGroup === null) {
          throw new DetailContractError()
        }
        const skip = pageNumber * RECORD_PAGE_SIZE
        const expectedTotal =
          side === "current"
            ? openGroup.currentRecords
            : openGroup.candidateRecords
        const page =
          await CustomerLedgerService.readCustomerUploadReplacementDetails({
            projectId,
            requestBody: {
              basis,
              selector: {
                kind: "records",
                category,
                canonical_ip: openGroup.canonicalIp,
                side,
                skip,
                limit: RECORD_PAGE_SIZE,
              },
            },
          })
        if (
          !validRecordPage(page, {
            actorId,
            projectId,
            request,
            category,
            canonicalIp: openGroup.canonicalIp,
            side,
            skip,
            limit: RECORD_PAGE_SIZE,
            expectedTotal,
          })
        ) {
          throw new DetailContractError()
        }
        return page
      },
    }
  }

  const currentRecords = useQuery(recordQuery("current"))
  const candidateRecords = useQuery(recordQuery("candidate"))

  useEffect(() => {
    if (currentRecords.error) reactToError(currentRecords.error)
  }, [currentRecords.error, reactToError])

  useEffect(() => {
    if (candidateRecords.error) reactToError(candidateRecords.error)
  }, [candidateRecords.error, reactToError])

  const closeCategory = () => {
    if (category !== null) returnCategoryFocus.current = category
    returnGroupFocus.current = null
    setCategory(null)
    setOpenGroup(null)
  }

  const chooseCategory = (next: DetailCategory) => {
    if (category === next) {
      closeCategory()
      return
    }
    setCategory(next)
    setGroupPage(0)
    setOpenGroup(null)
  }

  const openRecords = (group: {
    canonical_ip: string
    current_records: number
    candidate_records: number
  }) => {
    if (openGroup?.canonicalIp === group.canonical_ip) {
      returnGroupFocus.current = group.canonical_ip
      setOpenGroup(null)
      return
    }
    setOpenGroup({
      canonicalIp: group.canonical_ip,
      currentRecords: group.current_records,
      candidateRecords: group.candidate_records,
      currentPage: 0,
      candidatePage: 0,
    })
  }

  const changeGroupPage = (next: number) => {
    setGroupPage(next)
    setOpenGroup(null)
  }

  const changeRecordPage = (side: DetailSide, next: number) => {
    setOpenGroup((current) => {
      if (!current) return current
      return side === "current"
        ? { ...current, currentPage: next }
        : { ...current, candidatePage: next }
    })
  }

  const categoryLabels: Record<DetailCategory, [string, string]> = {
    added: ["Added IPs", "新增 IP"],
    removed: ["Removed IPs", "移出 IP"],
    changed: ["Changed declaration IPs", "声明变化 IP"],
  }
  const emptyCategoryCopy: Record<DetailCategory, [string, string]> = {
    added: ["No added IP groups in this preview.", "此预览没有新增 IP 分组。"],
    removed: [
      "No removed IP groups in this preview.",
      "此预览没有移出 IP 分组。",
    ],
    changed: [
      "No changed declaration IP groups in this preview.",
      "此预览没有声明变化 IP 分组。",
    ],
  }

  if (failure) {
    const copy =
      failure.kind === "denied"
        ? [
            "Detail access denied",
            "明细访问被拒绝",
            "You do not have access to these source declarations. Nothing was applied.",
            "您无权读取这些原生声明。尚未应用任何内容。",
          ]
        : failure.kind === "group-missing"
          ? [
              "Detail no longer matches the preview",
              "明细与预览不再一致",
              "This IP group is not part of the fixed preview. Nothing was applied; close this preview and read the latest version again.",
              "此 IP 分组不属于固定预览。尚未应用任何内容；请关闭预览并重新读取最新版本。",
            ]
          : failure.kind === "conflict"
            ? [
                "The current version changed",
                "当前版本已变化",
                "The fixed preview basis is no longer current. Preview the latest version again before applying.",
                "固定预览依据已非当前版本。应用前请重新预览最新版本。",
              ]
            : [
                "Detail did not match the fixed preview",
                "明细与固定预览不一致",
                "The source detail response failed its identity or total check. No detail is shown and nothing was applied.",
                "明细响应的身份或总数校验失败。未显示明细，也未应用任何内容。",
              ]
    return (
      <Alert variant="destructive" data-testid="replacement-detail-unavailable">
        <AlertCircle />
        <AlertTitle
          ref={failureHeading}
          role="heading"
          aria-level={4}
          tabIndex={-1}
          className="outline-none focus:ring-2 focus:ring-ring"
        >
          {t(copy[0], copy[1])}
        </AlertTitle>
        <AlertDescription>{t(copy[2], copy[3])}</AlertDescription>
      </Alert>
    )
  }

  const groupPageData =
    groupsQuery.data?.kind === "groups" ? groupsQuery.data : null

  return (
    <div className="min-w-0 space-y-3 border-t pt-4">
      <div className="space-y-1">
        <h3 className="text-sm font-medium">
          {t("Bounded source detail", "有界原生明细")}
        </h3>
        <p className="text-xs text-muted-foreground">
          {t(
            "Category buttons count IP units. Each IP group lists every active source declaration on each side, including duplicates; record totals are not field-change counts.",
            "分类按钮按 IP 计数。每个 IP 分组分别列出各侧全部有效原生声明（含重复项）；记录总数不是字段变化数。",
          )}
        </p>
      </div>
      {firstImport && (
        <p className="text-sm text-muted-foreground">
          {t(
            `First selection: all ${summary.candidate_record_count} candidate records across ${summary.candidate_unique_ips} IPs are reported as added IPs. Removed and changed IPs stay 0; no record is paired across files.`,
            `首次选择：候选 ${summary.candidate_record_count} 条记录、${summary.candidate_unique_ips} 个 IP 全部计为新增 IP。移出与变化 IP 保持 0；不会跨文件配对记录。`,
          )}
        </p>
      )}
      {noDifference && (
        <p role="status" className="text-sm">
          {t(
            "No added, removed or changed IP declarations in this preview.",
            "此预览没有新增、移出或声明变化的 IP。",
          )}
        </p>
      )}
      <fieldset className="m-0 min-w-0 border-0 p-0">
        <legend className="sr-only">
          {t("Difference detail categories", "差异明细分类")}
        </legend>
        <div className="flex flex-wrap gap-2">
          {(Object.keys(categoryLabels) as DetailCategory[]).map((value) => {
            const label = categoryLabels[value]
            const expanded = category === value
            return (
              <Button
                key={value}
                ref={(element) => {
                  categoryButtons.current[value] = element
                }}
                type="button"
                size="sm"
                variant={expanded ? "default" : "outline"}
                aria-expanded={expanded}
                aria-controls={expanded ? `${panelId}-groups` : undefined}
                onClick={() => chooseCategory(value)}
              >
                {t(label[0], label[1])}: {categoryTotals[value]}
              </Button>
            )
          })}
        </div>
      </fieldset>
      {category !== null && (
        <section
          id={`${panelId}-groups`}
          aria-label={t(
            `${categoryLabels[category][0]} detail`,
            `${categoryLabels[category][1]}明细`,
          )}
          className="min-w-0 space-y-3"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-medium">
              {t(
                `${categoryLabels[category][0]}: ${categoryTotals[category]} IP groups`,
                `${categoryLabels[category][1]}：${categoryTotals[category]} 个 IP 分组`,
              )}
            </p>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={closeCategory}
            >
              {t("Close details", "关闭明细")}
            </Button>
          </div>
          {groupsQuery.isPending ? (
            <p role="status" className="text-sm">
              {t("Loading IP groups…", "正在加载 IP 分组…")}
            </p>
          ) : groupsQuery.isError ? (
            <div role="status" className="space-y-2 text-sm">
              <p>
                {t(
                  "This page of IP groups could not be read. The preview and apply actions are unchanged.",
                  "无法读取此页 IP 分组。预览与应用操作保持不变。",
                )}
              </p>
              <DiagnosticDetails detail={apiErrorDetail(groupsQuery.error)} />
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => void groupsQuery.refetch()}
              >
                {t("Retry this page", "重试此页")}
              </Button>
            </div>
          ) : groupPageData && groupPageData.total_groups === 0 ? (
            <p role="status" className="text-sm text-muted-foreground">
              {t(...emptyCategoryCopy[category])}
            </p>
          ) : groupPageData ? (
            <ul className="space-y-2">
              {groupPageData.groups.map((group) => {
                const expanded = openGroup?.canonicalIp === group.canonical_ip
                const recordsId = `${panelId}-records`
                return (
                  <li
                    key={group.canonical_ip}
                    className="min-w-0 rounded-lg border p-3"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0 space-y-1">
                        <p className="break-all font-mono text-sm">
                          {group.canonical_ip}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {t(
                            `${group.current_records} current records · ${group.candidate_records} candidate records`,
                            `${group.current_records} 条当前记录 · ${group.candidate_records} 条候选记录`,
                          )}
                        </p>
                      </div>
                      <Button
                        ref={(element) => {
                          groupButtons.current[group.canonical_ip] = element
                        }}
                        type="button"
                        size="sm"
                        variant="outline"
                        aria-expanded={expanded}
                        aria-controls={expanded ? recordsId : undefined}
                        onClick={() => openRecords(group)}
                      >
                        {expanded
                          ? t("Hide source records", "收起原生记录")
                          : t("Inspect source records", "查看原生记录")}
                      </Button>
                    </div>
                    {expanded && openGroup && (
                      <SourceRecordPanel
                        id={recordsId}
                        canonicalIp={group.canonical_ip}
                        category={category}
                        openGroup={openGroup}
                        currentRecords={currentRecords}
                        candidateRecords={candidateRecords}
                        onClose={() => {
                          returnGroupFocus.current = group.canonical_ip
                          setOpenGroup(null)
                        }}
                        onPage={changeRecordPage}
                      />
                    )}
                  </li>
                )
              })}
            </ul>
          ) : null}
          {categoryTotals[category] > 0 && (
            <DetailPager
              label={t(
                `${categoryLabels[category][0]} groups`,
                `${categoryLabels[category][1]}分组`,
              )}
              page={groupPage}
              pageSize={GROUP_PAGE_SIZE}
              total={categoryTotals[category]}
              onPageChange={changeGroupPage}
            />
          )}
        </section>
      )}
    </div>
  )
}

function SourceRecordPanel({
  id,
  canonicalIp,
  category,
  openGroup,
  currentRecords,
  candidateRecords,
  onClose,
  onPage,
}: {
  id: string
  canonicalIp: string
  category: DetailCategory
  openGroup: {
    currentRecords: number
    candidateRecords: number
    currentPage: number
    candidatePage: number
  }
  currentRecords: UseQueryResult<ReplacementRecordPage, Error>
  candidateRecords: UseQueryResult<ReplacementRecordPage, Error>
  onClose: () => void
  onPage: (side: DetailSide, page: number) => void
}) {
  const { t } = useI18n()
  return (
    <section
      id={id}
      aria-label={t(
        `Source records for ${canonicalIp}`,
        `${canonicalIp} 的原生记录`,
      )}
      className="mt-3 min-w-0 space-y-4 border-t pt-3"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <p className="break-all font-mono text-sm">{canonicalIp}</p>
          <p className="text-xs text-muted-foreground">
            {t(
              "Records from different files cannot be reliably matched. Current and candidate sections list each file's declarations independently; similar positions or the same IP do not imply correspondence.",
              "不同文件的记录无法可靠配对。当前与候选部分独立列出各自文件的声明；位置相近或 IP 相同都不代表互相对应。",
            )}
          </p>
          <p className="text-xs text-muted-foreground">
            {t(
              "Each card is one source declaration in that file, not an asset. Duplicate declarations remain separate. A side's total counts every active declaration on that side, including unchanged ones.",
              "每张卡片是该文件的一条原生声明，不是资产。重复声明保持独立。单侧总数计入该侧全部有效声明，包括未变化声明。",
            )}
          </p>
        </div>
        <Button type="button" size="sm" variant="ghost" onClick={onClose}>
          {t("Close records", "关闭记录")}
        </Button>
      </div>
      <div className="space-y-5">
        <RecordSide
          side="current"
          category={category}
          expectedTotal={openGroup.currentRecords}
          page={openGroup.currentPage}
          query={currentRecords}
          onPage={onPage}
        />
        <RecordSide
          side="candidate"
          category={category}
          expectedTotal={openGroup.candidateRecords}
          page={openGroup.candidatePage}
          query={candidateRecords}
          onPage={onPage}
        />
      </div>
    </section>
  )
}

function RecordSide({
  side,
  category,
  expectedTotal,
  page,
  query,
  onPage,
}: {
  side: DetailSide
  category: DetailCategory
  expectedTotal: number
  page: number
  query: UseQueryResult<ReplacementRecordPage, Error>
  onPage: (side: DetailSide, page: number) => void
}) {
  const { t } = useI18n()
  const heading = useId()
  const sideLabel =
    side === "current"
      ? [t("Current source declarations", "当前原生声明"), "current"]
      : [t("Candidate source declarations", "候选原生声明"), "candidate"]
  const data =
    query.data?.kind === "records" && query.data.side === side
      ? query.data
      : null
  return (
    <section
      aria-labelledby={heading}
      className="min-w-0 space-y-2 border-t pt-3 first:border-t-0 first:pt-0"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h5 id={heading} className="text-sm font-medium">
          {sideLabel[0]}
        </h5>
        <p className="text-xs text-muted-foreground">
          {t(
            `${expectedTotal} records in this side`,
            `此侧共 ${expectedTotal} 条记录`,
          )}
        </p>
      </div>
      {query.isPending ? (
        <p role="status" className="text-sm">
          {t(
            `Loading ${sideLabel[1]} source declarations…`,
            `正在加载${side === "current" ? "当前" : "候选"}原生声明…`,
          )}
        </p>
      ) : query.isError ? (
        <div role="status" className="space-y-2 text-sm">
          <p>
            {t(
              `This page of ${sideLabel[1]} source declarations could not be read. The preview and apply actions are unchanged.`,
              `无法读取此页${
                side === "current" ? "当前" : "候选"
              }原生声明。预览与应用操作保持不变。`,
            )}
          </p>
          <DiagnosticDetails detail={apiErrorDetail(query.error)} />
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => void query.refetch()}
          >
            {t("Retry this page", "重试此页")}
          </Button>
        </div>
      ) : expectedTotal === 0 ? (
        <p className="text-sm text-muted-foreground">
          {t(
            `No ${sideLabel[1]} source declarations for this IP in this preview.`,
            `此预览中该 IP 没有${
              side === "current" ? "当前" : "候选"
            }原生声明。`,
          )}
        </p>
      ) : data ? (
        <ul className="space-y-3">
          {data.records.map((record) => (
            <li key={record.entry_id} className="min-w-0 rounded-lg border p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-sm font-medium">
                  {t(
                    `Source declaration ${record.position}`,
                    `原生声明 ${record.position}`,
                  )}
                </p>
                <code className="break-all text-xs text-muted-foreground">
                  {t("Record ID", "记录 ID")}: {record.entry_id}
                </code>
              </div>
              <p className="mb-2 text-xs text-muted-foreground">
                {t(
                  "Position and record ID are local to this file only.",
                  "位置与记录 ID 仅在本文件内有效。",
                )}
              </p>
              <CustomerRecordFields fields={record.fields} exact />
            </li>
          ))}
        </ul>
      ) : null}
      {expectedTotal > 0 && (
        <DetailPager
          label={t(
            `${side === "current" ? "Current" : "Candidate"} source records`,
            `${side === "current" ? "当前" : "候选"}原生记录`,
          )}
          page={page}
          pageSize={RECORD_PAGE_SIZE}
          total={expectedTotal}
          onPageChange={(next) => onPage(side, next)}
        />
      )}
      <p className="text-xs text-muted-foreground">
        {t(
          `Category: ${category}. Page ${page + 1} shows at most ${RECORD_PAGE_SIZE} complete records for this side.`,
          `分类：${category}。第 ${page + 1} 页最多显示此侧 ${RECORD_PAGE_SIZE} 条完整记录。`,
        )}
      </p>
    </section>
  )
}
