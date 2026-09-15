import { fileURLToPath } from "node:url"
import { cloudatlasCapsetToken, testApiUrl } from "./config"
import { expect, test } from "./fixtures"

test.use({ actionTimeout: 15000 })

const workbook = fileURLToPath(
  new URL("./fixtures/customer-ledger.xlsx", import.meta.url),
)

test("customer ledger preserves input history through correction and real new Runs", async ({
  page,
  request,
}, info) => {
  test.setTimeout(480000)
  await page.goto("/")
  const token = await page.evaluate(() => localStorage.getItem("access_token"))
  const headers = { Authorization: `Bearer ${token}` }
  const projectResponse = await request.post(`${testApiUrl}/api/v1/projects/`, {
    headers,
    data: { name: `Ledger ${crypto.randomUUID()}` },
  })
  expect(projectResponse.status()).toBe(201)
  const project = await projectResponse.json()
  const root = `${testApiUrl}/api/v1/projects/${project.id}`
  await page.goto(`/?project=${project.id}&view=inputs`)
  await page.getByLabel("XLSX file", { exact: true }).setInputFiles(workbook)
  await page
    .locator("form")
    .filter({ has: page.getByLabel("XLSX file", { exact: true }) })
    .getByRole("button", { name: "Upload", exact: true })
    .click()
  const row = page.getByRole("row").filter({ hasText: "customer-ledger.xlsx" })
  await row.getByRole("button", { name: "Set as current input" }).click()
  await page.getByRole("link", { name: "Customer ledger", exact: true }).click()
  await expect(
    page.getByRole("heading", { name: "Customer asset ledger" }),
  ).toBeVisible()
  await expect(
    page.getByText("61 matching source records", { exact: true }),
  ).toBeVisible()
  const first = await request.get(`${root}/customer-ledger`, { headers })
  expect(first.ok()).toBe(true)
  const u1 = await first.json()
  expect(u1.revision_id).toBeNull()
  let r1: string | undefined
  let report1: unknown
  let canonical1: unknown
  let csv1: string | undefined
  async function runThroughUi() {
    await page.goto(`/?project=${project.id}&view=runs`)
    await page.getByLabel("Use these versions for this comparison").check()
    await page.getByRole("button", { name: "Trigger Run", exact: true }).click()
    await expect(page).toHaveURL(/view=overview/, { timeout: 120000 })
    return new URL(page.url()).searchParams.get("run")!
  }
  if (process.env.RUN_GOVERNANCE_E2E === "1") {
    expect(
      (
        await request.post(
          "http://cloudatlas-fixture:18080/fixture/set-assets",
          {
            data: {
              items: [
                { id: 1, ip: "2001:db8:10::25", status: "valid" },
                ...Array.from({ length: 60 }, (_, i) => ({
                  id: i + 2,
                  ip: `2001:db8:10::${(0x100 + i).toString(16)}`,
                  status: "valid",
                })),
              ],
            },
          },
        )
      ).ok(),
    ).toBe(true)
    await page.goto(`/?project=${project.id}&view=cloudatlas`)
    await page.getByLabel("OctoBus Instance ID").fill("cloudatlas-fixture")
    await page.getByLabel("Read-only Capset ID").fill("cloudatlas-readonly")
    await page
      .getByRole("button", { name: "Save binding", exact: true })
      .click()
    await page
      .getByLabel("Capset token", { exact: true })
      .fill(cloudatlasCapsetToken)
    await page
      .getByRole("button", { name: "Validate source", exact: true })
      .click()
    await page
      .getByRole("button", { name: "Enable source", exact: true })
      .click()
    r1 = await runThroughUi()
    const rr = await request.get(`${root}/governance-reports`, { headers })
    expect(rr.ok()).toBe(true)
    report1 = await rr.json()
    const id = (report1 as { data: { id: string }[] }).data[0].id
    const details = await request.get(`${root}/governance-reports/${id}`, {
      headers,
    })
    expect(details.ok()).toBe(true)
    canonical1 = (await details.json()).canonical_content
    const csv = await request.get(`${root}/governance-reports/${id}/csv`, {
      headers,
    })
    expect(csv.ok()).toBe(true)
    csv1 = (await csv.body()).toString("base64")
    await page.goto(`/projects/${project.id}/customer-ledger`)
    await expect(
      page.getByRole("heading", { name: "Customer asset ledger" }),
    ).toBeVisible()
  }
  await page
    .getByRole("navigation", { name: "Ledger pagination" })
    .getByRole("button", { name: "Next", exact: true })
    .click()
  await expect(page).toHaveURL(/ledger_page=2/)
  await page.reload()
  await expect(
    page
      .getByRole("navigation", { name: "Ledger pagination" })
      .getByText("Page 2 of 3"),
  ).toBeVisible()
  await page
    .getByRole("navigation", { name: "Ledger pagination" })
    .getByRole("button", { name: "Previous", exact: true })
    .click()
  await page
    .getByRole("row")
    .filter({ hasText: "2001:db8:10::20" })
    .getByRole("button", { name: "Correct", exact: true })
    .click()
  await page.getByLabel("Asset IP", { exact: true }).fill("2001:db8:10::25")
  await page
    .getByLabel("Reason for this change")
    .fill("Correct the declared IPv6 address")
  await page
    .getByRole("button", { name: "Save new revision", exact: true })
    .click()
  await expect(
    page.getByText("Saved a new revision. Existing Run reports are unchanged."),
  ).toBeVisible()
  const currentResponse = await request.get(`${root}/customer-ledger`, {
    headers,
  })
  const u2 = await currentResponse.json()
  expect(u2.upload_id).not.toBe(u1.upload_id)
  expect(u2.data[0].canonical_ip).toBe("2001:db8:10::25")
  expect(u2.data[0].entry_id).toBe(u1.data[0].entry_id)
  await page.reload()
  await expect(
    page.getByRole("heading", { name: "Customer asset ledger" }),
  ).toBeVisible()
  await page
    .getByRole("row")
    .filter({ hasText: "2001:db8:10::25" })
    .getByRole("button", { name: "Manage", exact: true })
    .click()
  await page.getByLabel("Confirmed owner").fill("Confirmed operator")
  await page.getByLabel("Tags (comma separated)").fill("follow-up")
  await page
    .getByLabel("Reason for this change")
    .fill("Confirm ownership locally")
  await page
    .getByRole("button", { name: "Save new revision", exact: true })
    .click()
  await expect(
    page.getByText("Confirmed operator", { exact: true }),
  ).toBeVisible()
  const u3 = await (
    await request.get(`${root}/customer-ledger`, { headers })
  ).json()
  expect(u3.upload_id).toBe(u2.upload_id)
  expect(u3.data[0].fields.asset_owner).toBe("Declared owner")
  await page
    .getByRole("button", { name: "2001:db8:10::25", exact: true })
    .click()
  await expect(
    page.getByText("Customer IP dossier: 2001:db8:10::25", { exact: true }),
  ).toBeVisible()
  await page.emulateMedia({ reducedMotion: "reduce" })
  for (const lang of ["en", "zh-CN"]) {
    await page
      .getByRole("combobox", { name: "Language / 语言" })
      .selectOption(lang)
    for (const width of [1366, 1920, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1080 })
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBe(true)
      await page.screenshot({
        path: info.outputPath(`ledger-${lang}-${width}.png`),
        fullPage: true,
      })
    }
  }
  await page.setViewportSize({ width: 1366, height: 768 })
  await page
    .getByRole("combobox", { name: "Language / 语言" })
    .selectOption("en")
  await page.goto(
    `/projects/${project.id}/customer-ledger?ledger_upload=${u1.upload_id}`,
  )
  await expect(
    page.getByRole("row").filter({ hasText: "2001:db8:10::20" }),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Correct", exact: true }),
  ).toHaveCount(0)
  expect(
    (
      await (
        await request.get(`${root}/customer-ledger?upload_id=${u1.upload_id}`, {
          headers,
        })
      ).json()
    ).upload_sha256,
  ).toBe(u1.upload_sha256)
  if (r1) {
    const r2 = await runThroughUi()
    expect(r2).not.toBe(r1)
    const runResponse = await request.get(`${root}/governance-runs`, {
      headers,
    })
    expect(runResponse.ok()).toBe(true)
    const runs = (await runResponse.json()).data
    expect(
      runs.find((run: { id: string }) => run.id === r1).customer_upload_id,
    ).toBe(u1.upload_id)
    expect(
      runs.find((run: { id: string }) => run.id === r2).customer_upload_id,
    ).toBe(u2.upload_id)
    const after = await (
      await request.get(`${root}/governance-reports`, { headers })
    ).json()
    const original = (report1 as { data: { id: string }[] }).data[0]
    expect(
      after.data.find((item: { id: string }) => item.id === original.id),
    ).toEqual(original)
    const oldDetails = await request.get(
      `${root}/governance-reports/${original.id}`,
      { headers },
    )
    expect(oldDetails.ok()).toBe(true)
    expect((await oldDetails.json()).canonical_content).toEqual(canonical1)
    const oldCsv = await request.get(
      `${root}/governance-reports/${original.id}/csv`,
      { headers },
    )
    expect(oldCsv.ok()).toBe(true)
    expect((await oldCsv.body()).toString("base64")).toBe(csv1)
    await info.attach("lineage", {
      body: JSON.stringify({
        project: project.id,
        r1,
        r2,
        u1: u1.upload_id,
        u2: u2.upload_id,
        oldReport: original,
      }),
      contentType: "application/json",
    })
  }
})

test("unknown ledger requests recover after reload using the same intent without storing customer fields", async ({
  page,
  request,
}) => {
  await page.goto("/")
  const token = await page.evaluate(() => localStorage.getItem("access_token"))
  const headers = { Authorization: `Bearer ${token}` }
  const project = await (
    await request.post(`${testApiUrl}/api/v1/projects/`, {
      headers,
      data: { name: `Recovery ${crypto.randomUUID()}` },
    })
  ).json()
  const root = `${testApiUrl}/api/v1/projects/${project.id}`
  const { readFileSync } = await import("node:fs")
  const upload = await (
    await request.post(`${root}/customer-uploads`, {
      headers,
      multipart: {
        file: {
          name: "customer-ledger.xlsx",
          mimeType:
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          buffer: readFileSync(workbook),
        },
      },
    })
  ).json()
  expect(
    (
      await request.post(`${root}/customer-uploads/${upload.id}/select`, {
        headers,
      })
    ).ok(),
  ).toBe(true)
  await page.goto(`/projects/${project.id}/customer-ledger`)
  await expect(page).toHaveURL(/ledger_upload=/)
  await page
    .getByRole("row")
    .filter({ hasText: "2001:db8:10::20" })
    .getByRole("button", { name: "Correct", exact: true })
    .click()
  await page.getByLabel("Asset IP", { exact: true }).fill("2001:db8:10::25")
  const reason = "Keep this private correction out of session storage"
  await page.getByLabel("Reason for this change").fill(reason)
  let originalKey = ""
  await page.route("**/customer-ledger/revisions", async (route) => {
    if (route.request().method() !== "POST") return route.continue()
    originalKey = route.request().headers()["idempotency-key"]
    return route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({ detail: { code: "ledger_save_failed" } }),
    })
  })
  await page
    .getByRole("button", { name: "Save new revision", exact: true })
    .click()
  await expect(
    page.getByRole("button", { name: "Query original request" }),
  ).toBeVisible()
  const stored = await page.evaluate(() =>
    Object.keys(sessionStorage)
      .filter((key) => key.startsWith("exposure:ledger:"))
      .map((key) => sessionStorage.getItem(key))
      .join(""),
  )
  expect(stored).not.toContain(reason)
  expect(stored).not.toContain("2001:db8:10::25")
  expect(stored).not.toContain("Declared owner")
  await page.unroute("**/customer-ledger/revisions")
  await page.reload()
  await page.getByRole("button", { name: "Query original request" }).click()
  await expect(
    page.getByText(
      "No saved result was found for this request. No new request was sent.",
    ),
  ).toBeVisible()
  await page.getByRole("button", { name: "Re-enter original request" }).click()
  await page.getByLabel("Asset IP", { exact: true }).fill("2001:db8:10::99")
  await page.getByLabel("Reason for this change").fill(reason)
  const calls: string[] = []
  page.on("request", (req) => {
    if (
      req.method() === "POST" &&
      req.url().endsWith("/customer-ledger/revisions")
    )
      calls.push(req.headers()["idempotency-key"])
  })
  await page.getByRole("button", { name: "Confirm original request" }).click()
  await expect(
    page.getByText(
      "Re-enter exactly the original change and reason before restoring this request.",
    ),
  ).toBeVisible()
  expect(calls).toHaveLength(0)
  await page.getByLabel("Asset IP", { exact: true }).fill("2001:db8:10::25")
  await page.getByRole("button", { name: "Confirm original request" }).click()
  await expect(
    page.getByText("Saved a new revision. Existing Run reports are unchanged."),
  ).toBeVisible()
  expect(calls).toEqual([originalKey])
  expect(
    await (
      await request.get(`${root}/customer-ledger/revisions`, { headers })
    ).json(),
  ).toHaveLength(1)
})

test("fresh current reads and browser history isolate version details and delayed saves", async ({
  page,
  request,
}) => {
  await page.goto("/")
  const token = await page.evaluate(() => localStorage.getItem("access_token"))
  const headers = { Authorization: `Bearer ${token}` }
  const project = await (
    await request.post(`${testApiUrl}/api/v1/projects/`, {
      headers,
      data: { name: `Scopes ${crypto.randomUUID()}` },
    })
  ).json()
  const root = `${testApiUrl}/api/v1/projects/${project.id}`
  const { readFileSync } = await import("node:fs")
  const uploaded = await request.post(`${root}/customer-uploads`, {
    headers,
    multipart: {
      file: {
        name: "customer-ledger.xlsx",
        mimeType:
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        buffer: readFileSync(workbook),
      },
    },
  })
  const u1 = await uploaded.json()
  expect(
    (
      await request.post(`${root}/customer-uploads/${u1.id}/select`, {
        headers,
      })
    ).ok(),
  ).toBe(true)
  await page.goto(`/projects/${project.id}/customer-ledger`)
  await expect(page).toHaveURL(new RegExp(u1.id))
  const base = await (
    await request.get(`${root}/customer-ledger`, { headers })
  ).json()
  const posted = await request.post(`${root}/customer-ledger/revisions`, {
    headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
    data: {
      expected_upload_id: base.upload_id,
      expected_revision_id: null,
      expected_profile_id: base.current_profile_id,
      entry_id: base.data[0].entry_id,
      operation: "update",
      fields: { asset_ip: "2001:db8:10::25" },
      reason: "External correction",
    },
  })
  expect(posted.status()).toBe(201)
  const u2 = await posted.json()
  await page
    .getByRole("button", { name: "Read current version", exact: true })
    .click()
  await expect(page).toHaveURL(new RegExp(u2.id))
  await page
    .getByRole("row")
    .filter({ hasText: "2001:db8:10::25" })
    .getByRole("button", { name: "Details", exact: true })
    .click()
  await expect(
    page.getByRole("heading", { name: "2001:db8:10::25 · Source record 1" }),
  ).toBeVisible()
  await page.goBack()
  await expect(page).toHaveURL(new RegExp(u1.id))
  await expect(
    page.getByRole("heading", { name: "2001:db8:10::25 · Source record 1" }),
  ).toHaveCount(0)
  await page
    .getByRole("button", { name: "Read current version", exact: true })
    .click()
  await expect(page).toHaveURL(new RegExp(u2.id))
  await page
    .getByRole("row")
    .filter({ hasText: "2001:db8:10::25" })
    .getByRole("button", { name: "Manage", exact: true })
    .click()
  await page.getByLabel("Confirmed owner").fill("late owner")
  await page.getByLabel("Reason for this change").fill("Delayed ownership")
  let release: () => void = () => {}
  let arrived: () => void = () => {}
  const pending = new Promise<void>((resolve) => {
    release = resolve
  })
  const reached = new Promise<void>((resolve) => {
    arrived = resolve
  })
  await page.route("**/customer-ledger/revisions", async (route) => {
    if (route.request().method() !== "POST") return route.continue()
    const response = await route.fetch()
    arrived()
    await pending
    await route.fulfill({ response })
  })
  await page
    .getByRole("button", { name: "Save new revision", exact: true })
    .click()
  await reached
  await page.goBack()
  await expect(page).toHaveURL(new RegExp(u1.id))
  await expect(page.getByLabel("Confirmed owner")).toHaveCount(0)
  const delivered = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/customer-ledger/revisions"),
  )
  release()
  await delivered
  await expect(page).toHaveURL(new RegExp(u1.id))
  await expect(page.getByText("late owner", { exact: true })).toHaveCount(0)
  await expect(
    page.getByRole("button", { name: "Query original request" }),
  ).toHaveCount(0)
  await page.getByRole("button", { name: "Return to original version" }).click()
  await expect(page).toHaveURL(new RegExp(u2.id))
  await page.getByRole("button", { name: "Query original request" }).click()
  await expect(
    page.getByText("Saved a new revision. Existing Run reports are unchanged."),
  ).toBeVisible()
  await expect(page.getByText("late owner", { exact: true })).toBeVisible()
})
