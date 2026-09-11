import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useId, useState } from "react"

import {
  ApiError,
  type ManualReviewPublic,
  ManualReviewsService,
} from "@/client"
import { ResultPagination } from "@/components/ResultPagination"
import { TechnicalValue } from "@/components/TechnicalValue"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"

type Scope = {
  projectId: string
  resourceId: string
  runId: string
  findingId?: string
}

const PAGE_SIZE = 20

export function ManualReviewPanel(scope: Scope) {
  const { t, formatDate, translateValue } = useI18n()
  const formId = useId()
  const queryClient = useQueryClient()
  const [page, setPage] = useState(0)
  const [conclusion, setConclusion] = useState("")
  const [pendingVerification, setPendingVerification] = useState("")
  const [supersedesId, setSupersedesId] = useState<string | null>(null)
  const queryKey = [
    "manual-reviews",
    scope.projectId,
    scope.resourceId,
    scope.runId,
    scope.findingId ?? null,
  ]
  const verifyScope = (item: ManualReviewPublic) => {
    if (
      item.project_id !== scope.projectId ||
      item.resource_id !== scope.resourceId ||
      item.run_id !== scope.runId ||
      (item.finding_id ?? null) !== (scope.findingId ?? null)
    )
      throw new Error("Manual review scope mismatch")
    return item
  }
  const list = useQuery({
    queryKey: [...queryKey, page],
    queryFn: async () => {
      const response = await ManualReviewsService.readManualReviews({
        ...scope,
        skip: page * PAGE_SIZE,
        limit: PAGE_SIZE,
      })
      return { ...response, data: response.data.map(verifyScope) }
    },
    retry: false,
  })
  const records = list.isSuccess ? list.data.data : []
  const current =
    page === 0 ? records.find((item) => item.is_current) : undefined
  const writable = list.isSuccess && list.data.can_create
  const fresh = list.isSuccess && !list.isFetching
  const staleCorrection = supersedesId !== null && current?.id !== supersedesId
  const save = useMutation({
    mutationFn: async () =>
      verifyScope(
        await ManualReviewsService.createManualReview({
          projectId: scope.projectId,
          requestBody: {
            resource_id: scope.resourceId,
            run_id: scope.runId,
            finding_id: scope.findingId ?? null,
            conclusion: conclusion.trim(),
            pending_verification: pendingVerification.trim(),
            supersedes_id: supersedesId,
          },
        }),
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey })
      setPage(0)
      setSupersedesId(null)
      setConclusion("")
      setPendingVerification("")
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409)
        void queryClient.invalidateQueries({ queryKey })
    },
  })
  const canSave =
    writable &&
    fresh &&
    page === 0 &&
    !save.isPending &&
    !staleCorrection &&
    (supersedesId !== null || list.data.count === 0) &&
    !!conclusion.trim() &&
    !!pendingVerification.trim()
  const statusLabel = (status: string) => {
    switch (status) {
      case "PENDING":
        return t("Pending verification", "待验证")
      case "RESOLVED":
        return t("Verified resolved", "已验证解决")
      case "UNRESOLVED":
        return t("Unresolved", "未解决")
      case "INSUFFICIENT_EVIDENCE":
        return t("Insufficient evidence", "证据不足")
      default:
        return t("No new conclusion", "没有新的可用结论")
    }
  }
  const reasonLabel = (reason: string) => {
    switch (reason) {
      case "both_sources_observed":
        return t(
          "Both sources observed the asset; the original difference is resolved.",
          "两侧均已观测到资产，原差异已解决。",
        )
      case "original_difference_persists":
        return t(
          "The original source difference is still present.",
          "原有来源差异仍然存在。",
        )
      case "original_difference_not_established":
        return t(
          "The base Run does not establish a verifiable original difference.",
          "基础运行未确立可验证的原差异。",
        )
      case "resource_not_observed":
        return t(
          "The asset was not observed; absence does not establish resolution.",
          "资产未被观测到；缺失不能证明已解决。",
        )
      case "difference_direction_changed":
        return t(
          "The source difference changed direction; resolution is not established.",
          "来源差异方向发生变化，无法确认已解决。",
        )
      case "comparison_evidence_unavailable":
        return t(
          "Compatible published comparison evidence is unavailable.",
          "缺少兼容的已发布比较证据。",
        )
      case "run_not_successful":
        return t(
          "This Run has no successful published result to verify.",
          "此运行没有可供验证的成功发布结果。",
        )
      default:
        return t(
          "See the recorded result; no additional conclusion is inferred.",
          "请查看已记录结果，不推断额外结论。",
        )
    }
  }

  return (
    <section
      className="min-w-0 space-y-3 rounded-lg border p-4"
      aria-label={t("Manual review", "人工核查")}
    >
      <h2 className="text-lg font-semibold">
        {t("Manual review", "人工核查")}
      </h2>
      <p className="text-sm text-muted-foreground">
        {t(
          "Save independently of AI availability. Saving or correcting a record never closes a Finding or changes published facts. Each new version waits for a later Run.",
          "无需 AI 可用即可记录。保存或更正不会关闭发现项，也不改变已发布事实；每个新版本重新等待后续运行验证。",
        )}
      </p>
      <p className="text-sm text-muted-foreground">
        {t(
          "Verification only checks whether the original difference is resolved, not whether every explanation in your text is true. NetFlow activity, zero records or missing data alone do not prove resolution.",
          "验证仅判断原差异是否解决，不自动证明人工文字中的全部解释。NetFlow 活动、零记录或数据缺失本身均不能证明已解决。",
        )}
      </p>
      <details className="min-w-0 text-xs">
        <summary className="cursor-pointer font-medium">
          {t(
            "Fixed object and base Run · full identifiers",
            "固定对象与基础运行 · 完整标识",
          )}
        </summary>
        <dl className="mt-2 grid min-w-0 gap-2 sm:grid-cols-2">
          {[
            [t("Project", "项目"), scope.projectId],
            [t("Resource", "资源"), scope.resourceId],
            [t("Base published Run", "基础已发布运行"), scope.runId],
            ...(scope.findingId
              ? [[t("Finding", "发现项"), scope.findingId]]
              : []),
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
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={list.isFetching || save.isPending}
        onClick={() => void list.refetch()}
      >
        {t("Refresh verification", "刷新验证")}
      </Button>
      {list.isPending && (
        <p role="status">{t("Loading manual records…", "正在加载人工记录…")}</p>
      )}
      {list.isError && (
        <Alert variant="destructive">
          <AlertTitle>
            {t("Manual records could not be read", "无法读取人工记录")}
          </AlertTitle>
          <AlertDescription>
            {t(
              "Refresh to read again. No verification outcome is assumed.",
              "请刷新后重新读取，不推定任何验证结果。",
            )}
          </AlertDescription>
        </Alert>
      )}
      {list.isSuccess && !list.data.can_create && (
        <p className="text-sm text-muted-foreground">
          {t(
            "Read-only access. An Operator can save manual records.",
            "当前为只读权限，Operator 可保存人工记录。",
          )}
        </p>
      )}
      {list.isSuccess && list.data.count === 0 && (
        <p className="text-sm text-muted-foreground">
          {t(
            "No manual records for this fixed scope.",
            "此固定范围暂无人工记录。",
          )}
        </p>
      )}
      {save.isError && (
        <Alert variant="destructive">
          <AlertTitle>
            {t(
              "Manual record was not confirmed saved",
              "尚未确认人工记录已保存",
            )}
          </AlertTitle>
          <AlertDescription>
            {save.error instanceof ApiError && save.error.status === 409
              ? t(
                  "A current version already exists or changed. Your text is retained; review the latest version before correcting it.",
                  "当前版本已存在或发生变化。已保留输入，请读取最新版本后再更正。",
                )
              : t(
                  "Your text is retained. Refresh the records to check the result before trying again.",
                  "已保留输入。请刷新记录确认结果后再尝试。",
                )}
          </AlertDescription>
        </Alert>
      )}
      {writable &&
        (list.data.count === 0 ||
          supersedesId !== null ||
          conclusion !== "") && (
          <form
            className="min-w-0 space-y-2"
            onSubmit={(event) => {
              event.preventDefault()
              if (canSave) save.mutate()
            }}
          >
            <h3 className="text-sm font-medium">
              {supersedesId
                ? t("Append a correction", "追加更正版本")
                : t("New manual record", "新增人工记录")}
            </h3>
            <label
              className="block text-sm font-medium"
              htmlFor={`${formId}-conclusion`}
            >
              {t("Manual conclusion", "人工结论")}
            </label>
            <textarea
              id={`${formId}-conclusion`}
              className="block min-h-20 w-full min-w-0 rounded-md border bg-background p-2 text-sm"
              required
              maxLength={4000}
              disabled={save.isPending}
              value={conclusion}
              onChange={(event) => setConclusion(event.target.value)}
            />
            <label
              className="block text-sm font-medium"
              htmlFor={`${formId}-pending`}
            >
              {t("Items to verify", "待验证事项")}
            </label>
            <textarea
              id={`${formId}-pending`}
              className="block min-h-20 w-full min-w-0 rounded-md border bg-background p-2 text-sm"
              required
              maxLength={4000}
              disabled={save.isPending}
              value={pendingVerification}
              onChange={(event) => setPendingVerification(event.target.value)}
            />
            {staleCorrection && (
              <p role="status" className="text-sm">
                {t(
                  "Return to the newest page and select its current version before saving. Your draft is retained.",
                  "请返回最新一页并选择当前版本后保存，草稿已保留。",
                )}
              </p>
            )}
            <Button type="submit" disabled={!canSave}>
              {save.isPending
                ? t("Saving manual record…", "正在保存人工记录…")
                : supersedesId
                  ? t("Save correction", "保存更正")
                  : t("Save manual record", "保存人工记录")}
            </Button>
          </form>
        )}
      {records.map((item) => (
        <article
          key={item.id}
          aria-label={t(
            `Manual record version ${item.version}`,
            `人工记录版本 ${item.version}`,
          )}
          className="min-w-0 space-y-3 border-t pt-3"
        >
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-medium">
              {t(`Version ${item.version}`, `版本 ${item.version}`)}
            </h3>
            {item.is_current && (
              <Badge variant="outline">
                {t("Current version", "当前版本")}
              </Badge>
            )}
            <Badge>{statusLabel(item.status)}</Badge>
          </div>
          <p className="break-words text-xs [overflow-wrap:anywhere]">
            {item.author_name} ·{" "}
            <time dateTime={item.created_at}>
              {formatDate(item.created_at)}
            </time>
          </p>
          <dl className="min-w-0 space-y-2 text-sm">
            <div>
              <dt className="font-medium">
                {t("Manual conclusion", "人工结论")}
              </dt>
              <dd className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
                {item.conclusion}
              </dd>
            </div>
            <div>
              <dt className="font-medium">
                {t("Items to verify", "待验证事项")}
              </dt>
              <dd className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
                {item.pending_verification}
              </dd>
            </div>
          </dl>
          <details className="min-w-0 text-xs">
            <summary className="cursor-pointer font-medium">
              {t("Record identifiers", "记录标识")}
            </summary>
            <dl className="mt-2 space-y-2">
              {[
                [t("Record", "记录"), item.id],
                [t("Author", "作者"), item.author_id],
                ...(item.supersedes_id
                  ? [[t("Corrects record", "更正的记录"), item.supersedes_id]]
                  : []),
              ].map(([label, value]) => (
                <div key={label}>
                  <dt className="font-medium">{label}</dt>
                  <dd>
                    <TechnicalValue value={value} label={label} />
                  </dd>
                </div>
              ))}
            </dl>
          </details>
          {writable && item.is_current && page === 0 && (
            <Button
              type="button"
              variant="outline"
              disabled={!fresh || save.isPending || supersedesId === item.id}
              onClick={() => {
                if (!conclusion && !pendingVerification) {
                  setConclusion(item.conclusion)
                  setPendingVerification(item.pending_verification)
                }
                setSupersedesId(item.id)
                save.reset()
              }}
            >
              {t("Correct current version", "更正当前版本")}
            </Button>
          )}
          <h4 className="text-sm font-medium">
            {t("Subsequent Run verification", "后续运行验证")}
          </h4>
          {item.verifications.length === 0 && (
            <p className="text-sm text-muted-foreground">
              {t(
                "Waiting for a subsequent Run started after this version was saved.",
                "等待此版本保存后启动的后续运行。",
              )}
            </p>
          )}
          {item.verifications.map((verification) => (
            <div
              key={verification.run_id}
              className="min-w-0 space-y-1 rounded-md border p-3 text-xs"
            >
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">
                  {statusLabel(verification.status)}
                </Badge>
                <span>
                  {t("Run status", "运行状态")}:{" "}
                  {translateValue(verification.run_status)}
                </span>
              </div>
              <p>
                {verification.status === "NO_NEW_CONCLUSION"
                  ? t(
                      "This Run adds no usable conclusion; earlier successful verification remains unchanged.",
                      "此运行没有新增可用结论，先前成功验证保持不变。",
                    )
                  : t(
                      "Result from subsequent published facts, not a validation of the full manual explanation.",
                      "结果依据后续已发布事实，不是对人工解释全文的确认。",
                    )}
              </p>
              <p>{reasonLabel(verification.reason)}</p>
              <p>
                {t("Completed", "完成时间")}:{" "}
                {verification.completed_at ? (
                  <time dateTime={verification.completed_at}>
                    {formatDate(verification.completed_at)}
                  </time>
                ) : (
                  t("Not completed", "尚未完成")
                )}
              </p>
              <p>
                {t("Result reference time", "结果依据时间")}:{" "}
                <time dateTime={verification.observed_at}>
                  {formatDate(verification.observed_at)}
                </time>
              </p>
              <details className="min-w-0">
                <summary className="cursor-pointer font-medium">
                  {t(
                    "Verification Run · full identifier and reason",
                    "验证运行 · 完整标识与原因",
                  )}
                </summary>
                <TechnicalValue
                  value={verification.run_id}
                  label={t("Verification Run", "验证运行")}
                />
                <p className="break-all">
                  {t("Reason code", "原因代码")}: {verification.reason}
                </p>
              </details>
            </div>
          ))}
        </article>
      ))}
      {list.isSuccess && (
        <ResultPagination
          label={t("Manual records", "人工记录")}
          count={list.data.count}
          page={page}
          pageSize={PAGE_SIZE}
          onPageChange={setPage}
        />
      )}
    </section>
  )
}
