import https from "node:https";
import { checkServerIdentity } from "node:tls";
import { createHash } from "node:crypto";
import bundle from "../contract.json" with { type: "json" };

export const contracts = bundle.domains;
const integerLexeme = /^-?(?:0|[1-9][0-9]*)$/;
function fail(code = "cloudatlas_response_contract_failed") { throw new Error(code); }
function object(value) { return value !== null && typeof value === "object" && !Array.isArray(value); }
function integer(value) {
  const number = typeof value === "bigint" ? Number(value) : value;
  if (!Number.isSafeInteger(number)) fail();
  return number;
}
function project(value, schema, delta, omitted = []) {
  if (schema.nullable && value === null) return null;
  switch (schema.type) {
    case "identity":
      if (typeof value !== "bigint" || value.toString().length > 100) fail();
      return value.toString();
    case "integer": return integer(value);
    case "boolean":
      if (typeof value !== "boolean") fail();
      return value;
    case "string":
      if (typeof value !== "string" || (schema.enum && !schema.enum.includes(value))) fail();
      // Keep valid JSON control characters, including NUL, but reject unpaired surrogates.
      if (!value.isWellFormed()) fail();
      return value;
    case "array":
      if (!Array.isArray(value)) fail();
      return value.map((item) => project(item, schema.items, delta));
    case "object": {
      if (!object(value) || schema.required.some((key) => !Object.hasOwn(value, key))) fail();
      for (const key of Object.keys(value)) {
        if (!Object.hasOwn(schema.properties, key) && !omitted.includes(key)) delta.count++;
      }
      const output = {};
      for (const [key, child] of Object.entries(schema.properties)) {
        if (Object.hasOwn(value, key)) output[key] = project(value[key], child, delta);
      }
      return output;
    }
    default: fail();
  }
}
function typeOf(value) {
  if (value === null) return "null";
  if (typeof value === "bigint") return "integer";
  if (Array.isArray(value)) return "array";
  return typeof value;
}
// Only paths from the frozen schema can become diagnostic keys. Values and
// unexpected source field names never leave this boundary, even on type errors.
function diagnose(items, schema, omitted) {
  const fields = {};
  let unknownFields = 0;
  function visit(value, shape, path, present = true) {
    const entry = fields[path] ??= { present: 0, missing: 0, types: {}, invalidEnum: 0 };
    if (!present) { entry.missing++; return; }
    entry.present++;
    const type = typeOf(value); entry.types[type] = (entry.types[type] ?? 0) + 1;
    if (shape.enum && !shape.enum.includes(value)) entry.invalidEnum++;
    // E12/E13 define only these two known BU child names. Inspect their types
    // to qualify the declared-string mismatch; normal reads remain strict.
    if (path === "$.bu" && shape.type === "string" && object(value)) {
      shape = { type: "object", properties: { id: { type: "identity" }, name: { type: "string" } } };
    }
    if (shape.type === "object" && object(value)) {
      for (const key of Object.keys(value)) {
        if (!Object.hasOwn(shape.properties, key) && !(path === "$" && omitted.includes(key))) unknownFields++;
      }
      for (const [key, child] of Object.entries(shape.properties)) {
        visit(value[key], child, `${path}.${key}`, Object.hasOwn(value, key));
      }
    } else if (shape.type === "array" && Array.isArray(value)) {
      for (const item of value) visit(item, shape.items, `${path}[]`);
    }
  }
  for (const item of items) visit(item, schema, "$");
  return { itemCount: items.length, fields, unknownFieldCount: unknownFields };
}
export function normalizePage(text, domain, page, size, spaceId, diagnosticsOnly = false) {
  const contract = contracts[domain];
  if (!contract) fail();
  let payload;
  try {
    payload = JSON.parse(text, (_key, value, context) =>
      typeof value === "number" && integerLexeme.test(context.source) ? BigInt(context.source) : value,
    );
  } catch { fail(); }
  if (!object(payload)) fail();
  const code = integer(payload.code);
  if (code === 401) fail("cloudatlas_authentication_failed");
  if (code === 403) fail("cloudatlas_authorization_failed");
  if (code !== 200) fail("cloudatlas_upstream_failed");
  if (typeof payload.message !== "string" || !object(payload.data)) fail();
  const data = payload.data;
  const total = integer(data.total);
  if (!Array.isArray(data.items) || integer(data.current) !== page || integer(data.size) !== size ||
      total < 0 || total > 2147483647 || data.items.length > size || data.items.length > total) fail();
  if (diagnosticsOnly) {
    if (page !== 1 || size > 20) fail("invalid_request");
    return { page, size, total, spaceId, itemsJson: "[]", diagnosticsJson: JSON.stringify({
      ...diagnose(data.items, contract.schema, contract.omitted_fields),
      responseSha256: createHash("sha256").update(text).digest("hex"),
    }) };
  }
  const delta = { count: 0 };
  const items = data.items.map((item) => project(item, contract.schema, delta, contract.omitted_fields));
  if (new Set(items.map((item) => item.id)).size !== items.length) fail();
  if (delta.count) console.error(JSON.stringify({ code: "cloudatlas_field_delta", domain, omitted_field_count: delta.count }));
  return { page, size, total, spaceId, itemsJson: JSON.stringify(items), omittedFieldCount: delta.count };
}
export async function listPage(ctx, domain) {
  const { page, size, maxResponseBytes, timeoutSeconds, diagnosticsOnly = false } = ctx.request;
  const contract = contracts[domain];
  if (!Number.isInteger(page) || page < 1 || page > 2147483647 ||
      !Number.isInteger(size) || size < 1 || size > 200 ||
      !Number.isInteger(maxResponseBytes) || maxResponseBytes < 1 || maxResponseBytes > 16777216 ||
      !Number.isInteger(timeoutSeconds) || timeoutSeconds < 1 || timeoutSeconds > 300 ||
      typeof diagnosticsOnly !== "boolean" || !contract ||
      (diagnosticsOnly && (page !== 1 || size > 20 || maxResponseBytes > 4194304 || timeoutSeconds > 120))) fail("invalid_request");
  let base;
  try { base = new URL(ctx.config.baseUrl); } catch { fail("invalid_source_config"); }
  const spaceId = ctx.config.spaceId;
  const token = ctx.secret.token;
  if (base.protocol !== "https:" || base.username || base.password || base.search || base.hash ||
      !["/", "/openapi", "/openapi/"].includes(base.pathname) ||
      typeof spaceId !== "string" || !/^(?:0|[1-9][0-9]*)$/.test(spaceId) ||
      typeof token !== "string" || !token.trim() || /[^\x21-\x7e]/.test(token)) fail("invalid_source_config");
  const url = new URL("/openapi" + contract.path, base.origin);
  url.search = new URLSearchParams({ space: spaceId, page: String(page), size: String(size), sort: "-id", ...contract.filters }).toString();
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
  return normalizePage(text, domain, page, size, spaceId, diagnosticsOnly);
}
