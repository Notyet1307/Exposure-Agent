import { expect, type Page, test } from "./fixtures"

const project = "00000000-0000-4000-8000-000000000286"
const analysis = "10000000-0000-4000-8000-000000000286"
const dataset = "20000000-0000-4000-8000-000000000286"
const context = "30000000-0000-4000-8000-000000000286"
const scope = "a".repeat(64)
const otherProject = "00000000-0000-4000-8000-000000000287"
const otherAnalysis = "10000000-0000-4000-8000-000000000287"
const latestAnalysis = "10000000-0000-4000-8000-000000000288"
const otherDataset = "20000000-0000-4000-8000-000000000287"
const latestDataset = "20000000-0000-4000-8000-000000000288"
const otherContext = "30000000-0000-4000-8000-000000000287"
const latestContext = "30000000-0000-4000-8000-000000000288"
const notice = "A newer processing result is available."
const root = `/api/v1/projects/${project}`
const identity = {
  project_id: project,
  analysis_id: analysis,
  dataset_id: dataset,
  context_revision_id: context,
  network_namespace: "synthetic",
  test_fixture: true,
  provenance: {},
}
const batch = {
  ...identity,
  status: "SUCCEEDED",
  can_read_result: true,
  completed_at: "2026-01-01T00:01:00Z",
  created_at: "2026-01-01T00:00:00Z",
  context: {},
  quality: {},
  result: {},
}
const observation = (i: number) => ({
  object_key: `object-${i}`,
  canonical_ip: `192.0.2.${i}`,
  family: 4,
  protocol_number: 6,
  source_port: 22932,
  source_record_count: 30,
  retained_count: 27,
  omitted_count: 3,
  original: {},
})
const timing = {
  batch_created_at: batch.created_at,
  batch_completed_at: batch.completed_at,
  original_time_basis: "unknown",
  business_time_qualification: "UNKNOWN",
}

async function setup(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "synthetic-token")
    localStorage.setItem("exposure:language", "en")
  })
  await page.route("**/api/v1/**", (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path === "/api/v1/users/me")
      return route.fulfill({
        json: {
          id: "synthetic-user",
          email: "synthetic@example.net",
          is_active: true,
          is_superuser: false,
        },
      })
    if (path === "/api/v1/projects/")
      return route.fulfill({
        json: {
          data: [{ id: project, name: "Synthetic project", status: "active" }],
          count: 1,
        },
      })
    if (path === `${root}/netflow-analyses/${analysis}/access`)
      return route.fulfill({
        json: { ...identity, can_read_result: true, status: "SUCCEEDED" },
      })
    if (path === `${root}/netflow-analyses/${analysis}`)
      return route.fulfill({ json: batch })
    if (path === `${root}/netflow-results/current`)
      return route.fulfill({
        json: {
          project_id: project,
          collection_scope: null,
          scopes: [],
          current: null,
          latest_attempt: null,
        },
      })
    if (path.endsWith("/observations")) {
      const skip = Number(url.searchParams.get("skip") ?? 0)
      const filtered = url.searchParams.has("ip")
      return route.fulfill({
        json: {
          ...identity,
          ...timing,
          data: Array.from({ length: filtered || skip ? 1 : 25 }, (_, i) =>
            observation(filtered ? 26 : skip + i + 1),
          ),
          count: filtered ? 1 : 26,
          skip,
          limit: 25,
          raw_record_count: 780,
          total_source_records: 780,
          total_observations: 26,
          total_addresses: 26,
        },
      })
    }
    if (path.includes("/observations/"))
      return route.fulfill({
        json: { ...identity, ...timing, ...observation(26), context: {} },
      })
    if (path.endsWith("/evidence")) {
      const skip = Number(url.searchParams.get("skip") ?? 0)
      return route.fulfill({
        json: {
          ...identity,
          data: [
            {
              reference: `row:${skip + 1}`,
              side: "source",
              dataset_id: dataset,
              normalized_sha256: "synthetic-hash",
            },
          ],
          count: 27,
          retained_count: 27,
          omitted_count: 3,
          skip,
          limit: 10,
        },
      })
    }
    return route.fulfill({ json: { data: [], count: 0 } })
  })
}

const attempt = (analysisId: string, overrides: Record<string, unknown>) => ({
  ...batch,
  analysis_id: analysisId,
  ...overrides,
})

const currentResponse = ({
  current,
  latest,
  projectId = project,
  scopeId = scope,
}: {
  current: Record<string, unknown> | null
  latest: Record<string, unknown> | null
  projectId?: string
  scopeId?: string
}) => ({
  project_id: projectId,
  scope_id: scopeId,
  scopes: [
    {
      scope_id: scopeId,
      network_namespace: "synthetic",
      collection_scope: "branch-edge-a",
      label: "branch-edge-a",
      evidence: null,
    },
  ],
  current,
  latest_attempt: latest,
})

const coverageLimitations = [
  "INPUT_RECORDS_NOT_SESSIONS",
  "REACHABILITY_NOT_VERIFIED",
  "OBSERVATION_COVERAGE_NOT_COMPLETE",
  "REVERSE_TUPLES_DO_NOT_PROVE_HANDSHAKE",
  "COUNTERS_NOT_RESCALED",
  "SAMPLING_UNKNOWN",
  "ORIGINAL_MAPPED_FORM_UNRECOVERABLE",
  "SYNTHETIC_TEST_ONLY",
  "SOURCE_POSITION_DECLARATION_NOT_OWNERSHIP_OR_AUTHORIZATION",
  "SOURCE_COLUMN_NOT_CONNECTION_INITIATOR",
  "REVERSE_MATCHING_NOT_EVALUATED",
  "EXTERNAL_PEER_BY_CUSTOMER_DECLARATION",
]
const resultCounts = (overrides: Record<string, number> = {}) => ({
  address_side_crossover_count: 0,
  candidates: 0,
  duplicate_records: 0,
  endpoint_count: 0,
  excluded: 0,
  invalid_records: 0,
  mapped_addresses_normalized: 0,
  observations: 0,
  peer_addresses: 0,
  peer_hypotheses: 0,
  raw_records: 0,
  records_without_managed_endpoint: 0,
  review: 0,
  self_loop_records: 0,
  service_hypotheses: 0,
  valid_records: 0,
  ...overrides,
})
const results = {
  empty: {
    counts: resultCounts(),
    coverage_limitations: coverageLimitations,
    input_state: "empty",
    review_task_count: 1,
    component_run_id: otherAnalysis,
    artifacts: [],
  },
  nonempty: {
    counts: resultCounts({
      address_side_crossover_count: 2,
      endpoint_count: 4,
      observations: 5,
      peer_addresses: 6,
      peer_hypotheses: 8,
      raw_records: 8,
      review: 5,
      self_loop_records: 1,
      service_hypotheses: 5,
      valid_records: 8,
    }),
    coverage_limitations: coverageLimitations,
    input_state: "data_without_candidates",
    review_task_count: 5,
    component_run_id: otherAnalysis,
    artifacts: [
      {
        name: "result/observations.jsonl",
        artifact_id: otherAnalysis,
        byte_size: 1,
        sha256: "b".repeat(64),
      },
    ],
  },
}

const readableCurrent = (result: Record<string, unknown>) =>
  attempt(otherAnalysis, {
    dataset_id: otherDataset,
    context_revision_id: otherContext,
    result,
    created_at: "2026-01-02T00:00:00Z",
    completed_at: "2026-01-02T00:01:00Z",
  })

const failedLatest = attempt(latestAnalysis, {
  dataset_id: latestDataset,
  context_revision_id: latestContext,
  status: "FAILED",
  can_read_result: false,
  result: null,
  created_at: "2026-01-03T00:00:00Z",
  completed_at: null,
})

const fixedUrl = `/projects/${project}/netflow-results?analysis=${analysis}&collectionScope=${scope}`

async function mockCurrent(page: Page, response: Record<string, unknown>) {
  await page.route(`**${root}/netflow-results/current*`, (route) =>
    route.fulfill({ json: response }),
  )
}

async function mountWithNotice(page: Page) {
  let response = currentResponse({
    current: readableCurrent(results.nonempty),
    latest: failedLatest,
  })
  await page.route(`**${root}/netflow-results/current*`, (route) =>
    route.fulfill({ json: response }),
  )
  await page.goto(fixedUrl)
  await expect(page.getByText(notice, { exact: true })).toBeVisible()
  return async (next: Record<string, unknown>) => {
    response = next
    const refetched = page.waitForResponse((candidate) =>
      candidate.url().includes("/netflow-results/current"),
    )
    await page.evaluate(() =>
      document.dispatchEvent(new Event("visibilitychange")),
    )
    await refetched
  }
}

test("independent processed observations keep batch, full pages, counts and evidence", async ({
  page,
}) => {
  await setup(page)
  const requests: string[] = []
  page.on("request", (request) => {
    if (request.url().includes("/api/"))
      requests.push(`${request.method()} ${request.url()}`)
  })
  await page.goto(`/projects/${project}/netflow-results?analysis=${analysis}`)
  await expect(
    page.getByRole("heading", { name: "NetFlow observations", exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole("combobox", { name: "Published run", exact: true }),
  ).toHaveCount(0)
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
    "780",
  )
  await expect(
    page.getByLabel("Observation objects", { exact: true }),
  ).toHaveText("26")
  await expect(
    page.getByLabel("Distinct source IPs", { exact: true }),
  ).toHaveText("26")
  await page
    .getByRole("navigation", { name: "Observations pagination" })
    .getByRole("button", { name: "Next", exact: true })
    .click()
  await page.getByRole("button", { name: "192.0.2.26", exact: true }).click()
  await expect(
    page.getByRole("heading", { name: "Observation details", exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole("region", { name: "Observation details", exact: true }),
  ).toBeFocused()
  await expect(
    page.getByText("Source-side observed port: 22932", { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByText("Observation time: unknown", { exact: true }),
  ).toBeVisible()
  await page
    .getByRole("button", { name: "View input evidence", exact: true })
    .click()
  await expect(page.getByText("row:1", { exact: true })).toBeVisible()
  await expect(
    page.getByRole("region", { name: "Input evidence", exact: true }),
  ).toBeFocused()
  await page
    .getByRole("navigation", { name: "Evidence pagination" })
    .getByRole("button", { name: "Next", exact: true })
    .click()
  await expect(page.getByText("row:11", { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByText("row:11", { exact: true })).toBeVisible()
  expect(new URL(page.url()).searchParams.get("analysis")).toBe(analysis)
  expect(requests.every((request) => request.startsWith("GET "))).toBe(true)
  expect(
    requests.some((request) =>
      /source-correlations|governance-runs|\/runs\//.test(request),
    ),
  ).toBe(false)
})

test("filters and separate peer evidence remain pinned through refresh and back", async ({
  page,
}) => {
  await setup(page)
  const reads: URL[] = []
  page.on("request", (request) => reads.push(new URL(request.url())))
  await page.route(
    `**${root}/netflow-analyses/${analysis}/peers?*`,
    (route) => {
      const skip = Number(
        new URL(route.request().url()).searchParams.get("skip") ?? 0,
      )
      return route.fulfill({
        json: {
          ...identity,
          data: [
            {
              peer_key: `peer-${skip}`,
              canonical_ip: `198.51.100.${skip ? 26 : 1}`,
              protocol_number: 17,
              peer_port: 53,
              source_record_count: 4,
            },
          ],
          count: 26,
          skip,
          limit: 25,
          total_peers: 26,
          total_peer_records: 104,
        },
      })
    },
  )
  await page.goto(`/projects/${project}/netflow-results?analysis=${analysis}`)
  await page.getByLabel("Exact IP", { exact: true }).fill("::ffff:192.0.2.26")
  await page.getByLabel("Protocol number", { exact: true }).fill("6")
  await page.getByLabel("Source-side port", { exact: true }).fill("22932")
  await page.getByRole("button", { name: "Filter", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "192.0.2.26", exact: true }),
  ).toBeVisible()
  expect(
    reads.some(
      (url) =>
        url.pathname.endsWith("/observations") &&
        url.searchParams.get("ip") === "::ffff:192.0.2.26" &&
        url.searchParams.get("protocol") === "6" &&
        url.searchParams.get("source_port") === "22932",
    ),
  ).toBe(true)
  await page
    .getByRole("button", { name: "External peers", exact: true })
    .click()
  await expect(
    page.getByRole("button", { name: "198.51.100.1", exact: true }),
  ).toBeVisible()
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveCount(0)
  await page
    .getByRole("navigation", { name: "Peers pagination" })
    .getByRole("button", { name: "Next", exact: true })
    .click()
  await page.getByRole("button", { name: "198.51.100.26", exact: true }).click()
  await expect(page.getByText("row:1", { exact: true })).toBeVisible()
  expect(
    reads.some(
      (url) =>
        url.pathname.endsWith("/evidence") &&
        url.searchParams.get("peer_key") === "peer-25" &&
        !url.searchParams.has("object_key"),
    ),
  ).toBe(true)
  await page.reload()
  await expect(
    page.getByRole("button", { name: "198.51.100.26", exact: true }),
  ).toBeVisible()
  await page.goBack()
  expect(new URL(page.url()).searchParams.get("analysis")).toBe(analysis)
})

for (const status of ["PENDING", "FAILED", "UNKNOWN"]) {
  test(`explicit ${status} batch never becomes a successful empty result`, async ({
    page,
  }) => {
    await setup(page)
    let contents = 0
    page.on("request", (request) => {
      if (/\/observations|\/peers|\/evidence/.test(request.url())) contents++
    })
    await page.route(`**${root}/netflow-analyses/${analysis}`, (route) =>
      route.fulfill({ json: { ...batch, status, can_read_result: false } }),
    )
    await page.goto(`/projects/${project}/netflow-results?analysis=${analysis}`)
    await expect(page.getByRole("alert")).toContainText(
      "This batch has no readable published result",
    )
    expect(contents).toBe(0)
    await expect(page.getByLabel("Original rows", { exact: true })).toHaveCount(
      0,
    )
  })
}

for (const status of [403, 404, 410]) {
  test(`a ${status} content response clears cached observations and open evidence`, async ({
    page,
  }) => {
    await setup(page)
    await page.goto(
      `/projects/${project}/netflow-results?analysis=${analysis}&object=object-26&evidence=true`,
    )
    await expect(page.getByText("row:1", { exact: true })).toBeVisible()
    await page.route(
      `**${root}/netflow-analyses/${analysis}/observations?*`,
      (route) =>
        route.fulfill({
          status,
          json: {
            detail: {
              code:
                status === 410
                  ? "correlation_source_expired"
                  : "netflow_input_not_found",
            },
          },
        }),
    )
    await page.evaluate(() =>
      document.dispatchEvent(new Event("visibilitychange")),
    )
    await expect(page.getByRole("alert")).toContainText(
      "This fixed batch cannot be read",
    )
    await expect(page.getByText("row:1", { exact: true })).toHaveCount(0)
    await expect(page.getByLabel("Original rows", { exact: true })).toHaveCount(
      0,
    )
    await expect(
      page.getByRole("heading", { name: "Observation details", exact: true }),
    ).toHaveCount(0)
  })
}

test("invalid or conflicting explicit identity never falls back to another batch", async ({
  page,
}) => {
  await setup(page)
  const contents: string[] = []
  page.on("request", (request) => {
    if (/\/observations|\/peers|\/evidence|\/analyses/.test(request.url()))
      contents.push(request.url())
  })
  await page.goto(`/projects/${project}/netflow-results?analysis=invalid`)
  await expect(page.getByRole("alert")).toContainText(
    "explicit batch identity is invalid",
  )
  await page.goto(
    `/projects/${project}/netflow-results?analysis=${analysis}&dataset=${context}`,
  )
  // The access check may clear batch metadata before the detailed mismatch text renders.
  await expect(
    page.getByRole("heading", { name: "This fixed batch cannot be read" }),
  ).toBeVisible()
  expect(contents).toEqual([])
})

test("empty ordinary entry offers explicit history without selecting a batch", async ({
  page,
}) => {
  await setup(page)
  let batchReads = 0
  await page.route(`**${root}/netflow-datasets?*`, (route) =>
    route.fulfill({
      json: {
        data: [{ id: dataset, display_filename: "capture.csv" }],
        count: 1,
      },
    }),
  )
  await page.route(
    `**${root}/netflow-datasets/${dataset}/analyses?*`,
    (route) =>
      route.fulfill({
        json: {
          data: [
            {
              ...batch,
              status: "FAILED",
              can_read_result: false,
              analysis_id: context,
            },
            batch,
          ],
          count: 2,
        },
      }),
  )
  page.on("request", (request) => {
    if (request.url().includes(`/netflow-analyses/${analysis}`)) batchReads++
  })
  await page.goto(`/projects/${project}/netflow-results`)
  await page
    .getByRole("button", { name: "Browse processing history", exact: true })
    .click()
  await page.getByRole("button", { name: "capture.csv", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Open batch", exact: true }),
  ).toHaveCount(2)
  expect(batchReads).toBe(0)
  await expect(
    page.getByRole("button", { name: "Open batch", exact: true }).first(),
  ).toBeDisabled()
  await page
    .getByRole("button", { name: "Open batch", exact: true })
    .last()
    .click()
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
    "780",
  )
  expect(new URL(page.url()).searchParams.get("analysis")).toBe(analysis)
})

test("ordinary entry fixes a resolved current result before reading observations", async ({
  page,
}) => {
  await setup(page)
  await page.route(`**${root}/netflow-results/current`, (route) =>
    route.fulfill({
      json: {
        project_id: project,
        scope_id: "a".repeat(64),
        scopes: [
          {
            scope_id: "a".repeat(64),
            network_namespace: "synthetic",
            collection_scope: "branch-edge-a",
            label: "branch-edge-a",
            evidence: "Synthetic fixed collection scope.",
          },
        ],
        current: batch,
        latest_attempt: batch,
      },
    }),
  )
  await page.goto(`/projects/${project}/netflow-results`)
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
    "780",
  )
  expect(new URL(page.url()).searchParams.get("analysis")).toBe(analysis)
})

test("project switch stays in processed data and rejects the old late response", async ({
  page,
}) => {
  await setup(page)
  await page.route(
    (url) => url.pathname === "/api/v1/projects/",
    (route) =>
      route.fulfill({
        json: {
          data: [
            { id: project, name: "First project" },
            { id: context, name: "Second project" },
          ],
          count: 2,
        },
      }),
  )
  let release: () => void = () => {}
  let requested: () => void = () => {}
  const waiting = new Promise<void>((resolve) => {
    requested = resolve
  })
  const released = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route(
    `**${root}/netflow-analyses/${analysis}/observations?*`,
    async (route) => {
      requested()
      await released
      await route.fulfill({
        json: {
          ...identity,
          ...timing,
          data: [observation(26)],
          count: 1,
          skip: 0,
          limit: 25,
          raw_record_count: 780,
          total_source_records: 780,
          total_observations: 26,
          total_addresses: 26,
        },
      })
    },
  )
  await page.goto(`/projects/${project}/netflow-results?analysis=${analysis}`)
  await waiting
  await page
    .getByRole("combobox", { name: "Project", exact: true })
    .selectOption(context)
  await expect(page).toHaveURL(
    new RegExp(`/projects/${context}/netflow-results`),
  )
  release()
  await expect(
    page.getByRole("heading", {
      name: "Choose a collection scope or processing history",
      exact: true,
    }),
  ).toBeVisible()
  expect(new URL(page.url()).searchParams.has("analysis")).toBe(false)
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveCount(0)
  await expect(
    page.getByRole("button", { name: "192.0.2.26", exact: true }),
  ).toHaveCount(0)
})

test("bulk pages use cursors, keep immutable content idle, and clear on access revocation", async ({
  page,
}, testInfo) => {
  await setup(page)
  await page.clock.install()
  let observationsRead = 0
  let accessRead = 0
  let revoked = false
  let usedCursor: string | null = null
  const bulkIdentity = {
    ...identity,
    provenance: { backend: "netflow-bulk-v1", policy: "bulk-export-row-v1" },
  }
  await page.route(`**${root}/netflow-analyses/${analysis}`, (route) =>
    route.fulfill({
      json: {
        ...batch,
        ...bulkIdentity,
        pipeline_complete: true,
        result: {
          counts: {
            raw: 52,
            invalid: 0,
            filtered: 0,
            retained: 52,
            unique: 26,
            duplicate: 26,
          },
        },
      },
    }),
  )
  await page.route(`**${root}/netflow-analyses/${analysis}/access`, (route) => {
    accessRead++
    return route.fulfill(
      revoked
        ? { status: 409, json: { detail: { code: "netflow_context_revoked" } } }
        : { json: { ...identity, status: "SUCCEEDED", can_read_result: true } },
    )
  })
  await page.route(
    `**${root}/netflow-analyses/${analysis}/observations?*`,
    (route) => {
      observationsRead++
      const params = new URL(route.request().url()).searchParams
      usedCursor = params.get("cursor")
      const next = usedCursor === "fixed-cursor-2"
      return route.fulfill({
        json: {
          ...bulkIdentity,
          ...timing,
          data: Array.from({ length: next ? 1 : 25 }, (_, i) => ({
            ...observation(next ? 26 : i + 1),
            source_record_count: 1,
            retained_count: 1,
            omitted_count: 0,
          })),
          count: 26,
          skip: 0,
          limit: 25,
          next_cursor: next ? null : "fixed-cursor-2",
          raw_record_count: 52,
          total_observations: 26,
          total_source_records: 26,
          total_addresses: 26,
        },
      })
    },
  )
  await page.goto(
    `/projects/${project}/netflow-results?analysis=${analysis}&dataset=${dataset}`,
  )
  await expect(
    page.getByRole("region", { name: "Bulk record counts" }),
  ).toBeVisible()
  await expect(page.getByText("192.0.2.1", { exact: true })).toBeVisible()
  await page.clock.runFor(5001)
  await expect.poll(() => accessRead).toBeGreaterThanOrEqual(2)
  await page.clock.runFor(6001)
  await expect.poll(() => accessRead).toBeGreaterThanOrEqual(3)
  expect(observationsRead).toBe(1)
  await page
    .getByRole("navigation", { name: "Observations pagination" })
    .getByRole("button", { name: "Next", exact: true })
    .click()
  await expect(page.getByText("192.0.2.26", { exact: true })).toBeVisible()
  expect(usedCursor).toBe("fixed-cursor-2")
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.screenshot({
    path: testInfo.outputPath("bulk-desktop.png"),
    fullPage: true,
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({
    path: testInfo.outputPath("bulk-mobile.png"),
    fullPage: true,
  })
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true)
  revoked = true
  await page.clock.runFor(5001)
  await expect(
    page.getByRole("heading", { name: "This fixed batch cannot be read" }),
  ).toBeVisible()
  await expect(page.getByText("192.0.2.26", { exact: true })).toHaveCount(0)
})

for (const status of ["PENDING", "RUNNING", "FAILED", "UNKNOWN"]) {
  test(`a ${status} latest attempt never announces a new readable result`, async ({
    page,
  }) => {
    await setup(page)
    const replaceCurrent = await mountWithNotice(page)
    await replaceCurrent(
      currentResponse({
        current: batch,
        latest: attempt(latestAnalysis, {
          dataset_id: latestDataset,
          context_revision_id: latestContext,
          status,
          can_read_result: false,
          result: null,
          created_at: "2026-01-03T00:00:00Z",
          completed_at: null,
        }),
      }),
    )
    await expect(page.getByText(notice, { exact: true })).toHaveCount(0)
    await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
      "780",
    )
    expect(new URL(page.url()).searchParams.get("analysis")).toBe(analysis)
    expect(new URL(page.url()).searchParams.get("collectionScope")).toBe(scope)
  })
}

test("a successful but unreadable latest attempt never announces a new result", async ({
  page,
}) => {
  await setup(page)
  const replaceCurrent = await mountWithNotice(page)
  await replaceCurrent(
    currentResponse({
      current: batch,
      latest: attempt(latestAnalysis, {
        dataset_id: latestDataset,
        context_revision_id: latestContext,
        status: "SUCCEEDED",
        can_read_result: false,
        result: null,
        created_at: "2026-01-03T00:00:00Z",
        completed_at: "2026-01-03T00:01:00Z",
      }),
    }),
  )
  await expect(page.getByText(notice, { exact: true })).toHaveCount(0)
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
    "780",
  )
  expect(new URL(page.url()).searchParams.get("analysis")).toBe(analysis)
})

for (const [state, result] of Object.entries(results)) {
  test(`a successful ${state} current result is announced while the latest attempt failed`, async ({
    page,
  }, testInfo) => {
    await setup(page)
    const writes: string[] = []
    page.on("request", (request) => {
      if (request.url().includes("/api/") && request.method() !== "GET")
        writes.push(`${request.method()} ${request.url()}`)
    })
    await mockCurrent(
      page,
      currentResponse({
        current: readableCurrent(result),
        latest: failedLatest,
      }),
    )
    await page.goto(fixedUrl)
    await expect(page.getByText(notice, { exact: true })).toBeVisible()
    await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
      "780",
    )
    expect(new URL(page.url()).searchParams.get("analysis")).toBe(analysis)
    expect(new URL(page.url()).searchParams.get("collectionScope")).toBe(scope)
    await page.screenshot({
      path: testInfo.outputPath(
        `netflow-result-notice-${state}-failed-latest.png`,
      ),
      fullPage: true,
    })
    expect(writes).toEqual([])
  })

  test(`a successful ${state} current result is announced when the latest attempt is that result`, async ({
    page,
  }, testInfo) => {
    await setup(page)
    const writes: string[] = []
    page.on("request", (request) => {
      if (request.url().includes("/api/") && request.method() !== "GET")
        writes.push(`${request.method()} ${request.url()}`)
    })
    const current = readableCurrent(result)
    await mockCurrent(
      page,
      currentResponse({
        current,
        latest: { ...current, result: null },
      }),
    )
    await page.goto(fixedUrl)
    await expect(page.getByText(notice, { exact: true })).toBeVisible()
    await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
      "780",
    )
    expect(new URL(page.url()).searchParams.get("analysis")).toBe(analysis)
    expect(new URL(page.url()).searchParams.get("collectionScope")).toBe(scope)
    await page.screenshot({
      path: testInfo.outputPath(
        `netflow-result-notice-${state}-successful-latest.png`,
      ),
      fullPage: true,
    })
    expect(writes).toEqual([])
  })
}

test("no successful readable current result keeps the fixed result without a notice", async ({
  page,
}) => {
  await setup(page)
  const replaceCurrent = await mountWithNotice(page)
  await replaceCurrent(currentResponse({ current: null, latest: failedLatest }))
  await expect(page.getByText(notice, { exact: true })).toHaveCount(0)
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
    "780",
  )
  expect(new URL(page.url()).searchParams.get("analysis")).toBe(analysis)
})

test("a failed current lookup keeps the fixed result without a notice", async ({
  page,
}) => {
  await setup(page)
  await page.route(`**${root}/netflow-results/current*`, (route) =>
    route.fulfill({
      status: 500,
      json: { detail: { code: "synthetic_current_failure" } },
    }),
  )
  const failed = page.waitForResponse(
    (candidate) =>
      candidate.url().includes("/netflow-results/current") &&
      candidate.status() === 500,
  )
  await page.goto(fixedUrl)
  await failed
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
    "780",
  )
  await expect(page.getByText(notice, { exact: true })).toHaveCount(0)
  expect(new URL(page.url()).searchParams.get("analysis")).toBe(analysis)
})

test("current data for another project never announces a new result", async ({
  page,
}) => {
  await setup(page)
  const replaceCurrent = await mountWithNotice(page)
  await replaceCurrent(
    currentResponse({
      projectId: otherProject,
      current: readableCurrent(results.nonempty),
      latest: failedLatest,
    }),
  )
  await expect(page.getByText(notice, { exact: true })).toHaveCount(0)
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
    "780",
  )
})

test("current data for another scope never announces a new result", async ({
  page,
}) => {
  await setup(page)
  const replaceCurrent = await mountWithNotice(page)
  await replaceCurrent(
    currentResponse({
      scopeId: "b".repeat(64),
      current: readableCurrent(results.nonempty),
      latest: failedLatest,
    }),
  )
  await expect(page.getByText(notice, { exact: true })).toHaveCount(0)
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
    "780",
  )
})

const accessPath = `**${root}/netflow-analyses/${analysis}/access`
const batchPath = `**${root}/netflow-analyses/${analysis}`
const successAccess = {
  ...identity,
  can_read_result: true,
  status: "SUCCEEDED",
}

test("a transient access read failure keeps verified results and recovers", async ({
  page,
}) => {
  await setup(page)
  await page.clock.install()
  await page.goto(`/projects/${project}/netflow-results?analysis=${analysis}`)
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
    "780",
  )
  await page.route(accessPath, (route) =>
    route.fulfill({
      status: 500,
      json: { detail: { code: "synthetic_access_unavailable" } },
    }),
  )
  const failed = page.waitForResponse(
    (candidate) =>
      candidate.url().includes(`/netflow-analyses/${analysis}/access`) &&
      candidate.status() === 500,
  )
  await page.evaluate(() =>
    document.dispatchEvent(new Event("visibilitychange")),
  )
  await failed
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
    "780",
  )
  await expect(
    page.getByText(
      "The latest access check failed; the last verified access result is shown. Revocation may not be reflected until a read succeeds.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(
    page.getByRole("heading", { name: "This fixed batch cannot be read" }),
  ).toHaveCount(0)
  await page.route(accessPath, (route) =>
    route.fulfill({ json: successAccess }),
  )
  await page.evaluate(() =>
    document.dispatchEvent(new Event("visibilitychange")),
  )
  await expect(
    page.getByText("The latest access check failed", { exact: false }),
  ).toHaveCount(0)
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
    "780",
  )
})

test("a transient batch read failure keeps results and is not a task failure", async ({
  page,
}) => {
  await setup(page)
  await page.clock.install()
  await page.goto(`/projects/${project}/netflow-results?analysis=${analysis}`)
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
    "780",
  )
  await page.route(batchPath, (route) =>
    route.fulfill({
      status: 503,
      json: { detail: { code: "synthetic_batch_unavailable" } },
    }),
  )
  const failed = page.waitForResponse(
    (candidate) =>
      new URL(candidate.url()).pathname ===
        `${root}/netflow-analyses/${analysis}` && candidate.status() === 503,
  )
  await page.evaluate(() =>
    document.dispatchEvent(new Event("visibilitychange")),
  )
  await failed
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
    "780",
  )
  await expect(
    page.getByText(
      "The latest batch read failed; the last verified batch status is shown. Results are preserved.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(
    page.getByText("Failed; inspect the error before retrying", {
      exact: true,
    }),
  ).toHaveCount(0)
  await expect(
    page.getByRole("heading", { name: "This fixed batch cannot be read" }),
  ).toHaveCount(0)
  await page.route(batchPath, (route) => route.fulfill({ json: batch }))
  await page.evaluate(() =>
    document.dispatchEvent(new Event("visibilitychange")),
  )
  await expect(
    page.getByText("The latest batch read failed", { exact: false }),
  ).toHaveCount(0)
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
    "780",
  )
})

test("an initial transient batch failure is unavailable and retryable", async ({
  page,
}) => {
  await setup(page)
  await page.route(batchPath, (route) =>
    route.fulfill({
      status: 503,
      json: { detail: { code: "synthetic_batch_unavailable" } },
    }),
  )
  await page.goto(`/projects/${project}/netflow-results?analysis=${analysis}`)
  await expect(
    page.getByRole("heading", {
      name: "This fixed batch cannot be read yet",
      exact: true,
    }),
  ).toBeVisible()
  await expect(
    page.getByRole("button", {
      name: "Retry reading this fixed batch",
      exact: true,
    }),
  ).toBeVisible()
  await expect(
    page.getByRole("heading", {
      name: "This fixed batch cannot be read",
      exact: true,
    }),
  ).toHaveCount(0)
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveCount(0)
  await page.route(batchPath, (route) => route.fulfill({ json: batch }))
  await page
    .getByRole("button", {
      name: "Retry reading this fixed batch",
      exact: true,
    })
    .click()
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
    "780",
  )
})

test("an access refusal still clears verified results", async ({ page }) => {
  await setup(page)
  await page.clock.install()
  await page.goto(`/projects/${project}/netflow-results?analysis=${analysis}`)
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
    "780",
  )
  await page.route(accessPath, (route) =>
    route.fulfill({
      status: 403,
      json: { detail: { code: "netflow_view_forbidden" } },
    }),
  )
  const failed = page.waitForResponse(
    (candidate) =>
      candidate.url().includes(`/netflow-analyses/${analysis}/access`) &&
      candidate.status() === 403,
  )
  await page.evaluate(() =>
    document.dispatchEvent(new Event("visibilitychange")),
  )
  await failed
  await expect(
    page.getByRole("heading", { name: "This fixed batch cannot be read" }),
  ).toBeVisible()
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveCount(0)
})

test("a refusal on one fixed scope does not block the next fixed scope", async ({
  page,
}) => {
  await setup(page)
  const otherIdentity = {
    ...identity,
    analysis_id: otherAnalysis,
    dataset_id: otherDataset,
    context_revision_id: otherContext,
  }
  const otherBatch = { ...batch, ...otherIdentity }
  await page.route(accessPath, (route) =>
    route.fulfill({
      status: 403,
      json: { detail: { code: "netflow_view_forbidden" } },
    }),
  )
  await page.route(`**${root}/netflow-analyses/${otherAnalysis}`, (route) =>
    route.fulfill({ json: otherBatch }),
  )
  await page.route(
    `**${root}/netflow-analyses/${otherAnalysis}/access`,
    (route) =>
      route.fulfill({
        json: { ...otherIdentity, can_read_result: true, status: "SUCCEEDED" },
      }),
  )
  await page.route(
    `**${root}/netflow-analyses/${otherAnalysis}/observations?*`,
    (route) =>
      route.fulfill({
        json: {
          ...otherIdentity,
          ...timing,
          data: [observation(1)],
          count: 1,
          skip: 0,
          limit: 25,
          raw_record_count: 30,
          total_source_records: 30,
          total_observations: 1,
          total_addresses: 1,
        },
      }),
  )
  await page.goto(`/projects/${project}/netflow-results?analysis=${analysis}`)
  await expect(
    page.getByRole("heading", {
      name: "This fixed batch cannot be read",
      exact: true,
    }),
  ).toBeVisible()
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveCount(0)
  await page.goto(
    `/projects/${project}/netflow-results?analysis=${otherAnalysis}`,
  )
  await expect(
    page.getByRole("heading", { name: "NetFlow observations", exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "192.0.2.1", exact: true }),
  ).toBeVisible()
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
    "30",
  )
  await expect(
    page.getByRole("heading", {
      name: "This fixed batch cannot be read",
      exact: true,
    }),
  ).toHaveCount(0)
})

test("an access identity conflict clears verified results", async ({
  page,
}) => {
  await setup(page)
  await page.clock.install()
  await page.goto(`/projects/${project}/netflow-results?analysis=${analysis}`)
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
    "780",
  )
  await page.route(accessPath, (route) =>
    route.fulfill({
      json: {
        ...successAccess,
        analysis_id: otherAnalysis,
      },
    }),
  )
  await page.evaluate(() =>
    document.dispatchEvent(new Event("visibilitychange")),
  )
  await expect(
    page.getByRole("heading", { name: "This fixed batch cannot be read" }),
  ).toBeVisible()
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveCount(0)
})

test("audit explicit progress revocation clears previously readable result", async ({
  page,
}) => {
  await setup(page)
  await page.route(batchPath, (route) =>
    route.fulfill({
      json: {
        ...batch,
        pipeline_complete: true,
        provenance: { backend: "netflow-bulk-v1" },
      },
    }),
  )
  let release: () => void = () => {}
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route(
    `**${root}/netflow-bulk/analyses/${analysis}/progress`,
    async (route) => {
      await held
      return route.fulfill({
        status: 409,
        json: { detail: { code: "netflow_context_revoked" } },
      })
    },
  )
  await page.clock.install()
  await page.goto(`/projects/${project}/netflow-results?analysis=${analysis}`)
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
    "780",
  )
  await page.route(accessPath, (route) =>
    route.fulfill({ status: 503, json: { detail: "temporary" } }),
  )
  release()
  await expect(
    page.getByRole("heading", {
      name: "This fixed batch cannot be read",
      exact: true,
    }),
  ).toBeVisible()
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveCount(0)
  await page.clock.runFor(5001)
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveCount(0)
})

test("a transient progress failure keeps read results and is not a denial", async ({
  page,
}) => {
  await setup(page)
  await page.route(batchPath, (route) =>
    route.fulfill({
      json: {
        ...batch,
        pipeline_complete: true,
        provenance: { backend: "netflow-bulk-v1" },
      },
    }),
  )
  let reads = 0
  await page.route(
    `**${root}/netflow-bulk/analyses/${analysis}/progress`,
    (route) => {
      reads += 1
      if (reads === 1)
        return route.fulfill({
          json: {
            ...identity,
            provenance: { backend: "netflow-bulk-v1" },
            status: "RUNNING",
            phase: "NORMALIZING",
            cancel_requested: false,
            heartbeat_at: null,
            lease_until: null,
            files_completed: 0,
            files_total: 4,
            rows_normalized: 0,
            metrics: {},
          },
        })
      return route.fulfill({ status: 503, json: { detail: "temporary" } })
    },
  )
  await page.clock.install()
  await page.goto(`/projects/${project}/netflow-results?analysis=${analysis}`)
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
    "780",
  )
  await expect(page.getByText("Phase: Normalizing input files")).toBeVisible()
  await page.clock.runFor(5001)
  await page.clock.runFor(5001)
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
    "780",
  )
  await expect(
    page.getByText(
      "The last verified progress is shown; the latest read failed.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(
    page.getByRole("heading", { name: "This fixed batch cannot be read" }),
  ).toHaveCount(0)
})
