import { ApiError } from "@/client"

export type DiagnosticDetail = {
  code?: string
  message?: string
  field?: string
  row?: number
  column?: number
  reason?: string
  location?: string
  limit?: number
  observed?: number
  measurement?: string
  unit?: string
}

const text = (value: unknown, maximum = 160): string | undefined =>
  typeof value === "string" && value.length > 0
    ? Array.from(value).slice(0, maximum).join("")
    : undefined

const position = (value: unknown): number | undefined =>
  typeof value === "number" && Number.isSafeInteger(value) && value >= 1
    ? value
    : undefined

const amount = (value: unknown): number | undefined =>
  typeof value === "number" && Number.isSafeInteger(value) && value >= 0
    ? value
    : undefined

/** Parse only the documented diagnostic fields; ignore any extra server content. */
export function parseDiagnosticDetail(
  detail: unknown,
): DiagnosticDetail | null {
  if (!detail || typeof detail !== "object" || Array.isArray(detail))
    return null
  const value = detail as Record<string, unknown>
  const parsed: DiagnosticDetail = {
    code: text(value.code, 80),
    message: text(value.message, 500),
    field: text(value.field, 100),
    row: position(value.row),
    column: position(value.column),
    reason: text(value.reason, 100),
    location: text(value.location, 40),
    limit: amount(value.limit),
    observed: amount(value.observed),
    measurement: text(value.measurement, 40),
    unit: text(value.unit, 40),
  }
  return Object.values(parsed).some((item) => item !== undefined)
    ? parsed
    : null
}

export type WarningNameDetail = {
  name: string
  column: number
  nearMatch: string | null
}

export type WarningDetail = {
  names: WarningNameDetail[]
  truncated: boolean
  omittedCount: number
  namesTruncated: boolean
}

const MAX_WARNING_NAMES = 32
const MAX_WARNING_NAME_CHARACTERS = 64

/** Display-only text: remove control and bidi formatting characters, then bound length. */
export function displayWarningName(value: string): string {
  const cleaned = value.replace(/[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/gu, "")
  return Array.from(cleaned).slice(0, MAX_WARNING_NAME_CHARACTERS).join("")
}

/** Parse historical and current warning detail shapes without trusting either one. */
export function parseWarningDetail(detail: unknown): WarningDetail | null {
  if (!detail || typeof detail !== "object" || Array.isArray(detail))
    return null
  const value = detail as Record<string, unknown>
  const names: WarningNameDetail[] = []
  if (Array.isArray(value.names)) {
    for (const item of value.names.slice(0, MAX_WARNING_NAMES)) {
      if (!item || typeof item !== "object" || Array.isArray(item)) continue
      const entry = item as Record<string, unknown>
      const column = position(entry.column)
      if (typeof entry.name !== "string" || column === undefined) continue
      const nearMatch =
        typeof entry.near_match === "string"
          ? displayWarningName(entry.near_match)
          : ""
      names.push({
        name: displayWarningName(entry.name),
        column,
        nearMatch: nearMatch || null,
      })
    }
  }
  const omittedCount = amount(value.omitted_count) ?? 0
  const truncated = value.truncated === true || omittedCount > 0
  const namesTruncated = value.names_truncated === true
  return names.length > 0 || truncated || namesTruncated
    ? { names, truncated, omittedCount, namesTruncated }
    : null
}

/** Return only the structured error detail; ignore strings and non-API errors. */
export function apiErrorDetail(error: unknown): unknown {
  if (
    error instanceof ApiError &&
    error.body &&
    typeof error.body === "object" &&
    "detail" in error.body
  ) {
    const detail = (error.body as { detail?: unknown }).detail
    return detail && typeof detail === "object" ? detail : undefined
  }
  return undefined
}
