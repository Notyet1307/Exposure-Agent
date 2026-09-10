import { useState } from "react"

import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import { useI18n } from "@/lib/i18n"

export function TechnicalValue({
  value,
  label,
}: {
  value: string
  label?: string
}) {
  const { t } = useI18n()
  const [copied, copy] = useCopyToClipboard()
  const [failed, setFailed] = useState(false)
  if (!value) return <span>{t("Not available", "不可用")}</span>

  return (
    <span className="inline-flex min-w-0 max-w-full flex-wrap items-center gap-2 align-middle">
      <span className="min-w-0 break-all font-mono text-xs select-text">
        {value}
      </span>
      <button
        type="button"
        className="shrink-0 rounded border px-2 py-1 text-xs focus-visible:outline-2 focus-visible:outline-offset-2"
        aria-label={
          label
            ? t(`Copy ${label}`, `复制${label}`)
            : t(`Copy full value: ${value}`, `复制完整值：${value}`)
        }
        onClick={async () => setFailed(!(await copy(value)))}
      >
        {t("Copy", "复制")}
      </button>
      <span role="status" className="text-xs">
        {failed
          ? t(
              "Copy failed. Select the full value to copy manually.",
              "复制失败，请选中完整值手动复制。",
            )
          : copied === value
            ? t("Copied", "已复制")
            : null}
      </span>
    </span>
  )
}
