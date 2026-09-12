import type { FileChooser } from "@playwright/test"
import type { CloudAtlasSourcePublic } from "../src/client"
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
    name: "Archive Lab",
    id: "00000000-0000-0000-0000-000000000002",
    tenant_id: "00000000-0000-0000-0000-000000000010",
    created_at: "2026-07-29T10:00:00Z",
    updated_at: "2026-07-29T10:00:00Z",
    archived_at: "2026-07-30T11:00:00Z",
  },
]

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

const cloudatlasSources = {
  [projects[0].id]: {
    data: [
      {
        id: "50000000-0000-0000-0000-000000000001",
        source_type: "cloudatlas",
        instance_id: "cloudatlas-north",
        capset_id: "cloudatlas-readonly",
        enabled: false,
        validation_status: "not_validated",
        validated_fingerprint: null,
        created_at: "2026-07-30T12:00:00Z",
        updated_at: "2026-07-30T12:00:00Z",
      },
    ],
    count: 1,
    can_manage: false,
  },
  [projects[1].id]: {
    data: [],
    count: 0,
    can_manage: false,
  },
}

const confirmedInputs = {
  confirmation_input_hash: "a".repeat(64),
  customer_upload_id: "20000000-0000-0000-0000-000000000001",
  customer_filename: "north-assets.xlsx",
  customer_record_count: 2,
  customer_profile_version: 1,
  customer_accepted_at: "2026-07-30T12:00:00Z",
  source_instance_id: "50000000-0000-0000-0000-000000000001",
  source_instance_name: "cloudatlas-north",
  source_fingerprint: "b".repeat(64),
  source_validated_at: "2026-07-30T12:00:00Z",
  netflow_dataset_id: null,
  netflow_filename: null,
  netflow_record_count: null,
  netflow_accepted_at: null,
}

const governanceRuns = {
  [projects[0].id]: {
    data: [],
    count: 0,
    can_trigger: true,
    ready: false,
    readiness_code: "run_customer_upload_not_ready",
  },
  [projects[1].id]: {
    data: [],
    count: 0,
    can_trigger: false,
    ready: false,
    readiness_code: "run_project_archived",
  },
}

const uploads = {
  [projects[0].id]: {
    data: [
      {
        id: "20000000-0000-0000-0000-000000000001",
        display_filename: "north-assets.xlsx",
        raw_sha256: "a".repeat(64),
        record_count: 2,
        profile_id: profiles[projects[0].id].id,
        profile_version: 1,
        warnings: [
          {
            code: "missing_responsibility_value",
            field: "asset_owner",
            count: 1,
          },
        ],
        created_at: "2026-07-30T12:00:00Z",
      },
    ],
    count: 1,
    current_customer_upload_id: null,
    can_upload: true,
    can_select: true,
  },
  [projects[1].id]: {
    data: [],
    count: 0,
    current_customer_upload_id: null,
    can_upload: false,
    can_select: false,
  },
}
const northNetflowDatasets = [
  {
    id: "21000000-0000-0000-0000-000000000001",
    display_filename: "north-netflow.csv",
    raw_sha256: "c".repeat(64),
    normalized_sha256: "d".repeat(64),
    dataset_contract_version: "netflow-dataset-v1",
    schema_fingerprint: "e".repeat(64),
    encoding: "utf-8-sig",
    byte_size: 2048,
    raw_record_count: 12,
    activity_valid_record_count: 9,
    isolated_record_count: 3,
    valid_time_start_utc: "2026-08-01T00:00:00Z",
    valid_time_end_utc: "2026-08-01T12:00:00Z",
    duplicate_group_count: 2,
    duplicate_record_count: 3,
    warnings: [
      {
        code: "invalid_timestamp",
        field: "start_time",
        count: 2,
        source_record_keys: ["row:4", "row:8"],
      },
    ],
    created_at: "2026-08-01T13:00:00Z",
  },
  {
    id: "21000000-0000-0000-0000-000000000002",
    display_filename: "north-netflow-older.txt",
    raw_sha256: "f".repeat(64),
    normalized_sha256: "a".repeat(64),
    dataset_contract_version: "netflow-dataset-v1",
    schema_fingerprint: "b".repeat(64),
    encoding: "gb18030",
    byte_size: 1024,
    raw_record_count: 4,
    activity_valid_record_count: 4,
    isolated_record_count: 0,
    valid_time_start_utc: null,
    valid_time_end_utc: null,
    duplicate_group_count: 0,
    duplicate_record_count: 0,
    warnings: [],
    created_at: "2026-07-31T13:00:00Z",
  },
]
const netflowDatasets = {
  [projects[0].id]: {
    data: northNetflowDatasets,
    count: 2,
    current_netflow_dataset_id: "21000000-0000-0000-0000-000000000001",
    current_netflow_dataset: northNetflowDatasets[0],
    can_upload: true,
    can_select: true,
  },
  [projects[1].id]: {
    data: [],
    count: 0,
    current_netflow_dataset_id: null,
    current_netflow_dataset: null,
    can_upload: false,
    can_select: false,
  },
}

async function mockDashboardApi(page: Page) {
  await page.addInitScript(() => {
    if (sessionStorage.getItem("component-auth-seeded") === null) {
      localStorage.setItem("access_token", "component-token")
      sessionStorage.setItem("component-auth-seeded", "true")
    }
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
    const request = route.request()
    const url = new URL(request.url())
    if (
      url.pathname.endsWith("/governance-reports") &&
      request.method() === "GET"
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
    const profileMatch = url.pathname.match(
      /projects\/([^/]+)\/customer-upload-profile$/,
    )
    if (profileMatch) {
      await route.fulfill({
        json: profiles[profileMatch[1] as keyof typeof profiles],
      })
      return
    }
    const sourceMatch = url.pathname.match(
      /projects\/([^/]+)\/cloudatlas-source-instances$/,
    )
    if (sourceMatch && request.method() === "GET") {
      await route.fulfill({
        json: cloudatlasSources[
          sourceMatch[1] as keyof typeof cloudatlasSources
        ],
      })
      return
    }
    const runsMatch = url.pathname.match(/projects\/([^/]+)\/governance-runs$/)
    if (runsMatch && request.method() === "GET") {
      await route.fulfill({
        json: governanceRuns[runsMatch[1] as keyof typeof governanceRuns],
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
    const netflowMatch = url.pathname.match(
      /projects\/([^/]+)\/netflow-datasets$/,
    )
    if (netflowMatch && request.method() === "GET") {
      await route.fulfill({
        json: netflowDatasets[netflowMatch[1] as keyof typeof netflowDatasets],
      })
      return
    }
    if (url.pathname === "/api/v1/projects/") {
      await route.fulfill({ json: { data: projects, count: projects.length } })
      return
    }
    await route.fallback()
  })
}

test.beforeEach(async ({ page }) => {
  await mockDashboardApi(page)
})

test("explains a known unavailable Run input without enabling its trigger", async ({
  page,
}) => {
  await page.route(
    `**/api/v1/projects/${projects[0].id}/governance-runs`,
    (route) =>
      route.fulfill({
        json: {
          data: [],
          count: 0,
          can_trigger: true,
          ready: false,
          readiness_code: "run_netflow_dataset_not_ready",
        },
      }),
  )
  await page.goto("/?view=inputs")
  await page.getByRole("link", { name: "Runs", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Trigger Run", exact: true }),
  ).toBeDisabled()
  await page
    .getByRole("combobox", { name: "Language / 语言" })
    .selectOption("zh-CN")
  await expect(
    page.getByText(
      "run_netflow_dataset_not_ready（选中的 NetFlow 数据集不可用）",
      { exact: false },
    ),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "开始比对", exact: true }),
  ).toBeDisabled()
  await page
    .getByRole("combobox", { name: "Language / 语言" })
    .selectOption("en")
  await expect(
    page.getByText("Run inputs are not ready.", { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Trigger Run", exact: true }),
  ).toBeDisabled()
})

test("preserves an unknown source validation status across language changes", async ({
  page,
}) => {
  await page.route(
    `**/api/v1/projects/${projects[0].id}/cloudatlas-source-instances`,
    (route) =>
      route.fulfill({
        json: {
          data: [
            {
              ...cloudatlasSources[projects[0].id].data[0],
              validation_status: "constructor",
            },
          ],
          count: 1,
          can_manage: false,
        },
      }),
  )
  await page.goto("/?view=inputs")
  await page.getByRole("link", { name: "CloudAtlas", exact: true }).click()
  await expect(
    page.getByRole("cell", { name: "constructor", exact: true }),
  ).toBeVisible()
  await page
    .getByRole("combobox", { name: "Language / 语言" })
    .selectOption("zh-CN")
  await expect(
    page.getByRole("cell", { name: "constructor", exact: true }),
  ).toBeVisible()
})

test("keeps the selected upload and project while translating an existing rejection", async ({
  page,
}) => {
  let rejectionMessage = "The workbook is malformed."
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    async (route) => {
      if (route.request().method() !== "POST") return route.fallback()
      return route.fulfill({
        status: 422,
        json: {
          detail: {
            code: "malformed_workbook",
            message: rejectionMessage,
          },
        },
      })
    },
  )
  await page.goto("/?view=inputs")
  const input = page.getByLabel("XLSX file", { exact: true })
  await input.setInputFiles({
    name: "Customer-English-原始文件.xlsx",
    mimeType:
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: Buffer.from("invalid workbook"),
  })
  await page
    .locator("form")
    .filter({ has: input })
    .getByRole("button", { name: "Upload", exact: true })
    .click()
  await expect(
    page.getByText("The workbook is malformed.", { exact: false }),
  ).toBeVisible()
  await page
    .getByRole("combobox", { name: "Language / 语言" })
    .selectOption("zh-CN")
  await expect(
    page.getByText("工作簿格式损坏。", { exact: false }),
  ).toBeVisible()
  await expect(
    page.getByRole("combobox", { name: "项目", exact: true }),
  ).toHaveValue(projects[0].id)
  await expect(page.locator('input[type="file"]').first()).toHaveValue(
    /Customer-English-原始文件\.xlsx$/,
  )
  await page
    .getByRole("combobox", { name: "Language / 语言" })
    .selectOption("en")
  await expect(
    page.getByText("The workbook is malformed.", { exact: false }),
  ).toBeVisible()
  await expect(input).toHaveValue(/Customer-English-原始文件\.xlsx$/)
  rejectionMessage = "__proto__"
  await page
    .locator("form")
    .filter({ has: input })
    .getByRole("button", { name: "Upload", exact: true })
    .click()
  await expect(page.getByText("__proto__", { exact: true })).toBeVisible()
  await page
    .getByRole("combobox", { name: "Language / 语言" })
    .selectOption("zh-CN")
  await expect(page.getByText("__proto__", { exact: true })).toBeVisible()
})

test("shows a fresh Trigger action after a terminal pre-Run launch", async ({
  page,
}) => {
  const triggerKeys: string[] = []
  let terminalLaunch = false
  await page.route(
    `**/api/v1/projects/${projects[0].id}/governance-runs*`,
    async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          json: {
            data: [],
            count: 0,
            can_trigger: true,
            ready: true,
            input_preview: confirmedInputs,
            can_operate: true,
            readiness_code: null,
            launch_blocking_code: null,
          },
        })
        return
      }
      triggerKeys.push(route.request().headers()["idempotency-key"] ?? "")
      if (!terminalLaunch) {
        terminalLaunch = true
        await route.fulfill({
          status: 409,
          json: {
            detail: {
              code: "run_launch_terminal_use_new_trigger",
              message: "Use a new Trigger ID.",
            },
          },
        })
        return
      }
      await route.fulfill({
        json: {
          accepted: true,
          agent_compose_run_id: "a".repeat(64),
          agent_compose_status: "RUN_STATUS_PENDING",
          governance_run_id: null,
        },
      })
    },
  )

  await page.goto("/?view=inputs")
  await page.getByRole("link", { name: "Runs", exact: true }).click()
  await page.getByLabel("Use these versions for this comparison").check()
  await page.getByRole("button", { name: "Trigger Run" }).click()
  await expect(page.getByRole("status")).toHaveText(
    "The previous launch ended before creating a Run. Use a new Trigger ID.",
  )
  await page.getByLabel("Use these versions for this comparison").check()
  await page.getByRole("button", { name: "Trigger Run" }).click()
  await expect(
    page.getByText(
      "Governance Session accepted. Waiting for the Runner to start.",
    ),
  ).toBeVisible()
  await expect.poll(() => triggerKeys.length).toBe(2)
  expect(triggerKeys[0]).toBeTruthy()
  expect(triggerKeys[1]).toBeTruthy()
  expect(triggerKeys[1]).not.toBe(triggerKeys[0])
})

test("selects the first Project and switches its Profile and upload list", async ({
  page,
}) => {
  await page.goto("/?view=inputs")

  const projectSelect = page.getByRole("combobox", { name: "Project" })
  await expect(projectSelect).toHaveValue(projects[0].id)
  await page.getByText("Profile details", { exact: true }).press("Enter")
  await expect(
    page.getByText(profiles[projects[0].id].id).first(),
  ).toBeVisible()
  await expect(page.getByText("north-assets.xlsx")).toBeVisible()

  await projectSelect.selectOption(projects[1].id)

  await expect(projectSelect).toHaveValue(projects[1].id)
  await page.getByText("Profile details", { exact: true }).press("Enter")
  await expect(page.getByText(profiles[projects[1].id].id)).toBeVisible()
  await expect(page.getByText("No accepted uploads yet.")).toBeVisible()
})

test("loads every page of accessible Projects into the dropdown", async ({
  page,
}) => {
  const allProjects = [
    ...projects,
    ...Array.from({ length: 99 }, (_, index) => ({
      ...projects[0],
      id: `40000000-0000-0000-0000-${String(index).padStart(12, "0")}`,
      name: `Paged Project ${index + 3}`,
    })),
  ]
  await page.route("**/api/v1/projects/?*", (route) => {
    const url = new URL(route.request().url())
    const skip = Number(url.searchParams.get("skip") ?? 0)
    const limit = Number(url.searchParams.get("limit") ?? 100)
    return route.fulfill({
      json: {
        data: allProjects.slice(skip, skip + limit),
        count: allProjects.length,
      },
    })
  })
  await page.goto("/?view=inputs")

  await expect(
    page.getByRole("combobox", { name: "Project" }).getByRole("option", {
      name: "Paged Project 101",
      exact: true,
    }),
  ).toHaveAttribute("value", allProjects[100].id)
})

test("shows loading, empty, and failure states for Projects", async ({
  page,
}) => {
  await page.route("**/api/v1/projects/?*", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 500))
    await route.fulfill({ json: { data: projects, count: projects.length } })
  })
  await page.goto("/?view=inputs")
  await expect(page.getByRole("status")).toHaveText("Loading Projects…")

  await page.route("**/api/v1/projects/?*", (route) =>
    route.fulfill({ json: { data: [], count: 0 } }),
  )
  await page.reload()
  await expect(
    page.getByRole("heading", { name: "Your first comparison starts here" }),
  ).toBeVisible()

  await page.route("**/api/v1/projects/?*", (route) =>
    route.fulfill({ status: 500 }),
  )
  await page.reload()
  await expect(page.getByText("Projects could not be loaded")).toBeVisible({
    timeout: 15_000,
  })
})

test("selects an accepted upload as the current Project input", async ({
  page,
}) => {
  let currentUploadId: string | null = null
  let selectionRequests = 0
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads/${uploads[projects[0].id].data[0].id}/select`,
    async (route) => {
      selectionRequests += 1
      currentUploadId = uploads[projects[0].id].data[0].id
      await route.fulfill({ json: uploads[projects[0].id].data[0] })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    (route) =>
      route.fulfill({
        json: {
          ...uploads[projects[0].id],
          current_customer_upload_id: currentUploadId,
        },
      }),
  )
  await page.goto("/?view=inputs")

  await expect(page.getByText("Project input is not ready.")).toBeVisible()
  await page.getByRole("button", { name: "Set as current input" }).click()

  const currentDetails = page
    .locator("details")
    .filter({ has: page.getByText("Current input details", { exact: true }) })
  await expect(
    currentDetails.getByText(uploads[projects[0].id].data[0].id, {
      exact: true,
    }),
  ).toBeHidden()
  await currentDetails.locator("summary").press("Enter")
  await expect(
    currentDetails.getByText(uploads[projects[0].id].data[0].id, {
      exact: true,
    }),
  ).toBeVisible()
  await expect(page.getByText("Current", { exact: true }).first()).toBeVisible()
  expect(selectionRequests).toBe(1)
})

test("keeps read-only and Archived Projects visible without input controls", async ({
  page,
}) => {
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    (route) =>
      route.fulfill({
        json: {
          ...uploads[projects[0].id],
          can_upload: false,
          can_select: false,
        },
      }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/netflow-datasets*`,
    (route) =>
      route.fulfill({
        json: {
          ...netflowDatasets[projects[0].id],
          can_upload: false,
          can_select: false,
        },
      }),
  )
  await page.goto("/?view=inputs")

  await expect(
    page.getByText(
      "You have read-only access to CustomerUpload inputs for this Project.",
    ),
  ).toBeVisible()
  await expect(page.getByLabel("XLSX file")).not.toBeVisible()
  await expect(
    page.getByRole("button", { name: "Set as current input" }),
  ).not.toBeVisible()

  const projectSelect = page.getByRole("combobox", { name: "Project" })
  await projectSelect.selectOption(projects[1].id)
  await expect(
    page.getByText("Archived Project", { exact: true }),
  ).toBeVisible()
  await expect(page.getByText("Existing inputs remain visible")).toBeVisible()
  await expect(page.getByLabel("XLSX file")).not.toBeVisible()
  await expect(page.getByLabel("NetFlow dataset file")).not.toBeVisible()
  await expect(
    page.getByRole("button", { name: /Select .*current NetFlowDataset/ }),
  ).not.toBeVisible()
  await expect(
    page.getByRole("button", { name: "Clear current" }),
  ).not.toBeVisible()
})

test("keeps NetFlow quality visible and identities behind keyboard-copyable details", async ({
  page,
}) => {
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"])
  await page.route(
    `**/api/v1/projects/${projects[0].id}/netflow-datasets*`,
    (route) =>
      route.fulfill({
        json: {
          ...netflowDatasets[projects[0].id],
          data: [netflowDatasets[projects[0].id].data[1]],
          count: 11,
        },
      }),
  )
  await page.goto("/?view=inputs")

  await expect(
    page.getByText("Current NetFlowDataset", { exact: true }),
  ).toBeVisible()
  await expect(page.getByText("Raw records").first()).toBeVisible()
  await expect(page.getByText("Valid activity records").first()).toBeVisible()
  await expect(page.getByText("Isolated records").first()).toBeVisible()
  await expect(page.getByText("12", { exact: true })).toBeVisible()
  await expect(page.getByText("9", { exact: true })).toBeVisible()
  await expect(page.getByText("3", { exact: true }).first()).toBeVisible()
  await expect(page.getByText("invalid_timestamp: 2")).toBeVisible()
  await expect(page.getByText("Duplicate groups").first()).toBeVisible()
  await expect(page.getByText("Duplicate records").first()).toBeVisible()
  await expect(page.getByText(/2026-08-01 00:00:00 UTC/).first()).toBeVisible()
  const netflow = page.getByRole("region", {
    name: "NetFlowDatasets",
    exact: true,
  })
  for (const width of [1365, 390]) {
    await page.setViewportSize({ width, height: 844 })
    await expect(
      netflow.getByText("north-netflow.csv", { exact: true }),
    ).toBeVisible()
    await expect(netflow.getByText("invalid_timestamp: 2")).toBeVisible()
    await expect(
      netflow
        .getByText("Valid time range: Not available — Not available")
        .filter({ visible: true }),
    ).toBeVisible()
    await expect(
      netflow.getByText(/^Accepted: /).filter({ visible: true }),
    ).toHaveCount(2)
    for (const dataset of northNetflowDatasets) {
      const details = netflow
        .locator("details:visible")
        .filter({ hasText: dataset.id })
      await expect(
        details.getByText(dataset.id, { exact: true }),
      ).not.toBeVisible()
      await expect(
        details.getByText(dataset.raw_sha256, { exact: true }),
      ).not.toBeVisible()
      await details.locator("summary").focus()
      await page.keyboard.press("Enter")
      for (const [label, value] of [
        ["Dataset ID", dataset.id],
        ["RAW SHA-256", dataset.raw_sha256],
      ]) {
        await expect(details.getByText(value, { exact: true })).toBeVisible()
        await details
          .getByRole("button", { name: `Copy ${label}`, exact: true })
          .focus()
        await page.keyboard.press("Enter")
        await expect
          .poll(() => page.evaluate(() => navigator.clipboard.readText()))
          .toBe(value)
      }
      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
        .toBeLessThanOrEqual(width)
      await details.locator("summary").focus()
      await page.keyboard.press("Enter")
    }
  }
})

test("keeps both file pickers and upload actions within desktop and narrow viewports", async ({
  page,
}) => {
  // Keep interception active; one-shot listeners toggle it asynchronously.
  const choosers: FileChooser[] = []
  page.on("filechooser", (chooser) => choosers.push(chooser))
  await page.goto("/?view=inputs")
  for (const width of [1365, 390]) {
    await page.setViewportSize({ width, height: 844 })
    for (const [label, extension] of [
      ["XLSX file", "xlsx"],
      ["NetFlow dataset file", "csv"],
    ]) {
      const input = page.getByLabel(label, { exact: true })
      const form = page.locator("form").filter({ has: input })
      const picker = form.getByRole("button", {
        name: "Choose file",
        exact: true,
      })
      await expect(picker).toBeEnabled()
      await picker.focus()
      await expect(picker).toBeFocused()
      await page.keyboard.press("Enter")
      await expect.poll(() => choosers.length).toBe(1)
      const chooser = choosers.shift()!
      const filename = `${"long-selected-filename-".repeat(8)}.${extension}`
      await chooser.setFiles({
        name: filename,
        mimeType: "application/octet-stream",
        buffer: Buffer.from("mock input"),
      })
      await expect(form.getByText(filename, { exact: true })).toBeVisible()
      await expect(input).toHaveValue(new RegExp(`\\.${extension}$`))
      const upload = form.getByRole("button", { name: "Upload", exact: true })
      await expect(upload).toBeEnabled()
      for (const control of [input, picker, upload]) {
        const bounds = await control.boundingBox()
        expect(bounds).not.toBeNull()
        expect(bounds!.x).toBeGreaterThanOrEqual(0)
        expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width)
      }
      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
        .toBeLessThanOrEqual(width)
    }
  }
})

test("uploads a NetFlowDataset and refreshes the list", async ({ page }) => {
  let uploaded = false
  const newDataset = {
    ...netflowDatasets[projects[0].id].data[0],
    id: "21000000-0000-0000-0000-000000000003",
    display_filename: "new-netflow.csv",
    raw_sha256: "1".repeat(64),
  }
  await page.route(
    `**/api/v1/projects/${projects[0].id}/netflow-datasets*`,
    async (route) => {
      if (route.request().method() === "POST") {
        uploaded = true
        await route.fulfill({ status: 201, json: newDataset })
        return
      }
      await route.fulfill({
        json: uploaded
          ? {
              ...netflowDatasets[projects[0].id],
              data: [newDataset, ...netflowDatasets[projects[0].id].data],
              count: 3,
            }
          : netflowDatasets[projects[0].id],
      })
    },
  )
  await page.goto("/?view=inputs")

  const fileInput = page.getByLabel("NetFlow dataset file")
  await fileInput.setInputFiles({
    name: "new-netflow.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("source_record_key,src_ip"),
  })
  await page.getByRole("button", { name: "Upload" }).last().click()

  await expect(
    page.getByText("NetFlowDataset upload accepted successfully."),
  ).toBeVisible()
  await expect(fileInput).toHaveValue("")
  await expect(page.getByText("new-netflow.csv").first()).toBeVisible()
})

test("selects and clears the current NetFlowDataset", async ({ page }) => {
  const secondId = netflowDatasets[projects[0].id].data[1].id
  let currentId: string | null =
    netflowDatasets[projects[0].id].current_netflow_dataset_id
  await page.route(
    new RegExp(
      `/api/v1/projects/${projects[0].id}/netflow-datasets(?:/.*)?(?:\\?.*)?$`,
    ),
    async (route) => {
      const url = new URL(route.request().url())
      if (
        route.request().method() === "POST" &&
        url.pathname.endsWith(`/${secondId}/select`)
      ) {
        currentId = secondId
        await route.fulfill({ json: netflowDatasets[projects[0].id].data[1] })
        return
      }
      if (
        route.request().method() === "DELETE" &&
        url.pathname.endsWith("/current-selection")
      ) {
        currentId = null
        await route.fulfill({ status: 204 })
        return
      }
      await route.fulfill({
        json: {
          ...netflowDatasets[projects[0].id],
          current_netflow_dataset_id: currentId,
          current_netflow_dataset:
            currentId === null
              ? null
              : (netflowDatasets[projects[0].id].data.find(
                  (dataset) => dataset.id === currentId,
                ) ?? null),
        },
      })
    },
  )
  await page.goto("/?view=inputs")

  await page
    .getByRole("button", { name: /Select north-netflow-older\.txt/ })
    .click()
  await expect(
    page.getByText("Current NetFlowDataset updated successfully."),
  ).toBeVisible()
  await expect(page.getByText("north-netflow-older.txt").first()).toBeVisible()

  await page.getByRole("button", { name: "Clear current" }).click()
  await expect(
    page.getByText("Current NetFlowDataset cleared successfully."),
  ).toBeVisible()
  await expect(page.getByText("No current NetFlowDataset")).toBeVisible()
})

for (const status of [201, 200]) {
  test(`refreshes and clears the file after a ${status} upload success`, async ({
    page,
  }) => {
    let accepted = false
    const acceptedUpload = {
      ...uploads[projects[0].id].data[0],
      id: `20000000-0000-0000-0000-000000000${status}`,
      display_filename: "new-assets.xlsx",
      raw_sha256: "b".repeat(64),
    }
    await page.route(
      `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
      async (route) => {
        if (route.request().method() === "POST") {
          accepted = true
          await route.fulfill({ status, json: acceptedUpload })
          return
        }
        await route.fulfill({
          json: accepted
            ? {
                data: [acceptedUpload],
                count: 1,
                current_customer_upload_id: null,
                can_upload: true,
                can_select: true,
              }
            : uploads[projects[0].id],
        })
      },
    )
    await page.goto("/?view=inputs")

    const fileInput = page.getByLabel("XLSX file")
    await fileInput.setInputFiles({
      name: "new-assets.xlsx",
      mimeType:
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      buffer: Buffer.from("mock workbook"),
    })
    await page
      .locator("form")
      .filter({ has: page.getByLabel("XLSX file") })
      .getByRole("button", { name: "Upload" })
      .click()

    await expect(page.getByText("Upload accepted successfully.")).toBeVisible()
    await expect(fileInput).toHaveValue("")
    await expect(page.getByText("new-assets.xlsx")).toBeVisible()
  })
}

test("lets an Admin validate, enable, configure, and disable a CloudAtlas source", async ({
  page,
}) => {
  await page.route("**/api/v1/users/me", (route) =>
    route.fulfill({
      json: {
        email: "admin@example.com",
        full_name: "Test Admin",
        id: "30000000-0000-0000-0000-000000000002",
        is_active: true,
        is_superuser: true,
      },
    }),
  )
  let source: CloudAtlasSourcePublic = {
    ...cloudatlasSources[projects[0].id].data[0],
  }
  const requests: Array<{ method: string; path: string; body: unknown }> = []
  const handleSourceRequest = async (route: Route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.method() === "GET") {
      await route.fulfill({
        json: { data: [source], count: 1, can_manage: true },
      })
      return
    }
    requests.push({
      method: request.method(),
      path: url.pathname,
      body: request.postDataJSON(),
    })
    if (url.pathname.endsWith("/validate")) {
      source = {
        ...source,
        validation_status: "validated",
        validated_fingerprint: "abcdef0123456789".repeat(4),
      }
    } else if (url.pathname.endsWith("/enable")) {
      source = { ...source, enabled: true }
    } else if (url.pathname.endsWith("/disable")) {
      source = { ...source, enabled: false }
    } else if (request.method() === "PATCH") {
      const body = request.postDataJSON() as {
        instance_id: string
        capset_id: string
      }
      source = {
        ...source,
        instance_id: body.instance_id,
        capset_id: body.capset_id,
        enabled: false,
        validation_status: "not_validated",
        validated_fingerprint: null,
      }
    }
    await route.fulfill({ json: source })
  }
  const sourceUrl = `**/api/v1/projects/${projects[0].id}/cloudatlas-source-instances`
  await page.route(sourceUrl, handleSourceRequest)
  await page.route(`${sourceUrl}/**`, handleSourceRequest)
  await page.goto("/?view=inputs")
  await page.getByRole("link", { name: "CloudAtlas", exact: true }).click()

  await expect(page.getByText("CloudAtlas source")).toBeVisible()
  const tokenInput = page.getByLabel("Capset token")
  await expect(tokenInput).toHaveAttribute("type", "password")
  await tokenInput.fill("transient-test-token")
  await page.getByRole("button", { name: "Validate source" }).click()
  await expect(page.getByText("Validated", { exact: true })).toBeVisible()
  await expect(tokenInput).toHaveValue("")
  const sourceDetails = page.locator("details").filter({
    has: page.getByText("Source details", { exact: true }),
  })
  const fingerprint = "abcdef0123456789".repeat(4)
  await expect(
    sourceDetails.getByText(fingerprint, { exact: true }),
  ).toBeHidden()
  await sourceDetails.locator("summary").focus()
  await page.keyboard.press("Enter")
  await expect(
    sourceDetails.getByText(fingerprint, { exact: true }),
  ).toBeVisible()
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"])
  await sourceDetails.getByRole("button", { name: "Copy Fingerprint" }).focus()
  await page.keyboard.press("Enter")
  await expect
    .poll(() => page.evaluate(() => navigator.clipboard.readText()))
    .toBe(fingerprint)

  await page.getByRole("button", { name: "Enable source" }).click()
  await expect(page.getByText("Enabled", { exact: true })).toBeVisible()
  await page.getByLabel("OctoBus Instance ID").fill("cloudatlas-replacement")
  await page.getByRole("button", { name: "Save binding" }).click()
  await expect(
    page.getByRole("cell", { name: "cloudatlas-replacement", exact: true }),
  ).toBeVisible()

  source = {
    ...source,
    enabled: true,
    validation_status: "validated",
    validated_fingerprint: "abcdef0123456789".repeat(4),
  }
  await page.reload()
  await page.getByRole("link", { name: "CloudAtlas", exact: true }).click()
  await page.getByRole("button", { name: "Disable source" }).click()
  await expect(page.getByText("Disabled", { exact: true })).toBeVisible()

  expect(requests.map((request) => [request.method, request.path])).toEqual([
    ["POST", expect.stringMatching(/\/validate$/)],
    ["POST", expect.stringMatching(/\/enable$/)],
    ["PATCH", expect.stringMatching(/50000000-0000-0000-0000-000000000001$/)],
    ["POST", expect.stringMatching(/\/disable$/)],
  ])
  expect(requests[0].body).toEqual({ capset_token: "transient-test-token" })
})

test("keeps the local session after a structured CloudAtlas authentication failure", async ({
  page,
}) => {
  await page.route("**/api/v1/users/me", (route) =>
    route.fulfill({
      json: {
        email: "admin@example.com",
        full_name: "Test Admin",
        id: "30000000-0000-0000-0000-000000000002",
        is_active: true,
        is_superuser: true,
      },
    }),
  )
  const source = cloudatlasSources[projects[0].id].data[0]
  const sourceUrl = `**/api/v1/projects/${projects[0].id}/cloudatlas-source-instances`
  await page.route(sourceUrl, (route) =>
    route.fulfill({
      json: { data: [source], count: 1, can_manage: true },
    }),
  )
  await page.route(`${sourceUrl}/**`, (route) =>
    route.fulfill({
      status: 401,
      json: {
        detail: {
          code: "cloudatlas_authentication_failed",
          message: "CloudAtlas authentication failed.",
        },
      },
    }),
  )
  await page.goto("/?view=inputs")
  await page.getByRole("link", { name: "CloudAtlas", exact: true }).click()

  const tokenInput = page.getByLabel("Capset token")
  await tokenInput.fill("transient-test-token")
  await page.getByRole("button", { name: "Validate source" }).click()

  await expect(tokenInput).toHaveValue("")
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("access_token")))
    .toBe("component-token")
  await expect(page).toHaveURL((url) => url.pathname === "/")
  await expect(
    page.getByText("CloudAtlas source validation failed."),
  ).toBeVisible()
})

test("clears the local session when the current user no longer exists", async ({
  page,
}) => {
  await page.route("**/api/v1/users/me", (route) =>
    route.fulfill({ status: 404, json: { detail: "User not found" } }),
  )

  await page.goto("/?view=inputs")

  await expect(page).toHaveURL("/login", { timeout: 15_000 })
  expect(
    await page.evaluate(() => localStorage.getItem("access_token")),
  ).toBeNull()
})

test("lets an Admin manage an older enabled source from disabled history", async ({
  page,
}) => {
  const newerDisabled = { ...cloudatlasSources[projects[0].id].data[0] }
  let olderEnabled = {
    ...newerDisabled,
    id: "50000000-0000-0000-0000-000000000002",
    instance_id: "cloudatlas-older-enabled",
    enabled: true,
    validation_status: "validated",
    validated_fingerprint: "123456789abcdef0".repeat(4),
  }
  let disablePath: string | null = null
  const sourceUrl = `**/api/v1/projects/${projects[0].id}/cloudatlas-source-instances`
  await page.route(sourceUrl, (route) =>
    route.fulfill({
      json: {
        data: [newerDisabled, olderEnabled],
        count: 2,
        can_manage: true,
      },
    }),
  )
  await page.route(`${sourceUrl}/**`, async (route) => {
    disablePath = new URL(route.request().url()).pathname
    olderEnabled = { ...olderEnabled, enabled: false }
    await route.fulfill({ json: olderEnabled })
  })
  await page.goto("/?view=inputs")
  await page.getByRole("link", { name: "CloudAtlas", exact: true }).click()

  await expect(page.getByLabel("OctoBus Instance ID")).toHaveValue(
    "cloudatlas-older-enabled",
  )
  await page.getByRole("button", { name: "Disable source" }).click()
  await expect(page.getByText("CloudAtlas source disabled.")).toBeVisible()
  expect(disablePath).toMatch(/50000000-0000-0000-0000-000000000002\/disable$/)

  const newerRow = page
    .getByRole("row")
    .filter({ hasText: newerDisabled.instance_id })
  await newerRow.getByRole("button", { name: "Manage source" }).click()
  await expect(page.getByLabel("OctoBus Instance ID")).toHaveValue(
    newerDisabled.instance_id,
  )
})

test("shows only the server safe upload explanation", async ({ page }) => {
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 422,
          json: {
            detail: {
              code: "invalid_required_value",
              message: "The workbook contains an invalid required value.",
              debug: "sensitive-cell-value",
            },
          },
        })
        return
      }
      await route.fulfill({ json: uploads[projects[0].id] })
    },
  )
  await page.goto("/?view=inputs")
  await page.getByLabel("XLSX file").setInputFiles({
    name: "invalid.xlsx",
    mimeType:
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: Buffer.from("invalid workbook"),
  })
  await page
    .locator("form")
    .filter({ has: page.getByLabel("XLSX file") })
    .getByRole("button", { name: "Upload" })
    .click()

  await expect(
    page.getByText("The workbook contains an invalid required value."),
  ).toBeVisible()
  await expect(page.getByText("sensitive-cell-value")).not.toBeVisible()
})

test("shows the six Run steps and triggers with a caller-owned stable ID", async ({
  page,
}) => {
  const run = {
    id: "60000000-0000-0000-0000-000000000001",
    trigger_id: "browser-trigger",
    session_id: "b".repeat(64),
    status: "COMPLETED",
    customer_upload_id: uploads[projects[0].id].data[0].id,
    customer_upload_sha256: "a".repeat(64),
    customer_upload_profile_id: profiles[projects[0].id].id,
    customer_upload_profile_version: 1,
    source_instance_id: cloudatlasSources[projects[0].id].data[0].id,
    cloudatlas_validated_fingerprint: "c".repeat(64),
    cloudatlas_capset_id: "cloudatlas-readonly",
    cloudatlas_method: "cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets",
    package_sha256: "d".repeat(64),
    descriptor_sha256: "e".repeat(64),
    runner_build_version: "runner-v1",
    created_at: "2026-07-30T13:00:00Z",
    completed_at: "2026-07-30T13:01:00Z",
    steps: [
      "LOAD_CUSTOMER",
      "PULL_CLOUDATLAS",
      "NORMALIZE",
      "RESOLVE",
      "CHECK_FINDINGS",
      "PUBLISH",
    ].map((step_code) => ({
      step_code,
      status: "SUCCEEDED",
      attempt: 1,
      input_hash: "f".repeat(64),
      output_hash: "1".repeat(64),
      error_code: null,
      started_at: "2026-07-30T13:00:00Z",
      completed_at: "2026-07-30T13:01:00Z",
    })),
    snapshots: [
      {
        id: "70000000-0000-0000-0000-000000000001",
        source_type: "CUSTOMER_UPLOAD",
        content_sha256: "2".repeat(64),
        schema_fingerprint: "3".repeat(64),
        method_fingerprint: null,
        record_count: 2,
        created_at: "2026-07-30T13:00:20Z",
      },
      {
        id: "70000000-0000-0000-0000-000000000002",
        source_type: "CLOUDATLAS",
        content_sha256: "4".repeat(64),
        schema_fingerprint: "5".repeat(64),
        method_fingerprint: "6".repeat(64),
        record_count: 1,
        created_at: "2026-07-30T13:00:40Z",
      },
    ],
  }
  let idempotencyKey = ""
  await page.route(
    `**/api/v1/projects/${projects[0].id}/governance-runs`,
    async (route) => {
      if (route.request().method() === "POST") {
        idempotencyKey = route.request().headers()["idempotency-key"] ?? ""
        await route.fulfill({
          status: 202,
          json: {
            accepted: true,
            agent_compose_run_id: "7".repeat(64),
            agent_compose_status: "RUN_STATUS_PENDING",
            governance_run_id: null,
          },
        })
        return
      }
      await route.fulfill({
        json: {
          data: [run],
          count: 1,
          can_trigger: true,
          ready: true,
          input_preview: confirmedInputs,
          can_operate: true,
          readiness_code: null,
        },
      })
    },
  )
  await page.goto("/?view=inputs")
  await page.getByRole("link", { name: "Runs", exact: true }).click()

  await expect(page.getByText("Inputs ready")).toBeVisible()
  for (const step of [
    "LOAD_CUSTOMER",
    "PULL_CLOUDATLAS",
    "NORMALIZE",
    "RESOLVE",
    "CHECK_FINDINGS",
    "PUBLISH",
  ]) {
    await expect(page.getByRole("cell", { name: step })).toBeVisible()
  }
  await expect(page.getByText("CUSTOMER_UPLOAD")).toBeVisible()
  await expect(page.getByText("CLOUDATLAS", { exact: true })).toBeVisible()

  await page.getByLabel("Use these versions for this comparison").check()
  await page.getByRole("button", { name: "Trigger Run" }).click()
  await expect(
    page.getByText(
      "Governance Session accepted. Waiting for the Runner to start.",
    ),
  ).toBeVisible()
  expect(idempotencyKey).toMatch(/^[0-9a-f-]{36}$/)
})

test("Operator can Retry or explicitly Rerun a failed Governance Run", async ({
  page,
}) => {
  const runId = "60000000-0000-0000-0000-000000000099"
  const failedRun = {
    id: runId,
    trigger_id: "failed-trigger",
    session_id: "7".repeat(64),
    status: "FAILED_DATA",
    customer_upload_id: "20000000-0000-0000-0000-000000000001",
    customer_upload_sha256: "a".repeat(64),
    customer_upload_profile_id: "10000000-0000-0000-0000-000000000001",
    customer_upload_profile_version: 1,
    source_instance_id: "50000000-0000-0000-0000-000000000001",
    cloudatlas_validated_fingerprint: "b".repeat(64),
    cloudatlas_capset_id: "cloudatlas-readonly",
    cloudatlas_method: "cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets",
    package_sha256: "c".repeat(64),
    descriptor_sha256: "d".repeat(64),
    runner_build_version: "runner-v1",
    created_at: "2026-07-30T13:00:00Z",
    completed_at: null,
    session_terminal_at: "2026-07-30T13:01:00Z",
    session_recovery_code: null,
    steps: [
      {
        step_code: "LOAD_CUSTOMER",
        status: "SUCCEEDED",
        attempt: 1,
        input_hash: "a".repeat(64),
        output_hash: "a".repeat(64),
        error_code: null,
        started_at: "2026-07-30T13:00:00Z",
        completed_at: "2026-07-30T13:00:10Z",
      },
      {
        step_code: "PULL_CLOUDATLAS",
        status: "FAILED",
        attempt: 2,
        input_hash: "b".repeat(64),
        output_hash: null,
        error_code: "cloudatlas_snapshot_failed",
        started_at: "2026-07-30T13:00:11Z",
        completed_at: "2026-07-30T13:00:20Z",
      },
    ],
    snapshots: [
      {
        id: "70000000-0000-0000-0000-000000000099",
        source_type: "CUSTOMER_UPLOAD",
        content_sha256: "a".repeat(64),
        schema_fingerprint: "e".repeat(64),
        method_fingerprint: null,
        record_count: 2,
        created_at: "2026-07-30T13:00:10Z",
      },
    ],
    reused_snapshot_count: 1,
    can_retry: true,
    can_rerun: true,
    blocking_code: null,
  }
  const actions: string[] = []
  const rerunKeys: string[] = []
  let terminalLaunch = false
  await page.route(
    `**/api/v1/projects/${projects[0].id}/governance-runs/${runId}/**`,
    async (route) => {
      const action =
        new URL(route.request().url()).pathname.split("/").pop() ?? ""
      actions.push(action)
      if (action === "rerun") {
        rerunKeys.push(route.request().headers()["idempotency-key"] ?? "")
        if (rerunKeys.length === 1) {
          terminalLaunch = true
          await route.fulfill({
            status: 409,
            json: {
              detail: {
                code: "run_launch_terminal_use_new_trigger",
                message: "Use a new Trigger ID.",
              },
            },
          })
          return
        }
      }
      await route.fulfill({
        status: 202,
        json: {
          accepted: true,
          action,
          governance_run_id: runId,
          source_governance_run_id: runId,
          session_id: failedRun.session_id,
          agent_compose_run_id: "8".repeat(64),
          agent_compose_status: "RUNNING",
          code: null,
        },
      })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/governance-runs`,
    (route) =>
      route.fulfill({
        json: {
          data: [failedRun],
          count: 1,
          can_trigger: false,
          ready: true,
          input_preview: confirmedInputs,
          can_operate: true,
          readiness_code: null,
          launch_blocking_code: terminalLaunch
            ? "run_launch_terminal_use_new_trigger"
            : null,
        },
      }),
  )
  await page.goto("/?view=inputs")
  await page.getByRole("link", { name: "Runs", exact: true }).click()

  await expect(page.getByText("FAILED_DATA", { exact: true })).toBeVisible()
  await expect(page.getByText("Snapshots reused: 1")).toBeVisible()
  await expect(
    page
      .getByRole("row")
      .filter({ hasText: "PULL_CLOUDATLAS" })
      .getByRole("cell", { name: "2", exact: true }),
  ).toBeVisible()
  await page.getByRole("button", { name: "Retry same Session" }).click()
  await expect(
    page.getByText("Retry accepted for the same Governance Run and Session."),
  ).toBeVisible()
  await page
    .getByRole("combobox", { name: "Language / 语言" })
    .selectOption("zh-CN")
  await expect(page.getByRole("status")).toContainText("重试")
  await expect(page.getByRole("button", { name: /重试/ })).toBeVisible()
  await page
    .getByRole("combobox", { name: "Language / 语言" })
    .selectOption("en")
  await expect(
    page.getByText("Retry accepted for the same Governance Run and Session."),
  ).toBeVisible()
  await page.getByRole("button", { name: "Rerun with current inputs" }).click()
  await expect(page.getByRole("status")).toHaveText(
    "The previous launch ended before creating a Run. Use a new Trigger ID.",
  )
  await page.getByRole("button", { name: "Rerun with current inputs" }).click()
  await expect(
    page.getByText("Rerun accepted with current inputs and a new Trigger ID."),
  ).toBeVisible()
  expect(actions).toEqual(["retry", "rerun", "rerun"])
  expect(rerunKeys[0]).toBeTruthy()
  expect(rerunKeys[1]).toBeTruthy()
  expect(rerunKeys[1]).not.toBe(rerunKeys[0])
})

test("hides Rerun while a same-Session Retry is in progress", async ({
  page,
}) => {
  const retryPreparedRun = {
    id: "60000000-0000-0000-0000-000000000097",
    trigger_id: "retry-prepared",
    session_id: "6".repeat(64),
    status: "RUNNING",
    customer_upload_id: "20000000-0000-0000-0000-000000000001",
    customer_upload_sha256: "a".repeat(64),
    customer_upload_profile_id: "10000000-0000-0000-0000-000000000001",
    customer_upload_profile_version: 1,
    source_instance_id: "50000000-0000-0000-0000-000000000001",
    cloudatlas_validated_fingerprint: "b".repeat(64),
    cloudatlas_capset_id: "cloudatlas-readonly",
    cloudatlas_method: "cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets",
    package_sha256: "c".repeat(64),
    descriptor_sha256: "d".repeat(64),
    runner_build_version: "runner-v1",
    created_at: "2026-07-30T13:00:00Z",
    completed_at: null,
    session_terminal_at: "2026-07-30T13:01:00Z",
    session_recovery_code: "retry_prepared",
    steps: [],
    snapshots: [],
    reused_snapshot_count: 0,
    can_retry: true,
    can_rerun: false,
    blocking_code: null,
  }
  await page.route(
    `**/api/v1/projects/${projects[0].id}/governance-runs`,
    (route) =>
      route.fulfill({
        json: {
          data: [retryPreparedRun],
          count: 1,
          can_trigger: false,
          ready: true,
          input_preview: confirmedInputs,
          can_operate: true,
          readiness_code: null,
        },
      }),
  )
  await page.goto("/?view=inputs")
  await page.getByRole("link", { name: "Runs", exact: true }).click()

  await expect(page.getByText("RUNNING", { exact: true })).toBeVisible()
  await expect(page.getByText("Snapshots reused: 0")).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Retry same Session" }),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Rerun with current inputs" }),
  ).toHaveCount(0)
})

for (const role of ["Viewer", "Approver"] as const) {
  test(`${role} receives no recovery controls`, async ({ page }) => {
    await page.route("**/api/v1/users/me", (route) =>
      route.fulfill({
        json: {
          email: `${role.toLowerCase()}@example.com`,
          full_name: `Test ${role}`,
          id: "30000000-0000-0000-0000-000000000001",
          is_active: true,
          is_superuser: false,
        },
      }),
    )
    const runId = "60000000-0000-0000-0000-000000000098"
    await page.route(
      `**/api/v1/projects/${projects[0].id}/governance-runs`,
      (route) =>
        route.fulfill({
          json: {
            data: [
              {
                id: runId,
                trigger_id: "read-only-failure",
                session_id: "9".repeat(64),
                status: "FAILED_PROCESSING",
                customer_upload_id: "20000000-0000-0000-0000-000000000001",
                customer_upload_sha256: "a".repeat(64),
                customer_upload_profile_id:
                  "10000000-0000-0000-0000-000000000001",
                customer_upload_profile_version: 1,
                source_instance_id: "50000000-0000-0000-0000-000000000001",
                cloudatlas_validated_fingerprint: "b".repeat(64),
                cloudatlas_capset_id: "cloudatlas-readonly",
                cloudatlas_method:
                  "cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets",
                package_sha256: "c".repeat(64),
                descriptor_sha256: "d".repeat(64),
                runner_build_version: "runner-v1",
                created_at: "2026-07-30T13:00:00Z",
                completed_at: null,
                session_terminal_at: null,
                session_recovery_code: null,
                steps: [],
                snapshots: [],
                reused_snapshot_count: 0,
                can_retry: false,
                can_rerun: false,
                blocking_code: "run_session_state_unknown",
              },
            ],
            count: 1,
            can_trigger: false,
            ready: true,
            input_preview: confirmedInputs,
            can_operate: true,
            readiness_code: null,
          },
        }),
    )
    await page.goto("/?view=inputs")
    await page.getByRole("link", { name: "Runs", exact: true }).click()

    await expect(page.getByText("Recovery status")).toBeVisible()
    await expect(
      page.getByRole("button", { name: "Retry same Session" }),
    ).toHaveCount(0)
    await expect(
      page.getByRole("button", { name: "Rerun with current inputs" }),
    ).toHaveCount(0)
    await expect(page.getByRole("button", { name: "Trigger Run" })).toHaveCount(
      0,
    )
  })
}
