import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { once } from "node:events";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import https from "node:https";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, test } from "node:test";
import { listPage, normalizePage } from "../../octobus/cloudatlas-root-domains/bin/source.js";

// Synthetic only: node --test tests/cloudatlas_fixture/verify_root_domains_contract.mjs
const row = () => ({
  id: "9007199254740993123456789", root_domain: "MiXeD.Example.invalid", status: "source-status",
  icp_date: null, icp_num: "", icp_official_name: null,
  whois_registrant: "", whois_email: null, whois_expiration_time: null,
  valid_subdomain: 7, sources: [{ source: "declared", reason: "<script>text</script>", factor: "" }],
  created_at: "2026-01-02 03:04:05", updated_at: "", lastseen_at: "2026-01-03T00:00:00+08:00",
});
const envelope = (items = [row()], patch = {}) => JSON.stringify({ code: 200, data: {
  current: 1, size: 2, total: items.length, items, ...patch,
} }).replace(/"id":"(-?[0-9]+)"/g, '"id":$1');
const normalize = (text) => normalizePage(text, "root_domain", 1, 2, "7");
const contractFailure = { message: "cloudatlas_response_contract_failed" };

test("all fourteen fields and nested sources are required; only six fields accept null", () => {
  const original = row();
  const nullable = new Set(["icp_date", "icp_num", "icp_official_name", "whois_registrant", "whois_email", "whois_expiration_time"]);
  assert.deepEqual(JSON.parse(normalize(envelope()).itemsJson), [original]);
  for (const field of Object.keys(original)) {
    const missing = { ...original };
    delete missing[field];
    assert.throws(() => normalize(envelope([missing])), contractFailure);
    const nulled = { ...original, [field]: null };
    if (nullable.has(field)) assert.equal(JSON.parse(normalize(envelope([nulled])).itemsJson)[0][field], null);
    else assert.throws(() => normalize(envelope([nulled])), contractFailure);
  }
  for (const field of ["source", "reason", "factor"]) {
    const nested = { ...original.sources[0] };
    delete nested[field];
    assert.throws(() => normalize(envelope([{ ...original, sources: [nested] }])), contractFailure);
    assert.throws(() => normalize(envelope([{ ...original, sources: [{ ...original.sources[0], [field]: null }] }])), contractFailure);
  }
  for (const patch of [{ root_domain: " " }, { status: "" }, { sources: {} }, { valid_subdomain: true }, { valid_subdomain: 1.5 }, { whois_email: 7 }, { id: "9".repeat(101) }]) {
    assert.throws(() => normalize(envelope([{ ...original, ...patch }])), contractFailure);
  }
  for (const id of ['"123"', "1.0", "1e3", "true", "null"]) {
    const text = envelope().replace('"id":9007199254740993123456789', `"id":${id}`);
    assert.throws(() => normalize(text), contractFailure);
  }
});

test("same-name distinct large IDs survive; unknown fields emit only a count", (t) => {
  const warnings = [];
  t.mock.method(console, "error", (message) => warnings.push(JSON.parse(message)));
  const original = row();
  const extra = { ...original, "secret-field-name": "private-value", sources: [{ ...original.sources[0], email: "private@example.invalid" }] };
  const other = { ...original, id: "9007199254740993123456790", sources: [] };
  assert.deepEqual(JSON.parse(normalize(envelope([extra, other])).itemsJson), [original, other]);
  assert.deepEqual(warnings, [{ code: "cloudatlas_field_delta", domain: "root_domain", omitted_field_count: 2 }]);
  assert.throws(() => normalize(envelope([original, original])), contractFailure);
  assert.deepEqual(JSON.parse(normalize(envelope([])).itemsJson), []);
  for (const patch of [{ current: 2 }, { size: 3 }, { total: -1 }, { total: 0 }, { total: 2147483648 }, { total: true }]) {
    assert.throws(() => normalize(envelope([original], patch)), contractFailure);
  }
  assert.throws(() => normalize(envelope([original, other, { ...other, id: "3" }], { total: 3 })), contractFailure);
  assert.throws(() => normalize('not-json-with-private-content'), contractFailure);
});

let directory;
let key;
let cert;
before(() => {
  directory = mkdtempSync(join(tmpdir(), "root-domains-contract-tls-"));
  const keyPath = join(directory, "key.pem");
  const certPath = join(directory, "cert.pem");
  execFileSync("openssl", ["req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1", "-keyout", keyPath, "-out", certPath], { stdio: "ignore" });
  key = readFileSync(keyPath);
  cert = readFileSync(certPath);
});
after(() => rmSync(directory, { recursive: true, force: true }));

async function source(t, handler, trust = true) {
  const server = https.createServer({ key, cert }, handler);
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  t.after(() => { server.closeAllConnections(); server.close(); });
  if (trust) {
    const request = https.request;
    t.mock.method(https, "request", (url, options, callback) => request(url, { ...options, ca: cert }, callback));
  }
  return {
    request: { page: 1, size: 2, maxResponseBytes: 4096, timeoutSeconds: 2 },
    config: { baseUrl: `https://127.0.0.1:${server.address().port}`, spaceId: "7" },
    secret: { token: "synthetic-token" },
  };
}

test("TLS rejects untrusted roots before credentials are sent", async (t) => {
  let calls = 0;
  const ctx = await source(t, (_req, res) => { calls++; res.end(envelope()); }, false);
  await assert.rejects(listPage(ctx, "root_domain"), { message: "cloudatlas_connectivity_failed" });
  assert.equal(calls, 0);
});

test("TLS checks hostname even when the certificate is trusted", async (t) => {
  let calls = 0;
  const ctx = await source(t, (_req, res) => { calls++; res.end(envelope()); });
  ctx.config.baseUrl = ctx.config.baseUrl.replace("127.0.0.1", "localhost");
  await assert.rejects(listPage(ctx, "root_domain"), { message: "cloudatlas_connectivity_failed" });
  assert.equal(calls, 0);
});

test("only fixed valid/-id root GETs run; redirect and upstream errors stay sanitized", async (t) => {
  const calls = [];
  let statusCode = 302;
  const ctx = await source(t, (req, res) => {
    calls.push({ method: req.method, url: req.url, token: req.headers.token });
    res.writeHead(statusCode, { Location: "/private-redirect" });
    res.end(statusCode === 200 ? envelope() : "private-body-and-token");
  });
  for (const [code, message] of [[302, "cloudatlas_upstream_failed"], [401, "cloudatlas_authentication_failed"], [403, "cloudatlas_authorization_failed"], [503, "cloudatlas_upstream_failed"]]) {
    statusCode = code;
    await assert.rejects(listPage(ctx, "root_domain"), { message });
  }
  assert.equal(calls.length, 4);
  for (const call of calls) assert.deepEqual(call, { method: "GET", url: "/openapi/v1/asset/root-domain?space=7&page=1&size=2&sort=-id&status=valid", token: "synthetic-token" });
  statusCode = 200;
  assert.deepEqual(JSON.parse((await listPage(ctx, "root_domain")).itemsJson), [row()]);
  for (const domain of ["ip", "port", "unknown"]) await assert.rejects(listPage(ctx, domain), { message: "invalid_request" });
  assert.equal(calls.length, 5);
});

test("streaming overflow, compression and truncated responses are refused", async (t) => {
  let calls = 0;
  const ctx = await source(t, (_req, res) => {
    calls++;
    if (calls === 1) {
      res.writeHead(200);
      res.write("x".repeat(2048));
    } else if (calls === 2) {
      res.writeHead(200, { "Content-Encoding": "gzip" });
      res.end("compressed-private-content");
    } else {
      res.writeHead(200, { "Content-Length": "1024" });
      res.write('{"code":200,');
      res.flushHeaders();
      setImmediate(() => res.destroy());
    }
  });
  ctx.request.maxResponseBytes = 1024;
  await assert.rejects(listPage(ctx, "root_domain"), contractFailure);
  await assert.rejects(listPage(ctx, "root_domain"), contractFailure);
  await assert.rejects(listPage(ctx, "root_domain"), { message: "cloudatlas_connectivity_failed" });
  assert.equal(calls, 3);
});

test("wall-clock deadline is not reset by continuous chunks", async (t) => {
  const ctx = await source(t, (_req, res) => {
    res.writeHead(200);
    const timer = setInterval(() => res.write(" "), 25);
    res.on("close", () => clearInterval(timer));
  });
  ctx.request.timeoutSeconds = 1;
  await assert.rejects(listPage(ctx, "root_domain"), { message: "cloudatlas_connectivity_failed" });
});

test("invalid request/configuration never starts a source call", async (t) => {
  let calls = 0;
  const ctx = await source(t, (_req, res) => { calls++; res.end(envelope()); });
  for (const patch of [{ page: 0 }, { size: 201 }, { maxResponseBytes: 16777217 }, { timeoutSeconds: 301 }]) {
    await assert.rejects(listPage({ ...ctx, request: { ...ctx.request, ...patch } }, "root_domain"), { message: "invalid_request" });
  }
  for (const baseUrl of [ctx.config.baseUrl.replace("https:", "http:"), ctx.config.baseUrl + "/other", ctx.config.baseUrl + "?status=all"]) {
    await assert.rejects(listPage({ ...ctx, config: { ...ctx.config, baseUrl } }, "root_domain"), { message: "invalid_source_config" });
  }
  await assert.rejects(listPage({ ...ctx, secret: { token: "" } }, "root_domain"), { message: "invalid_source_config" });
  assert.equal(calls, 0);
});
