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

const temporalKinds = new Set(["datetime", "date", "time", "timedelta"])
const integerText = /^(0|-?[1-9]\d*)$/
const floatText = /^-?(0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$/

export type DetailNumberCell = {
  kind: "number"
  numeric_type: "integer" | "float"
  value: string
}

export function isDetailNumberCell(value: unknown): value is DetailNumberCell {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    return false
  const cell = value as Record<string, unknown>
  if (Object.keys(cell).length !== 3) return false
  if (cell.kind !== "number" || typeof cell.value !== "string") return false
  if (cell.numeric_type === "integer") return integerText.test(cell.value)
  if (cell.numeric_type === "float")
    return floatText.test(cell.value) && Number.isFinite(Number(cell.value))
  return false
}

type ExactFieldKind =
  | "missing"
  | "null"
  | "empty"
  | "text"
  | "integer"
  | "float"
  | "boolean"
  | "datetime"
  | "date"
  | "time"
  | "timedelta"
  | "unsupported"

function exactFieldValue(
  fields: Record<string, unknown>,
  name: string,
): { kind: ExactFieldKind; value: string } {
  if (!Object.keys(fields).includes(name)) {
    return { kind: "missing", value: "" }
  }
  const raw = fields[name]
  if (raw === null) return { kind: "null", value: "null" }
  if (raw === "") return { kind: "empty", value: "" }
  if (typeof raw === "string") return { kind: "text", value: raw }
  if (typeof raw === "number") return { kind: "unsupported", value: "" }
  if (typeof raw === "boolean") {
    return { kind: "boolean", value: raw ? "true" : "false" }
  }
  if (typeof raw === "object") {
    if (isDetailNumberCell(raw)) {
      return { kind: raw.numeric_type, value: raw.value }
    }
    const kind = Reflect.get(raw, "kind")
    const value = Reflect.get(raw, "value")
    if (
      typeof kind === "string" &&
      temporalKinds.has(kind) &&
      typeof value === "string"
    ) {
      return { kind: kind as ExactFieldKind, value }
    }
  }
  return { kind: "unsupported", value: "" }
}

const kindLabels: Record<ExactFieldKind, [string, string]> = {
  missing: ["missing key", "缺少键"],
  null: ["null", "null"],
  empty: ["empty string", "空字符串"],
  text: ["text", "文本"],
  integer: ["integer", "整数"],
  float: ["float", "浮点数"],
  boolean: ["boolean", "布尔值"],
  datetime: ["datetime", "日期时间"],
  date: ["date", "日期"],
  time: ["time", "时间"],
  timedelta: ["duration", "时长"],
  unsupported: ["unsupported value", "不支持的值"],
}

function ExactFieldValue({
  fields,
  name,
}: {
  fields: Record<string, unknown>
  name: string
}) {
  const { t } = useI18n()
  const field = exactFieldValue(fields, name)
  const label = kindLabels[field.kind]
  if (field.kind === "missing") {
    return (
      <span className="text-muted-foreground">
        {t("Missing key", "缺少键")}
      </span>
    )
  }
  if (field.kind === "null") {
    return <span className="text-muted-foreground">null</span>
  }
  if (field.kind === "empty") {
    return (
      <span className="text-muted-foreground">
        {t("Empty string", "空字符串")} <code>""</code>
      </span>
    )
  }
  return (
    <span className="space-x-2">
      <span className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
        {field.value}
      </span>
      <span className="rounded border px-1 text-xs text-muted-foreground">
        {t(label[0], label[1])}
      </span>
    </span>
  )
}

export function CustomerRecordFields({
  fields,
  exact = false,
}: {
  fields: Record<string, unknown>
  exact?: boolean
}) {
  const { t } = useI18n()
  return (
    <dl className="grid min-w-0 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {customerFields.map(([name, en, zh]) => (
        <div key={name} className="min-w-0">
          <dt className="text-sm text-muted-foreground">{t(en, zh)}</dt>
          <dd className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
            {exact ? (
              <ExactFieldValue fields={fields} name={name} />
            ) : (
              customerFieldValue(fields[name]) || t("Not provided", "未提供")
            )}
          </dd>
        </div>
      ))}
    </dl>
  )
}
