import { ApiError } from "@/client"

export function netflowErrorCode(error: unknown): string | undefined {
  if (!(error instanceof ApiError)) return undefined
  const body = error.body
  if (body && typeof body === "object" && "detail" in body) {
    const detail = body.detail
    if (detail && typeof detail === "object" && "code" in detail)
      return typeof detail.code === "string" ? detail.code : undefined
    return typeof detail === "string" ? detail : undefined
  }
  return undefined
}

// Only definite pre-write rejections release a pending operation key. In
// particular, a key conflict may identify a previously committed operation.
export const netflowRequestRejected = (error: unknown) =>
  error instanceof ApiError &&
  ([400, 401, 403, 404, 410, 413, 415, 422].includes(error.status) ||
    (error.status === 409 &&
      netflowErrorCode(error) === "netflow_revision_conflict"))
