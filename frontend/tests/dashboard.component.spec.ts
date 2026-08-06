import { expect, type Page, type Route, test } from "@playwright/test"

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
        fingerprint_summary: null,
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

async function mockDashboardApi(page: Page) {
  await page.addInitScript(() =>
    localStorage.setItem("access_token", "component-token"),
  )
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

test("selects the first Project and switches its Profile and upload list", async ({
  page,
}) => {
  await page.goto("/")

  const projectSelect = page.getByRole("combobox", { name: "Project" })
  await expect(projectSelect).toContainText("North Plant")
  await expect(
    page.getByText(profiles[projects[0].id].id).first(),
  ).toBeVisible()
  await expect(page.getByText("north-assets.xlsx")).toBeVisible()

  await projectSelect.click()
  await page.getByRole("option", { name: "Archive Lab" }).click()

  await expect(projectSelect).toContainText("Archive Lab")
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
  await page.goto("/")

  await page.getByRole("combobox", { name: "Project" }).click()
  await expect(
    page.getByRole("option", { name: "Paged Project 101" }),
  ).toBeVisible()
})

test("shows loading, empty, and failure states for Projects", async ({
  page,
}) => {
  await page.route("**/api/v1/projects/?*", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 500))
    await route.fulfill({ json: { data: projects, count: projects.length } })
  })
  await page.goto("/")
  await expect(page.getByRole("status")).toHaveText("Loading Projects…")

  await page.route("**/api/v1/projects/?*", (route) =>
    route.fulfill({ json: { data: [], count: 0 } }),
  )
  await page.reload()
  await expect(
    page.getByText("No accessible Projects are available."),
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
  await page.goto("/")

  await expect(page.getByText("Project input is not ready.")).toBeVisible()
  await page.getByRole("button", { name: "设为当前输入" }).click()

  await expect(page.getByText("Current CustomerUpload ID")).toBeVisible()
  await expect(page.getByText(uploads[projects[0].id].data[0].id)).toBeVisible()
  await expect(page.getByText("Current", { exact: true })).toBeVisible()
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
  await page.goto("/")

  await expect(
    page.getByText(
      "You have read-only access to CustomerUpload inputs for this Project.",
    ),
  ).toBeVisible()
  await expect(page.getByLabel("XLSX file")).not.toBeVisible()
  await expect(
    page.getByRole("button", { name: "设为当前输入" }),
  ).not.toBeVisible()

  const projectSelect = page.getByRole("combobox", { name: "Project" })
  await projectSelect.click()
  await page.getByRole("option", { name: "Archive Lab (Archived)" }).click()
  await expect(
    page.getByText("Archived Project", { exact: true }),
  ).toBeVisible()
  await expect(page.getByText("Existing inputs remain visible")).toBeVisible()
  await expect(page.getByLabel("XLSX file")).not.toBeVisible()
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
    await page.goto("/")

    const fileInput = page.getByLabel("XLSX file")
    await fileInput.setInputFiles({
      name: "new-assets.xlsx",
      mimeType:
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      buffer: Buffer.from("mock workbook"),
    })
    await page.getByRole("button", { name: "Upload" }).click()

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
  let source = { ...cloudatlasSources[projects[0].id].data[0] }
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
        fingerprint_summary: "abcdef012345",
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
        fingerprint_summary: null,
      }
    }
    await route.fulfill({ json: source })
  }
  const sourceUrl = `**/api/v1/projects/${projects[0].id}/cloudatlas-source-instances`
  await page.route(sourceUrl, handleSourceRequest)
  await page.route(`${sourceUrl}/**`, handleSourceRequest)
  await page.goto("/")

  await expect(page.getByText("CloudAtlas source")).toBeVisible()
  const tokenInput = page.getByLabel("Capset token")
  await expect(tokenInput).toHaveAttribute("type", "password")
  await tokenInput.fill("transient-test-token")
  await page.getByRole("button", { name: "Validate source" }).click()
  await expect(page.getByText("Validated", { exact: true })).toBeVisible()
  await expect(tokenInput).toHaveValue("")

  await page.getByRole("button", { name: "Enable source" }).click()
  await expect(page.getByText("Enabled", { exact: true })).toBeVisible()
  await page.getByLabel("OctoBus Instance ID").fill("cloudatlas-replacement")
  await page.getByRole("button", { name: "Save binding" }).click()
  await expect(page.getByText("cloudatlas-replacement")).toBeVisible()

  source = {
    ...source,
    enabled: true,
    validation_status: "validated",
    fingerprint_summary: "abcdef012345",
  }
  await page.reload()
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
    fingerprint_summary: "123456789abc",
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
  await page.goto("/")

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
  await page.goto("/")
  await page.getByLabel("XLSX file").setInputFiles({
    name: "invalid.xlsx",
    mimeType:
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: Buffer.from("invalid workbook"),
  })
  await page.getByRole("button", { name: "Upload" }).click()

  await expect(
    page.getByText("The workbook contains an invalid required value."),
  ).toBeVisible()
  await expect(page.getByText("sensitive-cell-value")).not.toBeVisible()
})

test("shows the three Run steps and triggers with a caller-owned stable ID", async ({
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
    steps: ["LOAD_CUSTOMER", "PULL_CLOUDATLAS", "PUBLISH"].map((step_code) => ({
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
          readiness_code: null,
        },
      })
    },
  )
  await page.goto("/")

  await expect(page.getByText("Inputs ready")).toBeVisible()
  for (const step of ["LOAD_CUSTOMER", "PULL_CLOUDATLAS", "PUBLISH"]) {
    await expect(page.getByRole("cell", { name: step })).toBeVisible()
  }
  await expect(page.getByText("CUSTOMER_UPLOAD")).toBeVisible()
  await expect(page.getByText("CLOUDATLAS", { exact: true })).toBeVisible()

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
  await page.route(
    `**/api/v1/projects/${projects[0].id}/governance-runs/${runId}/**`,
    async (route) => {
      actions.push(
        new URL(route.request().url()).pathname.split("/").at(-1) ?? "",
      )
      await route.fulfill({
        status: 202,
        json: {
          accepted: true,
          action: actions.at(-1),
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
          readiness_code: null,
        },
      }),
  )
  await page.goto("/")

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
  await page.getByRole("button", { name: "Rerun with current inputs" }).click()
  await expect(
    page.getByText("Rerun accepted with current inputs and a new Trigger ID."),
  ).toBeVisible()
  expect(actions).toEqual(["retry", "rerun"])
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
          readiness_code: null,
        },
      }),
  )
  await page.goto("/")

  await expect(page.getByText("RUNNING", { exact: true })).toBeVisible()
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
            readiness_code: null,
          },
        }),
    )
    await page.goto("/")

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
