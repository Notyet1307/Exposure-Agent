import { mkdir } from "node:fs/promises"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { expect, test } from "./fixtures"

const api = process.env.TEST_API_URL!
const workbook = (name: string) =>
  fileURLToPath(new URL(`./fixtures/${name}`, import.meta.url))

test("customer replacement uses the real preview, preserves old versions and recovers lost replies", async ({
  page,
  request,
}) => {
  const login = await request.post(`${api}/api/v1/login/access-token`, {
    form: {
      username: process.env.FIRST_SUPERUSER!,
      password: process.env.FIRST_SUPERUSER_PASSWORD!,
    },
  })
  expect(login.ok()).toBeTruthy()
  const token = (await login.json()).access_token as string
  const headers = { Authorization: `Bearer ${token}` }
  const created = await request.post(`${api}/api/v1/projects/`, {
    headers,
    data: { name: `Product replacement ${crypto.randomUUID()}` },
  })
  expect(created.status()).toBe(201)
  const project = await created.json()
  const root = `${api}/api/v1/projects/${project.id}`
  await page.addInitScript(
    (value) => localStorage.setItem("access_token", value),
    token,
  )
  await page.goto(`/?project=${project.id}&view=inputs`)
  await expect(
    page.getByRole("heading", { name: "Data access", exact: true }),
  ).toBeVisible()
  const upload = async (name: string) => {
    await page
      .getByLabel("XLSX file", { exact: true })
      .setInputFiles(workbook(name))
    await page
      .locator("form")
      .filter({ has: page.getByLabel("XLSX file", { exact: true }) })
      .getByRole("button", { name: "Upload", exact: true })
      .click()
    const row = page.getByRole("row").filter({ hasText: name })
    await expect(row).toBeVisible()
    return row
  }
  const first = await upload("customer-upload-v1.xlsx")
  let inputs = await (
    await request.get(`${root}/customer-uploads`, { headers })
  ).json()
  expect(inputs.current_customer_upload_id).toBeNull()
  const firstId = inputs.data[0].id as string
  await first.getByRole("button", { name: "Preview replacement" }).click()
  await expect(
    page.getByText("Replacement preview", { exact: true }),
  ).toBeVisible()
  expect(
    (await (await request.get(`${root}/customer-uploads`, { headers })).json())
      .current_customer_upload_id,
  ).toBeNull()
  await page
    .getByRole("button", { name: "Apply replacement", exact: true })
    .click()
  await expect(first.getByText("Current", { exact: true })).toBeVisible()
  await expect(
    page.getByText("Replacement confirmed.", { exact: false }),
  ).toBeVisible()

  const second = await upload("customer-upload-stage4-second.xlsx")
  inputs = await (
    await request.get(`${root}/customer-uploads`, { headers })
  ).json()
  const secondId = inputs.data.find(
    (row: { display_filename: string }) =>
      row.display_filename === "customer-upload-stage4-second.xlsx",
  ).id as string
  expect(inputs.current_customer_upload_id).toBe(firstId)
  await second.getByRole("button", { name: "Preview replacement" }).click()
  await expect(
    page.getByText("Replacement preview", { exact: true }),
  ).toBeVisible()
  expect(
    (await (await request.get(`${root}/customer-uploads`, { headers })).json())
      .current_customer_upload_id,
  ).toBe(firstId)
  let applies = 0
  const applyPath = `/api/v1/projects/${project.id}/customer-ledger/replacements`
  await page.route(
    (url) => url.pathname === applyPath,
    async (route) => {
      applies += 1
      const response = await route.fetch()
      expect(response.status()).toBe(201)
      await route.abort("connectionfailed")
    },
  )
  await page
    .getByRole("button", { name: "Apply replacement", exact: true })
    .click()
  await expect(
    page.getByText("Replacement outcome unknown", { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Preview replacement" }),
  ).toHaveCount(0)
  expect(applies).toBe(1)
  expect(
    (await (await request.get(`${root}/customer-uploads`, { headers })).json())
      .current_customer_upload_id,
  ).toBe(secondId)
  await page.reload()
  await page
    .getByRole("button", { name: "Recover result", exact: true })
    .click()
  await expect(
    page.getByText("Replacement confirmed.", { exact: false }),
  ).toBeVisible()
  await expect(
    page.getByText("Replacement outcome unknown", { exact: true }),
  ).toHaveCount(0)
  expect(applies).toBe(1)
  const historical = await request.get(
    `${root}/customer-ledger?upload_id=${firstId}&original=true`,
    { headers },
  )
  expect(historical.ok()).toBeTruthy()
  expect((await historical.json()).upload_id).toBe(firstId)
  expect(
    (await (await request.get(`${root}/customer-uploads`, { headers })).json())
      .current_customer_upload_id,
  ).toBe(secondId)

  const evidence = process.env.PRODUCT_LOGIC_EVIDENCE
  if (evidence) {
    await mkdir(evidence, { recursive: true })
    await page.setViewportSize({ width: 1366, height: 900 })
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({
      path: path.join(evidence, "data-access-en-1366.png"),
      fullPage: true,
    })
  }
  const writes: string[] = []
  page.on("request", (req) => {
    if (!["GET", "HEAD", "OPTIONS"].includes(req.method()))
      writes.push(`${req.method()} ${new URL(req.url()).pathname}`)
  })
  await page.reload()
  await expect(
    page.getByRole("heading", { name: "Data access", exact: true }),
  ).toBeVisible()
  await page
    .getByRole("link", { name: "Customer asset ledger", exact: true })
    .first()
    .click()
  await expect(
    page.getByRole("heading", { name: "Customer asset ledger", exact: true }),
  ).toBeVisible()
  expect(writes).toEqual([])
})

test("real C+A result stays fixed across browsing, optional evidence and expiry", async ({
  page,
  request,
}) => {
  test.setTimeout(180_000)
  page.setDefaultTimeout(15_000)
  const { readFile } = await import("node:fs/promises")
  const { execFileSync } = await import("node:child_process")
  const repo = path.resolve(fileURLToPath(new URL("../..", import.meta.url)))
  const seed = (stage: string) =>
    execFileSync(
      "python3",
      [
        "../evidence/run-browser.py",
        "backend",
        "uv",
        "run",
        "python",
        "../scripts/seed-product-logic-acceptance.py",
        stage,
      ],
      { cwd: repo, stdio: "pipe" },
    )
  seed("core")
  let fixture = JSON.parse(
    await readFile(process.env.PRODUCT_LOGIC_FIXTURE!, "utf8"),
  )
  const login = await request.post(`${api}/api/v1/login/access-token`, {
    form: {
      username: process.env.FIRST_SUPERUSER!,
      password: process.env.FIRST_SUPERUSER_PASSWORD!,
    },
  })
  expect(login.ok()).toBeTruthy()
  const token = (await login.json()).access_token as string
  const headers = { Authorization: `Bearer ${token}` }
  const root = `${api}/api/v1/projects/${fixture.project_id}`
  const route = `/projects/${fixture.project_id}/netflow-correlation`
  await page.addInitScript(
    (value) => localStorage.setItem("access_token", value),
    token,
  )
  await page.goto(route)
  await expect(
    page.getByRole("heading", {
      name: "No readable comparison has been generated",
    }),
  ).toBeVisible()
  await page
    .getByRole("button", { name: "Generate comparison results", exact: true })
    .click()
  await page
    .getByLabel("Confirmed network namespace", { exact: true })
    .fill(fixture.namespace)
  await page
    .getByLabel("Same-space confirmation evidence", { exact: true })
    .fill(
      "Synthetic customer and CloudAtlas scope confirmed for the same test network",
    )
  let result: { id: string } | undefined
  let creates = 0
  let replyLost: () => void = () => {}
  const committedThenLost = new Promise<void>((resolve) => {
    replyLost = resolve
  })
  await page.route(
    `**/api/v1/projects/${fixture.project_id}/comparison-results`,
    async (route) => {
      if (route.request().method() !== "POST") return route.continue()
      creates += 1
      const response = await route.fetch()
      expect(response.status(), await response.text()).toBe(201)
      result = await response.json()
      await route.abort("connectionfailed")
      replyLost()
    },
  )
  await page
    .getByRole("button", { name: "Confirm and generate results", exact: true })
    .click()
  await committedThenLost
  await expect(
    page.getByRole("region", {
      name: "Recover original operation",
      exact: true,
    }),
  ).toBeVisible()
  expect(creates).toBe(1)
  await page.reload()
  await expect(
    page.getByRole("region", {
      name: "Recover original operation",
      exact: true,
    }),
  ).toBeVisible()
  expect(new URL(page.url()).searchParams.has("result")).toBe(false)
  await page
    .getByRole("button", { name: "Read original operation", exact: true })
    .click()
  await expect(page).toHaveURL(new RegExp(`result=${result!.id}`))
  expect(creates).toBe(1)
  const summary = async () => {
    const response = await request.get(
      `${root}/comparison-results/${result!.id}/summary`,
      { headers },
    )
    expect(response.ok()).toBeTruthy()
    return response.json()
  }
  const initial = await summary()
  expect(initial).toMatchObject(fixture.expected)
  expect(initial.selection.netflow).toBeNull()
  const rows = page.getByRole("table", {
    name: "Comparison addresses",
    exact: true,
  })
  await expect(rows).toBeVisible()
  await expect(rows.getByRole("row")).toHaveCount(26)
  const writes: string[] = []
  const observe = (req: import("@playwright/test").Request) => {
    if (!["GET", "HEAD", "OPTIONS"].includes(req.method()))
      writes.push(`${req.method()} ${new URL(req.url()).pathname}`)
  }
  page.on("request", observe)
  await page
    .getByRole("navigation", { name: "Comparison addresses pagination" })
    .getByRole("button", { name: "Next" })
    .click()
  await expect(page).toHaveURL(/core_page=1/)
  await page
    .locator("summary")
    .filter({ hasText: "View the materials used here" })
    .click()
  await page
    .getByRole("link", {
      name: "Read the customer version used here",
      exact: true,
    })
    .click()
  await expect(page).toHaveURL(
    new RegExp(`ledger_upload=${fixture.customer_upload_id}`),
  )
  await expect(
    page.getByRole("heading", { name: "Customer asset ledger", exact: true }),
  ).toBeVisible()
  await page
    .getByRole("link", { name: "Return to comparison results", exact: true })
    .click()
  await expect(page).toHaveURL(new RegExp(`result=${result!.id}`))
  await expect(page).toHaveURL(/core_page=1/)
  await page
    .locator("summary")
    .filter({ hasText: "View the materials used here" })
    .click()
  await page
    .getByRole("link", {
      name: "Read the CloudAtlas version used here",
      exact: true,
    })
    .click()
  await expect(page).toHaveURL(
    new RegExp(`external_version=${fixture.cloud_version_id}`),
  )
  await page
    .getByRole("link", { name: "Return to comparison results", exact: true })
    .click()
  await expect(page).toHaveURL(/core_page=1/)
  await page.getByLabel("IP address", { exact: true }).fill("192.0.2.20")
  await page.getByRole("button", { name: "Filter", exact: true }).click()
  await expect(rows.getByRole("row")).toHaveCount(2)
  await rows.getByRole("button", { name: "View evidence", exact: true }).click()
  const detail = page.getByRole("region", {
    name: "Fixed address evidence",
    exact: true,
  })
  await expect(detail).toBeVisible()
  await expect(
    detail.getByText("Customer records 2", { exact: false }),
  ).toBeVisible()
  const fixedUrl = page.url()
  await page
    .getByRole("button", { name: "Close evidence", exact: true })
    .click()
  await page.getByRole("button", { name: "Clear filters", exact: true }).click()
  for (const name of [
    "Recorded on both sides",
    "CloudAtlas record, not registered in this customer version",
    "Customer record, not observed in this CloudAtlas batch",
  ]) {
    await page.getByRole("button", { name: new RegExp(`^${name}`) }).click()
    await expect(rows).toBeVisible()
  }
  await page.getByRole("button", { name: /^All addresses/ }).click()
  await page.getByRole("button", { name: "Refresh page", exact: true }).click()
  await page.goto(route)
  await expect(page).toHaveURL(new RegExp(`result=${result!.id}`))
  await expect(rows).toBeVisible()
  expect(writes).toEqual([])
  page.off("request", observe)

  // Initialization is outside the read-only browsing observation window.
  seed("netflow")
  fixture = JSON.parse(
    await readFile(process.env.PRODUCT_LOGIC_FIXTURE!, "utf8"),
  )
  await page.goto(`/projects/${fixture.project_id}/netflow-results`)
  await expect(page).toHaveURL(new RegExp(`analysis=${fixture.analysis_id}`))
  await expect(
    page.getByLabel("Observation objects", { exact: true }),
  ).toHaveText("2")
  await expect(page.getByText("192.0.2.40", { exact: true })).toBeVisible()
  const evidence = process.env.PRODUCT_LOGIC_EVIDENCE!
  await mkdir(evidence, { recursive: true })
  await page.setViewportSize({ width: 1366, height: 950 })
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({
    path: path.join(evidence, "netflow-en-1366.png"),
    fullPage: true,
  })
  await page.goto(route)
  await expect(rows).toBeVisible()
  await page
    .getByRole("button", { name: "Attach existing observations", exact: true })
    .click()
  const cutoff = new Date(Date.now() + 20_000)
  const local = new Date(cutoff.getTime() - cutoff.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 19)
  await page
    .getByLabel("Evidence valid until (local time)", { exact: true })
    .fill(local)
  await page
    .getByLabel("Same-space evidence for this result and these observations", {
      exact: true,
    })
    .fill("Synthetic same network and explicit short evidence cutoff")
  const bindReply = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      new URL(r.url()).pathname ===
        `/api/v1/projects/${fixture.project_id}/comparison-results/${result!.id}/supplements`,
  )
  await page
    .getByRole("button", { name: "Confirm evidence binding", exact: true })
    .click()
  expect((await bindReply).status()).toBe(201)
  const leads = page.getByRole("table", {
    name: "Supplemental leads",
    exact: true,
  })
  await expect(leads.getByText("192.0.2.40", { exact: true })).toBeVisible()
  expect(await summary()).toMatchObject(fixture.expected)
  const boundUrl = page.url()
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({
    path: path.join(evidence, "comparison-with-evidence-en-1366.png"),
    fullPage: true,
  })
  await expect(
    page.getByText("Evidence expired", { exact: true }).first(),
  ).toBeVisible({ timeout: 30_000 })
  await expect(leads).toHaveCount(0)
  await expect(rows.getByText("192.0.2.40", { exact: true })).toHaveCount(0)
  expect(await summary()).toMatchObject(fixture.expected)
  await page.reload()
  await expect(rows).toBeVisible()
  await expect(leads).toHaveCount(0)
  await expect(page).toHaveURL(boundUrl)

  for (const [width, language, theme] of [
    [1366, "en", "light"],
    [1920, "zh-CN", "dark"],
    [390, "zh-CN", "light"],
  ] as const) {
    await page.setViewportSize({ width: 1366, height: 950 })
    await page
      .getByRole("combobox", { name: "Language / 语言" })
      .selectOption(language)
    await page.getByTestId("theme-button").click()
    await page.getByTestId(`${theme}-mode`).click()
    await page.setViewportSize({ width, height: 950 })
    await page.evaluate(() => window.scrollTo(0, 0))
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
    ).toBe(false)
    await page.screenshot({
      path: path.join(evidence, `comparison-${width}-${language}-${theme}.png`),
      fullPage: true,
    })
  }
  await page.setViewportSize({ width: 1366, height: 950 })
  await page
    .getByRole("combobox", { name: "Language / 语言" })
    .selectOption("en")
  await page.goto(fixedUrl)
  await expect(detail).toBeVisible()
  await page.screenshot({
    path: path.join(evidence, "fixed-evidence-en-1366.png"),
    fullPage: true,
  })
  await page
    .getByRole("button", { name: "Close evidence", exact: true })
    .focus()
  await page.keyboard.press("Enter")
  await expect(detail).toHaveCount(0)
  await page.route(
    `**/api/v1/projects/${fixture.project_id}/comparison-results/current`,
    (route) =>
      route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          detail: { code: "temporary_metadata_failure" },
        }),
      }),
  )
  await page.goto(route)
  await expect(
    page.getByText("Current result metadata could not be read.", {
      exact: false,
    }),
  ).toBeVisible()
  await expect(
    page.getByRole("heading", {
      name: "No readable comparison has been generated",
    }),
  ).toHaveCount(0)
})

test("real evidence revocation rejects a delayed response without clearing C+A", async ({
  page,
  request,
}) => {
  test.setTimeout(60_000)
  const { readFile } = await import("node:fs/promises")
  const fixture = JSON.parse(
    await readFile(process.env.PRODUCT_LOGIC_FIXTURE!, "utf8"),
  )
  const login = await request.post(`${api}/api/v1/login/access-token`, {
    form: {
      username: process.env.FIRST_SUPERUSER!,
      password: process.env.FIRST_SUPERUSER_PASSWORD!,
    },
  })
  const token = (await login.json()).access_token as string
  const headers = { Authorization: `Bearer ${token}` }
  const root = `${api}/api/v1/projects/${fixture.project_id}`
  const current = await (
    await request.get(`${root}/comparison-results/current`, { headers })
  ).json()
  const resultId = current.result.id
  const base = `${root}/comparison-results/${resultId}`
  const previous = await (
    await request.get(`${base}/supplements`, { headers })
  ).json()
  const bindingResponse = await request.post(`${base}/supplements`, {
    headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
    data: {
      analysis_id: fixture.analysis_id,
      expected_binding_id: previous.id,
      valid_until: new Date(Date.now() + 3600_000).toISOString(),
      scope_evidence: "Independent synthetic browser revocation check",
    },
  })
  expect(bindingResponse.status(), await bindingResponse.text()).toBe(201)
  const binding = await bindingResponse.json()
  await page.addInitScript(
    (value) => localStorage.setItem("access_token", value),
    token,
  )
  const url = `/projects/${fixture.project_id}/netflow-correlation?result=${resultId}&binding=${binding.id}`
  await page.goto(url)
  const rows = page.getByRole("table", {
    name: "Comparison addresses",
    exact: true,
  })
  const leads = page.getByRole("table", {
    name: "Supplemental leads",
    exact: true,
  })
  await expect(leads.getByText("192.0.2.40", { exact: true })).toBeVisible()
  let release: () => void = () => {}
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  let captured: () => void = () => {}
  const capturedResponse = new Promise<void>((resolve) => {
    captured = resolve
  })
  await page.route(
    `**/comparison-results/${resultId}/supplements/${binding.id}/addresses**`,
    async (route) => {
      if (!route.request().url().includes("only_supplemental=true"))
        return route.continue()
      const response = await route.fetch()
      captured()
      await held
      await route.fulfill({ response }).catch(() => {})
    },
  )
  await page.getByRole("button", { name: "Refresh page", exact: true }).click()
  await capturedResponse
  const contexts = `${root}/netflow-datasets/${fixture.dataset_id}/processing-contexts`
  const selected = (
    await (
      await request.get(
        `${contexts}?context_revision_id=${fixture.context_revision_id}`,
        { headers },
      )
    ).json()
  ).data[0]
  const revoked = await request.post(contexts, {
    headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
    data: {
      expected_parent_id: fixture.context_revision_id,
      state: "REVOKED",
      network_namespace: selected.network_namespace,
      collection_scope: selected.collection_scope,
      collection_scope_evidence: selected.collection_scope_evidence,
      endpoint_selection: selected.declarations.endpoint_selection,
      source_position_evidence: selected.declarations.source_position_evidence,
      nat_context: selected.declarations.nat_context,
      nat_evidence: selected.declarations.nat_evidence,
      observation_point: selected.declarations.observation_point,
      sampling: selected.declarations.sampling,
    },
  })
  expect(revoked.status(), await revoked.text()).toBe(201)
  await expect(
    page.getByText(
      "Evidence is unavailable under its current permissions or context.",
      { exact: false },
    ),
  ).toBeVisible({ timeout: 15_000 })
  release()
  await expect(leads).toHaveCount(0)
  await expect(rows).toBeVisible()
  await page.reload()
  await expect(leads).toHaveCount(0)
  await expect(rows).toBeVisible()
  const summary = await (
    await request.get(`${base}/summary`, { headers })
  ).json()
  expect(summary).toMatchObject(fixture.expected)
  const evidence = process.env.PRODUCT_LOGIC_EVIDENCE
  if (evidence) {
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({
      path: path.join(evidence, "core-after-evidence-revocation.png"),
      fullPage: true,
    })
  }
  const writes: string[] = []
  page.on("request", (req) => {
    if (!["GET", "HEAD", "OPTIONS"].includes(req.method()))
      writes.push(req.method())
  })
  const fixedFlow = `/projects/${fixture.project_id}/netflow-results?analysis=${fixture.analysis_id}&dataset=${fixture.dataset_id}`
  await page.goto(fixedFlow)
  await expect(
    page.getByRole("heading", {
      name: "This fixed batch cannot be read",
      exact: true,
    }),
  ).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`analysis=${fixture.analysis_id}`))
  await expect(page.getByText("192.0.2.40", { exact: true })).toHaveCount(0)
  await page.reload()
  await expect(
    page.getByRole("heading", {
      name: "This fixed batch cannot be read",
      exact: true,
    }),
  ).toBeVisible()
  expect(writes).toEqual([])
})
