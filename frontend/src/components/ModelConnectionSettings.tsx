import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useEffect, useRef, useState } from "react"
import { z } from "zod"
import {
  ApiError,
  type ConnectionActionPublic,
  type ConnectionPublic,
  type OperationPublic,
  type SaveConnection,
  ModelConnectionsService as Service,
} from "@/client"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import useAuth from "@/hooks/useAuth"
import { useI18n } from "@/lib/i18n"

const intentSchema = z
  .object({
    key: z.string().uuid(),
    action: z.enum([
      "save",
      "adopt",
      "validate",
      "activate",
      "revoke",
      "discard",
    ]),
    connection: z.string().uuid().optional(),
  })
  .strict()
type Intent = z.infer<typeof intentSchema>
const terminal = (op: OperationPublic) =>
  ["SUCCEEDED", "FAILED"].includes(op.status)

const failureCopy: Record<string, readonly [string, string]> = {
  model_connection_generation_conflict: [
    "The connection state changed. Read the current state before starting a new operation.",
    "连接状态已变化。请重新读取当前状态，再发起新的操作。",
  ],
  model_connection_intent_conflict: [
    "This key belongs to different inputs. Query the original operation; do not create a duplicate version.",
    "此操作 key 已绑定其他内容。请查询原操作，不要重复创建版本。",
  ],
  model_connection_secret_unavailable: [
    "The deployment cannot resolve its protected credentials. Ask the deployment administrator to check the master key.",
    "部署无法解析受保护凭据。请联系部署管理员检查主密钥。",
  ],
  legacy_binding_unknown: [
    "An existing task or session is not confirmed as finished. Confirm its state before activating this connection.",
    "现有任务或会话尚未确认结束。请先确认其状态，再启用连接。",
  ],
  model_binding_changed: [
    "The connection binding changed. Verify this version again before activation.",
    "连接绑定已变化。请重新验证此版本后再启用。",
  ],
  model_not_qualified: [
    "Verification is not established. Verify this version before activation.",
    "尚无有效验证。请先验证此版本再启用。",
  ],
}

function StateLabel({ value }: { value: string }) {
  const { t } = useI18n()
  const labels: Record<string, readonly [string, string]> = {
    unconfigured: ["Not configured", "未配置"],
    legacy: ["Deployment connection", "现有部署连接"],
    active: ["Active", "已启用"],
    disabled: ["Disabled", "已禁用"],
    unavailable: ["Unavailable", "暂不可用"],
    UNVERIFIED: ["Not verified", "未验证"],
    VALIDATING: ["Verifying", "验证中"],
    VALIDATED: ["Passed", "通过"],
    ACTIVATING: ["Preparing activation", "准备启用"],
    NOT_RUN: ["Not verified", "未验证"],
    PENDING: ["Not verified", "未验证"],
    RUNNING: ["Verifying", "验证中"],
    RESERVED: ["Preparing", "准备中"],
    PASS: ["Passed", "通过"],
    SUCCEEDED: ["Completed", "已完成"],
    FAIL: ["Failed", "失败"],
    FAILED: ["Failed", "失败"],
    UNKNOWN: ["Unconfirmed", "结果未知"],
  }
  const label = labels[value] ?? ["Not verified", "未验证"]
  return <span>{t(label[0], label[1])}</span>
}

export default function ModelConnectionSettings() {
  const { user, userError, refetchUser, logout } = useAuth()
  const { t } = useI18n()
  useEffect(() => {
    document.title = t(
      "AI settings - Exposure-Agent",
      "AI 设置 - Exposure-Agent",
    )
  }, [t])
  if (userError)
    return (
      <Alert variant="destructive">
        <AlertDescription>
          {t("Permissions could not be read.", "无法读取权限。")}
          <Button variant="outline" onClick={() => void refetchUser()}>
            {t("Retry permission check", "重新读取权限")}
          </Button>
          <Button variant="ghost" onClick={logout}>
            {t("Sign in again", "重新登录")}
          </Button>
        </AlertDescription>
      </Alert>
    )
  if (!user)
    return <p role="status">{t("Checking permissions…", "正在读取权限…")}</p>
  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">
          {t("AI settings", "AI 设置")}
        </h1>
        <p className="max-w-prose text-muted-foreground">
          {t(
            "Save a connection, verify it, then activate it for new AI tasks.",
            "保存连接，验证通过后，再启用到新的 AI 任务。",
          )}
        </p>
      </header>
      <Availability key={`status:${user.id}`} actor={user.id} />
      {user.is_superuser ? (
        <Management key={user.id} actor={user.id} />
      ) : (
        <p>
          {t(
            "Only an administrator can manage model connections. Contact your administrator to make changes.",
            "只有管理员可以管理模型连接。如需变更，请联系管理员。",
          )}
        </p>
      )}
    </div>
  )
}

function Availability({ actor }: { actor: string }) {
  const { t } = useI18n()
  const query = useQuery({
    queryKey: ["model-connection-status", actor],
    queryFn: () => Service.status(),
    retry: false,
  })
  return (
    <section
      aria-label={t("AI availability", "AI 可用性")}
      className="space-y-2 border-b pb-6"
    >
      <h2 className="font-semibold">
        {t("Current availability", "当前可用性")}
      </h2>
      {query.isError ? (
        <p role="alert">
          {t("Availability could not be read.", "无法读取可用性。")}
        </p>
      ) : query.data ? (
        <>
          <p>
            <StateLabel value={query.data.state} />
            {query.data.model_identity && (
              <span className="ml-3 break-all text-muted-foreground">
                {query.data.model_identity}
              </span>
            )}
          </p>
          <p className="text-sm text-muted-foreground">
            {query.data.ready
              ? t(
                  "Connection is ready. Project access and material permissions are checked separately.",
                  "连接已就绪，项目访问和材料许可仍会单独检查。",
                )
              : t(
                  "AI readiness is not established. Deterministic comparisons and historical results remain available.",
                  "AI 尚未就绪。确定性比对和历史结果仍可使用。",
                )}
          </p>
        </>
      ) : (
        <p role="status">{t("Loading…", "正在读取…")}</p>
      )}
      <Button
        size="sm"
        variant="ghost"
        disabled={query.isFetching}
        onClick={() => void query.refetch()}
      >
        {t("Refresh status", "刷新状态")}
      </Button>
    </section>
  )
}

function Management({ actor }: { actor: string }) {
  const { t } = useI18n()
  const { logout } = useAuth()
  const cache = useQueryClient()
  const storageKey = `exposure:model-connection:${actor}`
  const [initial] = useState(() => {
    try {
      const raw = sessionStorage.getItem(storageKey)
      return {
        intent: raw ? intentSchema.parse(JSON.parse(raw)) : null,
        invalid: false,
      }
    } catch {
      return { intent: null, invalid: true }
    }
  })
  const [intent, setIntent] = useState<Intent | null>(initial.intent)
  const [last, setLast] = useState<OperationPublic | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("")
  const [locked, setLocked] = useState(false)
  const [rejected, setRejected] = useState(false)
  const form = useRef<HTMLFormElement>(null)
  const secret = useRef<HTMLInputElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const alive = useRef(true)
  const sending = useRef(false)
  const [token] = useState(() => localStorage.getItem("access_token"))
  const current = useCallback(
    () => alive.current && token === localStorage.getItem("access_token"),
    [token],
  )
  useEffect(() => {
    alive.current = true
    const clear = () => form.current?.reset()
    window.addEventListener("pagehide", clear)
    return () => {
      alive.current = false
      clear()
      window.removeEventListener("pagehide", clear)
    }
  }, [])
  const stateKey = ["model-connections", actor]
  const state = useQuery({
    queryKey: stateKey,
    queryFn: () => Service.readConnections(),
    retry: false,
  })
  const recovery = useQuery({
    queryKey: [
      "model-connection-operation",
      actor,
      intent?.action,
      intent?.key,
    ],
    queryFn: async () => {
      if (!intent) return null
      const found = await Service.recoverOperation({
        action: intent.action,
        idempotencyKey: intent.key,
      })
      return found.operation.action === "VALIDATE" && !terminal(found.operation)
        ? Service.operation({ operationId: found.operation.id })
        : found
    },
    enabled: !!intent && !busy && !locked,
    retry: false,
    refetchInterval: (query) =>
      query.state.data &&
      !terminal(query.state.data.operation) &&
      query.state.data.operation.status !== "UNKNOWN"
        ? 2000
        : false,
  })
  const forget = useCallback(() => {
    try {
      sessionStorage.removeItem(storageKey)
      setIntent(null)
      setRejected(false)
    } catch {
      setLocked(true)
      setMessage(t("Recovery storage is unavailable.", "恢复存储不可用。"))
    }
  }, [storageKey, t])
  const accept = useCallback(
    (result: ConnectionActionPublic) => {
      if (!current()) return
      cache.setQueryData(["model-connections", actor], result.state)
      setLast(result.operation)
      void cache.invalidateQueries({
        queryKey: ["model-connection-status", actor],
      })
      if (terminal(result.operation)) {
        forget()
        heading.current?.focus({ preventScroll: true })
      }
    },
    [current, cache, actor, forget],
  )
  useEffect(() => {
    if (recovery.data) accept(recovery.data)
  }, [recovery.data, accept])
  const op = recovery.data?.operation
  const notFound =
    recovery.error instanceof ApiError && recovery.error.status === 404
  const forbidden =
    locked ||
    (state.error instanceof ApiError &&
      [401, 403].includes(state.error.status)) ||
    (recovery.error instanceof ApiError &&
      [401, 403].includes(recovery.error.status))
  useEffect(() => {
    if (forbidden || state.isError) form.current?.reset()
  }, [forbidden, state.isError])

  async function submit(
    action: Intent["action"],
    connection?: string,
    payload?: SaveConnection,
  ) {
    if (
      sending.current ||
      forbidden ||
      initial.invalid ||
      !state.data ||
      !current()
    )
      return
    sending.current = true
    const selected = intent ?? {
      key: crypto.randomUUID(),
      action,
      ...(connection ? { connection } : {}),
    }
    if (selected.action !== action || selected.connection !== connection) {
      sending.current = false
      return
    }
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(selected))
    } catch {
      sending.current = false
      if (secret.current) secret.current.value = ""
      setMessage(
        t(
          "Recovery storage is unavailable. No request was sent.",
          "恢复存储不可用，未发送请求。",
        ),
      )
      setLocked(true)
      return
    }
    setIntent(selected)
    setBusy(true)
    setMessage("")
    setRejected(false)
    if (secret.current) secret.current.value = ""
    await cache.cancelQueries({ queryKey: stateKey })
    try {
      const requestBody = {
        expected_generation: op?.expected_generation ?? state.data.generation,
      }
      const result =
        action === "save"
          ? await Service.save({
              idempotencyKey: selected.key,
              requestBody: { ...payload!, ...requestBody },
            })
          : action === "adopt"
            ? await Service.adoptLegacy({
                idempotencyKey: selected.key,
                requestBody,
              })
            : await Service.action({
                idempotencyKey: selected.key,
                connectionId: connection!,
                action,
                requestBody,
              })
      accept(result)
      if (current()) form.current?.reset()
    } catch (error) {
      if (!current()) return
      const denied =
        error instanceof ApiError && [401, 403].includes(error.status)
      setLocked(denied)
      setRejected(
        error instanceof ApiError && [409, 422].includes(error.status),
      )
      const parsed =
        error instanceof ApiError
          ? z
              .object({ detail: z.object({ code: z.string() }) })
              .safeParse(error.body)
          : null
      const code = parsed?.success ? parsed.data.detail.code : undefined
      const explanation =
        typeof code === "string" ? failureCopy[code] : undefined
      setMessage(
        explanation
          ? t(explanation[0], explanation[1])
          : denied
            ? t(
                "Permission is no longer available. Sign in again.",
                "当前权限不可用，请重新登录。",
              )
            : error instanceof ApiError && error.status === 422
              ? t(
                  "The input was rejected. Check the fields, then query the original operation before retrying.",
                  "输入未通过校验。请检查字段，并先查询原操作再重试。",
                )
              : t(
                  "The operation was not confirmed. Query the original operation before explicitly retrying it.",
                  "操作结果尚未确认。请先查询原操作，再明确确认是否重试。",
                ),
      )
    } finally {
      sending.current = false
      if (current()) {
        setBusy(false)
        if (secret.current) secret.current.value = ""
      }
    }
  }
  if (forbidden)
    return (
      <Alert variant="destructive">
        <AlertDescription>
          {t(
            "Permission is no longer available. Connection inputs have been cleared.",
            "当前权限不可用，连接输入已清空。",
          )}
          <Button variant="outline" onClick={logout}>
            {t("Sign in again", "重新登录")}
          </Button>
        </AlertDescription>
      </Alert>
    )
  if (state.isError)
    return (
      <Alert variant="destructive">
        <AlertDescription>
          {t(
            "Connections could not be read. No changes were made.",
            "无法读取连接，未做任何变更。",
          )}
          <Button variant="outline" onClick={() => void state.refetch()}>
            {t("Retry reading", "重新读取")}
          </Button>
        </AlertDescription>
      </Alert>
    )
  if (!state.data)
    return <p role="status">{t("Loading connections…", "正在读取连接…")}</p>
  const data = state.data
  const active = data.connections.find((v) => v.id === data.active_id)
  const pending = data.connections.find((v) => v.id === data.pending_id)
  const history = data.connections.filter(
    (v) => v.id !== data.active_id && v.id !== data.pending_id,
  )
  const disabled = busy || !!intent || initial.invalid
  const needsForm = !pending || intent?.action === "save"
  return (
    <div className="space-y-8">
      <h2 ref={heading} tabIndex={-1} className="text-lg font-semibold">
        {t("Model connections", "模型连接")}
      </h2>
      {initial.invalid && (
        <Alert variant="destructive">
          <AlertDescription>
            {t(
              "Saved recovery data is invalid. No writes are available; ask your administrator to inspect this browser session.",
              "恢复记录异常，已停止写操作。请联系管理员检查此浏览器会话。",
            )}
          </AlertDescription>
        </Alert>
      )}
      <div role="status" aria-live="polite" className="space-y-2">
        {busy && <p>{t("Submitting…", "正在提交…")}</p>}
        {message && <p className="text-destructive">{message}</p>}
        {last && (
          <p>
            {t("Last operation", "最近操作")}：
            <StateLabel value={last.status} />
            {last.error_code && (
              <span className="ml-2 break-all text-sm">
                {t(
                  "The operation failed. Check verification results before starting a new attempt.",
                  "操作失败，请检查验证结果后再发起新的尝试。",
                )}
              </span>
            )}
          </p>
        )}
      </div>
      {intent && (
        <section
          className="space-y-3 rounded-lg border p-4"
          aria-label={t("Operation recovery", "操作恢复")}
        >
          <h3 className="font-semibold">
            {t("Resume the original operation", "恢复原操作")}
          </h3>
          <p className="text-sm">
            {t(
              "Refreshing only reads this operation. It never saves, verifies, or activates a connection.",
              "刷新只读取原操作，不会保存、验证或启用连接。",
            )}
          </p>
          <p role="status">
            {recovery.isFetching ? (
              t("Reading operation…", "正在查询原操作…")
            ) : op ? (
              <StateLabel value={op.status} />
            ) : notFound ? (
              t(
                "No receipt found yet. A retry may be the first accepted submission.",
                "暂未找到回执，确认重试可能成为首次成功提交。",
              )
            ) : (
              t("Result not confirmed.", "结果尚未确认。")
            )}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              disabled={busy || recovery.isFetching}
              onClick={() => void recovery.refetch()}
            >
              {t("Query original operation", "查询原操作")}
            </Button>
            {intent.action !== "save" && (
              <LoadingButton
                variant="outline"
                loading={busy}
                disabled={recovery.isFetching || (!op && !notFound)}
                onClick={() => void submit(intent.action, intent.connection)}
              >
                {t("Confirm retry of original intent", "确认重试原意图")}
              </LoadingButton>
            )}
            {rejected && notFound && (
              <Button
                variant="ghost"
                onClick={() => {
                  forget()
                  void state.refetch()
                }}
              >
                {t("Return to configuration", "返回配置")}
              </Button>
            )}
          </div>
        </section>
      )}
      <section
        className="space-y-3"
        aria-label={t("Active connection", "生效连接")}
      >
        <h3 className="font-semibold">{t("Active connection", "生效连接")}</h3>
        {active ? (
          <>
            <ConnectionDetails version={active} />
            <RevokeButton
              disabled={disabled}
              onConfirm={() => void submit("revoke", active.id)}
              active
            />
          </>
        ) : (
          <p className="text-muted-foreground">
            {data.adopted
              ? t(
                  "No active connection. Enabling a verified version resumes new AI tasks.",
                  "当前无生效连接。启用验证通过的版本后，才可发起新的 AI 任务。",
                )
              : t(
                  "The existing deployment configuration remains unchanged until explicit activation.",
                  "在明确启用前，现有部署配置保持原样。",
                )}
          </p>
        )}
      </section>
      {pending && (
        <section
          className="space-y-4 border-t pt-6"
          aria-label={t("Pending connection", "待启用连接")}
        >
          <h3 className="font-semibold">
            {t("Pending connection", "待启用连接")}
          </h3>
          <ConnectionDetails version={pending} />
          <div className="flex flex-wrap gap-3">
            <Button
              className="text-black"
              disabled={
                disabled ||
                ["VALIDATING", "ACTIVATING"].includes(pending.validation_status)
              }
              onClick={() => void submit("validate", pending.id)}
            >
              {t("Verify connection", "验证连接")}
            </Button>
            <Button
              variant="outline"
              disabled={disabled || pending.validation_status !== "VALIDATED"}
              onClick={() => void submit("activate", pending.id)}
            >
              {t("Activate for new tasks", "启用到新任务")}
            </Button>
            <Button
              variant="ghost"
              disabled={
                disabled ||
                ["VALIDATING", "ACTIVATING"].includes(pending.validation_status)
              }
              onClick={() => void submit("discard", pending.id)}
            >
              {t("Discard pending version", "放弃待启用版本")}
            </Button>
          </div>
          <p className="text-sm text-muted-foreground">
            {t(
              "Verification uses fixed synthetic samples. Passing does not activate the version or grant project material access.",
              "验证仅使用固定合成样例。通过不等于启用，也不授予项目材料许可。",
            )}
          </p>
        </section>
      )}
      {needsForm && (
        <section className="space-y-4 border-t pt-6">
          <h3 className="font-semibold">
            {t("Save a new version", "保存新版本")}
          </h3>
          <p className="text-sm text-muted-foreground">
            {intent?.action === "save"
              ? t(
                  "Re-enter the original inputs and Key to retry the same intent. The browser does not retain them after leaving.",
                  "请重新输入原连接内容与 Key，以同一意图重试。离页后浏览器不会保留这些输入。",
                )
              : t(
                  "Saved versions cannot be edited. Changing the model or rotating a Key creates a new version.",
                  "已保存版本不可修改。变更模型或轮换 Key 会创建新版本。",
                )}
          </p>
          <form
            ref={form}
            className="max-w-2xl space-y-5"
            onSubmit={(event) => {
              event.preventDefault()
              const values = new FormData(event.currentTarget)
              void submit("save", undefined, {
                expected_generation: data.generation,
                name: String(values.get("name")),
                endpoint: String(values.get("endpoint")),
                model_identity: String(values.get("model")),
                protocol: values.get("protocol") as SaveConnection["protocol"],
                api_key: String(values.get("api_key")),
              })
            }}
          >
            <fieldset
              disabled={
                busy ||
                initial.invalid ||
                (!!intent && intent.action !== "save")
              }
              className="space-y-5"
            >
              <div className="space-y-2">
                <Label htmlFor="connection-name">
                  {t("Connection name", "连接名称")}
                </Label>
                <Input
                  id="connection-name"
                  name="name"
                  required
                  maxLength={255}
                  autoComplete="off"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="connection-protocol">
                  {t("Protocol", "协议")}
                </Label>
                <select
                  id="connection-protocol"
                  name="protocol"
                  className="h-10 w-full rounded-md border bg-background px-3 text-sm focus-visible:outline-2 focus-visible:outline-ring"
                >
                  <option value="chat_completions">Chat Completions</option>
                  <option value="responses">Responses</option>
                </select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="connection-endpoint">
                  {t("API base URL", "API 基础地址")}
                </Label>
                <Input
                  id="connection-endpoint"
                  name="endpoint"
                  type="url"
                  required
                  maxLength={2048}
                  autoComplete="off"
                  aria-describedby="endpoint-help"
                />
                <p id="endpoint-help" className="text-sm text-muted-foreground">
                  {t(
                    "Use the base URL, such as http://model.internal:8080/v1, without /chat/completions or /responses. Deployment network restrictions still apply.",
                    "填写基础地址，例如 http://model.internal:8080/v1，不附加 /chat/completions 或 /responses。仍遵循部署网络限制。",
                  )}
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="connection-model">
                  {t("Model identifier", "模型标识")}
                </Label>
                <Input
                  id="connection-model"
                  name="model"
                  required
                  maxLength={255}
                  autoComplete="off"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="connection-key">API Key</Label>
                <Input
                  ref={secret}
                  id="connection-key"
                  name="api_key"
                  type="password"
                  required
                  maxLength={8192}
                  autoComplete="new-password"
                  spellCheck={false}
                  aria-describedby="key-help"
                />
                <p id="key-help" className="text-sm text-muted-foreground">
                  {t(
                    "Write only. Cleared on submission or leaving this page; never stored in browser recovery data.",
                    "仅供写入，提交或离页即清空，不存入浏览器恢复记录。",
                  )}
                </p>
              </div>
              <LoadingButton
                className="text-black"
                type="submit"
                loading={busy}
                disabled={!!intent && (!notFound || recovery.isFetching)}
              >
                {intent?.action === "save"
                  ? t("Confirm retry of original intent", "确认重试原意图")
                  : t("Save pending version", "保存待启用版本")}
              </LoadingButton>
            </fieldset>
          </form>
          {!data.adopted && !intent && (
            <div className="space-y-2 border-t pt-4">
              <p className="text-sm text-muted-foreground">
                {t(
                  "Already configured by deployment? Import it as a pending version, then verify and activate it explicitly.",
                  "已有部署连接？可导入为待启用版本，再明确验证与启用。",
                )}
              </p>
              <Button
                variant="outline"
                disabled={disabled}
                onClick={() => void submit("adopt")}
              >
                {t("Import deployment connection", "导入部署连接")}
              </Button>
            </div>
          )}
        </section>
      )}
      {history.length > 0 && (
        <section className="space-y-4 border-t pt-6">
          <h3 className="font-semibold">
            {t("Historical versions", "历史版本")}
          </h3>
          {history.map((version) => (
            <details key={version.id} className="border-b pb-4">
              <summary className="cursor-pointer break-words py-2 font-medium">
                {version.name} ·{" "}
                {version.revoked_at
                  ? t("Revoked", "已撤销")
                  : version.discarded_at
                    ? t("Discarded", "已放弃")
                    : t("Historical", "历史版本")}
              </summary>
              <div className="space-y-3 pt-3">
                <ConnectionDetails version={version} />
                {version.activated_at && !version.revoked_at && (
                  <RevokeButton
                    disabled={disabled}
                    onConfirm={() => void submit("revoke", version.id)}
                  />
                )}
              </div>
            </details>
          ))}
        </section>
      )}
    </div>
  )
}

function ConnectionDetails({ version }: { version: ConnectionPublic }) {
  const { t } = useI18n()
  const checks = [
    ["qualification", "Connection & structured output", "连接与结构化输出"],
    ["investigation", "Investigation capability", "核查能力"],
    ["analysis_report", "Report capability", "报告能力"],
    ["runtime", "Runtime binding", "运行时绑定"],
  ] as const
  return (
    <div className="space-y-3">
      <p className="break-words text-lg font-medium">{version.name}</p>
      <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[auto_1fr]">
        <dt className="text-muted-foreground">{t("Model", "模型")}</dt>
        <dd className="break-all">{version.model_identity}</dd>
        <dt className="text-muted-foreground">{t("Endpoint", "端点")}</dt>
        <dd className="break-all">{version.endpoint}</dd>
        <dt className="text-muted-foreground">{t("Protocol", "协议")}</dt>
        <dd>
          {version.protocol === "responses" ? "Responses" : "Chat Completions"}
        </dd>
        <dt className="text-muted-foreground">API Key</dt>
        <dd>
          {version.key_configured
            ? t("Configured · write only", "已配置 · 不可读取")
            : t("Not configured", "未配置")}
        </dd>
        <dt className="text-muted-foreground">
          {t("Verification", "验证状态")}
        </dt>
        <dd>
          <StateLabel value={version.validation_status} />
        </dd>
      </dl>
      <ul className="max-w-2xl divide-y text-sm">
        {checks.map(([key, en, zh]) => (
          <li key={key} className="flex justify-between gap-4 py-2">
            <span>{t(en, zh)}</span>
            <StateLabel
              value={String(version.validation_evidence?.[key] ?? "NOT_RUN")}
            />
          </li>
        ))}
      </ul>
      {version.validation_completed_at && (
        <p className="text-sm text-muted-foreground">
          {t("Verified at", "验证完成时间")}：
          <time dateTime={version.validation_completed_at}>
            {new Date(version.validation_completed_at).toLocaleString()}
          </time>
        </p>
      )}
      <details className="text-sm">
        <summary className="cursor-pointer text-muted-foreground">
          {t("Version identity", "版本身份")}
        </summary>
        <p className="break-all pt-2">{version.id}</p>
      </details>
    </div>
  )
}

function RevokeButton({
  disabled,
  onConfirm,
  active = false,
}: {
  disabled: boolean
  onConfirm: () => void
  active?: boolean
}) {
  const { t } = useI18n()
  const [confirming, setConfirming] = useState(false)
  return confirming ? (
    <fieldset
      className="space-y-2"
      aria-label={t("Confirm revocation", "确认撤销")}
    >
      <p className="max-w-prose text-sm">
        {t(
          "This blocks the version’s next model request, including existing tasks. An already sent request may finish. Historical results remain available.",
          "这将阻断此版本的下一次模型请求，包括已有任务；已发出的请求可能完成。历史结果仍可读取。",
        )}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button
          variant="destructive"
          disabled={disabled}
          onClick={() => {
            setConfirming(false)
            onConfirm()
          }}
        >
          {t("Confirm revocation", "确认撤销")}
        </Button>
        <Button variant="ghost" onClick={() => setConfirming(false)}>
          {t("Cancel", "取消")}
        </Button>
      </div>
    </fieldset>
  ) : (
    <Button
      variant="outline"
      disabled={disabled}
      onClick={() => setConfirming(true)}
    >
      {active
        ? t("Disable current connection", "禁用当前连接")
        : t("Revoke this version", "撤销此版本")}
    </Button>
  )
}
