import {
  NetflowProgressIdentityError,
  NetflowProgressShapeError,
  netflowProgressCancellation,
  netflowProgressTerminal,
  parseNetflowProgress,
} from "../src/lib/netflow-progress"
import { expect, type Page, type Route, test } from "./fixtures"

const project = "00000000-0000-4000-8000-000000000301"
const analysis = "10000000-0000-4000-8000-000000000301"
const otherAnalysis = "10000000-0000-4000-8000-000000000302"
const dataset = "20000000-0000-4000-8000-000000000301"
const otherDataset = "20000000-0000-4000-8000-000000000302"
const context = "30000000-0000-4000-8000-000000000301"
const otherContext = "30000000-0000-4000-8000-000000000302"
const scope = "a".repeat(64)
const root = `/api/v1/projects/${project}`
const _progressPath = (id = analysis) =>
  `${root}/netflow-bulk/analyses/${id}/progress`
const identity = (id = analysis) => ({
  project_id: project,
  analysis_id: id,
  dataset_id: id === analysis ? dataset : otherDataset,
  context_revision_id: id === analysis ? context : otherContext,
  network_namespace: "synthetic",
  test_fixture: true,
  provenance: { backend: "netflow-bulk-v1" },
})
const batch = (overrides: Record<string, unknown> = {}) => ({
  ...identity(),
  status: "RUNNING",
  can_read_result: false,
  completed_at: null,
  created_at: "2026-01-01T00:00:00Z",
  context: {},
  quality: {},
  result: null,
  error_code: null,
  ...overrides,
})
const observation = (overrides: Record<string, unknown> = {}) => ({
  ...identity(),
  status: "RUNNING",
  phase: "NORMALIZING",
  cancel_requested: false,
  heartbeat_at: "2026-01-01T00:00:05Z",
  lease_until: "2026-01-01T00:02:00Z",
  files_completed: 0,
  files_total: 4,
  rows_normalized: 0,
  metrics: {},
  ...overrides,
})
const access = {
  project_id: project,
  analysis_id: analysis,
  dataset_id: dataset,
  context_revision_id: context,
  network_namespace: "synthetic",
  identity_sha256: "a".repeat(64),
  status: "RUNNING",
  can_read_result: false,
}
const current = {
  project_id: project,
  collection_scope: null,
  scopes: [],
  current: null,
  latest_attempt: null,
}

type Reply = (route: Route) => Promise<void> | void
const json = (route: Route, value: unknown, status = 200) =>
  route.fulfill({ status, json: value })

async function mountResults(
  page: Page,
  replies: {
    batch?: () => Record<string, unknown>
    access?: () => Record<string, unknown>
    progress: () => Reply | Promise<Reply>
    extra?: (path: string, route: Route) => boolean
  },
) {
  let batchValue = replies.batch ?? (() => batch())
  let accessValue = replies.access ?? (() => access)
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "synthetic-token")
    localStorage.setItem("exposure:language", "en")
  })
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === "/api/v1/users/me")
      return json(route, {
        id: "synthetic-user",
        email: "synthetic@example.net",
        is_active: true,
        is_superuser: false,
      })
    if (path === "/api/v1/projects/")
      return json(route, {
        data: [{ id: project, name: "Synthetic project", status: "active" }],
        count: 1,
      })
    if (path === `${root}/netflow-analyses/${analysis}/access`)
      return json(route, accessValue())
    if (path === `${root}/netflow-analyses/${analysis}`)
      return json(route, batchValue())
    if (path === `${root}/netflow-results/current`) return json(route, current)
    if (path.endsWith(`/netflow-bulk/analyses/${analysis}/progress`)) {
      const reply = await replies.progress()
      return reply(route)
    }
    if (replies.extra?.(path, route)) return
    return json(route, { data: [], count: 0 })
  })
  return {
    setBatch: (value: Record<string, unknown>) => {
      batchValue = () => value
    },
    setAccess: (value: Record<string, unknown>) => {
      accessValue = () => value
    },
  }
}

const resultsUrl = `/projects/${project}/netflow-results?analysis=${analysis}&dataset=${dataset}&collectionScope=${scope}`

test.describe("progress parser", () => {
  test("terminal, cancellation and identity rules are pure", () => {
    const base = {
      status: "RUNNING",
      phase: "NORMALIZING",
      cancel_requested: false,
      heartbeat_at: null,
      lease_until: null,
      files_completed: 0,
      files_total: 4,
      rows_normalized: 0,
      metrics: {},
    }
    expect(netflowProgressTerminal(base)).toBe(false)
    expect(
      netflowProgressTerminal({
        ...base,
        status: "SUCCEEDED",
        phase: "SUCCEEDED",
        files_completed: 3,
      }),
    ).toBe(false)
    expect(
      netflowProgressTerminal({
        ...base,
        status: "SUCCEEDED",
        phase: "SUCCEEDED",
        files_completed: 4,
      }),
    ).toBe(true)
    expect(
      netflowProgressTerminal({
        ...base,
        status: "FAILED",
        phase: "CANCELLED",
      }),
    ).toBe(true)
    expect(
      netflowProgressTerminal({
        ...base,
        status: "FAILED",
        phase: "UNSEEN_PHASE",
      }),
    ).toBe(false)
    expect(netflowProgressCancellation(base, false)).toBe("none")
    expect(netflowProgressCancellation(base, true)).toBe("requested")
    expect(
      netflowProgressCancellation(
        { ...base, status: "FAILED", phase: "FAILED", cancel_requested: true },
        true,
      ),
    ).toBe("none")
    expect(
      netflowProgressCancellation(
        {
          ...base,
          status: "SUCCEEDED",
          phase: "SUCCEEDED",
          files_completed: 4,
          cancel_requested: true,
        },
        true,
      ),
    ).toBe("none")
    expect(
      netflowProgressCancellation(
        { ...base, status: "FAILED", phase: "CANCELLED" },
        false,
      ),
    ).toBe("confirmed")
    expect(
      netflowProgressCancellation(
        {
          ...base,
          status: "SUCCEEDED",
          phase: "SUCCEEDED",
          files_completed: 4,
        },
        true,
      ),
    ).toBe("none")
  })

  test("the parser accepts exactly the observed identity", () => {
    const expected = {
      backend: "netflow-bulk-v1" as const,
      project_id: project,
      analysis_id: analysis,
      dataset_id: dataset,
      context_revision_id: context,
      network_namespace: "synthetic",
      test_fixture: true,
    }
    const value = {
      ...observation({ files_total: 0 }),
      ...expected,
      provenance: { backend: "netflow-bulk-v1" },
    }
    expect(parseNetflowProgress(value, expected).files_total).toBe(0)
    expect(() =>
      parseNetflowProgress(
        { ...value, files_completed: 2, files_total: 1 },
        expected,
      ),
    ).toThrow(NetflowProgressShapeError)
    expect(() =>
      parseNetflowProgress({ ...value, analysis_id: otherAnalysis }, expected),
    ).toThrow(NetflowProgressIdentityError)
    expect(() =>
      parseNetflowProgress(
        { ...value, provenance: { backend: "legacy" } },
        expected,
      ),
    ).toThrow(NetflowProgressIdentityError)
  })
})

test("progress follows server phases to terminal and then stops polling", async ({
  page,
}) => {
  let reads = 0
  const replies = [
    observation(),
    observation({
      phase: "COMPUTING",
      files_completed: 2,
      rows_normalized: 12,
    }),
    observation({
      status: "SUCCEEDED",
      phase: "SUCCEEDED",
      files_completed: 4,
      rows_normalized: 24,
      lease_until: null,
    }),
  ]
  const mounted = await mountResults(page, {
    progress: () => (route) => {
      const value = replies[Math.min(reads, replies.length - 1)]
      reads += 1
      return json(route, value)
    },
  })
  await mounted.setBatch(batch())
  await page.clock.install()
  await page.goto(resultsUrl)
  await expect(
    page.getByRole("heading", { name: "Processing progress", exact: true }),
  ).toBeVisible()
  await expect(page.getByText("Phase: Normalizing input files")).toBeVisible()
  await expect(page.getByText("Last heartbeat:")).toBeVisible()
  await expect(page.getByText("Progress observed:")).toBeVisible()
  await expect(page.getByLabel("Files complete", { exact: true })).toHaveText(
    "0 / 4",
  )
  await page.clock.runFor(5001)
  await expect(page.getByText("Phase: Computing results")).toBeVisible()
  await expect(page.getByLabel("Files complete", { exact: true })).toHaveText(
    "2 / 4",
  )
  await page.clock.runFor(5001)
  await expect(
    page.getByText("Progress status: Analysis completed"),
  ).toBeVisible()
  await expect(page.getByLabel("Files complete", { exact: true })).toHaveText(
    "4 / 4",
  )
  const stopped = reads
  await page.clock.runFor(20000)
  expect(reads).toBe(stopped)
})

test("a first read failure retries, a later failure keeps the last observation, and both recover", async ({
  page,
}) => {
  const queue: Array<unknown> = [
    { code: 503, body: { detail: { code: "synthetic_progress_unavailable" } } },
    observation(),
    { code: 500, body: { detail: { code: "synthetic_progress_unavailable" } } },
    observation({ phase: "COMPUTING", files_completed: 1 }),
  ]
  await mountResults(page, {
    progress: () => (route) => {
      const value = queue.length > 1 ? queue.shift() : queue[0]
      if (value && typeof value === "object" && "code" in value)
        return json(
          route,
          (value as { body: unknown }).body,
          (value as { code: number }).code,
        )
      return json(route, value)
    },
  })
  await page.clock.install()
  await page.goto(resultsUrl)
  await expect(
    page.getByText(
      "Progress is temporarily unavailable. Retrying for the same task.",
      { exact: true },
    ),
  ).toBeVisible()
  await page.clock.runFor(5001)
  await expect(page.getByText("Phase: Normalizing input files")).toBeVisible()
  await page.clock.runFor(5001)
  await expect(
    page.getByText(
      "The last verified progress is shown; the latest read failed.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(page.getByText("Phase: Normalizing input files")).toBeVisible()
  await page.clock.runFor(5001)
  await expect(page.getByText("Phase: Computing results")).toBeVisible()
  await expect(
    page.getByText(
      "The last verified progress is shown; the latest read failed.",
      { exact: true },
    ),
  ).toHaveCount(0)
  await expect(page.getByText("Progress status: Running")).toBeVisible()
})

test("legacy analyses never call the bulk progress endpoint", async ({
  page,
}) => {
  let progressReads = 0
  await mountResults(page, {
    batch: () => batch({ provenance: {}, status: "FAILED" }),
    access: () => ({ ...access, status: "FAILED", can_read_result: false }),
    progress: () => (route) => {
      progressReads += 1
      return json(route, observation())
    },
  })
  await page.goto(resultsUrl)
  await expect(
    page.getByText(/Failed; inspect the error before retrying/),
  ).toBeVisible()
  await expect(
    page.getByRole("heading", { name: "Processing progress", exact: true }),
  ).toHaveCount(0)
  expect(progressReads).toBe(0)
})

test("zero totals, a missing heartbeat and an unknown phase stay literal", async ({
  page,
}) => {
  await mountResults(page, {
    progress: () => (route) =>
      json(
        route,
        observation({
          status: "PENDING",
          phase: "SYNTHETIC_QUEUE",
          heartbeat_at: null,
          lease_until: null,
          files_completed: 0,
          files_total: 0,
        }),
      ),
  })
  await page.clock.install()
  await page.goto(resultsUrl)
  await expect(page.getByLabel("Files complete", { exact: true })).toHaveText(
    "0 / 0",
  )
  await expect(page.getByText(/No heartbeat reported/)).toBeVisible()
  await expect(page.getByText("Phase: SYNTHETIC_QUEUE")).toBeVisible()
  await expect(page.getByRole("progressbar")).toHaveCount(0)
  await expect(page.getByText(/%/)).toHaveCount(0)
})

test("a late observation clears on refusal and stops the same-task interval", async ({
  page,
}) => {
  let reads = 0
  await mountResults(page, {
    progress: () => (route) => {
      reads += 1
      if (reads === 1) return json(route, observation())
      return json(
        route,
        { detail: { code: "netflow_analysis_not_found" } },
        404,
      )
    },
  })
  await page.clock.install()
  await page.goto(resultsUrl)
  await expect(page.getByText("Phase: Normalizing input files")).toBeVisible()
  await page.clock.runFor(5001)
  await expect(
    page.getByRole("heading", {
      name: "This fixed batch cannot be read",
      exact: true,
    }),
  ).toBeVisible()
  await expect(page.getByText("Phase: Normalizing input files")).toHaveCount(0)
  const stopped = reads
  await page.clock.runFor(20000)
  expect(reads).toBe(stopped)
  await expect(
    page.getByRole("link", { name: "Original activity ledger", exact: true }),
  ).toHaveCount(0)
})

for (const status of [401, 403, 410]) {
  test(`a ${status} progress refusal clears content`, async ({ page }) => {
    let reads = 0
    await mountResults(page, {
      progress: () => (route) => {
        reads += 1
        if (reads === 1) return json(route, observation())
        return json(
          route,
          { detail: { code: "netflow_view_forbidden" } },
          status,
        )
      },
    })
    await page.clock.install()
    await page.goto(resultsUrl)
    await expect(page.getByText("Phase: Normalizing input files")).toBeVisible()
    await page.clock.runFor(5001)
    await expect(
      page.getByRole("heading", {
        name: "This fixed batch cannot be read",
        exact: true,
      }),
    ).toBeVisible()
    await expect(page.getByText("Phase: Normalizing input files")).toHaveCount(
      0,
    )
  })
}

test("a malformed identity never renders and polling can recover", async ({
  page,
}) => {
  let reads = 0
  await mountResults(page, {
    progress: () => (route) => {
      reads += 1
      return json(
        route,
        reads === 1
          ? observation({ analysis_id: otherAnalysis })
          : observation({ phase: "COMPUTING" }),
      )
    },
  })
  await page.clock.install()
  await page.goto(resultsUrl)
  await expect(
    page.getByText(
      "Progress data did not match this fixed task and was cleared.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(page.getByText(/Normalizing input files/)).toHaveCount(0)
  await page.clock.runFor(5001)
  await expect(page.getByText("Phase: Computing results")).toBeVisible()
  await expect(
    page.getByText(
      "Progress data did not match this fixed task and was cleared.",
      { exact: true },
    ),
  ).toHaveCount(0)
})

test("an already terminal task gets one counters read and no interval", async ({
  page,
}) => {
  let reads = 0
  await mountResults(page, {
    batch: () => batch({ status: "SUCCEEDED", can_read_result: false }),
    progress: () => (route) => {
      reads += 1
      return json(
        route,
        observation({
          status: "SUCCEEDED",
          phase: "SUCCEEDED",
          files_completed: 4,
          rows_normalized: 24,
          lease_until: null,
        }),
      )
    },
  })
  await page.clock.install()
  await page.goto(resultsUrl)
  await expect(
    page.getByText("Progress status: Analysis completed"),
  ).toBeVisible()
  await expect(page.getByLabel("Files complete", { exact: true })).toHaveText(
    "4 / 4",
  )
  expect(reads).toBe(1)
  await page.clock.runFor(20000)
  expect(reads).toBe(1)
})

test("inconsistent success stays non-terminal until status, phase and counts agree", async ({
  page,
}) => {
  let reads = 0
  const replies = [
    observation({
      status: "SUCCEEDED",
      phase: "COMPUTING",
      files_completed: 4,
    }),
    observation({
      status: "SUCCEEDED",
      phase: "SUCCEEDED",
      files_completed: 3,
    }),
    observation({
      status: "SUCCEEDED",
      phase: "SUCCEEDED",
      files_completed: 4,
    }),
  ]
  await mountResults(page, {
    progress: () => (route) => {
      reads += 1
      return json(route, replies[Math.min(reads - 1, replies.length - 1)])
    },
  })
  await page.clock.install()
  await page.goto(resultsUrl)
  await expect(page.getByText("Phase: Computing results")).toBeVisible()
  await page.clock.runFor(5001)
  await expect(page.getByLabel("Files complete", { exact: true })).toHaveText(
    "3 / 4",
  )
  await page.clock.runFor(5001)
  await expect(page.getByLabel("Files complete", { exact: true })).toHaveText(
    "4 / 4",
  )
  const stopped = reads
  await page.clock.runFor(20000)
  expect(reads).toBe(stopped)
})

test("a cancelled observation is confirmed even when cancel_requested is set", async ({
  page,
}) => {
  await mountResults(page, {
    batch: () => batch({ status: "FAILED", can_read_result: false }),
    progress: () => (route) =>
      json(
        route,
        observation({
          status: "FAILED",
          phase: "CANCELLED",
          cancel_requested: true,
          lease_until: null,
        }),
      ),
  })
  await page.goto(resultsUrl)
  await expect(
    page.getByText("Processing cancelled", { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByText("Cancellation requested", { exact: true }),
  ).toHaveCount(0)
})

test("failed without the cancelled phase is terminal, not requested", async ({
  page,
}) => {
  await mountResults(page, {
    batch: () => batch({ status: "FAILED", can_read_result: false }),
    progress: () => (route) =>
      json(
        route,
        observation({
          status: "FAILED",
          phase: "FAILED",
          cancel_requested: true,
          lease_until: null,
        }),
      ),
  })
  await page.goto(resultsUrl)
  await expect(
    page.getByText(
      "Progress status: Failed; inspect the error before retrying",
    ),
  ).toBeVisible()
  await expect(
    page.getByText("Cancellation requested", { exact: true }),
  ).toHaveCount(0)
  await expect(
    page.getByText("Processing cancelled", { exact: true }),
  ).toHaveCount(0)
})

test("terminal success wins even when cancel_requested is still set", async ({
  page,
}) => {
  await mountResults(page, {
    batch: () =>
      batch({
        status: "SUCCEEDED",
        completed_at: "2026-01-01T00:01:00Z",
      }),
    progress: () => (route) =>
      json(
        route,
        observation({
          status: "SUCCEEDED",
          phase: "SUCCEEDED",
          files_completed: 4,
          lease_until: null,
          cancel_requested: true,
        }),
      ),
  })
  await page.goto(resultsUrl)
  await expect(
    page.getByText("Progress status: Analysis completed"),
  ).toBeVisible()
  await expect(
    page.getByText("Cancellation requested", { exact: true }),
  ).toHaveCount(0)
  await expect(
    page.getByText("Processing cancelled", { exact: true }),
  ).toHaveCount(0)
})

const fixedDataset = {
  id: dataset,
  display_filename: "capture.csv",
  raw_record_count: 4,
  activity_valid_record_count: 4,
  isolated_record_count: 0,
  created_at: "2026-01-01T00:00:00Z",
}
const otherDatasetRow = {
  ...fixedDataset,
  id: otherDataset,
  display_filename: "later.csv",
}
const contextRow = {
  project_id: project,
  dataset_id: dataset,
  context_revision_id: context,
  current_context_revision_id: context,
  network_namespace: "synthetic",
  state: "CONFIRMED",
  current_state: "CONFIRMED",
  revision: 1,
  parent_id: null,
  declarations: {},
  raw_sha256: "a",
  normalized_sha256: "a",
  created_by: "synthetic",
  created_at: "2026-01-01T00:00:00Z",
}
const otherContextRow = {
  ...contextRow,
  dataset_id: otherDataset,
  context_revision_id: otherContext,
  current_context_revision_id: otherContext,
}

async function mountActions(
  page: Page,
  {
    progress,
    cancel,
    reconcile,
    hold,
  }: {
    progress: (id: string) => Reply
    cancel?: (route: Route) => Promise<void> | void
    reconcile?: (route: Route) => Promise<void> | void
    hold?: (id: string) => Promise<void>
  },
) {
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "synthetic-token")
    localStorage.setItem("exposure:language", "en")
  })
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path === "/api/v1/users/me")
      return json(route, {
        id: "synthetic-admin",
        email: "admin@example.net",
        is_active: true,
        is_superuser: true,
      })
    if (path === "/api/v1/projects/")
      return json(route, {
        data: [{ id: project, name: "Synthetic project", status: "active" }],
        count: 1,
      })
    if (path === `${root}/external-assets/sources`)
      return json(route, { data: [], count: 0, can_manage: true })
    if (path === `${root}/netflow-datasets`)
      return json(route, { data: [fixedDataset, otherDatasetRow], count: 2 })
    if (path === `${root}/netflow-datasets/${dataset}`)
      return json(route, { data: [fixedDataset], count: 1 })
    if (path === `${root}/netflow-datasets/${otherDataset}`)
      return json(route, { data: [otherDatasetRow], count: 1 })
    if (path === `${root}/netflow-datasets/${dataset}/processing-contexts`)
      return json(route, { data: [contextRow], count: 1 })
    if (path === `${root}/netflow-datasets/${otherDataset}/processing-contexts`)
      return json(route, { data: [otherContextRow], count: 1 })
    if (path === `${root}/netflow-datasets/${dataset}/analyses`)
      return json(route, {
        data: [
          batch(),
          batch({ ...identity(otherAnalysis), analysis_id: otherAnalysis }),
        ],
        count: 2,
      })
    if (path === `${root}/netflow-datasets/${otherDataset}/analyses`)
      return json(route, {
        data: [
          batch({
            ...identity(otherAnalysis),
            analysis_id: otherAnalysis,
            dataset_id: otherDataset,
            context_revision_id: otherContext,
          }),
        ],
        count: 1,
      })
    if (path === `${root}/netflow-analyses/${otherAnalysis}`)
      return json(
        route,
        batch({
          ...identity(otherAnalysis),
          analysis_id: otherAnalysis,
          dataset_id: otherDataset,
          context_revision_id: otherContext,
        }),
      )
    if (path === `${root}/netflow-analyses/${analysis}`)
      return json(route, batch())
    if (path.endsWith("/progress")) {
      const id = path.includes(otherAnalysis) ? otherAnalysis : analysis
      if (hold) await hold(id)
      return progress(id)(route)
    }
    if (path.endsWith("/cancel")) {
      if (cancel) return cancel(route)
      return json(route, { analysis_id: analysis, cancel_requested: true })
    }
    if (path.endsWith("/reconcile")) {
      if (reconcile) return reconcile(route)
      return json(route, batch())
    }
    return json(route, { data: [], count: 0, can_manage: true })
  })
}

const actionsUrl = `/projects/${project}/netflow-correlation?dataset=${dataset}&context=${context}&analysis=${analysis}&namespace=synthetic`

test("an acknowledged cancel is requested, then confirmed only by one cancelled observation", async ({
  page,
}) => {
  let reads = 0
  const replies = [
    observation(),
    observation({ cancel_requested: true }),
    observation({
      status: "FAILED",
      phase: "CANCELLED",
      cancel_requested: true,
      lease_until: null,
    }),
  ]
  await mountActions(page, {
    progress: () => (route) => {
      const value = replies[Math.min(reads, replies.length - 1)]
      reads += 1
      return json(route, value)
    },
  })
  let cancels = 0
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/cancel"))
      cancels += 1
  })
  await page.clock.install()
  await page.goto(actionsUrl)
  const cancel = page.getByRole("button", {
    name: "Cancel bulk processing",
    exact: true,
  })
  await expect(cancel).toBeVisible()
  await expect(cancel).toBeEnabled()
  await cancel.click()
  const progress = page.getByRole("region", {
    name: "Processing progress",
    exact: true,
  })
  await expect(
    progress.getByText("Cancellation requested", { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole("button", {
      name: "Cancellation requested",
      exact: true,
    }),
  ).toBeDisabled()
  await page.clock.runFor(5001)
  await expect(
    progress.getByText("Processing cancelled", { exact: true }),
  ).toBeVisible()
  await expect(
    progress.getByText("Cancellation requested", { exact: true }),
  ).toHaveCount(0)
  expect(cancels).toBe(1)
})

test("a false cancel acknowledgement stays unrequested", async ({ page }) => {
  let cancels = 0
  await mountActions(page, {
    progress: () => (route) => json(route, observation()),
    cancel: (route) => {
      cancels += 1
      return json(route, { analysis_id: analysis, cancel_requested: false })
    },
  })
  await page.goto(actionsUrl)
  const cancel = page.getByRole("button", {
    name: "Cancel bulk processing",
    exact: true,
  })
  await expect(cancel).toBeEnabled()
  await cancel.click()
  await expect(
    page.getByText("Cancellation requested", { exact: true }),
  ).toHaveCount(0)
  await expect(cancel).toBeEnabled()
  expect(cancels).toBe(1)
})

test("terminal success wins over a late local cancel acknowledgement", async ({
  page,
}) => {
  let reads = 0
  const replies = [
    observation(),
    observation({
      status: "SUCCEEDED",
      phase: "SUCCEEDED",
      files_completed: 4,
      lease_until: null,
    }),
  ]
  await mountActions(page, {
    progress: () => (route) => {
      const value = replies[Math.min(reads, replies.length - 1)]
      reads += 1
      return json(route, value)
    },
    cancel: (route) =>
      json(route, { analysis_id: analysis, cancel_requested: true }),
  })
  await page.clock.install()
  await page.goto(actionsUrl)
  await page
    .getByRole("button", { name: "Cancel bulk processing", exact: true })
    .click()
  await page.clock.runFor(5001)
  await expect(
    page.getByText("Progress status: Analysis completed"),
  ).toBeVisible()
  await expect(
    page.getByText("Cancellation requested", { exact: true }),
  ).toHaveCount(0)
  await expect(
    page.getByText("Processing cancelled", { exact: true }),
  ).toHaveCount(0)
})

test("a reconcile response for another task never replaces the fixed analysis", async ({
  page,
}) => {
  let reconciles = 0
  await mountActions(page, {
    progress: () => (route) => json(route, observation()),
    reconcile: (route) => {
      reconciles += 1
      return json(
        route,
        batch({
          ...identity(otherAnalysis),
          analysis_id: otherAnalysis,
          dataset_id: otherDataset,
          context_revision_id: otherContext,
        }),
      )
    },
  })
  await page.goto(actionsUrl)
  await page
    .getByRole("button", { name: "Reconcile original Analysis", exact: true })
    .click()
  await expect(
    page.getByRole("alert").filter({
      hasText: "Analysis action returned another task",
    }),
  ).toBeVisible()
  expect(reconciles).toBe(1)
  expect(new URL(page.url()).searchParams.get("analysis")).toBe(analysis)
  await expect(page.getByText("Phase: Normalizing input files")).toBeVisible()
})

test("a cancel response for another analysis is never acknowledged", async ({
  page,
}) => {
  await mountActions(page, {
    progress: () => (route) => json(route, observation()),
    cancel: (route) =>
      json(route, { analysis_id: otherAnalysis, cancel_requested: true }),
  })
  await page.goto(actionsUrl)
  await page
    .getByRole("button", { name: "Cancel bulk processing", exact: true })
    .click()
  await expect(
    page.getByRole("alert").filter({
      hasText: "Cancellation could not be confirmed",
    }),
  ).toBeVisible()
  await expect(
    page.getByText("Cancellation requested", { exact: true }),
  ).toHaveCount(0)
})

test("a held cancel success from the old analysis does not touch the new one", async ({
  page,
}) => {
  let release: () => void = () => {}
  let requested: () => void = () => {}
  const waiting = new Promise<void>((resolve) => {
    requested = resolve
  })
  const released = new Promise<void>((resolve) => {
    release = resolve
  })
  await mountActions(page, {
    progress: (id) => (route) =>
      json(
        route,
        id === otherAnalysis
          ? observation({
              ...identity(otherAnalysis),
              analysis_id: otherAnalysis,
              dataset_id: otherDataset,
              context_revision_id: otherContext,
              phase: "COMPUTING",
            })
          : observation(),
      ),
    cancel: async (route) => {
      requested()
      await released
      return json(route, { analysis_id: analysis, cancel_requested: true })
    },
  })
  await page.goto(actionsUrl)
  await page
    .getByRole("button", { name: "Cancel bulk processing", exact: true })
    .click()
  await waiting
  await page
    .getByRole("combobox", { name: "Analysis", exact: true })
    .selectOption(otherAnalysis)
  await expect(page).toHaveURL(new RegExp(`analysis=${otherAnalysis}`))
  release()
  await expect(page.getByText("Phase: Computing results")).toBeVisible()
  await expect(
    page.getByText("Cancellation requested", { exact: true }),
  ).toHaveCount(0)
  await expect(
    page.getByRole("button", { name: "Cancel bulk processing", exact: true }),
  ).toBeEnabled()
})

test("a held cancel error from the old analysis does not touch the new one", async ({
  page,
}) => {
  let release: () => void = () => {}
  let requested: () => void = () => {}
  const waiting = new Promise<void>((resolve) => {
    requested = resolve
  })
  const released = new Promise<void>((resolve) => {
    release = resolve
  })
  await mountActions(page, {
    progress: (id) => (route) =>
      json(
        route,
        id === otherAnalysis
          ? observation({
              ...identity(otherAnalysis),
              analysis_id: otherAnalysis,
              dataset_id: otherDataset,
              context_revision_id: otherContext,
              phase: "COMPUTING",
            })
          : observation(),
      ),
    cancel: async (route) => {
      requested()
      await released
      return route.abort("failed")
    },
  })
  await page.goto(actionsUrl)
  await page
    .getByRole("button", { name: "Cancel bulk processing", exact: true })
    .click()
  await waiting
  await page
    .getByRole("combobox", { name: "Analysis", exact: true })
    .selectOption(otherAnalysis)
  await expect(page).toHaveURL(new RegExp(`analysis=${otherAnalysis}`))
  release()
  await expect(page.getByText("Phase: Computing results")).toBeVisible()
  await expect(
    page.getByRole("alert").filter({
      hasText: "Cancellation could not be confirmed",
    }),
  ).toHaveCount(0)
  await expect(
    page.getByText("Cancellation requested", { exact: true }),
  ).toHaveCount(0)
  await expect(
    page.getByRole("button", { name: "Cancel bulk processing", exact: true }),
  ).toBeEnabled()
})

test("a held progress read from the old analysis never replaces the new phase", async ({
  page,
}) => {
  let release: () => void = () => {}
  let requested: () => void = () => {}
  const waiting = new Promise<void>((resolve) => {
    requested = resolve
  })
  const released = new Promise<void>((resolve) => {
    release = resolve
  })
  await mountActions(page, {
    progress: (id) => async (route) => {
      if (id === analysis) {
        requested()
        await released
        return json(route, observation({ phase: "NORMALIZING" }))
      }
      return json(
        route,
        observation({
          ...identity(otherAnalysis),
          analysis_id: otherAnalysis,
          dataset_id: otherDataset,
          context_revision_id: otherContext,
          phase: "COMPUTING",
        }),
      )
    },
  })
  await page.goto(actionsUrl)
  await waiting
  await page
    .getByRole("combobox", { name: "Analysis", exact: true })
    .selectOption(otherAnalysis)
  await expect(page).toHaveURL(new RegExp(`analysis=${otherAnalysis}`))
  release()
  await expect(page.getByText("Phase: Computing results")).toBeVisible()
  await expect(page.getByText("Phase: Normalizing input files")).toHaveCount(0)
})

test("audit same-task metadata refresh retains verified progress during transient errors", async ({
  page,
}) => {
  let reads = 0
  const mounted = await mountResults(page, {
    progress: () => (route) => {
      reads += 1
      return reads === 1
        ? json(route, observation())
        : json(route, { detail: "temporary" }, 503)
    },
  })
  await page.clock.install()
  await page.goto(resultsUrl)
  await expect(page.getByText("Phase: Normalizing input files")).toBeVisible()
  mounted.setBatch(
    batch({ quality: { worker_heartbeat: "2026-01-01T00:00:10Z" } }),
  )
  await page.clock.runFor(5001)
  await page.clock.runFor(5001)
  await expect(page.getByText("Phase: Normalizing input files")).toBeVisible()
  await expect(
    page.getByText(
      "The last verified progress is shown; the latest read failed.",
      { exact: true },
    ),
  ).toBeVisible()
})
