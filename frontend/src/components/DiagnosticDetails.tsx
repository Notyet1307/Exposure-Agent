import { parseDiagnosticDetail } from "@/lib/diagnostics"
import { useI18n } from "@/lib/i18n"

const fieldLabels: Record<string, [string, string]> = {
  asset_ip: ["Asset IP", "资产 IP"],
  start_port: ["Start port", "起始端口"],
  end_port: ["End port", "结束端口"],
  is_web: ["Web interface", "是否 Web 界面"],
  web_url: ["Web URL", "Web 界面 URL"],
  service_type: ["Service", "服务类型"],
  asset_owner: ["Declared owner", "原声明负责人"],
  asset_department: ["Asset department", "资产所属部门"],
  port_owner: ["Port owner", "端口负责人"],
  department: ["Department", "部门"],
  serial: ["Source number", "原序号"],
}

const reasonLabels: Record<string, [string, string]> = {
  invalid_required_value: ["Invalid required value", "必填值无效"],
  invalid_ip: ["IP address is invalid", "IP 地址无效"],
  port_not_integer: ["Port must be an integer", "端口必须为整数"],
  port_out_of_range: [
    "Port must be between 1 and 65535",
    "端口必须在 1 到 65535 之间",
  ],
  port_order: [
    "Start port must not exceed end port",
    "起始端口不得大于结束端口",
  ],
  web_flag: [
    "Web flag must be 是, 否 or 无",
    "是否 Web 字段必须为“是”、“否”或“无”",
  ],
  web_url: [
    "Web URL is invalid or does not match the Web flag",
    "Web URL 无效或与是否 Web 字段不一致",
  ],
  workbook_bytes: ["Workbook exceeds the admitted size", "工作簿超过允许大小"],
  request_bytes: [
    "Upload request exceeds the admitted size",
    "上传请求超过允许大小",
  ],
  workbook_entries: [
    "Workbook has too many ZIP entries",
    "工作簿 ZIP 条目过多",
  ],
  workbook_directory_bytes: [
    "Workbook central directory is too large",
    "工作簿中央目录过大",
  ],
  workbook_member_bytes: [
    "A workbook member is too large",
    "工作簿内部文件过大",
  ],
  workbook_total_bytes: [
    "Workbook expanded size is too large",
    "工作簿解压后总大小过大",
  ],
  unsupported_formula: [
    "Formulas and external links are not supported",
    "不支持公式或外部链接",
  ],
  merged_header: [
    "Header row must not contain merged cells",
    "表头行不得包含合并单元格",
  ],
  file_stat_failed: [
    "Workbook size could not be measured",
    "无法测量工作簿大小",
  ],
  unsupported_character: [
    "Cell contains an unsupported character",
    "单元格包含不支持的字符",
  ],
  unsupported_cell_value: ["Cell value is unsupported", "单元格值不受支持"],
}

const measurementLabels: Record<string, [string, string]> = {
  exact: ["exact file size", "精确文件大小"],
  declared: ["size declared by ZIP metadata", "ZIP 元数据声明大小"],
  received: ["bytes received so far", "当前已接收字节数"],
}

const locationLabels: Record<string, [string, string]> = {
  worksheet: ["accepted XLSX worksheet", "已接受的 XLSX 工作表"],
  ledger: ["customer ledger", "客户台账"],
}

/** Render a server diagnostic as inert text, with no raw parser or cell content. */
export function DiagnosticDetails({ detail }: { detail: unknown }) {
  const { t } = useI18n()
  const parsed = parseDiagnosticDetail(detail)
  if (!parsed) return null
  const rows: Array<{ label: string; value: string }> = []
  if (parsed.field) {
    const label = fieldLabels[parsed.field]
    rows.push({
      label: t("Field", "字段"),
      value: label ? t(label[0], label[1]) : parsed.field,
    })
  }
  if (parsed.row !== undefined) {
    rows.push({
      label:
        parsed.location === "ledger"
          ? t("Ledger row", "台账行")
          : t("Worksheet row", "工作表行"),
      value: String(parsed.row),
    })
  }
  if (parsed.column !== undefined) {
    rows.push({ label: t("Column", "列"), value: String(parsed.column) })
  }
  if (parsed.reason) {
    const label = reasonLabels[parsed.reason]
    rows.push({
      label: t("Reason", "原因"),
      value: label ? t(label[0], label[1]) : parsed.reason,
    })
  }
  if (parsed.limit !== undefined) {
    rows.push({
      label: t("Limit", "上限"),
      value: quantity(parsed.limit, parsed.unit, t),
    })
  }
  if (parsed.observed !== undefined) {
    rows.push({
      label: t("Observed", "实测"),
      value: quantity(parsed.observed, parsed.unit, t),
    })
  }
  if (parsed.measurement) {
    const label = measurementLabels[parsed.measurement]
    rows.push({
      label: t("Measurement", "测量方式"),
      value: label ? t(label[0], label[1]) : parsed.measurement,
    })
  }
  if (parsed.location) {
    const label = locationLabels[parsed.location]
    rows.push({
      label: t("Location", "位置"),
      value: label ? t(label[0], label[1]) : parsed.location,
    })
  }
  if (rows.length === 0) return null
  return (
    <dl
      data-testid="diagnostic-details"
      aria-label={t("Diagnostic details", "诊断详情")}
      className="mt-2 grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[max-content_1fr]"
    >
      {rows.map((row) => (
        <div key={row.label} className="contents">
          <dt className="text-muted-foreground">{row.label}</dt>
          <dd className="break-words">{row.value}</dd>
        </div>
      ))}
    </dl>
  )
}

function quantity(
  value: number,
  unit: string | undefined,
  t: (english: string, chinese: string) => string,
): string {
  const formatted = value.toLocaleString()
  if (unit === "bytes") {
    const mebibytes = value / (1024 * 1024)
    const suffix = Number.isInteger(mebibytes) ? ` (${mebibytes} MiB)` : ""
    return `${formatted} ${t("bytes", "字节")}${suffix}`
  }
  if (unit === "port_number") {
    return `${formatted} ${t("port number", "端口号")}`
  }
  if (unit === "entries") {
    return `${formatted} ${t("entries", "条目")}`
  }
  return unit ? `${formatted} ${unit}` : formatted
}
