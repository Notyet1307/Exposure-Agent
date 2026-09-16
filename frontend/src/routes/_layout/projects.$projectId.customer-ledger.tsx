import { useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { useEffect, useRef, useState } from "react"
import {
  ApiError,
  CustomerLedgerService,
  type LedgerEdit,
  type LedgerEntry,
  ProjectsService,
  type app__domain__customer_ledger__RevisionPublic as RevisionPublic,
} from "@/client"
import { ResultPagination } from "@/components/ResultPagination"
import { TechnicalValue } from "@/components/TechnicalValue"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
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
import useAuth from "@/hooks/useAuth"
import { useI18n } from "@/lib/i18n"
import { requestDigest } from "@/lib/ledgerIntent"

const FIELDS = [
  ["asset_ip", "Asset IP", "资产 IP"],
  ["start_port", "Start port", "起始端口"],
  ["end_port", "End port", "结束端口"],
  ["is_web", "Web interface", "是否 Web 界面"],
  ["web_url", "Web URL", "Web 界面 URL"],
  ["service_type", "Service", "服务类型"],
  ["asset_owner", "Declared owner", "原声明负责人"],
  ["asset_department", "Asset department", "资产所属部门"],
  ["port_owner", "Port owner", "端口负责人"],
  ["department", "Department", "部门"],
  ["serial", "Source number", "原序号"],
] as const
const display = (value: LedgerEntry["fields"][string]) =>
  value === null || value === undefined
    ? ""
    : typeof value === "object"
      ? value.value
      : String(value)
const PAGE_SIZE = 25
const text = (value: unknown) => (typeof value === "string" ? value : undefined)
export const Route = createFileRoute(
  "/_layout/projects/$projectId/customer-ledger",
)({
  component: CustomerLedger,
  validateSearch: (search: Record<string, unknown>) => ({
    ledger_upload: text(search.ledger_upload),
    ledger_revision: text(search.ledger_revision),
    ledger_query: text(search.ledger_query),
    ledger_ip: text(search.ledger_ip),
    ledger_page:
      Number.isSafeInteger(Number(search.ledger_page)) &&
      Number(search.ledger_page) > 0
        ? Number(search.ledger_page)
        : 1,
    ledger_archived:
      search.ledger_archived === true || search.ledger_archived === "true",
  }),
})

type PendingIntent = {
  key: string
  digest: string
  base: Pick<
    LedgerEdit,
    | "expected_upload_id"
    | "expected_revision_id"
    | "expected_profile_id"
    | "operation"
    | "entry_id"
  >
}
const initialFields = {
  asset_ip: "",
  start_port: 443,
  end_port: 443,
  is_web: "否",
  web_url: null,
}

function CustomerLedger() {
  const { projectId } = Route.useParams()
  const { user } = useAuth()
  const { t } = useI18n()
  useEffect(() => {
    document.title = t("Customer ledger - Exposure", "客户资产台账 - Exposure")
  }, [t])
  return user ? (
    <LedgerView
      key={`${user.id}:${projectId}`}
      actorId={user.id}
      projectId={projectId}
    />
  ) : null
}

function LedgerView({
  actorId,
  projectId,
}: {
  actorId: string
  projectId: string
}) {
  const { t, formatDate } = useI18n()
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  const cache = useQueryClient()
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  const recoveryName = `exposure:ledger:${actorId}:${projectId}`
  const viewScope = `${search.ledger_upload ?? "current"}/${search.ledger_revision ?? "original"}`
  const scopeRef = useRef(viewScope)
  scopeRef.current = viewScope
  const isCurrent = (scope: string) =>
    alive.current && scopeRef.current === scope
  const [pending, setPending] = useState<PendingIntent | null>(() => {
    try {
      const item = JSON.parse(
        sessionStorage.getItem(recoveryName) ?? "null",
      ) as PendingIntent | null
      return item &&
        /^[A-Za-z0-9_-]{1,128}$/.test(item.key) &&
        /^[a-f0-9]{64}$/.test(item.digest) &&
        item.base?.expected_upload_id
        ? item
        : null
    } catch {
      return null
    }
  })
  const pendingKey = pending?.key
  const pendingScope = pending
    ? `${pending.base.expected_upload_id}/${pending.base.expected_revision_id ?? "original"}`
    : undefined
  const pendingHere = pendingScope === viewScope
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState("")
  const [query, setQuery] = useState(search.ledger_query ?? "")
  const [editState, updateEditor] = useState<{
    scope: string
    body: LedgerEdit
  } | null>(null)
  const [selection, updateSelection] = useState<{
    scope: string
    row: LedgerEntry
  } | null>(null)
  const editor = editState?.scope === viewScope ? editState.body : null
  const selected = selection?.scope === viewScope ? selection.row : null
  const setEditor = (body: LedgerEdit | null) =>
    updateEditor(body ? { scope: scopeRef.current, body } : null)
  const setSelected = (row: LedgerEntry | null) =>
    updateSelection(row ? { scope: scopeRef.current, row } : null)
  useEffect(() => {
    if (editState && editState.scope !== viewScope) updateEditor(null)
    if (selection && selection.scope !== viewScope) updateSelection(null)
  }, [viewScope, editState, selection])
  const [historyPage, setHistoryPage] = useState(0)
  const heading = useRef<HTMLHeadingElement>(null)
  const ledger = useQuery({
    queryKey: [
      "customer-ledger",
      actorId,
      projectId,
      search.ledger_upload,
      search.ledger_revision,
      search.ledger_query,
      search.ledger_ip,
      search.ledger_page,
      search.ledger_archived,
    ],
    queryFn: () =>
      CustomerLedgerService.readCustomerLedger({
        projectId,
        uploadId: search.ledger_upload,
        revisionId: search.ledger_revision,
        query: search.ledger_query,
        ip: search.ledger_ip,
        archived: search.ledger_archived,
        skip: (search.ledger_page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
    retry: false,
  })
  const history = useQuery({
    queryKey: ["customer-ledger-history", actorId, projectId, historyPage],
    queryFn: () =>
      CustomerLedgerService.readCustomerLedgerRevisions({
        projectId,
        skip: historyPage * 25,
        limit: 25,
      }),
    retry: false,
  })
  const originals = useQuery({
    queryKey: ["customer-ledger-inputs", actorId, projectId, historyPage],
    queryFn: () =>
      ProjectsService.readCustomerUploads({
        projectId,
        skip: historyPage * 25,
        limit: 25,
      }),
    retry: false,
  })
  const data = ledger.data?.project_id === projectId ? ledger.data : undefined
  const canEdit = !!data?.can_edit && !ledger.isError
  useEffect(() => {
    if (
      ledger.isSuccess &&
      !ledger.isFetching &&
      data?.upload_id &&
      !search.ledger_upload &&
      !search.ledger_revision
    ) {
      void navigate({
        replace: true,
        search: (old) => ({
          ...old,
          ledger_upload: data.upload_id!,
          ledger_revision: data.revision_id ?? undefined,
        }),
      })
    }
  }, [
    data,
    navigate,
    search.ledger_upload,
    search.ledger_revision,
    ledger.isSuccess,
    ledger.isFetching,
  ])
  const showVersion = (uploadId?: string, revisionId?: string) => {
    setSelected(null)
    void navigate({
      search: (old) => ({
        ...old,
        ledger_upload: uploadId,
        ledger_revision: revisionId,
        ledger_page: 1,
      }),
    })
  }
  const failure = (error: unknown) => {
    const detail: unknown =
      error instanceof ApiError &&
      error.body &&
      typeof error.body === "object" &&
      "detail" in error.body
        ? error.body.detail
        : undefined
    const code =
      detail &&
      typeof detail === "object" &&
      "code" in detail &&
      typeof detail.code === "string"
        ? detail.code
        : ""
    const messages: Record<string, string> = {
      ledger_last_entry: t(
        "Keep at least one valid record. Empty inputs are not supported.",
        "至少保留一条有效记录，当前不支持空客户输入。",
      ),
      ledger_version_conflict: t(
        "The current input changed. Your edits are retained; review the latest version before resubmitting.",
        "当前输入已变化。已保留填写内容，请核对新版本后重新更正。",
      ),
      ledger_fields_invalid: t(
        "Check the IP, ports and Web fields. Start and end ports must match.",
        "请检查 IP、端口和 Web 字段；起始与结束端口须相同。",
      ),
      ledger_source_invalid: t(
        "The input could not be verified. No empty ledger was substituted.",
        "无法验证输入完整性，未将错误内容显示为空台账。",
      ),
      ledger_operation_not_found: t(
        "No saved result was found for this request. No new request was sent.",
        "尚未查到该请求的保存结果，未重新发送操作。",
      ),
    }
    return (
      messages[code] ??
      t(
        "Unable to complete this operation. Check permissions and recover the original request if its result is unknown.",
        "操作未完成。请核对权限；结果未知时查询原请求，不要重复提交。",
      )
    )
  }
  const finish = async (revision: RevisionPublic, requestScope: string) => {
    if (!isCurrent(requestScope)) return
    sessionStorage.removeItem(recoveryName)
    setPending(null)
    setEditor(null)
    setSelected(null)
    await cache.invalidateQueries({ queryKey: ["customer-ledger"] })
    await cache.invalidateQueries({
      queryKey: ["customer-ledger-history", actorId, projectId],
    })
    await cache.invalidateQueries({
      queryKey: ["customer-ledger-inputs", actorId, projectId],
    })
    await cache.invalidateQueries({ queryKey: ["customer-uploads", projectId] })
    if (!isCurrent(requestScope)) return
    await navigate({
      search: (old) => ({
        ...old,
        ledger_upload: revision.upload_id,
        ledger_revision: revision.id,
        ledger_page: 1,
      }),
    })
    if (!isCurrent(`${revision.upload_id}/${revision.id}`)) return
    setNotice("saved")
    heading.current?.focus()
  }
  const submit = async () => {
    if (!editor || busy || (!canEdit && !pending) || (pending && !pendingHere))
      return
    const requestScope = scopeRef.current
    const body = structuredClone(editor)
    setBusy(true)
    setNotice("")
    try {
      const digest = await requestDigest(body)
      if (!isCurrent(requestScope)) return
      if (pending && digest !== pending.digest) {
        setNotice(
          t(
            "Re-enter exactly the original change and reason before restoring this request.",
            "请重新填写与原请求一致的修改和理由，再恢复原操作。",
          ),
        )
        return
      }
      const intent: PendingIntent = pending ?? {
        key: crypto.randomUUID(),
        digest,
        base: {
          expected_upload_id: body.expected_upload_id,
          expected_revision_id: body.expected_revision_id,
          expected_profile_id: body.expected_profile_id,
          operation: body.operation,
          entry_id: body.entry_id,
        },
      }
      try {
        sessionStorage.setItem(recoveryName, JSON.stringify(intent))
      } catch {
        setNotice(
          t(
            "Session storage is unavailable; nothing was submitted.",
            "无法保存恢复身份，操作尚未提交。",
          ),
        )
        return
      }
      setPending(intent)
      await finish(
        await CustomerLedgerService.createCustomerLedgerRevision({
          projectId,
          idempotencyKey: intent.key,
          requestBody: body,
        }),
        requestScope,
      )
    } catch (error) {
      if (!isCurrent(requestScope)) return
      if (
        error instanceof ApiError &&
        [400, 401, 403, 404, 409, 422].includes(error.status)
      ) {
        sessionStorage.removeItem(recoveryName)
        setPending(null)
      }
      setNotice(failure(error))
    } finally {
      if (alive.current) setBusy(false)
    }
  }
  const recover = async () => {
    if (!pending || !pendingHere || busy) return
    const requestScope = scopeRef.current
    setBusy(true)
    try {
      await finish(
        await CustomerLedgerService.readCustomerLedgerOperation({
          projectId,
          operationKey: pending.key,
        }),
        requestScope,
      )
    } catch (error) {
      if (isCurrent(requestScope)) setNotice(failure(error))
    } finally {
      if (alive.current) setBusy(false)
    }
  }
  const restoreOriginal = async () => {
    if (!pending || !pendingHere || busy) return
    const requestScope = scopeRef.current
    setBusy(true)
    try {
      const base = pending.base
      const original = await CustomerLedgerService.readCustomerLedger({
        projectId,
        uploadId: base.expected_upload_id,
        revisionId: base.expected_revision_id ?? undefined,
        query: base.entry_id ?? undefined,
        limit: 1,
      })
      if (!isCurrent(requestScope)) return
      const row = original.data?.find((item) => item.entry_id === base.entry_id)
      if (base.operation !== "add" && !row)
        throw new Error("Original entry unavailable")
      await navigate({
        search: (old) => ({
          ...old,
          ledger_upload: base.expected_upload_id,
          ledger_revision: base.expected_revision_id ?? undefined,
          ledger_page: 1,
        }),
      })
      if (
        !isCurrent(
          `${base.expected_upload_id}/${base.expected_revision_id ?? "original"}`,
        )
      )
        return
      setEditor({
        ...base,
        reason: "",
        fields:
          base.operation === "add"
            ? { ...initialFields }
            : base.operation === "update"
              ? { ...row!.fields }
              : {},
        management:
          base.operation === "manage" ? { ...row?.management } : undefined,
      })
      setNotice(
        t(
          "Re-enter the original change and reason. Confirmation reuses its key and may submit it for the first time.",
          "请重填原修改和理由。确认将复用原标识；若请求此前未到达，可能首次提交。",
        ),
      )
    } catch (error) {
      if (alive.current) setNotice(failure(error))
    } finally {
      if (alive.current) setBusy(false)
    }
  }
  const refreshCurrent = async () => {
    if (busy || editor) return
    const requestScope = scopeRef.current
    setBusy(true)
    try {
      const fresh = await CustomerLedgerService.readCustomerLedger({
        projectId,
      })
      if (!isCurrent(requestScope)) return
      if (fresh.project_id !== projectId) throw new Error("Project mismatch")
      await cache.invalidateQueries({
        queryKey: ["customer-ledger", actorId, projectId],
      })
      if (isCurrent(requestScope))
        showVersion(
          fresh.upload_id ?? undefined,
          fresh.revision_id ?? undefined,
        )
    } catch (error) {
      if (isCurrent(requestScope)) setNotice(failure(error))
    } finally {
      if (alive.current) setBusy(false)
    }
  }
  const start = (operation: LedgerEdit["operation"], row?: LedgerEntry) => {
    if (!data?.upload_id || !canEdit || pendingKey) return
    setSelected(row ?? null)
    setNotice("")
    setEditor({
      expected_upload_id: data.upload_id,
      expected_revision_id: data.revision_id,
      expected_profile_id: data.current_profile_id,
      operation,
      entry_id: row?.entry_id ?? null,
      reason: "",
      fields:
        operation === "add"
          ? {
              asset_ip: "",
              start_port: 443,
              end_port: 443,
              is_web: "否",
              web_url: null,
            }
          : operation === "update"
            ? { ...row!.fields }
            : {},
      management: operation === "manage" ? { ...row?.management } : undefined,
    })
  }
  const locked = busy || !!pendingKey || !canEdit
  return (
    <div className="min-w-0 space-y-6">
      <header className="space-y-3">
        <h1
          ref={heading}
          tabIndex={-1}
          className="text-2xl font-bold tracking-tight"
        >
          {t("Customer asset ledger", "客户资产台账")}
        </h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          {t(
            "Manage customer records and their revisions. Changes apply to future Runs; published reports keep their original inputs.",
            "管理客户原生记录与修订。更正用于后续新批次，已发布报告保留原输入。",
          )}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline">
            <Link to="/" search={{ project: projectId, view: "inputs" }}>
              {t("Import / select input", "导入 / 选择输入")}
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link to="/" search={{ project: projectId, view: "runs" }}>
              {t("Confirm a new Run", "确认新批次")}
            </Link>
          </Button>
          <Button
            variant="outline"
            disabled={busy || !!editor}
            onClick={() => void refreshCurrent()}
          >
            {t("Read current version", "读取当前版本")}
          </Button>
          {canEdit && (
            <Button disabled={locked || !!editor} onClick={() => start("add")}>
              {t("Add record", "新增记录")}
            </Button>
          )}
        </div>
      </header>
      {notice && (
        <Alert role="status">
          <AlertDescription>
            {notice === "saved"
              ? t(
                  "Saved a new revision. Existing Run reports are unchanged.",
                  "新修订已保存，已有批次报告保持不变。",
                )
              : notice}
          </AlertDescription>
        </Alert>
      )}
      {pendingKey && pendingHere && (
        <Alert>
          <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
            <span>
              {t(
                "This request has an unconfirmed result. Recover it before making another change.",
                "原请求结果尚未确认，查询其结果后再做新的修改。",
              )}
            </span>
            <Button variant="outline" disabled={busy} onClick={recover}>
              {t("Query original request", "查询原请求")}
            </Button>
            {!editor && (
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => void restoreOriginal()}
              >
                {t("Re-enter original request", "重填原请求")}
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}
      {pendingKey && !pendingHere && (
        <Alert>
          <AlertDescription className="flex flex-wrap items-center gap-3">
            <span>
              {t(
                "Another version has an unconfirmed request. Return to its original version to recover it.",
                "另一版本有尚未确认的请求，请返回其原版本后恢复。",
              )}
            </span>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() =>
                showVersion(
                  pending!.base.expected_upload_id,
                  pending!.base.expected_revision_id ?? undefined,
                )
              }
            >
              {t("Return to original version", "返回原请求版本")}
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {ledger.isPending ? (
        <p role="status">{t("Loading ledger…", "正在读取台账…")}</p>
      ) : ledger.isError || !data ? (
        <Alert variant="destructive">
          <AlertDescription>
            {failure(ledger.error)}{" "}
            <Button variant="outline" onClick={() => void ledger.refetch()}>
              {t("Retry reading", "重试读取")}
            </Button>
          </AlertDescription>
        </Alert>
      ) : !data.upload_id ? (
        <p>
          {t(
            "No input is selected. Import and select a customer workbook first.",
            "尚未选中客户输入，请先导入并选择客户表格。",
          )}
        </p>
      ) : (
        <>
          <section
            aria-label={t("Version scope", "版本范围")}
            className="space-y-2 border-b pb-4"
          >
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold">
                {data.revision
                  ? t("Manual revision", "人工修订")
                  : t("Accepted input", "已接受输入")}
              </h2>
              <Badge variant="outline">
                {data.upload_id === data.current_upload_id &&
                data.revision_id === data.current_revision_id
                  ? t("Current", "当前版本")
                  : t("Historical", "历史版本")}
              </Badge>
            </div>
            <p className="text-sm break-words">
              {t("Input accepted", "输入接受于")} ·{" "}
              {data.source_created_at
                ? formatDate(data.source_created_at)
                : "—"}{" "}
              · {data.total_records} {t("active records", "有效记录")} ·{" "}
              {data.unique_ips} {t("distinct IPs", "个独立 IP")}
            </p>
            <p className="text-sm text-muted-foreground">
              {t(
                "This Project · Customer ledger facts",
                "本项目 · 客户台账资料",
              )}
            </p>
            {data.revision && (
              <p className="text-sm">
                {formatDate(data.revision.created_at)} · {data.revision.reason}
              </p>
            )}
            <details className="text-sm">
              <summary className="cursor-pointer">
                {t("Version evidence", "查看版本依据")}
              </summary>
              <div className="mt-2 space-y-2">
                <p className="break-all">{data.filename}</p>
                <TechnicalValue value={data.upload_id} label="CustomerUpload" />
                <TechnicalValue
                  value={data.upload_sha256 ?? ""}
                  label="SHA-256"
                />
                {data.revision_id && (
                  <TechnicalValue value={data.revision_id} label="Revision" />
                )}
              </div>
            </details>
          </section>
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(event) => {
              event.preventDefault()
              void navigate({
                search: (old) => ({
                  ...old,
                  ledger_query: query || undefined,
                  ledger_page: 1,
                }),
              })
            }}
          >
            <div className="min-w-0 flex-1">
              <Label htmlFor="ledger-query">
                {t("Search IP, owner or tag", "搜索 IP、负责人或标签")}
              </Label>
              <Input
                id="ledger-query"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                maxLength={200}
              />
            </div>
            <Button variant="outline" type="submit">
              {t("Search", "查询")}
            </Button>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={search.ledger_archived}
                onChange={(e) =>
                  void navigate({
                    search: (old) => ({
                      ...old,
                      ledger_archived: e.target.checked,
                      ledger_page: 1,
                    }),
                  })
                }
              />
              {t("Archived records", "已归档记录")}
            </label>
          </form>
          {search.ledger_ip && (
            <p className="flex flex-wrap items-center gap-3">
              <strong>
                {t("Customer IP dossier", "客户 IP 画像")}: {search.ledger_ip}
              </strong>
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  void navigate({
                    search: (old) => ({
                      ...old,
                      ledger_ip: undefined,
                      ledger_page: 1,
                    }),
                  })
                }
              >
                {t("All IPs", "全部 IP")}
              </Button>
            </p>
          )}
          <div className="space-y-3">
            <p className="text-sm">
              {data.count} {t("matching source records", "条匹配原生记录")}
            </p>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>IP</TableHead>
                  <TableHead>{t("Port / Web", "端口 / Web")}</TableHead>
                  <TableHead>{t("Declared owner", "原声明负责人")}</TableHead>
                  <TableHead>{t("Local management", "本地管理")}</TableHead>
                  <TableHead>{t("Actions", "操作")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(data.data ?? []).map((row) => (
                  <TableRow key={row.entry_id}>
                    <TableCell>
                      <button
                        type="button"
                        className="text-left underline underline-offset-4"
                        onClick={() => {
                          setSelected(row)
                          void navigate({
                            search: (old) => ({
                              ...old,
                              ledger_ip: row.canonical_ip,
                              ledger_page: 1,
                            }),
                          })
                        }}
                      >
                        {row.canonical_ip}
                      </button>
                      <p className="text-xs text-muted-foreground">
                        {t("Record", "条目")} {row.position}
                      </p>
                    </TableCell>
                    <TableCell>
                      {display(row.fields.start_port)} ·{" "}
                      {row.fields.is_web === "是" ? "Web" : "—"}
                    </TableCell>
                    <TableCell>
                      {display(row.fields.asset_owner) ||
                        t("Not provided", "未提供")}
                    </TableCell>
                    <TableCell>
                      <p>
                        {row.management?.owner || t("Unconfirmed", "未确认")}
                      </p>
                      <p className="text-xs">
                        {row.management?.tags?.join(" · ")}
                      </p>
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => {
                            setSelected(row)
                            setEditor(null)
                          }}
                          disabled={!!editor || busy}
                        >
                          {t("Details", "详情")}
                        </Button>
                        {canEdit && !row.archived && (
                          <>
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={locked || !!editor}
                              onClick={() => start("update", row)}
                            >
                              {t("Correct", "更正")}
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={locked || !!editor}
                              onClick={() => start("manage", row)}
                            >
                              {t("Manage", "管理")}
                            </Button>
                          </>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {!data.count && (
              <p>
                {t(
                  "No matching records in this version.",
                  "此版本没有匹配记录。",
                )}
              </p>
            )}
            <ResultPagination
              label={t("Ledger", "台账")}
              count={data.count ?? 0}
              page={search.ledger_page - 1}
              pageSize={PAGE_SIZE}
              onPageChange={(page) =>
                void navigate({
                  search: (old) => ({ ...old, ledger_page: page + 1 }),
                })
              }
            />
          </div>
          {selected && !editor && (
            <section className="space-y-4 border-t pt-5">
              <h2 className="text-lg font-semibold">
                {selected.canonical_ip} · {t("Source record", "原生条目")}{" "}
                {selected.position}
              </h2>
              <Button asChild variant="outline">
                <Link
                  to="/projects/$projectId/cloudatlas-ledger"
                  params={{ projectId }}
                  search={{
                    cloud_source: undefined,
                    cloud_snapshot: undefined,
                    cloud_revision: undefined,
                    cloud_page: 0,
                    cloud_ip: undefined,
                    cloud_asset: undefined,
                    profile_ip: selected.canonical_ip,
                    customer_upload: data.upload_id ?? undefined,
                    customer_revision: data.revision_id ?? undefined,
                    customer_page: 0,
                    profile_cloud_page: 0,
                  }}
                >
                  {t("View with CloudAtlas source", "结合云图来源查看画像")}
                </Link>
              </Button>
              <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {FIELDS.map(([name, en, zh]) => (
                  <div key={name}>
                    <dt className="text-sm text-muted-foreground">
                      {t(en, zh)}
                    </dt>
                    <dd className="break-words">
                      {display(selected.fields[name]) || "—"}
                    </dd>
                  </div>
                ))}
              </dl>
              {canEdit && !selected.archived && (
                <Button
                  variant="outline"
                  disabled={locked}
                  onClick={() => start("archive", selected)}
                >
                  {t("Archive this record", "归档此条目")}
                </Button>
              )}
            </section>
          )}
          {editor && (
            <form
              className="space-y-4 border-t pt-5"
              onSubmit={(e) => {
                e.preventDefault()
                void submit()
              }}
            >
              <h2 className="text-lg font-semibold">
                {editor.operation === "add"
                  ? t("Add customer record", "新增客户记录")
                  : editor.operation === "manage"
                    ? t("Local management fields", "本地管理字段")
                    : editor.operation === "archive"
                      ? t("Archive customer record", "归档客户记录")
                      : t("Correct customer record", "更正客户记录")}
              </h2>
              {(editor.operation === "add" ||
                editor.operation === "update") && (
                <p className="text-sm text-muted-foreground">
                  {t(
                    "Derived files contain only supported fields. The original file and its other columns remain in the previous input.",
                    "派生文件仅包含当前支持字段，原文件及其他列保留在旧输入中。",
                  )}
                </p>
              )}
              {editor.operation === "archive" ? (
                <p>
                  {t(
                    "The record is excluded from the new input; old versions remain readable. At least one active record must remain.",
                    "该条目将从新输入排除，旧版本仍可读取；必须保留至少一条有效记录。",
                  )}
                </p>
              ) : editor.operation === "manage" ? (
                <div className="grid gap-4 sm:grid-cols-2">
                  {(
                    [
                      ["owner", "Confirmed owner", "确认负责人"],
                      ["department", "Confirmed department", "确认部门"],
                    ] as const
                  ).map(([field, en, zh]) => (
                    <div key={field}>
                      <Label htmlFor={`manage-${field}`}>{t(en, zh)}</Label>
                      <Input
                        id={`manage-${field}`}
                        maxLength={255}
                        value={editor.management?.[field] ?? ""}
                        onChange={(e) =>
                          setEditor({
                            ...editor,
                            management: {
                              ...editor.management,
                              [field]: e.target.value,
                            },
                          })
                        }
                      />
                    </div>
                  ))}
                  <div>
                    <Label htmlFor="manage-tags">
                      {t("Tags (comma separated)", "标签（逗号分隔）")}
                    </Label>
                    <Input
                      id="manage-tags"
                      value={editor.management?.tags?.join(",") ?? ""}
                      onChange={(e) =>
                        setEditor({
                          ...editor,
                          management: {
                            ...editor.management,
                            tags: e.target.value.split(/[,，]/).filter(Boolean),
                          },
                        })
                      }
                    />
                  </div>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={editor.management?.followed ?? false}
                      onChange={(e) =>
                        setEditor({
                          ...editor,
                          management: {
                            ...editor.management,
                            followed: e.target.checked,
                          },
                        })
                      }
                    />
                    {t("Follow this record", "关注此条目")}
                  </label>
                </div>
              ) : (
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {FIELDS.map(([name, en, zh]) => (
                    <div key={name}>
                      <Label htmlFor={`edit-${name}`}>{t(en, zh)}</Label>
                      {name === "is_web" ? (
                        <select
                          id={`edit-${name}`}
                          className="h-9 w-full rounded-md border bg-background px-3 text-sm"
                          value={display(editor.fields?.[name] ?? null)}
                          onChange={(e) =>
                            setEditor({
                              ...editor,
                              fields: {
                                ...editor.fields,
                                [name]: e.target.value,
                              },
                            })
                          }
                        >
                          {["是", "否", "无"].map((v) => (
                            <option key={v} value={v}>
                              {t(
                                v === "是" ? "Yes" : v === "否" ? "No" : "None",
                                v,
                              )}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <Input
                          id={`edit-${name}`}
                          maxLength={32767}
                          required={[
                            "asset_ip",
                            "start_port",
                            "end_port",
                          ].includes(name)}
                          value={display(editor.fields?.[name] ?? null)}
                          onChange={(e) =>
                            setEditor({
                              ...editor,
                              fields: {
                                ...editor.fields,
                                [name]: e.target.value || null,
                              },
                            })
                          }
                        />
                      )}
                    </div>
                  ))}
                </div>
              )}
              <div>
                <Label htmlFor="ledger-reason">
                  {t("Reason for this change", "变更理由")}
                </Label>
                <textarea
                  className="min-h-20 w-full rounded-md border bg-background px-3 py-2 text-sm"
                  id="ledger-reason"
                  required
                  maxLength={1000}
                  value={editor.reason}
                  onChange={(e) =>
                    setEditor({ ...editor, reason: e.target.value })
                  }
                />
              </div>
              <div className="flex flex-wrap gap-3">
                <Button
                  type="submit"
                  disabled={
                    busy || (!canEdit && !pending) || !editor.reason.trim()
                  }
                  aria-busy={busy}
                >
                  {busy
                    ? t("Saving…", "正在保存…")
                    : pending
                      ? t("Confirm original request", "确认原请求")
                      : t("Save new revision", "保存新修订")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => {
                    setEditor(null)
                    heading.current?.focus()
                  }}
                >
                  {t("Cancel editing", "取消编辑")}
                </Button>
              </div>
            </form>
          )}
        </>
      )}
      <details className="border-t pt-4">
        <summary className="cursor-pointer font-medium">
          {t("Input versions and edit history", "输入版本与编辑历史")}
        </summary>
        <div className="mt-4 space-y-4">
          {history.isError || originals.isError ? (
            <p>{t("History could not be loaded.", "历史读取失败。")}</p>
          ) : (
            <>
              <ul className="space-y-2">
                {history.data?.map((revision) => (
                  <li
                    key={revision.id}
                    className="flex flex-wrap items-center gap-3"
                  >
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!!editor || busy}
                      onClick={() =>
                        showVersion(revision.upload_id, revision.id)
                      }
                    >
                      {formatDate(revision.created_at)}
                    </Button>
                    <span className="break-words text-sm">
                      {revision.reason} ·{" "}
                      {revision.input_changed
                        ? t("Input changed", "输入更正")
                        : t("Input unchanged", "输入未变")}
                    </span>
                  </li>
                ))}
              </ul>
              <ul className="space-y-2">
                {originals.data?.data.map((upload) => (
                  <li key={upload.id}>
                    <Button
                      size="sm"
                      variant="outline"
                      className="max-w-full whitespace-normal text-left"
                      disabled={!!editor || busy}
                      onClick={() => showVersion(upload.id)}
                    >
                      {upload.display_filename} ·{" "}
                      {formatDate(upload.created_at)}
                    </Button>
                  </li>
                ))}
              </ul>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!historyPage}
                  onClick={() => setHistoryPage(historyPage - 1)}
                >
                  {t("Previous", "上一页")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={
                    (history.data?.length ?? 0) < 25 &&
                    (originals.data?.data.length ?? 0) < 25
                  }
                  onClick={() => setHistoryPage(historyPage + 1)}
                >
                  {t("Next", "下一页")}
                </Button>
              </div>
            </>
          )}
        </div>
      </details>
    </div>
  )
}
