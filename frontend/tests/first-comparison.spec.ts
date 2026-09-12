import { fileURLToPath } from "node:url"
import type { FileChooser, Locator } from "@playwright/test"
import { cloudatlasCapsetToken, testApiUrl } from "./config"
import { expect, type Page, test } from "./fixtures"

test.skip(
  process.env.RUN_GOVERNANCE_E2E !== "1",
  "requires the isolated PostgreSQL, OctoBus and agent-compose fixture stack",
)
test.use({ actionTimeout: 15_000 })

const workbook = fileURLToPath(
  new URL("./fixtures/first-comparison.xlsx", import.meta.url),
)
const badWorkbook = fileURLToPath(
  new URL("./fixtures/first-comparison-missing-header.xlsx", import.meta.url),
)
const header = "IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n"

async function activate(target: Locator) {
  await expect(target).toBeEnabled()
  await target.focus()
  await expect(target).toBeFocused()
  await target.press("Enter")
}

async function uploadByKeyboard(
  page: Page,
  label: string,
  files: Parameters<FileChooser["setFiles"]>[0],
) {
  const form = page
    .locator("form")
    .filter({ has: page.getByLabel(label, { exact: true }) })
  const picker = page.waitForEvent("filechooser")
  await activate(form.getByRole("button", { name: "Choose file", exact: true }))
  await (await picker).setFiles(files)
  await page.keyboard.press("Tab")
  await expect(
    form.getByRole("button", { name: "Upload", exact: true }),
  ).toBeFocused()
  await page.keyboard.press("Enter")
}

test("administrator completes the first comparison through the UI with present, absent and empty NetFlow", async ({
  page,
  request,
}, info) => {
  test.setTimeout(480_000)
  const fixture = await request.post(
    "http://cloudatlas-fixture:18080/fixture/set-assets",
    { data: { items: [{ id: 46, ip: "192.0.2.46", status: "valid" }] } },
  )
  expect(fixture.ok()).toBe(true)
  for (const mode of ["present", "absent", "empty"] as const) {
    await page.setViewportSize({ width: 1366, height: 768 })
    await page.goto("/")
    await activate(
      page.getByRole("link", { name: "New comparison project" }).last(),
    )
    const name = `First comparison ${mode} ${crypto.randomUUID()}`
    await expect(page.getByLabel("Project name", { exact: true })).toBeFocused()
    await page.keyboard.type(name)
    if (mode === "present")
      await page.screenshot({
        path: info.outputPath("create-project.png"),
        fullPage: true,
      })
    await page.keyboard.press("Tab")
    await expect(
      page.getByRole("button", { name: "Create and prepare inputs" }),
    ).toBeFocused()
    await page.keyboard.press("Enter")
    await expect(page).toHaveURL(/view=inputs/)
    const projectId = new URL(page.url()).searchParams.get("project")!
    await expect(page.getByRole("heading", { name })).toBeVisible()
    await expect(
      page.getByRole("heading", { name: "Prepare this comparison" }),
    ).toBeFocused()
    if (mode === "present") {
      const rejection = page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          new URL(response.url()).pathname.endsWith("/customer-uploads"),
      )
      await uploadByKeyboard(page, "XLSX file", badWorkbook)
      const rejected = await rejection
      expect(rejected.status()).toBe(422)
      expect((await rejected.json()).detail.code).toBe(
        "missing_required_structure",
      )
      await expect(page.getByText("No accepted uploads yet.")).toBeVisible()
    }
    await uploadByKeyboard(page, "XLSX file", workbook)
    const row = page
      .getByRole("row")
      .filter({ hasText: "first-comparison.xlsx" })
    await activate(row.getByRole("button", { name: "Set as current input" }))
    await expect(
      page.getByRole("heading", { name: "Current Project input", exact: true }),
    ).toBeFocused()
    if (mode !== "absent") {
      await uploadByKeyboard(page, "NetFlow dataset file", {
        name: `${mode}.csv`,
        mimeType: "text/csv",
        buffer: Buffer.from(
          header +
            (mode === "present" ? "192.0.2.20,192.0.2.46,6,443,80\n" : ""),
        ),
      })
      await activate(
        page.getByRole("button", {
          name: `Select ${mode}.csv as current NetFlowDataset`,
          exact: true,
        }),
      )
      await expect(
        page.getByRole("heading", { name: "NetFlowDatasets", exact: true }),
      ).toBeFocused()
    }
    await activate(page.getByRole("link", { name: "CloudAtlas", exact: true }))
    await page.getByLabel("OctoBus Instance ID").fill("cloudatlas-fixture")
    await page.getByLabel("Read-only Capset ID").fill("cloudatlas-readonly")
    await activate(
      page.getByRole("button", { name: "Save binding", exact: true }),
    )
    await page
      .getByLabel("Capset token", { exact: true })
      .fill(cloudatlasCapsetToken)
    await activate(
      page.getByRole("button", { name: "Validate source", exact: true }),
    )
    await activate(
      page.getByRole("button", { name: "Enable source", exact: true }),
    )
    await activate(page.getByRole("link", { name: "Inputs", exact: true }))
    await expect(
      page.getByText("Validated and enabled", { exact: true }),
    ).toBeVisible()
    if (mode === "present") {
      await page
        .getByRole("combobox", { name: "Language / 语言" })
        .selectOption("zh-CN")
      await expect(
        page.getByRole("heading", { name: "准备本轮比对" }),
      ).toBeVisible()
      expect(new URL(page.url()).searchParams.get("project")).toBe(projectId)
      await page
        .getByRole("combobox", { name: "Language / 语言" })
        .selectOption("en")
      await activate(page.getByTestId("theme-button"))
      await expect(page.getByTestId("light-mode")).toBeFocused()
      await page.keyboard.press("Enter")
      await expect(page.locator("html")).toHaveClass(/light/)
      await expect(page.getByTestId("theme-button")).toBeFocused()
      await activate(page.getByTestId("theme-button"))
      await page.keyboard.press("ArrowDown")
      await expect(page.getByTestId("dark-mode")).toBeFocused()
      await page.keyboard.press("Enter")
      await expect(page.locator("html")).toHaveClass(/dark/)
      await page.emulateMedia({ reducedMotion: "reduce" })
      expect(
        await page
          .getByRole("link", { name: "Review inputs and start" })
          .evaluate((element) =>
            parseFloat(getComputedStyle(element).transitionDuration),
          ),
      ).toBeLessThanOrEqual(0.001)
      for (const width of [1366, 1920, 390]) {
        await page.setViewportSize({
          width,
          height: width === 390 ? 844 : width === 1366 ? 768 : 1080,
        })
        expect(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= window.innerWidth,
          ),
        ).toBe(true)
        await page.screenshot({
          path: info.outputPath(`preparation-${width}.png`),
          fullPage: true,
        })
      }
      await page.setViewportSize({ width: 1366, height: 768 })
    }
    await activate(page.getByRole("link", { name: "Review inputs and start" }))
    await expect(
      page.getByRole("heading", { name: "Confirm these input versions" }),
    ).toBeFocused()
    await expect(
      page.getByRole("button", { name: "Trigger Run", exact: true }),
    ).toBeDisabled()
    await page.getByLabel("Use these versions for this comparison").focus()
    await page.keyboard.press("Space")
    await expect(
      page.getByLabel("Use these versions for this comparison"),
    ).toBeChecked()
    await page.keyboard.press("Tab")
    await expect(
      page.getByRole("button", { name: "Trigger Run", exact: true }),
    ).toBeFocused()
    if (process.env.EXPECT_BACKEND_MODEL_UNCONFIGURED === "1") {
      const token = await page.evaluate(() =>
        localStorage.getItem("access_token"),
      )
      const status = await request.get(
        `${testApiUrl}/api/v1/model-qualification/status`,
        { headers: { Authorization: `Bearer ${token}` } },
      )
      expect(status.status()).toBe(200)
      expect(await status.json()).toEqual({ qualified: false })
    }
    await page.keyboard.press("Enter")
    await expect(page).toHaveURL(/view=overview/, { timeout: 120_000 })
    const runId = new URL(page.url()).searchParams.get("run")!
    expect(runId).toBeTruthy()
    await expect(
      page.getByRole("heading", { name: "Published overview" }),
    ).toBeVisible()
    await expect(
      page.getByRole("heading", { name: "Published overview" }),
    ).toBeFocused()
    const token = await page.evaluate(() =>
      localStorage.getItem("access_token"),
    )
    const runs = await request.get(
      `${testApiUrl}/api/v1/projects/${projectId}/governance-runs`,
      { headers: { Authorization: `Bearer ${token}` } },
    )
    expect(runs.ok()).toBe(true)
    const persisted = (await runs.json()).data
    expect(persisted).toHaveLength(1)
    expect(persisted[0].id).toBe(runId)
    expect(persisted[0].published).toBe(true)
    if (mode === "absent")
      await expect(page.getByText("Three-source summary: N/A")).toBeVisible()
    else {
      const comparisons = await request.get(
        `${testApiUrl}/api/v1/projects/${projectId}/governance-runs/${runId}/ip-source-comparisons`,
        { headers: { Authorization: `Bearer ${token}` } },
      )
      expect(comparisons.ok()).toBe(true)
      const data = await comparisons.json()
      expect(data.count).toBe(2)
      expect(
        data.data
          .map((item: { classification: string }) => item.classification)
          .sort(),
      ).toEqual(["cloudatlas_only", "customer_upload_only"])
      expect(
        data.data.every(
          (item: { netflow_status: string }) =>
            item.netflow_status === (mode === "present" ? "ACTIVE" : "UNKNOWN"),
        ),
      ).toBe(true)
    }
    await page.reload()
    await expect(page).toHaveURL(new RegExp(`run=${runId}`))
    for (const width of [1366, 1920, 390]) {
      await page.setViewportSize({
        width,
        height: width === 390 ? 844 : width === 1366 ? 768 : 1080,
      })
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBe(true)
      await page.screenshot({
        path: info.outputPath(`overview-${mode}-${width}.png`),
        fullPage: true,
      })
    }
  }
})
