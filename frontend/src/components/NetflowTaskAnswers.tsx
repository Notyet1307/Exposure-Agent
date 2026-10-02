import { type ReactNode, useEffect, useMemo, useRef, useState } from "react"
import { z } from "zod"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useI18n } from "@/lib/i18n"
import { netflowText } from "@/lib/netflow-labels"

type Schema = Record<string, unknown>
type Answers = Record<string, unknown>
const obj = (x: unknown): Schema | undefined =>
  x && typeof x === "object" && !Array.isArray(x) ? (x as Schema) : undefined
const resolve = (
  root: Schema,
  raw: Schema,
  seen = new Set<string>(),
): Schema => {
  if (typeof raw.$ref === "string" && raw.$ref.startsWith("#/$defs/")) {
    if (seen.has(raw.$ref)) return raw
    seen.add(raw.$ref)
    const target = obj(obj(root.$defs)?.[raw.$ref.slice(8)])
    return target
      ? { ...resolve(root, target, seen), title: raw.title ?? target.title }
      : raw
  }
  const choices = Array.isArray(raw.anyOf)
    ? (raw.anyOf.map(obj).filter(Boolean) as Schema[])
    : []
  const selected = choices.find((item) => item.type !== "null")
  return selected ? { ...selected, title: raw.title ?? selected.title } : raw
}
const copy = (x: Answers) => structuredClone(x)
const put = (x: Answers, path: string[], value: unknown) => {
  const out = copy(x)
  let at = out
  for (const key of path.slice(0, -1)) {
    const next = obj(at[key])
    if (next) at = next
    else {
      const created: Answers = {}
      at[key] = created
      at = created
    }
  }
  at[path[path.length - 1]!] = value
  return out
}
const drop = (x: Answers, path: string[]) => {
  const out = copy(x)
  let at = out
  for (const key of path.slice(0, -1)) {
    const next = obj(at[key])
    if (!next) return out
    at = next
  }
  delete at[path[path.length - 1]!]
  return out
}
const title = (key: string, schema: Schema) =>
  typeof schema.title === "string" ? schema.title : key
const valueState = (value: unknown) =>
  value === undefined ? "missing" : value === null ? "null" : "value"
const fieldNames: Record<string, string> = {
  responsible_unit: "Responsible unit",
  supporting_evidence: "Supporting evidence",
  business_role: "Business role",
  business_purpose: "Business purpose",
  actual_service: "Actual service",
  external_access_need: "External access need",
  access_control: "Access control",
  nat_mapping: "NAT mapping",
  mapping_time_window: "Mapping time window",
  observation_window: "Observation window",
  observation_view: "Observation view",
  additional_dataset: "Additional dataset",
  coverage_notes: "Coverage notes",
  sampling: "Sampling",
  rate: "Sampling rate",
  mode: "Sampling mode",
  protocol: "Protocol",
  pre_ip: "Pre-NAT IP",
  pre_port: "Pre-NAT port",
  post_ip: "Post-NAT IP",
  post_port: "Post-NAT port",
  start: "Start time",
  end: "End time",
  input_timezone: "Input timezone",
  counter_semantics: "Counter semantics",
  export_selection: "Export selection",
  direction_semantics: "Direction semantics",
  tcp_flags_semantics: "TCP flags semantics",
  cause_assessment: "Cause assessment",
}
const fieldChinese: Record<string, string> = {
  responsible_unit: "责任单位",
  supporting_evidence: "材料引用",
  business_role: "业务角色",
  business_purpose: "业务用途",
  actual_service: "实际服务",
  external_access_need: "对外访问需求",
  access_control: "访问控制",
  nat_mapping: "NAT 映射",
  mapping_time_window: "映射时间窗",
  observation_window: "观测时间窗",
  observation_view: "观测视角",
  additional_dataset: "补充数据集",
  coverage_notes: "覆盖说明",
  sampling: "采样情况",
  rate: "采样率",
  mode: "采样方式",
  protocol: "协议编号",
  pre_ip: "转换前 IP",
  pre_port: "转换前端口",
  post_ip: "转换后 IP",
  post_port: "转换后端口",
  start: "开始时间",
  end: "结束时间",
  input_timezone: "输入时区",
  counter_semantics: "计数语义",
  export_selection: "导出选择",
  direction_semantics: "方向语义",
  tcp_flags_semantics: "TCP 标志语义",
  cause_assessment: "原因判断",
}
const enumChinese: Record<string, string> = {
  service_provider: "服务提供方",
  outbound_client: "对外访问客户端",
  mixed: "混合角色",
  nat_aggregate: "NAT 聚合端点",
  unknown: "未知",
  UNKNOWN: "未知",
  required: "需要",
  not_required: "不需要",
  sampled: "已采样",
  unsampled: "未采样",
  PUBLIC_EDGE: "公网边界",
  INTERNAL: "内网",
  BEFORE_NAT: "转换前",
  AFTER_NAT: "转换后",
  BOTH: "转换前后",
}
const enumNames: Record<string, string> = {
  service_provider: "Service provider",
  outbound_client: "Outbound client",
  mixed: "Mixed",
  nat_aggregate: "NAT aggregate",
  unknown: "Unknown",
  required: "Required",
  not_required: "Not required",
  sampled: "Sampled",
  unsampled: "Unsampled",
  PUBLIC_EDGE: "Public edge",
  INTERNAL: "Internal",
  BEFORE_NAT: "Before NAT",
  AFTER_NAT: "After NAT",
  BOTH: "Both",
}
function known(root: Schema, raw: Schema, value: unknown): boolean {
  if (value === undefined || value === null) return true
  const schema = resolve(root, raw)
  if (schema.type === "array")
    return (
      Array.isArray(value) &&
      value.every((item) => known(root, obj(schema.items) ?? {}, item))
    )
  const record = obj(value)
  if (schema.type === "object") {
    const properties = obj(schema.properties) ?? {}
    if (!record) return false
    return Object.keys(record).every(
      (key) =>
        Object.keys(properties).includes(key) &&
        known(root, obj(properties[key]) ?? {}, record[key]),
    )
  }
  return true
}
function issues(root: Schema, schema: Schema, value: unknown): string[] {
  if (value === undefined) return []
  const resolved = resolve(root, schema),
    errors: string[] = []
  const alternatives = Array.isArray(schema.anyOf) ? schema.anyOf.map(obj) : []
  if (value === null)
    return alternatives.some((item) => item?.type === "null") ||
      schema.type === "null"
      ? []
      : ["value cannot be null"]
  const expected = resolved.type
  if (
    (expected === "object" && !obj(value)) ||
    (expected === "array" && !Array.isArray(value)) ||
    (expected === "string" && typeof value !== "string") ||
    (expected === "boolean" && typeof value !== "boolean") ||
    ((expected === "number" || expected === "integer") &&
      (typeof value !== "number" || !Number.isFinite(value)))
  )
    return ["incorrect value type"]
  if (expected === "integer" && !Number.isInteger(value))
    errors.push("whole number required")
  if (typeof value === "string") {
    if (
      typeof resolved.minLength === "number" &&
      value.length < resolved.minLength
    )
      errors.push("too short")
    if (
      typeof resolved.maxLength === "number" &&
      value.length > resolved.maxLength
    )
      errors.push("too long")
    if (
      typeof resolved.pattern === "string" &&
      !new RegExp(resolved.pattern).test(value)
    )
      errors.push("invalid format")
    const ipChoice =
      alternatives.some((item) => item?.format === "ipv4") &&
      alternatives.some((item) => item?.format === "ipv6")
    if (
      ipChoice
        ? !z.ipv4().safeParse(value).success &&
          !z.ipv6().safeParse(value).success
        : resolved.format === "ipv4"
          ? !z.ipv4().safeParse(value).success
          : resolved.format === "ipv6"
            ? !z.ipv6().safeParse(value).success
            : false
    )
      errors.push("invalid IP address")
    if (
      resolved.format === "date-time" &&
      !z.iso.datetime({ offset: true }).safeParse(value).success
    )
      errors.push("invalid date and time")
  }
  if (typeof value === "number") {
    if (typeof resolved.minimum === "number" && value < resolved.minimum)
      errors.push(`minimum ${resolved.minimum}`)
    if (
      typeof resolved.exclusiveMinimum === "number" &&
      value <= resolved.exclusiveMinimum
    )
      errors.push(`must exceed ${resolved.exclusiveMinimum}`)
    if (typeof resolved.maximum === "number" && value > resolved.maximum)
      errors.push(`maximum ${resolved.maximum}`)
  }
  if (Array.isArray(value)) {
    if (
      typeof resolved.minItems === "number" &&
      value.length < resolved.minItems
    )
      errors.push(`at least ${resolved.minItems} items`)
    if (
      typeof resolved.maxItems === "number" &&
      value.length > resolved.maxItems
    )
      errors.push(`at most ${resolved.maxItems} items`)
    if (
      resolved.uniqueItems &&
      new Set(value.map((item) => JSON.stringify(item))).size !== value.length
    )
      errors.push("items must be unique")
    const item = obj(resolved.items) ?? {}
    value.forEach((itemValue, index) => {
      errors.push(
        ...issues(root, item, itemValue).map(
          (error) => `item ${index + 1}: ${error}`,
        ),
      )
    })
  }
  const record = obj(value)
  if (record && resolved.type === "object") {
    if (record.mode === "unknown" && record.rate !== null)
      errors.push("unknown sampling requires a null rate")
    if (record.mode === "unsampled" && record.rate !== 1)
      errors.push("unsampled rate must be 1")
    if (
      typeof record.start === "string" &&
      typeof record.end === "string" &&
      Date.parse(record.end) < Date.parse(record.start)
    )
      errors.push("end must not precede start")
    for (const key of (resolved.required as string[] | undefined) ?? [])
      if (!(key in record)) errors.push(`${key} is required`)
    for (const [key, child] of Object.entries(obj(resolved.properties) ?? {}))
      errors.push(
        ...issues(root, obj(child) ?? {}, record[key]).map(
          (error) => `${key}: ${error}`,
        ),
      )
  }
  if (Array.isArray(resolved.enum) && !resolved.enum.includes(value))
    errors.push("choose a listed option")
  return errors
}

function valid(schema: Schema, answers: Answers) {
  return Object.entries(obj(schema.properties) ?? {}).every(
    ([key, raw]) => issues(schema, obj(raw) ?? {}, answers[key]).length === 0,
  )
}

export function NetflowTaskAnswers({
  schema,
  declared,
  serverErrors = [],
  identity,
  disabled,
  onChange,
}: {
  schema: Schema
  declared: Answers
  serverErrors?: Array<Record<string, unknown>>
  identity: string
  disabled: boolean
  onChange: (answers: Answers, supported: boolean, valid: boolean) => void
}) {
  const { t } = useI18n()
  const properties = obj(schema.properties) ?? {}
  const supported = useMemo(
    () =>
      Object.keys(declared).every((key) =>
        Object.keys(properties).includes(key),
      ) &&
      Object.values(properties).every((raw) =>
        supports(schema, obj(raw) ?? {}),
      ) &&
      Object.entries(declared).every(([key, value]) =>
        known(schema, obj(properties[key]) ?? {}, value),
      ),
    [declared, properties, schema],
  )
  const [answers, setAnswers] = useState<Answers>({})
  const initialized = useRef<string | undefined>(undefined)
  useEffect(() => {
    if (initialized.current === identity) return
    initialized.current = identity
    const next = copy(declared)
    setAnswers(next)
    onChange(next, supported, valid(schema, next))
  }, [identity, supported, onChange, declared, schema])
  const update = (path: string[], value: unknown) => {
    const next = put(answers, path, value)
    setAnswers(next)
    onChange(next, supported, valid(schema, next))
  }
  const unset = (path: string[]) => {
    const next = drop(answers, path)
    setAnswers(next)
    onChange(next, supported, valid(schema, next))
  }
  if (!supported)
    return (
      <p role="alert" className="text-sm text-destructive">
        {t(
          "Unsupported answer structure or retained unknown field. Existing answers remain unchanged and cannot be edited here.",
          "答案结构或保留字段尚不受此界面支持。原答案保持不变，请查看技术详情。",
        )}
      </p>
    )
  return (
    <section className="space-y-3" aria-label={t("Review answers", "复核答案")}>
      <p className="text-sm text-muted-foreground">
        {t(
          "You may save partial material. Fields marked below are needed for completeness; complete material still requires human review.",
          "可以保存部分材料。标注字段需补齐才算材料齐全；齐全后仍需人工复核。",
        )}
      </p>
      {Object.entries(properties).map(([key, raw]) => (
        <Field
          key={key}
          root={schema}
          path={[key]}
          schema={resolve(schema, obj(raw) ?? {})}
          value={answers[key]}
          errors={[
            ...issues(schema, obj(raw) ?? {}, answers[key]),
            ...(JSON.stringify(answers[key]) === JSON.stringify(declared[key])
              ? serverErrors
                  .filter((error) => String(error.field).split(".")[0] === key)
                  .map((error) => netflowText(String(error.code), t))
              : []),
          ]}
          requiredForCompletion={
            Array.isArray(schema.required_for_completeness) &&
            schema.required_for_completeness.includes(key)
          }
          disabled={disabled}
          onChange={update}
          onUnset={unset}
        />
      ))}
    </section>
  )
}

function supports(root: Schema, raw: Schema, depth = 0): boolean {
  if (depth > 6) return false
  const schema = resolve(root, raw)
  if (
    Array.isArray(schema.enum) ||
    ["string", "number", "integer", "boolean"].includes(String(schema.type))
  )
    return true
  if (schema.type === "array") {
    const item = resolve(root, obj(schema.items) ?? {})
    return (
      item.type === "string" ||
      (item.type === "object" &&
        Object.values(obj(item.properties) ?? {}).every((child) =>
          supports(root, obj(child) ?? {}, depth + 1),
        ))
    )
  }
  return (
    schema.type === "object" &&
    Object.values(obj(schema.properties) ?? {}).every((child) =>
      supports(root, obj(child) ?? {}, depth + 1),
    )
  )
}

function Field({
  root,
  path,
  schema,
  value,
  errors,
  requiredForCompletion = false,
  disabled,
  onChange,
  onUnset,
}: {
  root: Schema
  path: string[]
  schema: Schema
  value: unknown
  errors: string[]
  requiredForCompletion?: boolean
  disabled: boolean
  onChange: (path: string[], value: unknown) => void
  onUnset: (path: string[]) => void
}) {
  const { t } = useI18n()
  const key = path[path.length - 1]!
  const name = t(
      fieldNames[key] ?? key,
      fieldChinese[key] ?? title(key, schema),
    ),
    id = `answer-${path.join("-")}`,
    status = valueState(value)
  const stateChange = (next: string) => {
    if (next === "missing") onUnset(path)
    else if (next === "null") onChange(path, null)
    else if (schema.type === "array") onChange(path, [])
    else if (schema.type === "object") onChange(path, {})
    else if (schema.type === "boolean") onChange(path, false)
    else onChange(path, "")
  }
  let control: ReactNode
  if (Array.isArray(schema.enum))
    control = (
      <select
        id={id}
        className="mt-1 block w-full rounded border bg-background p-2"
        value={status === "value" ? String(value) : ""}
        disabled={disabled || status !== "value"}
        onChange={(e) => onChange(path, e.target.value)}
      >
        <option value="">{t("Choose", "请选择")}</option>
        {schema.enum.map((item) => (
          <option key={String(item)} value={String(item)}>
            {t(
              enumNames[String(item)] ?? String(item),
              enumChinese[String(item)] ?? String(item),
            )}
          </option>
        ))}
      </select>
    )
  else if (schema.type === "boolean")
    control = (
      <input
        id={id}
        type="checkbox"
        checked={value === true}
        disabled={disabled || status !== "value"}
        onChange={(e) => onChange(path, e.target.checked)}
      />
    )
  else if (schema.type === "number" || schema.type === "integer")
    control = (
      <Input
        id={id}
        type="number"
        min={typeof schema.minimum === "number" ? schema.minimum : undefined}
        max={typeof schema.maximum === "number" ? schema.maximum : undefined}
        value={status === "value" ? String(value) : ""}
        disabled={disabled || status !== "value"}
        onChange={(e) =>
          onChange(path, e.target.value === "" ? "" : Number(e.target.value))
        }
      />
    )
  else if (schema.type === "array")
    control = (
      <ArrayField
        id={id}
        root={root}
        path={path}
        schema={schema}
        value={value}
        disabled={disabled || status !== "value"}
        onChange={onChange}
      />
    )
  else if (schema.type === "object")
    control = (
      <ObjectField
        root={root}
        path={path}
        schema={schema}
        value={obj(value) ?? {}}
        disabled={disabled || status !== "value"}
        onChange={onChange}
        onUnset={onUnset}
      />
    )
  else
    control = (
      <textarea
        id={id}
        className="mt-1 min-h-20 w-full rounded border bg-background p-2"
        value={status === "value" ? String(value) : ""}
        disabled={disabled || status !== "value"}
        onChange={(e) => onChange(path, e.target.value)}
      />
    )
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{name}</Label>
      {requiredForCompletion && (
        <span className="text-xs text-muted-foreground">
          {t("Needed for complete material", "齐全材料所需")}
        </span>
      )}
      <select
        aria-label={t(`${name} value state`, `${name}填写状态`)}
        className="ml-2 rounded border bg-background p-1 text-xs"
        value={status}
        disabled={disabled}
        onChange={(e) => stateChange(e.target.value)}
      >
        <option value="missing">{t("Not supplied", "未填写")}</option>
        <option value="null">{t("Unknown (null)", "明确空值（null）")}</option>
        <option value="value">{t("Provide value", "填写值")}</option>
      </select>
      {control}
      {errors.length > 0 && (
        <span role="alert" className="block text-sm text-destructive">
          {errors.map((error) => errorText(error, t)).join(t("; ", "；"))}
        </span>
      )}
    </div>
  )
}

function errorText(error: string, t: (en: string, zh: string) => string) {
  let chinese = error
  const words: Record<string, string> = {
    "value cannot be null": "不能填写空值",
    "incorrect value type": "值类型不正确",
    "whole number required": "请输入整数",
    "too short": "内容太短",
    "too long": "内容太长",
    "invalid format": "格式无效",
    "invalid IP address": "IP 地址格式无效",
    "invalid date and time": "日期时间无效，请包含时区",
    "items must be unique": "条目不能重复",
    "unknown sampling requires a null rate": "未知采样方式须将采样率设为空值",
    "unsampled rate must be 1": "未采样的保留比例必须为 1",
    "end must not precede start": "结束时间不得早于开始时间",
    "choose a listed option": "请选择列表中的选项",
    " is required": "为必填字段",
    "minimum ": "最小值为 ",
    "maximum ": "最大值为 ",
    "must exceed ": "必须大于 ",
    "at least ": "最少需要 ",
    "at most ": "最多允许 ",
    " items": " 个条目",
    "item ": "条目 ",
  }
  for (const [en, zh] of Object.entries(words))
    chinese = chinese.split(en).join(zh)
  for (const [en, zh] of Object.entries(fieldChinese))
    chinese = chinese.split(en).join(zh)
  return t(error, chinese)
}

function ObjectField({
  root,
  path,
  schema,
  value,
  disabled,
  onChange,
  onUnset,
}: {
  root: Schema
  path: string[]
  schema: Schema
  value: Schema
  disabled: boolean
  onChange: (path: string[], value: unknown) => void
  onUnset: (path: string[]) => void
}) {
  const { t } = useI18n()
  const field = path[path.length - 1]!
  return (
    <fieldset className="grid gap-3 rounded border p-3 sm:grid-cols-2">
      <legend>
        {t(
          fieldNames[field] ?? title(field, schema),
          fieldChinese[field] ?? title(field, schema),
        )}
      </legend>
      {Object.entries(obj(schema.properties) ?? {}).map(([key, raw]) => (
        <Field
          key={key}
          root={root}
          path={[...path, key]}
          schema={resolve(root, obj(raw) ?? {})}
          value={value[key]}
          errors={issues(root, obj(raw) ?? {}, value[key])}
          disabled={disabled}
          onChange={onChange}
          onUnset={onUnset}
        />
      ))}
    </fieldset>
  )
}

function ArrayField({
  id,
  root,
  path,
  schema,
  value,
  disabled,
  onChange,
}: {
  id: string
  root: Schema
  path: string[]
  schema: Schema
  value: unknown
  disabled: boolean
  onChange: (path: string[], value: unknown) => void
}) {
  const { t } = useI18n()
  const field = path[path.length - 1]!
  const item = resolve(root, obj(schema.items) ?? {})
  if (item.type === "string")
    return (
      <textarea
        id={id}
        className="mt-1 min-h-20 w-full rounded border bg-background p-2"
        value={Array.isArray(value) ? value.join("\n") : ""}
        disabled={disabled}
        onChange={(e) =>
          onChange(
            path,
            e.target.value === "" ? [] : e.target.value.split("\n"),
          )
        }
      />
    )
  const rows = Array.isArray(value) ? value : [],
    properties = obj(item.properties) ?? {}
  return (
    <fieldset className="space-y-2 rounded border p-3">
      <legend>
        {t(
          fieldNames[field] ?? title(field, schema),
          fieldChinese[field] ?? title(field, schema),
        )}
      </legend>
      {rows.map((row, index) => (
        <div key={index} className="grid gap-2 sm:grid-cols-2">
          {Object.entries(properties).map(([key, raw]) => (
            <Field
              key={key}
              root={root}
              path={[...path, String(index), key]}
              schema={resolve(root, obj(raw) ?? {})}
              value={obj(row)?.[key]}
              errors={issues(root, obj(raw) ?? {}, obj(row)?.[key])}
              disabled={disabled}
              onUnset={() => {
                const next = rows.slice(),
                  itemValue = obj(next[index]) ?? {}
                delete itemValue[key]
                next[index] = itemValue
                onChange(path, next)
              }}
              onChange={(_, nextValue) => {
                const next = rows.slice()
                next[index] = { ...(obj(row) ?? {}), [key]: nextValue }
                onChange(path, next)
              }}
            />
          ))}
          <Button
            type="button"
            variant="outline"
            disabled={disabled}
            onClick={() =>
              onChange(
                path,
                rows.filter((_, i) => i !== index),
              )
            }
          >
            {t("Remove mapping", "删除映射")}
          </Button>
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        disabled={disabled}
        onClick={() => onChange(path, [...rows, {}])}
      >
        {t("Add mapping", "添加映射")}
      </Button>
    </fieldset>
  )
}
