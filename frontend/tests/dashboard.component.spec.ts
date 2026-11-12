import type { FileChooser, Locator } from "@playwright/test"
import type { CloudAtlasSourcePublic } from "../src/client"
import { requestDigest } from "../src/lib/ledgerIntent"
import { expect, type Page, type Route, test } from "./fixtures"
import { feedback, recordFeedback } from "./utils/interaction-feedback"
import { clickHistoricalLink } from "./utils/legacy-assets"

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
function inputSummary(projectId: string) {
  return {
    contract_version: "input-summary-v1",
    project_id: projectId,
    customer: {
      applied_upload_id: null,
      applied_revision_id: null,
      accepted_upload_count: 1,
      unapplied_upload_count: 1,
    },
    cloud: { sources: [] },
    core_readiness: {
      contract_version: "core-comparison-v2",
      project_id: projectId,
      state: "CUSTOMER_NOT_READY",
      reason_code: "customer_not_ready",
      scope_key: "a".repeat(64),
      scope_confirmation_id: null,
      selection: {
        network_namespace: "north",
        customer: null,
        cloud: null,
        netflow: null,
        history_run_id: null,
      },
      input_sha256: "b".repeat(64),
      expected_current_result_id: null,
      customer: null,
      customer_filename: null,
      customer_applied_at: null,
      clouds: [],
      scope_choices: [],
      can_generate: false,
      can_write: true,
      can_confirm_scope: false,
      sources: [
        {
          source: "CUSTOMER",
          state: "NOT_PROVIDED",
          read_state: "NOT_PROVIDED",
          coverage_state: "NOT_APPLICABLE",
          source_records: null,
          source_addresses: null,
          source_objects: null,
          metadata: {},
        },
        {
          source: "CLOUD",
          state: "NOT_PROVIDED",
          read_state: "NOT_PROVIDED",
          coverage_state: "NOT_APPLICABLE",
          source_records: null,
          source_addresses: null,
          source_objects: null,
          metadata: {},
        },
      ],
    },
    netflow: {
      read_state: "READ",
      dataset_count: 0,
      current_dataset_id: null,
      scope_id: null,
      scopes: [],
      current_analysis_id: null,
      latest_attempt_status: null,
      latest_attempt_error_code: null,
    },
  }
}

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
    const summaryMatch = url.pathname.match(/projects\/([^/]+)\/input-summary$/)
    if (summaryMatch && request.method() === "GET") {
      await route.fulfill({ json: inputSummary(summaryMatch[1]) })
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
    if (
      /projects\/[^/]+\/netflow-datasets\/[^/]+\/processing-contexts$/.test(
        url.pathname,
      ) &&
      request.method() === "GET"
    ) {
      await route.fulfill({
        json: {
          project_id: projects[0].id,
          dataset_id: "21000000-0000-0000-0000-000000000001",
          data: [],
          count: 0,
          skip: 0,
          limit: 25,
        },
      })
      return
    }
    if (
      /projects\/[^/]+\/netflow-datasets\/[^/]+\/analyses$/.test(
        url.pathname,
      ) &&
      request.method() === "GET"
    ) {
      await route.fulfill({
        json: {
          project_id: projects[0].id,
          dataset_id: "21000000-0000-0000-0000-000000000001",
          data: [],
          count: 0,
          skip: 0,
          limit: 25,
        },
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

const operatorId = "30000000-0000-0000-0000-000000000001"

function ledgerRead(
  currentUploadId: string | null,
  currentRevisionId: string | null = null,
  currentProfileId = profiles[projects[0].id].id,
) {
  return {
    project_id: projects[0].id,
    current_upload_id: currentUploadId,
    current_revision_id: currentRevisionId,
    current_profile_id: currentProfileId,
    data: [],
    count: 0,
  }
}

function replacementReceipt({
  candidateId,
  expectedUploadId,
  expectedRevisionId,
  expectedProfileId,
  digest,
}: {
  candidateId: string
  expectedUploadId: string | null
  expectedRevisionId: string | null
  expectedProfileId: string
  digest: string
}) {
  return {
    id: "91000000-0000-0000-0000-000000000099",
    project_id: projects[0].id,
    created_by: operatorId,
    candidate_upload_id: candidateId,
    expected_upload_id: expectedUploadId,
    expected_revision_id: expectedRevisionId,
    expected_profile_id: expectedProfileId,
    request_sha256: digest,
    created_at: projects[0].created_at,
  }
}

async function uploadXlsx(page: Page, name: string) {
  const input = page.getByLabel("XLSX file")
  await input.setInputFiles({
    name,
    mimeType:
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: Buffer.from("mock workbook"),
  })
  await page
    .locator("form")
    .filter({ has: input })
    .getByRole("button", { name: "Upload", exact: true })
    .click()
}

async function tabTo(page: Page, target: Locator) {
  for (let index = 0; index < 8; index += 1) {
    if (await target.evaluate((element) => element === document.activeElement))
      return
    await page.keyboard.press("Tab")
  }
  expect(
    await target.evaluate((element) => element === document.activeElement),
  ).toBe(true)
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
  await clickHistoricalLink(page, "Runs")
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
  await page
    .getByText("Historical Run source settings", { exact: true })
    .click()
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
  await clickHistoricalLink(page, "Runs")
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
  let replacementRequests = 0
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) =>
      route.fulfill({
        json: {
          project_id: projects[0].id,
          current_upload_id: currentUploadId,
          current_revision_id: null,
          current_profile_id: profiles[projects[0].id].id,
          data: [],
          count: 0,
        },
      }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    (route) => {
      const candidate = uploads[projects[0].id].data[0]
      return route.fulfill({
        json: {
          candidate_upload_id: candidate.id,
          current_upload_id: null,
          current_revision_id: null,
          profile_id: candidate.profile_id,
          current_record_count: 0,
          current_unique_ips: 0,
          candidate_record_count: candidate.record_count,
          candidate_unique_ips: candidate.unique_ip_count,
          added_ips: candidate.unique_ip_count,
          removed_ips: 0,
          changed_ip_declarations: 0,
        },
      })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    async (route) => {
      replacementRequests += 1
      currentUploadId = uploads[projects[0].id].data[0].id
      const candidate = uploads[projects[0].id].data[0]
      return route.fulfill({
        json: {
          id: "91000000-0000-0000-0000-000000000002",
          project_id: projects[0].id,
          created_by: "30000000-0000-0000-0000-000000000001",
          candidate_upload_id: candidate.id,
          expected_upload_id: null,
          expected_revision_id: null,
          expected_profile_id: candidate.profile_id,
          request_sha256: await requestDigest(route.request().postDataJSON()),
          created_at: projects[0].created_at,
        },
      })
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
  await page.getByRole("button", { name: "Preview selection" }).click()
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
  await expect(
    page.getByTestId("operation-confirmed").getByText("Operation confirmed.", {
      exact: true,
    }),
  ).toBeVisible()
  expect(replacementRequests).toBe(1)

  await page.reload()
  await expect(page.getByText("Current", { exact: true }).first()).toBeVisible()
  await expect(page.getByText("Project input is not ready.")).toHaveCount(0)
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
    page.getByRole("button", { name: /Preview (selection|replacement)/ }),
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

    await expect(
      page.getByText(
        "Upload accepted. Preview this file and set it as the current input.",
      ),
    ).toBeVisible()
    await expect(fileInput).toHaveValue("")
    await expect(
      page.getByTestId("upload-candidate").getByText("new-assets.xlsx"),
    ).toBeVisible()
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
  await page
    .getByText("Historical Run source settings", { exact: true })
    .click()

  const tokenInput = page.getByLabel("Capset token")
  await expect(tokenInput).toHaveAttribute("type", "password")
  await tokenInput.fill("transient-test-token")
  await page.getByRole("button", { name: "Validate source" }).click()
  await expect(page.getByText("Validated", { exact: true })).toBeVisible()
  await expect(tokenInput).toHaveValue("")
  const sourceDetails = page
    .getByText("Source details", { exact: true })
    .locator("..")
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
  await page
    .getByText("Historical Run source settings", { exact: true })
    .click()
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
  await page
    .getByText("Historical Run source settings", { exact: true })
    .click()

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
  await page
    .getByText("Historical Run source settings", { exact: true })
    .click()

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
  await clickHistoricalLink(page, "Runs")

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
  await clickHistoricalLink(page, "Runs")

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
  await clickHistoricalLink(page, "Runs")

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
    await clickHistoricalLink(page, "Runs")

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

test("uses replacement wording when a current input already exists", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  const second = {
    ...first,
    id: "20000000-0000-0000-0000-000000000002",
    display_filename: "south-assets.xlsx",
    raw_sha256: "b".repeat(64),
  }
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) =>
      route.fulfill({
        json: {
          project_id: projects[0].id,
          current_upload_id: first.id,
          current_revision_id: null,
          current_profile_id: first.profile_id,
          data: [],
          count: 0,
        },
      }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    (route) =>
      route.fulfill({
        json: {
          data: [first, second],
          count: 2,
          current_customer_upload_id: first.id,
          can_upload: true,
          can_select: true,
        },
      }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    (route) =>
      route.fulfill({
        json: {
          candidate_upload_id: second.id,
          current_upload_id: first.id,
          current_revision_id: null,
          profile_id: first.profile_id,
          current_record_count: first.record_count,
          current_unique_ips: 1,
          candidate_record_count: second.record_count,
          candidate_unique_ips: 1,
          added_ips: 0,
          removed_ips: 0,
          changed_ip_declarations: 1,
        },
      }),
  )
  await page.goto("/?view=inputs")

  const firstRow = page
    .getByRole("row")
    .filter({ hasText: first.display_filename })
  const secondRow = page
    .getByRole("row")
    .filter({ hasText: second.display_filename })
  await expect(firstRow.getByText("Current", { exact: true })).toBeVisible()
  await expect(
    firstRow.getByRole("button", { name: /Preview (selection|replacement)/ }),
  ).toHaveCount(0)
  await secondRow.getByRole("button", { name: "Preview replacement" }).click()

  await expect(
    page.getByText("Replacement preview", { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Apply replacement", exact: true }),
  ).toBeVisible()
  await expect(
    page.getByText("Selection preview", { exact: true }),
  ).toHaveCount(0)
})

test("shows a structured upload diagnostic and localizes known values", async ({
  page,
}) => {
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    async (route) => {
      if (route.request().method() !== "POST") return route.fallback()
      return route.fulfill({
        status: 422,
        json: {
          detail: {
            code: "invalid_required_value",
            message: "The workbook contains an invalid required value.",
            field: "start_port",
            row: 3,
            column: 2,
            reason: "port_out_of_range",
            location: "worksheet",
            limit: 65535,
            observed: 70000,
            unit: "port_number",
            debug: "sensitive-cell-value",
          },
        },
      })
    },
  )
  await page.goto("/?view=inputs")
  const input = page.getByLabel("XLSX file")
  await input.setInputFiles({
    name: "bad-port.xlsx",
    mimeType:
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: Buffer.from("bad port"),
  })
  await page
    .locator("form")
    .filter({ has: input })
    .getByRole("button", { name: "Upload", exact: true })
    .click()

  const details = page.getByTestId("diagnostic-details")
  await expect(details).toBeVisible()
  await expect(details.getByText("Start port", { exact: true })).toBeVisible()
  await expect(
    details.getByText("Worksheet row", { exact: true }),
  ).toBeVisible()
  await expect(details.getByText("3", { exact: true })).toBeVisible()
  await expect(details.getByText("Column", { exact: true })).toBeVisible()
  await expect(details.getByText("2", { exact: true })).toBeVisible()
  await expect(
    details.getByText("Port must be between 1 and 65535", { exact: true }),
  ).toBeVisible()
  await expect(
    details.getByText("65,535 port number", { exact: true }),
  ).toBeVisible()
  await expect(
    details.getByText("70,000 port number", { exact: true }),
  ).toBeVisible()
  await expect(page.getByText("sensitive-cell-value")).toHaveCount(0)

  await page
    .getByRole("combobox", { name: "Language / 语言" })
    .selectOption("zh-CN")
  await expect(details.getByText("工作表行", { exact: true })).toBeVisible()
  await expect(details.getByText("起始端口", { exact: true })).toBeVisible()
  await expect(
    details.getByText("端口必须在 1 到 65535 之间", { exact: true }),
  ).toBeVisible()
})

test("names every accepted Web flag value in both locales", async ({
  page,
}) => {
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    async (route) => {
      if (route.request().method() !== "POST") return route.fallback()
      return route.fulfill({
        status: 422,
        json: {
          detail: {
            code: "invalid_required_value",
            message: "The workbook contains an invalid required value.",
            field: "is_web",
            row: 2,
            column: 4,
            reason: "web_flag",
            location: "worksheet",
          },
        },
      })
    },
  )
  await page.goto("/?view=inputs")
  const input = page.getByLabel("XLSX file")
  await input.setInputFiles({
    name: "bad-web-flag.xlsx",
    mimeType:
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: Buffer.from("bad web flag"),
  })
  await page
    .locator("form")
    .filter({ has: input })
    .getByRole("button", { name: "Upload", exact: true })
    .click()

  const details = page.getByTestId("diagnostic-details")
  const english = details.getByText(/Web flag must be/)
  await expect(english).toContainText("是")
  await expect(english).toContainText("否")
  await expect(english).toContainText("无")

  await page
    .getByRole("combobox", { name: "Language / 语言" })
    .selectOption("zh-CN")
  const chinese = details.getByText(/是否 Web 字段必须为/)
  await expect(chinese).toContainText("是")
  await expect(chinese).toContainText("否")
  await expect(chinese).toContainText("无")
})

test("renders bounded extra-column detail and marks historical warnings", async ({
  page,
}) => {
  const currentWarning = {
    ...uploads[projects[0].id].data[0],
    warnings: [
      {
        code: "extra_columns_ignored",
        field: "extra_columns",
        count: 3,
        detail: {
          names: [
            {
              name: "归属‮信息",
              column: 9,
              near_match: "asset_owner",
            },
            { name: "internal-note", column: 12, near_match: null },
          ],
          truncated: true,
          omitted_count: 4,
          names_truncated: true,
        },
      },
    ],
  }
  const historicalWarning = {
    ...currentWarning,
    id: "20000000-0000-0000-0000-000000000004",
    display_filename: "historical.xlsx",
    warnings: [
      {
        code: "extra_columns_ignored",
        field: "extra_columns",
        count: 2,
      },
    ],
  }
  const omittedOnlyWarning = {
    ...currentWarning,
    id: "20000000-0000-0000-0000-000000000005",
    display_filename: "omitted-only.xlsx",
    warnings: [
      {
        code: "extra_columns_ignored",
        field: "extra_columns",
        count: 9,
        detail: {
          names: [{ name: "short-name", column: 6, near_match: null }],
          truncated: true,
          omitted_count: 8,
          names_truncated: false,
        },
      },
    ],
  }
  const longNameWarning = {
    ...currentWarning,
    id: "20000000-0000-0000-0000-000000000006",
    display_filename: "long-name.xlsx",
    warnings: [
      {
        code: "extra_columns_ignored",
        field: "extra_columns",
        count: 1,
        detail: {
          names: [{ name: "L".repeat(64), column: 6, near_match: null }],
          truncated: false,
          omitted_count: 0,
          names_truncated: true,
        },
      },
    ],
  }
  const legacyDetailWarning = {
    ...currentWarning,
    id: "20000000-0000-0000-0000-000000000007",
    display_filename: "legacy-detail.xlsx",
    warnings: [
      {
        code: "extra_columns_ignored",
        field: "extra_columns",
        count: 3,
        detail: {
          names: [{ name: "legacy-short", column: 6, near_match: null }],
          truncated: true,
          omitted_count: 2,
        },
      },
    ],
  }
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    (route) =>
      route.fulfill({
        json: {
          data: [
            currentWarning,
            historicalWarning,
            omittedOnlyWarning,
            longNameWarning,
            legacyDetailWarning,
          ],
          count: 5,
          current_customer_upload_id: null,
          can_upload: true,
          can_select: true,
        },
      }),
  )
  await page.goto("/?view=inputs")

  const currentRow = page
    .getByRole("row")
    .filter({ hasText: currentWarning.display_filename })
  await expect(currentRow.getByText("归属信息", { exact: false })).toBeVisible()
  await expect(
    currentRow.getByText("Did you mean Declared owner?", { exact: false }),
  ).toBeVisible()
  await expect(
    currentRow.getByText("4 more columns omitted.", { exact: true }),
  ).toBeVisible()
  await expect(
    currentRow.getByText("Some column names are shortened to 64 characters.", {
      exact: true,
    }),
  ).toBeVisible()
  const omittedOnlyRow = page
    .getByRole("row")
    .filter({ hasText: omittedOnlyWarning.display_filename })
  await expect(
    omittedOnlyRow.getByText("8 more columns omitted.", { exact: true }),
  ).toBeVisible()
  await expect(
    omittedOnlyRow.getByText(
      "Some column names are shortened to 64 characters.",
      { exact: true },
    ),
  ).toHaveCount(0)
  await expect(
    omittedOnlyRow.getByText("0 more columns omitted.", { exact: true }),
  ).toHaveCount(0)
  const longNameRow = page
    .getByRole("row")
    .filter({ hasText: longNameWarning.display_filename })
  await expect(
    longNameRow.getByText("Some column names are shortened to 64 characters.", {
      exact: true,
    }),
  ).toBeVisible()
  await expect(
    longNameRow.getByText("0 more columns omitted.", { exact: true }),
  ).toHaveCount(0)
  const legacyDetailRow = page
    .getByRole("row")
    .filter({ hasText: legacyDetailWarning.display_filename })
  await expect(
    legacyDetailRow.getByText("2 more columns omitted.", { exact: true }),
  ).toBeVisible()
  await expect(
    legacyDetailRow.getByText(
      "Some column names are shortened to 64 characters.",
      { exact: true },
    ),
  ).toHaveCount(0)
  const historicalRow = page
    .getByRole("row")
    .filter({ hasText: historicalWarning.display_filename })
  await expect(
    historicalRow.getByText(
      "Column details are unavailable for this historical warning.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(
    page.getByText(
      "Derived XLSX files materialize supported fields only. The absence of an extra-column warning is not evidence that unsupported columns are retained.",
      { exact: true },
    ),
  ).toBeVisible()
  await page
    .getByRole("combobox", { name: "Language / 语言" })
    .selectOption("zh-CN")
  await expect(
    longNameRow.getByText("部分列名超过 64 个字符，已截断显示。", {
      exact: true,
    }),
  ).toBeVisible()
  await expect(
    omittedOnlyRow.getByText("另有 8 列未显示。", { exact: true }),
  ).toBeVisible()
  await expect(
    omittedOnlyRow.getByText("部分列名超过 64 个字符，已截断显示。", {
      exact: true,
    }),
  ).toHaveCount(0)
})

test("explains the post-upload next step for an existing input", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  const acceptedUpload = {
    ...first,
    id: "20000000-0000-0000-0000-000000000005",
    display_filename: "replacement-candidate.xlsx",
    raw_sha256: "c".repeat(64),
  }
  let accepted = false
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    async (route) => {
      if (route.request().method() === "POST") {
        accepted = true
        return route.fulfill({ status: 201, json: acceptedUpload })
      }
      return route.fulfill({
        json: {
          data: accepted ? [first, acceptedUpload] : [first],
          count: accepted ? 2 : 1,
          current_customer_upload_id: first.id,
          can_upload: true,
          can_select: true,
        },
      })
    },
  )
  await page.goto("/?view=inputs")
  const input = page.getByLabel("XLSX file")
  await input.setInputFiles({
    name: "replacement-candidate.xlsx",
    mimeType:
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: Buffer.from("replacement"),
  })
  await page
    .locator("form")
    .filter({ has: input })
    .getByRole("button", { name: "Upload", exact: true })
    .click()

  await expect(
    page.getByText(
      "Upload accepted. Preview the replacement before applying it.",
    ),
  ).toBeVisible()
  await expect(
    page
      .getByRole("row")
      .filter({ hasText: "replacement-candidate.xlsx" })
      .getByRole("button", { name: "Preview replacement" }),
  ).toBeVisible()
})

test("keeps the current input when a replacement conflict is rejected", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  const second = {
    ...first,
    id: "20000000-0000-0000-0000-000000000006",
    display_filename: "conflicting.xlsx",
    raw_sha256: "d".repeat(64),
  }
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) =>
      route.fulfill({
        json: {
          project_id: projects[0].id,
          current_upload_id: first.id,
          current_revision_id: null,
          current_profile_id: first.profile_id,
          data: [],
          count: 0,
        },
      }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    (route) =>
      route.fulfill({
        json: {
          data: [first, second],
          count: 2,
          current_customer_upload_id: first.id,
          can_upload: true,
          can_select: true,
        },
      }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    (route) =>
      route.fulfill({
        json: {
          candidate_upload_id: second.id,
          current_upload_id: first.id,
          current_revision_id: null,
          profile_id: first.profile_id,
          current_record_count: first.record_count,
          current_unique_ips: 1,
          candidate_record_count: second.record_count,
          candidate_unique_ips: 1,
          added_ips: 0,
          removed_ips: 0,
          changed_ip_declarations: 1,
        },
      }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    (route) =>
      route.fulfill({
        status: 409,
        json: {
          detail: {
            code: "ledger_version_conflict",
            message: "The current input changed.",
          },
        },
      }),
  )
  await page.goto("/?view=inputs")
  const secondRow = page
    .getByRole("row")
    .filter({ hasText: second.display_filename })
  await secondRow.getByRole("button", { name: "Preview replacement" }).click()
  await page.getByRole("button", { name: "Apply replacement" }).click()

  await expect(
    page.getByText(
      "The current version or profile changed. This request was rejected; preview the latest version again.",
    ),
  ).toBeVisible()
  await expect(
    page
      .getByRole("row")
      .filter({ hasText: first.display_filename })
      .getByText("Current", { exact: true }),
  ).toBeVisible()
})

test("recovers a lost selection response after refresh and resends the same identity", async ({
  page,
}) => {
  const candidate = uploads[projects[0].id].data[0]
  let currentUploadId: string | null = null
  let failApply = true
  const recoveryFound = false
  let receipt: Record<string, unknown> | null = null
  const keys: string[] = []
  const bodies: Array<Record<string, unknown>> = []
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) =>
      route.fulfill({
        json: {
          project_id: projects[0].id,
          current_upload_id: currentUploadId,
          current_revision_id: null,
          current_profile_id: candidate.profile_id,
          data: [],
          count: 0,
        },
      }),
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
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/*`,
    (route) => {
      if (route.request().method() !== "GET") return route.fallback()
      if (!recoveryFound || !receipt) {
        return route.fulfill({
          status: 404,
          json: { detail: { code: "ledger_replacement_not_found" } },
        })
      }
      return route.fulfill({ json: receipt })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    async (route) => {
      keys.push(route.request().headers()["idempotency-key"] ?? "")
      const body = route.request().postDataJSON()
      bodies.push(body)
      receipt = {
        id: "91000000-0000-0000-0000-000000000003",
        project_id: projects[0].id,
        created_by: "30000000-0000-0000-0000-000000000001",
        candidate_upload_id: candidate.id,
        expected_upload_id: null,
        expected_revision_id: null,
        expected_profile_id: candidate.profile_id,
        request_sha256: await requestDigest(body),
        created_at: projects[0].created_at,
      }
      if (failApply) {
        failApply = false
        return route.abort("connectionfailed")
      }
      currentUploadId = candidate.id
      return route.fulfill({ json: receipt })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    (route) =>
      route.fulfill({
        json: {
          candidate_upload_id: candidate.id,
          current_upload_id: null,
          current_revision_id: null,
          profile_id: candidate.profile_id,
          current_record_count: 0,
          current_unique_ips: 0,
          candidate_record_count: candidate.record_count,
          candidate_unique_ips: 1,
          added_ips: 1,
          removed_ips: 0,
          changed_ip_declarations: 0,
        },
      }),
  )
  await page.goto("/?view=inputs")
  await page.getByRole("button", { name: "Preview selection" }).click()
  await page.getByRole("button", { name: "Set as current input" }).click()
  await expect(
    page.getByText("Selection outcome unknown", { exact: true }),
  ).toBeVisible()

  await page.reload()
  await expect(
    page.getByText("Selection outcome unknown", { exact: true }),
  ).toBeVisible()
  const recover = page.getByRole("button", { name: "Recover result" })
  await expect(recover).toBeVisible()
  await recover.click()
  await expect(
    page.getByText("No completed receipt yet.", { exact: false }),
  ).toBeVisible()
  await page.getByRole("button", { name: "Resend original request" }).click()
  await expect(
    page.getByTestId("operation-confirmed").getByText("Operation confirmed.", {
      exact: true,
    }),
  ).toBeVisible()
  expect(keys).toHaveLength(2)
  expect(keys[0]).toBe(keys[1])
  expect(bodies).toHaveLength(2)
  expect(bodies[0]).toEqual(bodies[1])
  expect(currentUploadId).toBe(candidate.id)
})

test("requires an explicit preview and one explicit apply for a first import", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  const candidate = {
    ...first,
    id: "20000000-0000-0000-0000-000000000011",
    display_filename: "explicit-first.xlsx",
    raw_sha256: "1".repeat(64),
    record_count: 3,
  }
  let accepted = false
  let currentUploadId: string | null = null
  let previewRequests = 0
  let applyRequests = 0
  let summaryReads = 0
  const previewBodies: Array<Record<string, unknown>> = []
  const applyBodies: Array<Record<string, unknown>> = []
  const applyKeys: string[] = []
  const writes: string[] = []
  page.on("request", (request) => {
    if (
      ["POST", "PUT", "PATCH", "DELETE"].includes(request.method()) &&
      request.url().includes("/api/v1/projects/")
    )
      writes.push(`${request.method()} ${new URL(request.url()).pathname}`)
  })
  await page.route(
    `**/api/v1/projects/${projects[0].id}/input-summary`,
    (route) => {
      summaryReads += 1
      return route.fulfill({ json: inputSummary(projects[0].id) })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) => route.fulfill({ json: ledgerRead(currentUploadId) }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    async (route) => {
      previewRequests += 1
      const body = route.request().postDataJSON() as Record<string, unknown>
      previewBodies.push(body)
      return route.fulfill({
        json: {
          candidate_upload_id: candidate.id,
          current_upload_id: body.expected_upload_id,
          current_revision_id: body.expected_revision_id,
          profile_id: body.expected_profile_id,
          current_record_count: 0,
          current_unique_ips: 0,
          candidate_record_count: 3,
          candidate_unique_ips: 1,
          added_ips: 1,
          removed_ips: 0,
          changed_ip_declarations: 0,
        },
      })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    async (route) => {
      applyRequests += 1
      applyKeys.push(route.request().headers()["idempotency-key"] ?? "")
      const body = route.request().postDataJSON() as Record<string, unknown>
      applyBodies.push(body)
      currentUploadId = candidate.id
      return route.fulfill({
        json: replacementReceipt({
          candidateId: candidate.id,
          expectedUploadId: body.expected_upload_id as string | null,
          expectedRevisionId: body.expected_revision_id as string | null,
          expectedProfileId: body.expected_profile_id as string,
          digest: await requestDigest(body),
        }),
      })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    async (route) => {
      if (route.request().method() === "POST") {
        accepted = true
        return route.fulfill({ status: 201, json: candidate })
      }
      return route.fulfill({
        json: {
          data: accepted ? [first, candidate] : [first],
          count: accepted ? 2 : 1,
          current_customer_upload_id: currentUploadId,
          can_upload: true,
          can_select: true,
        },
      })
    },
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await uploadXlsx(page, "explicit-first.xlsx")
  const candidateCard = page.getByTestId("upload-candidate")
  await expect(
    candidateCard.getByText(
      "Upload accepted. Preview this file and set it as the current input.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(
    candidateCard.getByText("explicit-first.xlsx", { exact: true }),
  ).toBeVisible()
  expect(previewRequests).toBe(0)
  expect(applyRequests).toBe(0)

  await candidateCard.getByRole("button", { name: "Preview this file" }).click()
  const previewCard = page.getByTestId("replacement-preview")
  await expect(previewCard).toBeVisible()
  expect(previewRequests).toBe(1)
  expect(previewBodies[0]).toEqual({
    candidate_upload_id: candidate.id,
    expected_upload_id: null,
    expected_revision_id: null,
    expected_profile_id: profiles[projects[0].id].id,
  })
  await expect(
    previewCard.getByText("explicit-first.xlsx", { exact: true }),
  ).toBeVisible()
  await expect(previewCard.getByText("0 / 0", { exact: true })).toBeVisible()
  await expect(previewCard.getByText("3 / 1", { exact: true })).toBeVisible()
  await expect(
    previewCard.getByText("1 / 0 / 0", { exact: true }),
  ).toBeVisible()
  await expect(previewCard.getByText(/Declared owner/)).toBeVisible()
  expect(applyRequests).toBe(0)

  const summaryBeforeApply = summaryReads
  await previewCard
    .getByRole("button", { name: "Set as current input" })
    .click()
  const confirmation = page.getByTestId("operation-confirmed")
  await expect(confirmation).toBeVisible()
  await expect(
    confirmation.getByRole("heading", { name: "Operation confirmed." }),
  ).toBeFocused()
  expect(applyRequests).toBe(1)
  expect(applyBodies[0]).toEqual(previewBodies[0])
  expect(applyKeys).toHaveLength(1)
  expect(applyKeys[0].length).toBeGreaterThan(0)
  const link = confirmation.getByRole("link", {
    name: "Go to comparison results",
  })
  await expect(link).toBeVisible()
  const href = await link.getAttribute("href")
  expect(href).not.toBeNull()
  const destination = new URL(href!, "http://127.0.0.1:5183")
  expect(destination.pathname).toBe(
    `/projects/${projects[0].id}/netflow-correlation`,
  )
  expect(destination.search).toBe("")
  await expect.poll(() => summaryReads).toBeGreaterThan(summaryBeforeApply)

  const writesBeforeNavigation = writes.length
  await link.click()
  await expect
    .poll(() => new URL(page.url()).pathname)
    .toBe(`/projects/${projects[0].id}/netflow-correlation`)
  expect(previewRequests).toBe(1)
  expect(applyRequests).toBe(1)
  expect(writes.length).toBe(writesBeforeNavigation)
})

test("requires an explicit preview for a replacement upload and applies once", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  const candidate = {
    ...first,
    id: "20000000-0000-0000-0000-000000000012",
    display_filename: "replacement-upload.xlsx",
    raw_sha256: "2".repeat(64),
    record_count: 4,
  }
  let accepted = false
  let currentUploadId: string | null = first.id
  let previewRequests = 0
  let applyRequests = 0
  const previewBodies: Array<Record<string, unknown>> = []
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) => route.fulfill({ json: ledgerRead(currentUploadId) }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    async (route) => {
      previewRequests += 1
      const body = route.request().postDataJSON() as Record<string, unknown>
      previewBodies.push(body)
      return route.fulfill({
        json: {
          candidate_upload_id: candidate.id,
          current_upload_id: body.expected_upload_id,
          current_revision_id: body.expected_revision_id,
          profile_id: body.expected_profile_id,
          current_record_count: 2,
          current_unique_ips: 1,
          candidate_record_count: 4,
          candidate_unique_ips: 1,
          added_ips: 2,
          removed_ips: 0,
          changed_ip_declarations: 0,
        },
      })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    async (route) => {
      applyRequests += 1
      const body = route.request().postDataJSON() as Record<string, unknown>
      currentUploadId = candidate.id
      return route.fulfill({
        json: replacementReceipt({
          candidateId: candidate.id,
          expectedUploadId: body.expected_upload_id as string | null,
          expectedRevisionId: body.expected_revision_id as string | null,
          expectedProfileId: body.expected_profile_id as string,
          digest: await requestDigest(body),
        }),
      })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    async (route) => {
      if (route.request().method() === "POST") {
        accepted = true
        return route.fulfill({ status: 201, json: candidate })
      }
      return route.fulfill({
        json: {
          data: accepted ? [first, candidate] : [first],
          count: accepted ? 2 : 1,
          current_customer_upload_id: currentUploadId,
          can_upload: true,
          can_select: true,
        },
      })
    },
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await uploadXlsx(page, "replacement-upload.xlsx")
  const candidateCard = page.getByTestId("upload-candidate")
  await expect(
    candidateCard.getByText(
      "Upload accepted. Preview the replacement before applying it.",
      { exact: true },
    ),
  ).toBeVisible()
  await candidateCard.getByRole("button", { name: "Preview this file" }).click()
  const previewCard = page.getByTestId("replacement-preview")
  await expect(previewCard).toBeVisible()
  expect(previewRequests).toBe(1)
  expect(previewBodies[0]).toEqual({
    candidate_upload_id: candidate.id,
    expected_upload_id: first.id,
    expected_revision_id: null,
    expected_profile_id: profiles[projects[0].id].id,
  })
  expect(applyRequests).toBe(0)
  await previewCard.getByRole("button", { name: "Apply replacement" }).click()
  await expect(page.getByTestId("operation-confirmed")).toBeVisible()
  expect(applyRequests).toBe(1)
  const currentCard = page.locator('[data-slot="card"]').filter({
    has: page.getByRole("heading", { name: "Current Project input" }),
  })
  await expect(
    currentCard.getByText("replacement-upload.xlsx", { exact: true }),
  ).toBeVisible()
})

test("previews a 200 dedupe candidate from the response without changing the upload page", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  const older = {
    ...first,
    id: "20000000-0000-0000-0000-000000000013",
    display_filename: "older-page-item.xlsx",
    raw_sha256: "3".repeat(64),
  }
  const candidate = {
    ...first,
    id: "20000000-0000-0000-0000-000000000014",
    display_filename: "dedupe-page-two.xlsx",
    raw_sha256: "4".repeat(64),
    record_count: 5,
  }
  let previewRequests = 0
  let applyRequests = 0
  const previewBodies: Array<Record<string, unknown>> = []
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) => route.fulfill({ json: ledgerRead(null) }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    async (route) => {
      previewRequests += 1
      const body = route.request().postDataJSON() as Record<string, unknown>
      previewBodies.push(body)
      return route.fulfill({
        json: {
          candidate_upload_id: candidate.id,
          current_upload_id: null,
          current_revision_id: null,
          profile_id: candidate.profile_id,
          current_record_count: 0,
          current_unique_ips: 0,
          candidate_record_count: candidate.record_count,
          candidate_unique_ips: 2,
          added_ips: 2,
          removed_ips: 0,
          changed_ip_declarations: 0,
        },
      })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    (route) => {
      applyRequests += 1
      return route.fulfill({ status: 500 })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    async (route) => {
      if (route.request().method() === "POST")
        return route.fulfill({ status: 200, json: candidate })
      return route.fulfill({
        json: {
          data: [older],
          count: 11,
          current_customer_upload_id: null,
          can_upload: true,
          can_select: true,
        },
      })
    },
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs&upload_page=2`)
  await expect(page.getByText("Page 2", { exact: true })).toBeVisible()
  await uploadXlsx(page, candidate.display_filename)
  const candidateCard = page.getByTestId("upload-candidate")
  await expect(
    candidateCard.getByText(candidate.display_filename, { exact: true }),
  ).toBeVisible()
  expect(new URL(page.url()).searchParams.get("upload_page")).toBe("2")
  await expect(page.getByText("Page 2", { exact: true })).toBeVisible()
  await expect(
    page.getByRole("row").filter({ hasText: candidate.display_filename }),
  ).toHaveCount(0)
  expect(previewRequests).toBe(0)
  await candidateCard.getByRole("button", { name: "Preview this file" }).click()
  await expect(
    page
      .getByTestId("replacement-preview")
      .getByText(candidate.display_filename, { exact: true }),
  ).toBeVisible()
  expect(previewRequests).toBe(1)
  expect(previewBodies[0]).toEqual({
    candidate_upload_id: candidate.id,
    expected_upload_id: null,
    expected_revision_id: null,
    expected_profile_id: profiles[projects[0].id].id,
  })
  expect(applyRequests).toBe(0)
})

test("shows an already-current dedupe candidate without preview or apply", async ({
  page,
}) => {
  const candidate = uploads[projects[0].id].data[0]
  const revisionId = "70000000-0000-0000-0000-000000000001"
  let previewRequests = 0
  let applyRequests = 0
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) =>
      route.fulfill({
        json: ledgerRead(candidate.id, revisionId, candidate.profile_id),
      }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    (route) => {
      previewRequests += 1
      return route.fulfill({
        json: {
          candidate_upload_id: candidate.id,
          current_upload_id: candidate.id,
          current_revision_id: revisionId,
          profile_id: candidate.profile_id,
          current_record_count: candidate.record_count,
          current_unique_ips: 1,
          candidate_record_count: candidate.record_count,
          candidate_unique_ips: 1,
          added_ips: 0,
          removed_ips: 0,
          changed_ip_declarations: 0,
        },
      })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    (route) => {
      applyRequests += 1
      return route.fulfill({ status: 500 })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    async (route) => {
      if (route.request().method() === "POST")
        return route.fulfill({ status: 200, json: candidate })
      return route.fulfill({
        json: {
          data: [candidate],
          count: 1,
          current_customer_upload_id: candidate.id,
          can_upload: true,
          can_select: true,
        },
      })
    },
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await uploadXlsx(page, candidate.display_filename)
  const candidateCard = page.getByTestId("upload-candidate")
  await expect(
    candidateCard.getByText(
      "Upload accepted. Preview the replacement before applying it.",
      { exact: true },
    ),
  ).toBeVisible()
  await candidateCard.getByRole("button", { name: "Preview this file" }).click()
  const alreadyCurrent = page.getByTestId("already-current")
  await expect(alreadyCurrent).toBeVisible()
  await expect(
    alreadyCurrent.getByRole("heading", { name: "File is already current" }),
  ).toBeFocused()
  await expect(
    alreadyCurrent.getByText(
      "This file is already the current input. No preview or apply is needed; existing manual revisions are unchanged.",
      { exact: true },
    ),
  ).toBeVisible()
  expect(previewRequests).toBe(0)
  expect(applyRequests).toBe(0)
  await expect(
    page.getByRole("button", { name: "Set as current input" }),
  ).toHaveCount(0)
  await expect(
    page.getByRole("button", { name: "Apply replacement" }),
  ).toHaveCount(0)
  await expect(
    page
      .getByRole("row")
      .filter({ hasText: candidate.display_filename })
      .getByText("Current", { exact: true }),
  ).toBeVisible()
})

test("returns focus to the preview trigger when the preview is cancelled", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  let previewRequests = 0
  let applyRequests = 0
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) => route.fulfill({ json: ledgerRead(null) }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    (route) => {
      previewRequests += 1
      return route.fulfill({
        json: {
          candidate_upload_id: first.id,
          current_upload_id: null,
          current_revision_id: null,
          profile_id: first.profile_id,
          current_record_count: 0,
          current_unique_ips: 0,
          candidate_record_count: first.record_count,
          candidate_unique_ips: 1,
          added_ips: 1,
          removed_ips: 0,
          changed_ip_declarations: 0,
        },
      })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    (route) => {
      applyRequests += 1
      return route.fulfill({ status: 500 })
    },
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  const trigger = page
    .getByRole("row")
    .filter({ hasText: first.display_filename })
    .getByRole("button", { name: "Preview selection" })
  await trigger.click()
  const previewCard = page.getByTestId("replacement-preview")
  await expect(
    previewCard.getByRole("heading", { name: "Selection preview" }),
  ).toBeFocused()
  await previewCard.getByRole("button", { name: "Cancel" }).click()
  await expect(trigger).toBeFocused()
  await expect(previewCard).toHaveCount(0)
  expect(previewRequests).toBe(1)
  expect(applyRequests).toBe(0)
})

test("keeps the chosen file after a 422 and retries the upload", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  const candidate = {
    ...first,
    id: "20000000-0000-0000-0000-000000000015",
    display_filename: "retry-422.xlsx",
    raw_sha256: "5".repeat(64),
    record_count: 2,
  }
  let accepted = false
  let uploadRequests = 0
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    async (route) => {
      if (route.request().method() === "POST") {
        uploadRequests += 1
        if (uploadRequests === 1)
          return route.fulfill({
            status: 422,
            json: {
              detail: {
                code: "unsupported_workbook",
                message: "The workbook could not be read.",
                row: 2,
                column: 3,
              },
            },
          })
        accepted = true
        return route.fulfill({ status: 201, json: candidate })
      }
      return route.fulfill({
        json: {
          data: accepted ? [first, candidate] : [first],
          count: accepted ? 2 : 1,
          current_customer_upload_id: null,
          can_upload: true,
          can_select: true,
        },
      })
    },
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await uploadXlsx(page, "retry-422.xlsx")
  const errorSummary = page.getByTestId("import-error-summary")
  await expect(
    errorSummary.getByText("The workbook could not be read.", { exact: true }),
  ).toBeVisible()
  await expect(errorSummary).toBeFocused()
  const input = page.getByLabel("XLSX file")
  expect(
    await input.evaluate(
      (element) => (element as HTMLInputElement).files?.[0]?.name,
    ),
  ).toBe("retry-422.xlsx")
  expect(uploadRequests).toBe(1)

  await page
    .locator("form")
    .filter({ has: input })
    .getByRole("button", { name: "Upload", exact: true })
    .click()
  await expect(page.getByTestId("upload-candidate")).toBeVisible()
  await expect(
    page
      .getByTestId("upload-candidate")
      .getByText("retry-422.xlsx", { exact: true }),
  ).toBeVisible()
  expect(uploadRequests).toBe(2)
  await expect(
    page
      .getByTestId("upload-candidate")
      .getByRole("heading", { name: "Accepted file" }),
  ).toBeFocused()
})

test("discards a late preview after a different local file is chosen", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  const second = {
    ...first,
    id: "20000000-0000-0000-0000-000000000016",
    display_filename: "second-choice.xlsx",
    raw_sha256: "6".repeat(64),
  }
  let previewRequests = 0
  let applyRequests = 0
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) => route.fulfill({ json: ledgerRead(null) }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    async (route) => {
      previewRequests += 1
      const body = route.request().postDataJSON() as Record<string, unknown>
      await new Promise((resolve) => setTimeout(resolve, 400))
      return route.fulfill({
        json: {
          candidate_upload_id: body.candidate_upload_id,
          current_upload_id: null,
          current_revision_id: null,
          profile_id: first.profile_id,
          current_record_count: 0,
          current_unique_ips: 0,
          candidate_record_count: first.record_count,
          candidate_unique_ips: 1,
          added_ips: 1,
          removed_ips: 0,
          changed_ip_declarations: 0,
        },
      })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    (route) => {
      applyRequests += 1
      return route.fulfill({ status: 500 })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    async (route) => {
      if (route.request().method() === "POST")
        return route.fulfill({ status: 201, json: second })
      return route.fulfill({
        json: {
          data: [first, second],
          count: 2,
          current_customer_upload_id: null,
          can_upload: true,
          can_select: true,
        },
      })
    },
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  const trigger = page
    .getByRole("row")
    .filter({ hasText: first.display_filename })
    .getByRole("button", { name: "Preview selection" })
  const previewResponse = page.waitForResponse((response) =>
    response.url().endsWith("/customer-ledger/replacements/preview"),
  )
  await trigger.click()
  const input = page.getByLabel("XLSX file")
  await input.setInputFiles({
    name: "second-choice.xlsx",
    mimeType:
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: Buffer.from("mock workbook"),
  })
  await expect(
    page.getByText("second-choice.xlsx", { exact: true }),
  ).toBeVisible()
  await previewResponse
  await page.waitForTimeout(100)
  await expect(page.getByTestId("replacement-preview")).toHaveCount(0)
  await expect(
    page.getByText("second-choice.xlsx", { exact: true }),
  ).toBeVisible()
  expect(previewRequests).toBe(1)
  expect(applyRequests).toBe(0)

  await page
    .locator("form")
    .filter({ has: input })
    .getByRole("button", { name: "Upload", exact: true })
    .click()
  await expect(
    page
      .getByTestId("upload-candidate")
      .getByText("second-choice.xlsx", { exact: true }),
  ).toBeVisible()
  expect(previewRequests).toBe(1)
  expect(applyRequests).toBe(0)
})

test("ignores a late preview and apply after switching Projects", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  let currentUploadId: string | null = null
  let applyRequests = 0
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) => route.fulfill({ json: ledgerRead(currentUploadId) }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    (route) =>
      route.fulfill({
        json: {
          candidate_upload_id: first.id,
          current_upload_id: null,
          current_revision_id: null,
          profile_id: first.profile_id,
          current_record_count: 0,
          current_unique_ips: 0,
          candidate_record_count: first.record_count,
          candidate_unique_ips: 1,
          added_ips: 1,
          removed_ips: 0,
          changed_ip_declarations: 0,
        },
      }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    async (route) => {
      applyRequests += 1
      const body = route.request().postDataJSON() as Record<string, unknown>
      const receipt = replacementReceipt({
        candidateId: first.id,
        expectedUploadId: body.expected_upload_id as string | null,
        expectedRevisionId: body.expected_revision_id as string | null,
        expectedProfileId: body.expected_profile_id as string,
        digest: await requestDigest(body),
      })
      currentUploadId = first.id
      await new Promise((resolve) => setTimeout(resolve, 500))
      return route.fulfill({ json: receipt })
    },
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await page
    .getByRole("row")
    .filter({ hasText: first.display_filename })
    .getByRole("button", { name: "Preview selection" })
    .click()
  await page
    .getByTestId("replacement-preview")
    .getByRole("button", { name: "Set as current input" })
    .click()
  const projectSelect = page.getByRole("combobox", { name: "Project" })
  await projectSelect.selectOption(projects[1].id)
  const focusAfterSwitch = await page.evaluate(
    () => document.activeElement?.outerHTML ?? null,
  )
  await page.waitForTimeout(800)
  await expect(projectSelect).toHaveValue(projects[1].id)
  expect(
    await page.evaluate(() => document.activeElement?.outerHTML ?? null),
  ).toBe(focusAfterSwitch)
  await expect(page.getByText("No accepted uploads yet.")).toBeVisible()
  await expect(page.getByTestId("operation-confirmed")).toHaveCount(0)
  await expect(page.getByTestId("replacement-preview")).toHaveCount(0)
  await expect(page.getByText("Selection outcome unknown")).toHaveCount(0)
  expect(applyRequests).toBe(1)
})

test("freezes the preview during digest and submits one apply for a double click", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  let currentUploadId: string | null = null
  let applyRequests = 0
  const applyKeys: string[] = []
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) => route.fulfill({ json: ledgerRead(currentUploadId) }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    (route) =>
      route.fulfill({
        json: {
          candidate_upload_id: first.id,
          current_upload_id: null,
          current_revision_id: null,
          profile_id: first.profile_id,
          current_record_count: 0,
          current_unique_ips: 0,
          candidate_record_count: first.record_count,
          candidate_unique_ips: 1,
          added_ips: 1,
          removed_ips: 0,
          changed_ip_declarations: 0,
        },
      }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    async (route) => {
      applyRequests += 1
      applyKeys.push(route.request().headers()["idempotency-key"] ?? "")
      const body = route.request().postDataJSON() as Record<string, unknown>
      currentUploadId = first.id
      return route.fulfill({
        json: replacementReceipt({
          candidateId: first.id,
          expectedUploadId: body.expected_upload_id as string | null,
          expectedRevisionId: body.expected_revision_id as string | null,
          expectedProfileId: body.expected_profile_id as string,
          digest: await requestDigest(body),
        }),
      })
    },
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await page
    .getByRole("row")
    .filter({ hasText: first.display_filename })
    .getByRole("button", { name: "Preview selection" })
    .click()
  await expect(page.getByTestId("replacement-preview")).toBeVisible()
  await page.evaluate(() => {
    const original = crypto.subtle.digest.bind(crypto.subtle)
    crypto.subtle.digest = (async (algorithm, data) => {
      await new Promise((resolve) => setTimeout(resolve, 500))
      return original(algorithm, data)
    }) as typeof crypto.subtle.digest
  })
  const apply = page.getByRole("button", { name: "Set as current input" })
  await apply.evaluate((element) => {
    const button = element as HTMLElement
    button.click()
    button.click()
  })
  await expect(page.getByTestId("replacement-preview")).toBeVisible()
  await expect(apply).toBeDisabled()
  await expect(page.getByTestId("operation-confirmed")).toBeVisible()
  expect(applyRequests).toBe(1)
  expect(applyKeys).toHaveLength(1)
})

test("does not submit when the replacement intent cannot be saved", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  let applyRequests = 0
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) => route.fulfill({ json: ledgerRead(null) }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    (route) =>
      route.fulfill({
        json: {
          candidate_upload_id: first.id,
          current_upload_id: null,
          current_revision_id: null,
          profile_id: first.profile_id,
          current_record_count: 0,
          current_unique_ips: 0,
          candidate_record_count: first.record_count,
          candidate_unique_ips: 1,
          added_ips: 1,
          removed_ips: 0,
          changed_ip_declarations: 0,
        },
      }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    (route) => {
      applyRequests += 1
      return route.fulfill({ status: 500 })
    },
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await page
    .getByRole("row")
    .filter({ hasText: first.display_filename })
    .getByRole("button", { name: "Preview selection" })
    .click()
  await expect(page.getByTestId("replacement-preview")).toBeVisible()
  await page.evaluate(() => {
    const original = Storage.prototype.setItem
    Storage.prototype.setItem = function (
      this: Storage,
      key: string,
      value: string,
    ) {
      if (key.startsWith("exposure:customer-replacement:"))
        throw new DOMException("Storage quota exceeded", "QuotaExceededError")
      return original.call(this, key, value)
    }
  })
  await page.getByRole("button", { name: "Set as current input" }).click()
  await expect(
    page.getByText("The request could not be saved. Nothing was submitted."),
  ).toBeVisible()
  await expect(page.getByTestId("replacement-preview")).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Set as current input" }),
  ).toBeEnabled()
  expect(applyRequests).toBe(0)
  expect(
    await page.evaluate(() =>
      Object.keys(sessionStorage).filter((key) =>
        key.startsWith("exposure:customer-replacement:"),
      ),
    ),
  ).toEqual([])
})

for (const conflict of [
  {
    code: "ledger_version_conflict",
    title: "Current version changed",
    copy: "The current version or profile changed. This request was rejected; preview the latest version again.",
  },
  {
    code: "ledger_profile_changed",
    title: "Current profile changed",
    copy: "The current profile changed. This request was rejected; preview the latest version again.",
  },
] as const) {
  test(`retains the candidate after a 409 ${conflict.code} and re-previews explicitly`, async ({
    page,
  }) => {
    const first = uploads[projects[0].id].data[0]
    const second = {
      ...first,
      id: "20000000-0000-0000-0000-000000000017",
      display_filename: "conflict-candidate.xlsx",
      raw_sha256: "7".repeat(64),
      record_count: 3,
    }
    const newerUploadId = "20000000-0000-0000-0000-000000000018"
    const newerRevisionId = "70000000-0000-0000-0000-000000000018"
    const newerProfileId = "10000000-0000-0000-0000-000000000099"
    let ledger = ledgerRead(first.id)
    let currentUploadId: string | null = first.id
    let previewRequests = 0
    let applyRequests = 0
    const previewBodies: Array<Record<string, unknown>> = []
    const applyBodies: Array<Record<string, unknown>> = []
    const applyKeys: string[] = []
    await page.route(
      `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
      (route) => route.fulfill({ json: ledger }),
    )
    await page.route(
      `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
      (route) => {
        previewRequests += 1
        const body = route.request().postDataJSON() as Record<string, unknown>
        previewBodies.push(body)
        return route.fulfill({
          json: {
            candidate_upload_id: second.id,
            current_upload_id: body.expected_upload_id,
            current_revision_id: body.expected_revision_id,
            profile_id: body.expected_profile_id,
            current_record_count: first.record_count,
            current_unique_ips: 1,
            candidate_record_count: second.record_count,
            candidate_unique_ips: 1,
            added_ips: 0,
            removed_ips: 0,
            changed_ip_declarations: 1,
          },
        })
      },
    )
    await page.route(
      `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
      async (route) => {
        applyRequests += 1
        const body = route.request().postDataJSON() as Record<string, unknown>
        applyBodies.push(body)
        applyKeys.push(route.request().headers()["idempotency-key"] ?? "")
        if (applyRequests === 1)
          return route.fulfill({
            status: 409,
            json: {
              detail: {
                code: conflict.code,
                message: "The current input changed.",
              },
            },
          })
        currentUploadId = second.id
        return route.fulfill({
          json: replacementReceipt({
            candidateId: second.id,
            expectedUploadId: body.expected_upload_id as string | null,
            expectedRevisionId: body.expected_revision_id as string | null,
            expectedProfileId: body.expected_profile_id as string,
            digest: await requestDigest(body),
          }),
        })
      },
    )
    await page.route(
      `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
      async (route) => {
        if (route.request().method() === "POST")
          return route.fulfill({ status: 201, json: second })
        return route.fulfill({
          json: {
            data: [first, second],
            count: 2,
            current_customer_upload_id: currentUploadId,
            can_upload: true,
            can_select: true,
          },
        })
      },
    )
    await page.goto(`/?project=${projects[0].id}&view=inputs`)
    await page
      .getByRole("row")
      .filter({ hasText: second.display_filename })
      .getByRole("button", { name: "Preview replacement" })
      .click()
    await page
      .getByTestId("replacement-preview")
      .getByRole("button", { name: "Apply replacement" })
      .click()
    const errorCard = page.getByTestId("import-error")
    await expect(
      errorCard.getByRole("heading", { name: conflict.title }),
    ).toBeFocused()
    await expect(
      errorCard.getByText(conflict.copy, { exact: true }),
    ).toBeVisible()
    await expect(
      errorCard.getByText(second.display_filename, { exact: true }),
    ).toBeVisible()
    await expect(
      page.getByText("Selection outcome unknown", { exact: true }),
    ).toHaveCount(0)
    await expect(
      page.getByRole("button", { name: "Resend original request" }),
    ).toHaveCount(0)
    expect(previewRequests).toBe(1)
    expect(applyRequests).toBe(1)

    if (conflict.code === "ledger_version_conflict")
      ledger = ledgerRead(newerUploadId, newerRevisionId)
    else ledger = ledgerRead(first.id, null, newerProfileId)
    await errorCard
      .getByRole("button", { name: "Read latest version and preview again" })
      .click()
    await expect(page.getByTestId("replacement-preview")).toBeVisible()
    expect(previewRequests).toBe(2)
    expect(applyRequests).toBe(1)
    if (conflict.code === "ledger_version_conflict") {
      expect(previewBodies[1]).toEqual({
        candidate_upload_id: second.id,
        expected_upload_id: newerUploadId,
        expected_revision_id: newerRevisionId,
        expected_profile_id: profiles[projects[0].id].id,
      })
    } else {
      expect(previewBodies[1]).toEqual({
        candidate_upload_id: second.id,
        expected_upload_id: first.id,
        expected_revision_id: null,
        expected_profile_id: newerProfileId,
      })
    }

    await page
      .getByTestId("replacement-preview")
      .getByRole("button", { name: "Apply replacement" })
      .click()
    await expect(page.getByTestId("operation-confirmed")).toBeVisible()
    expect(applyRequests).toBe(2)
    expect(applyBodies[1]).toEqual(previewBodies[1])
    expect(applyKeys[0]).not.toBe(applyKeys[1])
  })
}

test("clears a 409 key conflict without masquerading as a version change or retrying", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  const second = {
    ...first,
    id: "20000000-0000-0000-0000-000000000019",
    display_filename: "key-conflict.xlsx",
    raw_sha256: "8".repeat(64),
  }
  let previewRequests = 0
  let applyRequests = 0
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) => route.fulfill({ json: ledgerRead(first.id) }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    (route) => {
      previewRequests += 1
      return route.fulfill({
        json: {
          candidate_upload_id: second.id,
          current_upload_id: first.id,
          current_revision_id: null,
          profile_id: first.profile_id,
          current_record_count: first.record_count,
          current_unique_ips: 1,
          candidate_record_count: second.record_count,
          candidate_unique_ips: 1,
          added_ips: 0,
          removed_ips: 0,
          changed_ip_declarations: 0,
        },
      })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    (route) => {
      applyRequests += 1
      return route.fulfill({
        status: 409,
        json: {
          detail: {
            code: "ledger_key_conflict",
            message: "This operation key belongs to another request.",
          },
        },
      })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    async (route) => {
      if (route.request().method() === "POST")
        return route.fulfill({ status: 201, json: second })
      return route.fulfill({
        json: {
          data: [first, second],
          count: 2,
          current_customer_upload_id: first.id,
          can_upload: true,
          can_select: true,
        },
      })
    },
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await page
    .getByRole("row")
    .filter({ hasText: second.display_filename })
    .getByRole("button", { name: "Preview replacement" })
    .click()
  await page
    .getByTestId("replacement-preview")
    .getByRole("button", { name: "Apply replacement" })
    .click()
  const errorCard = page.getByTestId("import-error")
  await expect(
    errorCard.getByRole("heading", { name: "Operation key conflict" }),
  ).toBeVisible()
  await expect(
    errorCard.getByText(/already used for a different request/),
  ).toBeVisible()
  await expect(
    page.getByText(
      "The current version or profile changed. This request was rejected; preview the latest version again.",
    ),
  ).toHaveCount(0)
  await expect(
    page.getByRole("button", { name: "Resend original request" }),
  ).toHaveCount(0)
  expect(previewRequests).toBe(1)
  expect(applyRequests).toBe(1)
  expect(
    await page.evaluate(() =>
      Object.keys(sessionStorage).filter((key) =>
        key.startsWith("exposure:customer-replacement:"),
      ),
    ),
  ).toEqual([])
  await errorCard
    .getByRole("button", { name: "Preview this file again" })
    .click()
  await expect(page.getByTestId("replacement-preview")).toBeVisible()
  expect(previewRequests).toBe(2)
  expect(applyRequests).toBe(1)
})

for (const mismatch of [
  {
    field: "candidate_upload_id",
    value: "20000000-0000-0000-0000-000000000098",
  },
  {
    field: "current_upload_id",
    value: "20000000-0000-0000-0000-000000000097",
  },
  {
    field: "current_revision_id",
    value: "70000000-0000-0000-0000-000000000096",
  },
  {
    field: "profile_id",
    value: "10000000-0000-0000-0000-000000000095",
  },
] as const) {
  test(`rejects a preview identity mismatch in ${mismatch.field}`, async ({
    page,
  }) => {
    const first = uploads[projects[0].id].data[0]
    let applyRequests = 0
    await page.route(
      `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
      (route) => route.fulfill({ json: ledgerRead(null) }),
    )
    await page.route(
      `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
      (route) =>
        route.fulfill({
          json: {
            candidate_upload_id: first.id,
            current_upload_id: null,
            current_revision_id: null,
            profile_id: first.profile_id,
            current_record_count: 0,
            current_unique_ips: 0,
            candidate_record_count: first.record_count,
            candidate_unique_ips: 1,
            added_ips: 1,
            removed_ips: 0,
            changed_ip_declarations: 0,
            [mismatch.field]: mismatch.value,
          },
        }),
    )
    await page.route(
      `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
      (route) => {
        applyRequests += 1
        return route.fulfill({ status: 500 })
      },
    )
    await page.goto(`/?project=${projects[0].id}&view=inputs`)
    await page
      .getByRole("row")
      .filter({ hasText: first.display_filename })
      .getByRole("button", { name: "Preview selection" })
      .click()
    const errorCard = page.getByTestId("import-error")
    await expect(
      errorCard.getByRole("heading", { name: "Preview could not be read" }),
    ).toBeVisible()
    await expect(
      errorCard.getByText(
        "The preview response did not match the request identity. Nothing was applied.",
        { exact: true },
      ),
    ).toBeVisible()
    await expect(page.getByTestId("replacement-preview")).toHaveCount(0)
    await expect(
      page.getByRole("button", { name: "Set as current input" }),
    ).toHaveCount(0)
    expect(applyRequests).toBe(0)
  })
}

test("recovers a committed 503 operation without submitting again", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  let currentUploadId: string | null = null
  let applyRequests = 0
  let recoveryRequests = 0
  let receipt: Record<string, unknown> | null = null
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) => route.fulfill({ json: ledgerRead(null) }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    (route) =>
      route.fulfill({
        json: {
          candidate_upload_id: first.id,
          current_upload_id: null,
          current_revision_id: null,
          profile_id: first.profile_id,
          current_record_count: 0,
          current_unique_ips: 0,
          candidate_record_count: first.record_count,
          candidate_unique_ips: 1,
          added_ips: 1,
          removed_ips: 0,
          changed_ip_declarations: 0,
        },
      }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    async (route) => {
      applyRequests += 1
      const body = route.request().postDataJSON() as Record<string, unknown>
      receipt = replacementReceipt({
        candidateId: first.id,
        expectedUploadId: body.expected_upload_id as string | null,
        expectedRevisionId: body.expected_revision_id as string | null,
        expectedProfileId: body.expected_profile_id as string,
        digest: await requestDigest(body),
      })
      return route.fulfill({
        status: 503,
        json: {
          detail: {
            code: "ledger_commit_unknown",
            message: "The commit outcome is unknown.",
          },
        },
      })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/*`,
    async (route) => {
      if (route.request().method() !== "GET") return route.fallback()
      recoveryRequests += 1
      currentUploadId = first.id
      return route.fulfill({ json: receipt })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    async (route) => {
      if (route.request().method() === "POST")
        return route.fulfill({ status: 201, json: first })
      return route.fulfill({
        json: {
          data: [first],
          count: 1,
          current_customer_upload_id: currentUploadId,
          can_upload: true,
          can_select: true,
        },
      })
    },
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await page
    .getByRole("row")
    .filter({ hasText: first.display_filename })
    .getByRole("button", { name: "Preview selection" })
    .click()
  await page
    .getByTestId("replacement-preview")
    .getByRole("button", { name: "Set as current input" })
    .click()
  await expect(
    page.getByText("Selection outcome unknown", { exact: true }),
  ).toBeVisible()
  expect(recoveryRequests).toBe(0)
  const uploadForm = page.locator("form").filter({
    has: page.getByLabel("XLSX file"),
  })
  const uploadButton = uploadForm.getByRole("button", {
    name: "Upload",
    exact: true,
  })
  const chooseFile = uploadForm.getByRole("button", {
    name: "Choose file",
    exact: true,
  })
  const rowPreview = page
    .getByRole("row")
    .filter({ hasText: first.display_filename })
    .getByRole("button", { name: "Preview selection" })
  await expect(uploadButton).toBeDisabled()
  await expect(chooseFile).toBeDisabled()
  await expect(rowPreview).toBeDisabled()
  await expect(
    page.getByRole("button", { name: "Recover result" }),
  ).toBeEnabled()
  await page.getByRole("button", { name: "Recover result" }).click()
  await expect(page.getByTestId("operation-confirmed")).toBeVisible()
  expect(recoveryRequests).toBe(1)
  expect(applyRequests).toBe(1)
  await expect(uploadButton).toBeEnabled()
  await expect(chooseFile).toBeEnabled()
  const currentCard = page.locator('[data-slot="card"]').filter({
    has: page.getByRole("heading", { name: "Current Project input" }),
  })
  await expect(
    currentCard.getByText(first.display_filename, { exact: true }),
  ).toBeVisible()
})

test("keeps the intent and hides resend after a generic recovery 404", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  let applyRequests = 0
  let recoveryRequests = 0
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) => route.fulfill({ json: ledgerRead(null) }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    (route) =>
      route.fulfill({
        json: {
          candidate_upload_id: first.id,
          current_upload_id: null,
          current_revision_id: null,
          profile_id: first.profile_id,
          current_record_count: 0,
          current_unique_ips: 0,
          candidate_record_count: first.record_count,
          candidate_unique_ips: 1,
          added_ips: 1,
          removed_ips: 0,
          changed_ip_declarations: 0,
        },
      }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    (route) => {
      applyRequests += 1
      return route.abort("connectionfailed")
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/*`,
    (route) => {
      if (route.request().method() !== "GET") return route.fallback()
      recoveryRequests += 1
      return route.fulfill({
        status: 404,
        json: { detail: { code: "not_found", message: "Not found." } },
      })
    },
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await page
    .getByRole("row")
    .filter({ hasText: first.display_filename })
    .getByRole("button", { name: "Preview selection" })
    .click()
  await page
    .getByTestId("replacement-preview")
    .getByRole("button", { name: "Set as current input" })
    .click()
  await expect(
    page.getByText("Selection outcome unknown", { exact: true }),
  ).toBeVisible()
  await page.getByRole("button", { name: "Recover result" }).click()
  await expect(
    page.getByText(
      "Could not read the operation. Keep its identity and retry this read.",
      { exact: true },
    ),
  ).toBeVisible()
  expect(recoveryRequests).toBe(1)
  expect(applyRequests).toBe(1)
  await expect(
    page.getByRole("button", { name: "Resend original request" }),
  ).toHaveCount(0)
  expect(
    await page.evaluate(
      () =>
        Object.keys(sessionStorage).filter((key) =>
          key.startsWith("exposure:customer-replacement:"),
        ).length,
    ),
  ).toBe(1)
  await expect(
    page.getByRole("button", { name: "Recover result" }),
  ).toBeEnabled()
})

test("confirms a historical receipt without claiming it is still current", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  const second = {
    ...first,
    id: "20000000-0000-0000-0000-000000000020",
    display_filename: "newer-current.xlsx",
    raw_sha256: "9".repeat(64),
    record_count: 5,
  }
  let currentUploadId: string | null = null
  let applyRequests = 0
  let receipt: Record<string, unknown> | null = null
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) => route.fulfill({ json: ledgerRead(null) }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    (route) =>
      route.fulfill({
        json: {
          candidate_upload_id: first.id,
          current_upload_id: null,
          current_revision_id: null,
          profile_id: first.profile_id,
          current_record_count: 0,
          current_unique_ips: 0,
          candidate_record_count: first.record_count,
          candidate_unique_ips: 1,
          added_ips: 1,
          removed_ips: 0,
          changed_ip_declarations: 0,
        },
      }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    async (route) => {
      applyRequests += 1
      const body = route.request().postDataJSON() as Record<string, unknown>
      receipt = replacementReceipt({
        candidateId: first.id,
        expectedUploadId: body.expected_upload_id as string | null,
        expectedRevisionId: body.expected_revision_id as string | null,
        expectedProfileId: body.expected_profile_id as string,
        digest: await requestDigest(body),
      })
      return route.abort("connectionfailed")
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/*`,
    (route) => {
      if (route.request().method() !== "GET") return route.fallback()
      currentUploadId = second.id
      return route.fulfill({ json: receipt })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    async (route) => {
      if (route.request().method() === "POST")
        return route.fulfill({ status: 201, json: first })
      return route.fulfill({
        json: {
          data: [first, second],
          count: 2,
          current_customer_upload_id: currentUploadId,
          can_upload: true,
          can_select: true,
        },
      })
    },
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await page
    .getByRole("row")
    .filter({ hasText: first.display_filename })
    .getByRole("button", { name: "Preview selection" })
    .click()
  await page
    .getByTestId("replacement-preview")
    .getByRole("button", { name: "Set as current input" })
    .click()
  await expect(
    page.getByText("Selection outcome unknown", { exact: true }),
  ).toBeVisible()
  await page.getByRole("button", { name: "Recover result" }).click()
  const confirmation = page.getByTestId("operation-confirmed")
  await expect(confirmation).toBeVisible()
  await expect(
    confirmation.getByText(first.display_filename, { exact: true }),
  ).toHaveCount(0)
  const currentCard = page.locator('[data-slot="card"]').filter({
    has: page.getByRole("heading", { name: "Current Project input" }),
  })
  await expect(
    currentCard.getByText(second.display_filename, { exact: true }),
  ).toBeVisible()
  await expect(
    page
      .getByRole("row")
      .filter({ hasText: second.display_filename })
      .getByText("Current", { exact: true }),
  ).toBeVisible()
  expect(applyRequests).toBe(1)
})

test("clears a saved replacement intent when accepted-upload reads are forbidden", async ({
  page,
}) => {
  const first = uploads[projects[0].id as keyof typeof uploads].data[0]
  const request = {
    candidate_upload_id: first.id,
    expected_upload_id: null,
    expected_revision_id: null,
    expected_profile_id: first.profile_id,
  }
  const storageKey = `exposure:customer-replacement:${operatorId}:${projects[0].id}`
  const savedIntent = {
    key: "saved-denied-intent",
    digest: await requestDigest(request),
    request,
  }
  await page.addInitScript(
    ([key, intent]) => {
      sessionStorage.setItem(key, JSON.stringify(intent))
    },
    [storageKey, savedIntent] as const,
  )
  let uploadPosts = 0
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    (route) => {
      if (route.request().method() === "POST") {
        uploadPosts += 1
        return route.fulfill({ status: 201, json: first })
      }
      return route.fulfill({
        status: 403,
        json: { detail: { code: "forbidden", message: "Forbidden." } },
      })
    },
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await expect(
    page.getByText("Current input could not be read", { exact: true }),
  ).toBeVisible({ timeout: 15_000 })
  expect(uploadPosts).toBe(0)
  await expect(page.getByTestId("operation-state")).toHaveCount(0)
  await expect(
    page.getByRole("button", { name: "Recover result" }),
  ).toHaveCount(0)
  await expect(
    page.getByText("Selection outcome unknown", { exact: true }),
  ).toHaveCount(0)
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          Object.keys(sessionStorage).filter((key) =>
            key.startsWith("exposure:customer-replacement:"),
          ).length,
      ),
    )
    .toBe(0)
})

test("keeps confirmation and shows a separate current-read failure with retry", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  let currentUploadId: string | null = null
  let failCurrentRead = false
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) => route.fulfill({ json: ledgerRead(null) }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    (route) =>
      route.fulfill({
        json: {
          candidate_upload_id: first.id,
          current_upload_id: null,
          current_revision_id: null,
          profile_id: first.profile_id,
          current_record_count: 0,
          current_unique_ips: 0,
          candidate_record_count: first.record_count,
          candidate_unique_ips: 1,
          added_ips: 1,
          removed_ips: 0,
          changed_ip_declarations: 0,
        },
      }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    async (route) => {
      const body = route.request().postDataJSON() as Record<string, unknown>
      const receipt = replacementReceipt({
        candidateId: first.id,
        expectedUploadId: body.expected_upload_id as string | null,
        expectedRevisionId: body.expected_revision_id as string | null,
        expectedProfileId: body.expected_profile_id as string,
        digest: await requestDigest(body),
      })
      currentUploadId = first.id
      failCurrentRead = true
      return route.fulfill({ json: receipt })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    async (route) => {
      if (route.request().method() === "POST")
        return route.fulfill({ status: 201, json: first })
      if (failCurrentRead)
        return route.fulfill({
          status: 500,
          json: { detail: { code: "internal_error", message: "Read failed." } },
        })
      return route.fulfill({
        json: {
          data: [first],
          count: 1,
          current_customer_upload_id: currentUploadId,
          can_upload: true,
          can_select: true,
        },
      })
    },
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await page
    .getByRole("row")
    .filter({ hasText: first.display_filename })
    .getByRole("button", { name: "Preview selection" })
    .click()
  await page
    .getByTestId("replacement-preview")
    .getByRole("button", { name: "Set as current input" })
    .click()
  const confirmation = page.getByTestId("operation-confirmed")
  await expect(confirmation).toBeVisible()
  await expect(
    page.getByText("Current input could not be read", { exact: true }),
  ).toBeVisible({ timeout: 15_000 })
  await expect(confirmation).toBeVisible()
  failCurrentRead = false
  await page.getByRole("button", { name: "Retry current input" }).click()
  const currentCard = page.locator('[data-slot="card"]').filter({
    has: page.getByRole("heading", { name: "Current Project input" }),
  })
  await expect(
    currentCard.getByText(first.display_filename, { exact: true }),
  ).toBeVisible()
  await expect(confirmation).toBeVisible()
  await expect(
    page.getByText("Current input could not be read", { exact: true }),
  ).toHaveCount(0)
})

test("shows a recoverable read error when the current input becomes unavailable during preview", async ({
  page,
}) => {
  const first = uploads[projects[0].id as keyof typeof uploads].data[0]
  let failCurrentReads = false
  let failedUploadsReadGateUsed = false
  let releaseFailedUploadsRead: () => void = () => undefined
  const failedUploadsReadGate = new Promise<void>((resolve) => {
    releaseFailedUploadsRead = resolve
  })
  let previewRequests = 0
  let releasePreview: () => void = () => undefined
  const previewGate = new Promise<void>((resolve) => {
    releasePreview = resolve
  })
  let applyRequests = 0
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) => route.fulfill({ json: ledgerRead(null) }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    async (route) => {
      previewRequests += 1
      if (previewRequests === 1) await previewGate
      return route.fulfill({
        json: {
          candidate_upload_id: first.id,
          current_upload_id: null,
          current_revision_id: null,
          profile_id: first.profile_id,
          current_record_count: 0,
          current_unique_ips: 0,
          candidate_record_count: first.record_count,
          candidate_unique_ips: 1,
          added_ips: 1,
          removed_ips: 0,
          changed_ip_declarations: 0,
        },
      })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    (route) => {
      applyRequests += 1
      return route.fulfill({ status: 500 })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    async (route) => {
      if (route.request().method() === "POST") {
        failCurrentReads = true
        return route.fulfill({ status: 201, json: first })
      }
      if (failCurrentReads) {
        if (!failedUploadsReadGateUsed) {
          failedUploadsReadGateUsed = true
          await failedUploadsReadGate
        }
        return route.fulfill({
          status: 500,
          json: { detail: { code: "internal_error", message: "Read failed." } },
        })
      }
      return route.fulfill({
        json: {
          data: [first],
          count: 1,
          current_customer_upload_id: null,
          can_upload: true,
          can_select: true,
        },
      })
    },
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await uploadXlsx(page, "preview-current-read-race.xlsx")
  await expect(page.getByTestId("upload-candidate")).toBeVisible()
  await page.getByRole("button", { name: "Preview this file" }).click()
  await expect.poll(() => previewRequests).toBe(1)
  releaseFailedUploadsRead()
  await expect(
    page.getByText("Current input could not be read", { exact: true }),
  ).toBeVisible({ timeout: 15_000 })
  failCurrentReads = false
  releasePreview()
  await expect(page.getByTestId("import-error")).toBeVisible()
  await expect(
    page.getByText(
      "The current input could not be refreshed. Nothing was applied.",
    ),
  ).toBeVisible()
  await expect(page.getByText("Reading preview…", { exact: true })).toHaveCount(
    0,
  )
  await expect(page.getByTestId("replacement-preview")).toHaveCount(0)
  const previewAgain = page.getByRole("button", {
    name: "Preview this file again",
  })
  await expect(previewAgain).toBeDisabled()
  expect(applyRequests).toBe(0)
  await page.getByRole("button", { name: "Retry current input" }).click()
  await expect(
    page.getByText("Current input could not be read", { exact: true }),
  ).toHaveCount(0)
  await expect(previewAgain).toBeEnabled()
  await previewAgain.click()
  await expect(page.getByTestId("replacement-preview")).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Set as current input" }),
  ).toBeEnabled()
  expect(previewRequests).toBe(2)
  expect(applyRequests).toBe(0)
})

test("keeps long candidate names and the full keyboard journey usable at 390px", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  const longName = `${"long-candidate-filename-".repeat(6)}.xlsx`
  const candidate = {
    ...first,
    id: "20000000-0000-0000-0000-000000000021",
    display_filename: longName,
    raw_sha256: "a".repeat(64),
  }
  let accepted = false
  let currentUploadId: string | null = null
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) => route.fulfill({ json: ledgerRead(null) }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    (route) =>
      route.fulfill({
        json: {
          candidate_upload_id: candidate.id,
          current_upload_id: null,
          current_revision_id: null,
          profile_id: candidate.profile_id,
          current_record_count: 0,
          current_unique_ips: 0,
          candidate_record_count: candidate.record_count,
          candidate_unique_ips: 1,
          added_ips: 1,
          removed_ips: 0,
          changed_ip_declarations: 0,
        },
      }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    async (route) => {
      const body = route.request().postDataJSON() as Record<string, unknown>
      currentUploadId = candidate.id
      return route.fulfill({
        json: replacementReceipt({
          candidateId: candidate.id,
          expectedUploadId: body.expected_upload_id as string | null,
          expectedRevisionId: body.expected_revision_id as string | null,
          expectedProfileId: body.expected_profile_id as string,
          digest: await requestDigest(body),
        }),
      })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    async (route) => {
      if (route.request().method() === "POST") {
        accepted = true
        return route.fulfill({ status: 201, json: candidate })
      }
      return route.fulfill({
        json: {
          data: accepted ? [first, candidate] : [first],
          count: accepted ? 2 : 1,
          current_customer_upload_id: currentUploadId,
          can_upload: true,
          can_select: true,
        },
      })
    },
  )
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  const customerForm = page
    .locator("form")
    .filter({ has: page.getByLabel("XLSX file") })
  const picker = customerForm.getByRole("button", {
    name: "Choose file",
    exact: true,
  })
  await picker.focus()
  await expect(picker).toBeFocused()
  const input = page.getByLabel("XLSX file")
  await input.setInputFiles({
    name: longName,
    mimeType:
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: Buffer.from("mock workbook"),
  })
  await expect(page.getByText(longName, { exact: true })).toBeVisible()
  const upload = page
    .locator("form")
    .filter({ has: input })
    .getByRole("button", { name: "Upload", exact: true })
  await upload.focus()
  await page.keyboard.press("Enter")
  const candidateHeading = page
    .getByTestId("upload-candidate")
    .getByRole("heading", { name: "Accepted file" })
  await expect(candidateHeading).toBeFocused()
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBeLessThanOrEqual(390)
  const preview = page
    .getByTestId("upload-candidate")
    .getByRole("button", { name: "Preview this file" })
  await tabTo(page, preview)
  await page.keyboard.press("Enter")
  const previewHeading = page
    .getByTestId("replacement-preview")
    .getByRole("heading", { name: "Selection preview" })
  await expect(previewHeading).toBeFocused()
  const apply = page.getByRole("button", { name: "Set as current input" })
  await tabTo(page, apply)
  const applyBounds = await apply.boundingBox()
  expect(applyBounds).not.toBeNull()
  expect(applyBounds!.x).toBeGreaterThanOrEqual(0)
  expect(applyBounds!.x + applyBounds!.width).toBeLessThanOrEqual(390)
  await page.keyboard.press("Enter")
  const confirmedHeading = page
    .getByTestId("operation-confirmed")
    .getByRole("heading", { name: "Operation confirmed." })
  await expect(confirmedHeading).toBeFocused()
  const link = page.getByRole("link", { name: "Go to comparison results" })
  await tabTo(page, link)
  await expect(link).toBeVisible()
  const linkBounds = await link.boundingBox()
  expect(linkBounds).not.toBeNull()
  expect(linkBounds!.x).toBeGreaterThanOrEqual(0)
  expect(linkBounds!.x + linkBounds!.width).toBeLessThanOrEqual(390)
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBeLessThanOrEqual(390)
})

test("keeps 409 and recovery headings and actions keyboard-reachable at 390px", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  const second = {
    ...first,
    id: "20000000-0000-0000-0000-000000000022",
    display_filename: "narrow-conflict.xlsx",
    raw_sha256: "b".repeat(64),
  }
  let ledger = ledgerRead(first.id)
  let applyRequests = 0
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) => route.fulfill({ json: ledger }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    (route) => {
      const body = route.request().postDataJSON() as Record<string, unknown>
      return route.fulfill({
        json: {
          candidate_upload_id: second.id,
          current_upload_id: body.expected_upload_id,
          current_revision_id: body.expected_revision_id,
          profile_id: body.expected_profile_id,
          current_record_count: first.record_count,
          current_unique_ips: 1,
          candidate_record_count: second.record_count,
          candidate_unique_ips: 1,
          added_ips: 0,
          removed_ips: 0,
          changed_ip_declarations: 1,
        },
      })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    (route) => {
      applyRequests += 1
      if (applyRequests === 1)
        return route.fulfill({
          status: 409,
          json: {
            detail: {
              code: "ledger_version_conflict",
              message: "The current input changed.",
            },
          },
        })
      return route.fulfill({
        status: 503,
        json: {
          detail: {
            code: "ledger_commit_unknown",
            message: "The commit outcome is unknown.",
          },
        },
      })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    async (route) => {
      if (route.request().method() === "POST")
        return route.fulfill({ status: 201, json: second })
      return route.fulfill({
        json: {
          data: [first, second],
          count: 2,
          current_customer_upload_id: first.id,
          can_upload: true,
          can_select: true,
        },
      })
    },
  )
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await page
    .getByRole("row")
    .filter({ hasText: second.display_filename })
    .getByRole("button", { name: "Preview replacement" })
    .click()
  await page
    .getByTestId("replacement-preview")
    .getByRole("button", { name: "Apply replacement" })
    .click()
  const errorHeading = page
    .getByTestId("import-error")
    .getByRole("heading", { name: "Current version changed" })
  await expect(errorHeading).toBeFocused()
  const rePreview = page.getByRole("button", {
    name: "Read latest version and preview again",
  })
  await tabTo(page, rePreview)
  const rePreviewBounds = await rePreview.boundingBox()
  expect(rePreviewBounds).not.toBeNull()
  expect(rePreviewBounds!.x).toBeGreaterThanOrEqual(0)
  expect(rePreviewBounds!.x + rePreviewBounds!.width).toBeLessThanOrEqual(390)
  ledger = ledgerRead("20000000-0000-0000-0000-000000000023")
  await page.keyboard.press("Enter")
  await expect(page.getByTestId("replacement-preview")).toBeVisible()
  await page
    .getByTestId("replacement-preview")
    .getByRole("button", { name: "Apply replacement" })
    .click()
  const recoveryHeading = page
    .getByTestId("operation-state")
    .getByRole("heading", { name: "Replacement outcome unknown" })
  await expect(recoveryHeading).toBeFocused()
  const recover = page.getByRole("button", { name: "Recover result" })
  await tabTo(page, recover)
  const recoverBounds = await recover.boundingBox()
  expect(recoverBounds).not.toBeNull()
  expect(recoverBounds!.x).toBeGreaterThanOrEqual(0)
  expect(recoverBounds!.x + recoverBounds!.width).toBeLessThanOrEqual(390)
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBeLessThanOrEqual(390)
  expect(applyRequests).toBe(2)
})

test("labels ledger diagnostics as ledger rows, never worksheet rows", async ({
  page,
}) => {
  const uploadId = "20000000-0000-0000-0000-000000000007"
  const entryId = "40000000-0000-0000-0000-000000000007"
  const profileId = profiles[projects[0].id].id
  const ledgerPage = {
    project_id: projects[0].id,
    upload_id: uploadId,
    revision_id: null,
    current_upload_id: uploadId,
    current_revision_id: null,
    current_profile_id: profileId,
    data: [
      {
        entry_id: entryId,
        position: 1,
        canonical_ip: "2001:db8::7",
        fields: {
          asset_ip: "2001:db8::7",
          start_port: 8443,
          end_port: 443,
          is_web: "否",
          web_url: null,
          service_type: "",
          asset_owner: "",
          asset_department: "",
          port_owner: "",
          department: "",
          serial: "",
        },
        management: { owner: "", tags: [] },
        archived: false,
      },
    ],
    count: 1,
    total_records: 1,
    unique_ips: 1,
    can_edit: true,
  }
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) => route.fulfill({ json: ledgerPage }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/revisions*`,
    (route) => {
      if (route.request().method() === "GET") return route.fulfill({ json: [] })
      return route.fulfill({
        status: 422,
        json: {
          detail: {
            code: "ledger_fields_invalid",
            field: "start_port",
            row: 1,
            reason: "port_order",
            location: "ledger",
          },
        },
      })
    },
  )
  await page.goto(`/projects/${projects[0].id}/customer-ledger`)
  await page.getByRole("button", { name: "Correct", exact: true }).click()
  await page.getByLabel("Reason for this change").fill("Correct the port order")
  await page.getByRole("button", { name: "Save new revision" }).click()

  const details = page.getByTestId("diagnostic-details")
  await expect(details).toBeVisible()
  await expect(details.getByText("Ledger row", { exact: true })).toBeVisible()
  await expect(details.getByText("Start port", { exact: true })).toBeVisible()
  await expect(
    details.getByText("Start port must not exceed end port", { exact: true }),
  ).toBeVisible()
  await expect(details.getByText("Worksheet row", { exact: true })).toHaveCount(
    0,
  )
  await expect(
    details.getByText("Original Excel row", { exact: true }),
  ).toHaveCount(0)
})

test("delivery measures five upload feedback samples and preserves rejection", async ({
  page,
}) => {
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    async (route) => {
      if (route.request().method() !== "POST") return route.fallback()
      await new Promise((resolve) => setTimeout(resolve, 350))
      return route.fulfill({
        status: 422,
        json: {
          detail: {
            code: "invalid_workbook",
            message: "The workbook is malformed.",
          },
        },
      })
    },
  )
  const samples = []
  for (let i = 0; i < 5; i++) {
    await page.goto("/?view=inputs")
    const input = page.getByLabel("XLSX file")
    await input.setInputFiles({
      name: "invalid.xlsx",
      mimeType:
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      buffer: Buffer.from("invalid"),
    })
    const button = page
      .locator("form")
      .filter({ has: input })
      .getByRole("button", { name: "Upload", exact: true })
    samples.push(await feedback(button))
    await expect(
      page.getByText("The workbook is malformed.", { exact: false }),
    ).toBeVisible()
  }
  recordFeedback("upload", samples)
})

function replacementPreview(
  candidate: { id: string; profile_id: string; record_count: number },
  request: {
    expected_upload_id?: unknown
    expected_revision_id?: unknown
    expected_profile_id?: unknown
  },
) {
  const replacing =
    request.expected_upload_id !== null &&
    request.expected_upload_id !== undefined
  return {
    candidate_upload_id: candidate.id,
    current_upload_id: request.expected_upload_id ?? null,
    current_revision_id: request.expected_revision_id ?? null,
    profile_id: request.expected_profile_id,
    current_record_count: replacing ? candidate.record_count : 0,
    current_unique_ips: replacing ? 1 : 0,
    candidate_record_count: candidate.record_count,
    candidate_unique_ips: 1,
    added_ips: replacing ? 0 : 1,
    removed_ips: 0,
    changed_ip_declarations: 0,
  }
}

test("keeps the visible file, native picker, and upload request consistent after cancelling a preview", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  const accepted = {
    ...first,
    id: "20000000-0000-0000-0000-000000000030",
    display_filename: "after-cancel.xlsx",
    raw_sha256: "7".repeat(64),
  }
  let previewRequests = 0
  let applyRequests = 0
  let uploadRequests = 0
  const uploadedNames: string[] = []
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) => route.fulfill({ json: ledgerRead(null) }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    (route) => {
      previewRequests += 1
      const body = route.request().postDataJSON() as Record<string, unknown>
      return route.fulfill({ json: replacementPreview(first, body) })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    (route) => {
      applyRequests += 1
      return route.fulfill({ status: 500 })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    async (route) => {
      if (route.request().method() === "POST") {
        uploadRequests += 1
        const match = /filename="([^"]+)"/.exec(
          route.request().postData() ?? "",
        )
        uploadedNames.push(match?.[1] ?? "")
        return route.fulfill({ status: 201, json: accepted })
      }
      return route.fulfill({ json: uploads[projects[0].id] })
    },
  )
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  const input = page.getByLabel("XLSX file", { exact: true })
  await input.setInputFiles({
    name: "hidden-local.xlsx",
    mimeType:
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: Buffer.from("hidden local workbook"),
  })
  await expect(
    page.getByText("hidden-local.xlsx", { exact: true }),
  ).toBeVisible()
  const trigger = page
    .getByRole("row")
    .filter({ hasText: first.display_filename })
    .getByRole("button", { name: "Preview selection" })
  await trigger.focus()
  await page.keyboard.press("Enter")
  await expect(page.getByTestId("replacement-preview")).toBeVisible()
  const cancel = page
    .getByTestId("replacement-preview")
    .getByRole("button", { name: "Cancel", exact: true })
  await cancel.focus()
  await page.keyboard.press("Enter")
  await expect(trigger).toBeFocused()
  await expect(
    page
      .locator("#customer-inputs")
      .getByText("No file chosen", { exact: true }),
  ).toBeVisible()
  const nativeFilesBeforeUpload = await input.evaluate((element) =>
    Array.from((element as HTMLInputElement).files ?? []).map(
      (file) => file.name,
    ),
  )
  const upload = page
    .locator("form")
    .filter({ has: input })
    .getByRole("button", { name: "Upload", exact: true })
  await upload.focus()
  await page.keyboard.press("Enter")
  await page.waitForTimeout(300)
  const nativeFilesAfterUpload = await input.evaluate((element) =>
    Array.from((element as HTMLInputElement).files ?? []).map(
      (file) => file.name,
    ),
  )
  expect({
    nativeFilesBeforeUpload,
    nativeFilesAfterUpload,
    uploadRequests,
  }).toEqual({
    nativeFilesBeforeUpload: [],
    nativeFilesAfterUpload: [],
    uploadRequests: 0,
  })
  await expect(page.getByTestId("import-error-summary")).toContainText(
    "Choose one XLSX file to upload.",
  )
  expect(previewRequests).toBe(1)
  expect(applyRequests).toBe(0)
  await expect(page.getByText("Project input is not ready.")).toBeVisible()

  const chooserPromise = page.waitForEvent("filechooser")
  const chooseFile = page
    .locator("#customer-inputs")
    .getByRole("button", { name: "Choose file", exact: true })
  await chooseFile.focus()
  await page.keyboard.press("Enter")
  const chooser = await chooserPromise
  await chooser.setFiles({
    name: "after-cancel.xlsx",
    mimeType:
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: Buffer.from("reselect workbook"),
  })
  await expect(
    page.getByText("after-cancel.xlsx", { exact: true }),
  ).toBeVisible()
  await upload.focus()
  await page.keyboard.press("Enter")
  await expect(page.getByTestId("upload-candidate")).toBeVisible()
  expect(uploadRequests).toBe(1)
  expect(uploadedNames).toEqual(["after-cancel.xlsx"])
  await expect(
    page
      .getByTestId("upload-candidate")
      .getByText("after-cancel.xlsx", { exact: true }),
  ).toBeVisible()
  expect(applyRequests).toBe(0)
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390)
})

test("keeps a submitted operation when a readable project becomes read-only", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  const storageKey = `exposure:customer-replacement:${operatorId}:${projects[0].id}`
  let canSelect = true
  let applyRequests = 0
  let recoveryRequests = 0
  let recoveryKey = ""
  let receipt: Record<string, unknown> | null = null
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) => route.fulfill({ json: ledgerRead(null) }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    (route) => {
      const body = route.request().postDataJSON() as Record<string, unknown>
      return route.fulfill({ json: replacementPreview(first, body) })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    async (route) => {
      applyRequests += 1
      const body = route.request().postDataJSON()
      receipt = replacementReceipt({
        candidateId: first.id,
        expectedUploadId: body.expected_upload_id,
        expectedRevisionId: body.expected_revision_id,
        expectedProfileId: body.expected_profile_id,
        digest: await requestDigest(body),
      })
      return route.fulfill({
        status: 503,
        json: {
          detail: {
            code: "ledger_commit_unknown",
            message: "The commit outcome is unknown.",
          },
        },
      })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/*`,
    (route) => {
      if (route.request().method() !== "GET") return route.fallback()
      recoveryRequests += 1
      recoveryKey = new URL(route.request().url()).pathname
      return route.fulfill({ json: receipt })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    (route) => {
      if (route.request().method() === "POST") return route.fallback()
      return route.fulfill({
        json: {
          data: [first],
          count: 1,
          current_customer_upload_id: null,
          can_upload: canSelect,
          can_select: canSelect,
        },
      })
    },
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await page.getByRole("button", { name: "Preview selection" }).click()
  await page.getByRole("button", { name: "Set as current input" }).click()
  await expect(
    page.getByText("Selection outcome unknown", { exact: true }),
  ).toBeVisible()
  const saved = await page.evaluate(
    (key) => sessionStorage.getItem(key),
    storageKey,
  )
  if (!saved) throw new Error("Expected a saved replacement intent")
  canSelect = false
  await page.evaluate(() => window.dispatchEvent(new Event("visibilitychange")))
  await expect(
    page.getByText(
      "You have read-only access to CustomerUpload inputs for this Project.",
    ),
  ).toBeVisible()
  expect(
    await page.evaluate((key) => sessionStorage.getItem(key), storageKey),
  ).toBe(saved)
  const recover = page.getByRole("button", { name: "Recover result" })
  await expect(recover).toBeVisible()
  await expect(recover).toBeEnabled()
  expect(applyRequests).toBe(1)
  await recover.click()
  await expect(page.getByTestId("operation-confirmed")).toBeVisible()
  expect(recoveryRequests).toBe(1)
  expect(recoveryKey.endsWith(JSON.parse(saved).key)).toBe(true)
  expect(applyRequests).toBe(1)
})

test("keeps a read-only intent after a structured missing receipt and resends only after writability returns", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  const storageKey = `exposure:customer-replacement:${operatorId}:${projects[0].id}`
  let canSelect = true
  let applyAttempts = 0
  let recoveryRequests = 0
  const applyKeys: string[] = []
  const applyBodies: Record<string, unknown>[] = []
  let receipt: Record<string, unknown> | null = null
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) => route.fulfill({ json: ledgerRead(null) }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    (route) => {
      const body = route.request().postDataJSON() as Record<string, unknown>
      return route.fulfill({ json: replacementPreview(first, body) })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    async (route) => {
      applyAttempts += 1
      const body = route.request().postDataJSON()
      applyKeys.push(route.request().headers()["idempotency-key"] ?? "")
      applyBodies.push(body)
      receipt = replacementReceipt({
        candidateId: first.id,
        expectedUploadId: body.expected_upload_id,
        expectedRevisionId: body.expected_revision_id,
        expectedProfileId: body.expected_profile_id,
        digest: await requestDigest(body),
      })
      if (applyAttempts === 1)
        return route.fulfill({
          status: 503,
          json: {
            detail: {
              code: "ledger_commit_unknown",
              message: "The commit outcome is unknown.",
            },
          },
        })
      return route.fulfill({ json: receipt })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/*`,
    (route) => {
      if (route.request().method() !== "GET") return route.fallback()
      recoveryRequests += 1
      return route.fulfill({
        status: 404,
        json: {
          detail: {
            code: "ledger_replacement_not_found",
            message: "No completed replacement receipt.",
          },
        },
      })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    (route) => {
      if (route.request().method() === "POST") return route.fallback()
      return route.fulfill({
        json: {
          data: [first],
          count: 1,
          current_customer_upload_id: null,
          can_upload: canSelect,
          can_select: canSelect,
        },
      })
    },
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await page.getByRole("button", { name: "Preview selection" }).click()
  await page.getByRole("button", { name: "Set as current input" }).click()
  await expect(
    page.getByText("Selection outcome unknown", { exact: true }),
  ).toBeVisible()
  const saved = await page.evaluate(
    (key) => sessionStorage.getItem(key),
    storageKey,
  )
  if (!saved) throw new Error("Expected a saved replacement intent")
  canSelect = false
  await page.evaluate(() => window.dispatchEvent(new Event("visibilitychange")))
  await expect(
    page.getByText(
      "You have read-only access to CustomerUpload inputs for this Project.",
    ),
  ).toBeVisible()
  const recover = page.getByRole("button", { name: "Recover result" })
  await expect(recover).toBeVisible()
  await recover.click()
  await expect(
    page.getByText("No completed receipt yet.", { exact: false }),
  ).toBeVisible()
  const resend = page.getByRole("button", { name: "Resend original request" })
  await expect(resend).toBeVisible()
  await expect(resend).toBeDisabled()
  expect(recoveryRequests).toBe(1)
  expect(applyAttempts).toBe(1)
  expect(
    await page.evaluate((key) => sessionStorage.getItem(key), storageKey),
  ).toBe(saved)

  canSelect = true
  await page.evaluate(() => window.dispatchEvent(new Event("visibilitychange")))
  await expect(
    page.getByText(
      "You have read-only access to CustomerUpload inputs for this Project.",
    ),
  ).toHaveCount(0)
  await expect(resend).toBeEnabled()
  await resend.click()
  await expect(page.getByTestId("operation-confirmed")).toBeVisible()
  expect(applyAttempts).toBe(2)
  expect(applyKeys[0]).toBe(applyKeys[1])
  expect(applyBodies[0]).toEqual(applyBodies[1])
})

test("keeps an in-flight apply resolvable when write access is downgraded", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  const storageKey = `exposure:customer-replacement:${operatorId}:${projects[0].id}`
  let canSelect = true
  let applyRequests = 0
  let recoveryRequests = 0
  let releaseApply: () => void = () => undefined
  const applyGate = new Promise<void>((resolve) => {
    releaseApply = resolve
  })
  let receipt: Record<string, unknown> | null = null
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) => route.fulfill({ json: ledgerRead(null) }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    (route) => {
      const body = route.request().postDataJSON() as Record<string, unknown>
      return route.fulfill({ json: replacementPreview(first, body) })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    async (route) => {
      applyRequests += 1
      const body = route.request().postDataJSON()
      receipt = replacementReceipt({
        candidateId: first.id,
        expectedUploadId: body.expected_upload_id,
        expectedRevisionId: body.expected_revision_id,
        expectedProfileId: body.expected_profile_id,
        digest: await requestDigest(body),
      })
      await applyGate
      return route.fulfill({ json: receipt })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/*`,
    (route) => {
      if (route.request().method() !== "GET") return route.fallback()
      recoveryRequests += 1
      return route.fulfill({ json: receipt })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    (route) => {
      if (route.request().method() === "POST") return route.fallback()
      return route.fulfill({
        json: {
          data: [first],
          count: 1,
          current_customer_upload_id: null,
          can_upload: canSelect,
          can_select: canSelect,
        },
      })
    },
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await page.getByRole("button", { name: "Preview selection" }).click()
  await page.getByRole("button", { name: "Set as current input" }).click()
  await expect(
    page.getByText("Setting current input…", { exact: true }),
  ).toBeVisible()
  expect(applyRequests).toBe(1)
  const saved = await page.evaluate(
    (key) => sessionStorage.getItem(key),
    storageKey,
  )
  if (!saved) throw new Error("Expected a saved replacement intent")
  canSelect = false
  await page.evaluate(() => window.dispatchEvent(new Event("visibilitychange")))
  await expect(
    page.getByText(
      "You have read-only access to CustomerUpload inputs for this Project.",
    ),
  ).toBeVisible()
  try {
    expect(
      await page.evaluate((key) => sessionStorage.getItem(key), storageKey),
    ).toBe(saved)
    await expect(
      page.getByText("Setting current input…", { exact: true }),
    ).toBeVisible()
    const recover = page.getByRole("button", { name: "Recover result" })
    await expect(recover).toBeVisible()
    await expect(recover).toBeEnabled()
  } finally {
    releaseApply()
  }
  await expect(page.getByTestId("operation-confirmed")).toBeVisible()
  expect(applyRequests).toBe(1)
  expect(recoveryRequests).toBe(0)
})

test("restores a saved operation and its read-only receipt recovery at 390px", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  const storageKey = `exposure:customer-replacement:${operatorId}:${projects[0].id}`
  const request = {
    candidate_upload_id: first.id,
    expected_upload_id: null,
    expected_revision_id: null,
    expected_profile_id: first.profile_id,
  }
  const savedIntent = {
    key: "saved-readable-intent",
    digest: await requestDigest(request),
    request,
  }
  const receipt = replacementReceipt({
    candidateId: first.id,
    expectedUploadId: null,
    expectedRevisionId: null,
    expectedProfileId: first.profile_id,
    digest: savedIntent.digest,
  })
  let applyRequests = 0
  let recoveryRequests = 0
  let recoveryKey = ""
  await page.addInitScript(
    ([key, intent]) => {
      sessionStorage.setItem(key, JSON.stringify(intent))
    },
    [storageKey, savedIntent] as const,
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    (route) => {
      if (route.request().method() === "POST") {
        applyRequests += 1
        return route.fulfill({ status: 500 })
      }
      return route.fulfill({
        json: {
          data: [first],
          count: 1,
          current_customer_upload_id: null,
          can_upload: false,
          can_select: false,
        },
      })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/*`,
    (route) => {
      if (route.request().method() !== "GET") return route.fallback()
      recoveryRequests += 1
      recoveryKey = new URL(route.request().url()).pathname
      return route.fulfill({ json: receipt })
    },
  )
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await expect(
    page.getByText(
      "You have read-only access to CustomerUpload inputs for this Project.",
    ),
  ).toBeVisible()
  await expect(
    page.getByText("Selection outcome unknown", { exact: true }),
  ).toBeVisible()
  expect(
    await page.evaluate((key) => sessionStorage.getItem(key), storageKey),
  ).toBe(JSON.stringify(savedIntent))
  const recoveryHeading = page
    .getByTestId("operation-state")
    .getByRole("heading", { name: "Selection outcome unknown" })
  await recoveryHeading.focus()
  await page.keyboard.press("Tab")
  const recover = page.getByRole("button", { name: "Recover result" })
  await expect(recover).toBeFocused()
  const bounds = await recover.boundingBox()
  expect(bounds).not.toBeNull()
  expect(bounds!.x).toBeGreaterThanOrEqual(0)
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390)
  await page.keyboard.press("Enter")
  await expect(page.getByTestId("operation-confirmed")).toBeVisible()
  expect(recoveryRequests).toBe(1)
  expect(recoveryKey.endsWith(savedIntent.key)).toBe(true)
  expect(applyRequests).toBe(0)
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390)
})

test("does not confirm a receipt whose Project or actor identity differs", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  const storageKey = `exposure:customer-replacement:${operatorId}:${projects[0].id}`
  const request = {
    candidate_upload_id: first.id,
    expected_upload_id: null,
    expected_revision_id: null,
    expected_profile_id: first.profile_id,
  }
  const savedIntent = {
    key: "saved-identity-intent",
    digest: await requestDigest(request),
    request,
  }
  const valid = replacementReceipt({
    candidateId: first.id,
    expectedUploadId: null,
    expectedRevisionId: null,
    expectedProfileId: first.profile_id,
    digest: savedIntent.digest,
  })
  let variant: "project" | "actor" | "valid" = "project"
  let recoveryRequests = 0
  await page.addInitScript(
    ([key, intent]) => {
      sessionStorage.setItem(key, JSON.stringify(intent))
    },
    [storageKey, savedIntent] as const,
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    (route) =>
      route.fulfill({
        json: {
          data: [first],
          count: 1,
          current_customer_upload_id: null,
          can_upload: false,
          can_select: false,
        },
      }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/*`,
    (route) => {
      if (route.request().method() !== "GET") return route.fallback()
      recoveryRequests += 1
      if (variant === "project")
        return route.fulfill({
          json: { ...valid, project_id: projects[1].id },
        })
      if (variant === "actor")
        return route.fulfill({
          json: {
            ...valid,
            created_by: "30000000-0000-0000-0000-000000000099",
          },
        })
      return route.fulfill({ json: valid })
    },
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await expect(
    page.getByText("Selection outcome unknown", { exact: true }),
  ).toBeVisible()
  const recover = page.getByRole("button", { name: "Recover result" })
  await recover.click()
  await expect(
    page.getByText(
      "Could not read the operation. Keep its identity and retry this read.",
      { exact: true },
    ),
  ).toBeVisible()
  expect(await page.getByTestId("operation-confirmed").count()).toBe(0)
  expect(
    await page.evaluate((key) => sessionStorage.getItem(key), storageKey),
  ).toBe(JSON.stringify(savedIntent))
  variant = "actor"
  await recover.click()
  await expect.poll(() => recoveryRequests).toBe(2)
  await expect(
    page.getByText(
      "Could not read the operation. Keep its identity and retry this read.",
      { exact: true },
    ),
  ).toBeVisible()
  expect(await page.getByTestId("operation-confirmed").count()).toBe(0)
  variant = "valid"
  await recover.click()
  await expect(page.getByTestId("operation-confirmed")).toBeVisible()
  expect(recoveryRequests).toBe(3)
})

test("keeps one Project's saved operation when an old Project's read-only response arrives", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  const request = {
    candidate_upload_id: first.id,
    expected_upload_id: null,
    expected_revision_id: null,
    expected_profile_id: first.profile_id,
  }
  const digest = await requestDigest(request)
  const intentA = { key: "saved-project-a-intent", digest, request }
  const intentB = { key: "saved-project-b-intent", digest, request }
  const storageA = `exposure:customer-replacement:${operatorId}:${projects[0].id}`
  const storageB = `exposure:customer-replacement:${operatorId}:${projects[1].id}`
  await page.addInitScript(
    ([firstKey, firstIntent, secondKey, secondIntent]) => {
      sessionStorage.setItem(firstKey, JSON.stringify(firstIntent))
      sessionStorage.setItem(secondKey, JSON.stringify(secondIntent))
    },
    [storageA, intentA, storageB, intentB] as const,
  )
  let aUploadReads = 0
  let bUploadReads = 0
  let releaseA: () => void = () => undefined
  const aGate = new Promise<void>((resolve) => {
    releaseA = resolve
  })
  let recoveryPath = ""
  await page.route("**/api/v1/projects/**", async (route) => {
    const url = new URL(route.request().url())
    const match = url.pathname.match(/projects\/([^/]+)\/customer-uploads$/)
    if (!match || route.request().method() !== "GET") return route.fallback()
    if (match[1] === projects[0].id) {
      aUploadReads += 1
      await aGate
    } else {
      bUploadReads += 1
    }
    return route.fulfill({
      json: {
        data: [first],
        count: 1,
        current_customer_upload_id: null,
        can_upload: false,
        can_select: false,
      },
    })
  })
  await page.route(
    `**/api/v1/projects/${projects[1].id}/customer-ledger/replacements/*`,
    (route) => {
      if (route.request().method() !== "GET") return route.fallback()
      recoveryPath = new URL(route.request().url()).pathname
      return route.fulfill({
        json: {
          ...replacementReceipt({
            candidateId: first.id,
            expectedUploadId: null,
            expectedRevisionId: null,
            expectedProfileId: first.profile_id,
            digest,
          }),
          project_id: projects[1].id,
        },
      })
    },
  )
  await page.route(
    "**/api/v1/projects/**/customer-ledger/replacements",
    (route) => route.fulfill({ status: 500 }),
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await expect.poll(() => aUploadReads).toBeGreaterThanOrEqual(1)
  await page
    .getByRole("combobox", { name: "Project" })
    .selectOption(projects[1].id)
  await expect(
    page.getByText("Selection outcome unknown", { exact: true }),
  ).toBeVisible()
  expect(bUploadReads).toBeGreaterThanOrEqual(1)
  expect(
    await page.evaluate((key) => sessionStorage.getItem(key), storageB),
  ).toBe(JSON.stringify(intentB))
  releaseA()
  await page.waitForTimeout(300)
  expect(
    await page.evaluate((key) => sessionStorage.getItem(key), storageA),
  ).toBe(JSON.stringify(intentA))
  expect(
    await page.evaluate((key) => sessionStorage.getItem(key), storageB),
  ).toBe(JSON.stringify(intentB))
  const recover = page.getByRole("button", { name: "Recover result" })
  await expect(recover).toBeVisible()
  await recover.click()
  await expect(page.getByTestId("operation-confirmed")).toBeVisible()
  expect(recoveryPath.endsWith(intentB.key)).toBe(true)
  expect(recoveryPath.endsWith(intentA.key)).toBe(false)
  expect(
    await page.evaluate((key) => sessionStorage.getItem(key), storageA),
  ).toBe(JSON.stringify(intentA))
})

for (const status of [401, 404]) {
  test(`clears a saved operation when accepted-upload reads are denied with ${status}`, async ({
    page,
  }) => {
    const first = uploads[projects[0].id].data[0]
    const storageKey = `exposure:customer-replacement:${operatorId}:${projects[0].id}`
    const request = {
      candidate_upload_id: first.id,
      expected_upload_id: null,
      expected_revision_id: null,
      expected_profile_id: first.profile_id,
    }
    const savedIntent = {
      key: "saved-denied-intent",
      digest: await requestDigest(request),
      request,
    }
    await page.addInitScript(
      ([key, intent]) => {
        sessionStorage.setItem(key, JSON.stringify(intent))
      },
      [storageKey, savedIntent] as const,
    )
    let uploadPosts = 0
    await page.route(
      `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
      (route) => {
        if (route.request().method() === "POST") {
          uploadPosts += 1
          return route.fulfill({ status: 201, json: first })
        }
        return route.fulfill({
          status,
          json: { detail: { code: "forbidden", message: "Forbidden." } },
        })
      },
    )
    await page.goto(`/?project=${projects[0].id}&view=inputs`)
    await expect(
      page.getByText("Current input could not be read", { exact: true }),
    ).toBeVisible({ timeout: 20_000 })
    expect(uploadPosts).toBe(0)
    await expect(page.getByTestId("operation-state")).toHaveCount(0)
    await expect(
      page.getByRole("button", { name: "Recover result" }),
    ).toHaveCount(0)
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            Object.keys(sessionStorage).filter((key) =>
              key.startsWith("exposure:customer-replacement:"),
            ).length,
        ),
      )
      .toBe(0)
  })
}

type DetailBody = {
  basis: {
    candidate_upload_id: string
    expected_upload_id: string | null
    expected_revision_id: string | null
    expected_profile_id: string
  }
  selector:
    | { kind: "groups"; category: string; skip: number; limit: number }
    | {
        kind: "records"
        category: string
        canonical_ip: string
        side: string
        skip: number
        limit: number
      }
}

function detailEnvelope(body: DetailBody, page: Record<string, unknown>) {
  const { basis, selector } = body
  return {
    actor_id: operatorId,
    project_id: projects[0].id,
    basis: { ...basis },
    selector: { ...selector },
    ...page,
  }
}

async function previewSelectionWithDetails(
  page: Page,
  details: (route: Route, body: DetailBody) => Promise<void> | void,
  impact: Record<string, unknown> = {},
  ledger?: (route: Route) => Promise<void> | void,
) {
  const first = uploads[projects[0].id].data[0]
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) =>
      ledger ? ledger(route) : route.fulfill({ json: ledgerRead(null) }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    (route) =>
      route.fulfill({
        json: {
          candidate_upload_id: first.id,
          current_upload_id: null,
          current_revision_id: null,
          profile_id: first.profile_id,
          current_record_count: 0,
          current_unique_ips: 0,
          candidate_record_count: 3,
          candidate_unique_ips: 2,
          added_ips: 2,
          removed_ips: 0,
          changed_ip_declarations: 0,
          ...impact,
        },
      }),
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/details`,
    (route) => details(route, route.request().postDataJSON() as DetailBody),
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await page.getByRole("button", { name: "Preview selection" }).click()
  await expect(page.getByTestId("replacement-preview")).toBeVisible()
  return first
}

function exactDetailFields() {
  return {
    asset_ip: "10.0.0.1",
    start_port: { kind: "number", numeric_type: "integer", value: "443" },
    end_port: { kind: "number", numeric_type: "integer", value: "8443" },
    is_web: true,
    web_url: null,
    service_type: `long service ${"x".repeat(220)}`,
    asset_department: { kind: "date", value: "2026-01-02" },
    port_owner: "1",
    department: "",
    serial: { kind: "datetime", value: "2026-01-02T03:04:05" },
  }
}

test("binds exact grouped source details to the fixed preview and pages both sides", async ({
  page,
}) => {
  const detailBodies: DetailBody[] = []
  const writes: string[] = []
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      request.url().includes("/api/v1/projects/")
    )
      writes.push(new URL(request.url()).pathname)
  })
  const first = await previewSelectionWithDetails(
    page,
    (route, body) => {
      detailBodies.push(body)
      if (body.selector.kind === "groups") {
        const { skip, limit, category } = body.selector
        const total = 27
        const groups = Array.from(
          { length: Math.max(0, Math.min(limit, total - skip)) },
          (_, offset) => {
            const index = skip + offset
            const canonical_ip =
              index === 1
                ? "2001:db8:85a3::8a2e:370:7334"
                : `10.0.0.${index + 1}`
            return {
              canonical_ip,
              current_records: 0,
              candidate_records: index === 0 ? 12 : 1,
            }
          },
        )
        return route.fulfill({
          json: detailEnvelope(body, {
            kind: "groups",
            category,
            skip,
            limit,
            total_groups: total,
            groups,
          }),
        })
      }
      const { category, canonical_ip, side, skip, limit } = body.selector
      const total =
        side === "current" ? 0 : canonical_ip === "10.0.0.1" ? 12 : 1
      const records =
        side === "current"
          ? []
          : Array.from(
              { length: Math.max(0, Math.min(limit, total - skip)) },
              (_, offset) => ({
                entry_id: `40000000-0000-0000-0000-${String(
                  skip + offset + 1,
                ).padStart(12, "0")}`,
                position: skip + offset + 1,
                canonical_ip,
                fields: exactDetailFields(),
              }),
            )
      return route.fulfill({
        json: detailEnvelope(body, {
          kind: "records",
          category,
          canonical_ip,
          side,
          skip,
          limit,
          total_records: total,
          records,
        }),
      })
    },
    {
      candidate_record_count: 38,
      candidate_unique_ips: 27,
      added_ips: 27,
    },
  )

  const preview = page.getByTestId("replacement-preview")
  await expect(
    preview.getByText(
      "First selection: all 38 candidate records across 27 IPs are reported as added IPs. Removed and changed IPs stay 0; no record is paired across files.",
    ),
  ).toBeVisible()
  const added = preview.getByRole("button", { name: "Added IPs: 27" })
  await added.click()
  await expect(added).toHaveAttribute("aria-expanded", "true")
  await expect(preview.getByText("Added IPs: 27 IP groups")).toBeVisible()
  await expect(preview.getByText("1–25 of 27")).toBeVisible()
  expect(detailBodies[0]).toEqual({
    basis: {
      candidate_upload_id: first.id,
      expected_upload_id: null,
      expected_revision_id: null,
      expected_profile_id: first.profile_id,
    },
    selector: { kind: "groups", category: "added", skip: 0, limit: 25 },
  })

  const groupsPanel = preview.getByRole("region", { name: "Added IPs detail" })
  await groupsPanel.getByRole("button", { name: "Next" }).click()
  await expect(preview.getByText("26–27 of 27")).toBeVisible()
  expect(detailBodies.at(-1)?.selector.skip).toBe(25)
  await groupsPanel.getByRole("button", { name: "Previous" }).click()
  await expect(preview.getByText("1–25 of 27")).toBeVisible()

  const firstGroup = preview
    .locator("li")
    .filter({ has: page.getByText("10.0.0.1", { exact: true }) })
  await firstGroup
    .getByRole("button", { name: "Inspect source records" })
    .click()
  const currentSide = preview.getByRole("region", {
    name: "Current source declarations",
  })
  const candidateSide = preview.getByRole("region", {
    name: "Candidate source declarations",
  })
  await expect(
    currentSide.getByText(
      "No current source declarations for this IP in this preview.",
    ),
  ).toBeVisible()
  await expect(
    preview.getByText(
      "Records from different files cannot be reliably matched. Current and candidate sections list each file's declarations independently; similar positions or the same IP do not imply correspondence.",
    ),
  ).toBeVisible()
  await expect(
    candidateSide.getByText("Source declaration 1", { exact: true }),
  ).toBeVisible()
  await expect(
    candidateSide.getByText("Source declaration 2", { exact: true }),
  ).toBeVisible()
  await expect(
    preview.getByText("Position and record ID are local to this file only."),
  ).toHaveCount(10)
  for (const [label, count] of [
    ["Missing key", 10],
    ["Empty string", 10],
    ["null", 10],
    ["integer", 20],
    ["boolean", 10],
    ["date", 10],
    ["datetime", 10],
    ["text", 30],
  ] as const) {
    await expect(
      candidateSide.getByText(
        label,
        label === "Empty string" ? { exact: false } : { exact: true },
      ),
    ).toHaveCount(count)
  }
  await expect(
    candidateSide.getByText(/long service x{10}/).first(),
  ).toBeVisible()

  const recordBodies = detailBodies.filter(
    (body) => body.selector.kind === "records",
  )
  expect(
    recordBodies.some(
      (body) =>
        body.selector.kind === "records" &&
        body.selector.side === "current" &&
        body.selector.canonical_ip === "10.0.0.1" &&
        body.selector.skip === 0,
    ),
  ).toBe(true)
  expect(
    recordBodies.some(
      (body) =>
        body.selector.kind === "records" &&
        body.selector.side === "candidate" &&
        body.selector.canonical_ip === "10.0.0.1" &&
        body.selector.skip === 0,
    ),
  ).toBe(true)

  await expect(preview.getByText("1–10 of 12")).toBeVisible()
  const candidatePager = preview.getByRole("navigation", {
    name: "Candidate source records pagination",
  })
  await candidatePager.getByRole("button", { name: "Next" }).click()
  await expect(preview.getByText("11–12 of 12")).toBeVisible()
  await expect(candidatePager.getByText("11–12 of 12")).toBeFocused()
  expect(
    detailBodies.some(
      (body) =>
        body.selector.kind === "records" &&
        body.selector.side === "candidate" &&
        body.selector.skip === 10,
    ),
  ).toBe(true)
  await expect(
    candidateSide.getByText("Source declaration 11", { exact: true }),
  ).toBeVisible()
  await expect(
    candidateSide.getByText("Source declaration 12", { exact: true }),
  ).toBeVisible()

  await page.setViewportSize({ width: 320, height: 900 })
  const fits = await preview.evaluate(
    (element) => element.scrollWidth <= element.clientWidth + 1,
  )
  expect(fits).toBe(true)

  await preview.getByRole("button", { name: "Close records" }).click()
  await expect(
    firstGroup.getByRole("button", { name: "Inspect source records" }),
  ).toBeFocused()
  await preview.getByRole("button", { name: "Close details" }).click()
  await expect(added).toBeFocused()
  expect(
    writes.some(
      (path) =>
        path.endsWith("/customer-ledger/replacements") &&
        !path.endsWith("/preview") &&
        !path.endsWith("/details"),
    ),
  ).toBe(false)
})

test("fails closed when detail identity or totals do not match the preview", async ({
  page,
}) => {
  await previewSelectionWithDetails(page, (route, body) => {
    if (body.selector.kind !== "groups") {
      return route.fulfill({ status: 500 })
    }
    return route.fulfill({
      json: detailEnvelope(body, {
        actor_id: "30000000-0000-0000-0000-000000000002",
        kind: "groups",
        category: body.selector.category,
        skip: body.selector.skip,
        limit: body.selector.limit,
        total_groups: 2,
        groups: [],
      }),
    })
  })
  const preview = page.getByTestId("replacement-preview")
  await preview.getByRole("button", { name: "Added IPs: 2" }).click()
  await expect(
    preview.getByRole("heading", {
      name: "Detail did not match the fixed preview",
    }),
  ).toBeVisible()
  await expect(
    preview.getByText(
      "The source detail response failed its identity or total check. No detail is shown and nothing was applied.",
    ),
  ).toBeVisible()
  await expect(preview.getByText("Bounded source detail")).toHaveCount(0)
  await expect(
    preview.getByRole("button", { name: "Set as current input" }),
  ).toBeVisible()
})

test("hides detail on denial and distinguishes a missing group from a receipt", async ({
  page,
}) => {
  let denied = true
  await previewSelectionWithDetails(page, (route, _body) => {
    if (denied) {
      return route.fulfill({
        status: 403,
        json: { detail: { code: "forbidden" } },
      })
    }
    return route.fulfill({
      status: 404,
      json: { detail: { code: "ledger_diff_group_not_found" } },
    })
  })
  const preview = page.getByTestId("replacement-preview")
  await preview.getByRole("button", { name: "Added IPs: 2" }).click()
  await expect(
    preview.getByRole("heading", { name: "Detail access denied" }),
  ).toBeVisible()
  await expect(preview.getByText("10.0.0.1")).toHaveCount(0)
  await expect(preview.getByTestId("operation-state")).toHaveCount(0)

  denied = false
  await preview.getByRole("button", { name: "Close details" }).count()
  await page.getByRole("button", { name: "Cancel", exact: true }).click()
  await expect(preview).toHaveCount(0)
  await page.getByRole("button", { name: "Preview selection" }).click()
  const nextPreview = page.getByTestId("replacement-preview")
  await nextPreview.getByRole("button", { name: "Added IPs: 2" }).click()
  await expect(
    nextPreview.getByRole("heading", {
      name: "Detail no longer matches the preview",
    }),
  ).toBeVisible()
  await expect(
    nextPreview.getByText(
      /close this preview and read the latest version again/i,
    ),
  ).toBeVisible()
  await expect(nextPreview.getByText("Selection outcome unknown")).toHaveCount(
    0,
  )
})

test("invalidates only the matching unsubmitted preview on a detail conflict", async ({
  page,
}) => {
  let previewRequests = 0
  let groupRequests = 0
  const applyPaths: string[] = []
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      request.url().endsWith("/customer-ledger/replacements")
    )
      applyPaths.push(new URL(request.url()).pathname)
  })
  await previewSelectionWithDetails(page, (route, body) => {
    if (body.selector.kind === "groups") {
      groupRequests += 1
      if (groupRequests === 1) {
        return route.fulfill({
          status: 409,
          json: { detail: { code: "ledger_version_conflict" } },
        })
      }
      return route.fulfill({
        json: detailEnvelope(body, {
          kind: "groups",
          category: body.selector.category,
          skip: body.selector.skip,
          limit: body.selector.limit,
          total_groups: 2,
          groups: [
            {
              canonical_ip: "10.0.0.1",
              current_records: 0,
              candidate_records: 2,
            },
            {
              canonical_ip: "10.0.0.2",
              current_records: 0,
              candidate_records: 1,
            },
          ],
        }),
      })
    }
    return route.fulfill({ status: 500 })
  })
  page.on("request", (request) => {
    if (request.url().includes("/customer-ledger/replacements/preview"))
      previewRequests += 1
  })
  const preview = page.getByTestId("replacement-preview")
  await preview.getByRole("button", { name: "Added IPs: 2" }).click()
  await expect(
    page.getByRole("heading", { name: "Current version changed" }),
  ).toBeVisible()
  await expect(preview).toHaveCount(0)
  const again = page.getByRole("button", {
    name: "Read latest version and preview again",
  })
  await expect(again).toBeVisible()
  const previewsBefore = previewRequests
  await again.click()
  await expect(page.getByTestId("replacement-preview")).toBeVisible()
  expect(previewRequests).toBeGreaterThan(previewsBefore)
  const nextPreview = page.getByTestId("replacement-preview")
  await nextPreview.getByRole("button", { name: "Added IPs: 2" }).click()
  const firstGroup = nextPreview
    .locator("li")
    .filter({ has: page.getByText("10.0.0.1", { exact: true }) })
  await expect(
    firstGroup.getByRole("button", { name: "Inspect source records" }),
  ).toBeVisible()
  expect(applyPaths).toEqual([])
})

test("refuses a preview whose current tuple changed while it was open", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  let ledger = ledgerRead(null)
  let ledgerReads = 0
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger?*`,
    (route) => {
      ledgerReads += 1
      return route.fulfill({ json: ledger })
    },
  )
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements/preview`,
    (route) =>
      route.fulfill({
        json: {
          candidate_upload_id: first.id,
          current_upload_id: null,
          current_revision_id: null,
          profile_id: first.profile_id,
          current_record_count: 0,
          current_unique_ips: 0,
          candidate_record_count: 3,
          candidate_unique_ips: 2,
          added_ips: 2,
          removed_ips: 0,
          changed_ip_declarations: 0,
        },
      }),
  )
  await page.goto(`/?project=${projects[0].id}&view=inputs`)
  await page.getByRole("button", { name: "Preview selection" }).click()
  await expect(page.getByTestId("replacement-preview")).toBeVisible()
  await page.waitForLoadState("networkidle")
  const settledReads = ledgerReads
  ledger = ledgerRead("20000000-0000-0000-0000-000000000099")
  await page.bringToFront()
  await page.evaluate(() => {
    window.dispatchEvent(new Event("focus"))
    window.dispatchEvent(new Event("visibilitychange"))
  })
  await expect.poll(() => ledgerReads).toBeGreaterThan(settledReads)
  await expect(
    page.getByRole("heading", { name: "Current version changed" }),
  ).toBeVisible()
  await expect(page.getByTestId("replacement-preview")).toHaveCount(0)
  await expect(
    page.getByRole("button", { name: "Read latest version and preview again" }),
  ).toBeVisible()
})

test("explains a preview with no differences and an empty category", async ({
  page,
}) => {
  await previewSelectionWithDetails(
    page,
    (route, body) => {
      return route.fulfill({
        json: detailEnvelope(body, {
          kind: "groups",
          category: "added",
          skip: 0,
          limit: 25,
          total_groups: 0,
          groups: [],
        }),
      })
    },
    {
      candidate_record_count: 0,
      candidate_unique_ips: 0,
      added_ips: 0,
    },
  )
  const preview = page.getByTestId("replacement-preview")
  await expect(
    preview.getByText(
      "No added, removed or changed IP declarations in this preview.",
    ),
  ).toBeVisible()
  await preview.getByRole("button", { name: "Added IPs: 0" }).click()
  await expect(
    preview.getByText("No added IP groups in this preview."),
  ).toBeVisible()
})

test("maps a detail profile conflict to the explicit profile re-preview", async ({
  page,
}) => {
  const applyPaths: string[] = []
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      request.url().endsWith("/customer-ledger/replacements")
    )
      applyPaths.push(new URL(request.url()).pathname)
  })
  await previewSelectionWithDetails(page, (route) => {
    return route.fulfill({
      status: 409,
      json: { detail: { code: "ledger_profile_changed" } },
    })
  })
  const preview = page.getByTestId("replacement-preview")
  await preview.getByRole("button", { name: "Added IPs: 2" }).click()
  await expect(
    page.getByRole("heading", { name: "Current profile changed" }),
  ).toBeVisible()
  await expect(
    page.getByRole("button", {
      name: "Read latest version and preview again",
    }),
  ).toBeVisible()
  await expect(preview).toHaveCount(0)
  expect(applyPaths).toEqual([])
})

function groupPageFor(body: DetailBody) {
  return {
    kind: "groups",
    category: body.selector.category,
    skip: body.selector.skip,
    limit: body.selector.limit,
    total_groups: 2,
    groups: [
      { canonical_ip: "10.0.0.1", current_records: 0, candidate_records: 2 },
      { canonical_ip: "10.0.0.2", current_records: 0, candidate_records: 1 },
    ],
  }
}

function recordPageFor(
  body: DetailBody,
  totals: { current: number; candidate: number },
) {
  if (body.selector.kind !== "records") throw new Error("records expected")
  const selector = body.selector
  const expectedTotal =
    selector.side === "current" ? totals.current : totals.candidate
  const length = Math.max(
    0,
    Math.min(selector.limit, expectedTotal - selector.skip),
  )
  return {
    kind: "records",
    category: selector.category,
    canonical_ip: selector.canonical_ip,
    side: selector.side,
    skip: selector.skip,
    limit: selector.limit,
    total_records: expectedTotal,
    records: Array.from({ length }, (_, offset) => ({
      entry_id: `43000000-0000-0000-0000-${String(
        selector.skip + offset + 1,
      ).padStart(12, "0")}`,
      position: selector.skip + offset + 1,
      canonical_ip: selector.canonical_ip,
      fields: exactDetailFields(),
    })),
  }
}

test("renders complete tagged detail values including lossless numbers and whitespace", async ({
  page,
}) => {
  const serviceText = "  leading and trailing  "
  const maximumText = `  ${"m".repeat(32767 - 4)}  `
  const fields = {
    asset_ip: "10.0.0.1",
    start_port: {
      kind: "number",
      numeric_type: "integer",
      value: "9007199254740993",
    },
    end_port: {
      kind: "number",
      numeric_type: "integer",
      value: "-9007199254740993",
    },
    is_web: true,
    web_url: null,
    service_type: serviceText,
    asset_department: { kind: "datetime", value: "2026-01-02T03:04:05" },
    port_owner: { kind: "number", numeric_type: "float", value: "1.5" },
    department: "",
    serial: maximumText,
  }
  await previewSelectionWithDetails(
    page,
    (route, body) => {
      if (body.selector.kind === "groups") {
        return route.fulfill({
          json: detailEnvelope(body, {
            kind: "groups",
            category: "added",
            skip: 0,
            limit: 25,
            total_groups: 1,
            groups: [
              {
                canonical_ip: "10.0.0.1",
                current_records: 0,
                candidate_records: 1,
              },
            ],
          }),
        })
      }
      const { side, skip, limit } = body.selector
      if (side === "current") {
        return route.fulfill({
          json: detailEnvelope(body, {
            kind: "records",
            category: "added",
            canonical_ip: "10.0.0.1",
            side,
            skip,
            limit,
            total_records: 0,
            records: [],
          }),
        })
      }
      return route.fulfill({
        json: detailEnvelope(body, {
          kind: "records",
          category: "added",
          canonical_ip: "10.0.0.1",
          side,
          skip,
          limit,
          total_records: 1,
          records: [
            {
              entry_id: "44000000-0000-0000-0000-000000000001",
              position: 1,
              canonical_ip: "10.0.0.1",
              fields,
            },
          ],
        }),
      })
    },
    {
      candidate_record_count: 1,
      candidate_unique_ips: 1,
      added_ips: 1,
    },
  )
  const preview = page.getByTestId("replacement-preview")
  await preview.getByRole("button", { name: "Added IPs: 1" }).click()
  const firstGroup = preview
    .locator("li")
    .filter({ has: page.getByText("10.0.0.1", { exact: true }) })
  await firstGroup
    .getByRole("button", { name: "Inspect source records" })
    .click()
  const side = preview.getByRole("region", {
    name: "Candidate source declarations",
  })
  const field = (label: string) =>
    side
      .locator("dt")
      .filter({ hasText: new RegExp(`^${label}$`) })
      .locator("xpath=following-sibling::dd")
  const exactText = (label: string) =>
    field(label).locator("span > span").first()

  await expect(field("Asset IP")).toContainText("10.0.0.1")
  await expect(field("Start port")).toContainText("9007199254740993")
  await expect(field("Start port")).toContainText("integer")
  await expect(field("End port")).toContainText("-9007199254740993")
  await expect(field("Port owner")).toContainText("1.5")
  await expect(field("Port owner")).toContainText("float")
  await expect(field("Web interface")).toContainText("true")
  await expect(field("Web URL")).toContainText("null")
  await expect(field("Declared owner")).toContainText("Missing key")
  await expect(field("Department")).toContainText('""')
  await expect(field("Asset department")).toContainText("2026-01-02T03:04:05")
  expect(await exactText("Service").textContent()).toBe(serviceText)
  const maximum = await exactText("Source number").textContent()
  expect(maximum).toBe(maximumText)
  expect(maximum?.length).toBe(32767)
})

for (const [name, value] of [
  ["raw JavaScript number", Number("9007199254740993")],
  [
    "leading-zero integer tag",
    { kind: "number", numeric_type: "integer", value: "0900" },
  ],
  [
    "non-finite float tag",
    { kind: "number", numeric_type: "float", value: "nan" },
  ],
] as const) {
  test(`fails closed on a ${name} in detail fields`, async ({ page }) => {
    await previewSelectionWithDetails(page, (route, body) => {
      if (body.selector.kind === "groups") {
        return route.fulfill({
          json: detailEnvelope(body, {
            kind: "groups",
            category: "added",
            skip: 0,
            limit: 25,
            total_groups: 2,
            groups: [
              {
                canonical_ip: "10.0.0.1",
                current_records: 0,
                candidate_records: 2,
              },
              {
                canonical_ip: "10.0.0.2",
                current_records: 0,
                candidate_records: 1,
              },
            ],
          }),
        })
      }
      const { category, canonical_ip, side, skip, limit } = body.selector
      const current = side === "current"
      return route.fulfill({
        json: detailEnvelope(body, {
          kind: "records",
          category,
          canonical_ip,
          side,
          skip,
          limit,
          total_records: current ? 0 : 2,
          records: current
            ? []
            : [
                {
                  entry_id: "45000000-0000-0000-0000-000000000001",
                  position: 1,
                  canonical_ip,
                  fields: { ...exactDetailFields(), serial: value },
                },
                {
                  entry_id: "45000000-0000-0000-0000-000000000002",
                  position: 2,
                  canonical_ip,
                  fields: exactDetailFields(),
                },
              ],
        }),
      })
    })
    const preview = page.getByTestId("replacement-preview")
    await preview.getByRole("button", { name: "Added IPs: 2" }).click()
    const firstGroup = preview
      .locator("li")
      .filter({ has: page.getByText("10.0.0.1", { exact: true }) })
    await firstGroup
      .getByRole("button", { name: "Inspect source records" })
      .click()
    await expect(
      preview.getByRole("heading", {
        name: "Detail did not match the fixed preview",
      }),
    ).toBeVisible()
    await expect(preview.getByText("9007199254740992")).toHaveCount(0)
    await expect(preview.getByText("unsupported value")).toHaveCount(0)
  })
}

const currentBasisDenials = [
  { name: "401", status: 401, body: { detail: { code: "unauthorized" } } },
  { name: "403", status: 403, body: { detail: { code: "forbidden" } } },
  { name: "404", status: 404, body: { detail: { code: "not_found" } } },
  {
    name: "inactive 400",
    status: 400,
    body: { detail: "Inactive user" },
  },
] as const

for (const denial of currentBasisDenials) {
  test(`denies and clears detail when the current-basis read alone returns ${denial.name}`, async ({
    page,
  }) => {
    let deny = false
    let ledgerReads = 0
    let groupsRequests = 0
    const heldRecords: Route[] = []
    await previewSelectionWithDetails(
      page,
      (route, body) => {
        if (body.selector.kind === "groups") {
          groupsRequests += 1
          return route.fulfill({
            json: detailEnvelope(body, {
              kind: "groups",
              category: "added",
              skip: 0,
              limit: 25,
              total_groups: 2,
              groups: [
                {
                  canonical_ip: "10.0.0.1",
                  current_records: 0,
                  candidate_records: 2,
                },
                {
                  canonical_ip: "10.0.0.2",
                  current_records: 0,
                  candidate_records: 1,
                },
              ],
            }),
          })
        }
        heldRecords.push(route)
      },
      {},
      (route) => {
        ledgerReads += 1
        if (deny) {
          return route.fulfill({ status: denial.status, json: denial.body })
        }
        return route.fulfill({ json: ledgerRead(null) })
      },
    )
    const preview = page.getByTestId("replacement-preview")
    await preview.getByRole("button", { name: "Added IPs: 2" }).click()
    const firstGroup = preview
      .locator("li")
      .filter({ has: page.getByText("10.0.0.1", { exact: true }) })
    await firstGroup
      .getByRole("button", { name: "Inspect source records" })
      .click()
    await expect.poll(() => heldRecords.length).toBeGreaterThan(0)
    await expect(preview.getByText("10.0.0.1", { exact: true })).toHaveCount(2)
    const settledReads = ledgerReads
    deny = true
    await page.bringToFront()
    await page.evaluate(() => {
      window.dispatchEvent(new Event("focus"))
      window.dispatchEvent(new Event("visibilitychange"))
    })
    await expect.poll(() => ledgerReads).toBeGreaterThan(settledReads)
    await expect(
      preview.getByRole("heading", { name: "Detail access denied" }),
    ).toBeVisible()
    await expect(preview.getByText("10.0.0.1", { exact: true })).toHaveCount(0)
    await expect(preview.getByTestId("operation-state")).toHaveCount(0)
    await expect(preview.getByTestId("operation-confirmed")).toHaveCount(0)
    for (const route of heldRecords) {
      try {
        await route.fulfill({ status: 500 })
      } catch {
        // The unmounted generation may have aborted its reads.
      }
    }
    const beforeFreshPreview = groupsRequests
    deny = false
    await page.getByRole("button", { name: "Cancel", exact: true }).click()
    await page.getByRole("button", { name: "Preview selection" }).click()
    await expect(page.getByTestId("replacement-preview")).toBeVisible()
    const nextPreview = page.getByTestId("replacement-preview")
    await nextPreview.getByRole("button", { name: "Added IPs: 2" }).click()
    await expect.poll(() => groupsRequests).toBeGreaterThan(beforeFreshPreview)
  })
}

test("unmounts detail while apply preparation owns the flow and ignores a late detail 409", async ({
  page,
}) => {
  const first = uploads[projects[0].id].data[0]
  let applyRequests = 0
  const heldRecords: Route[] = []
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-ledger/replacements`,
    async (route) => {
      applyRequests += 1
      const body = route.request().postDataJSON() as Record<string, unknown>
      return route.fulfill({
        json: replacementReceipt({
          candidateId: first.id,
          expectedUploadId: body.expected_upload_id as string | null,
          expectedRevisionId: body.expected_revision_id as string | null,
          expectedProfileId: body.expected_profile_id as string,
          digest: await requestDigest(body),
        }),
      })
    },
  )
  await previewSelectionWithDetails(page, (route, body) => {
    if (body.selector.kind === "groups") {
      return route.fulfill({
        json: detailEnvelope(body, {
          kind: "groups",
          category: "added",
          skip: 0,
          limit: 25,
          total_groups: 2,
          groups: [
            {
              canonical_ip: "10.0.0.1",
              current_records: 0,
              candidate_records: 2,
            },
            {
              canonical_ip: "10.0.0.2",
              current_records: 0,
              candidate_records: 1,
            },
          ],
        }),
      })
    }
    heldRecords.push(route)
  })
  const preview = page.getByTestId("replacement-preview")
  await preview.getByRole("button", { name: "Added IPs: 2" }).click()
  const firstGroup = preview
    .locator("li")
    .filter({ has: page.getByText("10.0.0.1", { exact: true }) })
  await firstGroup
    .getByRole("button", { name: "Inspect source records" })
    .click()
  await expect.poll(() => heldRecords.length).toBeGreaterThan(0)
  await page.evaluate(() => {
    const original = crypto.subtle.digest.bind(crypto.subtle)
    const target = window as unknown as { __releaseDigest?: () => void }
    target.__releaseDigest = undefined
    let held = false
    crypto.subtle.digest = (async (algorithm, data) => {
      // Hold only the preparation digest; apply re-hashes after it releases.
      if (!held) {
        held = true
        await new Promise<void>((resolve) => {
          target.__releaseDigest = resolve
        })
      }
      return original(algorithm, data)
    }) as typeof crypto.subtle.digest
  })
  const apply = preview.getByRole("button", { name: "Set as current input" })
  await apply.click()
  await expect(apply).toHaveAttribute("aria-busy", "true")
  await expect(preview.getByText("Bounded source detail")).toHaveCount(0)
  for (const route of heldRecords) {
    try {
      await route.fulfill({
        status: 409,
        json: { detail: { code: "ledger_version_conflict" } },
      })
    } catch {
      // The unmounted detail generation may have aborted its reads.
    }
  }
  await expect(
    page.getByRole("heading", { name: "Current version changed" }),
  ).toHaveCount(0)
  await expect(
    page.getByRole("button", { name: "Read latest version and preview again" }),
  ).toHaveCount(0)
  await page.evaluate(() => {
    const target = window as unknown as { __releaseDigest?: () => void }
    target.__releaseDigest?.()
  })
  await expect(page.getByTestId("operation-confirmed")).toBeVisible()
  expect(applyRequests).toBe(1)
})

for (const late of [
  {
    name: "success",
    response: (body: DetailBody) => ({
      json: detailEnvelope(body, {
        kind: "groups",
        category: body.selector.category,
        skip: body.selector.skip,
        limit: body.selector.limit,
        total_groups: 2,
        groups: [
          {
            canonical_ip: "10.0.0.9",
            current_records: 0,
            candidate_records: 2,
          },
          {
            canonical_ip: "10.0.0.10",
            current_records: 0,
            candidate_records: 1,
          },
        ],
      }),
    }),
  },
  {
    name: "conflict",
    response: () => ({
      status: 409,
      json: { detail: { code: "ledger_version_conflict" } },
    }),
  },
] as const) {
  test(`ignores a late detail ${late.name} after cancel and same-tuple re-preview`, async ({
    page,
  }) => {
    let holdFirst = true
    let groupRequests = 0
    const held: Array<{ route: Route; body: DetailBody }> = []
    await previewSelectionWithDetails(page, (route, body) => {
      if (body.selector.kind !== "groups") return route.fulfill({ status: 500 })
      groupRequests += 1
      if (holdFirst) {
        held.push({ route, body })
        return
      }
      return route.fulfill({
        json: detailEnvelope(body, {
          kind: "groups",
          category: "added",
          skip: 0,
          limit: 25,
          total_groups: 2,
          groups: [
            {
              canonical_ip: "10.0.0.7",
              current_records: 0,
              candidate_records: 2,
            },
            {
              canonical_ip: "10.0.0.8",
              current_records: 0,
              candidate_records: 1,
            },
          ],
        }),
      })
    })
    const preview = page.getByTestId("replacement-preview")
    await preview.getByRole("button", { name: "Added IPs: 2" }).click()
    await expect.poll(() => held.length).toBe(1)
    await page.getByRole("button", { name: "Cancel", exact: true }).click()
    await expect(preview).toHaveCount(0)
    holdFirst = false
    await page.getByRole("button", { name: "Preview selection" }).click()
    const nextPreview = page.getByTestId("replacement-preview")
    await expect(nextPreview).toBeVisible()
    await nextPreview.getByRole("button", { name: "Added IPs: 2" }).click()
    await expect(
      nextPreview.getByText("10.0.0.7", { exact: true }),
    ).toBeVisible()
    for (const item of held) {
      try {
        await item.route.fulfill(late.response(item.body))
      } catch {
        // The replaced generation may have aborted its read.
      }
    }
    await expect(
      nextPreview.getByRole("heading", { name: "Current version changed" }),
    ).toHaveCount(0)
    await expect(
      nextPreview.getByRole("button", {
        name: "Read latest version and preview again",
      }),
    ).toHaveCount(0)
    await expect(
      nextPreview.getByText("10.0.0.7", { exact: true }),
    ).toBeVisible()
    await expect(
      nextPreview.getByText("10.0.0.9", { exact: true }),
    ).toHaveCount(0)
    expect(groupRequests).toBe(2)
  })
}

for (const late of [
  {
    name: "success",
    response: (body: DetailBody) => ({
      json: detailEnvelope(body, {
        kind: "groups",
        category: body.selector.category,
        skip: body.selector.skip,
        limit: body.selector.limit,
        total_groups: 2,
        groups: [
          {
            canonical_ip: "10.0.0.9",
            current_records: 0,
            candidate_records: 2,
          },
          {
            canonical_ip: "10.0.0.10",
            current_records: 0,
            candidate_records: 1,
          },
        ],
      }),
    }),
  },
  {
    name: "conflict",
    response: () => ({
      status: 409,
      json: { detail: { code: "ledger_version_conflict" } },
    }),
  },
] as const) {
  test(`ignores a late detail ${late.name} after a project scope switch`, async ({
    page,
  }) => {
    let holdFirst = true
    const held: Array<{ route: Route; body: DetailBody }> = []
    await previewSelectionWithDetails(page, (route, body) => {
      if (body.selector.kind !== "groups") return route.fulfill({ status: 500 })
      if (holdFirst) {
        held.push({ route, body })
        return
      }
      return route.fulfill({
        json: detailEnvelope(body, {
          kind: "groups",
          category: "added",
          skip: 0,
          limit: 25,
          total_groups: 2,
          groups: [
            {
              canonical_ip: "10.0.0.7",
              current_records: 0,
              candidate_records: 2,
            },
            {
              canonical_ip: "10.0.0.8",
              current_records: 0,
              candidate_records: 1,
            },
          ],
        }),
      })
    })
    const preview = page.getByTestId("replacement-preview")
    await preview.getByRole("button", { name: "Added IPs: 2" }).click()
    await expect.poll(() => held.length).toBe(1)
    const projectSelect = page.getByRole("combobox", { name: "Project" })
    await projectSelect.selectOption(projects[1].id)
    await expect(page.getByTestId("replacement-preview")).toHaveCount(0)
    await projectSelect.selectOption(projects[0].id)
    holdFirst = false
    await page.getByRole("button", { name: "Preview selection" }).click()
    const nextPreview = page.getByTestId("replacement-preview")
    await expect(nextPreview).toBeVisible()
    await nextPreview.getByRole("button", { name: "Added IPs: 2" }).click()
    await expect(
      nextPreview.getByText("10.0.0.7", { exact: true }),
    ).toBeVisible()
    for (const item of held) {
      try {
        await item.route.fulfill(late.response(item.body))
      } catch {
        // The replaced project scope may have aborted its read.
      }
    }
    await expect(
      nextPreview.getByRole("heading", { name: "Current version changed" }),
    ).toHaveCount(0)
    await expect(
      nextPreview.getByRole("button", {
        name: "Read latest version and preview again",
      }),
    ).toHaveCount(0)
    await expect(
      nextPreview.getByText("10.0.0.7", { exact: true }),
    ).toBeVisible()
    await expect(
      nextPreview.getByText("10.0.0.9", { exact: true }),
    ).toHaveCount(0)
  })
}

test("pages two independently nonempty detail sides with independent offsets and totals", async ({
  page,
}) => {
  // The fixed current upload is distinct so the candidate stays previewable.
  const currentUploadId = "70000000-0000-0000-0000-000000000001"
  const currentRevisionId = "71000000-0000-0000-0000-000000000001"
  const bodies: DetailBody[] = []
  await previewSelectionWithDetails(
    page,
    (route, body) => {
      bodies.push(body)
      if (body.selector.kind === "groups") {
        return route.fulfill({
          json: detailEnvelope(body, {
            kind: "groups",
            category: "changed",
            skip: 0,
            limit: 25,
            total_groups: 1,
            groups: [
              {
                canonical_ip: "10.0.0.1",
                current_records: 12,
                candidate_records: 12,
              },
            ],
          }),
        })
      }
      const { side, skip, limit } = body.selector
      return route.fulfill({
        json: detailEnvelope(body, {
          kind: "records",
          category: "changed",
          canonical_ip: "10.0.0.1",
          side,
          skip,
          limit,
          total_records: 12,
          records: Array.from(
            { length: Math.max(0, Math.min(limit, 12 - skip)) },
            (_, offset) => ({
              entry_id: `46000000-0000-0000-0000-${String(
                skip + offset + 1,
              ).padStart(12, "0")}`,
              position: skip + offset + 1,
              canonical_ip: "10.0.0.1",
              fields: {
                asset_ip: "10.0.0.1",
                service_type: `${side}-${skip + offset + 1}`,
              },
            }),
          ),
        }),
      })
    },
    {
      current_upload_id: currentUploadId,
      current_revision_id: currentRevisionId,
      current_record_count: 12,
      current_unique_ips: 1,
      candidate_record_count: 12,
      candidate_unique_ips: 1,
      added_ips: 0,
      removed_ips: 0,
      changed_ip_declarations: 1,
    },
    (route) =>
      route.fulfill({ json: ledgerRead(currentUploadId, currentRevisionId) }),
  )
  const preview = page.getByTestId("replacement-preview")
  await preview
    .getByRole("button", { name: "Changed declaration IPs: 1" })
    .click()
  const firstGroup = preview
    .locator("li")
    .filter({ has: page.getByText("10.0.0.1", { exact: true }) })
  await firstGroup
    .getByRole("button", { name: "Inspect source records" })
    .click()
  const currentSide = preview.getByRole("region", {
    name: "Current source declarations",
  })
  const candidateSide = preview.getByRole("region", {
    name: "Candidate source declarations",
  })
  await expect(currentSide.getByText("1–10 of 12")).toBeVisible()
  await expect(candidateSide.getByText("1–10 of 12")).toBeVisible()
  await currentSide.getByRole("button", { name: "Next" }).click()
  await expect(currentSide.getByText("11–12 of 12")).toBeVisible()
  await expect(candidateSide.getByText("1–10 of 12")).toBeVisible()
  await expect(
    currentSide.getByText("current-11", { exact: true }),
  ).toBeVisible()
  await expect(
    candidateSide.getByText("candidate-11", { exact: true }),
  ).toHaveCount(0)
  await candidateSide.getByRole("button", { name: "Next" }).click()
  await expect(candidateSide.getByText("11–12 of 12")).toBeVisible()
  await expect(
    candidateSide.getByText("candidate-11", { exact: true }),
  ).toBeVisible()
  const recordBodies = bodies.filter((body) => body.selector.kind === "records")
  expect(
    recordBodies.some(
      (body) =>
        body.selector.kind === "records" &&
        body.selector.side === "current" &&
        body.selector.skip === 0 &&
        body.selector.limit === 10,
    ),
  ).toBe(true)
  expect(
    recordBodies.some(
      (body) =>
        body.selector.kind === "records" &&
        body.selector.side === "current" &&
        body.selector.skip === 10 &&
        body.selector.limit === 10,
    ),
  ).toBe(true)
  expect(
    recordBodies.some(
      (body) =>
        body.selector.kind === "records" &&
        body.selector.side === "candidate" &&
        body.selector.skip === 0 &&
        body.selector.limit === 10,
    ),
  ).toBe(true)
  expect(
    recordBodies.some(
      (body) =>
        body.selector.kind === "records" &&
        body.selector.side === "candidate" &&
        body.selector.skip === 10 &&
        body.selector.limit === 10,
    ),
  ).toBe(true)
})

const mismatchCases: Array<{
  name: string
  layer: "groups" | "records"
  mutate: (page: Record<string, unknown>) => void
}> = [
  {
    name: "actor",
    layer: "groups",
    mutate: (value) => {
      value.actor_id = "30000000-0000-0000-0000-000000000002"
    },
  },
  {
    name: "project",
    layer: "groups",
    mutate: (value) => {
      value.project_id = projects[1].id
    },
  },
  {
    name: "full basis",
    layer: "groups",
    mutate: (value) => {
      const basis = value.basis as Record<string, unknown>
      basis.expected_revision_id = "90000000-0000-0000-0000-000000000001"
    },
  },
  {
    name: "selector",
    layer: "groups",
    mutate: (value) => {
      const selector = value.selector as Record<string, unknown>
      selector.skip = 1
    },
  },
  {
    name: "side",
    layer: "records",
    mutate: (value) => {
      value.side = "current"
    },
  },
  {
    name: "offset",
    layer: "records",
    mutate: (value) => {
      value.skip = 10
    },
  },
  {
    name: "limit",
    layer: "records",
    mutate: (value) => {
      value.limit = 5
    },
  },
  {
    name: "total",
    layer: "records",
    mutate: (value) => {
      value.total_records = 3
    },
  },
]

function detailResponseFor(
  body: DetailBody,
  mismatch?: (typeof mismatchCases)[number],
): Record<string, unknown> {
  const response = detailEnvelope(
    body,
    body.selector.kind === "groups"
      ? groupPageFor(body)
      : recordPageFor(body, { current: 0, candidate: 2 }),
  )
  const layerMatches =
    mismatch !== undefined &&
    (mismatch.layer === "groups"
      ? body.selector.kind === "groups"
      : body.selector.kind === "records" && body.selector.side === "candidate")
  if (mismatch !== undefined && layerMatches) mismatch.mutate(response)
  return response
}

for (const mismatch of mismatchCases) {
  test(`fails closed when only the ${mismatch.name} mismatch is present`, async ({
    page,
  }) => {
    await previewSelectionWithDetails(page, (route, body) =>
      route.fulfill({ json: detailResponseFor(body, mismatch) }),
    )
    const preview = page.getByTestId("replacement-preview")
    await preview.getByRole("button", { name: "Added IPs: 2" }).click()
    if (mismatch.layer === "records") {
      const firstGroup = preview
        .locator("li")
        .filter({ has: page.getByText("10.0.0.1", { exact: true }) })
      await firstGroup
        .getByRole("button", { name: "Inspect source records" })
        .click()
    }
    await expect(
      preview.getByRole("heading", {
        name: "Detail did not match the fixed preview",
      }),
    ).toBeVisible()
  })
}
