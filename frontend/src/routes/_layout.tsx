import {
  createFileRoute,
  Outlet,
  redirect,
  useRouterState,
} from "@tanstack/react-router"

import { Footer } from "@/components/Common/Footer"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import WorkspaceSelector from "@/components/WorkspaceSelector"
import { isLoggedIn } from "@/hooks/useAuth"
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
            <Outlet />
          </div>
        </main>
        <Footer />
      </SidebarInset>
    </SidebarProvider>
  )
}
