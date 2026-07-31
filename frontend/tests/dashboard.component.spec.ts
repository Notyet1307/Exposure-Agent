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
