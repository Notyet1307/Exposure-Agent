import { expect, type Page, test } from "./fixtures"

const project = "00000000-0000-4000-8000-000000000001"
const source = "11111111-1111-4111-8111-111111111111"
const ipVersion = "22222222-2222-4222-8222-222222222222"
const portVersion = "33333333-3333-4333-8333-333333333333"
const recordId = "44444444-4444-4444-8444-444444444444"
const taskId = "55555555-5555-4555-8555-555555555555"
const routePath = `/projects/${project}/cloudatlas-ledger?asset_view=synced&external_source=${source}`
const stamp = "2026-09-01T00:00:00Z"
const retention = "2099-01-01T00:00:00Z"

// Synthetic HTTP responses exercise the real generated service and real route.
// This is not an OctoBus or CloudAtlas integration test.
async function serve(
  page: Page,
  profile: "assets-v1" | "root-domains-v1" | "dns-v1" = "assets-v1",
) {
  const rootDomains = profile === "root-domains-v1"
  const dnsRecords = profile === "dns-v1"
  const singleDomain = rootDomains || dnsRecords
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
    domain: dnsRecords ? "dns" : rootDomains ? "root_domain" : "ip",
    space_id: "7",
    status: "PUBLISHED",
    record_count: 1,
    complete: !singleDomain,
    expected_total: singleDomain ? 200 : 1,
    pages_read: 1,
    stop_reason: singleDomain ? "batch_limit" : "source_complete",
    filter: dnsRecords ? { flat: "1", status: "valid" } : { status: "valid" },
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
    ip: singleDomain ? null : "2001:db8::7",
    canonical_ip: singleDomain ? null : "2001:db8::7",
    fields: dnsRecords
      ? {
          id: "9007199254740993",
          domain: "Example.test",
          subdomain: "A%_\\B.Example.test",
          rdtype: "CNAME",
          record: `<script>text-only</script> https://example.test/never-fetch ${"x".repeat(512)}`,
          status: "source-declared",
          bu: {
            id: "9007199254740993123456792",
            name: "<img src=x onerror=alert(1)>Synthetic DNS group",
          },
          tags: [
            { pk: "9007199254740993123456789", name: "Synthetic DNS tag" },
          ],
          created_at: "",
          updated_at: "2026-09-27 01:02:03",
          lastseen_at: "",
        }
      : rootDomains
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
              capability_profile: profile,
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
          status: singleDomain ? "PARTIAL_SUCCEEDED" : "SUCCEEDED",
          created_at: stamp,
          started_at: stamp,
          completed_at: stamp,
          retain_until: retention,
          error_code: null,
          agent_run_id: "synthetic-run",
          session_id: "synthetic-session",
          domains: [
            {
              domain: dnsRecords ? "dns" : rootDomains ? "root_domain" : "ip",
              status: "PUBLISHED",
              version_id: ipVersion,
              record_count: 1,
              complete: !singleDomain,
              expected_total: singleDomain ? 200 : 1,
              pages_read: 1,
              error_code: null,
            },
            ...(singleDomain
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
        (dnsRecords
          ? row.fields.subdomain
              ?.toLowerCase()
              .includes((url.searchParams.get("subdomain") ?? "").toLowerCase())
          : !rootDomains ||
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
  return Object.assign(state, { version, row })
}

test("ambiguous accepted submission survives refresh and recovers the identical intent", async ({
  page,
}) => {
  const state = await serve(page)
  state.lostSubmission = true
  await page.goto(routePath)
  await page.getByRole("button", { name: "Update data", exact: true }).click()
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
  await page
    .getByRole("button", { name: "Inspect original submission", exact: true })
    .click()
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
  await dialog.getByText("Technical trace", { exact: true }).click()
  await expect(
    dialog.getByText("9007199254740993", { exact: true }),
  ).toBeVisible()
  await expect(
    dialog.getByText("<img src=x onerror=alert(1)>", { exact: true }),
  ).toBeVisible()
  await expect(dialog.getByText("Null", { exact: true })).toBeVisible()
  await expect(dialog.getByText("Empty string", { exact: true })).toBeVisible()
  await expect(
    dialog.getByText("Empty array", { exact: true }).first(),
  ).toBeVisible()
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
    .getByRole("button", { name: "More scopes / versions", exact: true })
    .click()
  await page
    .getByRole("button", { name: "Read latest local version", exact: true })
    .click()
  await expect(page.getByRole("alert")).toContainText("selected data expired")
  await expect(
    page.getByText("Synthetic private group", { exact: true }),
  ).toHaveCount(0)
  await page.getByRole("button", { name: "Update data", exact: true }).click()
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
  await serve(page, "root-domains-v1")
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
  await expect(
    page.getByRole("heading", { name: "Local asset records", exact: true }),
  ).toBeFocused()
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
  await page.getByRole("button", { name: "Update data", exact: true }).click()
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

test("DNS flat records keep literal search, escaped detail, keyboard focus and revoked cache isolated", async ({
  page,
}) => {
  const state = await serve(page, "dns-v1")
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(
    `${routePath}&external_domain=dns&external_ip=192.0.2.1&external_root_domain=stale&external_port_version=${portVersion}&external_match_page=2`,
  )
  await expect(page.getByLabel("Asset domain", { exact: true })).toHaveValue(
    "dns",
  )
  await page.getByLabel("Subdomain contains (local text)").fill("a%_\\b")
  await page
    .getByRole("button", { name: "Filter local records", exact: true })
    .click()
  const open = page.getByRole("link", { name: /Details for A%_/ })
  await open.focus()
  await page.keyboard.press("Enter")
  const dialog = page.getByRole("dialog")
  await dialog.getByText("Technical trace", { exact: true }).click()
  await expect(
    dialog.getByText("9007199254740993123456789", { exact: true }),
  ).toBeVisible()
  await expect(
    dialog.getByText("9007199254740993123456792", { exact: true }),
  ).toBeVisible()
  await expect(
    dialog.getByText("<img src=x onerror=alert(1)>Synthetic DNS group", {
      exact: true,
    }),
  ).toBeVisible()
  await expect(dialog.getByText("CNAME", { exact: true })).toBeVisible()
  await expect(
    dialog.getByText("<script>text-only</script>", { exact: false }),
  ).toBeVisible()
  await expect(dialog.getByText("Canonical IP", { exact: false })).toHaveCount(
    0,
  )
  await expect(dialog.getByLabel("Explicit port version")).toHaveCount(0)
  await expect(
    dialog.locator("img, script, a[href^='https:'], a[href^='mailto:']"),
  ).toHaveCount(0)
  await page.keyboard.press("Escape")
  await expect(open).toBeFocused()
  await page.getByLabel("Subdomain contains (local text)").fill("never-fetch")
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
    page.getByRole("cell", { name: "A%_\\B.Example.test", exact: true }),
  ).toBeVisible()
  state.denied = true
  await page
    .getByRole("button", { name: "More scopes / versions", exact: true })
    .click()
  await expect(page.getByRole("alert")).toBeVisible()
  await expect(
    page.getByRole("cell", { name: "A%_\\B.Example.test", exact: true }),
  ).toHaveCount(0)
})

test("ambiguous asset links fail closed before either reader mounts", async ({
  page,
}) => {
  await serve(page)
  const reads: string[] = []
  page.on("request", (request) => {
    if (
      /\/api\/v1\/projects\/[^/]+\/(external-assets|cloudatlas-ledger|cloudatlas-source-instances)(\/|$)/.test(
        new URL(request.url()).pathname,
      )
    )
      reads.push(request.url())
  })
  for (const path of ["cloudatlas-ledger", "external-assets"]) {
    for (const query of [
      `external_source=${source}&cloud_page=0`,
      `asset_view=history&external_version=${ipVersion}`,
      "asset_view=synced&cloud_revision=0",
      "asset_view=invalid",
    ]) {
      await page.goto(`/projects/${project}/${path}?${query}`)
      await expect(page.getByRole("alert")).toBeVisible()
      expect(reads).toEqual([])
      await expect(page.getByRole("dialog")).toHaveCount(0)
    }
  }
  await page.getByRole("link", { name: "Synced assets", exact: true }).click()
  await expect(
    page.getByText("Synthetic private group", { exact: true }),
  ).toBeVisible()
})

test("a late source creation cannot replace the new project's context", async ({
  page,
}) => {
  await serve(page)
  const nextProject = "00000000-0000-4000-8000-000000000002"
  const createdSource = "11111111-1111-4111-8111-111111111112"
  const submitted = Promise.withResolvers<void>()
  const released = Promise.withResolvers<void>()
  await page.route(
    (url) => url.pathname === "/api/v1/projects/",
    (route) =>
      route.fulfill({
        json: {
          data: [
            { id: project, name: "Original project", archived_at: null },
            { id: nextProject, name: "New project", archived_at: null },
          ],
          count: 2,
        },
      }),
  )
  await page.route(
    `**/api/v1/projects/${nextProject}/external-assets/sources`,
    (route) =>
      route.fulfill({ json: { data: [], count: 0, can_manage: true } }),
  )
  await page.route(
    `**/api/v1/projects/${project}/external-assets/sources`,
    async (route) => {
      if (route.request().method() !== "POST") return route.fallback()
      submitted.resolve()
      await released.promise
      await route.fulfill({
        json: { id: createdSource, capability_profile: "assets-v1" },
      })
    },
  )
  await page.goto(routePath)
  await page
    .getByRole("button", { name: "Sync management", exact: true })
    .click()
  await page.getByText("Set up a new source", { exact: true }).click()
  await page
    .getByLabel("Instance ID", { exact: true })
    .fill("synthetic-new-source")
  await page.getByLabel("Capset ID", { exact: true }).fill("synthetic-unused")
  await page
    .getByLabel("Space ID (decimal string, e.g. 7)", { exact: true })
    .fill("7")
  await page
    .getByRole("button", { name: "Create disabled source", exact: true })
    .click()
  await submitted.promise
  await page.keyboard.press("Escape")
  await page
    .getByRole("combobox", { name: "Project", exact: true })
    .selectOption(nextProject)
  await expect(page).toHaveURL(
    new RegExp(`/projects/${nextProject}/cloudatlas-ledger(?:\\?|$)`),
  )
  const response = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      r.url().endsWith("/external-assets/sources"),
  )
  released.resolve()
  await (await response).finished()
  expect(new URL(page.url()).pathname).toBe(
    `/projects/${nextProject}/cloudatlas-ledger`,
  )
  expect(new URL(page.url()).searchParams.has("external_source")).toBe(false)
  await expect(page.getByRole("alert")).toHaveCount(0)
})

test("bare entry pages local metadata, skips revoked sources, pins a readable partial version and never substitutes after failure", async ({
  page,
}) => {
  const state = await serve(page)
  state.enabled = false
  state.version.complete = false
  const revokedSource = "11111111-1111-4111-8111-111111111112"
  const expiredId = "77777777-7777-4777-8777-777777777777"
  const localSource = {
    id: source,
    instance_id: "synthetic-assets",
    capset_id: "synthetic-capset",
    space_id: "7",
    capability_profile: "assets-v1",
    enabled: false,
    data_access_enabled: true,
    validation_status: "validated",
    validated_fingerprint: "a".repeat(64),
    created_at: stamp,
    updated_at: stamp,
  }
  const metadataReads: {
    source: string
    domain: string | null
    skip: string | null
  }[] = []
  const recordReads: string[] = []
  let metadataFailure = false
  let writes = 0
  page.on("request", (request) => {
    const url = new URL(request.url())
    if (!url.pathname.includes("/external-assets/")) return
    if (request.method() !== "GET") writes++
    if (url.pathname.endsWith("/records"))
      recordReads.push(url.searchParams.get("version_id") ?? "")
  })
  await page.route("**/external-assets/sources", (route) =>
    route.fulfill({
      json: {
        data: [
          {
            ...localSource,
            id: revokedSource,
            enabled: true,
            data_access_enabled: false,
            created_at: "2026-09-02T00:00:00Z",
          },
          localSource,
        ],
        count: 2,
        can_manage: true,
      },
    }),
  )
  await page.route("**/external-assets/sources/*/versions?*", (route) => {
    const url = new URL(route.request().url())
    const selectedSource = url.pathname.split("/").at(-2)!
    metadataReads.push({
      source: selectedSource,
      domain: url.searchParams.get("domain"),
      skip: url.searchParams.get("skip"),
    })
    if (metadataFailure || selectedSource === revokedSource)
      return route.fulfill({
        status: metadataFailure ? 503 : 403,
        json: { detail: "Metadata unavailable" },
      })
    const skip = Number(url.searchParams.get("skip") ?? 0)
    return route.fulfill({
      json: {
        data:
          url.searchParams.get("domain") !== "ip"
            ? []
            : skip === 0
              ? Array.from({ length: 25 }, (_, index) => ({
                  ...state.version,
                  id: `00000000-0000-4000-8000-${String(index + 100).padStart(12, "0")}`,
                  status: "EXPIRED",
                  retain_until: "2000-01-01T00:00:00Z",
                }))
              : [state.version],
        count: url.searchParams.get("domain") === "ip" ? 26 : 0,
        latest_complete_version: null,
      },
    })
  })
  await page.route("**/external-assets/sources/*/records?*", (route) => {
    if (
      new URL(route.request().url()).searchParams.get("version_id") !==
      expiredId
    )
      return route.fallback()
    return route.fulfill({
      json: {
        data: [],
        count: 0,
        state: "EXPIRED",
        version: {
          ...state.version,
          id: expiredId,
          status: "EXPIRED",
          retain_until: "2000-01-01T00:00:00Z",
        },
      },
    })
  })
  await page.goto(`/projects/${project}/cloudatlas-ledger`)
  await expect(
    page.getByText("Synthetic private group", { exact: true }),
  ).toBeVisible()
  const selected = new URL(page.url()).searchParams
  expect(selected.get("external_source")).toBe(source)
  expect(selected.get("external_domain")).toBe("ip")
  expect(selected.get("external_version")).toBe(ipVersion)
  expect(metadataReads).toEqual([
    { source, domain: "ip", skip: "0" },
    { source, domain: "ip", skip: "25" },
  ])
  expect(recordReads).toEqual([ipVersion])

  await page.goto(`${routePath}&external_version=${expiredId}`)
  await expect(page.getByRole("alert")).toContainText("selected data expired")
  await expect(
    page.getByText("Synthetic private group", { exact: true }),
  ).toHaveCount(0)
  expect(new URL(page.url()).searchParams.get("external_version")).toBe(
    expiredId,
  )
  expect(recordReads).toEqual([ipVersion, expiredId])
  expect(metadataReads).toHaveLength(2)

  metadataFailure = true
  await page.goto(`/projects/${project}/cloudatlas-ledger`)
  await expect(page.getByRole("alert")).toContainText(
    "Version metadata could not be read",
  )
  expect(new URL(page.url()).searchParams.has("external_source")).toBe(false)
  expect(recordReads).toEqual([ipVersion, expiredId])
  expect(metadataReads).toEqual([
    { source, domain: "ip", skip: "0" },
    { source, domain: "ip", skip: "25" },
    { source, domain: "ip", skip: "0" },
  ])
  expect(writes).toBe(0)
})
