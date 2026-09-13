import { writeFileSync } from "node:fs"
import { expect, type Page, test } from "./fixtures"

const actor = "30000000-0000-4000-8000-000000000001"
const connection = "40000000-0000-4000-8000-000000000001"
const secret = "synthetic-key-never-real"
const endpoint = "http://model.internal:8080/v1"
const stamp = "2026-09-12T00:00:00Z"
async function fixture(page: Page, admin = true) {
  const state = {
    generation: 0,
    adopted: false,
    active_id: null as string | null,
    pending_id: null as string | null,
    connections: [] as any[],
  }
  const f = {
    actor,
    admin,
    state,
    drop: false,
    offline: false,
    unknown: false,
    delay: 0,
    calls: [] as any[],
    ops: new Map<string, any>(),
  }
  await page.addInitScript(() =>
    localStorage.setItem("access_token", "synthetic-ui-token"),
  )
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request(),
      path = new URL(req.url()).pathname,
      method = req.method()
    if (path.endsWith("/users/me"))
      return route.fulfill({
        json: {
          id: f.actor,
          is_active: true,
          is_superuser: f.admin,
          email: "synthetic@example.test",
          full_name: "Synthetic administrator",
        },
      })
    if (!path.includes("model-connections"))
      return route.fulfill({ json: { data: [], count: 0 } })
    const key = req.headers()["idempotency-key"] ?? "",
      body = method === "POST" ? req.postDataJSON() : null
    f.calls.push({ method, path, key, body })
    if (path.endsWith("/status"))
      return route.fulfill({
        json: {
          state: state.active_id
            ? "active"
            : state.adopted
              ? "disabled"
              : "legacy",
          ready: !!state.active_id,
          configured: true,
          model_identity: "fixture-model",
        },
      })
    if (!f.admin)
      return route.fulfill({ status: 403, json: { detail: "Forbidden" } })
    if (path.includes("/operations/recover/")) {
      if (f.offline) return route.abort("failed")
      const op = f.ops.get(key)
      return op && op.action === path.split("/").at(-1)!.toUpperCase()
        ? route.fulfill({ json: { operation: op, state } })
        : route.fulfill({
            status: 404,
            json: { detail: { code: "model_connection_operation_not_found" } },
          })
    }
    if (path.includes("/operations/"))
      return route.fulfill({
        json: {
          operation: [...f.ops.values()].find(
            (op) => op.id === path.split("/").at(-1),
          ),
          state,
        },
      })
    if (method === "GET") return route.fulfill({ json: state })
    if (f.delay) await new Promise((resolve) => setTimeout(resolve, f.delay))
    const action = path.endsWith("/model-connections")
      ? "SAVE"
      : path.endsWith("/adopt-legacy")
        ? "ADOPT"
        : path.split("/").at(-1)!.toUpperCase()
    const existing = f.ops.get(key)
    if (existing && existing.status !== "UNKNOWN")
      return route.fulfill({ json: { operation: existing, state } })
    const op = existing ?? {
      id: crypto.randomUUID(),
      connection_id: connection,
      action,
      expected_generation: body.expected_generation,
      status: "SUCCEEDED",
      error_code: null,
      evidence: null,
      created_at: stamp,
      completed_at: stamp,
    }
    if (!existing) state.generation++
    if (["SAVE", "ADOPT"].includes(action)) {
      state.pending_id = connection
      state.connections = [
        {
          id: connection,
          name: body.name ?? "Imported deployment connection",
          endpoint,
          protocol: "chat_completions",
          model_identity: body.model_identity ?? "fixture-model",
          key_configured: true,
          validation_status: "UNVERIFIED",
          validation_operation_id: null,
          validation_evidence: null,
          validation_completed_at: null,
          created_at: stamp,
          activated_at: null,
          revoked_at: null,
          discarded_at: null,
        },
      ]
    }
    const version = state.connections[0]
    if (action === "VALIDATE") {
      op.status = f.unknown ? "UNKNOWN" : "SUCCEEDED"
      version.validation_status = f.unknown ? "VALIDATING" : "VALIDATED"
      version.validation_operation_id = op.id
      if (!f.unknown) {
        version.validation_evidence = {
          qualification: "PASS",
          investigation: "PASS",
          analysis_report: "PASS",
          runtime: "PASS",
        }
        version.validation_completed_at = stamp
        op.evidence = version.validation_evidence
      }
    }
    if (action === "ACTIVATE") {
      state.adopted = true
      state.active_id = connection
      state.pending_id = null
      version.activated_at = stamp
    }
    if (action === "REVOKE") {
      state.active_id = null
      version.revoked_at = stamp
    }
    if (action === "DISCARD") {
      state.pending_id = null
      version.discarded_at = stamp
    }
    f.ops.set(key, op)
    if (f.drop) {
      f.drop = false
      return route.abort("failed")
    }
    return route.fulfill({
      status: action === "SAVE" ? 201 : 200,
      json: { operation: op, state },
    })
  })
  return f
}
async function fill(page: Page) {
  await page
    .getByLabel("Connection name", { exact: true })
    .fill("Synthetic connection")
  await page.getByLabel("API base URL").fill(endpoint)
  await page.getByLabel("Model identifier").fill("fixture-model")
  await page.getByLabel("API Key", { exact: true }).fill(secret)
}
async function noSecretStorage(page: Page) {
  const data = await page.evaluate(() =>
    JSON.stringify({
      session: { ...sessionStorage },
      local: { ...localStorage },
      url: location.href,
    }),
  )
  expect(data).not.toContain(secret)
  expect(data).not.toContain(endpoint)
  expect(await page.locator("body").innerText()).not.toContain(secret)
}
test("save, verify, activate and explicit revoke stay separate", async ({
  page,
}) => {
  const f = await fixture(page)
  await page.goto("/ai-settings")
  await fill(page)
  await page
    .getByRole("button", { name: "Save pending version", exact: true })
    .click()
  await expect(
    page.getByRole("region", { name: "Pending connection" }),
  ).toBeVisible()
  expect(f.calls.filter((c) => c.method === "POST")).toHaveLength(1)
  await expect(
    page.getByRole("button", { name: "Activate for new tasks" }),
  ).toBeDisabled()
  await page
    .getByRole("button", { name: "Verify connection", exact: true })
    .click()
  await expect(
    page.getByRole("button", { name: "Activate for new tasks" }),
  ).toBeEnabled()
  expect(f.state.active_id).toBeNull()
  await page.getByRole("button", { name: "Activate for new tasks" }).click()
  await page.getByRole("button", { name: "Disable current connection" }).click()
  expect(f.state.active_id).toBe(connection)
  await page
    .getByRole("button", { name: "Confirm revocation", exact: true })
    .click()
  await expect(
    page.getByText("No active connection.", { exact: false }),
  ).toBeVisible()
  await noSecretStorage(page)
})
test("lost save response recovers on reload without retaining inputs or repeating POST", async ({
  page,
}) => {
  const f = await fixture(page)
  await page.goto("/ai-settings")
  await fill(page)
  f.drop = true
  f.offline = true
  await page
    .getByRole("button", { name: "Save pending version", exact: true })
    .click()
  await expect(page.getByLabel("API Key", { exact: true })).toHaveValue("")
  await expect(
    page.getByRole("region", { name: "Operation recovery" }),
  ).toBeVisible()
  await noSecretStorage(page)
  f.offline = false
  await page.reload()
  await expect(
    page.getByRole("region", { name: "Pending connection" }),
  ).toBeVisible()
  await expect(
    page.getByRole("region", { name: "Operation recovery" }),
  ).toHaveCount(0)
  expect(f.calls.filter((c) => c.method === "POST")).toHaveLength(1)
})
test("UNKNOWN refresh only reads; explicit retry preserves key and generation", async ({
  page,
}) => {
  const f = await fixture(page)
  await page.goto("/ai-settings")
  await fill(page)
  await page
    .getByRole("button", { name: "Save pending version", exact: true })
    .click()
  f.unknown = true
  await page
    .getByRole("button", { name: "Verify connection", exact: true })
    .click()
  await expect(
    page.getByText("Unconfirmed", { exact: true }).first(),
  ).toBeVisible()
  const original = f.calls.filter((c) => c.method === "POST").at(-1)!
  await page.reload()
  await page
    .getByRole("button", { name: "Query original operation", exact: true })
    .click()
  expect(f.calls.filter((c) => c.method === "POST")).toHaveLength(2)
  f.unknown = false
  await page
    .getByRole("button", { name: "Confirm retry of original intent" })
    .click()
  await expect(
    page.getByRole("button", { name: "Activate for new tasks" }),
  ).toBeEnabled()
  const replay = f.calls.filter((c) => c.method === "POST").at(-1)!
  expect(replay.key).toBe(original.key)
  expect(replay.body).toEqual(original.body)
})
test("lost ADOPT response recovers as ADOPT", async ({ page }) => {
  const f = await fixture(page)
  await page.goto("/ai-settings")
  f.drop = true
  f.offline = true
  await page
    .getByRole("button", { name: "Import deployment connection" })
    .click()
  await expect(
    page.getByRole("region", { name: "Operation recovery" }),
  ).toBeVisible()
  f.offline = false
  await page.reload()
  await expect(
    page.getByText("Imported deployment connection", { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole("region", { name: "Operation recovery" }),
  ).toHaveCount(0)
  expect(f.calls.filter((c) => c.method === "POST")).toHaveLength(1)
  expect(f.calls.some((c) => c.path.endsWith("/recover/adopt"))).toBe(true)
})
test("ordinary users only request availability", async ({ page }) => {
  const f = await fixture(page, false)
  await page.goto("/ai-settings")
  await expect(
    page.getByText("Only an administrator can manage model connections.", {
      exact: false,
    }),
  ).toBeVisible()
  await expect(page.getByLabel("API Key", { exact: true })).toHaveCount(0)
  expect(
    f.calls.every((c) => c.path.endsWith("/status") && c.method === "GET"),
  ).toBe(true)
})
test("page hide clears secrets; a different actor cannot see recovery", async ({
  page,
}) => {
  const f = await fixture(page)
  await page.goto("/ai-settings")
  await fill(page)
  await page.evaluate(() =>
    window.dispatchEvent(new PageTransitionEvent("pagehide")),
  )
  await expect(page.getByLabel("API Key", { exact: true })).toHaveValue("")
  await page.evaluate(
    (actor) =>
      sessionStorage.setItem(
        `exposure:model-connection:${actor}`,
        JSON.stringify({ key: crypto.randomUUID(), action: "save" }),
      ),
    actor,
  )
  f.actor = "30000000-0000-4000-8000-000000000002"
  await page.reload()
  await expect(
    page.getByRole("heading", { name: "Model connections" }),
  ).toBeVisible()
  await expect(
    page.getByRole("region", { name: "Operation recovery" }),
  ).toHaveCount(0)
  await noSecretStorage(page)
})
for (const width of [390, 1366, 1920])
  test(`layout and keyboard at ${width}px`, async ({ page }) => {
    await fixture(page)
    await page.setViewportSize({ width, height: width === 1920 ? 1080 : 768 })
    await page.emulateMedia({ reducedMotion: "reduce" })
    await page.goto("/ai-settings")
    await fill(page)
    await page.getByLabel("API Key", { exact: true }).focus()
    await page.keyboard.press("Tab")
    await expect(
      page.getByRole("button", { name: "Save pending version", exact: true }),
    ).toBeFocused()
    await page.keyboard.press("Enter")
    await page
      .getByRole("button", { name: "Verify connection", exact: true })
      .click()
    await expect(
      page.getByRole("button", { name: "Activate for new tasks" }),
    ).toBeEnabled()
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true)
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({
      path: `/tmp/expux02-ui-${width}-en-dark.png`,
      fullPage: true,
    })
    await page.evaluate(() => {
      localStorage.setItem("exposure:language", "zh")
      localStorage.setItem("vite-ui-theme", "light")
    })
    await page.reload()
    await expect(
      page.getByRole("heading", { name: "AI 设置", exact: true }),
    ).toBeVisible()
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true)
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({
      path: `/tmp/expux02-ui-${width}-zh-light.png`,
      fullPage: true,
    })
  })

test("five local submission feedback measurements", async ({ page }) => {
  const f = await fixture(page)
  f.delay = 350
  const samples: number[] = []
  const longTasks: number[] = []
  for (let i = 0; i < 5; i++) {
    f.state.connections = []
    f.state.pending_id = null
    f.ops.clear()
    await page.goto("/ai-settings")
    await fill(page)
    const result = await page.evaluate(async () => {
      const tasks: number[] = []
      const observer = new PerformanceObserver((list) => {
        for (const e of list.getEntries()) tasks.push(e.duration)
      })
      observer.observe({ type: "longtask", buffered: false })
      const start = performance.now()
      const button = [...document.querySelectorAll("button")].find(
        (b) => b.textContent?.trim() === "Save pending version",
      )!
      button.click()
      const elapsed = await new Promise<number>((resolve) => {
        const frame = () => {
          if (
            document.body.textContent?.includes("Submitting…") ||
            performance.now() - start > 1000
          )
            resolve(performance.now() - start)
          else requestAnimationFrame(frame)
        }
        requestAnimationFrame(frame)
      })
      await new Promise((resolve) => setTimeout(resolve, 400))
      observer.disconnect()
      return { elapsed, tasks }
    })
    samples.push(result.elapsed)
    longTasks.push(...result.tasks)
    await expect(
      page.getByRole("region", { name: "Pending connection" }),
    ).toBeVisible()
  }
  writeFileSync(
    "/tmp/expux02-ui-feedback.json",
    JSON.stringify(
      {
        samples,
        longTasks,
        baseline: "NOT_AVAILABLE_NEW_SURFACE",
        provider: "MOCK_DELAY_350MS",
      },
      null,
      2,
    ),
  )
  expect(Math.max(...samples)).toBeLessThanOrEqual(100)
  expect(longTasks.every((duration) => duration <= 200)).toBe(true)
})

test("server permission loss clears the form and exposes no raw error", async ({
  page,
}) => {
  const f = await fixture(page)
  await page.goto("/ai-settings")
  await fill(page)
  f.admin = false
  await page
    .getByRole("button", { name: "Save pending version", exact: true })
    .click()
  await expect(
    page.getByText(
      "Permission is no longer available. Connection inputs have been cleared.",
    ),
  ).toBeVisible()
  await expect(page.getByLabel("API Key", { exact: true })).toHaveCount(0)
  await noSecretStorage(page)
})

test("a late response from an old token cannot publish old configuration", async ({
  page,
}) => {
  const f = await fixture(page)
  f.delay = 500
  await page.goto("/ai-settings")
  await fill(page)
  await page
    .getByRole("button", { name: "Save pending version", exact: true })
    .click()
  await expect(page.getByLabel("API Key", { exact: true })).toHaveValue("")
  await page.evaluate(() =>
    localStorage.setItem("access_token", "replacement-account-token"),
  )
  await page.waitForTimeout(650)
  await expect(
    page.getByRole("region", { name: "Pending connection" }),
  ).toHaveCount(0)
  await noSecretStorage(page)
})

test("generation conflict stays separate from an unknown network result", async ({
  page,
}) => {
  await fixture(page)
  await page.route("**/api/v1/model-connections", async (route, request) => {
    if (request.method() === "POST")
      return route.fulfill({
        status: 409,
        json: { detail: { code: "model_connection_generation_conflict" } },
      })
    return route.fallback()
  })
  await page.goto("/ai-settings")
  await fill(page)
  await page
    .getByRole("button", { name: "Save pending version", exact: true })
    .click()
  await expect(
    page.getByText("The connection state changed.", { exact: false }),
  ).toBeVisible()
  await expect(page.getByLabel("API Key", { exact: true })).toHaveValue("")
  await page.getByRole("button", { name: "Return to configuration" }).click()
  await expect(
    page.getByRole("region", { name: "Operation recovery" }),
  ).toHaveCount(0)
})
