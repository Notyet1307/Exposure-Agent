import { useParams, useRouterState } from "@tanstack/react-router"
import {
  Boxes,
  FileText,
  GitBranch,
  Home,
  ListChecks,
  Play,
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
  const reading: Item[] = [
    home("overview", t("Overview", "概览"), Home),
    {
      icon: Boxes,
      title: t("Assets & differences", "资产与差异"),
      path:
        project && run ? `/projects/${project}/runs/${run}/comparison` : "/",
      search: { ...context, view: "overview" },
      active: pathname.endsWith("/comparison"),
    },
    {
      icon: GitBranch,
      title: t("Lineage", "血缘"),
      path: project && run ? `/projects/${project}/runs/${run}/lineage` : "/",
      search: { ...context, view: "overview" },
      active: pathname.endsWith("/lineage"),
    },
    home("reports", t("Reports", "报告"), FileText),
  ]
  const management: Item[] = [
    home("inputs", t("Inputs", "输入管理"), Upload),
    home("cloudatlas", t("CloudAtlas", "来源管理"), Waypoints),
    home("runs", t("Runs", "运行管理"), Play),
    home("assets", t("Current assets", "当前资产"), Boxes),
    home("findings", t("Findings", "发现项"), ListChecks),
  ]
  management.push({
    icon: Settings2,
    title: t("AI settings", "AI 设置"),
    path: "/ai-settings",
  })
  if (currentUser?.is_superuser)
    management.push({
      icon: Users,
      title: t("Admin", "用户管理"),
      path: "/admin",
      search: context,
    })
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-6 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:items-center">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent>
        <Main label={t("Published results", "已发布结果")} items={reading} />
        <Main label={t("Management", "项目管理")} items={management} />
      </SidebarContent>
      <SidebarFooter>
        <SidebarAppearance />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
