import { expect, type Page, test } from "./fixtures"

const actor = "30000000-0000-4000-8000-000000000001"
const project = {
  id: "10000000-0000-4000-8000-000000000001",
  tenant_id: "00000000-0000-0000-0000-000000000001",
  name: "First comparison",
  created_at: "2026-09-12T00:00:00Z",
  updated_at: "2026-09-12T00:00:00Z",
  archived_at: null,
}
const preview = {
  confirmation_input_hash: "a".repeat(64),
  customer_upload_id: "20000000-0000-4000-8000-000000000001",
  customer_filename: "register.xlsx",
  customer_record_count: 1,
  customer_profile_version: 1,
  customer_accepted_at: project.created_at,
  source_instance_id: "40000000-0000-4000-8000-000000000001",
  source_instance_name: "Synthetic observations",
  source_fingerprint: "b".repeat(64),
  source_validated_at: project.created_at,
  netflow_dataset_id: null,
  netflow_filename: null,
  netflow_record_count: null,
  netflow_accepted_at: null,
}
async function base(
  page: Page,
  options: { empty?: boolean; admin?: boolean } = {},
) {
  const state = {
    projects: options.empty ? ([] as (typeof project)[]) : [project],
    actor,
    admin: options.admin ?? true,
    preview,
    pending: false,
  }
  await page.addInitScript(() => {
    if (!localStorage.getItem("access_token"))
      localStorage.setItem("access_token", "isolated-component-token")
  })
  await page.route("**/api/v1/users/me", (route) =>
    route.fulfill({
      json: {
        id: state.actor,
        is_active: true,
        is_superuser: state.admin,
        email: "isolated@example.test",
        full_name: "Isolated tester",
      },
    }),
  )
  await page.route("**/api/v1/projects/**", async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === "/api/v1/projects/")
      return route.fulfill({
        json: { data: state.projects, count: state.projects.length },
      })
    if (path.endsWith("/governance-reports"))
      return route.fulfill({
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
    if (path.endsWith("/governance-runs"))
      return route.fulfill({
        json: {
          data: [],
          count: 0,
          can_trigger: state.admin && !state.pending,
          can_operate: state.admin,
          ready: true,
          readiness_code: null,
          launch_blocking_code: state.pending ? "run_launch_in_progress" : null,
          input_preview: state.preview,
        },
      })
    if (path.endsWith("/customer-upload-profile"))
      return route.fulfill({
        json: {
          id: "20000000-0000-4000-8000-000000000002",
          version: 1,
          required_headers: ["资产IP"],
          warning_headers: [],
          optional_headers: [],
        },
      })
    if (path.endsWith("/customer-uploads"))
      return route.fulfill({
        json: {
          data: [],
          count: 0,
          current_customer_upload_id: null,
          can_upload: state.admin,
          can_select: state.admin,
        },
      })
    if (path.endsWith("/netflow-datasets"))
      return route.fulfill({
        json: {
          data: [],
          count: 0,
          current_netflow_dataset_id: null,
          current_netflow_dataset: null,
          can_upload: state.admin,
          can_select: state.admin,
        },
      })
    if (path.endsWith("/cloudatlas-source-instances"))
      return route.fulfill({
        json: { data: [], count: 0, can_manage: state.admin },
      })
    return route.fulfill({ status: 404, json: { detail: "Not found" } })
  })
  return state
}

test("zero-project creation survives a lost response and refresh with the same key", async ({
  page,
}) => {
  const state = await base(page, { empty: true })
  const keys: string[] = []
  await page.route("**/api/v1/projects/", async (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    keys.push(route.request().headers()["idempotency-key"])
    state.projects = [project]
    if (keys.length === 1) return route.abort("failed")
    return route.fulfill({ status: 201, json: project })
  })
  await page.goto("/")
  await page
    .getByRole("link", { name: "New comparison project" })
    .last()
    .click()
  await expect(page.getByLabel("Project name", { exact: true })).toBeFocused()
  await page.getByLabel("Project name", { exact: true }).fill(project.name)
  await page.getByRole("button", { name: "Create and prepare inputs" }).click()
  await expect(
    page.getByText("The result is not confirmed.", { exact: false }),
  ).toBeVisible()
  await page.reload()
  expect(keys).toHaveLength(1)
  await page.getByRole("button", { name: "Resume creation" }).click()
  await expect(page).toHaveURL(new RegExp(`project=${project.id}.*view=inputs`))
  await expect(
    page.getByRole("heading", { name: "Prepare this comparison" }),
  ).toBeVisible()
  await expect(
    page.getByRole("heading", { name: "Prepare this comparison" }),
  ).toBeFocused()
  expect(keys).toHaveLength(2)
  expect(keys[0]).toBe(keys[1])
})

test("unavailable recovery storage prevents a creation request", async ({
  page,
}) => {
  await base(page, { empty: true })
  let posts = 0
  await page.route("**/api/v1/projects/", async (route) => {
    if (route.request().method() === "POST") posts++
    return route.fallback()
  })
  await page.addInitScript(() => {
    const original = Storage.prototype.setItem
    Storage.prototype.setItem = function (key, value) {
      if (key.startsWith("exposure:project-create:")) throw new Error("blocked")
      return original.call(this, key, value)
    }
  })
  await page.goto("/?view=create")
  await page.getByLabel("Project name", { exact: true }).fill("Storage check")
  await page.getByRole("button", { name: "Create and prepare inputs" }).click()
  await expect(
    page.getByText("Recovery storage is unavailable or invalid.", {
      exact: false,
    }),
  ).toBeVisible()
  expect(posts).toBe(0)
})

test("202 without a business run retains the request across refresh and account change", async ({
  page,
}) => {
  const state = await base(page)
  const keys: string[] = []
  await page.route(
    `**/api/v1/projects/${project.id}/governance-runs`,
    async (route) => {
      if (route.request().method() !== "POST") return route.fallback()
      keys.push(route.request().headers()["idempotency-key"])
      expect(route.request().postDataJSON()).toEqual({
        confirmation_input_hash: preview.confirmation_input_hash,
      })
      state.pending = true
      return route.fulfill({
        status: 202,
        json: {
          accepted: keys.length === 1,
          agent_compose_run_id: "c".repeat(64),
          agent_compose_status: "PENDING",
          governance_run_id: null,
        },
      })
    },
  )
  await page.goto(`/?project=${project.id}&view=runs`)
  await page.getByLabel("Use these versions for this comparison").check()
  await page.getByRole("button", { name: "Trigger Run", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Resume saved request" }),
  ).toBeVisible()
  await page.reload()
  await expect(
    page.getByRole("button", { name: "Resume saved request" }),
  ).toBeVisible()
  expect(keys).toHaveLength(1)
  await page.getByRole("button", { name: "Resume saved request" }).click()
  await expect.poll(() => keys.length).toBe(2)
  expect(keys[0]).toBe(keys[1])
  state.actor = "30000000-0000-4000-8000-000000000002"
  await page.reload()
  await expect(
    page.getByRole("button", { name: "Resume saved request" }),
  ).toHaveCount(0)
  expect(keys).toHaveLength(2)
  state.actor = actor
  await page.reload()
  await expect(
    page.getByRole("button", { name: "Resume saved request" }),
  ).toBeVisible()
})

test("changed inputs require a new explicit confirmation", async ({ page }) => {
  const state = await base(page)
  await page.route(
    `**/api/v1/projects/${project.id}/governance-runs`,
    async (route) => {
      if (route.request().method() !== "POST") return route.fallback()
      state.preview = {
        ...preview,
        confirmation_input_hash: "d".repeat(64),
        customer_filename: "new-register.xlsx",
      }
      return route.fulfill({
        status: 409,
        json: { detail: { code: "run_inputs_changed" } },
      })
    },
  )
  await page.goto(`/?project=${project.id}&view=runs`)
  await page.getByLabel("Use these versions for this comparison").check()
  await page.getByRole("button", { name: "Trigger Run", exact: true }).click()
  await expect(
    page.getByText(
      "Inputs changed. Review and confirm the current versions again.",
    ),
  ).toBeVisible()
  await expect(
    page.getByLabel("Use these versions for this comparison"),
  ).not.toBeChecked()
  await expect(
    page.getByRole("button", { name: "Trigger Run", exact: true }),
  ).toBeDisabled()
})

test("viewer is read-only and preparation remains usable at 390px", async ({
  page,
}) => {
  await base(page, { admin: false })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto(`/?project=${project.id}&view=inputs`)
  await expect(
    page.getByRole("heading", { name: "Prepare this comparison" }),
  ).toBeVisible()
  await expect(
    page.getByRole("link", { name: "New comparison project" }),
  ).toHaveCount(0)
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true)
  await page.goto(`/?project=${project.id}&view=runs`)
  await expect(
    page.getByRole("button", { name: "Trigger Run", exact: true }),
  ).toHaveCount(0)
  await page.goto("/?view=create")
  await expect(
    page.getByText("Only an administrator can create a project.", {
      exact: false,
    }),
  ).toBeVisible()
})

test("an unavailable CloudAtlas source cannot inherit a stale ready badge", async ({
  page,
}) => {
  await base(page)
  await page.route(
    `**/api/v1/projects/${project.id}/cloudatlas-source-instances`,
    (route) =>
      route.fulfill({
        json: {
          data: [
            {
              id: preview.source_instance_id,
              source_type: "cloudatlas",
              instance_id: "Unavailable source",
              capset_id: "readonly",
              enabled: true,
              validated_fingerprint: "b".repeat(64),
              validation_status: "unavailable",
              created_at: project.created_at,
              updated_at: project.created_at,
            },
          ],
          count: 1,
          can_manage: true,
        },
      }),
  )
  await page.goto(`/?project=${project.id}&view=inputs`)
  await expect(
    page.getByText("Connection unavailable", { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByText("Validated and enabled", { exact: true }),
  ).toHaveCount(0)
})

test("the primary creation action has readable contrast in both themes", async ({
  page,
}) => {
  await base(page, { empty: true })
  for (const theme of ["light", "dark"]) {
    await page.goto("/?view=create")
    await expect(page.getByLabel("Project name", { exact: true })).toBeVisible()
    await page.evaluate(
      (value) => localStorage.setItem("vite-ui-theme", value),
      theme,
    )
    await page.reload()
    const action = page.getByRole("button", {
      name: "Create and prepare inputs",
    })
    await page
      .getByLabel("Project name", { exact: true })
      .fill("Contrast fixture")
    await expect(action).toBeEnabled()
    const ratio = await action.evaluate((element) => {
      const style = getComputedStyle(element)
      const canvas = document.createElement("canvas")
      canvas.width = canvas.height = 1
      const ctx = canvas.getContext("2d")!
      const luminance = (color: string) => {
        ctx.fillStyle = color
        ctx.fillRect(0, 0, 1, 1)
        const rgb = Array.from(ctx.getImageData(0, 0, 1, 1).data)
          .slice(0, 3)
          .map((c) => {
            const s = c / 255
            return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
          })
        return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722
      }
      const a = luminance(style.color),
        b = luminance(style.backgroundColor)
      return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
    })
    expect(ratio, `${theme} creation action contrast`).toBeGreaterThanOrEqual(
      4.5,
    )
  }
})

test("switching accounts in another tab hides the previous creation intent immediately", async ({
  page,
  context,
}) => {
  const state = await base(page)
  await page.addInitScript(
    ({ actor }) =>
      sessionStorage.setItem(
        `exposure:project-create:${actor}`,
        JSON.stringify({
          key: "90000000-0000-4000-8000-000000000001",
          name: "Private pending intent",
        }),
      ),
    { actor },
  )
  await page.goto("/?view=create")
  await expect(page.getByLabel("Project name", { exact: true })).toHaveValue(
    "Private pending intent",
  )
  const other = await context.newPage()
  await other.route("**/*", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<title>Account change fixture</title>",
    }),
  )
  await other.goto(new URL(page.url()).origin)
  state.actor = "30000000-0000-4000-8000-000000000002"
  await other.evaluate(() =>
    localStorage.setItem("access_token", "different-account-token"),
  )
  await expect(
    page.getByRole("heading", { name: "Prepare this comparison" }),
  ).toBeVisible()
  await page.goto("/?view=create")
  await expect(page.getByLabel("Project name", { exact: true })).toHaveValue("")
  await other.close()
})

for (const path of ["/?view=create", `/?project=${project.id}&view=runs`]) {
  test(`permission read failure offers recovery instead of indefinite loading: ${path}`, async ({
    page,
  }) => {
    await base(page)
    let unavailable = true
    await page.route("**/api/v1/users/me", async (route) =>
      unavailable
        ? route.fulfill({
            status: 500,
            json: { detail: "Synthetic user read failure" },
          })
        : route.fallback(),
    )
    await page.goto(path)
    await expect(
      page.getByText("Permissions could not be read.", { exact: false }),
    ).toBeVisible({ timeout: 15000 })
    unavailable = false
    await page.getByRole("button", { name: "Retry permission check" }).click()
    if (path.includes("view=create"))
      await expect(
        page.getByLabel("Project name", { exact: true }),
      ).toBeVisible()
    else
      await expect(
        page.getByLabel("Use these versions for this comparison"),
      ).toBeVisible()
  })
}

test("an inactive-account rejection retains the original creation key", async ({
  page,
}) => {
  await base(page, { empty: true })
  await page.route("**/api/v1/projects/", async (route) =>
    route.request().method() === "POST"
      ? route.fulfill({ status: 400, json: { detail: "Inactive user" } })
      : route.fallback(),
  )
  await page.goto("/?view=create")
  await page
    .getByLabel("Project name", { exact: true })
    .fill("Retained creation")
  await page.getByRole("button", { name: "Create and prepare inputs" }).click()
  await expect(
    page.getByText("Permission is no longer available.", { exact: false }),
  ).toBeVisible()
  const saved = await page.evaluate(
    (actor) =>
      JSON.parse(sessionStorage.getItem(`exposure:project-create:${actor}`)!),
    actor,
  )
  expect(saved.name).toBe("Retained creation")
  expect(saved.key).toMatch(/^[0-9a-f-]{36}$/)
  await expect(
    page.getByRole("button", { name: "Resume creation" }),
  ).toBeDisabled()
})
