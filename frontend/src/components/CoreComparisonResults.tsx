import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  ComparisonResultsService as API,
  ApiError,
  NetflowProcessingService,
} from "@/client"
import { ResultPagination } from "@/components/ResultPagination"
import { TechnicalValue } from "@/components/TechnicalValue"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  type ComparisonClass,
  type ComparisonReturn,
  comparisonClasses,
  comparisonUuid,
} from "@/lib/comparisonReturn"
import { useI18n } from "@/lib/i18n"
import { requestDigest } from "@/lib/ledgerIntent"

const SIZE = 25
// Browsers cap one timer at about 24.8 days; recheck long explicit cutoffs.
function expireAt(deadline: number, onExpire: () => void) {
  let timer: ReturnType<typeof setTimeout> | undefined
  const check = () => {
    const remaining = deadline - Date.now()
    if (remaining <= 0) onExpire()
    else timer = setTimeout(check, Math.min(remaining, 2147483647))
  }
  check()
  return () => clearTimeout(timer)
}
type Summary = Awaited<ReturnType<typeof API.summary>>
type Ready = Awaited<ReturnType<typeof API.readiness>>
type Creation = Parameters<typeof API.create>[0]["requestBody"]
type Binding = Parameters<typeof API.bindSupplement>[0]["requestBody"]
type Result = Awaited<ReturnType<typeof API.create>>
type Pending = {
  key: string
  digest: string
  action: "create" | "bind"
  result?: string
  needsEvidence: boolean
  body: Creation | Binding
}

export type CoreComparisonSearch = {
  result?: string
  binding?: string
  scope?: string
  core_history?: boolean
  core_class?: ComparisonClass
  core_page?: number
  core_ip?: string
  core_sort?: "ip_asc" | "ip_desc"
  core_address?: string
  core_evidence?: "customer" | "cloud"
  core_evidence_page?: number
  core_extra_page?: number
  core_history_page?: number
  core_invalid?: boolean
  core_filter_invalid?: boolean
  legacy?: boolean
}

export function coreComparisonSearch(
  s: Record<string, unknown>,
): CoreComparisonSearch {
  let invalid = false
  let badFilter = false
  const id = (name: string, none = false) => {
    if (s[name] === undefined) return undefined
    if (none && s[name] === "none") return "none"
    if (typeof s[name] !== "string" || !comparisonUuid.test(s[name])) {
      invalid = true
      return undefined
    }
    return s[name].toLowerCase()
  }
  const page = (name: string) => {
    if (s[name] === undefined) return 0
    if (
      !/^(0|[1-9][0-9]*)$/.test(String(s[name])) ||
      !Number.isSafeInteger(Number(s[name])) ||
      Number(s[name]) > Math.floor(Number.MAX_SAFE_INTEGER / SIZE)
    ) {
      badFilter = true
      return 0
    }
    return Number(s[name])
  }
  const result = id("result"),
    binding = id("binding", true)
  if (s.binding !== undefined && s.result === undefined) invalid = true
  if (
    s.scope !== undefined &&
    (typeof s.scope !== "string" || !/^[a-f0-9]{64}$/.test(s.scope))
  )
    invalid = true
  if (
    s.core_class !== undefined &&
    !comparisonClasses.includes(s.core_class as ComparisonClass)
  )
    badFilter = true
  if (
    s.core_ip !== undefined &&
    (typeof s.core_ip !== "string" || s.core_ip.length > 45)
  )
    badFilter = true
  if (
    s.core_address !== undefined &&
    (typeof s.core_address !== "string" ||
      !/^addr:[a-f0-9]{64}$/.test(s.core_address))
  )
    invalid = true
  return {
    result,
    binding,
    scope: typeof s.scope === "string" ? s.scope : undefined,
    core_history: s.core_history === true || s.core_history === "true",
    core_class: comparisonClasses.includes(s.core_class as ComparisonClass)
      ? (s.core_class as ComparisonClass)
      : "all",
    core_page: page("core_page"),
    core_history_page: page("core_history_page"),
    core_extra_page: page("core_extra_page"),
    core_evidence_page: page("core_evidence_page"),
    core_ip: typeof s.core_ip === "string" ? s.core_ip : undefined,
    core_sort: s.core_sort === "ip_desc" ? "ip_desc" : "ip_asc",
    core_address:
      typeof s.core_address === "string" ? s.core_address : undefined,
    core_evidence: s.core_evidence === "cloud" ? "cloud" : "customer",
    core_invalid: invalid,
    core_filter_invalid: badFilter,
    legacy: s.legacy === true || s.legacy === "true",
  }
}

const object = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
const code = (error: unknown) =>
  error instanceof ApiError
    ? String(object(object(error.body).detail).code ?? error.status)
    : "read_failed"

export default function CoreComparisonResults({
  actor,
  projectId,
  search,
  navigate,
}: {
  actor: string
  projectId: string
  search: CoreComparisonSearch
  navigate: (options: {
    search: (previous: CoreComparisonSearch) => CoreComparisonSearch
    replace?: boolean
  }) => Promise<void>
}) {
  const { t, formatDate } = useI18n()
  const cache = useQueryClient()
  const prefix = useMemo(
    () => [
      "core-comparison",
      actor,
      projectId,
      search.result ?? "current",
      search.scope ?? "default",
    ],
    [actor, projectId, search.result, search.scope],
  )
  const ePrefix = useMemo(
    () => [
      "core-supplement-content",
      actor,
      projectId,
      search.result,
      search.binding,
    ],
    [actor, projectId, search.result, search.binding],
  )
  const alive = useRef(true)
  const [denied, setDenied] = useState(false)
  const [ip, setIp] = useState(search.core_ip ?? "")
  const [composer, setComposer] = useState(false)
  const [source, setSource] = useState<string>()
  const [namespace, setNamespace] = useState("")
  const [scopeEvidence, setScopeEvidence] = useState("")
  const [notice, setNotice] = useState("")
  const [busy, setBusy] = useState(false)
  const submitting = useRef(false)
  const [expiredBinding, setExpiredBinding] = useState<string>()
  const [unreadableBinding, setUnreadableBinding] = useState<string>()
  const [expiredCore, setExpiredCore] = useState(false)
  const [attach, setAttach] = useState(false)
  const [flowScope, setFlowScope] = useState<string>()
  const [validUntil, setValidUntil] = useState("")
  const [bindingEvidence, setBindingEvidence] = useState("")
  const [canReplay, setCanReplay] = useState(false)
  const [showBindingHistory, setShowBindingHistory] = useState(false)
  const [bindingHistoryPage, setBindingHistoryPage] = useState(0)
  const detailHeading = useRef<HTMLHeadingElement>(null)
  const lastAddressTrigger = useRef<HTMLButtonElement | null>(null)
  const store = `exposure:comparison:${actor}:${projectId}:${search.result ?? search.scope ?? "current"}`
  const [pending, setPending] = useState<Pending | null>(() => {
    try {
      const value = JSON.parse(
        sessionStorage.getItem(store) ?? "null",
      ) as Pending | null
      return value &&
        /^[A-Za-z0-9_-]{1,128}$/.test(value.key) &&
        /^[a-f0-9]{64}$/.test(value.digest) &&
        ["create", "bind"].includes(value.action) &&
        value.body &&
        typeof value.body === "object"
        ? value
        : null
    } catch {
      return null
    }
  })
  const [recoveryEvidence, setRecoveryEvidence] = useState("")
  const change = useCallback(
    (patch: Partial<CoreComparisonSearch>) =>
      void navigate({ search: (previous) => ({ ...previous, ...patch }) }),
    [navigate],
  )
  const fixed = useCallback(
    (id: string, binding?: string) =>
      void navigate({
        search: () => ({
          result: id,
          binding,
          core_class: "all",
          core_page: 0,
        }),
        replace: true,
      }),
    [navigate],
  )
  const date = (value: unknown) =>
    typeof value === "string" ? formatDate(value) : t("Not provided", "未提供")
  useEffect(() => {
    setIp(search.core_ip ?? "")
  }, [search.core_ip])
  useEffect(() => {
    document.title = t("Comparison results - Exposure", "比对结果 - Exposure")
  }, [t])
  useEffect(() => {
    alive.current = true
    const refresh = () => {
      if (document.visibilityState === "visible")
        void cache.invalidateQueries({ queryKey: prefix })
    }
    document.addEventListener("visibilitychange", refresh)
    return () => {
      alive.current = false
      document.removeEventListener("visibilitychange", refresh)
      void cache.cancelQueries({ queryKey: prefix })
      cache.removeQueries({ queryKey: prefix })
    }
  }, [cache, prefix])
  useEffect(
    () => () => {
      void cache.cancelQueries({ queryKey: ePrefix })
      cache.removeQueries({ queryKey: ePrefix })
    },
    [cache, ePrefix],
  )
  const options = {
    retry: false,
    staleTime: 0,
    gcTime: 0,
    refetchOnWindowFocus: true,
  }
  const enabled = !denied && !search.core_invalid && !expiredCore
  const verify = <T extends { project_id: string; contract_version?: string }>(
    value: T,
  ) => {
    if (
      value.project_id !== projectId ||
      value.contract_version !== "core-comparison-v2"
    )
      throw new Error("comparison_identity_mismatch")
    return value
  }
  const current = useQuery({
    ...options,
    queryKey: [...prefix, "current"],
    enabled: enabled && !search.result && !search.core_history && !pending,
    queryFn: async () =>
      verify(await API.current({ projectId, scopeKey: search.scope })),
  })
  useEffect(() => {
    const found = current.data?.result
    if (
      !search.result &&
      !search.core_history &&
      !pending &&
      !search.core_invalid &&
      !current.isError &&
      found
    ) {
      if (found.project_id !== projectId) return
      fixed(found.id)
    }
  }, [
    current.data,
    current.isError,
    pending,
    search.result,
    search.core_history,
    search.core_invalid,
    projectId,
    fixed,
  ])
  const summary = useQuery({
    ...options,
    queryKey: [...prefix, "summary"],
    enabled: enabled && !!search.result,
    refetchInterval: 10000,
    queryFn: async () => {
      const value = verify(
        await API.summary({ projectId, resultId: search.result! }),
      )
      if (
        value.id !== search.result ||
        !value.selection.customer ||
        value.selection.netflow !== null ||
        value.selection.cloud?.kind !== "external_versions"
      )
        throw new Error("comparison_identity_mismatch")
      return value
    },
  })
  const readable =
    enabled && summary.isSuccess && !summary.isError && !!summary.data
  const result = readable ? summary.data : undefined
  const updates = useQuery({
    ...options,
    queryKey: [...prefix, "updates"],
    enabled: readable,
    refetchInterval: 10000,
    queryFn: async () => {
      const value = verify(
        await API.updates({ projectId, resultId: search.result! }),
      )
      if (value.result_id !== search.result)
        throw new Error("comparison_identity_mismatch")
      return value
    },
  })
  const rows = useQuery({
    ...options,
    queryKey: [
      ...prefix,
      "addresses",
      search.core_class,
      search.core_page,
      search.core_ip,
      search.core_sort,
    ],
    enabled: readable && !search.core_filter_invalid,
    queryFn: async () => {
      const value = verify(
        await API.addresses({
          projectId,
          resultId: search.result!,
          classification: search.core_class,
          ip: search.core_ip || undefined,
          skip: (search.core_page ?? 0) * SIZE,
          limit: SIZE,
          sort: search.core_sort,
        }),
      )
      if (value.result_id !== search.result)
        throw new Error("comparison_identity_mismatch")
      return value
    },
  })
  const proof = useQuery({
    ...options,
    queryKey: [
      ...prefix,
      "evidence",
      search.core_address,
      search.core_evidence,
      search.core_evidence_page,
    ],
    enabled: readable && !!search.core_address,
    queryFn: async () => {
      const value = verify(
        await API.evidence({
          projectId,
          resultId: search.result!,
          addressKey: search.core_address!,
          source: search.core_evidence ?? "customer",
          skip: (search.core_evidence_page ?? 0) * SIZE,
          limit: SIZE,
        }),
      )
      if (
        value.result_id !== search.result ||
        value.address_key !== search.core_address ||
        value.source !== (search.core_evidence ?? "customer")
      )
        throw new Error("comparison_identity_mismatch")
      return value
    },
  })
  const detail = useQuery({
    ...options,
    queryKey: [...prefix, "address-detail", search.core_address],
    enabled: readable && !!search.core_address,
    queryFn: async () => {
      const value = verify(
        await API.addressDetail({
          projectId,
          resultId: search.result!,
          addressKey: search.core_address!,
        }),
      )
      if (
        value.result_id !== search.result ||
        value.address.address_key !== search.core_address
      )
        throw new Error("comparison_identity_mismatch")
      return value
    },
  })
  useEffect(() => {
    if (detail.isSuccess && !detail.isError) detailHeading.current?.focus()
  }, [detail.isSuccess, detail.isError])
  const history = useQuery({
    ...options,
    queryKey: [...prefix, "history", search.core_history_page],
    enabled: enabled && search.core_history === true,
    queryFn: async () =>
      verify(
        await API.history({
          projectId,
          scopeKey: result?.scope_key ?? search.scope,
          skip: (search.core_history_page ?? 0) * SIZE,
          limit: SIZE,
        }),
      ),
  })
  const readiness = useQuery({
    ...options,
    refetchOnWindowFocus: false,
    queryKey: [...prefix, "prepare", source, namespace],
    enabled:
      enabled &&
      composer &&
      (!namespace || /^[a-z][a-z0-9_-]{0,63}$/.test(namespace)),
    queryFn: async () =>
      verify(
        await API.readiness({
          projectId,
          resultId: search.result,
          sourceInstanceId: source,
          networkNamespace: namespace || undefined,
        }),
      ),
  })
  const ready = readiness.isError ? undefined : readiness.data
  const statusReady = updates.data?.readiness ?? current.data?.readiness
  const error = [summary, rows, proof, detail].find(
    (query) => query.isError,
  )?.error
  useEffect(() => {
    if (
      error instanceof ApiError &&
      [401, 403, 404, 410].includes(error.status) &&
      code(error) !== "comparison_address_not_found"
    ) {
      setDenied(true)
      setComposer(false)
      setAttach(false)
      setPending(null)
      sessionStorage.removeItem(store)
      void cache.cancelQueries({ queryKey: prefix })
      cache.removeQueries({ queryKey: prefix })
      void cache.cancelQueries({ queryKey: ePrefix })
      cache.removeQueries({ queryKey: ePrefix })
    }
  }, [error, cache, prefix, ePrefix, store])
  const coreDeadline = result
    ? Math.min(
        ...Object.values(object(object(result.pins.CLOUD).domains))
          .map((value) => Date.parse(String(object(value).retain_until)))
          .filter(Number.isFinite),
      )
    : Number.POSITIVE_INFINITY
  useEffect(() => {
    if (!Number.isFinite(coreDeadline)) return
    return expireAt(coreDeadline, () => {
      setExpiredCore(true)
      void cache.cancelQueries({ queryKey: prefix })
      cache.removeQueries({ queryKey: prefix })
      void cache.cancelQueries({ queryKey: ePrefix })
      cache.removeQueries({ queryKey: ePrefix })
    })
  }, [coreDeadline, cache, prefix, ePrefix])
  const eMeta = useQuery({
    ...options,
    queryKey: [...prefix, "supplement", search.binding],
    enabled: readable && search.binding !== "none",
    refetchInterval: 5000,
    queryFn: async () => {
      const value = verify(
        await (search.binding
          ? API.fixedSupplement({
              projectId,
              resultId: search.result!,
              bindingId: search.binding,
            })
          : API.currentSupplement({ projectId, resultId: search.result! })),
      )
      if (
        value.result_id !== search.result ||
        (search.binding && value.id !== search.binding)
      )
        throw new Error("supplement_identity_mismatch")
      return value
    },
  })
  useEffect(() => {
    if (readable && !search.binding && eMeta.isSuccess && !eMeta.isError)
      change({ binding: eMeta.data.id ?? "none" })
  }, [
    readable,
    search.binding,
    eMeta.isSuccess,
    eMeta.isError,
    eMeta.data,
    change,
  ])
  const eReadable =
    readable &&
    !!search.binding &&
    search.binding !== "none" &&
    eMeta.isSuccess &&
    !eMeta.isError &&
    eMeta.data.state === "ACTIVE" &&
    expiredBinding !== search.binding &&
    unreadableBinding !== search.binding
  useEffect(() => {
    const deadline = eMeta.data?.valid_until,
      id = eMeta.data?.id
    if (!deadline || !id) return
    return expireAt(Date.parse(deadline) + 10, () => {
      setExpiredBinding(id)
      void cache.cancelQueries({ queryKey: ePrefix })
      cache.removeQueries({ queryKey: ePrefix })
      void eMeta.refetch()
    })
  }, [eMeta.data?.valid_until, eMeta.data?.id, cache, ePrefix, eMeta.refetch])
  useEffect(() => {
    if (!eReadable) {
      void cache.cancelQueries({ queryKey: ePrefix })
      cache.removeQueries({ queryKey: ePrefix })
    }
  }, [eReadable, cache, ePrefix])
  const flows = useQuery({
    ...options,
    queryKey: [
      ...ePrefix,
      "annotations",
      rows.data?.data.map((row) => row.canonical_ip),
    ],
    enabled:
      eReadable && rows.isSuccess && !rows.isError && !!rows.data.data.length,
    queryFn: async () => {
      const value = verify(
        await API.supplementAddresses({
          projectId,
          resultId: search.result!,
          bindingId: search.binding!,
          ip: rows.data!.data.map((row) => row.canonical_ip),
          limit: 100,
        }),
      )
      if (
        value.result_id !== search.result ||
        value.binding_id !== search.binding
      )
        throw new Error("supplement_identity_mismatch")
      return value
    },
  })
  const extra = useQuery({
    ...options,
    queryKey: [...ePrefix, "extra", search.core_extra_page],
    enabled: eReadable,
    queryFn: async () => {
      const value = verify(
        await API.supplementAddresses({
          projectId,
          resultId: search.result!,
          bindingId: search.binding!,
          onlySupplemental: true,
          skip: (search.core_extra_page ?? 0) * SIZE,
          limit: SIZE,
        }),
      )
      if (
        value.result_id !== search.result ||
        value.binding_id !== search.binding
      )
        throw new Error("supplement_identity_mismatch")
      return value
    },
  })
  const evidenceError = flows.isError || extra.isError
  useEffect(() => {
    if (evidenceError && search.binding) {
      setUnreadableBinding(search.binding)
      void cache.cancelQueries({ queryKey: ePrefix })
      cache.removeQueries({ queryKey: ePrefix })
    }
  }, [evidenceError, search.binding, cache, ePrefix])
  const currentFlow = useQuery({
    ...options,
    queryKey: [...prefix, "attach-current-flow", flowScope],
    enabled: readable && attach,
    queryFn: () =>
      NetflowProcessingService.readCurrentNetflow({
        projectId,
        collectionScope: flowScope,
      }),
  })
  const bindingHistory = useQuery({
    ...options,
    queryKey: [...prefix, "binding-history", bindingHistoryPage],
    enabled: readable && showBindingHistory,
    queryFn: async () => {
      const value = verify(
        await API.supplementHistory({
          projectId,
          resultId: search.result!,
          skip: bindingHistoryPage * SIZE,
          limit: SIZE,
        }),
      )
      if (value.result_id !== search.result)
        throw new Error("supplement_identity_mismatch")
      return value
    },
  })
  const back: ComparisonReturn = search.result
    ? {
        back_result: search.result,
        back_binding: search.binding,
        back_class: search.core_class,
        back_page: search.core_page,
        back_ip: search.core_ip,
        back_sort: search.core_sort,
        back_address: search.core_address,
        back_evidence: search.core_evidence,
        back_evidence_page: search.core_evidence_page,
        back_extra_page: search.core_extra_page,
      }
    : {}
  const classes: Record<ComparisonClass, string> = {
    all: t("All addresses", "全部地址"),
    both: t("Recorded on both sides", "双方都有记录"),
    cloud_only: t(
      "CloudAtlas record, not registered in this customer version",
      "云图有记录、客户本版未登记",
    ),
    customer_only: t(
      "Customer record, not observed in this CloudAtlas batch",
      "客户有记录、云图本批未观测",
    ),
  }
  const clearPending = () => {
    sessionStorage.removeItem(store)
    setPending(null)
    setCanReplay(false)
    setRecoveryEvidence("")
  }
  const errorText = (failure: unknown) => {
    const value = code(failure)
    if (
      value === "comparison_publish_conflict" ||
      value === "comparison_input_conflict"
    )
      return t(
        "The inputs or current publication changed. The old result is unchanged; read the current materials and confirm again.",
        "当前资料或发布版本已变化。旧结果保持不变，请重新读取资料并确认。",
      )
    if (value === "comparison_scope_confirmation_required")
      return t(
        "An administrator must confirm these exact input versions belong to the same comparison scope.",
        "需要管理员确认这些明确版本属于同一比对范围。",
      )
    if (value === "comparison_supplement_conflict")
      return t(
        "The evidence binding changed. Read and explicitly select its current version before updating.",
        "辅证绑定已变化，请读取并明确选择当前绑定后再更新。",
      )
    if (failure instanceof ApiError && failure.status === 410)
      return t(
        "This fixed material has expired. No other version was substituted.",
        "该固定资料已到期，未替换为其他版本。",
      )
    return t(
      "The operation could not be confirmed. Its original identity is retained for recovery.",
      "尚无法确认操作结果，已保留原标识用于恢复。",
    )
  }
  const checkResult = async (value: Result, body: Creation) => {
    verify(value)
    if (
      value.input_sha256 !== body.expected_input_sha256 ||
      value.purpose !== (body.purpose ?? "regular") ||
      (await requestDigest(value.selection)) !==
        (await requestDigest(body.selection))
    )
      throw new Error("comparison_identity_mismatch")
    return value
  }
  const send = async (intent: Pending, body: Creation | Binding) => {
    if (intent.action === "create") {
      const saved = await checkResult(
        await API.create({
          projectId,
          idempotencyKey: intent.key,
          requestBody: body as Creation,
        }),
        body as Creation,
      )
      if (!alive.current) return
      clearPending()
      setComposer(false)
      fixed(saved.id)
    } else {
      const saved = verify(
        await API.bindSupplement({
          projectId,
          resultId: intent.result!,
          idempotencyKey: intent.key,
          requestBody: body as Binding,
        }),
      )
      if (saved.result_id !== intent.result || !saved.id)
        throw new Error("supplement_identity_mismatch")
      if (!alive.current) return
      clearPending()
      setAttach(false)
      setNotice(
        t(
          "Saved a new evidence binding. The core classification and counts are unchanged.",
          "已保存新的辅证绑定，核心分类与计数保持不变。",
        ),
      )
      change({ binding: saved.id, core_extra_page: 0 })
    }
  }
  const perform = async (
    action: "create" | "bind",
    body: Creation | Binding,
  ) => {
    if (submitting.current || pending || !enabled) return
    submitting.current = true
    setBusy(true)
    setNotice("")
    try {
      const intent: Pending = {
        key: crypto.randomUUID(),
        action,
        result: search.result,
        needsEvidence: !!body.scope_evidence,
        body: { ...body, scope_evidence: null },
        digest: await requestDigest(body),
      }
      if (!alive.current) return
      sessionStorage.setItem(store, JSON.stringify(intent))
      setPending(intent)
      setCanReplay(false)
      await send(intent, body)
    } catch (failure) {
      if (!alive.current) return
      if (
        failure instanceof ApiError &&
        [400, 401, 403, 404, 409, 422].includes(failure.status)
      )
        clearPending()
      setNotice(errorText(failure))
    } finally {
      submitting.current = false
      if (alive.current) setBusy(false)
    }
  }
  const recover = async (replay = false) => {
    if (!pending || submitting.current) return
    const captured = pending
    submitting.current = true
    setBusy(true)
    setCanReplay(false)
    try {
      if (replay) {
        const body = {
          ...captured.body,
          scope_evidence: captured.needsEvidence
            ? recoveryEvidence.trim()
            : null,
        }
        if ((await requestDigest(body)) !== captured.digest) {
          setNotice(
            t(
              "Re-enter the original confirmation text. This request must match the saved operation exactly.",
              "请重新填写原确认依据，本次请求必须与原操作完全一致。",
            ),
          )
          setCanReplay(true)
          return
        }
        await send(captured, body)
      } else if (captured.action === "create") {
        const operation = verify(
          await API.operation({ projectId, key: captured.key }),
        )
        if (!alive.current) return
        if (operation.status === "FAILED") {
          clearPending()
          setNotice(
            t(
              "The original update was rejected. The prior successful result is unchanged.",
              "原更新请求已被拒绝，之前的成功结果保持不变。",
            ),
          )
          return
        }
        if (!operation.result) throw new Error("comparison_identity_mismatch")
        const saved = await checkResult(
          operation.result,
          captured.body as Creation,
        )
        if (alive.current) {
          clearPending()
          fixed(saved.id)
        }
      } else {
        const saved = verify(
          await API.supplementOperation({
            projectId,
            resultId: captured.result!,
            key: captured.key,
          }),
        )
        if (saved.result_id !== captured.result || !saved.id)
          throw new Error("supplement_identity_mismatch")
        if (alive.current) {
          clearPending()
          change({ binding: saved.id })
        }
      }
    } catch (failure) {
      if (alive.current) {
        setCanReplay(failure instanceof ApiError && failure.status === 404)
        setNotice(
          failure instanceof ApiError && failure.status === 404
            ? t(
                "No completed receipt is available yet. You may resend the exact original request with its original identity.",
                "尚无完成回执，可以复用原标识明确提交完全相同的请求。",
              )
            : errorText(failure),
        )
      }
    } finally {
      submitting.current = false
      if (alive.current) setBusy(false)
    }
  }
  const generate = () => {
    if (!ready?.can_generate || !ready.selection || !ready.input_sha256) return
    if (!ready.scope_confirmation_id && !scopeEvidence.trim()) {
      setNotice(
        t(
          "Enter the same-space confirmation evidence first.",
          "请先填写同空间确认依据。",
        ),
      )
      return
    }
    void perform("create", {
      selection: ready.selection,
      scope_confirmation_id: ready.scope_confirmation_id,
      scope_evidence: ready.scope_confirmation_id ? null : scopeEvidence.trim(),
      purpose: "regular",
      expected_input_sha256: ready.input_sha256,
      expected_current_result_id: ready.expected_current_result_id,
    })
  }
  const attachEvidence = () => {
    const flow = currentFlow.data?.current
    if (
      !result ||
      !flow ||
      flow.project_id !== projectId ||
      flow.network_namespace !== result.selection.network_namespace ||
      !validUntil ||
      !bindingEvidence.trim()
    )
      return
    const until = new Date(validUntil)
    if (!Number.isFinite(until.getTime()) || until.getTime() <= Date.now()) {
      setNotice(
        t("Choose a future evidence cutoff.", "请明确选择未来的辅证截止时间。"),
      )
      return
    }
    void perform("bind", {
      analysis_id: flow.analysis_id,
      expected_binding_id: search.binding === "none" ? null : search.binding,
      qualification_confirmation_id: null,
      scope_evidence: bindingEvidence.trim(),
      valid_until: until.toISOString(),
    })
  }
  const readinessText = (state: Ready["state"] | undefined) => {
    const labels: Record<string, [string, string]> = {
      READY: [
        "The applied customer register and published CloudAtlas data are ready.",
        "已应用客户台账和已发布云图资料可用于生成结果。",
      ],
      SCOPE_REQUIRED: [
        "Confirm the network namespace and comparable scope for these materials.",
        "请确认这些资料的网络空间与可比范围。",
      ],
      SCOPE_CONFIRMATION_REQUIRED: [
        "These exact input versions need a same-space confirmation.",
        "这些明确版本需要同空间确认。",
      ],
      CUSTOMER_NOT_READY: [
        "Apply a customer register version first.",
        "请先明确应用客户资产台账版本。",
      ],
      CLOUD_NOT_READY: [
        "This scope has no published, readable CloudAtlas IP/port data.",
        "此范围尚无已发布且可读的云图 IP／端口资料。",
      ],
      INSUFFICIENT_COVERAGE: [
        "Coverage is incomplete. Known records can be read, but full-scope difference statistics are unavailable.",
        "覆盖不足。可阅读已知记录，但不能提供全范围差异统计。",
      ],
      EXPIRED: [
        "The required data has expired. Prepare an authorized published version explicitly.",
        "所需资料已到期，请明确准备获准的已发布版本。",
      ],
      ACCESS_DENIED: [
        "Data access is denied. The result is not an empty set.",
        "资料读取被拒绝，不能将其视为空集。",
      ],
      READ_FAILED: [
        "The data could not be read. Check its fixed version and retry.",
        "无法读取资料，请核对固定版本后重试。",
      ],
      MULTIPLE_SCOPES: [
        "Choose one comparable source or scope.",
        "请选择一个可比的来源或范围。",
      ],
      METADATA_UNAVAILABLE: [
        "Update status could not be confirmed. This does not change the fixed result.",
        "暂无法确认资料更新状态，固定结果保持不变。",
      ],
    }
    return state && labels[state]
      ? t(...labels[state])
      : t("Reading material status…", "正在读取资料状态…")
  }
  const materialLinks = (value: Summary | Result) => {
    const customer = value.selection.customer,
      cloud = value.selection.cloud
    const version =
      cloud?.kind === "external_versions"
        ? (cloud.ip_version_id ?? cloud.port_version_id)
        : undefined
    return (
      <div className="flex flex-wrap gap-3 text-sm">
        {customer && (
          <Link
            className="underline"
            to="/projects/$projectId/customer-ledger"
            params={{ projectId }}
            search={{
              ...back,
              ledger_upload: customer.upload_id,
              ledger_revision: customer.revision_id ?? undefined,
              ledger_original: customer.revision_id === null,
              ledger_page: 1,
              ledger_archived: false,
            }}
          >
            {t("Read the customer version used here", "查看本次客户资料")}
          </Link>
        )}
        {cloud?.kind === "external_versions" && version && (
          <Link
            className="underline"
            to="/projects/$projectId/cloudatlas-ledger"
            params={{ projectId }}
            search={{
              ...back,
              asset_view: "synced",
              external_source: cloud.source_instance_id,
              external_domain: cloud.ip_version_id ? "ip" : "port",
              external_version: version,
            }}
          >
            {t("Read the CloudAtlas version used here", "查看本次云图资料")}
          </Link>
        )}
        <Link
          className="underline"
          to="/projects/$projectId/customer-ledger"
          params={{ projectId }}
          search={{ ...back, ledger_page: 1, ledger_archived: false }}
        >
          {t("Read current customer data", "查看当前客户数据")}
        </Link>
        <Link
          className="underline"
          to="/projects/$projectId/cloudatlas-ledger"
          params={{ projectId }}
          search={{ ...back, asset_view: "synced" }}
        >
          {t("Read current CloudAtlas data", "查看当前云图数据")}
        </Link>
      </div>
    )
  }
  const flowStatus = (value: string) => {
    if (!search.binding || search.binding === "none")
      return t("No evidence provided", "未提供佐证")
    if (eMeta.isError || flows.isError)
      return t("Evidence unavailable", "辅证不可读")
    if (!eReadable)
      return eMeta.data?.state === "EXPIRED" ||
        expiredBinding === search.binding
        ? t("Evidence expired", "辅证已到期")
        : eMeta.data?.state === "REMOVED"
          ? t("Evidence removed", "未提供佐证")
          : t("Evidence unavailable", "辅证不可读")
    if (!flows.isSuccess) return t("Reading evidence…", "正在读取佐证…")
    return flows.data.data.some((row) => row.canonical_ip === value)
      ? t("Flow records in this batch", "该资料中有流量记录")
      : t("No matching flow record", "未匹配到流量")
  }
  return (
    <main className="min-w-0 space-y-6">
      <header className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold">
              {t("Comparison results", "比对结果")}
            </h1>
            {result && (
              <p className="text-sm text-muted-foreground">
                {t("Generated", "生成时间")}：{date(result.published_at)} ·{" "}
                {t("Confirmed namespace", "已确认网络空间")}：
                {result.selection.network_namespace}
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={
                !enabled || busy || !!pending || !statusReady?.can_write
              }
              onClick={() => {
                setComposer(true)
                setNotice("")
                void readiness.refetch()
              }}
            >
              {result
                ? t("Update comparison", "更新比对")
                : t("Generate comparison results", "生成比对结果")}
            </Button>
            <Button
              variant="outline"
              disabled={!enabled}
              onClick={() =>
                change({
                  core_history: !search.core_history,
                  core_history_page: 0,
                })
              }
            >
              {t("Historical results", "历史结果")}
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setDenied(false)
                setExpiredCore(false)
                setUnreadableBinding(undefined)
                void cache.invalidateQueries({ queryKey: prefix })
                void cache.invalidateQueries({ queryKey: ePrefix })
              }}
            >
              {t("Refresh page", "刷新页面")}
            </Button>
          </div>
        </div>
        <p className="max-w-prose text-sm text-muted-foreground">
          {t(
            "The applied customer register and published CloudAtlas data form the core comparison. NetFlow only supplies optional observations.",
            "核心比对采用已应用客户台账与已发布云图资料。NetFlow 只提供可选观测依据。",
          )}
        </p>
        {result && (
          <p className="text-sm">
            {t("Customer version", "客户版本")}：{result.customer_filename} ·{" "}
            {t("Applied", "生效时间")}：{date(result.customer_applied_at)}
            <br />
            {t("CloudAtlas source", "云图来源")}：{result.source_name} ·{" "}
            {Object.entries(object(object(result.pins.CLOUD).domains)).map(
              ([domain, value]) => (
                <span key={domain}>
                  {domain.toUpperCase()} {t("collected", "采集")}{" "}
                  {date(object(value).fetched_at)}　
                </span>
              ),
            )}
          </p>
        )}
      </header>
      {notice && (
        <p role="status" className="rounded-md border p-3 text-sm">
          {notice}
        </p>
      )}
      {pending && (
        <section
          aria-label={t("Recover original operation", "恢复原操作")}
          className="space-y-3 rounded-md border p-4"
        >
          <p>
            {t(
              "The operation outcome is not confirmed. Read the original receipt before creating another request.",
              "操作结果尚未确认。请先读取原回执，再开始其他请求。",
            )}
          </p>
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => void recover()}
          >
            {t("Read original operation", "读取原操作")}
          </Button>
          {canReplay && (
            <div className="space-y-2">
              {pending.needsEvidence && (
                <Label>
                  {t("Original confirmation evidence", "原确认依据")}
                  <Input
                    value={recoveryEvidence}
                    onChange={(event) =>
                      setRecoveryEvidence(event.target.value)
                    }
                    maxLength={2048}
                  />
                </Label>
              )}
              <Button
                disabled={
                  busy || (pending.needsEvidence && !recoveryEvidence.trim())
                }
                onClick={() => void recover(true)}
              >
                {t("Resend original request", "复用原请求提交")}
              </Button>
            </div>
          )}
        </section>
      )}
      {search.core_invalid || denied || expiredCore || summary.isError ? (
        <section
          role="alert"
          className="space-y-3 rounded border border-destructive p-4"
        >
          <h2 className="font-semibold">
            {t("This fixed result cannot be read", "无法读取该固定结果")}
          </h2>
          <p>
            {expiredCore
              ? t(
                  "The selected data has expired. Restricted contents have been cleared.",
                  "所选资料已到期，受限内容已清除。",
                )
              : t(
                  "Identity, access or data integrity could not be verified. No other result was substituted.",
                  "无法核验身份、权限或资料完整性，未替换为其他结果。",
                )}
          </p>
          {!denied && !expiredCore && !search.core_invalid && (
            <Button variant="outline" onClick={() => void summary.refetch()}>
              {t("Retry this result", "重试读取本结果")}
            </Button>
          )}
        </section>
      ) : null}
      {!search.result &&
        !search.core_history &&
        !search.core_invalid &&
        (current.isPending ? (
          <p role="status">
            {t("Locating the latest readable result…", "正在定位最新可读结果…")}
          </p>
        ) : current.isError ? (
          <p role="alert">
            {t(
              "Current result metadata could not be read. Retry the page; this is not an empty result.",
              "无法读取当前结果元数据。请重试，这不代表结果为空。",
            )}
          </p>
        ) : !current.data?.result ? (
          <section className="space-y-4">
            <h2 className="text-lg font-semibold">
              {current.data?.state === "MULTIPLE_SCOPES"
                ? t("Choose a comparison scope", "选择比对范围")
                : t(
                    "No readable comparison has been generated",
                    "尚无可读的比对结果",
                  )}
            </h2>
            {current.data?.scope_choices?.map((scope) => (
              <Button
                key={scope.scope_key}
                variant="outline"
                onClick={() =>
                  void navigate({ search: () => ({ scope: scope.scope_key }) })
                }
              >
                {scope.source_name} · {scope.network_namespace}
              </Button>
            ))}
            <p className="text-sm">{readinessText(statusReady?.state)}</p>
            <div className="flex flex-wrap gap-3 text-sm">
              {!statusReady?.customer && (
                <Link
                  className="underline"
                  to="/"
                  search={{ project: projectId, view: "inputs" }}
                  hash="customer-inputs"
                >
                  {t("Apply a customer register", "应用客户台账")}
                </Link>
              )}
              {!statusReady?.clouds?.some((cloud) => cloud.selection) && (
                <Link
                  className="underline"
                  to="/"
                  search={{ project: projectId, view: "inputs" }}
                  hash="cloudatlas-inputs"
                >
                  {t("Prepare published CloudAtlas data", "准备已发布云图资料")}
                </Link>
              )}
            </div>
          </section>
        ) : null)}
      {search.result &&
        summary.isPending &&
        !denied &&
        !search.core_invalid && (
          <p role="status">
            {t("Reading the fixed comparison…", "正在读取固定比对结果…")}
          </p>
        )}
      {readable && (
        <div className="space-y-2 text-sm">
          {updates.isError ? (
            <p role="status">
              {t(
                "Could not confirm whether inputs have updates.",
                "暂无法确认资料是否有更新。",
              )}
            </p>
          ) : updates.data?.state === "UPDATED" ? (
            <p role="status">
              {t(
                "The current materials have updates. You can explicitly update this comparison; this saved result is unchanged.",
                "当前资料已有更新，可明确更新比对；这份已保存结果保持不变。",
              )}
            </p>
          ) : updates.data?.state === "UNAVAILABLE" ? (
            <p role="status">
              {t(
                "Could not confirm current input status. The saved result remains fixed.",
                "暂无法确认当前资料状态，已保存结果保持固定。",
              )}
            </p>
          ) : null}
          {updates.data?.latest_result_id &&
            updates.data.latest_result_id !== search.result && (
              <p role="status">
                {t(
                  "A newer result is available. This page has not changed version.",
                  "已有更新的结果，本页未中途换版。",
                )}{" "}
                <Button
                  variant="link"
                  onClick={() => fixed(updates.data!.latest_result_id!)}
                >
                  {t("Read the newer result", "查看新结果")}
                </Button>
              </p>
            )}
          {updates.data?.latest_attempt?.status === "FAILED" && (
            <p role="status">
              {t(
                "The latest update failed. This earlier successful result is retained.",
                "最近一次更新失败，仍保留这份成功结果。",
              )}
            </p>
          )}
        </div>
      )}
      {composer && enabled && (
        <section
          className="space-y-4 rounded-md border p-4"
          aria-label={t("Update comparison", "更新比对")}
        >
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-lg font-semibold">
              {t(
                "Confirm the materials for this comparison",
                "确认本次比对资料",
              )}
            </h2>
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => setComposer(false)}
            >
              {t("Close", "关闭")}
            </Button>
          </div>
          <p className="max-w-prose text-sm text-muted-foreground">
            {t(
              "This action uses data already saved locally. It does not sync CloudAtlas, process NetFlow or call a model.",
              "此操作只使用已落地资料，不同步云图、不处理 NetFlow，也不调用模型。",
            )}
          </p>
          {readiness.isError ? (
            <p role="alert">
              {t(
                "Material status could not be read. Retry before generating.",
                "无法读取资料状态，请重试后再生成。",
              )}
            </p>
          ) : readiness.isPending ? (
            <p role="status">
              {t(
                "Reading current applied materials…",
                "正在读取当前已生效资料…",
              )}
            </p>
          ) : (
            <>
              <p>{readinessText(ready?.state)}</p>
              {ready?.customer_filename && (
                <p className="text-sm">
                  {t("Customer register", "客户台账")}：
                  {ready.customer_filename}
                </p>
              )}
              {ready && (ready.clouds?.length ?? 0) > 1 && !search.result && (
                <Label>
                  {t("CloudAtlas source", "云图来源")}
                  <select
                    className="mt-1 block w-full rounded border bg-background p-2"
                    value={source ?? ""}
                    onChange={(event) =>
                      setSource(event.target.value || undefined)
                    }
                  >
                    <option value="">
                      {t("Choose a source", "请选择来源")}
                    </option>
                    {ready.clouds?.map((cloud) => (
                      <option
                        key={cloud.source_instance_id}
                        value={cloud.source_instance_id}
                      >
                        {cloud.source_name} · {t("space", "空间")}{" "}
                        {cloud.space_id}
                      </option>
                    ))}
                  </select>
                </Label>
              )}
              {!search.result &&
                !current.data?.readiness.selection?.network_namespace &&
                ready?.customer &&
                ready?.clouds?.some((cloud) => cloud.selection) && (
                  <Label>
                    {t("Confirmed network namespace", "已确认网络空间标识")}
                    <Input
                      value={namespace}
                      onChange={(event) => setNamespace(event.target.value)}
                      placeholder="customer-network"
                      pattern="[a-z][a-z0-9_-]{0,63}"
                      maxLength={64}
                    />
                  </Label>
                )}
              {ready?.selection && (
                <p className="text-sm">
                  {t("Namespace", "网络空间")}：
                  {ready.selection.network_namespace} ·{" "}
                  {ready.clouds?.[0]?.source_name}
                </p>
              )}
              {ready?.selection &&
                !ready.scope_confirmation_id &&
                (ready.can_confirm_scope ? (
                  <Label>
                    {t("Same-space confirmation evidence", "同空间确认依据")}
                    <textarea
                      className="mt-1 block min-h-20 w-full rounded border bg-background p-2"
                      value={scopeEvidence}
                      onChange={(event) => setScopeEvidence(event.target.value)}
                      maxLength={2048}
                    />
                  </Label>
                ) : (
                  <p role="status">
                    {t(
                      "An administrator must confirm these exact versions before generation.",
                      "这些明确版本需要管理员确认后才能生成。",
                    )}
                  </p>
                ))}
              <div className="flex flex-wrap gap-2">
                <Button
                  disabled={
                    busy ||
                    !!pending ||
                    !ready?.can_generate ||
                    !ready.selection ||
                    (!ready.scope_confirmation_id && !scopeEvidence.trim())
                  }
                  onClick={generate}
                >
                  {busy
                    ? t("Generating…", "正在生成…")
                    : t("Confirm and generate results", "确认并生成结果")}
                </Button>
                <Button
                  variant="outline"
                  disabled={busy || !!pending}
                  onClick={() => void readiness.refetch()}
                >
                  {t("Read current materials again", "重新读取当前资料")}
                </Button>
              </div>
            </>
          )}
        </section>
      )}
      {search.core_history && enabled && (
        <section
          className="space-y-3"
          aria-label={t("Historical results", "历史结果")}
        >
          <h2 className="text-lg font-semibold">
            {t("Historical results", "历史结果")}
          </h2>
          {history.isPending ? (
            <p role="status">{t("Reading history…", "正在读取历史…")}</p>
          ) : history.isError ? (
            <p role="alert">
              {t("History could not be read.", "无法读取历史结果。")}
            </p>
          ) : (
            <>
              <ul className="divide-y">
                {history.data.data.map((value) => (
                  <li
                    key={value.id}
                    className="flex flex-wrap items-center justify-between gap-2 py-3"
                  >
                    <span>
                      {date(value.published_at)} · {value.customer_filename} ·{" "}
                      {value.source_name} ·{" "}
                      {value.purpose === "custom"
                        ? t("Custom historical check", "自定义历史核查")
                        : t("Regular comparison", "常规比对")}
                    </span>
                    <Button variant="outline" onClick={() => fixed(value.id)}>
                      {t("Read this result", "查看本结果")}
                    </Button>
                  </li>
                ))}
              </ul>
              <ResultPagination
                label={t("Results", "比对结果")}
                count={history.data.count}
                page={search.core_history_page ?? 0}
                pageSize={SIZE}
                onPageChange={(page) => change({ core_history_page: page })}
              />
            </>
          )}
          <Link
            className="text-sm underline"
            to="/projects/$projectId/netflow-correlation"
            params={{ projectId }}
            search={{ legacy: true }}
          >
            {t("Historical V1 fixed correlations", "历史 V1 固定关联")}
          </Link>
        </section>
      )}
      {result && (
        <>
          <details className="space-y-3 rounded border p-4">
            <summary className="cursor-pointer font-medium">
              {t("View the materials used here", "查看本次资料")}
            </summary>
            {materialLinks(result)}
            <details className="text-sm">
              <summary className="cursor-pointer text-muted-foreground">
                {t("Fixed identities and rules", "固定身份与规则")}
              </summary>
              <div className="mt-2 space-y-2">
                <TechnicalValue
                  value={result.id}
                  label={t("Result ID", "结果 ID")}
                />
                <TechnicalValue
                  value={result.input_sha256}
                  label={t("Input fingerprint", "资料指纹")}
                />
                <p>{result.rule_version}</p>
              </div>
            </details>
          </details>
          <section
            aria-label={t("Core classification", "核心分类")}
            className="space-y-3"
          >
            <div className="flex flex-wrap gap-2">
              {comparisonClasses.map((kind) => {
                const value =
                  kind === "all" ? result.total_addresses : result[kind]
                return (
                  <Button
                    key={kind}
                    variant={
                      (search.core_class ?? "all") === kind
                        ? "default"
                        : "outline"
                    }
                    aria-pressed={(search.core_class ?? "all") === kind}
                    disabled={value === null}
                    className="h-auto whitespace-normal py-2 text-left"
                    onClick={() =>
                      change({
                        core_class: kind,
                        core_page: 0,
                        core_address: undefined,
                        core_evidence_page: 0,
                      })
                    }
                  >
                    {classes[kind]}{" "}
                    <span className="ml-2 font-semibold tabular-nums">
                      {value ?? "—"}
                    </span>
                  </Button>
                )
              })}
            </div>
            {result.comparison_state !== "AVAILABLE" && (
              <p role="status" className="text-sm">
                {t(
                  "The data coverage is insufficient for full-scope differences. The known records below remain readable.",
                  "资料覆盖不足，不能进行全范围差异统计。下方仍可阅读已知记录。",
                )}
              </p>
            )}
            <form
              className="flex flex-wrap items-end gap-3"
              onSubmit={(event) => {
                event.preventDefault()
                change({
                  core_ip: ip.trim() || undefined,
                  core_page: 0,
                  core_address: undefined,
                })
              }}
            >
              <Label>
                {t("IP address", "IP 地址")}
                <Input
                  value={ip}
                  onChange={(event) => setIp(event.target.value)}
                  placeholder="192.0.2.20"
                  maxLength={45}
                />
              </Label>
              <Label>
                {t("Sort", "排序")}
                <select
                  className="block rounded border bg-background p-2 text-sm"
                  value={search.core_sort ?? "ip_asc"}
                  onChange={(event) =>
                    change({
                      core_sort:
                        event.target.value === "ip_desc" ? "ip_desc" : "ip_asc",
                      core_page: 0,
                      core_address: undefined,
                    })
                  }
                >
                  <option value="ip_asc">{t("IP ascending", "IP 升序")}</option>
                  <option value="ip_desc">
                    {t("IP descending", "IP 降序")}
                  </option>
                </select>
              </Label>
              <Button variant="outline" type="submit">
                {t("Filter", "筛选")}
              </Button>
              <Button
                variant="ghost"
                type="button"
                onClick={() => {
                  setIp("")
                  change({
                    core_ip: undefined,
                    core_class: "all",
                    core_page: 0,
                    core_address: undefined,
                  })
                }}
              >
                {t("Clear filters", "清除筛选")}
              </Button>
            </form>
            {search.core_filter_invalid ? (
              <p role="alert">
                {t(
                  "Invalid query parameters. Clear the filters to continue reading this result.",
                  "查询参数无效，可清除筛选后继续阅读这份结果。",
                )}
              </p>
            ) : rows.isError ? (
              <p role="alert">
                {t(
                  "Could not read this filter. Check the IP address or retry; this is not zero records.",
                  "无法读取当前筛选，请检查 IP 或重试；这不代表零条记录。",
                )}
              </p>
            ) : rows.isPending ? (
              <p role="status">{t("Reading differences…", "正在读取差异…")}</p>
            ) : (
              <>
                <p className="text-sm text-muted-foreground">
                  {t("Fixed total", "固定全集")} {rows.data.total_addresses} ·{" "}
                  {t("Matching", "筛选命中")} {rows.data.count} ·{" "}
                  {t("This page", "本页")} {rows.data.data.length}
                </p>
                <Table
                  tabIndex={0}
                  aria-label={t("Comparison addresses", "比对地址列表")}
                  className="min-w-[740px] focus-visible:outline-2 focus-visible:outline-ring"
                >
                  <TableHeader>
                    <TableRow>
                      <TableHead>IP</TableHead>
                      <TableHead>{t("Customer records", "客户记录")}</TableHead>
                      <TableHead>
                        {t("CloudAtlas records", "云图记录")}
                      </TableHead>
                      <TableHead>{t("Conclusion", "核对结论")}</TableHead>
                      <TableHead>{t("Flow evidence", "流量佐证")}</TableHead>
                      <TableHead>{t("Evidence", "依据")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.data.data.map((row) => (
                      <TableRow key={row.address_key}>
                        <TableCell className="font-medium">
                          {row.canonical_ip}
                        </TableCell>
                        <TableCell>{row.customer_records}</TableCell>
                        <TableCell>{row.cloud_records}</TableCell>
                        <TableCell className="max-w-64 whitespace-normal">
                          {row.classification
                            ? classes[row.classification]
                            : t(
                                "Known records; comparison coverage is incomplete",
                                "已知记录；比对覆盖不足",
                              )}
                        </TableCell>
                        <TableCell className="max-w-48 whitespace-normal">
                          {flowStatus(row.canonical_ip)}
                        </TableCell>
                        <TableCell>
                          <Button
                            size="sm"
                            variant="outline"
                            aria-expanded={
                              search.core_address === row.address_key
                            }
                            onClick={(event) => {
                              lastAddressTrigger.current = event.currentTarget
                              change({
                                core_address: row.address_key,
                                core_evidence: row.customer_records
                                  ? "customer"
                                  : "cloud",
                                core_evidence_page: 0,
                              })
                            }}
                          >
                            {t("View evidence", "查看依据")}
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                {rows.data.count === 0 && (
                  <p>
                    {t(
                      "No records match this filter in the fixed result.",
                      "此固定结果没有符合当前筛选的记录。",
                    )}
                  </p>
                )}
                <ResultPagination
                  label={t("Comparison addresses", "比对地址")}
                  count={rows.data.count}
                  page={search.core_page ?? 0}
                  pageSize={SIZE}
                  onPageChange={(page) =>
                    change({
                      core_page: page,
                      core_address: undefined,
                      core_evidence_page: 0,
                    })
                  }
                />
              </>
            )}
            <p className="max-w-prose text-sm text-muted-foreground">
              {t(
                "These are differences between the selected records. A shared IP does not prove ownership or no risk. Not observed does not mean offline. A flow source port is not a listening-service port.",
                "这些结论只描述所用资料中的记录差异。相同 IP 不证明资产归属或无风险；本批未观测不等于下线；流量源侧端口不是监听服务端口。",
              )}
            </p>
          </section>
          {search.core_address && (
            <section
              className="space-y-4 rounded-md border p-4"
              aria-label={t("Fixed address evidence", "固定地址依据")}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2
                  ref={detailHeading}
                  tabIndex={-1}
                  className="text-lg font-semibold"
                >
                  {detail.data?.address.canonical_ip ??
                    t("Fixed address evidence", "固定地址依据")}
                </h2>
                <Button
                  variant="outline"
                  onClick={() => {
                    change({ core_address: undefined, core_evidence_page: 0 })
                    requestAnimationFrame(() =>
                      lastAddressTrigger.current?.focus(),
                    )
                  }}
                >
                  {t("Close evidence", "关闭依据")}
                </Button>
              </div>
              {detail.isError ? (
                <p role="alert">
                  {t(
                    "This address cannot be read in this fixed result.",
                    "无法在这份固定结果中读取该地址。",
                  )}
                </p>
              ) : detail.data ? (
                <p>
                  {detail.data.address.classification
                    ? classes[detail.data.address.classification]
                    : t(
                        "The sources contain records; coverage does not support a complete difference conclusion.",
                        "来源中存在记录，但覆盖范围不足以支持完整差异结论。",
                      )}
                </p>
              ) : (
                <p role="status">
                  {t("Reading the address…", "正在读取地址…")}
                </p>
              )}
              {detail.data && (
                <p className="text-sm">
                  {t("Customer records", "客户记录")}{" "}
                  {detail.data.address.customer_records} ·{" "}
                  {t("CloudAtlas records", "云图记录")}{" "}
                  {detail.data.address.cloud_records}
                </p>
              )}
              {materialLinks(result)}
              {eReadable && eMeta.data?.analysis_id && (
                <Link
                  className="block text-sm underline"
                  to="/projects/$projectId/netflow-results"
                  params={{ projectId }}
                  search={{
                    ...back,
                    analysis: eMeta.data.analysis_id,
                    dataset: eMeta.data.dataset_id ?? undefined,
                    ip: detail.data?.address.canonical_ip,
                  }}
                >
                  {t(
                    "Read the fixed NetFlow observations",
                    "查看固定 NetFlow 观测",
                  )}
                </Link>
              )}
              <div className="flex gap-2">
                {(["customer", "cloud"] as const).map((sourceName) => (
                  <Button
                    key={sourceName}
                    size="sm"
                    variant={
                      (search.core_evidence ?? "customer") === sourceName
                        ? "default"
                        : "outline"
                    }
                    onClick={() =>
                      change({
                        core_evidence: sourceName,
                        core_evidence_page: 0,
                      })
                    }
                  >
                    {sourceName === "customer"
                      ? t("Customer evidence", "客户依据")
                      : t("CloudAtlas evidence", "云图依据")}
                  </Button>
                ))}
              </div>
              {proof.isPending ? (
                <p role="status">
                  {t("Reading fixed source evidence…", "正在读取固定来源依据…")}
                </p>
              ) : proof.isError ? (
                <p role="alert">
                  {t(
                    "The fixed evidence could not be read. No current version was substituted.",
                    "无法读取固定依据，未替换为当前版本。",
                  )}
                </p>
              ) : (
                <>
                  {proof.data.data.length === 0 && (
                    <p>
                      {t(
                        "This selected source contains no record for the address in this result.",
                        "这份结果所用的该来源中，没有此地址的记录。",
                      )}
                    </p>
                  )}
                  {proof.data.data.map((record) => (
                    <details
                      key={`${record.version_id}:${record.record_key}`}
                      className="rounded border p-3 text-sm"
                    >
                      <summary className="cursor-pointer">
                        {record.canonical_ip} · {record.domain} ·{" "}
                        {t("Original source record", "原始来源记录")}
                      </summary>
                      <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs">
                        {JSON.stringify(
                          {
                            original: record.original,
                            availability: record.availability,
                          },
                          null,
                          2,
                        )}
                      </pre>
                      <TechnicalValue
                        value={record.version_id}
                        label={t("Fixed version", "固定版本")}
                      />
                      <TechnicalValue
                        value={record.record_key}
                        label={t("Source record", "来源记录")}
                      />
                    </details>
                  ))}
                  <ResultPagination
                    label={t("Evidence records", "依据记录")}
                    count={proof.data.count}
                    page={search.core_evidence_page ?? 0}
                    pageSize={SIZE}
                    onPageChange={(page) =>
                      change({ core_evidence_page: page })
                    }
                  />
                </>
              )}
            </section>
          )}
          <section
            className="space-y-4 border-t pt-5"
            aria-label={t("Optional NetFlow evidence", "可选 NetFlow 佐证")}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-lg font-semibold">
                {t("NetFlow evidence", "NetFlow 佐证")}
              </h2>
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={
                    !statusReady?.can_confirm_scope ||
                    busy ||
                    !!pending ||
                    !search.binding
                  }
                  onClick={() => setAttach(!attach)}
                >
                  {t("Attach existing observations", "附加已有观测")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setShowBindingHistory(!showBindingHistory)}
                >
                  {t("Evidence history", "辅证历史")}
                </Button>
                {search.binding &&
                  search.binding !== "none" &&
                  statusReady?.can_write && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy || !!pending}
                      onClick={() =>
                        void perform("bind", {
                          analysis_id: null,
                          expected_binding_id: search.binding,
                          qualification_confirmation_id: null,
                          scope_evidence: null,
                          valid_until: null,
                        })
                      }
                    >
                      {t("Remove from current binding", "移出当前绑定")}
                    </Button>
                  )}
              </div>
            </div>
            {!search.binding ? (
              <p role="status">
                {t("Reading the evidence binding…", "正在读取辅证绑定…")}
              </p>
            ) : search.binding === "none" ? (
              <p>
                {t(
                  "No NetFlow evidence was provided. Core results are complete without it.",
                  "未提供 NetFlow 佐证，核心结果不依赖它。",
                )}
              </p>
            ) : eMeta.isError ? (
              <p role="alert">
                {t(
                  "Evidence cannot be read. Core classification and counts remain available.",
                  "辅证不可读，核心分类与计数仍可阅读。",
                )}
              </p>
            ) : !eReadable ? (
              <p role="status">
                {eMeta.data?.state === "EXPIRED" ||
                expiredBinding === search.binding
                  ? t(
                      "This evidence binding has expired. Its contents are cleared; the core result is unchanged.",
                      "此辅证绑定已到期，相关内容已清除，核心结果保持不变。",
                    )
                  : eMeta.data?.state === "REMOVED"
                    ? t(
                        "The current binding contains no NetFlow evidence.",
                        "当前绑定未提供 NetFlow 佐证。",
                      )
                    : t(
                        "Evidence is unavailable under its current permissions or context. Core results are unchanged.",
                        "辅证当前权限或上下文不可用，核心结果保持不变。",
                      )}
              </p>
            ) : (
              <>
                <p className="text-sm">
                  {t("Bound", "绑定时间")}：{date(eMeta.data.created_at)} ·{" "}
                  {t("Evidence cutoff", "辅证截止")}：
                  {date(eMeta.data.valid_until)}
                  <br />
                  {t("Actual observation window", "实际观测窗口")}：
                  {t(
                    "Not provided by the sealed source result",
                    "封存来源结果未提供",
                  )}
                </p>
                <p className="text-sm text-muted-foreground">
                  {t(
                    "Only source-side observations are used. The time window is unqualified; these records do not prove simultaneous activity or listening services.",
                    "这里只使用源侧观测。时间窗口未取得资格，这些记录不证明同时活动或监听服务。",
                  )}
                </p>
                <h3 className="font-medium">
                  {t("Supplemental leads", "补充线索")}
                </h3>
                <p className="text-sm text-muted-foreground">
                  {t(
                    "Addresses observed only in NetFlow are outside the C+A core total. They are not automatically owned assets or confirmed omissions.",
                    "仅 NetFlow 出现的地址不计入 C+A 核心总数，也不自动认定为自有资产或已确认漏管。",
                  )}
                </p>
                {extra.isError ? (
                  <p role="alert">
                    {t(
                      "Supplemental observations could not be read.",
                      "无法读取补充观测。",
                    )}
                  </p>
                ) : extra.isPending ? (
                  <p role="status">
                    {t(
                      "Reading supplemental observations…",
                      "正在读取补充观测…",
                    )}
                  </p>
                ) : (
                  <>
                    <Table
                      tabIndex={0}
                      aria-label={t("Supplemental leads", "补充线索")}
                    >
                      <TableHeader>
                        <TableRow>
                          <TableHead>IP</TableHead>
                          <TableHead>
                            {t("Observation objects", "观测对象")}
                          </TableHead>
                          <TableHead>{t("Source records", "源记录")}</TableHead>
                          <TableHead>{t("Evidence", "依据")}</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {extra.data.data.map((row) => (
                          <TableRow key={row.canonical_ip}>
                            <TableCell>{row.canonical_ip}</TableCell>
                            <TableCell>{row.observation_count}</TableCell>
                            <TableCell>{row.source_records}</TableCell>
                            <TableCell>
                              <Link
                                className="underline"
                                to="/projects/$projectId/netflow-results"
                                params={{ projectId }}
                                search={{
                                  ...back,
                                  analysis: eMeta.data.analysis_id ?? undefined,
                                  dataset: eMeta.data.dataset_id ?? undefined,
                                  ip: row.canonical_ip,
                                }}
                              >
                                {t("Read observations", "查看观测")}
                              </Link>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                    {extra.data.count === 0 && (
                      <p>
                        {t(
                          "No NetFlow-only addresses in this fixed evidence binding.",
                          "该固定辅证绑定没有 NetFlow 独有地址。",
                        )}
                      </p>
                    )}
                    <ResultPagination
                      label={t("Supplemental leads", "补充线索")}
                      count={extra.data.count}
                      page={search.core_extra_page ?? 0}
                      pageSize={SIZE}
                      onPageChange={(page) => change({ core_extra_page: page })}
                    />
                  </>
                )}
              </>
            )}
            {attach && (
              <section
                className="space-y-3 rounded border p-4"
                aria-label={t(
                  "Attach existing NetFlow observations",
                  "附加已有 NetFlow 观测",
                )}
              >
                <p>
                  {t(
                    "Choose already processed observations. This action never starts processing. Confirm the exact same-space relationship and an explicit future cutoff.",
                    "请选择已处理观测。此操作不会启动处理；须确认确切同空间关系，并明确未来截止时间。",
                  )}
                </p>
                {currentFlow.isError ? (
                  <p role="alert">
                    {t(
                      "Current observations could not be read.",
                      "无法读取当前观测。",
                    )}
                  </p>
                ) : currentFlow.isPending ? (
                  <p role="status">
                    {t("Reading available scopes…", "正在读取可用范围…")}
                  </p>
                ) : (
                  <>
                    {currentFlow.data.scopes.length > 1 && (
                      <Label>
                        {t("Collection scope", "采集范围")}
                        <select
                          className="block w-full rounded border bg-background p-2"
                          value={flowScope ?? currentFlow.data.scope_id ?? ""}
                          onChange={(event) =>
                            setFlowScope(event.target.value || undefined)
                          }
                        >
                          <option value="">
                            {t("Choose a scope", "选择范围")}
                          </option>
                          {currentFlow.data.scopes
                            .filter(
                              (scope) =>
                                scope.network_namespace ===
                                result.selection.network_namespace,
                            )
                            .map((scope) => (
                              <option
                                key={scope.scope_id}
                                value={scope.scope_id}
                              >
                                {scope.label} · {scope.network_namespace}
                              </option>
                            ))}
                        </select>
                      </Label>
                    )}
                    {!currentFlow.data.current ? (
                      <p>
                        {t(
                          "No successful readable processing result is available in this scope.",
                          "此范围尚无成功且可读的处理结果。",
                        )}
                      </p>
                    ) : currentFlow.data.current.network_namespace !==
                      result.selection.network_namespace ? (
                      <p role="alert">
                        {t(
                          "The observation namespace differs from this result. Choose confirmed same-space observations.",
                          "观测网络空间与本结果不同，请选择已确认同空间观测。",
                        )}
                      </p>
                    ) : (
                      <>
                        <p className="text-sm">
                          {t("Processing completed", "处理完成")}：
                          {date(currentFlow.data.current.completed_at)} ·{" "}
                          {t("Actual window", "实际窗口")}：
                          {t("Not provided", "未提供")}
                        </p>
                        <Label>
                          {t(
                            "Evidence valid until (local time)",
                            "辅证有效截止（本地时间）",
                          )}
                          <Input
                            type="datetime-local"
                            value={validUntil}
                            onChange={(event) =>
                              setValidUntil(event.target.value)
                            }
                            required
                          />
                        </Label>
                        <Label>
                          {t(
                            "Same-space evidence for this result and these observations",
                            "本结果与此观测同空间的确认依据",
                          )}
                          <textarea
                            className="block min-h-20 w-full rounded border bg-background p-2"
                            value={bindingEvidence}
                            onChange={(event) =>
                              setBindingEvidence(event.target.value)
                            }
                            maxLength={2048}
                          />
                        </Label>
                        <Button
                          disabled={
                            busy ||
                            !!pending ||
                            !validUntil ||
                            !bindingEvidence.trim()
                          }
                          onClick={attachEvidence}
                        >
                          {t("Confirm evidence binding", "确认辅证绑定")}
                        </Button>
                      </>
                    )}
                  </>
                )}
              </section>
            )}
            {showBindingHistory && (
              <section
                className="space-y-2"
                aria-label={t("Evidence history", "辅证历史")}
              >
                {bindingHistory.isError ? (
                  <p role="alert">
                    {t(
                      "Evidence history could not be read.",
                      "无法读取辅证历史。",
                    )}
                  </p>
                ) : bindingHistory.isPending ? (
                  <p role="status">
                    {t("Reading evidence history…", "正在读取辅证历史…")}
                  </p>
                ) : (
                  <>
                    <ul className="divide-y">
                      {bindingHistory.data.data.map((value) => (
                        <li
                          key={value.id}
                          className="flex flex-wrap justify-between gap-2 py-2 text-sm"
                        >
                          <span>
                            {date(value.created_at)} · {date(value.valid_until)}{" "}
                            ·{" "}
                            {value.state === "ACTIVE"
                              ? t("Readable", "可读")
                              : value.state === "EXPIRED"
                                ? t("Expired", "已到期")
                                : value.state === "REMOVED"
                                  ? t("No evidence", "未提供佐证")
                                  : t("Unavailable", "不可读")}
                          </span>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              setShowBindingHistory(false)
                              change({
                                binding: value.id ?? "none",
                                core_extra_page: 0,
                              })
                            }}
                          >
                            {t("Read fixed binding", "查看固定绑定")}
                          </Button>
                        </li>
                      ))}
                    </ul>
                    <ResultPagination
                      label={t("Evidence bindings", "辅证绑定")}
                      count={bindingHistory.data.count}
                      page={bindingHistoryPage}
                      pageSize={SIZE}
                      onPageChange={setBindingHistoryPage}
                    />
                  </>
                )}
              </section>
            )}
          </section>
        </>
      )}
    </main>
  )
}
