import { useParams, useRouterState, useSearch } from "@tanstack/react-router"
import {
  FileSpreadsheet,
  Network,
  Settings2,
  Upload,
  Users,
  Waypoints,
} from "lucide-react"

import { SidebarAppearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarSeparator,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { useI18n } from "@/lib/i18n"
import { useWorkspaceSearch, type WorkspaceSearch } from "@/lib/workspace"
import { type Item, Main } from "./Main"
import { User } from "./User"

export function AppSidebar() {
  const { t } = useI18n()
  const { user: currentUser } = useAuth()
  const search = useWorkspaceSearch()
  const legacyComparison = useSearch({ strict: false }).legacy
  const params = useParams({ strict: false })
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  })
  const project = params.projectId ?? search.project
  const run = params.runId ?? search.run
  const context = { ...search, project, run }
  const home = (
    view: WorkspaceSearch["view"],
    title: string,
    icon: Item["icon"],
  ): Item => ({
    icon,
    title,
    path: "/",
    search: { ...context, view },
    active: pathname === "/" && (search.view ?? "overview") === view,
  })
  const primary: Item[] = [
    {
      icon: Network,
      title: t("Comparison results", "比对结果"),
      path: project ? `/projects/${project}/netflow-correlation` : "/",
      search:
        pathname.endsWith("/netflow-correlation") && !legacyComparison
          ? true
          : {},
      active: pathname.endsWith("/netflow-correlation"),
    },
    {
      icon: Waypoints,
      title: t("CloudAtlas assets", "云图资产"),
      path: project ? `/projects/${project}/cloudatlas-ledger` : "/",
      search: project ? undefined : { view: "cloudatlas-ledger" },
      active:
        pathname.endsWith("/cloudatlas-ledger") ||
        pathname.endsWith("/external-assets") ||
        (pathname === "/" && search.view === "cloudatlas-ledger"),
    },
    {
      icon: FileSpreadsheet,
      title: t("Customer asset ledger", "客户资产台账"),
      path: project ? `/projects/${project}/customer-ledger` : "/",
      search: project ? undefined : { view: "inputs" },
      active: pathname.endsWith("/customer-ledger"),
    },
    {
      icon: Network,
      title: t("NetFlow observations", "NetFlow 观测"),
      path: project ? `/projects/${project}/netflow-results` : "/",
      search: project ? undefined : { view: "inputs" },
      active: pathname.endsWith("/netflow-results"),
    },
  ]
  const management: Item[] = [
    {
      ...home("inputs", t("Data access", "数据接入"), Upload),
      search: { project, view: "inputs" },
      active:
        pathname === "/" &&
        ["inputs", "cloudatlas"].includes(search.view ?? ""),
    },
  ]
  const administration: Item[] = [
    {
      icon: Settings2,
      title: t("AI settings", "AI 设置"),
      path: "/ai-settings",
    },
    ...(currentUser?.is_superuser
      ? [
          {
            icon: Users,
            title: t("Admin", "用户管理"),
            path: "/admin",
            search: context,
          },
        ]
      : []),
  ]
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-6 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:items-center">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent>
        <Main label={t("Data and comparison", "资料与比对")} items={primary} />
        <SidebarSeparator className="mx-2 opacity-60" />
        <Main label={t("Project settings", "项目设置")} items={management} />
        {administration.length > 0 && (
          <>
            <SidebarSeparator className="mx-2 opacity-60" />
            <Main
              label={t("System management", "系统管理")}
              items={administration}
            />
          </>
        )}
      </SidebarContent>
      <SidebarFooter>
        <SidebarAppearance />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
