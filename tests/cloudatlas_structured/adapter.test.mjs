import assert from "node:assert/strict";
import { test } from "node:test";
import { contracts, normalizePage, listPage } from "../../octobus/cloudatlas-structured/bin/source.js";

const sample = (shape, key = "") => {
  if (shape.enum) return shape.enum[0];
  if (shape.type === "identity") return 900719925474099312345n;
  if (shape.type === "integer") return key === "port" ? 443 : 1;
  if (shape.type === "boolean") return true;
  if (shape.type === "string") return key === "status" ? "valid" : key === "ip" ? "2001:db8::1" : "synthetic\\literal\u0000value";
  if (shape.type === "array") return [sample(shape.items)];
  return Object.fromEntries(Object.entries(shape.properties).map(([key, value]) => [key, sample(value, key)]));
};
const envelope = (items, size = 20) => JSON.stringify({
  code: 200, message: "ok", data: { current: 1, size, total: items.length, items },
}, (_key, value) => typeof value === "bigint" ? JSON.rawJSON(value.toString()) : value);

for (const [domain, contract] of Object.entries(contracts)) {
  test(`${domain}: exact fields, lossless ids, missing/null and type rejection`, () => {
    const input = sample(contract.schema);
    input.unknown_private_field = "do not preserve";
    if (domain === "crawler") { input.headers = "Bearer do-not-store"; input.data = "do-not-store"; }
    const out = JSON.parse(normalizePage(envelope([input]), domain, 1, 20, "900719925474099312345").itemsJson)[0];
    assert.equal(out.id, "900719925474099312345");
    assert.equal(out.unknown_private_field, undefined);
    assert.equal(out.headers, undefined);
    assert.equal(out.data, undefined);
    assert.deepEqual(Object.keys(out).sort(), Object.keys(contract.schema.properties).sort());
    const missing = { ...input }; delete missing.id;
    assert.throws(() => normalizePage(envelope([missing]), domain, 1, 20, "7"), /contract_failed/);
    assert.throws(() => normalizePage(envelope([{ ...input, id: "123" }]), domain, 1, 20, "7"), /contract_failed/);
    assert.throws(() => normalizePage(envelope([input, input]), domain, 1, 20, "7"), /contract_failed/);
    for (const [key, schema] of Object.entries(contract.schema.properties)) {
      if (schema.nullable) {
        assert.equal(JSON.parse(normalizePage(envelope([{ ...input, [key]: null }]), domain, 1, 20, "7").itemsJson)[0][key], null);
      } else assert.throws(() => normalizePage(envelope([{ ...input, [key]: null }]), domain, 1, 20, "7"), /contract_failed/);
      if (!contract.schema.required.includes(key)) {
        const partial = { ...input }; delete partial[key];
        assert.equal(Object.hasOwn(JSON.parse(normalizePage(envelope([partial]), domain, 1, 20, "7").itemsJson)[0], key), false);
      }
    }
  });
  test(`${domain}: bounded diagnostics disclose types only`, () => {
    const input = sample(contract.schema);
    input.unknown_private_field = { do_not_leak: "sensitive" };
    if (domain === "crawler") { input.headers = "private credential"; input.data = "private body"; }
    if (Object.hasOwn(input, "bu")) input.bu = { do_not_leak: "unapproved shape" };
    const result = normalizePage(envelope([input]), domain, 1, 20, "7", true);
    assert.equal(result.itemsJson, "[]");
    assert.doesNotMatch(result.diagnosticsJson, /sensitive|do_not_leak|unknown_private_field|private credential|private body|unapproved shape/);
    const stats = JSON.parse(result.diagnosticsJson);
    assert.equal(stats.itemCount, 1);
    assert.match(stats.responseSha256, /^[0-9a-f]{64}$/);
    assert.equal(stats.fields["$.id"].types.integer, 1);
    if (Object.hasOwn(input, "bu")) {
      assert.equal(stats.fields["$.bu"].types.object, 1);
      assert.equal(stats.fields["$.bu.id"].missing, 1);
      assert.equal(stats.fields["$.bu.name"].missing, 1);
    }
    assert.throws(() => normalizePage(envelope([input], 21), domain, 1, 21, "7", true), /invalid_request/);
    assert.throws(() => normalizePage(envelope([input]), domain, 2, 20, "7", true), /contract_failed|invalid_request/);
  });
}
test("diagnostic budget and domain guard reject before any network access", async () => {
  const request = { page: 1, size: 20, maxResponseBytes: 4194304, timeoutSeconds: 120, diagnosticsOnly: true };
  for (const extra of [{ page: 2 }, { size: 21 }, { maxResponseBytes: 4194305 }, { timeoutSeconds: 121 }, { diagnosticsOnly: "true" }]) {
    await assert.rejects(listPage({ request: { ...request, ...extra } }, "web"), /invalid_request/);
  }
  await assert.rejects(listPage({ request }, "not-a-domain"), /invalid_request/);
});
