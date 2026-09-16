import { expect, type Page, test } from "./fixtures"

const project = "00000000-0000-0000-0000-000000000001"
const dataset = "10000000-0000-0000-0000-000000000001"
const user = {
  id: "20000000-0000-0000-0000-000000000001",
  email: "admin@example.com",
  full_name: "Admin",
  is_active: true,
  is_superuser: true,
}
const page = (canManage = true) => ({
  project_id: project,
  dataset_id: dataset,
  dataset_sha256: "a".repeat(64),
  raw_sha256: "b".repeat(64),
  contract_version: "netflow-dataset-v1",
  state: "PRESENT",
  revision: 0,
  current_revision: 0,
  count: 1,
  total_endpoints: 1,
  raw_records: 1,
  valid_records: 1,
  isolated_records: 0,
  can_manage: canManage,
  can_confirm_scope: true,
  data: [
    {
      canonical_ip: "2001:db8:10::25",
      family: 6,
      candidate_id: "30000000-0000-0000-0000-000000000001",
      namespace: "legacy",
      roles: ["src"],
      flow_count: 1,
      protocols: [6],
      source_record_keys: ["row:1"],
      candidate_state: "CANDIDATE",
      management_revision: 0,
      followed: false,
      excluded: false,
    },
  ],
})

async function mock(pageObject: Page, onPost?: (body: unknown) => void) {
  await pageObject.addInitScript(() =>
    localStorage.setItem("access_token", "component-token"),
  )
  await pageObject.route("**/api/v1/users/me", (route: any) =>
    route.fulfill({ json: user }),
  )
  await pageObject.route(
    `**/api/v1/projects/${project}/netflow-datasets`,
    (route: any) =>
      route.fulfill({
        json: {
          data: [{ id: dataset, display_filename: "D1.csv" }],
          count: 1,
          current_netflow_dataset_id: dataset,
          current_netflow_dataset: null,
          can_upload: true,
          can_select: true,
        },
      }),
  )
  await pageObject.route(
    `**/api/v1/projects/${project}/netflow-ledger?*`,
    (route: any) => route.fulfill({ json: page() }),
  )
  await pageObject.route(
    `**/api/v1/projects/${project}/netflow-ledger/profile?*`,
    (route: any) =>
      route.fulfill({
        json: {
          canonical_ip: "2001:db8:10::25",
          netflow: page(),
          customer: null,
          cloud: null,
          association: "NO_ASSOCIATION",
          risk_state: "NOT_CONNECTED",
          processing_state: "NO_RESOURCE_HISTORY",
        },
      }),
  )
  await pageObject.route(
    `**/api/v1/projects/${project}/netflow-ledger/revisions`,
    async (route: any) => {
      onPost?.(route.request().postDataJSON())
      await route.fulfill({
        status: 201,
        json: {
          id: "40000000-0000-0000-0000-000000000001",
          dataset_id: dataset,
          revision: 1,
        },
      })
    },
  )
}

test("scope and management send explicit values; profile reads fixed sources", async ({
  page: browser,
}) => {
  const bodies: any[] = []
  await mock(browser, (body) => bodies.push(body))
  await browser.goto(`/projects/${project}/netflow-ledger?dataset=${dataset}`)
  await browser.getByRole("button", { name: "Confirm scope" }).click()
  await browser.getByLabel("Namespace", { exact: true }).fill("lab")
  await browser.getByLabel("CIDRs").fill("2001:db8:10::/64")
  await browser.getByLabel("Viewpoint").selectOption("INTERNAL")
  await browser.getByLabel("Scope status").selectOption("REVOKED")
  await browser.getByLabel("Reason / evidence").fill("withdrawn")
  await browser.getByRole("button", { name: "Save revision" }).click()
  expect(bodies[0]).toMatchObject({
    kind: "scope",
    viewpoint: "INTERNAL",
    scope_status: "REVOKED",
  })
  await browser.getByRole("button", { name: "Manage" }).click()
  await browser.getByLabel("Follow this endpoint").check()
  await browser.getByLabel("Exclude from candidates").check()
  await browser.getByLabel("Reason / evidence").fill("local choice")
  await browser.getByRole("button", { name: "Save revision" }).click()
  expect(bodies[1]).toMatchObject({
    kind: "management",
    followed: true,
    excluded: true,
  })
  await browser.getByRole("button", { name: "IP profile" }).click()
  await expect(browser.getByText("Customer source: Not provided")).toBeVisible()
  await expect(
    browser.getByText("CloudAtlas source: Not provided"),
  ).toBeVisible()
})

test("unknown save never creates a second intent and survives reload", async ({
  page: browser,
}) => {
  let posts = 0
  await mock(browser)
  await browser.route(
    `**/api/v1/projects/${project}/netflow-ledger/revisions`,
    (route) => {
      posts++
      return route.abort("failed")
    },
  )
  await browser.route(
    `**/api/v1/projects/${project}/netflow-ledger/operations/*`,
    (route) =>
      route.fulfill({ status: 404, json: { detail: { code: "unavailable" } } }),
  )
  await browser.goto(
    `/projects/${project}/netflow-ledger?dataset=${dataset}&revision=0`,
  )
  await browser.getByRole("button", { name: "Manage", exact: true }).click()
  await browser.getByLabel("Follow this endpoint").check()
  await browser.getByLabel("Reason / evidence").fill("test unknown result")
  await browser.getByRole("button", { name: "Save revision" }).click()
  await expect(
    browser.getByRole("button", { name: "Save revision" }),
  ).toBeDisabled()
  await expect(
    browser.getByRole("button", { name: "Check original operation" }),
  ).toBeVisible()
  await browser.reload()
  await browser
    .getByRole("button", { name: "Check original operation" })
    .click()
  await expect(
    browser.getByText("The original operation is still unavailable."),
  ).toBeVisible()
  await browser.getByRole("button", { name: "Manage", exact: true }).click()
  await expect(
    browser.getByRole("button", { name: "Save revision" }),
  ).toBeDisabled()
  expect(posts).toBe(1)
})

test("switching Dataset discards profile bindings and ignores a late write", async ({
  page: browser,
}) => {
  const other = "10000000-0000-0000-0000-000000000002"
  let release!: () => void
  const held = new Promise<void>((r) => {
    release = r
  })
  let started = false
  await mock(browser)
  await browser.route(
    `**/api/v1/projects/${project}/netflow-datasets`,
    (route) =>
      route.fulfill({
        json: {
          data: [
            { id: dataset, display_filename: "D1.csv" },
            { id: other, display_filename: "D2.csv" },
          ],
          count: 2,
        },
      }),
  )
  await browser.route(
    `**/api/v1/projects/${project}/netflow-ledger?*`,
    (route) =>
      route.fulfill({
        json: {
          ...page(),
          dataset_id:
            new URL(route.request().url()).searchParams.get("dataset_id") ??
            dataset,
        },
      }),
  )
  await browser.route(
    `**/api/v1/projects/${project}/netflow-ledger/revisions`,
    async (route) => {
      started = true
      await held
      await route.fulfill({
        status: 201,
        json: {
          id: "40000000-0000-0000-0000-000000000001",
          dataset_id: dataset,
          revision: 1,
        },
      })
    },
  )
  await browser.goto(
    `/projects/${project}/netflow-ledger?dataset=${dataset}&revision=0&profile_ip=2001:db8:10::25&customer_upload=old-customer&cloud_snapshot=old-cloud`,
  )
  await browser.getByRole("button", { name: "Manage", exact: true }).click()
  await browser.getByLabel("Reason / evidence").fill("held response")
  await browser.getByRole("button", { name: "Save revision" }).click()
  await expect.poll(() => started).toBe(true)
  await browser.getByLabel("Dataset", { exact: true }).selectOption(other)
  await expect(
    browser.getByRole("heading", { name: "Manage endpoint" }),
  ).toHaveCount(0)
  await expect(
    browser.getByRole("heading", { name: "Fixed IP profile" }),
  ).toHaveCount(0)
  release()
  await expect(browser).toHaveURL(new RegExp(`dataset=${other}`))
  const query = new URL(browser.url()).searchParams
  expect(query.has("profile_ip")).toBe(false)
  expect(query.has("customer_upload")).toBe(false)
  expect(query.has("cloud_snapshot")).toBe(false)
  await expect(
    browser.getByRole("button", { name: "Check original operation" }),
  ).toHaveCount(0)
})
