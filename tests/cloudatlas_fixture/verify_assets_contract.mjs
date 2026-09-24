import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { once } from "node:events";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import https from "node:https";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, test } from "node:test";
import { listPage, normalizePage } from "../../octobus/cloudatlas-assets/bin/source.js";

// Synthetic contract only. Run: node --test tests/cloudatlas_fixture/verify_assets_contract.mjs
const envelope = (item, total = 1) => `{"code":200,"data":{"current":1,"size":2,"total":${total},"items":[${item}]}}`;
const ip = (id = "9007199254740993123456789", extra = "") =>
  `{"id":${id},"ip":"2001:db8::1","status":"valid"${extra}}`;

test("decimal identities are lossless, nested fields project, and absence/null/empty stay distinct", (t) => {
  const warnings = [];
  t.mock.method(console, "error", (message) => warnings.push(JSON.parse(message)));
  const result = normalizePage(envelope(ip(undefined, ',"bu":{"id":9007199254740993,"name":""},"tags":[{"pk":9007199254740995,"name":"tag"}],"subnet":null,"sources":[],"unexpected":"discard"')), "ip", 1, 2, "7");
  assert.deepEqual(JSON.parse(result.itemsJson), [{
    id: "9007199254740993123456789", ip: "2001:db8::1", status: "valid",
    bu: { id: "9007199254740993", name: "" }, tags: [{ pk: "9007199254740995", name: "tag" }],
    subnet: null, sources: [],
  }]);
  assert.deepEqual(warnings, [{ code: "cloudatlas_field_delta", domain: "ip", omitted_field_count: 1 }]);
  for (const id of ['"9007199254740993"', "true", "null", "1.0", "1e3"]) {
    assert.throws(() => normalizePage(envelope(ip(id)), "ip", 1, 2, "7"), /cloudatlas_response_contract_failed/);
  }
  assert.throws(() => normalizePage(envelope(ip("1", ',"bu":""')), "ip", 1, 2, "7"), /cloudatlas_response_contract_failed/);
  assert.throws(() => normalizePage(envelope(ip("1", ',"tags":[{"pk":1.0,"name":"tag"}]')), "ip", 1, 2, "7"), /cloudatlas_response_contract_failed/);
  const ports = normalizePage(envelope('{"id":2,"ip":"192.0.2.1","port":443,"banner":null,"categories":["tls"],"tunnel":""}'), "port", 1, 2, "7");
  assert.deepEqual(JSON.parse(ports.itemsJson)[0], { id: "2", ip: "192.0.2.1", port: 443, banner: null, categories: ["tls"], tunnel: "" });
});

let directory;
let key;
let cert;
before(() => {
  directory = mkdtempSync(join(tmpdir(), "assets-contract-tls-"));
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
  t.after(() => {
    server.closeAllConnections();
    server.close();
  });
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

test("TLS rejects an untrusted certificate before sending credentials", async (t) => {
  let calls = 0;
  const ctx = await source(t, (_req, res) => { calls++; res.end(envelope(ip())); }, false);
  await assert.rejects(listPage(ctx, "ip"), { message: "cloudatlas_connectivity_failed" });
  assert.equal(calls, 0);
});

test("TLS verifies hostname even with a trusted certificate", async (t) => {
  let calls = 0;
  const ctx = await source(t, (_req, res) => { calls++; res.end(envelope(ip())); });
  ctx.config.baseUrl = ctx.config.baseUrl.replace("127.0.0.1", "localhost");
  await assert.rejects(listPage(ctx, "ip"), { message: "cloudatlas_connectivity_failed" });
  assert.equal(calls, 0);
});

test("exact GET range and TOKEN stay on the configured origin; redirects are not followed", async (t) => {
  const calls = [];
  const ctx = await source(t, (req, res) => {
    calls.push({ method: req.method, url: req.url, token: req.headers.token });
    if (req.url.startsWith("/openapi/v1/asset/ip")) {
      res.writeHead(302, { Location: "/other" });
      res.end("never disclose source body");
    } else res.end(envelope('{"id":2,"ip":"192.0.2.1","port":443}'));
  });
  await assert.rejects(listPage(ctx, "ip"), { message: "cloudatlas_upstream_failed" });
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0], { method: "GET", url: "/openapi/v1/asset/ip?space=7&page=1&size=2&sort=-id&status=valid", token: "synthetic-token" });
  const page = await listPage(ctx, "port");
  assert.equal(JSON.parse(page.itemsJson)[0].port, 443);
  assert.equal(calls[1].url, "/openapi/v1/attack/port?space=7&page=1&size=2&sort=-id");
});

test("streaming cap stops chunked oversized bodies without trusting Content-Length", async (t) => {
  let ended = false;
  const ctx = await source(t, (_req, res) => {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.write("x".repeat(2048));
    const timer = setTimeout(() => { ended = true; res.end("rest"); }, 1000);
    res.on("close", () => clearTimeout(timer));
  });
  ctx.request.maxResponseBytes = 1024;
  await assert.rejects(listPage(ctx, "ip"), { message: "cloudatlas_response_contract_failed" });
  assert.equal(ended, false);
});

test("continuous chunks cannot reset the wall-clock deadline", async (t) => {
  const ctx = await source(t, (_req, res) => {
    res.writeHead(200);
    const timer = setInterval(() => res.write(" "), 25);
    res.on("close", () => clearInterval(timer));
  });
  ctx.request.timeoutSeconds = 1;
  await assert.rejects(listPage(ctx, "ip"), { message: "cloudatlas_connectivity_failed" });
});

test("compression and truncated bodies fail closed", async (t) => {
  let calls = 0;
  const ctx = await source(t, (_req, res) => {
    if (++calls === 1) {
      res.writeHead(200, { "Content-Encoding": "gzip" });
      res.end("not accepted compressed content");
    } else {
      res.writeHead(200, { "Content-Length": "2048" });
      res.write('{"code":200,');
      res.flushHeaders();
      setImmediate(() => res.destroy());
    }
  });
  await assert.rejects(listPage(ctx, "ip"), { message: "cloudatlas_response_contract_failed" });
  await assert.rejects(listPage(ctx, "ip"), { message: "cloudatlas_connectivity_failed" });
  assert.equal(calls, 2);
});
