import { useI18n } from "@/lib/i18n"

export const customerFields = [
  ["asset_ip", "Asset IP", "资产 IP"],
  ["start_port", "Start port", "起始端口"],
  ["end_port", "End port", "结束端口"],
  ["is_web", "Web interface", "是否 Web 界面"],
  ["web_url", "Web URL", "Web 界面 URL"],
  ["service_type", "Service", "服务类型"],
  ["asset_owner", "Declared owner", "原声明负责人"],
  ["asset_department", "Asset department", "资产所属部门"],
  ["port_owner", "Port owner", "端口负责人"],
  ["department", "Department", "部门"],
  ["serial", "Source number", "原序号"],
] as const

export const customerFieldValue = (value: unknown): string => {
  if (value === null || value === undefined) return ""
  const scalar = typeof value === "object" ? Reflect.get(value, "value") : value
  return scalar === null || scalar === undefined ? "" : String(scalar)
}

export function CustomerRecordFields({
  fields,
}: {
  fields: Record<string, unknown>
}) {
  const { t } = useI18n()
  return (
    <dl className="grid min-w-0 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {customerFields.map(([name, en, zh]) => (
        <div key={name} className="min-w-0">
          <dt className="text-sm text-muted-foreground">{t(en, zh)}</dt>
          <dd className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
            {customerFieldValue(fields[name]) || t("Not provided", "未提供")}
          </dd>
        </div>
      ))}
    </dl>
  )
}
