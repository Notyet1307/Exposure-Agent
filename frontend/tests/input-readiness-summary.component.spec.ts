import { expect, type Page, type Route, test } from "./fixtures"

const projects = [
  {
    name: "North Plant",
    id: "00000000-0000-0000-0000-000000000001",
    tenant_id: "00000000-0000-0000-0000-000000000010",
    created_at: "2026-07-30T10:00:00Z",
    updated_at: "2026-07-30T10:00:00Z",
    archived_at: null,
  },
  {
    name: "South Plant",
    id: "00000000-0000-0000-0000-000000000002",
    tenant_id: "00000000-0000-0000-0000-000000000010",
    created_at: "2026-07-29T10:00:00Z",
    updated_at: "2026-07-29T10:00:00Z",
    archived_at: null,
  },
]
const uploadId = "20000000-0000-0000-0000-000000000001"
const sourceId = "50000000-0000-0000-0000-000000000001"
const ipVersionId = "60000000-0000-0000-0000-000000000001"

const profiles = {
  [projects[0].id]: {
    id: "10000000-0000-0000-0000-000000000001",
    version: 1,
    required_headers: [
      "资产IP",
      "起始端口",
      "结束端口",
      "是否web界面",
      "web界面url",
    ],
    warning_headers: ["服务类型", "资产负责人"],
    optional_headers: ["序号"],
  },
  [projects[1].id]: {
    id: "10000000-0000-0000-0000-000000000002",
    version: 1,
    required_headers: [
      "资产IP",
      "起始端口",
      "结束端口",
      "是否web界面",
      "web界面url",
    ],
    warning_headers: ["服务类型", "资产负责人"],
    optional_headers: ["序号"],
  },
}

const uploads = {
  [projects[0].id]: {
    data: [
      {
        id: uploadId,
        display_filename: "north-assets.xlsx",
        raw_sha256: "a".repeat(64),
        record_count: 2,
        profile_id: profiles[projects[0].id].id,
        profile_version: 1,
        warnings: [],
        created_at: "2026-07-30T12:00:00Z",
      },
    ],
    count: 1,
    current_customer_upload_id: uploadId,
    can_upload: true,
    can_select: true,
  },
  [projects[1].id]: {
    data: [],
    count: 0,
    current_customer_upload_id: null,
    can_upload: true,
    can_select: true,
  },
}

function emptyNetflow() {
  return {
    data: [],
    count: 0,
    current_netflow_dataset_id: null,
    current_netflow_dataset: null,
    can_upload: true,
    can_select: true,
  }
}

function customerSource(overrides: Record<string, unknown> = {}) {
  return {
    source: "CUSTOMER",
    state: "VALID_NONEMPTY",
    read_state: "VALID_NONEMPTY",
    coverage_state: "NOT_APPLICABLE",
    source_records: 2,
    source_addresses: 2,
    source_objects: 2,
    metadata: {},
    ...overrides,
  }
}

function cloudSource(overrides: Record<string, unknown> = {}) {
  return {
    source: "CLOUD",
    state: "VALID_NONEMPTY",
    read_state: "VALID_NONEMPTY",
    coverage_state: "SUFFICIENT",
    source_records: 2,
    source_addresses: 2,
    source_objects: 2,
    metadata: {
      domains: { ip: { retain_until: "2099-01-01T00:00:00Z" } },
    },
    ...overrides,
  }
}

function readiness(state: string, overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "core-comparison-v2",
    project_id: projects[0].id,
    state,
    reason_code: null,
    scope_key: "a".repeat(64),
    scope_confirmation_id: null,
    selection: {
      network_namespace: "north",
      customer: { upload_id: uploadId, revision_id: null },
      cloud: {
        kind: "external_versions",
        source_instance_id: sourceId,
        ip_version_id: ipVersionId,
        port_version_id: null,
      },
      netflow: null,
      history_run_id: null,
    },
    input_sha256: "b".repeat(64),
    expected_current_result_id: null,
    customer: { upload_id: uploadId, revision_id: null },
    customer_filename: "north-assets.xlsx",
    customer_applied_at: "2026-07-30T12:00:00Z",
    clouds: [
      {
        source_instance_id: sourceId,
        source_name: "cloudatlas-north",
        space_id: "42",
        state: "PUBLISHED",
        selection: {
          kind: "external_versions",
          source_instance_id: sourceId,
          ip_version_id: ipVersionId,
          port_version_id: null,
        },
      },
    ],
    scope_choices: [],
    can_generate: true,
    can_write: true,
    can_confirm_scope: true,
    sources: [customerSource(), cloudSource()],
    ...overrides,
  }
}

function summary(projectId: string, overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "input-summary-v1",
    project_id: projectId,
    customer: {
      applied_upload_id: uploadId,
      applied_revision_id: null,
      accepted_upload_count: 1,
      unapplied_upload_count: 0,
    },
    cloud: {
      sources: [
        {
          source_instance_id: sourceId,
          instance_id: "cloudatlas-north",
          space_id: "42",
          enabled: true,
          data_access_enabled: true,
          validation_status: "validated",
        },
      ],
    },
    core_readiness: readiness("READY", { project_id: projectId }),
    netflow: {
      read_state: "READ",
      dataset_count: 0,
      current_dataset_id: null,
      scope_id: null,
      scopes: [],
      current_analysis_id: null,
      latest_attempt_status: null,
      latest_attempt_error_code: null,
    },
    ...overrides,
  }
}

type SummaryHandler = (route: Route, projectId: string) => void | Promise<void>
type ActorHandler = () => string

async function mockDashboard(
  page: Page,
  summaryHandler: SummaryHandler,
  actor: ActorHandler = () => "30000000-0000-0000-0000-000000000001",
) {
  await page.addInitScript(() => {
    if (sessionStorage.getItem("input-summary-auth") === null) {
      localStorage.setItem("access_token", "component-token")
      sessionStorage.setItem("input-summary-auth", "true")
    }
  })
  await page.route("**/api/v1/users/me", (route) =>
    route.fulfill({
      json: {
        email: "operator@example.com",
        full_name: "Test Operator",
        id: actor(),
        is_active: true,
        is_superuser: false,
      },
    }),
  )
  await page.route("**/api/v1/projects/**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const summaryMatch = url.pathname.match(/projects\/([^/]+)\/input-summary$/)
    if (summaryMatch) {
      await summaryHandler(route, summaryMatch[1])
      return
    }
    const profileMatch = url.pathname.match(
      /projects\/([^/]+)\/customer-upload-profile$/,
    )
    if (profileMatch) {
      await route.fulfill({
        json: profiles[profileMatch[1] as keyof typeof profiles],
      })
      return
    }
    const uploadsMatch = url.pathname.match(
      /projects\/([^/]+)\/customer-uploads$/,
    )
    if (uploadsMatch && request.method() === "GET") {
      await route.fulfill({
        json: uploads[uploadsMatch[1] as keyof typeof uploads],
      })
      return
    }
    if (
      url.pathname.endsWith("/cloudatlas-source-instances") &&
      request.method() === "GET"
    ) {
      await route.fulfill({ json: { data: [], count: 0, can_manage: false } })
      return
    }
    const netflowMatch = url.pathname.match(
      /projects\/([^/]+)\/netflow-datasets$/,
    )
    if (netflowMatch && request.method() === "GET") {
      await route.fulfill({ json: emptyNetflow() })
      return
    }
    if (url.pathname === "/api/v1/projects/") {
      await route.fulfill({ json: { data: projects, count: projects.length } })
      return
    }
    await route.fallback()
  })
}

function panel(page: Page) {
  return page.locator("[data-input-readiness]")
}

function verdict(page: Page) {
  return panel(page).locator("p[data-readiness-state]")
}

async function open(page: Page, project = projects[0]) {
  await page.goto(`/?project=${project.id}&view=inputs`)
  await expect(
    page.getByRole("heading", { name: "Data access", exact: true }),
  ).toBeVisible()
}

test("loading, ready facts and GET-only refresh", async ({ page }) => {
  let requests = 0
  const writes: string[] = []
  page.on("request", (request) => {
    if (
      ["POST", "PUT", "PATCH", "DELETE"].includes(request.method()) &&
      request.url().includes("/api/v1/projects/")
    )
      writes.push(`${request.method()} ${request.url()}`)
  })
  await mockDashboard(page, async (route) => {
    requests += 1
    await new Promise((resolve) => setTimeout(resolve, 250))
    await route.fulfill({ json: summary(projects[0].id) })
  })
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await expect(
    page.getByText("Reading input readiness…", { exact: true }),
  ).toBeVisible()
  await expect(
    panel(page).getByText(
      "The applied customer register and published CloudAtlas data are ready.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(verdict(page)).toHaveAttribute("data-readiness-state", "READY")
  await expect(
    panel(page).getByText(`Applied input: ${uploadId}`, { exact: true }),
  ).toBeVisible()
  await expect(
    panel(page).getByText("Records: 2 · Addresses: 2", { exact: true }),
  ).toBeVisible()
  const before = requests
  await page.evaluate(() => {
    window.dispatchEvent(new Event("visibilitychange"))
  })
  await expect.poll(() => requests).toBeGreaterThan(before)
  expect(writes).toEqual([])
})

test("whole failure shows no ready claim and retry recovers", async ({
  page,
}) => {
  let fail = true
  await mockDashboard(page, (route) =>
    fail
      ? route.fulfill({ status: 500 })
      : route.fulfill({ json: summary(projects[0].id) }),
  )
  await open(page)
  await expect(
    panel(page).getByText(
      "Input status could not be read. No ready claim is shown.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(verdict(page)).toHaveCount(0)
  fail = false
  await panel(page).getByRole("button", { name: "Retry", exact: true }).click()
  await expect(verdict(page)).toHaveAttribute("data-readiness-state", "READY")
})

test("denied, inaccessible and expired responses stay distinct", async ({
  page,
}) => {
  let status = 403
  await mockDashboard(page, (route) => route.fulfill({ status }))
  await open(page)
  await expect(
    panel(page).getByText(
      "Input status was denied. Nothing is shown as ready or empty.",
      { exact: true },
    ),
  ).toBeVisible()
  status = 404
  await page.reload()
  await expect(
    panel(page).getByText(
      "This project's input status is unavailable or not accessible.",
      { exact: true },
    ),
  ).toBeVisible()
  status = 410
  await page.reload()
  await expect(
    panel(page).getByText(
      "The fixed input versions have expired. Unknown is not an empty result.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(verdict(page)).toHaveCount(0)
})

test("true empty project never renders ready or a zero material", async ({
  page,
}) => {
  await mockDashboard(page, (route) =>
    route.fulfill({
      json: summary(projects[1].id, {
        customer: {
          applied_upload_id: null,
          applied_revision_id: null,
          accepted_upload_count: 0,
          unapplied_upload_count: 0,
        },
        cloud: { sources: [] },
        core_readiness: readiness("CUSTOMER_NOT_READY", {
          project_id: projects[1].id,
          selection: null,
          customer: null,
          clouds: [],
          sources: [],
          can_generate: false,
        }),
        netflow: {
          read_state: "READ",
          dataset_count: 0,
          current_dataset_id: null,
          scope_id: null,
          scopes: [],
          current_analysis_id: null,
          latest_attempt_status: null,
          latest_attempt_error_code: null,
        },
      }),
    }),
  )
  await open(page, projects[1])
  await expect(
    panel(page).getByText("Apply a customer register version first.", {
      exact: true,
    }),
  ).toBeVisible()
  await expect(verdict(page)).toHaveAttribute(
    "data-readiness-state",
    "CUSTOMER_NOT_READY",
  )
  await expect(
    panel(page).getByText("Applied input: None", { exact: true }),
  ).toBeVisible()
  await expect(
    panel(page).getByText("Accepted uploads: 0", { exact: true }),
  ).toBeVisible()
  await expect(
    panel(page).getByText("No assets-v1 source is configured.", {
      exact: true,
    }),
  ).toBeVisible()
  await expect(
    panel(page).getByText("Accepted datasets: 0", { exact: true }),
  ).toBeVisible()
  await expect(
    panel(page)
      .getByRole("link", {
        name: "Apply or replace the customer input",
        exact: true,
      })
      .first(),
  ).toBeVisible()
})

test("accepted uploads are not applied input", async ({ page }) => {
  await mockDashboard(page, (route) =>
    route.fulfill({
      json: summary(projects[1].id, {
        customer: {
          applied_upload_id: null,
          applied_revision_id: null,
          accepted_upload_count: 2,
          unapplied_upload_count: 2,
        },
        core_readiness: readiness("CUSTOMER_NOT_READY", {
          project_id: projects[1].id,
          selection: null,
          customer: null,
          sources: [],
          can_generate: false,
        }),
      }),
    }),
  )
  await open(page, projects[1])
  await expect(
    panel(page).getByText("Accepted uploads: 2", { exact: true }),
  ).toBeVisible()
  await expect(
    panel(page).getByText("Accepted but not applied: 2", { exact: true }),
  ).toBeVisible()
  await expect(verdict(page)).toHaveAttribute(
    "data-readiness-state",
    "CUSTOMER_NOT_READY",
  )
})

test("a validated connection is not a published readable version", async ({
  page,
}) => {
  await mockDashboard(page, (route) =>
    route.fulfill({
      json: summary(projects[0].id, {
        core_readiness: readiness("CLOUD_NOT_READY", {
          clouds: [
            {
              source_instance_id: sourceId,
              source_name: "cloudatlas-north",
              space_id: "42",
              state: "NOT_PUBLISHED",
              selection: null,
            },
          ],
          selection: null,
          sources: [],
        }),
      }),
    }),
  )
  await open(page)
  await expect(
    panel(page).getByText(/cloudatlas-north \(no published version\)/),
  ).toBeVisible()
  await expect(
    panel(page)
      .getByText("Material: Read status not reached; unknown.", {
        exact: true,
      })
      .first(),
  ).toBeVisible()
  await expect(verdict(page)).toHaveAttribute(
    "data-readiness-state",
    "CLOUD_NOT_READY",
  )
  await expect(
    panel(page).getByRole("link", {
      name: "Manage CloudAtlas sources and versions",
      exact: true,
    }),
  ).toBeVisible()
})

test("scope pending with data is never labelled comparable", async ({
  page,
}) => {
  await mockDashboard(page, (route) =>
    route.fulfill({
      json: summary(projects[0].id, {
        core_readiness: readiness("SCOPE_REQUIRED", {
          selection: null,
          sources: [],
        }),
      }),
    }),
  )
  await open(page)
  await expect(
    panel(page).getByText(
      "Confirm the network namespace and comparable scope for these materials.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(verdict(page)).toHaveAttribute(
    "data-readiness-state",
    "SCOPE_REQUIRED",
  )
  await expect(
    panel(page)
      .getByText("Material: Read status not reached; unknown.", {
        exact: true,
      })
      .last(),
  ).toBeVisible()
})

test("confirmation and coverage stay short of ready even with can_generate", async ({
  page,
}) => {
  let state = "SCOPE_CONFIRMATION_REQUIRED"
  await mockDashboard(page, (route) =>
    route.fulfill({
      json: summary(projects[0].id, {
        core_readiness: readiness(state, { can_generate: true }),
      }),
    }),
  )
  await open(page)
  await expect(verdict(page)).toHaveAttribute(
    "data-readiness-state",
    "SCOPE_CONFIRMATION_REQUIRED",
  )
  await expect(
    panel(page).getByText(
      "These exact input versions need a same-space confirmation.",
      { exact: true },
    ),
  ).toBeVisible()
  state = "INSUFFICIENT_COVERAGE"
  await page.reload()
  await expect(verdict(page)).toHaveAttribute(
    "data-readiness-state",
    "INSUFFICIENT_COVERAGE",
  )
  await expect(
    panel(page).getByText(
      "Coverage is incomplete. Known records can be read, but full-scope difference statistics are unavailable.",
      { exact: true },
    ),
  ).toBeVisible()
})

test("read failed and metadata unavailable are distinct from empty", async ({
  page,
}) => {
  let state = "READ_FAILED"
  await mockDashboard(page, (route) =>
    route.fulfill({
      json: summary(projects[0].id, {
        core_readiness: readiness(state, {
          reason_code: "netflow_artifact_integrity_failed",
          selection: null,
          sources: [],
        }),
      }),
    }),
  )
  await open(page)
  await expect(verdict(page)).toHaveAttribute(
    "data-readiness-state",
    "READ_FAILED",
  )
  await expect(
    panel(page).getByText(
      "The data could not be read. Check its fixed version and retry.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(
    panel(page).getByText(
      /cloudatlas-north \(published candidate \(metadata only\)\)/,
    ),
  ).toBeVisible()
  await expect(panel(page).getByText(/readable published version/)).toHaveCount(
    0,
  )
  await expect(
    panel(page)
      .getByText("Material: Read status not reached; unknown.", {
        exact: true,
      })
      .last(),
  ).toBeVisible()
  state = "METADATA_UNAVAILABLE"
  await page.reload()
  await expect(verdict(page)).toHaveAttribute(
    "data-readiness-state",
    "METADATA_UNAVAILABLE",
  )
  await expect(
    panel(page).getByText(
      "Update status could not be confirmed. This does not change the fixed result.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(
    panel(page).getByText("Records: Unknown · Addresses: Unknown", {
      exact: true,
    }),
  ).toBeVisible()
})

test("unknown nullable counts are not shown as zero", async ({ page }) => {
  await mockDashboard(page, (route) =>
    route.fulfill({
      json: summary(projects[0].id, {
        core_readiness: readiness("READY", {
          sources: [
            customerSource({ source_records: null, source_addresses: null }),
            cloudSource({ source_records: null, source_addresses: null }),
          ],
        }),
      }),
    }),
  )
  await open(page)
  await expect(
    panel(page).getByText("Records: Unknown · Addresses: Unknown", {
      exact: true,
    }),
  ).toBeVisible()
  await expect(
    panel(page).getByText("Records: 0 · Addresses: 0", { exact: true }),
  ).toHaveCount(0)
})

test("embedded denial and expiry withhold a ready claim", async ({ page }) => {
  let state = "ACCESS_DENIED"
  await mockDashboard(page, (route) =>
    route.fulfill({
      json: summary(projects[0].id, {
        core_readiness: readiness(state, { selection: null, sources: [] }),
      }),
    }),
  )
  await open(page)
  await expect(verdict(page)).toHaveAttribute(
    "data-readiness-state",
    "ACCESS_DENIED",
  )
  await expect(
    panel(page).getByText(
      "Data access is denied. The result is not an empty set.",
      { exact: true },
    ),
  ).toBeVisible()
  state = "EXPIRED"
  await page.reload()
  await expect(verdict(page)).toHaveAttribute("data-readiness-state", "EXPIRED")
  await expect(
    panel(page).getByText(
      "The required data has expired. Prepare an authorized published version explicitly.",
      { exact: true },
    ),
  ).toBeVisible()
})

test("optional NetFlow failure does not block core and facts stay separate", async ({
  page,
}) => {
  let failed = true
  await mockDashboard(page, (route) =>
    route.fulfill({
      json: summary(projects[0].id, {
        netflow: failed
          ? {
              read_state: "READ_FAILED",
              dataset_count: null,
              current_dataset_id: null,
              error_status: 403,
              error_code: "correlation_source_access_revoked",
            }
          : {
              read_state: "READ",
              dataset_count: 2,
              current_dataset_id: "21000000-0000-0000-0000-000000000001",
              scope_id: "scope-a",
              scopes: [
                {
                  scope_id: "scope-a",
                  network_namespace: "north",
                  collection_scope: "edge-a",
                  label: "edge-a",
                },
                {
                  scope_id: "scope-b",
                  network_namespace: "north",
                  collection_scope: "edge-b",
                  label: "edge-b",
                },
              ],
              current_analysis_id: "22000000-0000-0000-0000-000000000001",
              latest_attempt_status: "FAILED",
              latest_attempt_error_code: "netflow_no_valid_records",
            },
      }),
    }),
  )
  await open(page)
  await expect(verdict(page)).toHaveAttribute("data-readiness-state", "READY")
  await expect(
    panel(page).getByText(
      "NetFlow state could not be read: correlation_source_access_revoked (HTTP 403)",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(
    panel(page).getByText("Accepted datasets: Unknown", { exact: true }),
  ).toBeVisible()
  failed = false
  await page.reload()
  await expect(verdict(page)).toHaveAttribute("data-readiness-state", "READY")
  await expect(
    panel(page).getByText("Accepted datasets: 2", { exact: true }),
  ).toBeVisible()
  await expect(
    panel(page).getByText("Scopes: edge-a (north); edge-b (north)", {
      exact: true,
    }),
  ).toBeVisible()
  await expect(
    panel(page).getByText(
      "Current readable analysis: 22000000-0000-0000-0000-000000000001",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(
    panel(page).getByText("Latest attempt: FAILED · netflow_no_valid_records", {
      exact: true,
    }),
  ).toBeVisible()
})

test("idle material expiry withholds ready and refreshes by GET", async ({
  page,
}) => {
  // Date stays fixed across navigation while timers run for React Query notifications.
  const fixed = new Date("2026-11-10T00:00:00Z")
  await page.clock.install({ time: fixed })
  await page.clock.setFixedTime(fixed)
  const deadline = new Date(fixed.getTime() + 3000).toISOString()
  let requests = 0
  await mockDashboard(page, (route) => {
    requests += 1
    return route.fulfill({
      json: summary(projects[0].id, {
        core_readiness: readiness("READY", {
          sources: [
            customerSource(),
            cloudSource({
              metadata: { domains: { ip: { retain_until: deadline } } },
            }),
          ],
        }),
      }),
    })
  })
  await open(page)
  await expect(verdict(page)).toHaveAttribute("data-readiness-state", "READY")
  const beforeExpiry = requests
  await page.clock.setFixedTime(fixed.getTime() + 3000)
  await page.clock.fastForward(3001)
  await expect(
    panel(page).getByText(
      "A known material deadline has passed. No ready claim is shown; a fresh GET is required.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(verdict(page)).toHaveCount(0)
  await expect.poll(() => requests).toBeGreaterThan(beforeExpiry)
})

test("expired material stays hidden while a retry GET is pending", async ({
  page,
}) => {
  // Date stays fixed across navigation while timers run for React Query notifications.
  const fixed = new Date("2026-11-10T00:00:00Z")
  await page.clock.install({ time: fixed })
  await page.clock.setFixedTime(fixed)
  const deadline = new Date(fixed.getTime() + 3000).toISOString()
  const freshDeadline = new Date(fixed.getTime() + 3_600_000).toISOString()
  let hold = false
  let signalFirstHeld: () => void = () => {}
  const firstHeld = new Promise<void>((resolve) => {
    signalFirstHeld = resolve
  })
  let releaseHeld: () => void = () => {}
  const heldGate = new Promise<void>((resolve) => {
    releaseHeld = resolve
  })
  const payload = (retainUntil: string) =>
    summary(projects[0].id, {
      core_readiness: readiness("READY", {
        sources: [
          customerSource(),
          cloudSource({
            metadata: { domains: { ip: { retain_until: retainUntil } } },
          }),
        ],
      }),
    })
  await mockDashboard(page, async (route) => {
    if (!hold) {
      await route.fulfill({ json: payload(deadline) })
      return
    }
    signalFirstHeld()
    await heldGate
    await route.fulfill({ json: payload(freshDeadline) }).catch(() => {})
  })
  await open(page)
  await expect(verdict(page)).toHaveAttribute("data-readiness-state", "READY")
  hold = true
  await page.clock.setFixedTime(fixed.getTime() + 3000)
  await page.clock.fastForward(3001)
  await expect(
    panel(page).getByText(
      "A known material deadline has passed. No ready claim is shown; a fresh GET is required.",
      { exact: true },
    ),
  ).toBeVisible({ timeout: 10_000 })
  await firstHeld
  await expect(
    panel(page).getByText("Records: 2 · Addresses: 2", { exact: true }),
  ).toHaveCount(0)
  await expect(
    panel(page).getByText(/read valid non-empty; coverage sufficient/),
  ).toHaveCount(0)
  await expect(
    panel(page).getByText(/published candidate \(metadata only\)/),
  ).toHaveCount(0)
  await panel(page).getByRole("button", { name: "Retry", exact: true }).click()
  await page.waitForTimeout(250)
  await expect(
    panel(page).getByText(
      "A known material deadline has passed. No ready claim is shown; a fresh GET is required.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(
    panel(page).getByText("Records: 2 · Addresses: 2", { exact: true }),
  ).toHaveCount(0)
  await expect(
    panel(page).getByText(/read valid non-empty; coverage sufficient/),
  ).toHaveCount(0)
  releaseHeld()
  await expect(verdict(page)).toHaveAttribute("data-readiness-state", "READY")
  await expect(
    panel(page).getByText("Records: 2 · Addresses: 2", { exact: true }),
  ).toBeVisible()
  await expect(
    panel(page).getByText(/published candidate \(metadata only\)/),
  ).toBeVisible()
  await expect(panel(page).getByText(/readable published version/)).toHaveCount(
    0,
  )
})

test("a late response past its own material deadline is rejected", async ({
  page,
}) => {
  const deadline = new Date(Date.now() + 1200).toISOString()
  await mockDashboard(page, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 2500))
    await route.fulfill({
      json: summary(projects[0].id, {
        core_readiness: readiness("READY", {
          sources: [
            customerSource(),
            cloudSource({
              metadata: { domains: { ip: { retain_until: deadline } } },
            }),
          ],
        }),
      }),
    })
  })
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await expect(
    panel(page).getByText(
      "A known material deadline has passed. No ready claim is shown; a fresh GET is required.",
      { exact: true },
    ),
  ).toBeVisible({ timeout: 10_000 })
  await expect(verdict(page)).toHaveCount(0)
})

test("identity mismatch fails closed", async ({ page }) => {
  await mockDashboard(page, (route) =>
    route.fulfill({
      json: summary(projects[1].id),
    }),
  )
  await open(page)
  await expect(
    panel(page).getByText(
      "The response did not match this project and was discarded.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(verdict(page)).toHaveCount(0)
})

test("a late response from the previous project never renders", async ({
  page,
}) => {
  await mockDashboard(page, async (route, projectId) => {
    if (projectId === projects[0].id) {
      await new Promise((resolve) => setTimeout(resolve, 2500))
      await route.fulfill({
        json: summary(projects[0].id, {
          core_readiness: readiness("MULTIPLE_SCOPES"),
        }),
      })
      return
    }
    await route.fulfill({ json: summary(projectId) })
  })
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await expect(
    page.getByRole("heading", { name: "Data access", exact: true }),
  ).toBeVisible()
  const select = page.getByRole("combobox", { name: "Project" })
  await select.selectOption(projects[1].id)
  await expect(verdict(page)).toHaveAttribute("data-readiness-state", "READY")
  await page.waitForTimeout(3000)
  await expect(
    panel(page).getByText("Choose one comparable source or scope.", {
      exact: true,
    }),
  ).toHaveCount(0)
  await expect(verdict(page)).toHaveAttribute("data-readiness-state", "READY")
})

test("a late response from the previous actor never renders", async ({
  page,
}) => {
  const firstActor = "30000000-0000-0000-0000-000000000001"
  const secondActor = "30000000-0000-0000-0000-000000000002"
  let actor = firstActor
  let releaseFirst: () => void = () => {}
  let firstStarted: () => void = () => {}
  const firstRequestStarted = new Promise<void>((resolve) => {
    firstStarted = resolve
  })
  await mockDashboard(
    page,
    async (route, projectId) => {
      if (actor === firstActor) {
        firstStarted()
        await new Promise<void>((resolve) => {
          releaseFirst = resolve
        })
        await route
          .fulfill({
            json: summary(projectId, {
              core_readiness: readiness("MULTIPLE_SCOPES", {
                project_id: projectId,
              }),
            }),
          })
          .catch(() => {})
        return
      }
      await route.fulfill({ json: summary(projectId) })
    },
    () => actor,
  )
  await open(page)
  await firstRequestStarted
  actor = secondActor
  await page.evaluate(() => {
    window.dispatchEvent(new Event("visibilitychange"))
  })
  await expect(verdict(page)).toHaveAttribute("data-readiness-state", "READY")
  releaseFirst()
  await page.waitForTimeout(500)
  await expect(
    panel(page).getByText("Choose one comparable source or scope.", {
      exact: true,
    }),
  ).toHaveCount(0)
  await expect(verdict(page)).toHaveAttribute("data-readiness-state", "READY")
})

test("nullable customer identities compare only against a readiness selection", async ({
  page,
}) => {
  const revisionId = "40000000-0000-0000-0000-000000000001"
  let payload = summary(projects[0].id, {
    customer: {
      applied_upload_id: null,
      applied_revision_id: null,
      accepted_upload_count: 1,
      unapplied_upload_count: 1,
    },
  })
  await mockDashboard(page, (route) => route.fulfill({ json: payload }))
  await open(page)
  await expect(panel(page).getByRole("alert")).toContainText(
    "The applied input pointer and readiness selection disagree.",
  )
  await expect(verdict(page)).toHaveCount(0)
  await expect(
    panel(page).getByText("Applied input: None", { exact: true }),
  ).toBeVisible()
  await expect(
    panel(page).getByText(
      "The applied customer register and published CloudAtlas data are ready.",
      { exact: true },
    ),
  ).toHaveCount(0)

  payload = summary(projects[0].id)
  await page.reload()
  await expect(verdict(page)).toHaveAttribute("data-readiness-state", "READY")
  await expect(panel(page).getByRole("alert")).toHaveCount(0)

  payload = summary(projects[0].id, {
    core_readiness: readiness("READY", {
      customer: { upload_id: uploadId, revision_id: revisionId },
    }),
  })
  await page.reload()
  await expect(panel(page).getByRole("alert")).toContainText(
    "The applied input pointer and readiness selection disagree.",
  )
  await expect(verdict(page)).toHaveCount(0)

  payload = summary(projects[0].id, {
    customer: {
      applied_upload_id: uploadId,
      applied_revision_id: revisionId,
      accepted_upload_count: 1,
      unapplied_upload_count: 0,
    },
  })
  await page.reload()
  await expect(panel(page).getByRole("alert")).toContainText(
    "The applied input pointer and readiness selection disagree.",
  )
  await expect(verdict(page)).toHaveCount(0)

  payload = summary(projects[0].id, {
    core_readiness: readiness("CUSTOMER_NOT_READY", {
      project_id: projects[0].id,
      selection: null,
      customer: null,
      sources: [],
    }),
  })
  await page.reload()
  await expect(verdict(page)).toHaveAttribute(
    "data-readiness-state",
    "CUSTOMER_NOT_READY",
  )
  await expect(panel(page).getByRole("alert")).toHaveCount(0)

  payload = summary(projects[0].id, {
    customer: {
      applied_upload_id: null,
      applied_revision_id: null,
      accepted_upload_count: 0,
      unapplied_upload_count: 0,
    },
    core_readiness: readiness("CUSTOMER_NOT_READY", {
      project_id: projects[0].id,
      selection: null,
      customer: null,
      sources: [],
    }),
  })
  await page.reload()
  await expect(verdict(page)).toHaveAttribute(
    "data-readiness-state",
    "CUSTOMER_NOT_READY",
  )
  await expect(panel(page).getByRole("alert")).toHaveCount(0)
})
