import type { FindingDetailPublic, ManualReviewPublic } from "../src/client"
import { expect, test } from "./fixtures"

const projectId = "00000000-0000-0000-0000-000000000001"
const resourceId = "80000000-0000-0000-0000-000000000001"
const findingId = "90000000-0000-0000-0000-000000000001"
const customerSnapshotId = "70000000-0000-0000-0000-000000000001"
const cloudatlasSnapshotId = "70000000-0000-0000-0000-000000000002"

const sourceSnapshots = [
  {
    id: customerSnapshotId,
    source_type: "CUSTOMER_UPLOAD",
    content_sha256: "a".repeat(64),
    schema_fingerprint: "b".repeat(64),
    method_fingerprint: null,
    record_count: 1,
    created_at: "2026-07-30T12:00:00Z",
  },
  {
    id: cloudatlasSnapshotId,
    source_type: "CLOUDATLAS",
    content_sha256: "c".repeat(64),
    schema_fingerprint: "d".repeat(64),
    method_fingerprint: "e".repeat(64),
    record_count: 1,
    created_at: "2026-07-30T12:00:01Z",
  },
]

const observation = {
  id: "a0000000-0000-0000-0000-000000000001",
  source_type: "CUSTOMER_UPLOAD",
  source_record_key: "row:2",
  raw_ip: " 192.0.2.10 ",
  canonical_ip: "192.0.2.10",
  cloudatlas_asset_id: null,
  cloudatlas_status: null,
  source_snapshot_id: customerSnapshotId,
}

const cloudatlasObservation = {
  ...observation,
  id: "a0000000-0000-0000-0000-000000000002",
  source_type: "CLOUDATLAS",
  source_record_key: "page:1:item:0",
  raw_ip: "192.0.2.10",
  cloudatlas_asset_id: "atlas-1",
  cloudatlas_status: "valid",
  source_snapshot_id: cloudatlasSnapshotId,
}

const findingSummary = {
  id: findingId,
  resource_id: resourceId,
  finding_type: "UNOBSERVED_ASSET",
  status: "OPEN",
  canonical_ip: "192.0.2.10",
  first_detected_at: "2026-07-30T12:00:00Z",
  last_detected_at: "2026-07-30T12:00:00Z",
  latest_occurrence_at: "2026-07-30T12:00:00Z",
  latest_occurrence_run_id: "60000000-0000-0000-0000-000000000001",
  latest_transition_at: "2026-07-30T12:00:00Z",
  occurrence_count: 1,
  transition_count: 1,
}

// Controlled detail responses exercise presentation only; published-fact
// integrity and real API-backed scenarios are covered separately.
const findingDetail = {
  ...findingSummary,
  occurrences: [
    {
      id: "b0000000-0000-0000-0000-000000000001",
      governance_run_id: "60000000-0000-0000-0000-000000000001",
      created_at: "2026-07-30T12:00:00Z",
      observation_ids: [observation.id],
      source_snapshot_ids: [customerSnapshotId, cloudatlasSnapshotId],
      source_snapshots: sourceSnapshots,
      observations: [observation],
    },
  ],
  transitions: [
    {
      id: "c0000000-0000-0000-0000-000000000001",
      governance_run_id: "60000000-0000-0000-0000-000000000001",
      transition_type: "OPENED",
      created_at: "2026-07-30T12:00:00Z",
      observation_ids: [observation.id],
      source_snapshot_ids: [customerSnapshotId, cloudatlasSnapshotId],
      source_snapshots: sourceSnapshots,
      observations: [observation],
    },
  ],
  netflow_context: {
    governance_run_id: "60000000-0000-0000-0000-000000000001",
    status: "INPUT_UNMODELED",
    activity: null,
  } satisfies FindingDetailPublic["netflow_context"],
}

const positiveNetflowContext = {
  governance_run_id: "60000000-0000-0000-0000-000000000002",
  status: "POSITIVE_ACTIVITY",
  activity: {
    activity_id: "d0000000-0000-0000-0000-000000000001",
    source_snapshot_id: "70000000-0000-0000-0000-000000000003",
    aggregation_contract_version: "netflow-ip-activity-v1",
    content_sha256: "abcdef0123456789".repeat(4),
    flow_count: 1,
    first_seen_utc: "2026-07-31T01:02:03Z",
    last_seen_utc: "2026-07-31T04:05:06Z",
  },
} satisfies FindingDetailPublic["netflow_context"]

const findingDetailUrl = new RegExp(
  `/api/v1/projects/${projectId}/findings/${findingId}(?:\\?.*)?$`,
)

async function installBaseMocks(page: import("@playwright/test").Page) {
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
          data: [
            {
              name: "North Plant",
              id: projectId,
              tenant_id: "00000000-0000-0000-0000-000000000010",
              created_at: "2026-07-30T10:00:00Z",
              updated_at: "2026-07-30T10:00:00Z",
              archived_at: null,
            },
          ],
          count: 1,
        },
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
    if (
      url.pathname.endsWith("/governance-reports") &&
      route.request().method() === "GET"
    ) {
      await route.fulfill({
        json: {
          data: [],
          count: 0,
          page_size: 50,
          next_cursor: null,
          compatible: true,
          compatibility_code: null,
          latest_completed_run_id: null,
          latest_completed_run_at: null,
        },
      })
      return
    }
    if (url.pathname.endsWith("/governance-runs")) {
      await route.fulfill({
        json: {
          data: [],
          count: 0,
          can_trigger: false,
          ready: false,
          readiness_code: "run_customer_upload_not_ready",
          launch_blocking_code: null,
        },
      })
      return
    }
    await route.fallback()
  })
}

async function installResultMocks(page: import("@playwright/test").Page) {
  await page.route(
    new RegExp(`/api/v1/projects/${projectId}/manual-reviews(?:\\?.*)?$`),
    (route) =>
      route.fulfill({ json: { data: [], count: 0, can_create: true } }),
  )
  await page.route(
    new RegExp(`/api/v1/projects/${projectId}/ai-investigations(?:\\?.*)?$`),
    (route) =>
      route.fulfill({ json: { data: [], count: 0, can_create: true } }),
  )
  await page.route(
    new RegExp(`/api/v1/projects/${projectId}/ip-assets(?:\\?.*)?$`),
    (route) =>
      route.fulfill({
        json: {
          data: [
            {
              id: resourceId,
              resource_id: resourceId,
              resource_type: "IP",
              canonical_key: "192.0.2.10",
              canonical_ip: "192.0.2.10",
              customer_observation_count: 1,
              cloudatlas_observation_count: 1,
              observation_count: 2,
              customer_observed: true,
              cloudatlas_observed: true,
              open_finding_id: null,
              open_finding_type: null,
            },
          ],
          count: 1,
          latest_run_id: "60000000-0000-0000-0000-000000000001",
          latest_run_completed_at: "2026-07-30T12:00:00Z",
          compatible: true,
          compatibility_code: null,
        },
      }),
  )
  await page.route(
    new RegExp(
      `/api/v1/projects/${projectId}/ip-assets/${resourceId}(?:\\?.*)?$`,
    ),
    (route) =>
      route.fulfill({
        json: {
          id: resourceId,
          resource_id: resourceId,
          resource_type: "IP",
          canonical_key: "192.0.2.10",
          canonical_ip: "192.0.2.10",
          customer_observation_count: 1,
          cloudatlas_observation_count: 1,
          observation_count: 2,
          customer_observed: true,
          cloudatlas_observed: true,
          open_finding_id: null,
          open_finding_type: null,
          observations: [observation, cloudatlasObservation],
        },
      }),
  )
  await page.route(
    new RegExp(`/api/v1/projects/${projectId}/findings\\?status=OPEN.*$`),
    (route) =>
      route.fulfill({
        json: {
          data: [findingSummary],
          count: 1,
          status: "OPEN",
          latest_run_id: "60000000-0000-0000-0000-000000000001",
          latest_run_completed_at: "2026-07-30T12:00:00Z",
          compatible: true,
          compatibility_code: null,
        },
      }),
  )
  await page.route(
    new RegExp(`/api/v1/projects/${projectId}/findings\\?status=CLOSED.*$`),
    (route) =>
      route.fulfill({
        json: {
          data: [
            {
              ...findingSummary,
              status: "CLOSED",
            },
          ],
          count: 1,
          status: "CLOSED",
          latest_run_id: "60000000-0000-0000-0000-000000000001",
          latest_run_completed_at: "2026-07-30T12:00:00Z",
          compatible: true,
          compatibility_code: null,
        },
      }),
  )
  await page.route(findingDetailUrl, (route) =>
    route.fulfill({
      json: findingDetail,
    }),
  )
}

const completedInvestigation = {
  id: "e0000000-0000-4000-8000-000000000010",
  project_id: projectId,
  resource_id: resourceId,
  run_id: findingSummary.latest_occurrence_run_id,
  finding_id: null,
  parent_investigation_id: null,
  question: null,
  tool_reads: [],
  status: "COMPLETED",
  created_at: "2026-09-09T12:00:00Z",
  completed_at: "2026-09-09T12:01:00Z",
  failure_code: null,
  output: {
    facts: [
      {
        text: "Original published comparison.",
        citation_ids: ["base-comparison"],
      },
    ],
    explanations: [],
    gaps: [],
    next_steps: [],
  },
  material: {
    version: "ai-investigation-material/v1",
    project_id: projectId,
    scope: {
      resource_id: resourceId,
      run_id: findingSummary.latest_occurrence_run_id,
      finding_id: null,
    },
    published_at: "2026-07-30T12:00:00Z",
    report_id: "report-1",
    report_contract_version: "deterministic-report-v2",
    truncated: false,
    items: [
      {
        citation_id: "base-comparison",
        fact: { resource_id: resourceId, customer_observed: true },
      },
    ],
  },
}

test.describe("Project result views", () => {
  test.beforeEach(async ({ page }) => {
    await installBaseMocks(page)
    await installResultMocks(page)
    await page.goto("/")
  })
  test("saves without AI, retains rejected corrections, and resets the draft for a Finding scope", async ({
    page,
  }) => {
    const runId = findingSummary.latest_occurrence_run_id
    const original: ManualReviewPublic = {
      id: "f0000000-0000-4000-8000-000000000001",
      project_id: projectId,
      resource_id: resourceId,
      run_id: runId,
      finding_id: null,
      author_id: "30000000-0000-0000-0000-000000000001",
      author_name: "Test Operator",
      created_at: "2026-09-09T12:00:00Z",
      conclusion: "Original observation",
      pending_verification: "Confirm both source observations",
      supersedes_id: null,
      version: 1,
      is_current: true,
      status: "RESOLVED",
      verifications: [
        {
          run_id: "60000000-0000-4000-8000-000000000002",
          run_status: "COMPLETED",
          completed_at: "2026-09-09T12:02:00Z",
          observed_at: "2026-09-09T12:02:00Z",
          status: "RESOLVED",
          reason: "both_sources_observed",
        },
      ],
    }
    let records = [original]
    let findingRecords: ManualReviewPublic[] = []
    let conflict = true
    const requests: Record<string, unknown>[] = []
    await page.route(
      `**/api/v1/projects/${projectId}/ai-investigations**`,
      (route) =>
        route.fulfill({ status: 503, json: { detail: "Model unavailable" } }),
    )
    await page.route(
      `**/api/v1/projects/${projectId}/manual-reviews**`,
      async (route) => {
        if (route.request().method() === "POST") {
          const body = route.request().postDataJSON()
          requests.push(body)
          if (conflict) {
            conflict = false
            records = [
              {
                ...original,
                id: "f0000000-0000-4000-8000-000000000002",
                conclusion: "Another operator's correction",
                version: 2,
                created_at: "2026-09-09T12:03:00Z",
                status: "PENDING",
                verifications: [],
              },
              { ...original, is_current: false },
            ]
            return route.fulfill({
              status: 409,
              json: { detail: "Current version changed" },
            })
          }
          const saved: ManualReviewPublic = {
            ...original,
            ...body,
            id: body.finding_id
              ? "f0000000-0000-4000-8000-000000000004"
              : "f0000000-0000-4000-8000-000000000003",
            version: body.finding_id ? 1 : 3,
            created_at: "2026-09-09T12:04:00Z",
            status: "PENDING",
            verifications: [],
          }
          if (body.finding_id) findingRecords = [saved]
          else
            records = [
              saved,
              ...records.map((item) => ({ ...item, is_current: false })),
            ]
          return route.fulfill({ status: 201, json: saved })
        }
        const finding = new URL(route.request().url()).searchParams.get(
          "finding_id",
        )
        const scopedRecords = finding ? findingRecords : records
        return route.fulfill({
          json: {
            data: scopedRecords,
            count: scopedRecords.length,
            can_create: true,
          },
        })
      },
    )
    await page
      .getByRole("link", { name: "Current assets", exact: true })
      .click()
    await page.getByRole("button", { name: "View details" }).click()
    const panel = page.getByRole("region", {
      name: "Manual review",
      exact: true,
    })
    await expect(
      page.getByRole("region", { name: "AI investigation" }),
    ).toContainText("Investigation could not be read")
    await panel.getByRole("button", { name: "Correct current version" }).click()
    await expect(
      panel.getByLabel("Manual conclusion", { exact: true }),
    ).toHaveValue(original.conclusion)
    await panel
      .getByLabel("Manual conclusion", { exact: true })
      .fill("My corrected explanation")
    await panel
      .getByRole("button", { name: "Save correction", exact: true })
      .click()
    await expect(
      panel.getByRole("article", {
        name: "Manual record version 2",
        exact: true,
      }),
    ).toBeVisible()
    await expect(
      panel.getByLabel("Manual conclusion", { exact: true }),
    ).toHaveValue("My corrected explanation")
    await expect(
      panel.getByRole("button", { name: "Save correction", exact: true }),
    ).toBeDisabled()
    await expect(
      panel
        .getByRole("article", { name: "Manual record version 1", exact: true })
        .getByRole("button"),
    ).toHaveCount(0)
    await panel.getByRole("button", { name: "Correct current version" }).click()
    await expect(
      panel.getByLabel("Manual conclusion", { exact: true }),
    ).toHaveValue("My corrected explanation")
    await panel
      .getByRole("button", { name: "Save correction", exact: true })
      .click()
    const current = panel.getByRole("article", {
      name: "Manual record version 3",
      exact: true,
    })
    await expect(current).toContainText("Pending verification")
    await expect(current).toContainText("My corrected explanation")
    await expect(
      panel.getByRole("article", {
        name: "Manual record version 1",
        exact: true,
      }),
    ).toContainText(original.conclusion)
    expect(requests.map((request) => request.supersedes_id)).toEqual([
      original.id,
      "f0000000-0000-4000-8000-000000000002",
    ])
    expect(requests[1]).toMatchObject({
      resource_id: resourceId,
      run_id: runId,
      finding_id: null,
      conclusion: "My corrected explanation",
      pending_verification: original.pending_verification,
    })
    await panel.getByRole("button", { name: "Correct current version" }).click()
    await panel
      .getByLabel("Manual conclusion", { exact: true })
      .fill("Do not leak this asset draft")
    await page.getByRole("button", { name: "Close", exact: true }).click()
    await page.getByRole("link", { name: "Findings", exact: true }).click()
    await page.getByRole("button", { name: "View details" }).click()
    await expect(
      panel.getByLabel("Manual conclusion", { exact: true }),
    ).toHaveValue("")
    await expect(
      panel.getByLabel("Items to verify", { exact: true }),
    ).toHaveValue("")
    await panel
      .getByLabel("Manual conclusion", { exact: true })
      .fill("Finding-specific review")
    await panel
      .getByLabel("Items to verify", { exact: true })
      .fill("Check original difference")
    await panel
      .getByRole("button", { name: "Save manual record", exact: true })
      .click()
    await expect.poll(() => requests.length).toBe(3)
    expect(requests[2]).toMatchObject({
      resource_id: resourceId,
      run_id: runId,
      finding_id: findingId,
      supersedes_id: null,
    })
    await expect(
      panel.getByRole("article", {
        name: "Manual record version 1",
        exact: true,
      }),
    ).toContainText("Finding-specific review")
    await expect(
      page.getByRole("dialog").getByText("OPEN", { exact: true }),
    ).toBeVisible()
  })

  test("keeps successful verification beside later failure, with read-only paginated bilingual history", async ({
    page,
  }) => {
    const successRun = "60000000-0000-4000-8000-000000000002"
    const failureRun = "60000000-0000-4000-8000-000000000003"
    const record = {
      id: "f0000000-0000-4000-8000-000000000021",
      project_id: projectId,
      resource_id: resourceId,
      run_id: findingSummary.latest_occurrence_run_id,
      finding_id: null,
      author_id: "30000000-0000-0000-0000-000000000001",
      author_name: "Readably named operator",
      created_at: "2026-09-09T12:00:00Z",
      conclusion: "Documented original difference",
      pending_verification: "Check both sources",
      supersedes_id: null,
      version: 21,
      is_current: true,
      status: "RESOLVED",
      verifications: [
        {
          run_id: successRun,
          run_status: "COMPLETED",
          completed_at: "2026-09-09T13:00:00Z",
          observed_at: "2026-09-09T13:00:00Z",
          status: "RESOLVED",
          reason: "both_sources_observed",
        },
        {
          run_id: failureRun,
          run_status: "FAILED_PROCESSING",
          completed_at: "2026-09-09T14:00:00Z",
          observed_at: "2026-09-09T14:00:00Z",
          status: "NO_NEW_CONCLUSION",
          reason: "run_not_successful",
        },
      ],
    }
    await page.route(
      `**/api/v1/projects/${projectId}/manual-reviews**`,
      (route) => {
        const older =
          new URL(route.request().url()).searchParams.get("skip") === "20"
        return route.fulfill({
          json: {
            data: older
              ? [
                  {
                    ...record,
                    id: "f0000000-0000-4000-8000-000000000001",
                    version: 1,
                    is_current: false,
                    conclusion: "Old retained record",
                    verifications: [],
                  },
                ]
              : Array.from({ length: 20 }, (_, index) => ({
                  ...record,
                  id: `f0000000-0000-4000-8000-${String(21 - index).padStart(12, "0")}`,
                  version: 21 - index,
                  is_current: index === 0,
                  verifications: index === 0 ? record.verifications : [],
                })),
            count: 21,
            can_create: false,
          },
        })
      },
    )
    await page
      .getByRole("link", { name: "Current assets", exact: true })
      .click()
    await page.getByRole("button", { name: "View details" }).click()
    const panel = page.getByRole("region", {
      name: "Manual review",
      exact: true,
    })
    const current = panel.getByRole("article", {
      name: "Manual record version 21",
      exact: true,
    })
    await expect(current).toContainText("Verified resolved")
    await expect(current).toContainText("No new conclusion")
    await expect(current).toContainText(
      "earlier successful verification remains unchanged",
    )
    await expect(current).toContainText(record.author_name)
    await expect(panel.getByRole("textbox")).toHaveCount(0)
    await expect(
      panel.getByRole("button", { name: "Correct current version" }),
    ).toHaveCount(0)
    const identifiers = current
      .locator("summary")
      .filter({ hasText: "Verification Run · full identifier and reason" })
    await identifiers.first().focus()
    await page.keyboard.press("Enter")
    await identifiers.last().click()
    await expect(current.getByText(successRun, { exact: true })).toBeVisible()
    await expect(current.getByText(failureRun, { exact: true })).toBeVisible()
    await page.setViewportSize({ width: 390, height: 844 })
    expect(
      await page
        .getByRole("dialog")
        .evaluate((element) => element.scrollWidth <= element.clientWidth + 1),
    ).toBe(true)
    await panel
      .getByRole("navigation", { name: "Manual records pagination" })
      .getByRole("button", { name: "Next" })
      .click()
    await expect(
      panel.getByRole("article", {
        name: "Manual record version 1",
        exact: true,
      }),
    ).toContainText("Old retained record")
    await expect(
      panel.getByRole("button", { name: "Correct current version" }),
    ).toHaveCount(0)
    await page.evaluate(() =>
      localStorage.setItem("exposure:language", "zh-CN"),
    )
    await page.reload()
    const chinese = page.getByRole("region", { name: "人工核查", exact: true })
    await expect(chinese).toContainText("已验证解决")
    await expect(chinese).toContainText("没有新的可用结论")
    await expect(chinese).toContainText("当前为只读权限")
  })

  test("allows correcting a rejected follow-up after reload without replaying its rejected key", async ({
    page,
  }) => {
    const parent = completedInvestigation
    const question = "Approved synthetic question"
    const child = {
      ...parent,
      id: "e0000000-0000-4000-8000-000000000012",
      parent_investigation_id: parent.id,
      question,
      created_at: "2026-09-09T12:02:00Z",
    }
    const requests: { key: string; body: unknown }[] = []
    await page.route(
      `**/api/v1/projects/${projectId}/ai-investigations**`,
      async (route) => {
        const path = new URL(route.request().url()).pathname
        if (route.request().method() === "POST") {
          requests.push({
            key: route.request().headers()["idempotency-key"],
            body: route.request().postDataJSON(),
          })
          if (requests.length === 1)
            return route.fulfill({
              status: 409,
              json: { detail: { code: "synthetic_material_denied" } },
            })
          return route.fulfill({ json: child })
        }
        if (path.endsWith("/ai-investigations"))
          return route.fulfill({
            json: {
              data: requests.length > 1 ? [child, parent] : [parent],
              count: requests.length > 1 ? 2 : 1,
              can_create: true,
            },
          })
        return route.fulfill({ json: path.endsWith(child.id) ? child : parent })
      },
    )
    await page
      .getByRole("link", { name: "Current assets", exact: true })
      .click()
    await page.getByRole("button", { name: "View details" }).click()
    const panel = page.getByRole("region", { name: "AI investigation" })
    await panel.getByLabel("Follow-up question").fill("Unapproved question")
    await panel.getByRole("button", { name: "Submit follow-up" }).click()
    await expect(panel.getByRole("alert")).toContainText("Request rejected")
    await expect(
      panel.getByRole("button", { name: "Submit follow-up" }),
    ).toBeEnabled()
    await page.reload()
    await expect(
      panel.getByRole("button", { name: "Check previous request" }),
    ).toHaveCount(0)
    await panel.getByLabel("Follow-up question").fill(question)
    await panel.getByRole("button", { name: "Submit follow-up" }).click()
    await expect(panel).toContainText("Saved question")
    expect(requests).toHaveLength(2)
    expect(requests[1].body).toEqual({ question })
    expect(requests[1].key).not.toBe(requests[0].key)
  })

  test("replays a pending follow-up after reload without changing parent and retries a failed turn as a follow-up", async ({
    page,
  }) => {
    const parent = completedInvestigation
    const question = "What changed since the historical snapshot?"
    const child = {
      ...parent,
      id: "e0000000-0000-4000-8000-000000000011",
      parent_investigation_id: parent.id,
      question,
      created_at: "2026-09-09T12:02:00Z",
      completed_at: "2026-09-09T12:03:00Z",
      status: "FAILED",
      output: null,
      failure_code: "cloudatlas_upstream_failed",
    }
    const newer = {
      ...parent,
      id: "e0000000-0000-4000-8000-000000000099",
      created_at: "2026-09-09T13:00:00Z",
    }
    const requests: { path: string; key: string; body: unknown }[] = []
    let showNewer = false
    await page.route(
      `**/api/v1/projects/${projectId}/ai-investigations**`,
      async (route) => {
        const path = new URL(route.request().url()).pathname
        if (route.request().method() === "POST") {
          requests.push({
            path,
            key: route.request().headers()["idempotency-key"],
            body: route.request().postDataJSON(),
          })
          if (requests.length === 1) return route.abort()
          return route.fulfill({ json: child })
        }
        if (path.endsWith("/ai-investigations"))
          return route.fulfill({
            json: {
              data: showNewer ? [newer] : [parent],
              count: showNewer ? 3 : 1,
              can_create: true,
            },
          })
        return route.fulfill({
          json: path.endsWith(parent.id)
            ? parent
            : path.endsWith(newer.id)
              ? newer
              : child,
        })
      },
    )
    await page
      .getByRole("link", { name: "Current assets", exact: true })
      .click()
    await page.getByRole("button", { name: "View details" }).click()
    const panel = page.getByRole("region", { name: "AI investigation" })
    await panel.getByLabel("Follow-up question").fill(question)
    expect(requests).toHaveLength(0)
    await panel.getByRole("button", { name: "Submit follow-up" }).click()
    await expect(panel).toContainText("Pending question")
    showNewer = true
    await page.reload()
    await expect(panel).toContainText(question)
    await panel.getByRole("button", { name: "Check previous request" }).click()
    await expect(panel).toContainText("This attempt failed.")
    expect(requests).toHaveLength(2)
    expect(requests[1]).toEqual(requests[0])
    expect(requests[1].path).toBe(
      `/api/v1/projects/${projectId}/ai-investigations/${parent.id}/followups`,
    )
    expect(requests[1].body).toEqual({ question })
    // The parent is outside the list window and must be recovered by identity.
    await expect(
      panel.locator("article").filter({ hasText: "Saved question" }),
    ).toContainText(parent.id)
    await expect(panel.locator("article").first()).toContainText(parent.id)
    await panel.getByRole("button", { name: "Start a new attempt" }).click()
    await expect.poll(() => requests.length).toBe(3)
    expect(requests[2].path).toBe(requests[0].path)
    expect(requests[2].body).toEqual(requests[0].body)
    expect(requests[2].key).not.toBe(requests[0].key)
  })

  test("distinguishes persisted read sources and rejects scope drift, conflicting and unsuccessful citations", async ({
    page,
  }) => {
    const parent = completedInvestigation
    const read = {
      id: "f0000000-0000-4000-8000-000000000001",
      tool_name: "read_cloudatlas_asset",
      queried_at: "2026-09-09T12:02:00Z",
      completed_at: "2026-09-09T12:02:01Z",
      status: "SUCCEEDED",
      failure_code: null,
      project_id: projectId,
      resource_id: resourceId,
      run_id: parent.run_id,
      result: { source: "CloudAtlas OctoBus ListIPAssets", result: "FOUND" },
      items: [
        {
          citation_id: "live-asset",
          fact: {
            canonical_ip: "192.0.2.10",
            source: "CLOUDATLAS",
            queried_at: "2026-09-09T12:02:00Z",
          },
        },
      ],
    }
    const history = {
      ...read,
      id: "f0000000-0000-4000-8000-000000000002",
      tool_name: "read_asset_history",
      items: [
        {
          citation_id: "history-asset",
          fact: {
            run_id: "60000000-0000-0000-0000-000000000009",
            published_at: "2026-07-01T12:00:00Z",
            customer_observed: false,
          },
        },
      ],
    }
    const failed = {
      ...read,
      id: "f0000000-0000-4000-8000-000000000003",
      status: "FAILED",
      failure_code: "cloudatlas_upstream_failed",
      items: [],
      result: {},
    }
    const noData = {
      ...history,
      id: "f0000000-0000-4000-8000-000000000004",
      items: [],
      result: {
        result: "NO_DATA",
        gaps: ["no_published_asset_history"],
        source: "published_runs",
      },
    }
    const running = {
      ...read,
      id: "f0000000-0000-4000-8000-000000000005",
      status: "RUNNING",
      completed_at: null,
      items: [],
      result: {},
    }
    let corruption = ""
    await page.route(
      `**/api/v1/projects/${projectId}/ai-investigations**`,
      async (route) => {
        const live = {
          ...read,
          run_id: corruption === "scope" ? "other-run" : read.run_id,
          ...(corruption === "failed" ? { status: "FAILED", items: [] } : {}),
          ...(corruption === "running" ? { status: "RUNNING", items: [] } : {}),
          ...(corruption === "conflict"
            ? {
                items: [
                  {
                    citation_id: "base-comparison",
                    fact: { customer_observed: false },
                  },
                ],
              }
            : {}),
        }
        const child = {
          ...parent,
          id: "e0000000-0000-4000-8000-000000000012",
          parent_investigation_id: parent.id,
          question: "Compare the live and historical material.",
          created_at: "2026-09-09T12:04:00Z",
          tool_reads: [
            {
              ...read,
              id: "f0000000-0000-4000-8000-000000000006",
              tool_name: "read_asset_facts",
              items: parent.material.items,
            },
            live,
            history,
            failed,
            noData,
            running,
          ],
          output: {
            ...parent.output,
            facts: [
              {
                text: "Live and historical evidence differ.",
                citation_ids: [
                  corruption === "invented"
                    ? "never-read"
                    : corruption === "conflict"
                      ? "base-comparison"
                      : "live-asset",
                  "history-asset",
                  "base-comparison",
                ],
              },
            ],
          },
        }
        const path = new URL(route.request().url()).pathname
        return route.fulfill({
          json: path.endsWith("/ai-investigations")
            ? { data: [child], count: 2, can_create: false }
            : path.endsWith(parent.id)
              ? {
                  ...parent,
                  resource_id:
                    corruption === "ancestor" ? "other-resource" : resourceId,
                }
              : child,
        })
      },
    )
    await page
      .getByRole("link", { name: "Current assets", exact: true })
      .click()
    await page.getByRole("button", { name: "View details" }).click()
    const panel = page.getByRole("region", { name: "AI investigation" })
    await expect(panel).toContainText("Live and historical evidence differ.")
    await expect(panel).toContainText(
      "No facts or citations from this failed read.",
    )
    await expect(panel).toContainText("Read not yet confirmed")
    await expect(panel).toContainText("No matching material returned")
    await expect(panel).toContainText("NO_DATA")
    await expect(panel).toContainText("no_published_asset_history")
    const childArticle = panel
      .locator("article")
      .filter({ hasText: "Saved question" })
    const citations = childArticle.getByRole("list", {
      name: "Material citations",
    })
    const liveCitation = citations
      .locator("summary")
      .filter({ hasText: "live-asset" })
    await liveCitation.focus()
    await page.keyboard.press("Enter")
    await expect(liveCitation.locator("..")).toContainText(
      "Live CloudAtlas query",
    )
    await expect(liveCitation.locator("..")).toContainText("192.0.2.10")
    const historyCitation = citations
      .locator("summary")
      .filter({ hasText: "history-asset" })
    await historyCitation.click()
    await expect(historyCitation.locator("..")).toContainText(
      "Historical published snapshot",
    )
    await expect(historyCitation.locator("..")).toContainText("2026-07-01")
    await expect(panel.getByLabel("Follow-up question")).toHaveCount(0)
    await page.setViewportSize({ width: 390, height: 844 })
    expect(
      await page
        .getByRole("dialog")
        .evaluate((element) => element.scrollWidth <= element.clientWidth + 1),
    ).toBe(true)
    for (const invalid of [
      "scope",
      "failed",
      "running",
      "conflict",
      "invented",
      "ancestor",
    ]) {
      corruption = invalid
      await page.reload()
      await expect(panel).toContainText("Investigation could not be read")
      await expect(panel).not.toContainText(
        "Live and historical evidence differ.",
      )
    }
  })

  test("uses paginated Assets and Findings views with bounded source details", async ({
    page,
  }) => {
    await page
      .getByRole("link", { name: "Current assets", exact: true })
      .click()
    await expect(page.getByText("IP Assets")).toBeVisible()
    await expect(page.getByText("192.0.2.10", { exact: true })).toBeVisible()
    await expect(page.getByText("Present", { exact: true })).toHaveCount(2)

    await page.getByRole("button", { name: "View details" }).click()
    await expect(page.getByRole("dialog")).toContainText("row:2")
    await expect(page.getByRole("dialog")).toContainText("atlas-1")
    await expect(page.getByRole("dialog")).toContainText(customerSnapshotId)
    await page.getByRole("button", { name: "Close" }).click()

    await page.getByRole("link", { name: "Findings", exact: true }).click()
    await expect(
      page.getByRole("table").getByText("OPEN", { exact: true }),
    ).toBeVisible()
    await page.getByRole("combobox", { name: "Finding status" }).click()
    await page.getByRole("option", { name: "CLOSED", exact: true }).click()
    await expect(
      page.getByRole("table").getByText("CLOSED", { exact: true }),
    ).toBeVisible()
    await page.getByRole("button", { name: "View details" }).click()
    await expect(page.getByRole("dialog")).toContainText("Occurrence")
    await expect(page.getByRole("dialog")).toContainText("Transition · OPENED")
    await expect(page.getByRole("dialog")).toContainText(
      "Confirmed Snapshot references",
    )
  })

  test("recovers an uncertain investigation with the same identity and fixed Run after reload", async ({
    page,
  }) => {
    const runId = findingSummary.latest_occurrence_run_id
    const requests: { key: string; body: unknown }[] = []
    const investigation = {
      id: "e0000000-0000-0000-0000-000000000001",
      project_id: projectId,
      resource_id: resourceId,
      run_id: runId,
      finding_id: null,
      parent_investigation_id: null,
      question: null,
      tool_reads: [],
      status: "GENERATING",
      created_at: "2026-09-09T12:00:00Z",
      completed_at: null,
      failure_code: "investigation_session_unknown",
      output: null,
      material: {
        version: "ai-investigation-material/v1",
        project_id: projectId,
        scope: { resource_id: resourceId, run_id: runId, finding_id: null },
        published_at: "2026-07-30T12:00:00Z",
        report_id: "report-1",
        report_contract_version: "deterministic-report-v1",
        truncated: false,
        items: [],
      },
    }
    await page.route(
      `**/api/v1/projects/${projectId}/ai-investigations**`,
      async (route) => {
        if (route.request().method() === "POST") {
          requests.push({
            key: route.request().headers()["idempotency-key"],
            body: route.request().postDataJSON(),
          })
          if (requests.length === 1) return route.abort()
          return route.fulfill({ json: investigation })
        }
        const url = new URL(route.request().url())
        return route.fulfill({
          json: url.pathname.endsWith("/ai-investigations")
            ? { data: [], count: 0, can_create: true }
            : investigation,
        })
      },
    )
    await page
      .getByRole("link", { name: "Current assets", exact: true })
      .click()
    await page.getByRole("button", { name: "View details" }).click()
    await page.getByRole("button", { name: "Investigate this asset" }).click()
    await expect(page.getByText("Start not yet confirmed")).toBeVisible()
    // Recovery written by the initial-only UI has no follow-up fields.
    await page.evaluate(() => {
      const key = Object.keys(sessionStorage).find((entry) =>
        entry.startsWith("exposure:ai-investigation:"),
      )
      if (!key) throw new Error("Missing durable investigation identity")
      const { idempotencyKey, investigationId } = JSON.parse(
        sessionStorage.getItem(key) ?? "null",
      )
      sessionStorage.setItem(
        key,
        JSON.stringify({ idempotencyKey, investigationId }),
      )
    })
    await page.route(
      new RegExp(`/api/v1/projects/${projectId}/ip-assets(?:\\?.*)?$`),
      (route) =>
        route.fulfill({
          json: {
            data: [],
            count: 0,
            latest_run_id: "60000000-0000-0000-0000-000000000099",
            latest_run_completed_at: "2026-09-09T13:00:00Z",
            compatible: true,
            compatibility_code: null,
          },
        }),
    )
    await page.reload()
    await page.getByRole("button", { name: "Check previous request" }).click()
    await expect(
      page.getByRole("region", { name: "AI investigation" }),
    ).toContainText("Awaiting a confirmed result.")
    expect(requests).toHaveLength(2)
    expect(requests[0].key).toBeTruthy()
    expect(requests[1]).toEqual(requests[0])
    expect(requests[1].body).toEqual({
      resource_id: resourceId,
      run_id: runId,
      finding_id: null,
    })
    await expect(
      page.getByRole("region", { name: "AI investigation" }),
    ).not.toContainText("60000000-0000-0000-0000-000000000099")
    await page.getByRole("button", { name: "Check previous request" }).click()
    await expect.poll(() => requests.length).toBe(3)
    expect(requests[2]).toEqual(requests[0])
    const citationId = `comparison/${runId}/${resourceId}`
    const completed = {
      ...investigation,
      status: "COMPLETED",
      completed_at: "2026-09-09T13:01:00Z",
      failure_code: null,
      material: {
        ...investigation.material,
        items: [
          {
            citation_id: citationId,
            fact: { kind: "COMPARISON", resource_id: resourceId },
          },
        ],
      },
      output: {
        facts: [
          {
            text: `Published comparison for ${resourceId}; reference ${"a".repeat(128)}.`,
            citation_ids: [citationId],
          },
        ],
        explanations: [],
        gaps: [],
        next_steps: [],
      },
    }
    await page.route(
      `**/api/v1/projects/${projectId}/ai-investigations**`,
      (route) =>
        route.fulfill({
          json: new URL(route.request().url()).pathname.endsWith(
            "/ai-investigations",
          )
            ? { data: [completed], count: 1, can_create: true }
            : completed,
        }),
    )
    await page.setViewportSize({ width: 390, height: 844 })
    await page.reload()
    await expect(
      page.getByRole("heading", { name: "Cited facts" }),
    ).toBeVisible()
    const dialog = page.getByRole("dialog")
    expect(
      await dialog.evaluate(
        (element) => element.scrollWidth <= element.clientWidth + 1,
      ),
    ).toBe(true)
    const citation = dialog.locator("summary").filter({ hasText: citationId })
    await citation.focus()
    await page.keyboard.press("Enter")
    await expect(citation.locator("..")).toContainText(resourceId)
  })

  test("keeps Viewer investigation citations readable and rejects cross-project results", async ({
    page,
  }) => {
    await page.route(
      new RegExp(`/api/v1/projects/${projectId}/findings\\?status=OPEN.*$`),
      (route) =>
        route.fulfill({
          json: {
            data: [findingSummary],
            count: 1,
            status: "OPEN",
            latest_run_id: "60000000-0000-0000-0000-000000000099",
            latest_run_completed_at: "2026-09-09T12:00:00Z",
            compatible: true,
            compatibility_code: null,
          },
        }),
    )
    const citationId = `comparison/${findingSummary.latest_occurrence_run_id}/${resourceId}`
    let wrongProject = false
    const investigation = {
      id: "e0000000-0000-0000-0000-000000000002",
      project_id: projectId,
      resource_id: resourceId,
      run_id: findingSummary.latest_occurrence_run_id,
      finding_id: findingId,
      parent_investigation_id: null,
      question: null,
      tool_reads: [],
      status: "COMPLETED",
      created_at: "2026-09-09T12:00:00Z",
      completed_at: "2026-09-09T12:01:00Z",
      failure_code: null,
      output: {
        facts: [
          {
            text: "Customer-side observation is present.",
            citation_ids: [citationId],
          },
        ],
        explanations: ["Ownership requires confirmation."],
        gaps: ["No owner record."],
        next_steps: ["Ask the asset owner."],
      },
      material: {
        version: "ai-investigation-material/v1",
        project_id: projectId,
        scope: {
          resource_id: resourceId,
          run_id: findingSummary.latest_occurrence_run_id,
          finding_id: findingId,
        },
        published_at: "2026-07-30T12:00:00Z",
        report_id: "report-1",
        report_contract_version: "deterministic-report-v2",
        truncated: false,
        items: [{ citation_id: citationId, fact: { customer_observed: true } }],
      },
    }
    await page.route(
      `**/api/v1/projects/${projectId}/ai-investigations**`,
      async (route) => {
        expect(route.request().method()).toBe("GET")
        const result = {
          ...investigation,
          project_id: wrongProject ? "other-project" : projectId,
        }
        return route.fulfill({
          json: new URL(route.request().url()).pathname.endsWith(
            "/ai-investigations",
          )
            ? { data: [result], count: 1, can_create: false }
            : result,
        })
      },
    )
    await page.getByRole("link", { name: "Findings", exact: true }).click()
    await page.getByRole("button", { name: "View details" }).click()
    const panel = page.getByRole("region", { name: "AI investigation" })
    await expect(panel).toContainText("Customer-side observation is present.")
    expect(new URL(page.url()).searchParams.get("investigation_run")).toBe(
      findingSummary.latest_occurrence_run_id,
    )
    await page.goto(
      `/?project=${projectId}&view=findings&finding_id=${findingId}`,
    )
    await expect(panel).toContainText("Customer-side observation is present.")
    expect(new URL(page.url()).searchParams.get("investigation_run")).toBe(
      findingSummary.latest_occurrence_run_id,
    )
    await expect(panel).toContainText("Read-only access.")
    await expect(
      panel.getByRole("button", { name: "Investigate this asset" }),
    ).toHaveCount(0)
    await expect(panel.getByLabel("Follow-up question")).toHaveCount(0)
    await expect(
      panel.getByRole("heading", { name: "Explanations to verify" }),
    ).toBeVisible()
    await expect(
      panel.getByRole("heading", { name: "Information gaps" }),
    ).toBeVisible()
    await expect(
      panel.getByRole("heading", { name: "Next steps" }),
    ).toBeVisible()
    await expect(panel).toContainText(citationId)
    await page.setViewportSize({ width: 390, height: 844 })
    const citation = panel.locator("summary").filter({ hasText: citationId })
    await citation.focus()
    await page.keyboard.press("Enter")
    await expect(citation.locator("..")).toContainText("customer observed")
    await expect(citation.locator("..")).toContainText("Yes")
    await page
      .getByRole("dialog")
      .getByRole("combobox", { name: "Language / 语言" })
      .selectOption("zh-CN")
    await expect(
      page
        .getByRole("region", { name: "AI 核查" })
        .getByRole("heading", { name: "待验证解释" }),
    ).toBeVisible()
    await page
      .getByRole("dialog")
      .getByRole("combobox", { name: "Language / 语言" })
      .selectOption("en")
    wrongProject = true
    await page.reload()
    await expect(panel).toContainText("Investigation could not be read")
    await expect(panel).not.toContainText(
      "Customer-side observation is present.",
    )
  })

  test("explains when only a Stage 3 Run is available", async ({ page }) => {
    await page.route(
      new RegExp(`/api/v1/projects/${projectId}/ip-assets(?:\\?.*)?$`),
      (route) =>
        route.fulfill({
          json: {
            data: [],
            count: 0,
            latest_run_id: "60000000-0000-0000-0000-000000000099",
            latest_run_completed_at: "2026-07-29T12:00:00Z",
            compatible: false,
            compatibility_code: "stage4_run_required",
          },
        }),
    )
    await page
      .getByRole("link", { name: "Current assets", exact: true })
      .click()
    await expect(
      page.getByText("Stage 4 results are not available yet"),
    ).toBeVisible()
    await expect(
      page.getByText(
        "The latest completed Run contains only Stage 3 results. Create a new Run",
      ),
    ).toBeVisible()
  })
})

test.describe("Finding NetFlow context presentation", () => {
  test.use({ timezoneId: "Asia/Shanghai", locale: "en-US" })

  test.beforeEach(async ({ page }) => {
    await installBaseMocks(page)
    await installResultMocks(page)
    await page.goto("/")
    await page.getByRole("link", { name: "Findings", exact: true }).click()
  })

  for (const scenario of [
    {
      name: "complete times and minimum count",
      count: 1,
      first: "2026-07-31T01:02:03Z",
      last: "2026-07-31T04:05:06Z",
      firstText: "7/31/2026, 9:02:03 AM",
      lastText: "7/31/2026, 12:05:06 PM",
    },
    {
      name: "missing first time and maximum count",
      count: 2147483647,
      first: null,
      last: "2026-07-31T04:05:06Z",
      firstText: "Not provided",
      lastText: "7/31/2026, 12:05:06 PM",
    },
    {
      name: "missing last time",
      count: 1,
      first: "2026-07-31T01:02:03Z",
      last: null,
      firstText: "7/31/2026, 9:02:03 AM",
      lastText: "Not provided",
    },
    {
      name: "both times missing",
      count: 1,
      first: null,
      last: null,
      firstText: "Not provided",
      lastText: "Not provided",
    },
  ]) {
    test(`shows sampled flow records with ${scenario.name}`, async ({
      page,
    }) => {
      await page.route(findingDetailUrl, (route) =>
        route.fulfill({
          json: {
            ...findingDetail,
            status: "CLOSED",
            netflow_context: {
              ...positiveNetflowContext,
              activity: {
                ...positiveNetflowContext.activity,
                flow_count: scenario.count,
                first_seen_utc: scenario.first,
                last_seen_utc: scenario.last,
              },
            },
          },
        }),
      )
      const opener = page.getByRole("button", { name: "View details" })
      await opener.click()
      const dialog = page.getByRole("dialog", { name: "Finding details" })
      const context = dialog.getByRole("region", {
        name: "Latest published Run NetFlow activity",
      })
      await expect(context).toBeVisible()
      await expect(dialog.getByText("CLOSED", { exact: true })).toBeVisible()
      await expect(context).toContainText(
        positiveNetflowContext.governance_run_id,
      )
      await expect(context).toContainText("Asia/Shanghai")
      await expect(
        context
          .locator("div")
          .filter({
            has: page
              .locator("dt")
              .getByText("Sampled flow records", { exact: true }),
          })
          .locator("dd")
          .first(),
      ).toHaveText(String(scenario.count))
      for (const [label, value] of [
        ["First activity", scenario.firstText],
        ["Last activity", scenario.lastText],
        ["Activity ID", positiveNetflowContext.activity.activity_id],
        [
          "NETFLOW Snapshot ID",
          positiveNetflowContext.activity.source_snapshot_id,
        ],
        ["Aggregation contract", "netflow-ip-activity-v1"],
        ["Content SHA-256", positiveNetflowContext.activity.content_sha256],
      ]) {
        await expect(
          context
            .locator("div")
            .filter({
              has: page.locator("dt").getByText(label, { exact: true }),
            })
            .locator("dd"),
        ).toHaveText(value)
      }
      await expect(context.getByRole("link")).toHaveCount(0)
      await expect(context).toContainText("does not establish")
      await expect(
        dialog.getByRole("heading", { name: "Occurrence", exact: true }),
      ).toBeVisible()
      await expect(
        dialog.getByRole("heading", { name: "Transition · OPENED" }),
      ).toBeVisible()
      expect(
        await context.evaluate((element) => {
          const dialogElement = element.closest('[role="dialog"]')
          const occurrence = Array.from(
            dialogElement?.querySelectorAll("h3") ?? [],
          ).find((heading) => heading.textContent === "Occurrence")
          return (
            !!occurrence &&
            !!(
              element.compareDocumentPosition(occurrence) &
              Node.DOCUMENT_POSITION_FOLLOWING
            )
          )
        }),
      ).toBe(true)
      await page.keyboard.press("Tab")
      await expect(dialog).toContainText(
        "Latest published Run NetFlow activity",
      )
      expect(
        await dialog.evaluate((element) =>
          element.contains(document.activeElement),
        ),
      ).toBe(true)
      await page.keyboard.press("Escape")
      await expect(dialog).toHaveCount(0)
      await expect(opener).toBeFocused()
    })
  }

  for (const [status, message] of [
    ["NOT_APPLICABLE", "Not applicable to this Finding in this Run."],
    ["INPUT_UNMODELED", "This historical Run did not model NetFlow input."],
    ["INPUT_ABSENT", "No NetFlow input was provided for this Run."],
    [
      "ACTIVITY_UNMODELED",
      "This historical Run did not model the NetFlow activity contract.",
    ],
    [
      "NO_POSITIVE_ACTIVITY",
      "This Run has no positive NetFlow activity evidence for this resource.",
    ],
  ] as const) {
    test(`distinguishes ${status} without a zero placeholder`, async ({
      page,
    }) => {
      await page.route(findingDetailUrl, (route) =>
        route.fulfill({
          json: {
            ...findingDetail,
            netflow_context: {
              governance_run_id: positiveNetflowContext.governance_run_id,
              status,
              activity: null,
            } satisfies FindingDetailPublic["netflow_context"],
          },
        }),
      )
      await page.getByRole("button", { name: "View details" }).click()
      const context = page.getByRole("region", {
        name: "Latest published Run NetFlow activity",
      })
      await expect(context).toContainText(message)
      await expect(context).toContainText(
        positiveNetflowContext.governance_run_id,
      )
      await expect(context.locator("dl")).toHaveCount(0)
      await expect(context.getByText("0", { exact: true })).toHaveCount(0)
      await expect(context.getByRole("link")).toHaveCount(0)
      await expect(
        page.getByRole("dialog").getByText("OPEN", { exact: true }),
      ).toBeVisible()
    })
  }

  test("keeps an unknown NetFlow context explicit when language changes", async ({
    page,
  }) => {
    await page.route(findingDetailUrl, (route) =>
      route.fulfill({
        json: {
          ...findingDetail,
          netflow_context: {
            governance_run_id: positiveNetflowContext.governance_run_id,
            status: "constructor",
            activity: null,
          },
        },
      }),
    )
    await page.getByRole("button", { name: "View details" }).click()
    const dialog = page.getByRole("dialog")
    await expect(dialog).toContainText(
      "Unknown NetFlow context status: constructor",
    )
    await dialog
      .getByRole("combobox", { name: "Language / 语言" })
      .selectOption("zh-CN")
    await expect(dialog).toContainText("未知的 NetFlow 上下文状态：constructor")
    await expect(dialog).not.toContainText("此运行未提供 NetFlow 输入")
  })

  test("keeps a long hash inside the narrow dialog", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 800 })
    await page.route(findingDetailUrl, (route) =>
      route.fulfill({
        json: { ...findingDetail, netflow_context: positiveNetflowContext },
      }),
    )
    await page.getByRole("button", { name: "View details" }).click()
    const dialog = page.getByRole("dialog")
    const context = dialog.getByRole("region", {
      name: "Latest published Run NetFlow activity",
    })
    await expect(context).toContainText(
      positiveNetflowContext.activity.content_sha256,
    )
    expect(
      await context.evaluate(
        (element) => element.scrollWidth <= element.clientWidth,
      ),
    ).toBe(true)
    expect(
      await dialog.evaluate(
        (element) => element.scrollWidth <= element.clientWidth,
      ),
    ).toBe(true)
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true)
    await page.keyboard.press("Escape")
    await expect(dialog).toHaveCount(0)
  })

  for (const failure of ["server error", "invalid positive context"] as const) {
    test(`uses the existing loading error for ${failure}`, async ({ page }) => {
      let releaseResponse: () => void = () => {}
      const responseReady = new Promise<void>((resolve) => {
        releaseResponse = resolve
      })
      await page.route(findingDetailUrl, async (route) => {
        await responseReady
        await route.fulfill(
          failure === "server error"
            ? { status: 500, json: { detail: "Internal Server Error" } }
            : {
                json: {
                  ...findingDetail,
                  netflow_context: {
                    ...positiveNetflowContext,
                    activity: null,
                  },
                },
              },
        )
      })
      await page.getByRole("button", { name: "View details" }).click()
      await expect(page.getByRole("status")).toHaveText(
        "Loading Finding details…",
      )
      releaseResponse()
      const dialog = page.getByRole("dialog")
      await expect(dialog.getByRole("alert")).toContainText(
        "Finding details could not be loaded",
        { timeout: 15000 },
      )
      await expect(
        dialog.getByRole("region", {
          name: "Latest published Run NetFlow activity",
        }),
      ).toHaveCount(0)
      await expect(dialog).not.toContainText("no positive NetFlow activity")
    })
  }

  test("keeps latest Run context separate while both histories paginate", async ({
    page,
  }) => {
    const requests: URL[] = []
    await page.route(findingDetailUrl, (route) => {
      const url = new URL(route.request().url())
      requests.push(url)
      return route.fulfill({
        json: {
          ...findingDetail,
          occurrence_count: 21,
          transition_count: 21,
          netflow_context: positiveNetflowContext,
          occurrences: [
            {
              ...findingDetail.occurrences[0],
              created_at:
                url.searchParams.get("occurrence_skip") === "20"
                  ? "2026-07-29T12:00:00Z"
                  : findingDetail.occurrences[0].created_at,
            },
          ],
          transitions: [
            {
              ...findingDetail.transitions[0],
              transition_type:
                url.searchParams.get("transition_skip") === "20"
                  ? "REOPENED"
                  : "OPENED",
            },
          ],
        },
      })
    })
    await page.getByRole("button", { name: "View details" }).click()
    const dialog = page.getByRole("dialog")
    await dialog
      .getByRole("navigation", { name: "Finding occurrences pagination" })
      .getByRole("button", { name: "Next" })
      .click()
    await expect(
      dialog.getByRole("navigation", {
        name: "Finding occurrences pagination",
      }),
    ).toContainText("Page 2 of 2")
    await expect(dialog).toContainText("7/29/2026, 8:00:00 PM")
    await dialog
      .getByRole("navigation", { name: "Finding transitions pagination" })
      .getByRole("button", { name: "Next" })
      .click()
    await expect(
      dialog.getByRole("heading", { name: "Transition · REOPENED" }),
    ).toBeVisible()
    const context = dialog.getByRole("region", {
      name: "Latest published Run NetFlow activity",
    })
    await expect(context).toHaveCount(1)
    await expect(context).toContainText(
      positiveNetflowContext.governance_run_id,
    )
    await expect(context).not.toContainText(
      findingSummary.latest_occurrence_run_id,
    )
    expect(
      requests.map((url) => [
        url.searchParams.get("occurrence_skip"),
        url.searchParams.get("transition_skip"),
        url.searchParams.get("trace_limit"),
      ]),
    ).toEqual([
      ["0", "0", "20"],
      ["20", "0", "20"],
      ["20", "20", "20"],
    ])
  })
})
