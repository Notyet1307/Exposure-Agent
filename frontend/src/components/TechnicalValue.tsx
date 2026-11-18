import { Check, Copy } from "lucide-react"
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
  const isCopied = copied === value && !failed

  return (
    <span className="inline-flex min-w-0 max-w-full flex-wrap items-center gap-1.5 align-middle">
      <code className="min-w-0 rounded bg-muted/70 px-1.5 py-0.5 font-mono text-xs break-all select-text">
        {value}
      </code>
      <button
        type="button"
        data-copied={isCopied ? "" : undefined}
        data-failed={failed ? "" : undefined}
        className="inline-flex min-h-6 min-w-6 shrink-0 items-center justify-center rounded border border-transparent p-1 text-muted-foreground opacity-75 transition-opacity hover:border-border hover:bg-muted hover:text-foreground hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-offset-2 data-[copied]:text-emerald-600 dark:data-[copied]:text-emerald-400"
        aria-label={
          label
            ? t(`Copy ${label}`, `复制${label}`)
            : t(`Copy full value: ${value}`, `复制完整值：${value}`)
        }
        onClick={async () => setFailed(!(await copy(value)))}
      >
        {isCopied ? (
          <Check aria-hidden="true" className="size-3.5" />
        ) : (
          <Copy aria-hidden="true" className="size-3.5" />
        )}
      </button>
      <span role="status" className="text-xs text-muted-foreground">
        {failed
          ? t(
              "Copy failed. Select the full value to copy manually.",
              "复制失败，请选中完整值手动复制。",
            )
          : isCopied
            ? t("Copied", "已复制")
            : null}
      </span>
    </span>
  )
}
