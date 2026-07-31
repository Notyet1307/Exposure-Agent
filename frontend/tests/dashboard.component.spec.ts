import { expect, type Page, test } from "@playwright/test"

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
    can_upload: true,
  },
  [projects[1].id]: {
    data: [],
    count: 0,
    can_upload: false,
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

test("keeps read-only and Archived Projects visible without upload controls", async ({
  page,
}) => {
  await page.route(
    `**/api/v1/projects/${projects[0].id}/customer-uploads*`,
    (route) =>
      route.fulfill({
        json: { ...uploads[projects[0].id], can_upload: false },
      }),
  )
  await page.goto("/")

  await expect(
    page.getByText(
      "You have read-only access to CustomerUpload inputs for this Project.",
    ),
  ).toBeVisible()
  await expect(page.getByLabel("XLSX file")).not.toBeVisible()

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
            ? { data: [acceptedUpload], count: 1, can_upload: true }
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
