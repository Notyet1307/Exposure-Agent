import { execFileSync } from "node:child_process"
import { createHash } from "node:crypto"
import { readFile, writeFile } from "node:fs/promises"
import path from "node:path"
import { expect, test } from "@playwright/test"

test.skip(
  process.env.RUN_NETFLOW_USABILITY_E2E !== "1",
  "Use scripts/test-netflow-usability.py for an isolated database, real worker and synthetic HTTPS source",
)

test("fresh project to real worker, three sources, review history and local-only reads", async ({
  page,
  request,
  browser,
}) => {
  test.setTimeout(600_000)
  const evidence = process.env.NETFLOW_USABILITY_EVIDENCE!
  const upstream = process.env.NETFLOW_USABILITY_UPSTREAM!
  if (!evidence || !/^nf-usability-[a-f0-9]{10}-upstream$/.test(upstream))
    throw new Error("Isolated harness identity is required")
  const login = await request.post("/api/v1/login/access-token", {
    form: {
      username: process.env.FIRST_SUPERUSER!,
      password: process.env.FIRST_SUPERUSER_PASSWORD!,
    },
  })
  expect(login.ok()).toBe(true)
  const token = (await login.json()).access_token as string
  const headers = { Authorization: `Bearer ${token}` }
  const get = async (url: string) => {
    const response = await request.get(`/api/v1${url}`, { headers })
    expect(response.status(), url).toBe(200)
    return response.json()
  }
  const post = async (url: string, data: unknown) => {
    const response = await request.post(`/api/v1${url}`, {
      headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
      data,
    })
    expect(response.ok(), `${url}: ${await response.text()}`).toBe(true)
    return response.json()
  }
  const project = await post("/projects/", {
    name: `Synthetic NetFlow usability ${crypto.randomUUID()}`,
  })
  const root = `/projects/${project.id}`
  expect((await get(`${root}/netflow-datasets`)).count).toBe(0)
  expect((await get(`${root}/source-correlations`)).count).toBe(0)
  await page.addInitScript((value) => {
    localStorage.setItem("access_token", value)
    localStorage.setItem("exposure:language", "en")
  }, token)
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto(`${root}/netflow-correlation`)
  await page
    .getByRole("link", { name: "Import NetFlow data", exact: true })
    .click()
  const csv = `IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n${Array.from({ length: 30 }, (_, i) => [1, 2].map((peer) => `192.0.2.${i + 1},198.51.100.${peer},6,443,53000\n`).join("")).join("")}${"192.0.2.1,198.51.100.1,6,443,53000\n".repeat(25)}`
  await page.locator("#netflow-dataset-file").setInputFiles({
    name: "synthetic.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csv),
  })
  await page
    .getByRole("region", { name: "NetFlowDatasets", exact: true })
    .getByRole("button", { name: "Upload", exact: true })
    .click()
  await page
    .getByRole("link", { name: "Configure processing context for this upload" })
    .click()
  const dataset = new URL(page.url()).searchParams.get("dataset")!
  expect(
    (await get(`${root}/netflow-datasets/${dataset}/processing-contexts`))
      .count,
  ).toBe(0)
  expect(
    (await get(`${root}/netflow-datasets/${dataset}/analyses`)).count,
  ).toBe(0)
  const contextForm = page.getByRole("region", {
    name: "Create processing context",
  })
  await contextForm.getByLabel("Network namespace").fill("synthetic-usability")
  await contextForm.getByLabel("Observation point ID").fill("synthetic-edge")
  await contextForm
    .getByLabel("Source-side position evidence")
    .fill("Synthetic fixture: source is local, destination external")
  await contextForm.getByLabel("Context state").selectOption("CONFIRMED")
  await contextForm.getByLabel("NAT situation").selectOption("none")
  await contextForm
    .getByLabel("NAT evidence")
    .fill("Synthetic unconverted endpoints")
  const contextEndpoint = `**/api/v1${root}/netflow-datasets/${dataset}/processing-contexts`
  let contextPosts = 0
  await page.route(contextEndpoint, async (route) => {
    if (route.request().method() !== "POST") return route.continue()
    contextPosts += 1
    const result = await route.fetch()
    expect(result.ok()).toBe(true)
    // Lose only the HTTP response after the real server has committed the Context.
    await route.abort("failed")
  })
  await contextForm
    .getByRole("button", { name: "Append context version" })
    .click()
  await contextForm
    .getByRole("button", { name: "Query original context operation" })
    .click()
  await page.unroute(contextEndpoint)
  expect(contextPosts).toBe(1)
  expect(
    (await get(`${root}/netflow-datasets/${dataset}/processing-contexts`))
      .count,
  ).toBe(1)
  await page
    .getByRole("button", { name: "Start selected context analysis" })
    .click()
  await page.waitForURL((url) => url.searchParams.has("analysis"))
  const analysis = new URL(page.url()).searchParams.get("analysis")!
  await expect
    .poll(
      async () => (await get(`${root}/netflow-analyses/${analysis}`)).status,
      { timeout: 240_000, intervals: [1000, 2000] },
    )
    .toMatch(/^SUCCEEDED/)
  expect(
    (await get(`${root}/netflow-datasets/${dataset}/analyses`)).count,
  ).toBe(1)
  const processingUrl = page.url()
  const independentWrites: string[] = []
  const trackIndependentWrite = (item: {
    method: () => string
    url: () => string
  }) => {
    if (!["GET", "HEAD", "OPTIONS"].includes(item.method()))
      independentWrites.push(`${item.method()} ${new URL(item.url()).pathname}`)
  }
  page.on("request", trackIndependentWrite)
  // No correlation exists yet: select and read the sealed processing result.
  expect((await get(`${root}/source-correlations`)).count).toBe(0)
  await page
    .getByRole("link", { name: "Processed NetFlow data", exact: true })
    .click()
  await page.getByRole("button", { name: "synthetic.csv", exact: true }).click()
  await page.getByRole("button", { name: "Open batch", exact: true }).click()
  await expect(page.getByLabel("Original rows", { exact: true })).toHaveText(
    "85",
  )
  await expect(
    page.getByLabel("Observation objects", { exact: true }),
  ).toHaveText("30")
  await expect(
    page.getByLabel("Distinct source IPs", { exact: true }),
  ).toHaveText("30")
  await expect(
    page.getByRole("combobox", { name: "Published run", exact: true }),
  ).toHaveCount(0)
  await page
    .getByRole("navigation", { name: "Observations pagination" })
    .getByRole("button", { name: "Next", exact: true })
    .click()
  await page.getByRole("button", { name: "192.0.2.30", exact: true }).click()
  await expect(
    page.getByRole("heading", { name: "Observation details", exact: true }),
  ).toBeVisible()
  await page.getByLabel("Exact IP", { exact: true }).fill("::ffff:192.0.2.1")
  await page.getByLabel("Protocol number", { exact: true }).fill("6")
  await page.getByLabel("Source-side port", { exact: true }).fill("443")
  await page.getByRole("button", { name: "Filter", exact: true }).click()
  await page.getByRole("button", { name: "192.0.2.1", exact: true }).click()
  await expect(
    page.getByText("Source-side observed port: 443", { exact: true }),
  ).toBeVisible()
  await page
    .getByRole("button", { name: "View input evidence", exact: true })
    .click()
  await expect(
    page.getByRole("region", { name: "Input evidence", exact: true }),
  ).toContainText("Retained references: 20")
  await expect(
    page.getByRole("region", { name: "Input evidence", exact: true }),
  ).toContainText("Omitted references: 7")
  await page
    .getByRole("navigation", { name: "Evidence pagination" })
    .getByRole("button", { name: "Next", exact: true })
    .click()
  await page.reload()
  await expect(
    page.getByRole("heading", { name: "Input evidence", exact: true }),
  ).toBeVisible()
  expect(new URL(page.url()).searchParams.get("evidencePage")).toBe("1")
  expect(new URL(page.url()).searchParams.get("analysis")).toBe(analysis)
  await page
    .getByRole("button", { name: "External peers", exact: true })
    .click()
  await expect(
    page.getByRole("button", { name: "198.51.100.1", exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "192.0.2.1", exact: true }),
  ).toHaveCount(0)
  await page.getByRole("button", { name: "198.51.100.1", exact: true }).click()
  await expect(
    page.getByRole("heading", { name: "Input evidence", exact: true }),
  ).toBeVisible()
  await page.goto(processingUrl)
  page.off("request", trackIndependentWrite)
  expect(independentWrites).toEqual([])
  expect((await get(`${root}/source-correlations`)).count).toBe(0)
  // The first usable correlation is created by the page, with NetFlow alone.
  await page.getByRole("button", { name: "Create fixed correlation" }).click()
  await page.waitForURL((url) => url.searchParams.has("revision"))
  const singleRevision = new URL(page.url()).searchParams.get("revision")!
  expect(
    (await get(`${root}/source-correlations/${singleRevision}`))
      .total_addresses,
  ).toBe(30)

  const customer = await request.post(`/api/v1${root}/customer-uploads`, {
    headers,
    multipart: {
      file: {
        name: "synthetic-customer.xlsx",
        mimeType:
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        buffer: await readFile(path.join(evidence, "customer.xlsx")),
      },
    },
  })
  expect(customer.ok()).toBe(true)
  const upload = await customer.json()
  const source = await post(`${root}/external-assets/sources`, {
    instance_id: "nu279-assets",
    capset_id: "nu279-assets",
    space_id: "279",
  })
  expect(
    (
      await post(
        `${root}/external-assets/sources/${source.id}/validate`,
        undefined,
      )
    ).validation_status,
  ).toBe("validated")
  expect(
    (
      await request.patch(
        `/api/v1${root}/external-assets/sources/${source.id}`,
        { headers, data: { enabled: true } },
      )
    ).ok(),
  ).toBe(true)
  const sync = async (retention: number) => {
    const item = await post(
      `${root}/external-assets/sources/${source.id}/syncs`,
      {
        page_size: 25,
        max_pages: 8,
        max_records: 200,
        max_response_bytes: 1000000,
        timeout_seconds: 30,
        retain_until: new Date(Date.now() + retention).toISOString(),
      },
    )
    await expect
      .poll(
        async () =>
          (
            await get(
              `${root}/external-assets/sources/${source.id}/syncs/${item.id}`,
            )
          ).status,
        { timeout: 180_000, intervals: [1000, 2000] },
      )
      .toBe("SUCCEEDED")
    return get(`${root}/external-assets/sources/${source.id}/syncs/${item.id}`)
  }
  const published = await sync(28_800_000)
  const cloud = (item: {
    domains: Array<{ domain: string; version_id: string }>
  }) => ({
    kind: "external_versions",
    source_instance_id: source.id,
    ip_version_id: item.domains.find((d) => d.domain === "ip")!.version_id,
    port_version_id: item.domains.find((d) => d.domain === "port")!.version_id,
  })
  const correlation = await post(`${root}/source-correlations`, {
    network_namespace: "synthetic-usability",
    netflow: { analysis_id: analysis },
    customer: { upload_id: upload.id, revision_id: null },
    cloud: cloud(published),
    history_run_id: null,
  })
  const confirmed = await post(
    `${root}/source-correlations/${correlation.correlation_revision_id}/scope-revisions`,
    {
      expected_parent_id: correlation.correlation_revision_id,
      scope_state: "CONFIRMED",
      evidence:
        "Exact synthetic input versions describe the same fixture network",
    },
  )
  const limitedRevision = confirmed.correlation_revision_id as string
  const limitedSummary = await get(
    `${root}/source-correlations/${limitedRevision}`,
  )
  // The real IP sync is fixed to status=valid; successful pagination does not
  // erase that approved coverage restriction.
  expect(limitedSummary.comparison).toMatchObject({
    state: "INSUFFICIENT_COVERAGE",
    common_addresses: null,
    different_addresses: null,
  })
  expect(limitedSummary.positive_intersections).toBeNull()
  const completeCorrelation = await post(`${root}/source-correlations`, {
    network_namespace: "synthetic-usability",
    netflow: { analysis_id: analysis },
    customer: { upload_id: upload.id, revision_id: null },
    cloud: { ...cloud(published), ip_version_id: null },
    history_run_id: null,
  })
  const completeConfirmed = await post(
    `${root}/source-correlations/${completeCorrelation.correlation_revision_id}/scope-revisions`,
    {
      expected_parent_id: completeCorrelation.correlation_revision_id,
      scope_state: "CONFIRMED",
      evidence:
        "Customer, NetFlow and the complete unfiltered port batch describe the same synthetic network; no IP inventory is selected",
    },
  )
  const revision = completeConfirmed.correlation_revision_id as string
  const summary = await get(`${root}/source-correlations/${revision}`)
  expect(summary.total_addresses).toBe(38)
  expect(summary.comparison).toEqual({
    state: "AVAILABLE",
    sources: ["CUSTOMER", "CLOUD", "NETFLOW"],
    common_addresses: 1,
    different_addresses: 37,
  })
  const brief = await sync(70_000)
  const expiring = await post(`${root}/source-correlations`, {
    network_namespace: "synthetic-usability",
    netflow: null,
    customer: null,
    cloud: cloud(brief),
    history_run_id: null,
  })
  const readableBeforeExpiry = (await get(`${root}/source-correlations`)).count

  const reviews = `${root}/netflow-analyses/${analysis}`
  const firstFeedback = await get(`${reviews}/feedback`)
  const tasks = await get(
    `${reviews}/review-tasks?limit=100&feedback_revision_id=${firstFeedback.feedback_revision_id}`,
  )
  const exportTask = tasks.data.find(
    (item: { task: { task_kind: string } }) => item.task.task_kind === "export",
  )
  const serviceTask = tasks.data.find(
    (item: { task: { task_kind: string } }) =>
      item.task.task_kind === "service",
  )
  const taskUrl = (task: string, feedback: string) =>
    `${root}/netflow-correlation?revision=${revision}&tab=tasks&taskId=${encodeURIComponent(task)}&feedbackRevision=${feedback}`
  const answers = page.getByRole("region", { name: "Review answers" })
  const fill = async (label: string, value: string, enumeration = false) => {
    await answers
      .getByLabel(`${label} value state`, { exact: true })
      .selectOption("value")
    const input = answers.getByLabel(label, { exact: true })
    if (enumeration) await input.selectOption(value)
    else await input.fill(value)
  }
  const save = async (parent: string) => {
    await page
      .getByRole("button", { name: "Append correction", exact: true })
      .click()
    await page.waitForURL(
      (url) => url.searchParams.get("feedbackRevision") !== parent,
    )
    return new URL(page.url()).searchParams.get("feedbackRevision")!
  }
  const fixedPages = async (feedback: string) =>
    Promise.all(
      [0, 25].map((skip) =>
        get(
          `${reviews}/review-tasks?limit=25&skip=${skip}&feedback_revision_id=${feedback}`,
        ),
      ),
    )
  await page.goto(
    taskUrl(exportTask.task_id, firstFeedback.feedback_revision_id),
  )
  await fill("Responsible unit", "Synthetic collection team")
  const partial = await save(firstFeedback.feedback_revision_id)
  expect(
    (
      await get(
        `${reviews}/review-tasks/${encodeURIComponent(exportTask.task_id)}?feedback_revision_id=${partial}`,
      )
    ).material.material_status,
  ).toBe("MATERIAL_INCOMPLETE")
  const parentPages = await fixedPages(partial)
  await answers
    .getByLabel("Responsible unit", { exact: true })
    .fill("Synthetic corrected team")
  let latest = await save(partial)
  await page.getByRole("button", { name: "Read parent revision" }).click()
  await expect(
    answers.getByLabel("Responsible unit", { exact: true }),
  ).toHaveValue("Synthetic collection team")
  await expect(
    page.getByRole("button", { name: "Append correction", exact: true }),
  ).toBeDisabled()
  expect(await fixedPages(partial)).toEqual(parentPages)

  // Delay a real committed feedback response while the user starts another draft.
  const feedbackEndpoint = `**/api/v1${reviews}/feedback`
  let releaseResponse: (() => void) | undefined
  let committedFeedback: { feedback_revision_id: string } | undefined
  const gate = new Promise<void>((resolve) => {
    releaseResponse = resolve
  })
  await page.route(feedbackEndpoint, async (route) => {
    if (route.request().method() !== "POST") return route.continue()
    const response = await route.fetch()
    expect(response.ok()).toBe(true)
    committedFeedback = await response.json()
    await gate
    await route.fulfill({ response })
  })
  await page.goto(taskUrl(exportTask.task_id, latest))
  await answers
    .getByLabel("Responsible unit", { exact: true })
    .fill("Synthetic delayed correction")
  await page
    .getByRole("button", { name: "Append correction", exact: true })
    .click()
  await expect.poll(() => committedFeedback).toBeTruthy()
  await page
    .getByRole("region", { name: "Task table" })
    .getByRole("button", {
      name: `Service role material · ${serviceTask.task.target.ip} · ${serviceTask.task.target.local_port}`,
      exact: true,
    })
    .click()
  await fill("Responsible unit", "Other task's unsubmitted draft")
  const lateResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/feedback"),
  )
  releaseResponse!()
  await lateResponse
  await expect(
    answers.getByLabel("Responsible unit", { exact: true }),
  ).toHaveValue("Other task's unsubmitted draft")
  expect(new URL(page.url()).searchParams.get("feedbackRevision")).toBe(latest)
  expect(new URL(page.url()).searchParams.get("taskId")).toBe(
    serviceTask.task_id,
  )
  latest = committedFeedback!.feedback_revision_id
  await page.unroute(feedbackEndpoint)

  await page.goto(taskUrl(serviceTask.task_id, latest))
  for (const [label, value] of [
    ["Responsible unit", "Synthetic service owner"],
    ["Supporting evidence", "synthetic:service-inventory"],
    ["Actual service", "Synthetic HTTPS"],
    ["Business purpose", "Synthetic test only"],
    ["Access control", "Synthetic allowlist declaration"],
  ])
    await fill(label!, value!)
  await fill("Business role", "service_provider", true)
  await fill("External access need", "not_required", true)
  await page
    .getByLabel("Declared provider", { exact: true })
    .fill("Synthetic service provider")
  await page
    .getByLabel("Declared submission time (ISO 8601)", { exact: true })
    .fill("2000-01-01T00:00:00Z")
  latest = await save(latest)
  expect(
    (
      await get(
        `${reviews}/review-tasks/${encodeURIComponent(serviceTask.task_id)}?feedback_revision_id=${latest}`,
      )
    ).material.material_status,
  ).toBe("AWAITING_DEPENDENCY_MATERIAL")
  const sharedParent = latest
  const sharedPages = await fixedPages(sharedParent)
  await page.goto(taskUrl(exportTask.task_id, latest))
  for (const [label, value] of [
    ["Responsible unit", "Synthetic collector"],
    [
      "Supporting evidence",
      "synthetic:export-template\nsynthetic:collection-policy",
    ],
    ["Input timezone", "UTC"],
    ["Counter semantics", "Synthetic raw counters"],
    ["Export selection", "All synthetic fixture rows"],
    ["Direction semantics", "Synthetic SRC local; DST external"],
    ["TCP flags semantics", "Synthetic aggregated flags"],
  ])
    await fill(label!, value!)
  await answers
    .getByLabel("Sampling value state", { exact: true })
    .selectOption("value")
  await fill("Sampling mode", "unsampled", true)
  await fill("Sampling rate", "1")
  await fill("Observation view", "PUBLIC_EDGE", true)
  await page
    .getByLabel("Declared provider", { exact: true })
    .fill("Synthetic collector claim")
  await page
    .getByLabel("Declared submission time (ISO 8601)", { exact: true })
    .fill("2000-01-01T00:00:00Z")
  latest = await save(latest)
  for (const task of [exportTask, serviceTask]) {
    const item = await get(
      `${reviews}/review-tasks/${encodeURIComponent(task.task_id)}?feedback_revision_id=${latest}`,
    )
    expect(item.material).toMatchObject({
      material_status: "FIELDS_COMPLETE_PENDING_REVIEW",
      task_closed: false,
      facts_changed: false,
      review_required: true,
    })
  }
  expect(await fixedPages(sharedParent)).toEqual(sharedPages)
  const stale = await request.post(`/api/v1${reviews}/feedback`, {
    headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
    data: { expected_parent_id: partial, responses: [] },
  })
  expect(stale.status()).toBe(409)

  // This exact test-owned container is stopped; subsequent page reads use local versions.
  execFileSync("docker", ["stop", upstream], { stdio: "ignore" })
  const writes: string[] = []
  page.on("request", (item) => {
    if (!["GET", "HEAD", "OPTIONS"].includes(item.method()))
      writes.push(`${item.method()} ${new URL(item.url()).pathname}`)
  })
  await page.goto(
    `${root}/netflow-correlation?revision=${limitedRevision}&tab=summary`,
  )
  await expect(
    page.getByLabel("Source difference count", { exact: true }),
  ).toHaveText("Unavailable")
  await page.goto(
    `${root}/netflow-correlation?revision=${revision}&tab=summary`,
  )
  await expect(
    page.getByLabel("Source difference count", { exact: true }),
  ).toHaveText("37")
  for (const view of [
    {
      path: `${root}/netflow-results?analysis=${analysis}`,
      prefix: "processed",
    },
    {
      path: `${root}/netflow-correlation?revision=${revision}&tab=summary`,
      prefix: "workbench",
    },
  ]) {
    await page.goto(view.path)
    if (view.prefix === "processed")
      await expect(
        page.getByLabel("Observation objects", { exact: true }),
      ).toHaveText("30")
    else
      await expect(
        page.getByLabel("Source difference count", { exact: true }),
      ).toHaveText("37")
    for (const [width, language, theme] of [
      [1366, "en", "light"],
      [390, "en", "dark"],
      [1366, "zh-CN", "dark"],
      [390, "zh-CN", "light"],
    ] as const) {
      await page.setViewportSize({ width: 1366, height: 950 })
      await page
        .getByRole("combobox", { name: "Language / 语言" })
        .selectOption(language)
      await page.getByTestId("theme-button").click()
      await page.getByTestId(`${theme}-mode`).click()
      await expect(page.locator("html")).toHaveClass(new RegExp(theme))
      await expect(page.locator("html")).toHaveAttribute("lang", language)
      await page.setViewportSize({ width, height: 950 })
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        ),
      ).toBe(false)
      await page.screenshot({
        path: path.join(
          evidence,
          `${view.prefix}-${width}-${language}-${theme}.png`,
        ),
      })
    }
  }
  await page.setViewportSize({ width: 1366, height: 950 })
  await page
    .getByRole("combobox", { name: "Language / 语言" })
    .selectOption("en")
  await page
    .getByRole("button", { name: "Source differences", exact: true })
    .click()
  await expect(page).toHaveURL(/comparison=differences/)
  await expect(
    page.getByRole("button", { name: "192.0.2.26", exact: true }),
  ).toBeVisible()
  await page
    .getByRole("navigation", { name: "Addresses pagination" })
    .getByRole("button", { name: "Next", exact: true })
    .click()
  await expect(
    page.getByRole("button", { name: "192.0.2.38", exact: true }),
  ).toBeVisible()
  await page.getByRole("button", { name: "192.0.2.38", exact: true }).click()
  await expect(
    page
      .getByText("This IP has records in only some selected sources.", {
        exact: true,
      })
      .last(),
  ).toBeVisible()
  await page
    .getByRole("button", {
      name: "View evidence · CloudAtlas data",
      exact: true,
    })
    .click()
  await expect(page).toHaveURL(/evidenceSource=cloud/)
  await expect(
    page.getByRole("heading", { name: "Source evidence", exact: true }),
  ).toBeVisible()
  await page.getByRole("button", { name: "Summary", exact: true }).click()
  await page
    .getByRole("button", { name: "All selected sources present", exact: true })
    .click()
  await expect(
    page.getByRole("button", { name: "192.0.2.1", exact: true }),
  ).toBeVisible()
  await expect(
    page
      .getByRole("region", { name: "Address table", exact: true })
      .getByRole("row"),
  ).toHaveCount(2)
  await page.getByRole("button", { name: "Summary", exact: true }).click()
  await page.getByRole("button", { name: "All addresses", exact: true }).click()
  await page.goto(
    `${root}/netflow-correlation?revision=${revision}&tab=addresses`,
  )
  await page
    .getByRole("navigation", { name: "Addresses pagination" })
    .getByRole("button", { name: "Next", exact: true })
    .click()
  await expect(
    page.getByRole("button", { name: "192.0.2.26", exact: true }),
  ).toBeVisible()
  await page.getByLabel("Exact IP", { exact: true }).fill("192.0.2.1")
  await page.getByRole("button", { name: "Filter", exact: true }).click()
  await page.getByRole("button", { name: "192.0.2.1", exact: true }).click()
  await page
    .getByRole("navigation", { name: "Services pagination" })
    .getByRole("button", { name: "Next", exact: true })
    .click()
  await page
    .getByRole("button", { name: "Customer ledger", exact: true })
    .click()
  await page
    .getByRole("navigation", { name: "Evidence pagination" })
    .getByRole("button", { name: "Next", exact: true })
    .click()
  await page.reload()
  await expect(
    page.getByRole("region", { name: "Service material table" }),
  ).toBeVisible()
  expect(new URL(page.url()).searchParams.get("servicePage")).toBe("1")
  expect(new URL(page.url()).searchParams.get("evidencePage")).toBe("1")
  for (const width of [1366, 1920, 390]) {
    await page.setViewportSize({ width, height: 950 })
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
    ).toBe(false)
    await page.screenshot({ path: path.join(evidence, `netflow-${width}.png`) })
  }
  await page.keyboard.press("Tab")
  expect(await page.evaluate(() => document.activeElement?.tagName)).not.toBe(
    "BODY",
  )
  expect(
    await page.evaluate(
      () => matchMedia("(prefers-reduced-motion: reduce)").matches,
    ),
  ).toBe(true)
  expect(writes).toEqual([])

  for (const role of ["viewer", "operator"]) {
    const email = `synthetic-${role}-${crypto.randomUUID()}@example.com`,
      password = crypto.randomUUID()
    const user = await post("/users/", { email, password })
    await post(`${root}/memberships/`, { user_id: user.id, roles: [role] })
    const auth = await request.post("/api/v1/login/access-token", {
      form: { username: email, password },
    })
    const roleToken = (await auth.json()).access_token as string
    const roleContext = await browser.newContext({
      baseURL: process.env.PLAYWRIGHT_BASE_URL,
    })
    await roleContext.addInitScript((value) => {
      localStorage.setItem("access_token", value)
      localStorage.setItem("exposure:language", "en")
    }, roleToken)
    const rolePage = await roleContext.newPage()
    await rolePage.goto(`${root}/netflow-results?analysis=${analysis}`)
    await expect(
      rolePage.getByLabel("Observation objects", { exact: true }),
    ).toHaveText("30")
    await expect(
      rolePage.getByRole("button", {
        name: /Start .*analysis|Append correction|Reprocess/,
      }),
    ).toHaveCount(0)
    await rolePage.goto(taskUrl(exportTask.task_id, latest))
    if (role === "viewer")
      await expect(
        rolePage.getByRole("button", {
          name: "Append correction",
          exact: true,
        }),
      ).toBeDisabled()
    else
      await expect(
        rolePage.getByRole("button", {
          name: "Append correction",
          exact: true,
        }),
      ).toBeEnabled()
    const denied = await request.post(
      `/api/v1${root}/netflow-datasets/${dataset}/processing-contexts`,
      {
        headers: {
          Authorization: `Bearer ${roleToken}`,
          "Idempotency-Key": crypto.randomUUID(),
        },
        data: {
          expected_parent_id: null,
          network_namespace: "synthetic",
          state: "UNKNOWN",
          endpoint_selection: "declared_source",
          source_position_evidence: "Synthetic",
          nat_context: "unknown",
          nat_evidence: null,
          observation_point: { id: "synthetic", view: "UNKNOWN" },
          sampling: { mode: "unknown", rate: null },
        },
      },
    )
    expect(denied.status()).toBe(403)
    await roleContext.close()
  }
  await expect
    .poll(
      async () =>
        (
          await request.get(
            `/api/v1${root}/source-correlations/${expiring.correlation_revision_id}`,
            { headers },
          )
        ).status(),
      { timeout: 90_000 },
    )
    .toBe(410)
  expect((await get(`${root}/source-correlations`)).count).toBe(
    readableBeforeExpiry - 1,
  )
  expect(
    (await get(`${root}/source-correlations/${revision}`)).total_addresses,
  ).toBe(38)
  const other = await post("/projects/", {
    name: "Synthetic cross-project check",
  })
  expect(
    (
      await request.get(
        `/api/v1/projects/${other.id}/source-correlations/${revision}`,
        { headers },
      )
    ).status(),
  ).toBe(404)
  await page.goto(
    `${root}/netflow-correlation?revision=${revision}&namespace=conflicting`,
  )
  await expect(page.getByRole("alert")).toContainText("no latest fallback")
  await expect(page.getByRole("region", { name: "Address table" })).toHaveCount(
    0,
  )
  await page.goto(
    `${root}/netflow-correlation?revision=${revision}&tab=addresses`,
  )
  await expect(
    page.getByRole("region", { name: "Address table" }),
  ).toBeVisible()
  expect(
    (
      await request.patch(
        `/api/v1${root}/external-assets/sources/${source.id}`,
        { headers, data: { data_access_enabled: false } },
      )
    ).ok(),
  ).toBe(true)
  await expect(page.getByRole("alert")).toContainText("revoked", {
    timeout: 10_000,
  })
  await expect(page.getByRole("region", { name: "Address table" })).toHaveCount(
    0,
  )
  expect((await get(`${root}/source-correlations`)).count).toBe(1)
  await page.goto(`${root}/netflow-results?analysis=${analysis}`)
  await expect(
    page.getByLabel("Observation objects", { exact: true }),
  ).toHaveText("30")
  expect(writes).toEqual([])
  const hashes = (values: unknown[]) =>
    values.map((value) =>
      createHash("sha256").update(JSON.stringify(value)).digest("hex"),
    )
  await writeFile(
    path.join(evidence, "browser-result.json"),
    JSON.stringify(
      {
        status: "PASS",
        synthetic_only: true,
        project: project.id,
        dataset,
        analysis,
        revision,
        single_revision: singleRevision,
        partial_feedback: partial,
        shared_parent: sharedParent,
        latest_feedback: latest,
        fixed_page_hashes: hashes(sharedPages),
        browsing_writes: writes,
        comparison: summary.comparison,
        independent_browsing_writes: independentWrites,
        no_models: true,
      },
      null,
      2,
    ),
  )
})
