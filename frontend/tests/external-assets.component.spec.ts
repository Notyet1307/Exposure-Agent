import { expect, type Page, test } from "./fixtures"

const project = "00000000-0000-4000-8000-000000000001"
const source = "11111111-1111-4111-8111-111111111111"
const ipVersion = "22222222-2222-4222-8222-222222222222"
const portVersion = "33333333-3333-4333-8333-333333333333"
const recordId = "44444444-4444-4444-8444-444444444444"
const taskId = "55555555-5555-4555-8555-555555555555"
const routePath = `/projects/${project}/external-assets?external_source=${source}`
const stamp = "2026-09-01T00:00:00Z"
const retention = "2099-01-01T00:00:00Z"

// Synthetic HTTP responses exercise the real generated service and real route.
// This is not an OctoBus or CloudAtlas integration test.
async function serve(page: Page, rootDomains = false) {
  const state = {
    denied: false,
    expired: false,
    canManage: true,
    enabled: true,
    lostSubmission: false,
    purged: false,
    submissions: [] as { key: string; body: unknown }[],
    tasks: new Map<string, object>(),
  }
  const version = {
    id: ipVersion,
    source_id: source,
    domain: rootDomains ? "root_domain" : "ip",
    space_id: "7",
    status: "PUBLISHED",
    record_count: 1,
    complete: !rootDomains,
    expected_total: rootDomains ? 200 : 1,
    pages_read: 1,
    stop_reason: rootDomains ? "batch_limit" : "source_complete",
    filter: { status: "valid" },
    sort: "-id",
    fingerprint: "a".repeat(64),
    fetched_at: stamp,
    published_at: stamp,
    retain_until: retention,
  }
  const row = {
    id: recordId,
    version_id: ipVersion,
    source_id: "9007199254740993",
    ip: rootDomains ? null : "2001:db8::7",
    canonical_ip: rootDomains ? null : "2001:db8::7",
    fields: rootDomains
      ? {
          id: "9007199254740993",
          root_domain: "Example.test",
          status: "valid",
          icp_date: null,
          icp_num: "",
          icp_official_name: "<img src=x onerror=alert(1)>",
          whois_registrant: null,
          whois_email: "synthetic@example.test",
          whois_expiration_time: null,
          valid_subdomain: 57,
          sources: [
            {
              source: "synthetic",
              reason: "<script>bad()</script>",
              factor: "https://example.test/never-fetch",
            },
          ],
          created_at: "2026-09-01 10:00:00",
          updated_at: "2026-09-01 12:34:56",
          lastseen_at: "2026-09-01 12:00:00",
        }
      : {
          id: "9007199254740993",
          ip: "2001:db8::7",
          status: "valid",
          bu: { id: "9007199254740995", name: "Synthetic private group" },
          tags: [],
          provider: null,
          subnet: "",
          updated_at: "2026-09-01 12:34:56",
          sources: [
            {
              source: "synthetic",
              reason: "<img src=x onerror=alert(1)>",
              factor: 1,
              lastseen_at: "2026-09-01 12:34:56",
            },
          ],
        },
  }
  await page.addInitScript(() =>
    localStorage.setItem("access_token", "synthetic-component-token"),
  )
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname.endsWith("/users/me"))
      return route.fulfill({
        json: {
          id: "66666666-6666-4666-8666-666666666666",
          email: "test@example.com",
          full_name: "Test",
          is_active: true,
          is_superuser: true,
        },
      })
    if (url.pathname.endsWith("/external-assets/sources"))
      return route.fulfill({
        json: {
          data: [
            {
              id: source,
              instance_id: "synthetic-assets",
              capset_id: "synthetic-capset",
              space_id: "7",
              capability_profile: rootDomains ? "root-domains-v1" : "assets-v1",
              enabled: state.enabled,
              data_access_enabled: true,
              validation_status: "validated",
              validated_fingerprint: "a".repeat(64),
              created_at: stamp,
              updated_at: stamp,
            },
          ],
          count: 1,
          can_manage: state.canManage,
        },
      })
    if (!url.pathname.includes("/external-assets/"))
      return route.fulfill({ json: { data: [], count: 0 } })
    if (state.denied)
      return route.fulfill({
        status: 403,
        json: { detail: { code: "external_data_access_revoked" } },
      })
    if (url.pathname.endsWith("/purge-expired")) {
      state.purged = true
      return route.fulfill({ json: { deleted_records: 1 } })
    }
    if (url.pathname.endsWith("/syncs") && request.method() === "POST") {
      const key = request.headers()["idempotency-key"]
      state.submissions.push({ key, body: request.postDataJSON() })
      if (!state.tasks.has(key))
        state.tasks.set(key, {
          id: taskId,
          source_id: source,
          status: rootDomains ? "PARTIAL_SUCCEEDED" : "SUCCEEDED",
          created_at: stamp,
          started_at: stamp,
          completed_at: stamp,
          retain_until: retention,
          error_code: null,
          agent_run_id: "synthetic-run",
          session_id: "synthetic-session",
          domains: [
            {
              domain: rootDomains ? "root_domain" : "ip",
              status: "PUBLISHED",
              version_id: ipVersion,
              record_count: 1,
              complete: !rootDomains,
              expected_total: rootDomains ? 200 : 1,
              pages_read: 1,
              error_code: null,
            },
            ...(rootDomains
              ? []
              : [
                  {
                    domain: "port",
                    status: "PUBLISHED",
                    version_id: portVersion,
                    record_count: 0,
                    complete: true,
                    expected_total: 0,
                    pages_read: 1,
                    error_code: null,
                  },
                ]),
          ],
        })
      if (state.lostSubmission) {
        state.lostSubmission = false
        return route.abort("failed")
      }
      return route.fulfill({ status: 202, json: state.tasks.get(key) })
    }
    if (url.pathname.endsWith("/syncs"))
      return route.fulfill({
        json: { data: [...state.tasks.values()], count: state.tasks.size },
      })
    if (url.pathname.endsWith(`/syncs/${taskId}`))
      return route.fulfill({ json: [...state.tasks.values()][0] })
    if (url.pathname.endsWith("/versions")) {
      const selectedVersion =
        url.searchParams.get("domain") === "port"
          ? {
              ...version,
              id: portVersion,
              domain: "port",
              filter: {},
              record_count: 0,
              expected_total: 0,
            }
          : { ...version, status: state.expired ? "EXPIRED" : "PUBLISHED" }
      return route.fulfill({
        json: {
          data: [selectedVersion],
          count: 1,
          latest_complete_version:
            selectedVersion.status === "PUBLISHED" && selectedVersion.complete
              ? selectedVersion
              : null,
        },
      })
    }
    if (url.pathname.endsWith(`/records/${recordId}`))
      return route.fulfill({
        json: {
          record: row,
          version,
          matched_ports: [],
          matched_port_count: 0,
          port_version: url.searchParams.has("port_version_id")
            ? {
                ...version,
                id: portVersion,
                domain: "port",
                filter: {},
                record_count: 0,
                expected_total: 0,
              }
            : null,
        },
      })
    if (url.pathname.endsWith("/records")) {
      const matches =
        !state.expired &&
        (!rootDomains ||
          row.fields.root_domain
            ?.toLowerCase()
            .includes(
              (url.searchParams.get("root_domain") ?? "").toLowerCase(),
            ))
      return route.fulfill({
        json: {
          data: matches ? [row] : [],
          count: matches ? 1 : 0,
          version: {
            ...version,
            status: state.expired ? "EXPIRED" : "PUBLISHED",
          },
          state: state.expired ? "EXPIRED" : "PUBLISHED",
        },
      })
    }
    return route.fulfill({
      status: 404,
      json: { detail: "Unconfigured synthetic route" },
    })
  })
  return state
}

test("ambiguous accepted submission survives refresh and recovers the identical intent", async ({
  page,
}) => {
  const state = await serve(page)
  state.lostSubmission = true
  await page.goto(routePath)
  await page.getByLabel("Page size", { exact: true }).fill("2")
  await page.getByLabel("Maximum pages", { exact: true }).fill("3")
  await page.getByLabel("Maximum records", { exact: true }).fill("6")
  await page.getByLabel("Maximum response bytes", { exact: true }).fill("4096")
  await page.getByLabel("Timeout seconds", { exact: true }).fill("30")
  await page
    .getByLabel("Retention deadline (your local timezone)")
    .fill("2099-01-01T00:00")
  await page.getByRole("checkbox").check()
  await page
    .getByRole("button", {
      name: "Start authorized synchronization",
      exact: true,
    })
    .click()
  await expect(
    page.getByRole("button", { name: "Recover submission using the same key" }),
  ).toBeEnabled()
  await page.reload()
  await expect(
    page.getByRole("button", { name: "Recover submission using the same key" }),
  ).toBeEnabled()
  expect(state.submissions).toHaveLength(1)
  await expect(
    page.getByRole("button", {
      name: "Start authorized synchronization",
      exact: true,
    }),
  ).toHaveCount(0)
  await page
    .getByRole("button", { name: "Recover submission using the same key" })
    .click()
  await expect(
    page.getByRole("heading", { name: "Selected task", exact: true }),
  ).toBeVisible()
  expect(state.submissions).toHaveLength(2)
  expect(state.submissions[1]).toEqual(state.submissions[0])
  expect(state.tasks.size).toBe(1)
  await expect(
    page.getByRole("button", { name: "Recover submission using the same key" }),
  ).toHaveCount(0)
})

test("denial closes fixed detail and does not revive the previous cached record", async ({
  page,
}) => {
  const state = await serve(page)
  state.enabled = false
  state.canManage = false
  await page.goto(
    `${routePath}&external_record=${recordId}&external_record_version=${ipVersion}`,
  )
  const dialog = page.getByRole("dialog")
  await expect(
    dialog.getByText("9007199254740993", { exact: true }),
  ).toBeVisible()
  await expect(
    dialog.getByText("<img src=x onerror=alert(1)>", { exact: true }),
  ).toBeVisible()
  await expect(dialog.getByText("Null", { exact: true })).toBeVisible()
  await expect(dialog.getByText("Empty string", { exact: true })).toBeVisible()
  await expect(dialog.getByText("Empty array", { exact: true })).toBeVisible()
  await expect(
    page.getByRole("button", {
      name: "Start authorized synchronization",
      exact: true,
    }),
  ).toHaveCount(0)
  state.denied = true
  await dialog.getByLabel("Explicit port version").selectOption(portVersion)
  await expect(dialog).toHaveCount(0)
  await expect(page.getByRole("alert")).toContainText("Data unavailable")
  await expect(
    page.getByText("Synthetic private group", { exact: true }),
  ).toHaveCount(0)
  await page.goBack()
  await expect(
    page.getByText("Synthetic private group", { exact: true }),
  ).toHaveCount(0)
  await expect(page.getByRole("dialog")).toHaveCount(0)
})

test("expired pointer never falls back to cached data and cleanup remains usable", async ({
  page,
}) => {
  const state = await serve(page)
  await page.goto(routePath)
  await expect(
    page.getByText("Synthetic private group", { exact: true }),
  ).toBeVisible()
  state.expired = true
  await page
    .getByRole("button", { name: "Read latest local version", exact: true })
    .click()
  await expect(page.getByRole("alert")).toContainText("selected data expired")
  await expect(
    page.getByText("Synthetic private group", { exact: true }),
  ).toHaveCount(0)
  await page
    .getByRole("button", {
      name: "Clean up expired local records",
      exact: true,
    })
    .click()
  await expect(
    page.getByText(
      "Deleted 1 expired new-model records; legacy data unchanged.",
      { exact: true },
    ),
  ).toBeVisible()
  expect(state.purged).toBe(true)
})

test("root details isolate stale IP matching and retain source text and literal local search", async ({
  page,
}) => {
  await serve(page, true)
  const requests: URL[] = []
  page.on("request", (request) => {
    if (request.url().includes("/external-assets/"))
      requests.push(new URL(request.url()))
  })
  await page.goto(
    `${routePath}&external_domain=root_domain&external_record=${recordId}&external_record_version=${ipVersion}&external_port_version=${portVersion}&external_match_page=2`,
  )
  const dialog = page.getByRole("dialog")
  await expect(dialog.getByText("Example.test", { exact: true })).toBeVisible()
  await expect(
    dialog.getByText("<img src=x onerror=alert(1)>", { exact: true }),
  ).toBeVisible()
  await expect(
    dialog.getByText("<script>bad()</script>", { exact: true }),
  ).toBeVisible()
  await expect(
    dialog.getByText("synthetic@example.test", { exact: true }),
  ).toBeVisible()
  await expect(dialog.getByText("Empty string", { exact: true })).toBeVisible()
  await expect(dialog.getByText("Null", { exact: true })).toHaveCount(3)
  await expect(dialog.getByLabel("Explicit port version")).toHaveCount(0)
  await expect(dialog.getByText("Canonical IP", { exact: false })).toHaveCount(
    0,
  )
  await expect(
    dialog.locator("img, script, a[href^='https:'], a[href^='mailto:']"),
  ).toHaveCount(0)
  expect(
    requests.some(
      (url) =>
        url.searchParams.has("port_version_id") ||
        url.searchParams.get("domain") === "port",
    ),
  ).toBe(false)
  await page.keyboard.press("Escape")
  await expect(page.getByLabel("Asset domain", { exact: true })).toHaveValue(
    "root_domain",
  )
  await page.getByLabel("Root domain contains (local text)").fill("%")
  await page
    .getByRole("button", { name: "Filter local records", exact: true })
    .click()
  await expect(
    page.getByText("No records match these local filters or page.", {
      exact: true,
    }),
  ).toBeVisible()
  await page.getByRole("button", { name: "Clear filters", exact: true }).click()
  await expect(
    page.getByRole("cell", { name: "Example.test", exact: true }),
  ).toBeVisible()
  await page.getByLabel("Page size", { exact: true }).fill("20")
  await page.getByLabel("Maximum pages", { exact: true }).fill("1")
  await page.getByLabel("Maximum records", { exact: true }).fill("20")
  await page.getByLabel("Maximum response bytes", { exact: true }).fill("4096")
  await page.getByLabel("Timeout seconds", { exact: true }).fill("30")
  await page
    .getByLabel("Retention deadline (your local timezone)")
    .fill("2099-01-01T00:00")
  await page.getByRole("checkbox").check()
  await page
    .getByRole("button", {
      name: "Start authorized synchronization",
      exact: true,
    })
    .click()
  await expect(
    page.getByRole("heading", { name: "Selected task", exact: true }),
  ).toBeVisible()
  await expect(
    page.getByText("Batch completed — not full", { exact: true }).first(),
  ).toBeVisible()
})
