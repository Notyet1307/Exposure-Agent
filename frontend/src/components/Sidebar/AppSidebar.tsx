import { useParams, useRouterState } from "@tanstack/react-router"
import {
  Boxes,
  FileSpreadsheet,
  FileText,
  Home,
  ListChecks,
  Network,
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
  const primary: Item[] = [
    {
      icon: Network,
      title: t("Source comparison", "本次比对"),
      path: project ? `/projects/${project}/netflow-correlation` : "/",
      search: pathname.endsWith("/netflow-correlation")
        ? true
        : project
          ? undefined
          : { view: "inputs" },
      active: pathname.endsWith("/netflow-correlation"),
    },
    {
      icon: FileSpreadsheet,
      title: t("Customer ledger", "客户清单"),
      path: project ? `/projects/${project}/customer-ledger` : "/",
      search: project ? undefined : { view: "inputs" },
      active: pathname.endsWith("/customer-ledger"),
    },
    {
      icon: Waypoints,
      title: t("CloudAtlas data", "云图数据"),
      path: project ? `/projects/${project}/cloudatlas-ledger` : "/",
      search: project ? undefined : { view: "cloudatlas-ledger" },
      active:
        pathname.endsWith("/cloudatlas-ledger") ||
        pathname.endsWith("/external-assets") ||
        (pathname === "/" && search.view === "cloudatlas-ledger"),
    },
    {
      icon: Network,
      title: t("Processed NetFlow data", "流量观测"),
      path: project ? `/projects/${project}/netflow-results` : "/",
      search: project ? undefined : { view: "inputs" },
      active: pathname.endsWith("/netflow-results"),
    },
  ]
  const management: Item[] = [
    home("inputs", t("Inputs", "输入管理"), Upload),
    home("cloudatlas", t("CloudAtlas", "来源管理"), Waypoints),
  ]
  const historical: Item[] = [
    home("overview", t("Overview", "旧运行概览"), Home),
    {
      icon: Boxes,
      title: t("Assets & differences", "历史资产比较"),
      path:
        project && run ? `/projects/${project}/runs/${run}/comparison` : "/",
      search: { ...context, view: "overview" },
      active: pathname.endsWith("/comparison"),
    },
    home("reports", t("Reports", "历史报告"), FileText),
    {
      icon: Waypoints,
      title: t("NetFlow activity ledger", "旧 NetFlow 活动账"),
      path: project ? `/projects/${project}/netflow-ledger` : "/",
      search: project ? undefined : { view: "inputs" },
      active: pathname.endsWith("/netflow-ledger"),
    },
    home("runs", t("Runs", "运行管理"), Play),
    home("findings", t("Findings", "发现项"), ListChecks),
    {
      icon: Settings2,
      title: t("AI settings", "AI 设置"),
      path: "/ai-settings",
    },
  ]
  const administration: Item[] = currentUser?.is_superuser
    ? [
        {
          icon: Users,
          title: t("Admin", "用户管理"),
          path: "/admin",
          search: context,
        },
      ]
    : []
  const historicalPage =
    historical.some((item) => item.active) ||
    pathname.endsWith("/lineage") ||
    pathname === "/ai-settings" ||
    (pathname === "/" && search.view === "assets")
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-6 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:items-center">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent>
        <Main label={t("Data and comparison", "资料与比对")} items={primary} />
        <Main label={t("Project setup", "项目配置")} items={management} />
        <details
          key={historicalPage ? "historical" : "current"}
          open={historicalPage}
          className="group-data-[collapsible=icon]:hidden"
        >
          <summary className="mx-4 cursor-pointer rounded-md py-2 text-sm text-sidebar-foreground/70">
            {t("Historical governance", "历史与治理")}
          </summary>
          <Main items={historical} />
        </details>
        {administration.length > 0 && (
          <Main
            label={t("System management", "系统管理")}
            items={administration}
          />
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
