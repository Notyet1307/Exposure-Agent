import { Appearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import { LanguageSwitcher, useI18n } from "@/lib/i18n"
import { Footer } from "./Footer"

interface AuthLayoutProps {
  children: React.ReactNode
}

export function AuthLayout({ children }: AuthLayoutProps) {
  const { t } = useI18n()
  return (
    <div className="grid min-h-svh lg:grid-cols-2">
      <div className="relative hidden overflow-hidden border-r bg-muted/60 dark:bg-zinc-900/90 lg:flex lg:flex-col lg:items-center lg:justify-center lg:p-12">
        <div className="relative z-10 flex max-w-md flex-col items-center gap-3 text-center">
          <Logo variant="full" className="text-4xl" asLink={false} />
          <p className="text-sm leading-relaxed text-muted-foreground">
            {t(
              "Deterministic asset register & exposure reconciliation workbench",
              "确定性资产台账与互联网暴露面对账治理工作台",
            )}
          </p>
        </div>
      </div>
      <div className="flex flex-col gap-4 p-6 md:p-10">
        <div className="flex items-center justify-end gap-2">
          <LanguageSwitcher />
          <Appearance />
        </div>
        <div className="flex flex-1 items-center justify-center">
          <div className="w-full max-w-xs">{children}</div>
        </div>
        <Footer />
      </div>
    </div>
  )
}
