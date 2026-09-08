import { createContext, type ReactNode, useContext, useEffect, useState } from "react"

export type Locale = "zh" | "en"

type LocaleContextValue = {
  locale: Locale
  setLocale: (locale: Locale) => void
  text: (zh: string, en: string) => string
}

const LocaleContext = createContext<LocaleContextValue | null>(null)
const storageKey = "exposure-agent-locale"

function initialLocale(): Locale {
  return window.localStorage.getItem(storageKey) === "en" ? "en" : "zh"
}

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(initialLocale)
  useEffect(() => {
    window.localStorage.setItem(storageKey, locale)
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en"
  }, [locale])
  const value: LocaleContextValue = {
    locale,
    setLocale,
    text: (zh, en) => (locale === "zh" ? zh : en),
  }
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
}

export function useLocale() {
  const value = useContext(LocaleContext)
  if (!value) throw new Error("useLocale must be used inside LocaleProvider")
  return value
}
