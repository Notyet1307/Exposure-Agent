import { FileText, FolderInput, Home, ListChecks, Network, PlayCircle, Users } from "lucide-react"
import { useRouterState } from "@tanstack/react-router"

import { SidebarAppearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { Main } from "./Main"
import { User } from "./User"
import { useLocale } from "@/components/LocaleProvider"

export function AppSidebar() {
  const { user: currentUser } = useAuth()
  const { locale, text } = useLocale()
  const router = useRouterState()
  const search = router.location.search as {
    prototype?: string
    reader?: string
    reader_section?: string
    reader_locale?: string
    tab?: string
    resource_id?: string
  }

  const items = currentUser?.is_superuser
    ? [{ icon: Home, title: text("工作台", "Dashboard"), path: "/" }, { icon: Users, title: text("用户管理", "Admin"), path: "/admin" }]
    : [{ icon: Home, title: text("工作台", "Dashboard"), path: "/" }]

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-6 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:items-center">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent>
        {search.prototype === "customer" && search.reader === "full" ? (
          <CustomerReaderMenu section={search.tab ?? search.reader_section} locale={locale} resourceId={search.resource_id} canAdmin={currentUser?.is_superuser === true} />
        ) : <Main items={items} />}
      </SidebarContent>
      <SidebarFooter>
        <SidebarAppearance />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar

function CustomerReaderMenu({ section, locale, resourceId, canAdmin }: { section?: string; locale: "zh" | "en"; resourceId?: string; canAdmin: boolean }) {
  const zh = locale === "zh"
  const readerUrl = (reader_section: string) => `/?prototype=customer&reader=full&reader_section=${reader_section}${reader_section === "lineage" && resourceId ? `&resource_id=${resourceId}` : ""}`
  const projectUrl = (tab: string) => `/?prototype=customer&reader=full&project_id=3a36675f-789c-4789-a5bd-f03ea7d8c6f7&tab=${tab}`
  const reading = [["overview", zh ? "概览" : "Overview", ListChecks], ["matrix", zh ? "资产与差异" : "Assets & differences", Network], ["lineage", zh ? "血缘追溯" : "Lineage trace", Network], ["report", zh ? "报告" : "Report", FileText]] as const
  return <><SidebarGroup><SidebarGroupContent><p className="px-2 pb-2 text-xs font-semibold text-muted-foreground">{zh ? "结果阅读" : "Results"}</p><SidebarMenu>{reading.map(([key, title, Icon]) => <SidebarMenuItem key={key}><SidebarMenuButton tooltip={title} isActive={(section ?? "overview") === key} asChild><a href={readerUrl(key)}><Icon /><span>{title}</span></a></SidebarMenuButton></SidebarMenuItem>)}</SidebarMenu></SidebarGroupContent></SidebarGroup><SidebarGroup><SidebarGroupContent><p className="px-2 pb-2 text-xs font-semibold text-muted-foreground">{zh ? "管理入口" : "Management"}</p><SidebarMenu><SidebarMenuItem><SidebarMenuButton tooltip={zh ? "输入" : "Inputs"} asChild><a href={projectUrl("inputs")}><FolderInput /><span>{zh ? "输入" : "Inputs"}</span></a></SidebarMenuButton></SidebarMenuItem><SidebarMenuItem><SidebarMenuButton tooltip={zh ? "运行" : "Runs"} asChild><a href={projectUrl("runs")}><PlayCircle /><span>{zh ? "运行" : "Runs"}</span></a></SidebarMenuButton></SidebarMenuItem>{canAdmin && <SidebarMenuItem><SidebarMenuButton tooltip={zh ? "用户管理" : "Admin"} asChild><a href="/admin"><Users /><span>{zh ? "用户管理" : "Admin"}</span></a></SidebarMenuButton></SidebarMenuItem>}</SidebarMenu></SidebarGroupContent></SidebarGroup></>
}
