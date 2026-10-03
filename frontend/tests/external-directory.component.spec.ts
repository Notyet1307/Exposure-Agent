import { externalDomains } from "../src/lib/assetSearch"
import { expect, type Page, test } from "./fixtures"

const project = "00000000-0000-4000-8000-000000000001"
const stamp = "2026-10-03T00:00:00Z"
const uid = (prefix: string, n: number) =>
  `${prefix}-0000-4000-8000-${String(n).padStart(12, "0")}`
const profile = (domain: string) =>
  domain === "ip" || domain === "port"
    ? "assets-v1"
    : domain === "root_domain"
      ? "root-domains-v1"
      : `${domain.replaceAll("_", "-")}-v1`
const profiles = [...new Set(externalDomains.map(profile))]
const sid = (domain: string) =>
  uid("11111111", profiles.indexOf(profile(domain)) + 1)
const vid = (domain: string) =>
  uid("22222222", externalDomains.indexOf(domain as any) + 1)
const historic = uid("33333333", 1)
const url = (domain: string, version = vid(domain)) =>
  `/projects/${project}/cloudatlas-ledger?asset_view=synced&external_source=${sid(domain)}&external_domain=${domain}&external_version=${version}`
const labels: Record<string, string> = {
  ip: "IP",
  port: "Port services",
  root_domain: "Root domains",
  dns: "Subdomains / DNS",
  subdomain: "Subdomain intelligence",
  cert: "Certificates",
  openport: "Open ports",
  web: "Websites",
  dir: "Website paths",
  appfinger: "Website fingerprints",
  crawler: "Crawler data",
  seed_enterprise: "Enterprises",
  seed_keyword: "Keywords",
  seed_domain: "Domain WHOIS",
  seed_email: "Email domains",
  seed_cert: "Certificate information",
  seed_icon: "Website icons",
  seed_title: "Website titles",
}
async function serve(page: Page) {
  const state = {
    revoked: new Set<string>(),
    fail: new Set<string>(),
    empty: new Set<string>(),
    expiry: {} as Record<string, string>,
    reads: [] as URL[],
    records: [] as URL[],
  }
  const version = (domain: string, old = false) => ({
    id: old ? historic : vid(domain),
    source_id: sid(domain),
    domain,
    space_id: "281",
    status: "PUBLISHED",
    record_count: old
      ? 5
      : domain === "seed_keyword"
        ? 0
        : (externalDomains.indexOf(domain as any) + 1) * 3,
    complete: domain !== "seed_icon",
    expected_total: 100,
    pages_read: 1,
    stop_reason: "source_complete",
    filter: {},
    sort: "-id",
    fingerprint: "a".repeat(64),
    fetched_at: stamp,
    published_at: stamp,
    retain_until: state.expiry[domain] ?? "2099-01-01T00:00:00Z",
    omitted_field_count: 0,
  })
  await page.addInitScript(() =>
    localStorage.setItem("access_token", "synthetic-directory-token"),
  )
  await page.route("**/api/v1/**", async (route) => {
    expect(route.request().method()).toBe("GET")
    const u = new URL(route.request().url())
    if (u.pathname.endsWith("/users/me"))
      return route.fulfill({
        json: {
          id: uid("44444444", 1),
          email: "synthetic@example.com",
          is_active: true,
          is_superuser: true,
        },
      })
    if (u.pathname.endsWith("/external-assets/sources"))
      return route.fulfill({
        json: {
          data: profiles.map((p, i) => ({
            id: uid("11111111", i + 1),
            instance_id: p,
            capset_id: p,
            space_id: "281",
            capability_profile: p,
            enabled: true,
            data_access_enabled: !state.revoked.has(p),
            validation_status: "validated",
            validated_fingerprint: "a".repeat(64),
            created_at: stamp,
            updated_at: stamp,
          })),
          count: profiles.length,
          can_manage: false,
        },
      })
    if (u.pathname.endsWith("/versions")) {
      state.reads.push(u)
      const domain = u.searchParams.get("domain")!
      expect(u.pathname).toContain(sid(domain))
      if (state.fail.has(domain))
        return route.fulfill({
          status: 503,
          json: { detail: "Synthetic metadata unavailable" },
        })
      return route.fulfill({
        json: {
          data: state.empty.has(domain) ? [] : [version(domain)],
          count: state.empty.has(domain) ? 0 : 1,
          latest_complete_version: null,
        },
      })
    }
    if (u.pathname.endsWith("/records")) {
      state.records.push(u)
      const domain = u.searchParams.get("domain")!,
        v = version(domain, u.searchParams.get("version_id") === historic)
      const count = u.searchParams.has("q") ? 1 : v.record_count
      return route.fulfill({
        json: {
          data: Array.from({ length: Math.min(count, 25) }, (_, i) => ({
            id: uid("55555555", i + 1),
            version_id: v.id,
            source_id: String(i + 1),
            ip: null,
            canonical_ip: null,
            fields: {
              id: String(i + 1),
              name: "Synthetic",
              cn_name: "Synthetic",
              url: "https://synthetic.invalid/",
              ip: "192.0.2.1",
              port: 443,
              protocol: "tcp",
            },
          })),
          count,
          version: v,
          state: "PUBLISHED",
        },
      })
    }
    return route.fulfill({ json: { data: [], count: 0 } })
  })
  return state
}
test("all categories show their own fixed local counts before selection and click the counted version", async ({
  page,
}) => {
  const state = await serve(page)
  await page.goto(url("ip", historic))
  const nav = page.getByRole("navigation", { name: "Asset categories" })
  await nav.locator("summary").click()
  await expect(
    nav.getByRole("button", { name: "IP 5", exact: true }),
  ).toBeVisible()
  for (const d of externalDomains.filter((d) => d !== "ip")) {
    const n = d === "seed_keyword" ? 0 : (externalDomains.indexOf(d) + 1) * 3
    await expect(
      nav.getByRole("button", {
        name: `${labels[d]} ${n}${d === "seed_icon" ? " (partial)" : ""}`,
        exact: true,
      }),
    ).toBeVisible()
  }
  expect(
    state.records.every((u) => u.searchParams.get("domain") === "ip"),
  ).toBe(true)
  expect(new URL(page.url()).searchParams.get("external_version")).toBe(
    historic,
  )
  await nav
    .getByRole("button", { name: "Certificates 18", exact: true })
    .click()
  await expect(page).toHaveURL(new RegExp(`external_version=${vid("cert")}`))
  expect(new URL(page.url()).searchParams.get("external_source")).toBe(
    sid("cert"),
  )
  await page.locator('input[name="q"]').fill("Synthetic")
  await page
    .getByRole("button", { name: "Filter local records", exact: true })
    .click()
  await expect(
    nav.getByRole("button", { name: "Certificates 18", exact: true }),
  ).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(
    page
      .getByLabel("Asset domain", { exact: true })
      .locator('option[value="seed_keyword"]'),
  ).toHaveText("Keywords · 0")
})
test("unselected metadata failure, no versions, revocation and natural expiry never become false counts", async ({
  page,
}) => {
  await page.clock.install({ time: new Date("2026-10-03T10:00:00Z") })
  const state = await serve(page)
  state.fail.add("web")
  state.empty.add("root_domain")
  state.expiry.cert = "2026-10-03T10:00:05Z"
  await page.goto(url("ip"))
  const nav = page.getByRole("navigation", { name: "Asset categories" })
  await expect(
    nav.getByRole("button", { name: "Websites Unavailable", exact: true }),
  ).toBeVisible()
  await expect(
    nav.getByRole("button", { name: "Root domains Not read", exact: true }),
  ).toBeVisible()
  await expect(
    nav.getByRole("button", { name: "Certificates 18", exact: true }),
  ).toBeVisible()
  await expect(
    nav.getByRole("button", { name: "Website paths 27", exact: true }),
  ).toBeVisible()
  state.revoked.add("dir-v1")
  await page
    .getByRole("button", { name: "Refresh local access and data", exact: true })
    .click()
  await expect(
    nav.getByRole("button", { name: "Website paths Unavailable", exact: true }),
  ).toBeVisible()
  await expect(
    nav.getByRole("button", { name: "Website paths 27", exact: true }),
  ).toHaveCount(0)
  await page.clock.fastForward(5100)
  await expect(
    nav.getByRole("button", { name: "Certificates Expired", exact: true }),
  ).toBeVisible()
  expect(
    state.records.every((u) => u.searchParams.get("domain") === "ip"),
  ).toBe(true)
})

test("an explicit revoked source stays unavailable while another category can use its readable source", async ({
  page,
}) => {
  await serve(page)
  const other = uid("11111111", 999),
    portVersion = uid("22222222", 999)
  const version = (domain: string) => ({
    id: portVersion,
    source_id: other,
    domain,
    space_id: "281",
    status: "PUBLISHED",
    record_count: 9,
    complete: true,
    expected_total: 9,
    pages_read: 1,
    stop_reason: "source_complete",
    filter: {},
    sort: "-id",
    fingerprint: "a".repeat(64),
    fetched_at: stamp,
    published_at: stamp,
    retain_until: "2099-01-01T00:00:00Z",
    omitted_field_count: 0,
  })
  await page.route("**/external-assets/sources", (route) =>
    route.fulfill({
      json: {
        data: [sid("ip"), other].map((id) => ({
          id,
          instance_id: id,
          capset_id: id,
          space_id: "281",
          capability_profile: "assets-v1",
          enabled: false,
          data_access_enabled: id === other,
          validation_status: "validated",
          validated_fingerprint: "a".repeat(64),
          created_at: stamp,
          updated_at: stamp,
        })),
        count: 2,
        can_manage: false,
      },
    }),
  )
  await page.route(`**/external-assets/sources/${other}/versions?*`, (route) =>
    route.fulfill({
      json: {
        data: [
          version(new URL(route.request().url()).searchParams.get("domain")!),
        ],
        count: 1,
        latest_complete_version: null,
      },
    }),
  )
  await page.route(`**/external-assets/sources/${other}/records?*`, (route) =>
    route.fulfill({
      json: {
        data: [],
        count: 9,
        state: "PUBLISHED",
        version: version("port"),
      },
    }),
  )
  await page.goto(url("ip", historic))
  const nav = page.getByRole("navigation", { name: "Asset categories" })
  await expect(
    nav.getByRole("button", { name: "IP Unavailable", exact: true }),
  ).toBeVisible()
  await expect(
    nav.getByRole("button", { name: "Port services 9", exact: true }),
  ).toBeVisible()
  expect(new URL(page.url()).searchParams.get("external_source")).toBe(
    sid("ip"),
  )
  await nav
    .getByRole("button", { name: "Port services 9", exact: true })
    .click()
  await expect(page).toHaveURL(new RegExp(`external_source=${other}`))
  expect(new URL(page.url()).searchParams.get("external_version")).toBe(
    portVersion,
  )
})
