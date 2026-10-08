import {
  createFileRoute,
  Outlet,
  redirect,
  useRouterState,
} from "@tanstack/react-router"

import { Footer } from "@/components/Common/Footer"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import WorkspaceSelector from "@/components/WorkspaceSelector"
import useAuth, { isLoggedIn } from "@/hooks/useAuth"
import { useI18n } from "@/lib/i18n"
import { validateWorkspaceSearch } from "@/lib/workspace"

export const Route = createFileRoute("/_layout")({
  component: Layout,
  validateSearch: validateWorkspaceSearch,
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      throw redirect({
        to: "/login",
      })
    }
  },
})

function Layout() {
  const { user, userError, refetchUser, logout } = useAuth()
  const { t } = useI18n()
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  })
  const workspace = pathname === "/" || pathname.startsWith("/projects/")
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <header className="sticky top-0 z-10 flex min-h-16 shrink-0 items-center gap-2 border-b bg-background px-4 py-2">
          <SidebarTrigger className="-ml-1 text-muted-foreground" />
          {workspace && <WorkspaceSelector />}
        </header>
        <main className="flex-1 p-6 md:p-8">
          <div className="mx-auto max-w-7xl">
            {userError ? (
              <Alert variant="destructive">
                <AlertDescription>
                  {t(
                    "Permissions could not be read. Retry or sign in again before continuing.",
                    "无法读取权限。请重试或重新登录后再操作。",
                  )}
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="outline"
                      onClick={() => void refetchUser()}
                    >
                      {t("Retry permission check", "重新读取权限")}
                    </Button>
                    <Button variant="ghost" onClick={logout}>
                      {t("Sign in again", "重新登录")}
                    </Button>
                  </div>
                </AlertDescription>
              </Alert>
            ) : user ? (
              <Outlet />
            ) : (
              <p role="status">{t("Checking permissions…", "正在读取权限…")}</p>
            )}
          </div>
        </main>
        <Footer />
      </SidebarInset>
    </SidebarProvider>
  )
}
