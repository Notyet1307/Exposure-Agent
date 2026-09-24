// EXP-FOCUS-01A: actual adapter body, synthetic CLI/SDK boundaries; no network or subprocess.
// Run: node --experimental-vm-modules tests/cloudatlas_fixture/verify_focus_contract.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { SourceTextModule, SyntheticModule, createContext } from "node:vm";

const context = createContext({});
const files = new Map();
let handlers;
let cliResult;
let calls = 0;
const error = (code, message) => Object.assign(new Error(message), { code });
const modules = {
  "node:child_process": {
    spawnSync: () => {
      calls++;
      return cliResult;
    },
  },
  "node:fs": {
    mkdtempSync: () => "/synthetic-only",
    writeFileSync: (path, data) => files.set(path, data),
    rmSync: () => files.clear(),
  },
  "node:os": { tmpdir: () => "/synthetic-only" },
  "node:path": { join: (...parts) => parts.join("/") },
  "@chaitin-ai/octobus-sdk": {
    defineService: (service) => service,
    runServiceMain: (service) => { handlers = service.handlers; },
    grpcError: error,
    grpcInvalidArgumentError: (message) => error(3, message),
    grpcPermissionDeniedError: (message) => error(7, message),
    grpcUnauthenticatedError: (message) => error(16, message),
    grpcUnavailableError: (message) => error(14, message),
    status: { DATA_LOSS: 15 },
  },
};
const adapter = new SourceTextModule(
  readFileSync(new URL("../../octobus/cloudatlas-read/bin/cloudatlas-read.js", import.meta.url), "utf8"),
  { context },
);
await adapter.link((name) => {
  assert.ok(Object.hasOwn(modules, name), `Unapproved capability: ${name}`);
  const exports = modules[name];
  return new SyntheticModule(Object.keys(exports), function () {
    for (const [key, value] of Object.entries(exports)) this.setExport(key, value);
  }, { context });
});
await adapter.evaluate();
const read = handlers["cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets"];
const invoke = (request = {}) => read({
  request,
  config: { baseUrl: "https://cloudatlas.invalid", spaceId: "synthetic-space" },
  secret: { token: "synthetic-only-not-a-credential" },
});
const cliPage = (items, current = 1, total = items.length) => {
  cliResult = { status: 0, stdout: JSON.stringify({ items, current, size: 2, total }) };
};
const native = (value) => JSON.parse(JSON.stringify(value));
const check = (id, fn) => {
  fn();
  assert.equal(files.size, 0, "Synthetic temporary config was not removed");
  console.log(`${id} PASS`);
};
const asset = { id: 7, ip: "2001:db8::7", status: "valid" };

check("SYN-01 projection", () => {
  cliPage([{ ...asset, synthetic_extra: "not in the RPC contract" }]);
  assert.deepEqual(native(invoke()), {
    items: [{ ...asset, id: "7" }], page: 1, size: 2, total: 1,
  });
});
check("SYN-02 empty", () => {
  cliPage([]);
  assert.deepEqual(native(invoke()).items, []);
  assert.equal(invoke().total, 0);
});
check("SYN-03 pages", () => {
  cliPage([asset, { ...asset, id: 8 }], 1, 3);
  const first = native(invoke({ page: 1, size: 2 }));
  cliPage([{ ...asset, id: 9 }], 2, 3);
  const second = native(invoke({ page: 2, size: 2 }));
  assert.deepEqual([first.page, second.page, first.total, second.total], [1, 2, 3, 3]);
  assert.deepEqual([...first.items, ...second.items].map((item) => item.id), ["7", "8", "9"]);
});
check("SYN-04 duplicate-preservation", () => {
  cliPage([asset, asset]);
  assert.deepEqual(native(invoke()).items, [{ ...asset, id: "7" }, { ...asset, id: "7" }]);
});
check("SYN-05 input-rejection", () => {
  const before = calls;
  for (const request of [{ status: "unknown" }, { page: -1 }, { size: 201 }]) {
    assert.throws(() => invoke(request), (failure) => failure.code === 3);
  }
  assert.equal(calls, before, "Invalid input reached the CLI boundary");
});
check("SYN-06 malformed-response", () => {
  for (const stdout of ["not-json", JSON.stringify({ unexpected: true })]) {
    cliResult = { status: 0, stdout };
    assert.throws(() => invoke(), (failure) => failure.code === 15);
  }
});
check("SYN-07 authentication-permission-redaction", () => {
  for (const [status, code] of [[401, 16], [403, 7]]) {
    cliResult = { status: 1, stderr: `${status} synthetic-sensitive-marker` };
    assert.throws(() => invoke(), (failure) =>
      failure.code === code && !failure.message.includes("synthetic-sensitive-marker"));
  }
});
check("SYN-08 later-page-failure", () => {
  cliPage([asset], 1, 2);
  invoke({ page: 1 });
  cliResult = { status: 1, stderr: "503 synthetic-sensitive-marker" };
  assert.throws(() => invoke({ page: 2 }), (failure) =>
    failure.code === 14 && !failure.message.includes("synthetic-sensitive-marker"));
  // This is not a database publication/rollback check; no database is loaded.
});
check("SYN-09 timeout", () => {
  cliResult = { status: null, error: { message: "ETIMEDOUT synthetic-sensitive-marker" } };
  assert.throws(() => invoke(), (failure) =>
    failure.code === 14 && !failure.message.includes("synthetic-sensitive-marker"));
});
console.log("9 checks PASS; actual adapter body only; SDK/CLI/filesystem simulated; real integration NOT_RUN");
