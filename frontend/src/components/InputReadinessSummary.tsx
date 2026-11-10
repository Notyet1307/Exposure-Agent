import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { useEffect, useMemo, useState } from "react"
import { ApiError, InputSummaryService } from "@/client"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"
import { readinessText } from "@/lib/readiness-presentation"

type Summary = Awaited<ReturnType<typeof InputSummaryService.readInputSummary>>
type Readiness = Summary["core_readiness"]
type Source = NonNullable<Readiness["sources"]>[number]

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

const object = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}

function materialDeadline(value: Summary): number {
  const cloud = value.core_readiness.sources?.find(
    (row) => row.source === "CLOUD",
  )
  const deadlines = Object.values(object(object(cloud?.metadata).domains))
    .map((entry) => Date.parse(String(object(entry).retain_until)))
    .filter(Number.isFinite)
  return deadlines.length ? Math.min(...deadlines) : Number.POSITIVE_INFINITY
}

type NetFlowReadFields = {
  scope_id: string | null
  scopes: Array<{
    scope_id: string
    network_namespace: string
    collection_scope: string | null
    label: string
  }>
  current_analysis_id: string | null
  latest_attempt_status: string | null
  latest_attempt_error_code: string | null
}

// The generated union keeps read_state optional, so narrow it once here.
function netflowRead(value: Summary["netflow"]): NetFlowReadFields | undefined {
  return value.read_state === "READ" ? (value as NetFlowReadFields) : undefined
}

function customerContradiction(value: Summary): boolean {
  const readiness = value.core_readiness.customer
  // Only a present readiness selection is an observation to compare; a
  // short-circuited or unavailable readiness read remains unknown.
  if (!readiness) return false
  return (
    (value.customer.applied_upload_id ?? null) !==
      (readiness.upload_id ?? null) ||
    (value.customer.applied_revision_id ?? null) !==
      (readiness.revision_id ?? null)
  )
}

export default function InputReadinessSummary({
  actorId,
  projectId,
}: {
  actorId: string
  projectId: string
}) {
  const { t, formatDate } = useI18n()
  const cache = useQueryClient()
  const [expiring, setExpiring] = useState(false)
  const [blocked, setBlocked] = useState(false)
  const key = useMemo(
    () => ["input-summary", projectId, actorId] as const,
    [actorId, projectId],
  )
  const summary = useQuery({
    queryKey: key,
    retry: false,
    staleTime: 0,
    gcTime: 0,
    refetchOnWindowFocus: true,
    enabled: !blocked,
    queryFn: async () => {
      const value = await InputSummaryService.readInputSummary({ projectId })
      if (
        value.project_id !== projectId ||
        value.contract_version !== "input-summary-v1" ||
        value.core_readiness.project_id !== projectId ||
        value.core_readiness.contract_version !== "core-comparison-v2"
      )
        throw new Error("input_summary_identity_mismatch")
      if (materialDeadline(value) <= Date.now())
        throw new Error("input_summary_deadline_expired")
      return value
    },
  })
  const { refetch } = summary
  useEffect(
    () => () => {
      void cache.cancelQueries({ queryKey: key })
      cache.removeQueries({ queryKey: key })
    },
    [cache, key],
  )
  const data = summary.data
  const deadline = data ? materialDeadline(data) : Number.POSITIVE_INFINITY
  useEffect(() => {
    if (!Number.isFinite(deadline)) return
    return expireAt(deadline, () => {
      setExpiring(true)
      void refetch()
    })
  }, [deadline, refetch])
  useEffect(() => {
    if (data && Date.now() < materialDeadline(data)) setExpiring(false)
  }, [data])
  const status =
    summary.error instanceof ApiError ? summary.error.status : undefined
  const hard =
    status === 401 || status === 403 || status === 404 || status === 410
  useEffect(() => {
    if (hard) setBlocked(true)
  }, [hard])
  const reason =
    summary.error instanceof Error ? summary.error.message : undefined
  // Never trust only a boolean latch: cached data can pass its material
  // deadline while a retry is pending. The current deadline stays authoritative.
  const dataExpired = data ? deadline <= Date.now() : false
  const deadlineReached =
    dataExpired ||
    (expiring && !data) ||
    reason === "input_summary_deadline_expired"
  const identityFailed = reason === "input_summary_identity_mismatch"
  const usable = data && !summary.isError && !deadlineReached ? data : undefined
  const stale = summary.isFetching && Boolean(usable)
  const retry = () => {
    setBlocked(false)
    void refetch()
  }
  const heading = (
    <h2 id="input-readiness-title" className="text-base font-semibold">
      {t("Input readiness", "数据接入就绪状态")}
    </h2>
  )
  if (summary.isPending)
    return (
      <section
        aria-labelledby="input-readiness-title"
        className="space-y-3 border-t pt-6"
        data-input-readiness
      >
        {heading}
        <p role="status">
          {t("Reading input readiness…", "正在读取数据接入就绪状态…")}
        </p>
      </section>
    )
  if (!usable) {
    const message = hard
      ? status === 403 || status === 401
        ? t(
            "Input status was denied. Nothing is shown as ready or empty.",
            "数据接入状态读取被拒绝，不显示为已就绪或空集。",
          )
        : status === 404
          ? t(
              "This project's input status is unavailable or not accessible.",
              "此项目的数据接入状态不可用或无权访问。",
            )
          : t(
              "The fixed input versions have expired. Unknown is not an empty result.",
              "固定的输入版本已到期，未知不等于空集。",
            )
      : deadlineReached
        ? t(
            "A known material deadline has passed. No ready claim is shown; a fresh GET is required.",
            "已知资料期限已到，不显示就绪结论，需要重新读取。",
          )
        : identityFailed
          ? t(
              "The response did not match this project and was discarded.",
              "响应与当前项目不一致，已丢弃。",
            )
          : t(
              "Input status could not be read. No ready claim is shown.",
              "无法读取数据接入状态，不显示就绪结论。",
            )
    return (
      <section
        aria-labelledby="input-readiness-title"
        className="space-y-3 border-t pt-6"
        data-input-readiness
      >
        {heading}
        <p role="alert">{message}</p>
        <Button variant="outline" onClick={retry}>
          {t("Retry", "重试")}
        </Button>
      </section>
    )
  }
  const value = usable
  const readiness = value.core_readiness
  const sources = readiness.sources ?? []
  const customerState = sources.find((row) => row.source === "CUSTOMER")
  const cloudState = sources.find((row) => row.source === "CLOUD")
  const netflow = value.netflow
  const readNetflow = netflowRead(netflow)
  const contradiction = customerContradiction(value)
  const observedAt = formatDate(new Date(summary.dataUpdatedAt).toISOString())
  const readLabel = (state: Source | undefined) => {
    if (!state)
      return t("Read status not reached; unknown.", "尚未读取状态，未知。")
    const read = {
      VALID_NONEMPTY: t("read valid non-empty", "已读取，合法非空"),
      VALID_EMPTY: t("read valid empty", "已读取，合法空集"),
      NOT_PROVIDED: t("not provided", "未提供"),
      READ_FAILED: t("read failed", "读取失败"),
    }[state.read_state]
    const coverage = {
      SUFFICIENT: t("coverage sufficient", "覆盖充分"),
      INSUFFICIENT: t("coverage insufficient", "覆盖不足"),
      UNKNOWN: t("coverage unknown", "覆盖未知"),
      NOT_APPLICABLE: t("coverage not applicable", "覆盖不适用"),
    }[state.coverage_state]
    return `${read}; ${coverage}`
  }
  const known = (count: number | null | undefined) =>
    count === null || count === undefined ? t("Unknown", "未知") : String(count)
  const publication = {
    PUBLISHED: t(
      "published candidate (metadata only)",
      "已发布候选（仅元数据）",
    ),
    EXPIRED: t("expired version only", "仅有已到期版本"),
    NOT_PUBLISHED: t("no published version", "尚无已发布版本"),
  }
  const customerLink = (
    <Link
      className="underline"
      to="/"
      search={{ project: projectId, view: "inputs" }}
      hash="customer-inputs"
    >
      {t("Apply or replace the customer input", "应用或替换客户输入")}
    </Link>
  )
  const cloudLink = (
    <Link
      className="underline"
      to="/projects/$projectId/cloudatlas-ledger"
      params={{ projectId }}
      search={{ asset_view: "synced", external_manage: "sources" }}
    >
      {t("Manage CloudAtlas sources and versions", "管理云图来源与版本")}
    </Link>
  )
  const comparisonLink = (
    <Link
      className="underline"
      to="/projects/$projectId/netflow-correlation"
      params={{ projectId }}
      search={{}}
    >
      {t("Open comparison results", "打开比对结果")}
    </Link>
  )
  const nextStep =
    readiness.state === "CUSTOMER_NOT_READY"
      ? customerLink
      : readiness.state === "CLOUD_NOT_READY" ||
          readiness.state === "EXPIRED" ||
          readiness.state === "ACCESS_DENIED"
        ? cloudLink
        : comparisonLink
  const netflowLink = (
    <Link
      className="underline"
      to="/"
      search={
        netflow.read_state === "READ" && netflow.current_dataset_id
          ? {
              project: projectId,
              view: "inputs",
              processing_dataset: netflow.current_dataset_id,
            }
          : { project: projectId, view: "inputs" }
      }
      hash={
        netflow.read_state === "READ" && netflow.current_dataset_id
          ? "netflow-processing"
          : "netflow-inputs"
      }
    >
      {t("Configure optional NetFlow input", "配置可选 NetFlow 输入")}
    </Link>
  )
  return (
    <section
      aria-labelledby="input-readiness-title"
      className="space-y-4 border-t pt-6"
      data-input-readiness
    >
      {heading}
      <p className="max-w-prose text-sm text-muted-foreground">
        {t(
          "This summary only reads stored facts. Opening or refreshing it never applies a file, syncs, processes NetFlow, or generates a result.",
          "此摘要只读取已存事实。打开或刷新不会应用文件、同步、处理 NetFlow 或生成结果。",
        )}
      </p>
      {stale && (
        <p role="status">
          {t(
            `Refreshing input status. Last observed ${observedAt}; this is not a current ready claim.`,
            `正在刷新数据接入状态。上次观测时间 ${observedAt}，这不是当前就绪结论。`,
          )}
        </p>
      )}
      {contradiction ? (
        <p role="alert">
          {t(
            "The applied input pointer and readiness selection disagree. Refresh to read one consistent state; readiness is not recomputed here.",
            "已应用输入指针与就绪选择不一致，请刷新读取一致状态；此处不重算就绪结论。",
          )}
        </p>
      ) : (
        <p data-readiness-state={readiness.state}>
          {stale
            ? t(
                "Not confirming readiness while the summary is stale.",
                "摘要陈旧时不确认就绪。",
              )
            : readinessText(readiness.state, t)}
        </p>
      )}
      <p className="text-sm">
        {t("Next step", "下一步")}: {nextStep}
      </p>
      <div className="space-y-1 text-sm">
        <h3 className="font-medium">{t("Customer register", "客户台账")}</h3>
        <p>
          {t("Applied input", "已应用输入")}:{" "}
          {value.customer.applied_upload_id ?? t("None", "无")}
        </p>
        {value.customer.applied_revision_id && (
          <p>
            {t("Applied revision", "已应用修订")}:{" "}
            {value.customer.applied_revision_id}
          </p>
        )}
        <p>
          {t("Accepted uploads", "已接受上传")}:{" "}
          {value.customer.accepted_upload_count}
        </p>
        <p>
          {t("Accepted but not applied", "已接受但未应用")}:{" "}
          {value.customer.unapplied_upload_count}
        </p>
        <p>
          {t("Material", "材料")}: {readLabel(customerState)}
        </p>
      </div>
      <div className="space-y-1 text-sm">
        <h3 className="font-medium">{t("CloudAtlas", "云图")}</h3>
        {value.cloud.sources.length ? (
          <ul className="list-disc pl-5">
            {value.cloud.sources.map((source) => (
              <li key={source.source_instance_id}>
                {source.instance_id} · {source.validation_status} ·{" "}
                {source.enabled
                  ? t("enabled", "已启用")
                  : t("disabled", "未启用")}{" "}
                ·{" "}
                {source.data_access_enabled
                  ? t("data access allowed", "允许读取资料")
                  : t("data access revoked", "资料读取已撤权")}
              </li>
            ))}
          </ul>
        ) : (
          <p>
            {t(
              "No assets-v1 source is configured.",
              "尚未配置 assets-v1 来源。",
            )}
          </p>
        )}
        <p>
          {t("Published version candidates", "已发布版本候选")}:{" "}
          {readiness.clouds?.length
            ? readiness.clouds
                .map(
                  (choice) =>
                    `${choice.source_name} (${publication[choice.state]})`,
                )
                .join("; ")
            : t("None", "无")}
        </p>
        <p>
          {t("Material", "材料")}: {readLabel(cloudState)}
        </p>
        <p>
          {t("Records", "记录")}: {known(cloudState?.source_records)} ·{" "}
          {t("Addresses", "地址")}: {known(cloudState?.source_addresses)}
        </p>
      </div>
      <div className="space-y-1 text-sm">
        <h3 className="font-medium">
          {t("NetFlow (optional)", "NetFlow（可选）")}
        </h3>
        <p>
          {t(
            "Optional evidence only; it never gates the core comparison.",
            "仅作可选辅证，从不阻断核心比对。",
          )}
        </p>
        <p>
          {t("Accepted datasets", "已接受数据集")}:{" "}
          {known(netflow.dataset_count)}
        </p>
        {readNetflow ? (
          <>
            <p>
              {t("Scopes", "范围")}:{" "}
              {readNetflow.scopes.length
                ? readNetflow.scopes
                    .map(
                      (scope) => `${scope.label} (${scope.network_namespace})`,
                    )
                    .join("; ")
                : t("None selected", "未选择")}
            </p>
            <p>
              {t("Current readable analysis", "当前可读分析")}:{" "}
              {readNetflow.current_analysis_id ?? t("None", "无")}
            </p>
            <p>
              {t("Latest attempt", "最近尝试")}:{" "}
              {readNetflow.latest_attempt_status ?? t("None", "无")}
              {readNetflow.latest_attempt_error_code
                ? ` · ${readNetflow.latest_attempt_error_code}`
                : ""}
            </p>
          </>
        ) : (
          <p role="alert">
            {t("NetFlow state could not be read", "无法读取 NetFlow 状态")}:{" "}
            {netflow.read_state === "READ_FAILED"
              ? `${netflow.error_code}${
                  netflow.error_status ? ` (HTTP ${netflow.error_status})` : ""
                }`
              : t("Unknown", "未知")}
          </p>
        )}
        {netflowLink}
      </div>
    </section>
  )
}
