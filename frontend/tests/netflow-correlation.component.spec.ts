import { readFileSync } from "node:fs"
import { expect, type Page, type Route, test } from "./fixtures"

const project = "00000000-0000-4000-8000-000000000274"
const revision = "10000000-0000-4000-8000-000000000274"
const analysis = "20000000-0000-4000-8000-000000000274"
const root = `/api/v1/projects/${project}`
const summary = {
  project_id: project,
  correlation_revision_id: revision,
  network_namespace: "synthetic",
  selection: {
    network_namespace: "synthetic",
    customer: null,
    cloud: null,
    history_run_id: null,
    netflow: { analysis_id: analysis },
  },
  pins: {
    NETFLOW: {
      dataset_id: "30000000-0000-4000-8000-000000000274",
      context_revision_id: "40000000-0000-4000-8000-000000000274",
    },
  },

  sources: [],
  total_addresses: 26,
  current_scope_state: "UNKNOWN",
  created_at: "2026-01-01T00:00:00Z",
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

const realAnswerSchemas = JSON.parse(
  readFileSync(
    new URL("./fixtures/netflow-answer-schemas.json", import.meta.url),
    "utf8",
  ),
) as Record<string, Record<string, unknown>>

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
    } else if (path.endsWith("/cloudatlas-ledger/snapshots")) {
      await route.fulfill({ json: [] })
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
  const records = Array.from({ length: 101 }, (_, index) => {
    const id = `70000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`
    return {
      id,
      context_revision_id: id,
      current_context_revision_id: "70000000-0000-4000-8000-000000000001",
      analysis_id: id,
      project_id: project,
      dataset_id: datasetId,
      network_namespace: "synthetic",
      revision: index + 1,
      state: "CONFIRMED",
      current_state: "CONFIRMED",
      status: "SUCCEEDED",
      display_filename: `Historic ${index + 1}`,
      created_at: "2026-01-01T00:00:00Z",
      record_count: 1,
      raw_record_count: 1,
      activity_valid_record_count: 1,
      isolated_record_count: 0,
    }
  })
  const pageOf = (route: Route) => {
    const url = new URL(route.request().url()),
      skip = Number(url.searchParams.get("skip") ?? 0)
    const limit = Number(url.searchParams.get("limit") ?? 25)
    expect(limit).toBeLessThanOrEqual(25)
    const key = url.pathname
    skips.set(key, [...(skips.get(key) ?? []), skip])
    const exact =
      url.searchParams.get("context_revision_id") ??
      url.searchParams.get("version_id") ??
      url.searchParams.get("upload_id") ??
      url.searchParams.get("dataset_id")
    const filtered = exact
      ? records.filter((item) => item.id === exact)
      : records
    const data = filtered.slice(skip, skip + limit).map((item) => ({
      ...item,
      status: key.includes("/versions") ? "PUBLISHED" : item.status,
      domain: url.searchParams.get("domain"),
    }))
    return route.fulfill({
      json: { data, count: filtered.length, current_netflow_dataset_id: null },
    })
  }
  await page.route(`**${root}/source-correlations?*`, (route) => {
    const url = new URL(route.request().url()),
      skip = Number(url.searchParams.get("skip") ?? 0)
    skips.set(url.pathname, [...(skips.get(url.pathname) ?? []), skip])
    return route.fulfill({
      json: {
        data: records.slice(skip, skip + 25).map((item) => ({
          ...summary,
          correlation_revision_id: item.id,
          revision: item.revision,
        })),
        count: 101,
        skip,
        limit: 25,
      },
    })
  })
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
    const url = new URL(route.request().url()),
      skip = Number(url.searchParams.get("skip") ?? 0)
    skips.set(url.pathname, [...(skips.get(url.pathname) ?? []), skip])
    await route.fulfill({ json: records.slice(skip, skip + 25) })
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
    "Correlations",
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

test("fixed inputs collapse for a revision and stay open for first use", async ({
  page,
}) => {
  await setup(page)
  await page.goto(
    `/projects/${project}/netflow-correlation?revision=${revision}&namespace=synthetic`,
  )
  const fixed = page.getByRole("region", { name: "Fixed inputs" })
  await expect(fixed.locator("details").first()).not.toHaveAttribute("open", "")
  await expect(
    page.getByRole("button", { name: "Summary", exact: true }),
  ).toBeVisible()
  await fixed.locator("details").first().locator(":scope > summary").click()
  await expect(
    fixed.getByRole("combobox", { name: "Dataset", exact: true }),
  ).toBeVisible()
  await page.goto(`/projects/${project}/netflow-correlation`)
  await expect(
    page
      .getByRole("region", { name: "Fixed inputs" })
      .locator("details")
      .first(),
  ).toHaveAttribute("open", "")
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
  let replied: (() => void) | undefined
  const responseReleased = new Promise<void>((resolve) => {
    replied = resolve
  })
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
      if (second) replied?.()
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
  release?.()
  await responseReleased
  await expect(page.getByRole("region", { name: "Address table" })).toHaveCount(
    0,
  )
  await expect(page.getByText("192.0.2.99", { exact: true })).toHaveCount(0)
  await expect(page.getByText("192.0.2.1", { exact: true })).toHaveCount(0)
})

test("admin records an explicitly unknown processing context without defaults", async ({
  page,
}) => {
  await page.addInitScript(() =>
    localStorage.setItem("access_token", "synthetic-component-token"),
  )
  const datasetId = "30000000-0000-4000-8000-000000000299"
  let body: Record<string, unknown> | undefined
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path === "/api/v1/users/me")
      return route.fulfill({
        json: {
          id: "admin",
          email: "admin@example.com",
          is_active: true,
          is_superuser: true,
        },
      })
    if (path.includes("/processing-contexts") && request.method() === "POST") {
      body = request.postDataJSON() as Record<string, unknown>
      return route.fulfill({
        json: {
          project_id: project,
          dataset_id: datasetId,
          context_revision_id: "40000000-0000-4000-8000-000000000299",
          current_context_revision_id: "40000000-0000-4000-8000-000000000299",
          network_namespace: "synthetic",
          state: "UNKNOWN",
          current_state: "UNKNOWN",
          revision: 1,
          parent_id: null,
          declarations: {},
          raw_sha256: "a",
          normalized_sha256: "a",
          created_by: "admin",
          created_at: "2026-01-01T00:00:00Z",
        },
      })
    }
    return route.fulfill({ json: { data: [], count: 0, can_manage: false } })
  })
  await page.goto(
    `/projects/${project}/netflow-correlation?dataset=${datasetId}`,
  )
  const contextForm = page.getByRole("region", {
    name: "Create processing context",
  })
  await contextForm.getByLabel("Network namespace").fill("synthetic")
  await contextForm.getByLabel("Observation point ID").fill("edge-a")
  await contextForm
    .getByLabel("Source-side position evidence")
    .fill("router export")
  await page.getByRole("button", { name: "Append context version" }).click()
  await expect.poll(() => body).toBeTruthy()
  expect(body).toMatchObject({
    state: "UNKNOWN",
    nat_context: "unknown",
    nat_evidence: null,
    observation_point: { id: "edge-a", view: "UNKNOWN" },
    sampling: { mode: "unknown", rate: null },
  })
})

for (const cloud of [
  "cloudSource=60000000-0000-4000-8000-000000000279",
  "cloudMode=none&cloudSource=60000000-0000-4000-8000-000000000279",
  "cloudMode=legacy&cloudSource=60000000-0000-4000-8000-000000000279&cloudSnapshot=70000000-0000-4000-8000-000000000279&cloudLedgerRevision=0&cloudScopeRevision=0",
  "cloudMode=legacy&cloudSource=60000000-0000-4000-8000-000000000279&cloudSnapshot=70000000-0000-4000-8000-000000000279",
]) {
  test(`unresolved cloud identity never becomes an omitted input: ${cloud}`, async ({
    page,
  }) => {
    await setup(page)
    let writes = 0
    page.on("request", (request) => {
      if (request.method() === "POST") writes++
    })
    await page.route(`**${root}/external-assets/sources`, (route) =>
      route.fulfill({ json: { data: [], count: 0, can_manage: true } }),
    )
    await page.goto(
      `/projects/${project}/netflow-correlation?namespace=synthetic&customerUpload=50000000-0000-4000-8000-000000000279&${cloud}`,
    )
    await expect(
      page.getByRole("button", {
        name: "Create fixed correlation",
        exact: true,
      }),
    ).toBeDisabled()
    await expect(page).toHaveURL(/cloudSource=60000000/)
    expect(writes).toBe(0)
  })
}

const taskLabels: Record<string, string> = {
  export: "Export and collection material",
  nat: "NAT mapping material",
  source: "Source-side position material",
  tcp: "TCP flags material",
  coverage: "Observation coverage material",
  service: "Service role material",
}
async function setupAnswers(page: Page) {
  await setup(page)
  const feedbackRevision = "80000000-0000-4000-8000-000000000274"
  const kinds = ["export", "nat", "source", "tcp", "coverage", "service"]
  expect(kinds.every((kind) => realAnswerSchemas[kind])).toBe(true)
  const identity = {
    project_id: project,
    analysis_id: analysis,
    dataset_id: "30000000-0000-4000-8000-000000000274",
    context_revision_id: "40000000-0000-4000-8000-000000000274",
    network_namespace: "synthetic",
    test_fixture: true,
  }
  const material = (kind: string, index: number) => ({
    task_id: `task-${kind}`,
    task: { task_kind: kind, title: `${kind} task`, task_scope: "dataset" },
    schema_version: "netflow-feedback-v1",
    answer_schema: realAnswerSchemas[kind],
    material_status: "AWAITING_FEEDBACK",
    declared_answers: index === 0 ? { responsible_unit: null } : {},
    provider_claim: {},
    authenticated_author: null,
    missing_fields: [],
    field_errors: [],
    blocked_by: [],
    note_checks: [],
    model_hints: [],
    next_action: "raw_field_name",
    review_required: true,
    task_closed: false,
    facts_changed: false,
    external_reachability: "NOT_VERIFIED",
  })
  const materials = kinds.map(material)
  const feedback = {
    ...identity,
    feedback_revision_id: feedbackRevision,
    parent_id: null,
    revision: 1,
    system_generated: true,
    authenticated_actor_id: null,
    authenticated_submitted_at: "2026-01-01T00:00:00Z",
    human_note: null,
    binding: {},
    schema_version: "netflow-feedback-v1",
    submission: {},
    summary: {},
    response_authors: {},
    review_required: true,
    task_closed: false,
    facts_changed: false,
  }
  let saved: unknown
  let beforePost: ((route: Route) => Promise<void>) | undefined
  let sourceReads = 0
  await page.route(`**${root}/external-assets/sources**`, (route) => {
    sourceReads += 1
    return route.fulfill({ json: { data: [], count: 0, can_manage: true } })
  })
  await page.route(
    `**${root}/netflow-analyses/${analysis}/feedback**`,
    async (route) => {
      if (route.request().method() === "POST") {
        saved = route.request().postDataJSON()
        if (beforePost) return beforePost(route)
        return route.fulfill({ json: feedback })
      }
      await route.fulfill({ json: feedback })
    },
  )
  await page.route(
    `**${root}/netflow-analyses/${analysis}/review-tasks?*`,
    (route) =>
      route.fulfill({
        json: {
          ...identity,
          feedback_revision_id: feedbackRevision,
          binding: {},
          data: materials,
          count: materials.length,
          skip: 0,
          limit: 25,
          total_tasks: materials.length,
          state_counts: {},
        },
      }),
  )
  await page.route(
    `**${root}/netflow-analyses/${analysis}/review-tasks/*`,
    (route) => {
      const id = decodeURIComponent(
        new URL(route.request().url()).pathname.split("/").at(-1)!,
      )
      const item = materials.find((value) => value.task_id === id)!
      return route.fulfill({
        json: {
          ...identity,
          feedback_revision_id: feedbackRevision,
          binding: {},
          material: item,
          dependencies: [],
        },
      })
    },
  )
  await page.goto(
    `/projects/${project}/netflow-correlation?revision=${revision}&namespace=synthetic&tab=tasks&feedbackRevision=${feedbackRevision}&taskId=task-export`,
  )
  await expect.poll(() => sourceReads).toBeGreaterThan(0)
  await expect(
    page.getByRole("region", { name: "Review answers" }),
  ).toBeVisible()
  return {
    materials,
    feedback,
    feedbackRevision,
    kinds,
    saved: () => saved,
    interceptPost: (handler: (route: Route) => Promise<void>) => {
      beforePost = handler
    },
  }
}

test("real processor answer schemas render six task kinds without resetting edits", async ({
  page,
}) => {
  const { saved, feedbackRevision, kinds } = await setupAnswers(page)
  const answer = page.getByRole("region", { name: "Review answers" })
  await answer.getByLabel("Responsible unit value state").selectOption("value")
  await answer.getByLabel("Responsible unit", { exact: true }).fill("team-a")
  await page
    .getByRole("button", { name: "Export and collection material" })
    .click()
  await expect(
    answer.getByLabel("Responsible unit", { exact: true }),
  ).toHaveValue("team-a")
  await page.getByRole("button", { name: "Append correction" }).click()
  await expect.poll(() => saved()).toBeTruthy()
  expect(saved()).toMatchObject({
    expected_parent_id: feedbackRevision,
    responses: [
      { task_id: "task-export", answers: { responsible_unit: "team-a" } },
    ],
  })
  for (const kind of kinds.slice(1)) {
    await page.getByRole("button", { name: taskLabels[kind] }).click()
    await expect(
      page.getByRole("region", { name: "Review answers" }),
    ).toBeVisible()
  }
  await page
    .getByRole("button", { name: "Export and collection material" })
    .click()
})

test("bounded answer controls retain null, zero and arrays and reject malformed IP/time", async ({
  page,
}) => {
  const scenario = await setupAnswers(page)
  await page.getByRole("button", { name: taskLabels.nat }).click()
  const answer = page.getByRole("region", { name: "Review answers" })
  await answer.getByLabel("NAT mapping value state").selectOption("value")
  await answer.getByRole("button", { name: "Add mapping" }).click()
  for (const field of ["Protocol", "Pre-NAT IP", "Post-NAT IP"])
    await answer.getByLabel(`${field} value state`).selectOption("value")
  await answer.getByLabel("Protocol", { exact: true }).fill("0")
  await answer.getByLabel("Pre-NAT IP", { exact: true }).fill("not-an-ip")
  await answer.getByLabel("Post-NAT IP", { exact: true }).fill("2001:db8::1")
  await answer.getByLabel("Pre-NAT port value state").selectOption("null")
  await answer.getByLabel("Post-NAT port value state").selectOption("null")
  await expect(
    page.getByRole("button", { name: "Append correction", exact: true }),
  ).toBeDisabled()
  await answer.getByLabel("Pre-NAT IP", { exact: true }).fill("192.0.2.1")
  await answer
    .getByLabel("Supporting evidence value state")
    .selectOption("value")
  await answer
    .getByLabel("Supporting evidence", { exact: true })
    .fill("synthetic first reference\nsynthetic second reference")
  await answer
    .getByLabel("Mapping time window value state")
    .selectOption("value")
  for (const field of ["Start time", "End time"])
    await answer.getByLabel(`${field} value state`).selectOption("value")
  await answer
    .getByLabel("Start time", { exact: true })
    .fill("2026-01-01T02:00:00Z")
  await answer
    .getByLabel("End time", { exact: true })
    .fill("2026-01-01T01:00:00Z")
  await expect(
    page.getByRole("button", { name: "Append correction", exact: true }),
  ).toBeDisabled()
  await answer
    .getByLabel("End time", { exact: true })
    .fill("2026-01-01T03:00:00Z")
  await page
    .getByRole("button", { name: "Append correction", exact: true })
    .click()
  await expect.poll(scenario.saved).toBeTruthy()
  expect(scenario.saved()).toMatchObject({
    responses: [
      {
        task_id: "task-nat",
        answers: {
          nat_mapping: [
            {
              protocol: 0,
              pre_ip: "192.0.2.1",
              pre_port: null,
              post_ip: "2001:db8::1",
              post_port: null,
            },
          ],
          supporting_evidence: [
            "synthetic first reference",
            "synthetic second reference",
          ],
          mapping_time_window: {
            start: "2026-01-01T02:00:00Z",
            end: "2026-01-01T03:00:00Z",
          },
        },
      },
    ],
  })
})

test("partial answer controls distinguish missing, null, empty, false and zero", async ({
  page,
}) => {
  const scenario = await setupAnswers(page)
  const material = scenario.materials[1]!
  material.answer_schema = {
    type: "object",
    properties: {
      optional: { type: "string" },
      empty: { type: "string" },
      flag: { type: "boolean" },
      zero: { type: "integer" },
      nullable: { anyOf: [{ type: "string" }, { type: "null" }] },
    },
  } as typeof material.answer_schema
  await page.getByRole("button", { name: taskLabels.nat }).click()
  const answer = page.getByRole("region", { name: "Review answers" })
  for (const field of ["empty", "flag", "zero"])
    await answer.getByLabel(`${field} value state`).selectOption("value")
  await answer.getByLabel("zero", { exact: true }).fill("0")
  await answer.getByLabel("nullable value state").selectOption("null")
  await page
    .getByRole("button", { name: "Append correction", exact: true })
    .click()
  await expect.poll(scenario.saved).toBeTruthy()
  expect(scenario.saved()).toMatchObject({
    responses: [
      { answers: { empty: "", flag: false, zero: 0, nullable: null } },
    ],
  })
  expect(
    (
      scenario.saved() as {
        responses: Array<{ answers: Record<string, unknown> }>
      }
    ).responses[0]!.answers,
  ).not.toHaveProperty("optional")
})

test("unknown retained fields are not discarded or sent through a JSON fallback", async ({
  page,
}) => {
  const scenario = await setupAnswers(page)
  scenario.materials[1]!.declared_answers = {
    unrecognized: { kept: true },
  } as never
  await page.getByRole("button", { name: taskLabels.nat }).click()
  await expect(page.getByRole("alert")).toContainText(
    "Unsupported answer structure",
  )
  await expect(
    page.getByRole("button", { name: "Append correction", exact: true }),
  ).toBeDisabled()
  expect(scenario.saved()).toBeUndefined()
})

test("a late feedback response cannot replace another task draft", async ({
  page,
}) => {
  const scenario = await setupAnswers(page)
  let release: (() => void) | undefined
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  scenario.interceptPost(async (route) => {
    await gate
    await route.fulfill({
      json: {
        ...scenario.feedback,
        feedback_revision_id: "80000000-0000-4000-8000-000000000299",
        revision: 2,
        parent_id: scenario.feedbackRevision,
      },
    })
  })
  const answer = page.getByRole("region", { name: "Review answers" })
  await answer.getByLabel("Responsible unit value state").selectOption("value")
  await answer
    .getByLabel("Responsible unit", { exact: true })
    .fill("old-task-team")
  await page
    .getByRole("button", { name: "Append correction", exact: true })
    .click()
  await expect.poll(scenario.saved).toBeTruthy()
  await page.getByRole("button", { name: taskLabels.nat }).click()
  await answer.getByLabel("Responsible unit value state").selectOption("value")
  await answer
    .getByLabel("Responsible unit", { exact: true })
    .fill("new-task-draft")
  const late = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().endsWith("/feedback"),
  )
  release!()
  await late
  await expect(
    answer.getByLabel("Responsible unit", { exact: true }),
  ).toHaveValue("new-task-draft")
  await expect(page).toHaveURL(/taskId=task-nat/)
  await expect(page).toHaveURL(
    new RegExp(`feedbackRevision=${scenario.feedbackRevision}`),
  )
})

for (const failure of [
  "netflow_revision_conflict",
  "netflow_key_conflict",
  "response_lost",
]) {
  test(`context ${failure} uses the correct recovery path`, async ({
    page,
  }) => {
    await setup(page)
    await page.route("**/api/v1/users/me", (route) =>
      route.fulfill({
        json: {
          id: "admin",
          email: "admin@example.com",
          is_active: true,
          is_superuser: true,
        },
      }),
    )
    const datasetId = "30000000-0000-4000-8000-000000000299"
    const contextId = "40000000-0000-4000-8000-000000000299"
    const context = {
      project_id: project,
      dataset_id: datasetId,
      context_revision_id: contextId,
      current_context_revision_id: contextId,
      network_namespace: "synthetic",
      state: "UNKNOWN",
      current_state: "UNKNOWN",
      revision: 1,
      parent_id: null,
      declarations: {},
      raw_sha256: "a",
      normalized_sha256: "a",
      created_by: "admin",
      created_at: "2026-01-01T00:00:00Z",
    }
    let posts = 0,
      reads = 0,
      key: string | undefined,
      recovered: string | undefined
    await page.route(
      `**${root}/netflow-datasets/${datasetId}/processing-contexts**`,
      async (route) => {
        const req = route.request(),
          url = new URL(req.url())
        if (req.method() === "POST") {
          posts++
          key = req.headers()["idempotency-key"]
          if (failure === "response_lost") return route.abort("failed")
          return route.fulfill({
            status: 409,
            json: { detail: { code: failure } },
          })
        }
        if (url.pathname.includes("/operations/")) {
          recovered = url.pathname.split("/").at(-1)
          return route.fulfill({ json: context })
        }
        reads++
        return route.fulfill({
          json: { data: [], count: 0, skip: 0, limit: 25 },
        })
      },
    )
    await page.goto(
      `/projects/${project}/netflow-correlation?dataset=${datasetId}`,
    )
    const form = page.getByRole("region", { name: "Create processing context" })
    await form.getByLabel("Network namespace").fill("synthetic")
    await form.getByLabel("Observation point ID").fill("edge-a")
    await form
      .getByLabel("Source-side position evidence")
      .fill("synthetic declared export")
    await form.getByRole("button", { name: "Append context version" }).click()
    await expect(form.getByRole("alert")).toBeVisible()
    if (failure === "netflow_revision_conflict") {
      await expect(
        form.getByRole("button", { name: "Query original context operation" }),
      ).toHaveCount(0)
      const initialReads = reads
      await form.getByRole("button", { name: "Read latest context" }).click()
      await expect.poll(() => reads).toBeGreaterThan(initialReads)
    } else {
      await expect(
        form.getByRole("button", { name: "Append context version" }),
      ).toBeDisabled()
      await form
        .getByRole("button", { name: "Query original context operation" })
        .click()
      await expect.poll(() => recovered).toBe(key)
    }
    expect(posts).toBe(1)
  })
}
