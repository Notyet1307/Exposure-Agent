import type { FindingDetailPublic } from "../src/client"
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

test.describe("Project result tabs", () => {
  test.beforeEach(async ({ page }) => {
    await installBaseMocks(page)
    await installResultMocks(page)
    await page.goto("/")
  })

  test("uses paginated Assets and Findings views with bounded source details", async ({
    page,
  }) => {
    await page.getByRole("tab", { name: "Assets", exact: true }).click()
    await expect(page.getByText("IP Assets")).toBeVisible()
    await expect(page.getByText("192.0.2.10", { exact: true })).toBeVisible()
    await expect(page.getByText("Present", { exact: true })).toHaveCount(2)

    await page.getByRole("button", { name: "View details" }).click()
    await expect(page.getByRole("dialog")).toContainText("row:2")
    await expect(page.getByRole("dialog")).toContainText("atlas-1")
    await expect(page.getByRole("dialog")).toContainText(customerSnapshotId)
    await page.getByRole("button", { name: "Close" }).click()

    await page.getByRole("tab", { name: "Findings", exact: true }).click()
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
    await page.getByRole("tab", { name: "Assets", exact: true }).click()
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
    await page.getByRole("tab", { name: "Findings", exact: true }).click()
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
