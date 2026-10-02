import { expect, type Page, test } from "./fixtures"

const project = "00000000-0000-4000-8000-000000000274"
const revision = "10000000-0000-4000-8000-000000000274"
const analysis = "20000000-0000-4000-8000-000000000274"
const root = `/api/v1/projects/${project}`
const summary = {
  project_id: project,
  correlation_revision_id: revision,
  network_namespace: "synthetic",
  selection: { netflow: { analysis_id: analysis } },
  pins: {
    NETFLOW: {
      dataset_id: "30000000-0000-4000-8000-000000000274",
      context_revision_id: "40000000-0000-4000-8000-000000000274",
    },
  },

  sources: [],
  total_addresses: 26,
  positive_intersections: { NETFLOW: 26 },
  limitations: [],
}
const address = (ip: string) => ({
  address_key: `addr:${ip}`,
  canonical_ip: ip,
  positive_sources: ["NETFLOW"],
  source_record_count: 1,
  task_refs: ["synthetic-task"],
  unmatched_netflow: true,
})
const dataset = (id: string, name = id) => ({
  id,
  display_filename: name,
  raw_record_count: 1,
  activity_valid_record_count: 1,
  isolated_record_count: 0,
})

async function setup(page: Page) {
  await page.addInitScript(() =>
    localStorage.setItem("access_token", "synthetic-component-token"),
  )
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === "/api/v1/users/me") {
      await route.fulfill({
        json: {
          id: "synthetic-user",
          email: "synthetic@example.com",
          is_active: true,
          is_superuser: false,
        },
      })
    } else if (path === "/api/v1/projects/") {
      await route.fulfill({
        json: {
          data: [{ id: project, name: "Synthetic project", status: "active" }],
          count: 1,
        },
      })
    } else {
      await route.fulfill({ json: { data: [], count: 0, can_manage: false } })
    }
  })
  await page.route(`**${root}/source-correlations/${revision}`, (route) =>
    route.fulfill({ json: summary }),
  )
}
test("task selection never becomes an address selection", async ({ page }) => {
  await setup(page)
  await page.goto(
    `/projects/${project}/netflow-correlation?revision=${revision}&namespace=synthetic&tab=tasks&taskId=task-274`,
  )
  await page.getByRole("button", { name: "Addresses", exact: true }).click()
  await expect(page).toHaveURL(/tab=addresses/)
  await expect(page).not.toHaveURL(/taskId=task-274/)
  await expect(page).not.toHaveURL(/addressKey=task-274/)
})
test("address IP filters remain in the fixed request", async ({ page }) => {
  await setup(page)
  let requestedIp: string | null = null
  await page.route(
    `**${root}/source-correlations/${revision}/addresses?*`,
    (route) => {
      requestedIp = new URL(route.request().url()).searchParams.get("ip")
      return route.fulfill({
        json: {
          data: [address("192.0.2.1")],
          count: 1,
          total_addresses: 1,
          skip: 0,
          limit: 25,
        },
      })
    },
  )
  await page.goto(
    `/projects/${project}/netflow-correlation?revision=${revision}&namespace=synthetic&tab=addresses&addressIp=192.0.2.1`,
  )
  await expect(
    page.getByRole("button", { name: "192.0.2.1", exact: true }),
  ).toBeVisible()
  expect(requestedIp).toBe("192.0.2.1")
})

test("explicit mismatched namespace never exposes the pinned result", async ({
  page,
}) => {
  await setup(page)
  await page.goto(
    `/projects/${project}/netflow-correlation?revision=${revision}&namespace=wrong&tab=addresses`,
  )
  await expect(page.getByRole("alert")).toContainText("no latest fallback")
  await expect(page.getByRole("region", { name: "Address table" })).toHaveCount(
    0,
  )
  await expect(page).toHaveURL(/namespace=wrong/)
})

for (const [name, query] of [
  ["customer upload", "customerUpload=50000000-0000-4000-8000-000000000274"],
  [
    "customer revision",
    "customerRevision=50000000-0000-4000-8000-000000000275",
  ],
  ["history run", "historyRun=50000000-0000-4000-8000-000000000276"],
  [
    "legacy snapshot",
    "cloudMode=legacy&cloudSnapshot=50000000-0000-4000-8000-000000000277&cloudLedgerRevision=1&cloudScopeRevision=1",
  ],
  [
    "external source",
    "cloudMode=external&cloudSource=50000000-0000-4000-8000-000000000278&cloudIpVersion=50000000-0000-4000-8000-000000000279",
  ],
] as const) {
  test(`explicit conflicting ${name} never replaces the fixed revision`, async ({
    page,
  }) => {
    await setup(page)
    await page.goto(
      `/projects/${project}/netflow-correlation?revision=${revision}&namespace=synthetic&${query}`,
    )
    await expect(page.getByRole("alert")).toContainText("no latest fallback")
    await expect(page.getByText("Addresses", { exact: true })).toHaveCount(0)
  })
}

test("explicit empty or malformed fixed identity stays rejected in the URL", async ({
  page,
}) => {
  await setup(page)
  await page.goto(
    `/projects/${project}/netflow-correlation?revision=${revision}&dataset=not-a-uuid`,
  )
  await expect(page.getByRole("alert")).toContainText(
    "explicit fixed identity is invalid",
  )
  await expect(page).toHaveURL(/dataset=not-a-uuid/)
  await expect(page.getByText("Addresses", { exact: true })).toHaveCount(0)
})

test("orphan customer revision and false original marker never post", async ({
  page,
}) => {
  await setup(page)
  let posts = 0
  await page.route(`**${root}/source-correlations`, async (route) => {
    if (route.request().method() === "POST") posts += 1
    await route.fulfill({ json: {} })
  })
  await page.goto(
    `/projects/${project}/netflow-correlation?customerRevision=50000000-0000-4000-8000-000000000275&customerOriginal=false`,
  )
  await expect(page.getByRole("alert")).toContainText(
    "explicit fixed identity is invalid",
  )
  expect(posts).toBe(0)
})

test("a selector pages to item 101 and restores it by exact ID", async ({
  page,
}) => {
  await setup(page)
  const ids = Array.from(
    { length: 101 },
    (_, index) =>
      `30000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
  )
  const requests: URL[] = []
  await page.route(`**${root}/netflow-datasets?*`, async (route) => {
    const url = new URL(route.request().url())
    requests.push(url)
    const exact = url.searchParams.get("dataset_id")
    const skip = Number(url.searchParams.get("skip") ?? 0)
    const rows = exact
      ? [dataset(exact, "Historic 101")]
      : ids.slice(skip, skip + 25).map((id) => dataset(id))
    await route.fulfill({
      json: { data: rows, count: 101, current_netflow_dataset_id: null },
    })
  })
  await page.goto(`/projects/${project}/netflow-correlation`)
  for (let index = 0; index < 4; index++)
    await page.getByRole("button", { name: "Datasets next page" }).click()
  await page
    .getByRole("combobox", { name: "Dataset", exact: true })
    .selectOption(ids[100])
  await expect(page).toHaveURL(new RegExp(`dataset=${ids[100]}`))
  await page.reload()
  await expect
    .poll(() =>
      requests.some((url) => url.searchParams.get("dataset_id") === ids[100]),
    )
    .toBe(true)
})

test("every metadata selector uses a bounded fifth page", async ({ page }) => {
  await setup(page)
  const datasetId = "30000000-0000-4000-8000-000000000274"
  const sourceId = "60000000-0000-4000-8000-000000000274"
  const skips = new Map<string, number[]>()
  const pageOf = (
    route: Parameters<typeof page.route>[1] extends (route: infer T) => unknown
      ? T
      : never,
  ) => {
    const url = new URL(route.request().url())
    const key = url.pathname
    skips.set(key, [
      ...(skips.get(key) ?? []),
      Number(url.searchParams.get("skip") ?? 0),
    ])
    return route.fulfill({
      json: { data: [], count: 101, current_netflow_dataset_id: null },
    })
  }
  await page.route(`**${root}/netflow-datasets?*`, pageOf)
  await page.route(
    `**${root}/netflow-datasets/${datasetId}/processing-contexts?*`,
    pageOf,
  )
  await page.route(`**${root}/netflow-datasets/${datasetId}/analyses?*`, pageOf)
  await page.route(`**${root}/customer-uploads?*`, pageOf)
  await page.route(
    `**${root}/external-assets/sources/${sourceId}/versions?*`,
    pageOf,
  )
  await page.route(`**${root}/cloudatlas-ledger/snapshots?*`, async (route) => {
    const url = new URL(route.request().url())
    const key = url.pathname
    skips.set(key, [
      ...(skips.get(key) ?? []),
      Number(url.searchParams.get("skip") ?? 0),
    ])
    await route.fulfill({
      json: Array.from({ length: 25 }, (_, index) => ({ id: `${index}` })),
    })
  })
  await page.route(`**${root}/cloudatlas-source-instances`, (route) =>
    route.fulfill({
      json: { data: [{ id: sourceId, source_type: "cloudatlas" }] },
    }),
  )
  await page.route(`**${root}/external-assets/sources`, (route) =>
    route.fulfill({
      json: {
        data: [{ id: sourceId, capability_profile: "assets-v1" }],
        can_manage: false,
      },
    }),
  )
  await page.goto(
    `/projects/${project}/netflow-correlation?dataset=${datasetId}&cloudSource=${sourceId}`,
  )
  for (const label of [
    "Datasets",
    "Contexts",
    "Analyses",
    "Customer versions",
    "Legacy snapshots",
    "External versions",
  ]) {
    for (let index = 0; index < 4; index++)
      await page.getByRole("button", { name: `${label} next page` }).click()
  }
  await expect
    .poll(() => [...skips.values()].every((values) => values.includes(100)))
    .toBe(true)
})

test("explicit revision restores its pinned input identity", async ({
  page,
}) => {
  await setup(page)
  await page.goto(
    `/projects/${project}/netflow-correlation?revision=${revision}&namespace=synthetic`,
  )
  await expect(page).toHaveURL(
    new RegExp(
      `dataset=30000000-0000-4000-8000-000000000274.*context=40000000-0000-4000-8000-000000000274.*analysis=${analysis}`,
    ),
  )
})

test("an expired directory does not deny an independently readable pinned revision", async ({
  page,
}) => {
  await setup(page)
  await page.route(`**${root}/source-correlations?*`, (route) =>
    route.fulfill({
      status: 410,
      json: { detail: { code: "correlation_source_expired" } },
    }),
  )
  await page.route(
    `**${root}/source-correlations/${revision}/addresses?*`,
    (route) =>
      route.fulfill({
        json: {
          data: [address("192.0.2.1")],
          count: 1,
          total_addresses: 1,
          skip: 0,
          limit: 25,
        },
      }),
  )
  await page.goto(
    `/projects/${project}/netflow-correlation?namespace=synthetic`,
  )
  await expect(page.getByRole("alert").first()).toContainText(
    "correlation_source_expired",
  )
  await expect(page.getByRole("region", { name: "Address table" })).toHaveCount(
    0,
  )
  await page.goto(
    `/projects/${project}/netflow-correlation?revision=${revision}&namespace=synthetic&tab=addresses`,
  )
  await expect(
    page.getByRole("button", { name: "192.0.2.1", exact: true }),
  ).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`revision=${revision}`))
})

test("revocation removes cached rows and rejects an already pending page", async ({
  page,
}) => {
  await setup(page)
  let denied = false
  let release: (() => void) | undefined
  const pending = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route(`**${root}/source-correlations/${revision}`, (route) =>
    route.fulfill(
      denied
        ? {
            status: 403,
            json: { detail: { code: "correlation_source_access_revoked" } },
          }
        : { json: summary },
    ),
  )
  await page.route(
    `**${root}/source-correlations/${revision}/addresses?*`,
    async (route) => {
      const second =
        new URL(route.request().url()).searchParams.get("skip") === "25"
      if (second) await pending
      await route.fulfill({
        json: {
          data: [address(second ? "192.0.2.99" : "192.0.2.1")],
          count: 26,
          total_addresses: 26,
          skip: second ? 25 : 0,
          limit: 25,
        },
      })
    },
  )
  await page.goto(
    `/projects/${project}/netflow-correlation?revision=${revision}&namespace=synthetic&tab=addresses`,
  )
  await expect(
    page.getByRole("button", { name: "192.0.2.1", exact: true }),
  ).toBeVisible()
  const pageRequest = page.waitForRequest(
    (request) =>
      request.url().includes("/addresses?") &&
      new URL(request.url()).searchParams.get("skip") === "25",
  )
  await page
    .getByRole("navigation", { name: "Addresses pagination" })
    .getByRole("button", { name: "Next", exact: true })
    .click()
  await pageRequest
  denied = true
  await expect(page.getByRole("alert")).toContainText(
    "correlation_source_access_revoked",
    { timeout: 10000 },
  )
  const lateResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/addresses?") &&
      new URL(response.url()).searchParams.get("skip") === "25",
  )
  release?.()
  await lateResponse
  await expect(page.getByRole("region", { name: "Address table" })).toHaveCount(
    0,
  )
  await expect(page.getByText("192.0.2.99", { exact: true })).toHaveCount(0)
  await expect(page.getByText("192.0.2.1", { exact: true })).toHaveCount(0)
})
