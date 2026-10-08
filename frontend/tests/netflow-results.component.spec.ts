import { expect, type Page, test } from "./fixtures"

const project = "00000000-0000-4000-8000-000000000286"
const analysis = "10000000-0000-4000-8000-000000000286"
const dataset = "20000000-0000-4000-8000-000000000286"
const context = "30000000-0000-4000-8000-000000000286"
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
  await expect(page.getByRole("alert")).toContainText(
    "explicit batch identity is invalid",
  )
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
  await page.getByRole("button", { name: "Browse processing history", exact: true }).click()
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
