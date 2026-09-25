import https from "node:https";
import { checkServerIdentity } from "node:tls";

const integerLexeme = /^-?(?:0|[1-9][0-9]*)$/;
const string = "string";
// E10: chaitin-cli@857ae38973b9c7886fc088a4065e3694202b7982 OpenAPI.
// Independent source bytes keep the existing packages and their hashes immutable.
const fields = {
  root_domain: {
    id: "identity", root_domain: string, status: string,
    icp_date: "nullableString", icp_num: "nullableString", icp_official_name: "nullableString",
    whois_registrant: "nullableString", whois_email: "nullableString", whois_expiration_time: "nullableString",
    valid_subdomain: "integer",
    sources: [{ source: string, reason: string, factor: string }],
    created_at: string, updated_at: string, lastseen_at: string,
  },
};

function fail(code = "cloudatlas_response_contract_failed") {
  throw new Error(code);
}

function object(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function integer(value) {
  const number = typeof value === "bigint" ? Number(value) : value;
  if (!Number.isSafeInteger(number)) fail();
  return number;
}

function project(value, schema, delta) {
  if (schema === "identity") {
    if (typeof value !== "bigint" || value.toString().length > 100) fail();
    return value.toString();
  }
  if (schema === "integer") return integer(value);
  if (schema === "nullableString" && value === null) return null;
  if (typeof schema === "string") {
    if (typeof value !== "string") fail();
    return value;
  }
  if (Array.isArray(schema)) {
    if (!Array.isArray(value)) fail();
    return value.map((item) => project(item, schema[0], delta));
  }
  if (!object(value)) fail();
  for (const key of Object.keys(value)) {
    if (!Object.hasOwn(schema, key)) delta.count++;
  }
  const result = {};
  for (const [key, type] of Object.entries(schema)) {
    if (!Object.hasOwn(value, key)) fail();
    result[key] = project(value[key], type, delta);
  }
  return result;
}

export function normalizePage(text, domain, page, size, spaceId) {
  let payload;
  try {
    // Node >=24 exposes the original numeric token: never round identity through Number.
    payload = JSON.parse(text, (_key, value, context) =>
      typeof value === "number" && integerLexeme.test(context.source)
        ? BigInt(context.source) : value,
    );
  } catch {
    fail();
  }
  if (!object(payload)) fail();
  const code = integer(payload.code);
  if (code === 401) fail("cloudatlas_authentication_failed");
  if (code === 403) fail("cloudatlas_authorization_failed");
  if (code !== 200) fail("cloudatlas_upstream_failed");
  const data = payload.data;
  if (!object(data) || !Array.isArray(data.items) || !Object.hasOwn(fields, domain)) fail();
  const total = integer(data.total);
  if (integer(data.current) !== page || integer(data.size) !== size || total < 0 || total > 2147483647) fail();
  if (data.items.length > size || data.items.length > total) fail();
  const delta = { count: 0 };
  const items = data.items.map((item) => {
    const row = project(item, fields[domain], delta);
    if (!row.root_domain.trim() || !row.status.trim()) fail();
    return row;
  });
  if (new Set(items.map((item) => item.id)).size !== items.length) fail();
  if (delta.count) {
    console.error(JSON.stringify({ code: "cloudatlas_field_delta", domain, omitted_field_count: delta.count }));
  }
  return { page, size, total, spaceId, itemsJson: JSON.stringify(items) };
}

export async function listPage(ctx, domain) {
  const { page, size, maxResponseBytes, timeoutSeconds } = ctx.request;
  if (!Number.isInteger(page) || page < 1 || page > 2147483647 ||
      !Number.isInteger(size) || size < 1 || size > 200 ||
      !Number.isInteger(maxResponseBytes) || maxResponseBytes < 1 || maxResponseBytes > 16777216 ||
      !Number.isInteger(timeoutSeconds) || timeoutSeconds < 1 || timeoutSeconds > 300 ||
      !Object.hasOwn(fields, domain)) fail("invalid_request");
  let base;
  try { base = new URL(ctx.config.baseUrl); } catch { fail("invalid_source_config"); }
  const spaceId = ctx.config.spaceId;
  const token = ctx.secret.token;
  if (base.protocol !== "https:" || base.username || base.password || base.search || base.hash ||
      !["/", "/openapi", "/openapi/"].includes(base.pathname) ||
      typeof spaceId !== "string" || !/^(?:0|[1-9][0-9]*)$/.test(spaceId) ||
      typeof token !== "string" || !token.trim() || /[^\x21-\x7e]/.test(token)) fail("invalid_source_config");
  const url = new URL("/openapi/v1/asset/root-domain", base.origin);
  url.search = new URLSearchParams({ space: spaceId, page: String(page), size: String(size), sort: "-id", status: "valid" }).toString();
  const body = await new Promise((resolve, reject) => {
    let response;
    let request;
    let settled = false;
    const chunks = [];
    let bytes = 0;
    const finish = (code, result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (code) {
        response?.destroy();
        request?.destroy();
        reject(new Error(code));
      } else resolve(result);
    };
    // Wall-clock budget includes DNS, TLS, headers, and every body chunk; no retry.
    const timer = setTimeout(() => finish("cloudatlas_connectivity_failed"), timeoutSeconds * 1000);
    try {
      request = https.request(url, {
        method: "GET", agent: false, rejectUnauthorized: true, checkServerIdentity,
        maxHeaderSize: 16384,
        headers: { TOKEN: token, Accept: "application/json", "Accept-Encoding": "identity" },
      }, (incoming) => {
        response = incoming;
        incoming.on("error", () => finish("cloudatlas_connectivity_failed"));
        incoming.on("aborted", () => finish("cloudatlas_connectivity_failed"));
        if (incoming.statusCode !== 200) {
          // Native https never follows redirects; do not read or disclose their bodies.
          finish(incoming.statusCode === 401 ? "cloudatlas_authentication_failed" :
            incoming.statusCode === 403 ? "cloudatlas_authorization_failed" : "cloudatlas_upstream_failed");
          return;
        }
        // Reject compression rather than buffering an unbounded decompressed response.
        const encoding = incoming.headers["content-encoding"];
        if (encoding && encoding.toLowerCase() !== "identity") {
          finish("cloudatlas_response_contract_failed");
          return;
        }
        const length = incoming.headers["content-length"];
        if (length && (!/^[0-9]+$/.test(length) || Number(length) > maxResponseBytes)) {
          finish("cloudatlas_response_contract_failed");
          return;
        }
        incoming.on("data", (chunk) => {
          bytes += chunk.length;
          if (bytes > maxResponseBytes) finish("cloudatlas_response_contract_failed");
          else if (!settled) chunks.push(chunk);
        });
        incoming.on("end", () => {
          if (settled) return;
          if (!incoming.complete) finish("cloudatlas_connectivity_failed");
          else finish(null, Buffer.concat(chunks, bytes));
        });
      });
      request.on("error", () => finish("cloudatlas_connectivity_failed"));
      request.end();
    } catch {
      finish("cloudatlas_connectivity_failed");
    }
  });
  let text;
  try { text = new TextDecoder("utf-8", { fatal: true }).decode(body); } catch { fail(); }
  return normalizePage(text, domain, page, size, spaceId);
}
