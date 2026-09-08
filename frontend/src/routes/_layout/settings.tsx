import { createFileRoute } from "@tanstack/react-router"

import ChangePassword from "@/components/UserSettings/ChangePassword"
import UserInformation from "@/components/UserSettings/UserInformation"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useAuth from "@/hooks/useAuth"
import { useLocale } from "@/components/LocaleProvider"

export const Route = createFileRoute("/_layout/settings")({
  component: UserSettings,
  head: () => ({
    meta: [
      {
        title: "Settings - Exposure-Agent",
      },
    ],
  }),
})

function UserSettings() {
  const { user: currentUser } = useAuth()
  const { text } = useLocale()
  const tabsConfig = [
    { value: "my-profile", title: text("我的资料", "My profile"), component: UserInformation },
    { value: "password", title: text("密码", "Password"), component: ChangePassword },
  ]

  if (!currentUser) {
    return null
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{text("用户设置", "User Settings")}</h1>
        <p className="text-muted-foreground">
          {text("管理账号设置与偏好。", "Manage your account settings and preferences")}
        </p>
      </div>

      <Tabs defaultValue="my-profile">
        <TabsList>
          {tabsConfig.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value}>
              {tab.title}
            </TabsTrigger>
          ))}
        </TabsList>
        {tabsConfig.map((tab) => (
          <TabsContent key={tab.value} value={tab.value}>
            <tab.component />
          </TabsContent>
        ))}
      </Tabs>
    </div>
  )
}
