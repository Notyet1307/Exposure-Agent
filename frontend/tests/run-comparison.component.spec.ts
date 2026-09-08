import type {
  GovernanceRunPublic,
  GovernanceRunSourcePublic,
  GovernanceRunSourcesPublic,
  GovernanceRunsPublic,
  IPSourceComparisonPublic,
  IPSourceComparisonsPublic,
} from "../src/client"
import { expect, type Page, type Route, test } from "./fixtures"

const projectId = "00000000-0000-0000-0000-000000000001"
const otherProjectId = "00000000-0000-0000-0000-000000000002"
const oldRunId = "60000000-0000-0000-0000-000000000001"
const newRunId = "60000000-0000-0000-0000-000000000002"
const completedAt = "2026-07-30T13:01:00Z"
const hash = "a".repeat(64)
const comparisonPath = (project = projectId, run = oldRunId) =>
  `/projects/${project}/runs/${run}/comparison`

// These are browser presentation tests with controlled API responses, not
// backend end-to-end evidence. Generated types keep the published shapes real.
function publishedRun({
  project = projectId,
  run = oldRunId,
  netflow = "absent",
  size = netflow === "absent" ? 3 : 4,
}: {
  project?: string
  run?: string
  netflow?: "absent" | "positive" | "zero"
  size?: number
} = {}) {
  const reportId = run.replace(/^6/, "9")
  const reportVersion =
    netflow === "absent" ? "deterministic-report-v1" : "deterministic-report-v2"
  const sources: GovernanceRunSourcesPublic = {
    project_id: project,
    governance_run_id: run,
    governance_report_id: reportId,
    run_status: "COMPLETED",
    completed_at: completedAt,
    input_contract_version: "governance-run-input-v1",
    processing_contract_version: "ip-v1",
    report_contract_version: reportVersion,
    sources: (["CUSTOMER_UPLOAD", "CLOUDATLAS", "NETFLOW"] as const).map(
      (source_type, index): GovernanceRunSourcePublic => {
        const absent = source_type === "NETFLOW" && netflow === "absent"
        return {
          source_type,
          state: absent ? "ABSENT" : "PRESENT",
          snapshot_id: absent
            ? null
            : `70000000-0000-0000-0000-00000000000${index + 1}`,
          input_id: absent
            ? null
            : `80000000-0000-0000-0000-00000000000${index + 1}`,
          content_sha256: absent ? null : hash,
          schema_fingerprint: absent ? null : hash,
          method_fingerprint: source_type === "CLOUDATLAS" ? hash : null,
          record_count: absent
            ? null
            : source_type === "NETFLOW" && netflow === "zero"
              ? 0
              : 3,
          valid_time_start_utc: absent ? null : "2026-07-30T12:00:00Z",
          valid_time_end_utc: absent ? null : completedAt,
        }
      },
    ),
  }
  const classifications = [
    "matched",
    "customer_upload_only",
    "cloudatlas_only",
    "neither_source_observed",
  ] as const
  const data: IPSourceComparisonPublic[] = Array.from(
    { length: size },
    (_, index) => {
      const classification = classifications[index % classifications.length]
      const active =
        netflow === "positive" && (index % 4 === 0 || index % 4 === 3)
      return {
        resource_id: `a0000000-0000-0000-0000-${String(index + 1).padStart(12, "0")}`,
        canonical_ip: `192.0.2.${index + 1}`,
        customer_upload_present:
          classification === "matched" ||
          classification === "customer_upload_only",
        cloudatlas_present:
          classification === "matched" || classification === "cloudatlas_only",
        netflow_status: active ? "ACTIVE" : "UNKNOWN",
        classification,
        classification_reason: classification,
        netflow_reason:
          netflow === "absent"
            ? "netflow_input_absent"
            : active
              ? "positive_activity_evidence"
              : "no_positive_activity_evidence",
        content_hash: hash,
      }
    },
  )
  const comparisons: IPSourceComparisonsPublic = {
    project_id: project,
    governance_run_id: run,
    governance_report_id: reportId,
    report_contract_version: reportVersion,
    contract_version: "ip-source-comparison/v1",
    output_hash: hash,
    data,
    count: data.length,
    page_size: 25,
  }
  return { sources, comparisons }
}

type PublishedRun = {
  sources: GovernanceRunSourcesPublic
  comparisons: IPSourceComparisonsPublic
}

function runSummary(run: PublishedRun): GovernanceRunPublic {
  return {
    id: run.sources.governance_run_id,
    trigger_id: run.sources.governance_run_id,
    session_id: hash,
    status: "COMPLETED",
    customer_upload_id: "80000000-0000-0000-0000-000000000001",
    customer_upload_sha256: hash,
    customer_upload_profile_id: "10000000-0000-0000-0000-000000000001",
    customer_upload_profile_version: 1,
    source_instance_id: "80000000-0000-0000-0000-000000000002",
    cloudatlas_validated_fingerprint: hash,
    cloudatlas_capset_id: "cloudatlas-readonly",
    cloudatlas_method: "cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets",
    package_sha256: hash,
    descriptor_sha256: hash,
    runner_build_version: "runner-v1",
    processing_contract_version: "ip-v1",
    created_at: "2026-07-30T13:00:00Z",
    completed_at: completedAt,
    session_terminal_at: completedAt,
    session_recovery_code: null,
    steps: [],
    snapshots: [],
  }
}

async function installMocks(page: Page, runs: PublishedRun[]) {
  const requests: URL[] = []
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "component-token")
  })
  await page.route("**/api/v1/users/me", (route) =>
    route.fulfill({
      json: {
        email: "operator@example.com",
        full_name: "Test Operator",
        id: "30000000-0000-0000-0000-000000000001",
        is_active: true,
        is_superuser: false,
      },
    }),
  )
  await page.route("**/api/v1/projects/**", async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === "/api/v1/projects/") {
      await route.fulfill({
        json: {
          data: [projectId, otherProjectId].map((id, index) => ({
            id,
            name: index === 0 ? "North Plant" : "South Plant",
            tenant_id: "00000000-0000-0000-0000-000000000010",
            created_at: completedAt,
            updated_at: completedAt,
            archived_at: null,
          })),
          count: 2,
        },
      })
      return
    }
    const match = url.pathname.match(
      /\/projects\/([^/]+)\/governance-runs\/([^/]+)\/(sources|ip-source-comparisons)$/,
    )
    if (match) {
      requests.push(url)
      const run = runs.find(
        (candidate) =>
          candidate.sources.project_id === match[1] &&
          candidate.sources.governance_run_id === match[2],
      )
      if (!run) {
        await route.fulfill({ status: 404, json: { detail: "Run not found" } })
      } else if (match[3] === "sources") {
        await route.fulfill({ json: run.sources })
      } else {
        const data = run.comparisons.data.filter(
          (row) =>
            (!url.searchParams.has("classification") ||
              row.classification === url.searchParams.get("classification")) &&
            (!url.searchParams.has("netflow_status") ||
              row.netflow_status === url.searchParams.get("netflow_status")),
        )
        const skip = Number(url.searchParams.get("skip") ?? 0)
        const limit = Number(url.searchParams.get("limit") ?? 25)
        await route.fulfill({
          json: {
            ...run.comparisons,
            data: data.slice(skip, skip + limit),
            count: data.length,
            page_size: limit,
          } satisfies IPSourceComparisonsPublic,
        })
      }
      return
    }
    if (url.pathname.endsWith("/governance-runs")) {
      const data = runs
        .filter((run) =>
          url.pathname.includes(`/projects/${run.sources.project_id}/`),
        )
        .map(runSummary)
        .reverse()
      await route.fulfill({
        json: {
          data,
          count: data.length,
          can_trigger: false,
          ready: false,
          readiness_code: "run_customer_upload_not_ready",
          launch_blocking_code: null,
        } satisfies GovernanceRunsPublic,
      })
      return
    }
    if (url.pathname.endsWith("/customer-upload-profile")) {
      await route.fulfill({
        json: {
          id: "10000000-0000-0000-0000-000000000001",
          version: 1,
          required_headers: ["资产IP"],
          warning_headers: [],
          optional_headers: [],
        },
      })
      return
    }
    if (url.pathname.endsWith("/customer-uploads")) {
      await route.fulfill({
        json: {
          data: [],
          count: 0,
          current_customer_upload_id: null,
          can_upload: false,
          can_select: false,
        },
      })
      return
    }
    if (url.pathname.endsWith("/netflow-datasets")) {
      await route.fulfill({
        json: {
          data: [],
          count: 0,
          current_netflow_dataset_id: null,
          current_netflow_dataset: null,
          can_upload: false,
          can_select: false,
        },
      })
      return
    }
    if (url.pathname.endsWith("/cloudatlas-source-instances")) {
      await route.fulfill({ json: { data: [], count: 0, can_manage: false } })
      return
    }
    await route.fallback()
  })
  return requests
}

const sourceOverview = (page: Page) =>
  page.getByRole("region", { name: "Source overview", exact: true })
const matrix = (page: Page) =>
  page.getByRole("region", { name: "IP source comparison", exact: true })
const netflowCard = (page: Page) =>
  sourceOverview(page).getByRole("region", { name: "NetFlow", exact: true })
const tableRow = (page: Page, ip: string) =>
  matrix(page)
    .getByRole("row")
    .filter({ has: page.getByRole("cell", { name: ip, exact: true }) })
const comparisonRequests = (requests: URL[]) =>
  requests.filter((url) => url.pathname.endsWith("/ip-source-comparisons"))

function responseGate() {
  let release = () => {}
  const ready = new Promise<void>((resolve) => {
    release = resolve
  })
  return { release: () => release(), ready }
}

test("opens an explicit historical Run from Runs while a newer Run exists", async ({
  page,
}) => {
  const oldRun = publishedRun()
  const requests = await installMocks(page, [
    oldRun,
    publishedRun({ run: newRunId, netflow: "positive" }),
  ])
  await page.goto("/")
  await page.getByRole("tab", { name: "Runs", exact: true }).click()
  await page.locator(`a[href="${comparisonPath()}"]`).click()
  await expect(page).toHaveURL(new RegExp(`${comparisonPath()}$`))
  await expect(
    page.getByRole("heading", { level: 1, name: "Run source comparison" }),
  ).toBeVisible()
  await expect(
    page.getByText(`Report ID: ${oldRun.sources.governance_report_id}`, {
      exact: true,
    }),
  ).toBeVisible()
  await expect(
    page.getByText(`Run ID: ${oldRunId}`, { exact: true }),
  ).toBeVisible()
  await expect(
    netflowCard(page).getByText("ABSENT", { exact: true }),
  ).toBeVisible()
  await expect(tableRow(page, "192.0.2.1")).toContainText(
    "netflow_input_absent",
  )
  await expect(
    tableRow(page, "192.0.2.1").getByRole("cell", {
      name: "Observed",
      exact: true,
    }),
  ).toHaveCount(2)
  await expect(tableRow(page, "192.0.2.2")).toContainText("Not observed")
  await expect(matrix(page)).not.toContainText("no_positive_activity_evidence")
  await expect(matrix(page).getByRole("cell", { name: /^ACTIVE/ })).toHaveCount(
    0,
  )
  expect(
    requests.every((url) =>
      url.pathname.includes(`/governance-runs/${oldRunId}/`),
    ),
  ).toBe(true)
  await page.reload()
  await expect(
    netflowCard(page).getByText("ABSENT", { exact: true }),
  ).toBeVisible()
  expect(
    requests.every((url) =>
      url.pathname.includes(`/governance-runs/${oldRunId}/`),
    ),
  ).toBe(true)
})

test("shows three-source ACTIVE and UNKNOWN evidence without conflating observation", async ({
  page,
}) => {
  await installMocks(page, [publishedRun({ netflow: "positive" })])
  await page.goto(comparisonPath())
  for (const source of ["CustomerUpload", "CloudAtlas", "NetFlow"]) {
    await expect(
      sourceOverview(page).getByRole("heading", { name: source, exact: true }),
    ).toBeVisible()
  }
  await expect(
    sourceOverview(page).getByText("PRESENT", { exact: true }),
  ).toHaveCount(3)
  for (const heading of [
    "Canonical IP",
    "CustomerUpload",
    "CloudAtlas",
    "NetFlow",
    "Classification",
  ]) {
    await expect(
      matrix(page).getByRole("columnheader", { name: heading, exact: true }),
    ).toBeVisible()
  }
  await expect(
    page.getByRole("combobox", { name: "Classification" }).getByRole("option"),
  ).toHaveText([
    "All classifications",
    "matched",
    "customer_upload_only",
    "cloudatlas_only",
    "neither_source_observed",
  ])
  await expect(
    page.getByRole("combobox", { name: "NetFlow status" }).getByRole("option"),
  ).toHaveText(["All NetFlow statuses", "ACTIVE", "UNKNOWN"])
  await expect(tableRow(page, "192.0.2.1")).toContainText("ACTIVE")
  await expect(tableRow(page, "192.0.2.2")).toContainText("UNKNOWN")
  await expect(tableRow(page, "192.0.2.2")).toContainText(
    "no_positive_activity_evidence",
  )
  await expect(tableRow(page, "192.0.2.4")).toContainText(
    "neither_source_observed",
  )
  await expect(
    tableRow(page, "192.0.2.4").getByRole("cell", {
      name: "Not observed",
      exact: true,
    }),
  ).toHaveCount(2)
  await expect(tableRow(page, "192.0.2.4")).toContainText("ACTIVE")
  await expect(matrix(page)).toContainText(/UNKNOWN[\s\S]*does not/i)
  await expect(matrix(page)).toContainText(/zero traffic/i)
  await expect(matrix(page)).toContainText(/zero risk/i)
})

test("keeps a zero-record NetFlow input PRESENT with UNKNOWN activity", async ({
  page,
}) => {
  await installMocks(page, [publishedRun({ netflow: "zero" })])
  await page.goto(comparisonPath())
  await expect(
    netflowCard(page).getByText("PRESENT", { exact: true }),
  ).toBeVisible()
  await expect(netflowCard(page).getByText("0", { exact: true })).toBeVisible()
  await expect(netflowCard(page)).not.toContainText("ABSENT")
  await expect(tableRow(page, "192.0.2.1")).toContainText("UNKNOWN")
  await expect(tableRow(page, "192.0.2.1")).toContainText(
    "no_positive_activity_evidence",
  )
  await expect(matrix(page)).not.toContainText("netflow_input_absent")
})

test("preserves URL filters across reload and history and resets pagination on either filter", async ({
  page,
}) => {
  const requests = await installMocks(page, [
    publishedRun({ netflow: "positive", size: 60 }),
  ])
  await page.goto(`${comparisonPath()}?netflow_status=UNKNOWN&page=2`)
  const classification = page.getByRole("combobox", {
    name: "Classification",
    exact: true,
  })
  const netflow = page.getByRole("combobox", {
    name: "NetFlow status",
    exact: true,
  })
  const pagination = page.getByRole("navigation", {
    name: "Comparison pagination",
  })
  await expect(netflow).toHaveValue("UNKNOWN")
  await expect(pagination).toContainText("Page 2 of 2")
  await expect(tableRow(page, "192.0.2.51")).toBeVisible()
  const selectedScope = page.url()
  await page
    .getByRole("combobox", { name: "Language / 语言" })
    .selectOption("zh-CN")
  await expect(
    page.getByRole("combobox", { name: "NetFlow 状态", exact: true }),
  ).toHaveValue("UNKNOWN")
  await expect(
    page.getByRole("navigation", { name: "比较分页" }),
  ).toContainText("第 2 页")
  await expect(
    page.getByRole("cell", { name: "192.0.2.51", exact: true }),
  ).toBeVisible()
  await expect(page).toHaveURL(selectedScope)
  await page
    .getByRole("combobox", { name: "Language / 语言" })
    .selectOption("en")
  await expect(netflow).toHaveValue("UNKNOWN")
  await expect(pagination).toContainText("Page 2 of 2")
  expect(comparisonRequests(requests).at(-1)?.searchParams.get("skip")).toBe(
    "25",
  )
  expect(comparisonRequests(requests).at(-1)?.searchParams.get("limit")).toBe(
    "25",
  )
  await page.reload()
  await expect(netflow).toHaveValue("UNKNOWN")
  await expect(pagination).toContainText("Page 2 of 2")
  await classification.selectOption("customer_upload_only")
  await expect(page).toHaveURL(
    (url) =>
      url.searchParams.get("classification") === "customer_upload_only" &&
      !url.searchParams.has("page"),
  )
  await expect(tableRow(page, "192.0.2.2")).toBeVisible()
  await expect(pagination).toHaveCount(0)
  expect(comparisonRequests(requests).at(-1)?.searchParams.get("skip")).toBe(
    "0",
  )
  await page.goBack()
  await expect(classification).toHaveValue("")
  await expect(netflow).toHaveValue("UNKNOWN")
  await expect(pagination).toContainText("Page 2 of 2")
  await page.goForward()
  await expect(classification).toHaveValue("customer_upload_only")
  await expect(tableRow(page, "192.0.2.2")).toBeVisible()
  await classification.selectOption("")
  await pagination.getByRole("button", { name: "Next", exact: true }).click()
  await expect(page).toHaveURL((url) => url.searchParams.get("page") === "2")
  await expect(pagination).toContainText("Page 2 of 2")
  await netflow.selectOption("ACTIVE")
  await expect(page).toHaveURL(
    (url) =>
      url.searchParams.get("netflow_status") === "ACTIVE" &&
      !url.searchParams.has("page"),
  )
  await expect(tableRow(page, "192.0.2.1")).toBeVisible()
  expect(comparisonRequests(requests).at(-1)?.searchParams.get("skip")).toBe(
    "0",
  )
  await netflow.selectOption("")
  await expect(pagination).toContainText("Page 1 of 3")
  await expect(
    pagination.getByRole("button", { name: "Previous" }),
  ).toBeDisabled()
  await pagination.getByRole("button", { name: "Next" }).click()
  await expect(tableRow(page, "192.0.2.26")).toBeVisible()
  await expect(pagination).toContainText("Page 2 of 3")
  await pagination.getByRole("button", { name: "Next" }).click()
  await expect(tableRow(page, "192.0.2.51")).toBeVisible()
  await expect(pagination).toContainText("Page 3 of 3")
  await expect(pagination.getByRole("button", { name: "Next" })).toBeDisabled()
  expect(comparisonRequests(requests).at(-1)?.searchParams.get("skip")).toBe(
    "50",
  )
  expect(
    requests.every((url) =>
      url.pathname.includes(
        `/projects/${projectId}/governance-runs/${oldRunId}/`,
      ),
    ),
  ).toBe(true)
})

test("normalizes invalid URL search values without forwarding them to the API", async ({
  page,
}) => {
  const requests = await installMocks(page, [publishedRun()])
  for (const invalidPage of ["-2", "1.5", "nope"]) {
    await page.goto(
      `${comparisonPath()}?classification=invalid&netflow_status=ABSENT&page=${invalidPage}`,
    )
    await expect(tableRow(page, "192.0.2.1")).toBeVisible()
    await expect(
      page.getByRole("combobox", { name: "Classification" }),
    ).toHaveValue("")
    await expect(
      page.getByRole("combobox", { name: "NetFlow status" }),
    ).toHaveValue("")
    const query = comparisonRequests(requests).at(-1)?.searchParams
    expect(query?.get("classification")).toBeNull()
    expect(query?.get("netflow_status")).toBeNull()
    expect(query?.get("skip")).toBe("0")
  }
})

for (const size of [0, 30]) {
  test(`recovers an out-of-range page for ${size} matching records`, async ({
    page,
  }) => {
    const requests = await installMocks(page, [
      publishedRun({ netflow: "positive", size }),
    ])
    await page.goto(`${comparisonPath()}?page=99`)
    const expectedPage = size === 0 ? null : "2"
    await expect(page).toHaveURL(
      (url) => url.searchParams.get("page") === expectedPage,
    )
    if (size === 0) {
      await expect(matrix(page).getByRole("status")).toContainText(
        "No IP source comparisons",
      )
    } else {
      await expect(tableRow(page, "192.0.2.26")).toBeVisible()
      await expect(
        page.getByRole("navigation", { name: "Comparison pagination" }),
      ).toContainText("Page 2 of 2")
    }
    expect(
      comparisonRequests(requests).map((url) => url.searchParams.get("skip")),
    ).toEqual(["2450", size === 0 ? "0" : "25"])
  })
}

test("announces loading and an empty matrix without inventing source absence", async ({
  page,
}) => {
  await installMocks(page, [publishedRun({ netflow: "zero", size: 0 })])
  const gate = responseGate()
  await page.route(
    "**/governance-runs/*/ip-source-comparisons?*",
    async (route) => {
      await gate.ready
      await route.fallback()
    },
  )
  await page.goto(comparisonPath())
  await expect(page.getByRole("status")).toContainText(/loading/i)
  await expect(matrix(page).getByRole("row")).toHaveCount(0)
  gate.release()
  await expect(matrix(page).getByRole("status")).toContainText(
    /no .*comparisons|no .*match|no .*results|no .*IP/i,
  )
  await expect(
    netflowCard(page).getByText("PRESENT", { exact: true }),
  ).toBeVisible()
  await expect(matrix(page).getByRole("alert")).toHaveCount(0)
  await expect(matrix(page).getByRole("navigation")).toHaveCount(0)
})

for (const endpoint of ["sources", "ip-source-comparisons"] as const) {
  for (const status of [404, 500]) {
    test(`${endpoint} ${status} stays an error, never ABSENT or UNKNOWN, and retry recovers`, async ({
      page,
    }) => {
      await installMocks(page, [publishedRun({ netflow: "positive" })])
      let failing = true
      const match = new RegExp(
        `/governance-runs/${oldRunId}/${endpoint}(?:\\?.*)?$`,
      )
      await page.route(match, async (route: Route) => {
        if (failing) {
          await route.fulfill({
            status,
            json: {
              detail:
                status === 404 ? "Run not found" : "Internal Server Error",
            },
          })
        } else {
          await route.fallback()
        }
      })
      await page.goto(comparisonPath())
      await expect(page.getByRole("alert").first()).toBeVisible({
        timeout: 15000,
      })
      await expect(
        sourceOverview(page).getByText("ABSENT", { exact: true }),
      ).toHaveCount(0)
      await expect(matrix(page).getByRole("cell")).toHaveCount(0)
      await expect(matrix(page)).not.toContainText("netflow_input_absent")
      await expect(matrix(page)).not.toContainText(
        "no_positive_activity_evidence",
      )
      await expect(page).toHaveURL(new RegExp(`${comparisonPath()}$`))
      failing = false
      await page
        .getByRole("button", { name: "Try again", exact: true })
        .first()
        .click()
      await expect(
        netflowCard(page).getByText("PRESENT", { exact: true }),
      ).toBeVisible()
      await expect(tableRow(page, "192.0.2.1")).toContainText("ACTIVE")
      await expect(page.getByRole("alert")).toHaveCount(0)
    })
  }
}

test("rejects mismatched published Report identities instead of combining facts", async ({
  page,
}) => {
  const run = publishedRun({ netflow: "positive" })
  await installMocks(page, [run])
  await page.route("**/governance-runs/*/ip-source-comparisons?*", (route) =>
    route.fulfill({
      json: {
        ...run.comparisons,
        governance_report_id: newRunId.replace(/^6/, "9"),
      } satisfies IPSourceComparisonsPublic,
    }),
  )
  await page.goto(comparisonPath())
  await expect(page.getByRole("alert")).toContainText(/identity mismatch/i)
  await expect(matrix(page).getByRole("cell")).toHaveCount(0)
  await expect(netflowCard(page)).toHaveCount(0)
  await expect(page).toHaveURL(new RegExp(`${comparisonPath()}$`))
})

for (const targetProject of [projectId, otherProjectId]) {
  test(`ignores delayed old Run responses when switching ${targetProject === projectId ? "Run" : "Project and Run"}`, async ({
    page,
  }) => {
    const oldRun = publishedRun()
    const newRun = publishedRun({
      project: targetProject,
      run: newRunId,
      netflow: "positive",
    })
    newRun.comparisons.data[0].canonical_ip = "203.0.113.99"
    await installMocks(page, [oldRun, newRun])
    const gate = responseGate()
    let pending = 0
    await page.route(
      new RegExp(
        `/projects/${projectId}/governance-runs/${oldRunId}/(sources|ip-source-comparisons)(?:\\?.*)?$`,
      ),
      async (route) => {
        pending += 1
        await gate.ready
        await route.fallback()
      },
    )
    await page.goto("/")
    await page.getByRole("tab", { name: "Runs", exact: true }).click()
    await page.locator(`a[href="${comparisonPath()}"]`).click()
    await expect(page.getByRole("status")).toContainText(/loading/i)
    await expect.poll(() => pending).toBe(2)
    await page.goBack()
    if (targetProject !== projectId) {
      await page.getByRole("combobox", { name: "Project", exact: true }).click()
      await page
        .getByRole("option", { name: "South Plant", exact: true })
        .click()
    }
    await page.getByRole("tab", { name: "Runs", exact: true }).click()
    await page
      .locator(`a[href="${comparisonPath(targetProject, newRunId)}"]`)
      .click()
    await expect(tableRow(page, "203.0.113.99")).toBeVisible()
    const oldResponses = Promise.all([
      page.waitForResponse((response) =>
        response.url().includes(`/governance-runs/${oldRunId}/sources`),
      ),
      page.waitForResponse((response) =>
        response
          .url()
          .includes(`/governance-runs/${oldRunId}/ip-source-comparisons`),
      ),
    ])
    gate.release()
    await Promise.all(
      (await oldResponses).map((response) => response.finished()),
    )
    await expect(page).toHaveURL(
      new RegExp(`${comparisonPath(targetProject, newRunId)}$`),
    )
    await expect(
      netflowCard(page).getByText("PRESENT", { exact: true }),
    ).toBeVisible()
    await expect(tableRow(page, "203.0.113.99")).toBeVisible()
    await expect(tableRow(page, "192.0.2.1")).toHaveCount(0)
    await expect(
      page.getByText(`Report ID: ${oldRun.sources.governance_report_id}`, {
        exact: true,
      }),
    ).toHaveCount(0)
    await expect(
      page.getByText(`Report ID: ${newRun.sources.governance_report_id}`, {
        exact: true,
      }),
    ).toBeVisible()
  })
}

test("keeps narrow-screen content contained and the matrix keyboard-scrollable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await installMocks(page, [publishedRun({ netflow: "positive" })])
  await page.goto(comparisonPath())
  const scrollRegion = page.getByRole("region", {
    name: "IP source comparison table",
    exact: true,
  })
  await expect(scrollRegion).toBeVisible()
  await expect(scrollRegion).toHaveAttribute("tabindex", "0")
  await expect(
    page.getByRole("combobox", { name: "Classification" }),
  ).toBeVisible()
  await expect(
    page.getByRole("combobox", { name: "NetFlow status" }),
  ).toBeVisible()
  for (const name of ["CustomerUpload", "CloudAtlas", "NetFlow"]) {
    await expect(
      sourceOverview(page).getByRole("heading", { name, exact: true }),
    ).toBeVisible()
  }
  const headings = await Promise.all(
    ["CustomerUpload", "CloudAtlas", "NetFlow"].map((name) =>
      sourceOverview(page)
        .getByRole("heading", { name, exact: true })
        .boundingBox(),
    ),
  )
  expect(headings[0]?.x).toBe(headings[1]?.x)
  expect(headings[1]?.x).toBe(headings[2]?.x)
  expect(headings[0]!.y).toBeLessThan(headings[1]!.y)
  expect(headings[1]!.y).toBeLessThan(headings[2]!.y)
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true)
  expect(
    await scrollRegion.evaluate(
      (element) => element.scrollWidth > element.clientWidth,
    ),
  ).toBe(true)
  await scrollRegion.focus()
  await expect(scrollRegion).toBeFocused()
  await page.keyboard.press("ArrowRight")
  await expect
    .poll(() => scrollRegion.evaluate((element) => element.scrollLeft))
    .toBeGreaterThan(0)
})
