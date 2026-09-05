import { expect, test } from "@playwright/test"

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
  await page.route(
    new RegExp(
      `/api/v1/projects/${projectId}/findings/${findingId}(?:\\?.*)?$`,
    ),
    (route) =>
      route.fulfill({
        json: {
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
        },
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
