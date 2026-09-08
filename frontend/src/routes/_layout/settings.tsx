import { createFileRoute } from "@tanstack/react-router"
import { useEffect } from "react"

import ChangePassword from "@/components/UserSettings/ChangePassword"
import UserInformation from "@/components/UserSettings/UserInformation"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useAuth from "@/hooks/useAuth"
import { useI18n } from "@/lib/i18n"

const tabsConfig = [
  {
    value: "my-profile",
    title: ["My profile", "我的资料"] as const,
    component: UserInformation,
  },
  {
    value: "password",
    title: ["Password", "密码"] as const,
    component: ChangePassword,
  },
]

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
  const { t } = useI18n()
  useEffect(() => {
    document.title = t("Settings - Exposure-Agent", "设置 - Exposure-Agent")
  }, [t])
  const { user: currentUser } = useAuth()

  if (!currentUser) {
    return null
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          {t("User Settings", "用户设置")}
        </h1>
        <p className="text-muted-foreground">
          {t(
            "Manage your account settings and preferences",
            "管理您的账户设置与偏好",
          )}
        </p>
      </div>

      <Tabs defaultValue="my-profile">
        <TabsList>
          {tabsConfig.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value}>
              {t(tab.title[0], tab.title[1])}
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
