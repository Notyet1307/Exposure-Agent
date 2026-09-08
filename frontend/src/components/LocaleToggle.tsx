import { Languages } from "lucide-react"

import { useLocale } from "@/components/LocaleProvider"
import { Button } from "@/components/ui/button"

export function LocaleToggle({ compact = false }: { compact?: boolean }) {
  const { locale, setLocale } = useLocale()
  const next = locale === "zh" ? "en" : "zh"
  return <Button type="button" variant="outline" size={compact ? "icon-sm" : "sm"} aria-label={next === "zh" ? "切换至简体中文" : "Switch to English"} onClick={() => setLocale(next)}><Languages />{compact ? null : next === "zh" ? "简体中文" : "English"}</Button>
}
