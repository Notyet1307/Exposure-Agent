import { readFileSync } from "node:fs"
import { validateAssetSearch } from "../src/lib/assetSearch"
import { expect, type Page, test } from "./fixtures"

const contracts = JSON.parse(
  readFileSync(
    new URL(
      "../../backend/app/domain/cloudatlas_structured.schema.json",
      import.meta.url,
    ),
    "utf8",
  ),
).domains
const project = "00000000-0000-4000-8000-000000000001"
const source = "11111111-1111-4111-8111-111111111111"
const versionId = "22222222-2222-4222-8222-222222222222"
const recordId = "44444444-4444-4444-8444-444444444444"
const root = `/projects/${project}/cloudatlas-ledger?asset_view=synced&external_source=${source}`
const stamp = "2026-10-03T00:00:00Z"
const sample = (shape: any, key = ""): any => {
  if (shape.enum) return shape.enum[0]
  if (shape.type === "identity") return "900719925474099312345"
  if (shape.type === "integer")
    return key === "id" || key === "pk" ? "900719925474099312345" : 0
  if (shape.type === "number") return 0
  if (shape.type === "boolean") return false
  if (shape.type === "string")
    return key === "ip"
      ? "2001:db8::7"
      : key.endsWith("_at")
        ? stamp
        : `Synthetic ${key} <img src=https://never-fetch.example/x> %_\\`
  if (shape.type === "array") return [sample(shape.items)]
  return Object.fromEntries(
    Object.entries(shape.properties).map(([k, v]) => [k, sample(v, k)]),
  )
}
async function serve(page: Page, domain: string, canManage = false) {
  const definition = contracts[domain],
    calls: URL[] = []
  const version = {
    id: versionId,
    source_id: source,
    domain,
    space_id: "7",
    status: "PUBLISHED",
    record_count: 1,
    complete: true,
    expected_total: 1,
    pages_read: 1,
    stop_reason: "source_complete",
    filter: definition.filters,
    sort: "-id",
    fingerprint: "a".repeat(64),
    fetched_at: stamp,
    published_at: stamp,
    retain_until: "2099-01-01T00:00:00Z",
    omitted_field_count: 2,
  }
  const fields = sample(definition.schema)
  if (domain === "seed_icon") fields.icon_url = null
  if (domain === "crawler") delete fields.target
  const record = {
    id: recordId,
    version_id: versionId,
    source_id: fields.id,
    ip: fields.ip ?? null,
    canonical_ip: fields.ip ?? null,
    fields,
  }
  await page.addInitScript(() =>
    localStorage.setItem("access_token", "synthetic-component-token"),
  )
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url())
    calls.push(url)
    expect(route.request().method()).toBe("GET")
    if (url.pathname.endsWith("/users/me"))
      return route.fulfill({
        json: {
          id: "66666666-6666-4666-8666-666666666666",
          email: "test@example.com",
          is_active: true,
          is_superuser: true,
        },
      })
    if (url.pathname.endsWith("/sources"))
      return route.fulfill({
        json: {
          data: [
            {
              id: source,
              instance_id: `synthetic-${domain}`,
              capset_id: `synthetic-${domain}`,
              space_id: "7",
              capability_profile: definition.profile,
              enabled: true,
              data_access_enabled: true,
              validation_status: "validated",
              validated_fingerprint: "a".repeat(64),
              created_at: stamp,
              updated_at: stamp,
            },
          ],
          count: 1,
          can_manage: canManage,
        },
      })
    if (!url.pathname.includes("/external-assets/"))
      return route.fulfill({ json: { data: [], count: 0 } })
    if (url.pathname.endsWith("/versions"))
      return route.fulfill({
        json: { data: [version], count: 1, latest_complete_version: version },
      })
    if (url.pathname.endsWith(`/records/${recordId}`))
      return route.fulfill({
        json: {
          record,
          version,
          matched_ports: [],
          matched_port_count: 0,
          port_version: null,
        },
      })
    if (url.pathname.endsWith("/records")) {
      if (url.searchParams.get("ip") === "bad/cidr")
        return route.fulfill({
          status: 422,
          json: { detail: { code: "external_ip_filter_invalid" } },
        })
      return route.fulfill({
        json: { data: [record], count: 1, version, state: "PUBLISHED" },
      })
    }
    return route.fulfill({ json: { data: [], count: 0 } })
  })
  return { calls, fields }
}
test("structured URL validation rejects mixed readers and preserves false after canonicalization", () => {
  for (const d of Object.keys(contracts))
    expect(validateAssetSearch({ external_domain: d }).external_domain).toBe(d)
  expect(validateAssetSearch({ external_domain: "not-real" })).toEqual({
    asset_error: "invalid",
  })
  expect(validateAssetSearch({ external_seed_enabled: "0" })).toEqual({
    asset_error: "invalid",
  })
  expect(validateAssetSearch({ cloud_page: 0, external_q: "value" })).toEqual({
    asset_error: "conflict",
  })
  expect(
    validateAssetSearch(
      validateAssetSearch({
        external_domain: "seed_keyword",
        external_seed_enabled: "false",
      }),
    ).external_seed_enabled,
  ).toBe(false)
})
for (const domain of Object.keys(contracts))
  test(`${domain}: fixed list, grouped fields, escaped values and keyboard return`, async ({
    page,
  }) => {
    const { calls, fields } = await serve(page, domain)
    await page.goto(
      `${root}&external_domain=${domain}&external_version=${versionId}`,
    )
    const details = page.getByRole("link", { name: /Details for/ }).first()
    await expect(details).toBeVisible()
    if (domain.startsWith("seed_"))
      await expect(page.getByText("enable=true", { exact: true })).toBeVisible()
    if (domain === "openport")
      await expect(
        page.getByText("Source-default scope", { exact: true }),
      ).toBeVisible()
    if (domain === "dir")
      await expect(
        page.getByText(/^(status=valid · flat=1|flat=1 · status=valid)$/),
      ).toBeVisible()
    await details.focus()
    await page.keyboard.press("Enter")
    const dialog = page.getByRole("dialog")
    await expect(dialog).toBeVisible()
    await dialog.getByText("Technical trace", { exact: true }).click()
    await expect(
      dialog.getByText("900719925474099312345", { exact: true }).first(),
    ).toBeVisible()
    for (const field of Object.keys(contracts[domain].schema.properties).filter(
      (k) => k !== "id",
    )) {
      if (
        typeof fields[field] === "string" &&
        !field.endsWith("_at") &&
        fields[field] !== "valid"
      )
        await expect(
          dialog.getByText(fields[field], { exact: true }).first(),
        ).toBeVisible()
    }
    expect(await dialog.locator("img").count()).toBe(0)
    if (domain === "seed_icon")
      await expect(dialog.getByText("Null", { exact: true })).toBeVisible()
    if (domain === "crawler")
      await expect(dialog.getByText("Missing", { exact: true })).toBeVisible()
    if (domain === "seed_enterprise")
      await expect(
        dialog.getByText("credit_code", { exact: true }),
      ).toHaveCount(0)
    await page.keyboard.press("Escape")
    await expect(dialog).toHaveCount(0)
    await expect(details).toBeFocused()
    expect(
      calls
        .filter((u) => u.pathname.endsWith("/records"))
        .every(
          (u) =>
            u.searchParams.get("domain") === domain &&
            u.searchParams.get("version_id") === versionId,
        ),
    ).toBe(true)
  })
test("openport exact-IP queries run and display invalid-IP errors", async ({
  page,
}) => {
  const { calls } = await serve(page, "openport")
  await page.goto(
    `${root}&external_domain=openport&external_version=${versionId}&external_ip=2001%3Adb8%3A%3A7`,
  )
  await expect(page.getByRole("link", { name: /Details for/ })).toBeVisible()
  expect(
    calls.some(
      (u) =>
        u.pathname.endsWith("/records") &&
        u.searchParams.get("ip") === "2001:db8::7",
    ),
  ).toBe(true)
  await page
    .getByLabel("Exact IP (IPv4 or IPv6)", { exact: true })
    .fill("bad/cidr")
  await page
    .getByRole("button", { name: "Filter local records", exact: true })
    .click()
  await expect(
    page.getByLabel("Exact IP (IPv4 or IPv6)", { exact: true }),
  ).toHaveAttribute("aria-invalid", "true")
})
test("incompatible deep-link filters are removed before a new profile reads records", async ({
  page,
}) => {
  const { calls } = await serve(page, "web")
  await page.goto(
    `${root}&external_domain=cert&external_sha256=stale&external_seed_enabled=false&external_seed_type=like`,
  )
  await expect(page.getByRole("link", { name: /Details for/ })).toBeVisible()
  expect(
    calls
      .filter((u) => u.pathname.endsWith("/records"))
      .every(
        (u) =>
          u.searchParams.get("domain") === "web" &&
          !u.searchParams.has("sha256") &&
          !u.searchParams.has("seed_enabled") &&
          !u.searchParams.has("seed_type"),
      ),
  ).toBe(true)
  expect(new URL(page.url()).searchParams.has("external_sha256")).toBe(false)
})

for (const domain of ["openport", "seed_enterprise", "dir"])
  test(`${domain}: manual authorization describes only its fixed type and budget`, async ({
    page,
  }) => {
    await serve(page, domain, true)
    await page.goto(
      `${root}&external_domain=${domain}&external_version=${versionId}`,
    )
    await page.getByRole("button", { name: "Update data", exact: true }).click()
    await expect(
      page.getByText(/reserved for this one type, with at least one page/),
    ).toBeVisible()
    await expect(page.getByText(/Both domains start at page 1/)).toHaveCount(0)
    if (domain.startsWith("seed_"))
      await expect(page.getByText(/only; enable=true; sort=-id/)).toBeVisible()
    if (domain === "openport")
      await expect(
        page.getByText(/source-default scope; no status filter/),
      ).toBeVisible()
    await expect(
      page.getByLabel("Maximum pages", { exact: true }),
    ).toHaveAttribute("min", "1")
  })
