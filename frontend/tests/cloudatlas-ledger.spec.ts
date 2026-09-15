import { fileURLToPath } from "node:url"
import { cloudatlasCapsetToken, testApiUrl } from "./config"
import { expect, test } from "./fixtures"

test.use({ actionTimeout: 15000 })

const workbook = fileURLToPath(
  new URL("./fixtures/customer-ledger.xlsx", import.meta.url),
)

test("native CloudAtlas ledger preserves source history, recovers an unknown save and gates historical association", async ({
  page,
  request,
}, info) => {
  test.setTimeout(480000)
  test.skip(
    process.env.RUN_GOVERNANCE_E2E !== "1",
    "Requires isolated real Runner stack",
  )
  await page.goto("/")
  const token = await page.evaluate(() => localStorage.getItem("access_token"))
  const headers = { Authorization: `Bearer ${token}` }
  const created = await request.post(`${testApiUrl}/api/v1/projects/`, {
    headers,
    data: { name: `Cloud ledger ${crypto.randomUUID()}` },
  })
  expect(created.status()).toBe(201)
  const project = await created.json()
  const root = `${testApiUrl}/api/v1/projects/${project.id}`
  const uploaded = await request.post(`${root}/customer-uploads`, {
    headers,
    multipart: {
      file: {
        name: "customer-ledger.xlsx",
        mimeType:
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        buffer: await (await import("node:fs/promises")).readFile(workbook),
      },
    },
  })
  expect(uploaded.status()).toBe(201)
  const upload = await uploaded.json()
  expect(
    (
      await request.post(`${root}/customer-uploads/${upload.id}/select`, {
        headers,
      })
    ).status(),
  ).toBe(200)
  const sourceResponse = await request.post(
    `${root}/cloudatlas-source-instances`,
    {
      headers,
      data: {
        instance_id: "cloudatlas-fixture",
        capset_id: "cloudatlas-readonly",
      },
    },
  )
  // Use the fixture instance ids already deployed by the repository harness.
  expect(sourceResponse.status()).toBe(201)
  const source = await sourceResponse.json()
  expect(
    (
      await request.post(
        `${root}/cloudatlas-source-instances/${source.id}/validate`,
        { headers, data: { capset_token: cloudatlasCapsetToken } },
      )
    ).status(),
  ).toBe(200)
  expect(
    (
      await request.post(
        `${root}/cloudatlas-source-instances/${source.id}/enable`,
        { headers },
      )
    ).status(),
  ).toBe(200)
  await page.goto(`/?project=${project.id}&view=runs`)
  await page.getByLabel("Use these versions for this comparison").check()
  await page.getByRole("button", { name: "Trigger Run", exact: true }).click()
  await expect(page).toHaveURL(/view=overview/, { timeout: 180000 })
  const runId = new URL(page.url()).searchParams.get("run")!
  const reports = await (
    await request.get(`${root}/governance-reports`, { headers })
  ).json()
  const reportId = reports.data[0].id
  const oldReport = await (
    await request.get(`${root}/governance-reports/${reportId}`, { headers })
  ).json()
  const csv = await (
    await request.get(`${root}/governance-reports/${reportId}/csv`, { headers })
  ).body()
  let readSidePosts = 0
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      /governance-runs|ai-investigations|analysis-reports|cloudatlas-source-instances/.test(
        r.url(),
      )
    )
      readSidePosts++
  })
  await page
    .getByRole("link", { name: "CloudAtlas ledger", exact: true })
    .click()
  await expect(
    page.getByRole("heading", { name: "CloudAtlas native ledger" }),
  ).toBeVisible()
  await expect(page).toHaveURL(/cloud_snapshot=/)
  const first = await (
    await request.get(`${root}/cloudatlas-ledger`, { headers })
  ).json()
  expect(first.governance_run_id).toBe(runId)
  expect(first.total_records).toBeGreaterThan(0)
  await page
    .getByRole("button", { name: "IP profile", exact: true })
    .first()
    .click()
  await expect(
    page.getByText(
      "No authorized historical resource association. Handling records are not attached.",
    ),
  ).toBeVisible()
  await page.getByRole("button", { name: "Close profile" }).click()
  await page.getByLabel("Exact IP or ID").fill("2001:db8:10::20")
  await page
    .getByRole("button", { name: "Query IP profile", exact: true })
    .click()
  await expect(
    page.getByText("Not observed in this complete valid snapshot."),
  ).toBeVisible()
  await page
    .getByRole("link", { name: "Open this customer version", exact: true })
    .click()
  await expect(page).toHaveURL(new RegExp(`ledger_upload=${upload.id}`))
  await page
    .getByRole("button", { name: "2001:db8:10::20", exact: true })
    .first()
    .click()
  await page
    .getByRole("link", { name: "View with CloudAtlas source", exact: true })
    .click()
  await expect(page).toHaveURL(new RegExp(`customer_upload=${upload.id}`))
  await expect(
    page.getByText("Not observed in this complete valid snapshot."),
  ).toBeVisible()
  await page.getByRole("button", { name: "Close profile" }).click()
  await page
    .getByRole("button", { name: "Manage", exact: true })
    .first()
    .click()
  await page.getByLabel("Tags (comma separated)").fill("x".repeat(65))
  await page
    .getByLabel("Reason / evidence")
    .fill("Rejected input can be corrected")
  const rejectedSave = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      r.url().endsWith("/cloudatlas-ledger/revisions"),
    { timeout: 15000 },
  )
  await page
    .getByRole("button", { name: "Save new revision", exact: true })
    .click()
  expect((await rejectedSave).status()).toBe(422)
  await expect(
    page.getByText("Input rejected. Correct the fields and save again."),
  ).toBeVisible()
  await expect(
    page.getByRole("heading", { name: "Unconfirmed local operation" }),
  ).toHaveCount(0)
  await page.getByLabel("Tags (comma separated)").fill("follow-up")
  await page.getByLabel("Follow this source record").check()
  await page
    .getByLabel("Reason / evidence")
    .fill("Synthetic management acceptance")
  // The backend commits; the browser sees an unknown response and recovers the same operation.
  let intercepted = false
  await page.route(
    `**/api/v1/projects/${project.id}/cloudatlas-ledger/revisions`,
    async (route) => {
      if (route.request().method() !== "POST" || intercepted)
        return route.continue()
      intercepted = true
      const response = await route.fetch()
      expect(response.status()).toBe(201)
      await route.abort("failed")
    },
  )
  await page
    .getByRole("button", { name: "Save new revision", exact: true })
    .click()
  await expect(
    page.getByRole("heading", { name: "Unconfirmed local operation" }),
  ).toBeVisible()
  await page.reload()
  await page.getByRole("button", { name: "Check original operation" }).click()
  await expect(page).toHaveURL(/cloud_revision=1/)
  await expect(
    page.getByRole("heading", { name: "Unconfirmed local operation" }),
  ).toHaveCount(0)
  await page.unroute(
    `**/api/v1/projects/${project.id}/cloudatlas-ledger/revisions`,
  )
  await page
    .getByRole("button", { name: "Confirm network relationship", exact: true })
    .click()
  await page
    .getByLabel("Relationship to legacy Project space")
    .selectOption("CONFIRMED_LEGACY")
  await page
    .getByLabel("Reason / evidence")
    .fill("Synthetic fixture address space only")
  await page
    .getByRole("button", { name: "Save new revision", exact: true })
    .click()
  await expect(page).toHaveURL(/cloud_revision=2/)
  await page
    .getByRole("button", { name: "IP profile", exact: true })
    .first()
    .click()
  const historyLink = page.getByRole("link", {
    name: "View fixed Run evidence and handling records",
  })
  await expect(historyLink).toHaveAttribute(
    "href",
    new RegExp(`/runs/${runId}/lineage`),
  )
  const historyResponse = page.waitForResponse(
    (r) =>
      r.request().method() === "GET" &&
      r.url().includes(`/governance-runs/${runId}/lineage`),
    { timeout: 15000 },
  )
  await historyLink.click()
  expect((await historyResponse).status()).toBe(200)
  await expect(page).toHaveURL(new RegExp(`/runs/${runId}/lineage`))
  await expect(
    page.getByRole("heading", { name: "Asset review", exact: true }),
  ).toBeVisible()
  await page.goBack()
  await expect(
    page.getByRole("heading", { name: "CloudAtlas native ledger" }),
  ).toBeVisible()
  expect(readSidePosts).toBe(0)
  await page.getByTestId("theme-button").click()
  await page.getByTestId("light-mode").click()
  await expect(page.locator("html")).toHaveClass(/light/)
  for (const width of [390, 1366, 1920]) {
    await page.setViewportSize({
      width,
      height: width === 1366 ? 768 : width === 1920 ? 1080 : 844,
    })
    if (width === 390) {
      const region = page.getByRole("region", {
        name: "CloudAtlas source records",
        exact: true,
      })
      await region.focus()
      await expect(region).toBeFocused()
      await region.press("ArrowRight")
      await expect
        .poll(() => region.evaluate((el) => el.scrollLeft))
        .toBeGreaterThan(0)
    }
    await expect(
      page.getByRole("heading", { name: "CloudAtlas native ledger" }),
    ).toBeVisible()
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true)
    await page.screenshot({
      path: info.outputPath(`cloud-ledger-${width}.png`),
      fullPage: true,
    })
  }
  await page.getByTestId("theme-button").click()
  await page.getByTestId("dark-mode").click()
  await expect(page.locator("html")).toHaveClass(/dark/)
  await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "dark" })
  await page.evaluate(() => localStorage.setItem("exposure:language", "zh-CN"))
  await page.reload()
  await expect(
    page.getByRole("heading", { name: "云图原生资产账" }),
  ).toBeVisible()
  await page.evaluate(() => localStorage.setItem("exposure:language", "en"))
  await page.reload()
  const fixedURL = page.url()
  await page.reload()
  await expect(page).toHaveURL(fixedURL)
  const old = await (
    await request.get(
      `${root}/cloudatlas-ledger?snapshot_id=${first.snapshot_id}&revision=0`,
      { headers },
    )
  ).json()
  expect(old.data).toEqual(first.data)
  expect(
    (
      await (
        await request.get(`${root}/governance-reports/${reportId}`, { headers })
      ).json()
    ).canonical_content,
  ).toEqual(oldReport.canonical_content)
  expect(
    await (
      await request.get(`${root}/governance-reports/${reportId}/csv`, {
        headers,
      })
    ).body(),
  ).toEqual(csv)
})
