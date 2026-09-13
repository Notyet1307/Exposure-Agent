import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Link, useNavigate } from "@tanstack/react-router"
import { FolderPlus } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { z } from "zod"
import { ApiError, ProjectsService } from "@/client"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import useAuth, { isInactiveAccountError } from "@/hooks/useAuth"
import { useI18n } from "@/lib/i18n"

const intentSchema = z
  .object({ key: z.string().uuid(), name: z.string().trim().min(1).max(255) })
  .strict()

export function CreateProjectLink() {
  const { user } = useAuth()
  const { t } = useI18n()
  return user?.is_superuser ? (
    <Button asChild variant="outline">
      <Link to="/" search={{ view: "create" }}>
        <FolderPlus aria-hidden="true" />
        {t("New comparison project", "新建比对项目")}
      </Link>
    </Button>
  ) : null
}

export default function CreateProject() {
  const { user, userError, refetchUser, logout } = useAuth()
  const { t } = useI18n()
  if (userError)
    return (
      <Alert variant="destructive">
        <AlertDescription>
          {t(
            "Permissions could not be read. Retry or sign in again before continuing.",
            "无法读取权限。请重试或重新登录后再操作。",
          )}
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => void refetchUser()}>
              {t("Retry permission check", "重新读取权限")}
            </Button>
            <Button variant="ghost" onClick={logout}>
              {t("Sign in again", "重新登录")}
            </Button>
          </div>
        </AlertDescription>
      </Alert>
    )
  if (!user)
    return <p role="status">{t("Checking permissions…", "正在读取权限…")}</p>
  if (!user.is_superuser)
    return (
      <Alert>
        <AlertDescription>
          {t(
            "Only an administrator can create a project. Ask your administrator to create one and grant access.",
            "只有管理员可以创建项目。请联系管理员创建并授予访问权限。",
          )}
        </AlertDescription>
      </Alert>
    )
  return <ProjectForm key={user.id} actor={user.id} />
}

function ProjectForm({ actor }: { actor: string }) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const storageKey = `exposure:project-create:${actor}`
  const [initial] = useState(() => {
    try {
      const raw = sessionStorage.getItem(storageKey)
      return {
        intent: raw ? intentSchema.parse(JSON.parse(raw)) : null,
        error: false,
      }
    } catch {
      return { intent: null, error: true }
    }
  })
  const [intent, setIntent] = useState(initial.intent)
  const [name, setName] = useState(initial.intent?.name ?? "")
  const [error, setError] = useState<string | null>(
    initial.error ? "storage" : null,
  )
  const nameInput = useRef<HTMLInputElement>(null)
  const formTitle = useRef<HTMLHeadingElement>(null)
  const active = useRef(true)
  useEffect(() => {
    active.current = true
    if (nameInput.current?.disabled) formTitle.current?.focus()
    else nameInput.current?.focus()
    return () => {
      active.current = false
    }
  }, [])
  const mutation = useMutation({
    mutationFn: async () => {
      const pending =
        intent ?? intentSchema.parse({ key: crypto.randomUUID(), name })
      try {
        sessionStorage.setItem(storageKey, JSON.stringify(pending))
      } catch {
        setError("storage")
        throw new Error("storage")
      }
      setIntent(pending)
      const token = localStorage.getItem("access_token")
      const originSearch = window.location.search
      try {
        const project = await ProjectsService.createProject({
          requestBody: { name: pending.name },
          idempotencyKey: pending.key,
        })
        return { project, token, originSearch }
      } catch (failure) {
        if (token !== localStorage.getItem("access_token"))
          throw new Error("Account changed")
        throw failure
      }
    },
    onSuccess: async ({ project, token, originSearch }) => {
      if (
        !active.current ||
        token !== localStorage.getItem("access_token") ||
        window.location.search !== originSearch
      )
        return
      try {
        sessionStorage.removeItem(storageKey)
      } catch {
        /* The same saved key still replays the created project. */
      }
      await queryClient.invalidateQueries({ queryKey: ["projects"] })
      if (
        !active.current ||
        token !== localStorage.getItem("access_token") ||
        window.location.search !== originSearch
      )
        return
      toast.success(
        t(
          "Project created. Prepare the input versions next.",
          "项目已创建，接下来准备输入版本。",
        ),
      )
      void navigate({
        to: "/",
        search: { project: project.id, view: "inputs" },
      })
    },
    onError: (failure) => {
      if (!active.current) return
      if (isInactiveAccountError(failure)) {
        setError("permission")
      } else if (
        failure instanceof ApiError &&
        [400, 422].includes(failure.status)
      ) {
        try {
          sessionStorage.removeItem(storageKey)
          setIntent(null)
        } catch {
          setError("storage")
          return
        }
        setError("invalid")
      } else if (
        failure instanceof ApiError &&
        [401, 403, 404].includes(failure.status)
      )
        setError("permission")
      else if (failure instanceof ApiError && failure.status === 409)
        setError("conflict")
      else setError((value) => (value === "storage" ? value : "unknown"))
    },
  })
  return (
    <section
      className="mx-auto max-w-2xl space-y-8"
      aria-labelledby="create-project-title"
    >
      <header className="space-y-3">
        <h1
          ref={formTitle}
          tabIndex={-1}
          id="create-project-title"
          className="text-3xl font-semibold tracking-tight"
        >
          {t("Start a comparison project", "开始一个比对项目")}
        </h1>
        <p className="max-w-prose text-muted-foreground">
          {t(
            "Keep a stable scope for your assets. Prepare inputs next, then compare them in your first run.",
            "为一组资产建立持续管理的范围。接下来准备输入，完成首轮比对。",
          )}
        </p>
      </header>
      <form
        className="space-y-6"
        onSubmit={(event) => {
          event.preventDefault()
          if (!initial.error && !mutation.isPending) {
            setError(null)
            mutation.mutate()
          }
        }}
      >
        <div className="space-y-2">
          <Label htmlFor="comparison-project-name">
            {t("Project name", "项目名称")}
          </Label>
          <Input
            ref={nameInput}
            id="comparison-project-name"
            name="name"
            autoComplete="off"
            required
            maxLength={255}
            value={name}
            disabled={!!intent || mutation.isPending}
            onChange={(event) => setName(event.target.value)}
            placeholder={t(
              "For example: North plant assets",
              "例如：华北园区资产",
            )}
          />
          <p className="text-sm text-muted-foreground">
            {t(
              "Created within this deployment. A new comparison later will reuse this project.",
              "项目创建在当前部署范围内。后续比对继续使用同一项目。",
            )}
          </p>
        </div>
        {intent && (
          <p role="status" className="text-sm">
            {t(
              "A creation request is saved. Resuming uses the same request; it does not start a separate project.",
              "已保存创建请求。继续将恢复同一次请求，不会另建重复项目。",
            )}
          </p>
        )}
        {error && (
          <Alert variant="destructive">
            <AlertDescription>
              {error === "storage"
                ? t(
                    "Recovery storage is unavailable or invalid. No new request was sent. Restore browser storage before continuing.",
                    "恢复存储不可用或内容异常，未发送新的请求。请恢复浏览器存储后继续。",
                  )
                : error === "permission"
                  ? t(
                      "Permission is no longer available. Sign in with an authorized account.",
                      "当前权限不可用，请使用有权限的账号登录。",
                    )
                  : error === "conflict"
                    ? t(
                        "This request belongs to a different creation intent. Keep the original request and contact an administrator.",
                        "此请求已绑定其他创建内容。请保留原请求并联系管理员。",
                      )
                    : error === "invalid"
                      ? t(
                          "The name was rejected. Check it and try again.",
                          "项目名称未通过校验，请修改后重试。",
                        )
                      : t(
                          "The result is not confirmed. Resume the saved request to confirm whether the project was created.",
                          "创建结果尚未确认。请恢复已保存的请求，确认项目是否已创建。",
                        )}
            </AlertDescription>
          </Alert>
        )}
        <div className="flex flex-wrap gap-3">
          <LoadingButton
            type="submit"
            loading={mutation.isPending}
            disabled={
              initial.error ||
              !name.trim() ||
              error === "permission" ||
              error === "conflict"
            }
          >
            {intent
              ? t("Resume creation", "恢复创建请求")
              : t("Create and prepare inputs", "创建并准备输入")}
          </LoadingButton>
          <Button variant="ghost" asChild>
            <Link to="/" search={{}}>
              {t("Back to workspace", "返回工作区")}
            </Link>
          </Button>
        </div>
      </form>
    </section>
  )
}
