import { appendFileSync, mkdirSync, writeFileSync } from "node:fs"
import path from "node:path"
import {
  type APIRequestContext,
  expect,
  type Page,
  type Response,
  test,
} from "@playwright/test"

test.skip(
  process.env.RUN_NETFLOW_BULK_UI_E2E !== "1",
  "Use scripts/test-netflow-bulk-runtime.py for the isolated PostgreSQL, real bulk guest and API",
)

test.describe.configure({ mode: "serial" })

type Fixture = {
  label: string
  dataset_id: string
  context_revision_id: string
  input_bytes: number
  input_rows: number
  files?: number
}

type ProgressBody = {
  project_id: string
  analysis_id: string
  dataset_id: string
  context_revision_id: string
  network_namespace: string
  test_fixture: boolean
  provenance?: { backend?: string }
  status: string
  phase: string
  cancel_requested: boolean
  heartbeat_at: string | null
  lease_until: string | null
  files_completed: number
  files_total: number
  rows_normalized: number
}

type ProgressEvent = {
  at: string
  response_status: number
  url: string
  page_url: string
  body?: ProgressBody
  terminal: boolean
  error?: string
}

type TerminalFixture = { label: string; analysis_id: string }

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

function env(name: string): string {
  const value = process.env[name]
  if (!value) throw new Error(`Missing isolated UI input: ${name}`)
  return value
}

function optionalJson<T>(name: string): T | undefined {
  const value = process.env[name]
  if (!value) return undefined
  return JSON.parse(value) as T
}

function terminal(value: ProgressBody): boolean {
  if (
    value.status === "SUCCEEDED" ||
    value.status === "SUCCEEDED_WITH_WARNINGS"
  )
    return (
      value.phase === "SUCCEEDED" && value.files_completed === value.files_total
    )
  if (value.status === "FAILED")
    return value.phase === "FAILED" || value.phase === "CANCELLED"
  return false
}

function success(value: ProgressBody): boolean {
  return (
    terminal(value) &&
    (value.status === "SUCCEEDED" || value.status === "SUCCEEDED_WITH_WARNINGS")
  )
}

function statusLabel(status: string): string {
  return (
    {
      PENDING: "Waiting to run",
      RUNNING: "Running",
      SUCCEEDED: "Analysis completed",
      SUCCEEDED_WITH_WARNINGS: "Completed with coverage warnings",
      FAILED: "Failed; inspect the error before retrying",
      CANCELLED: "Cancelled",
    }[status] ?? status
  )
}

function progressPath(project: string, analysis: string): string {
  return `/api/v1/projects/${project}/netflow-bulk/analyses/${analysis}/progress`
}

function progressResponse(response: Response): boolean {
  const url = new URL(response.url())
  return /^\/api\/v1\/projects\/[^/]+\/netflow-bulk\/analyses\/[^/]+\/progress$/.test(
    url.pathname,
  )
}

async function until<T>(
  read: () => T | undefined,
  timeoutMs: number,
  message: string,
): Promise<T> {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    const value = read()
    if (value !== undefined) return value
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
  throw new Error(message)
}

type SettleResult = {
  waited_ms: number
  polls: number
  timed_out: boolean
  http_status: number | null
  terminal?: ProgressBody
  last?: ProgressBody
  error?: string
}

async function settleAfterMiss(
  request: APIRequestContext,
  token: string,
  project: string,
  analysisId: string,
  timeoutMs = 120_000,
): Promise<SettleResult> {
  const started = Date.now()
  let polls = 0
  let httpStatus: number | null = null
  let last: ProgressBody | undefined
  let error: string | undefined
  while (Date.now() - started < timeoutMs) {
    polls += 1
    try {
      const response = await request.get(progressPath(project, analysisId), {
        headers: { Authorization: `Bearer ${token}` },
        timeout: 15_000,
      })
      httpStatus = response.status()
      if (response.ok()) {
        const body = (await response.json()) as ProgressBody
        last = body
        if (terminal(body)) {
          return {
            waited_ms: Date.now() - started,
            polls,
            timed_out: false,
            http_status: httpStatus,
            terminal: body,
          }
        }
      }
    } catch (caught) {
      error = String(caught)
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
  return {
    waited_ms: Date.now() - started,
    polls,
    timed_out: true,
    http_status: httpStatus,
    last,
    error,
  }
}

async function settleAfterMissOrFail(
  attempt: Record<string, unknown>,
  request: APIRequestContext,
  token: string,
  project: string,
  analysisId: string,
): Promise<void> {
  const wait = await settleAfterMiss(request, token, project, analysisId)
  attempt.wait_before_retry = wait
  if (wait.timed_out)
    throw new Error(
      `missed attempt ${analysisId} did not reach a terminal state before retry`,
    )
}

async function login(request: APIRequestContext): Promise<string> {
  const response = await request.post("/api/v1/login/access-token", {
    form: {
      username: env("FIRST_SUPERUSER"),
      password: env("FIRST_SUPERUSER_PASSWORD"),
    },
  })
  expect(response.ok()).toBe(true)
  const value = (await response.json()) as { access_token?: unknown }
  if (typeof value.access_token !== "string")
    throw new Error("Login response did not contain an access token")
  return value.access_token
}

async function setupPage(page: Page, token: string): Promise<void> {
  await page.addInitScript((value) => {
    localStorage.setItem("access_token", value)
    localStorage.setItem("exposure:language", "en")
  }, token)
  await page.emulateMedia({ reducedMotion: "reduce" })
}

function recordProgress(page: Page, file: string) {
  mkdirSync(path.dirname(file), { recursive: true })
  const records: ProgressEvent[] = []
  let chain: Promise<void> = Promise.resolve()
  const handler = (response: Response) => {
    if (!progressResponse(response)) return
    const pageUrl = page.url()
    chain = chain
      .then(async () => {
        const url = new URL(response.url())
        let record: ProgressEvent
        try {
          const body = (await response.json()) as ProgressBody
          record = {
            at: new Date().toISOString(),
            response_status: response.status(),
            url: `${url.pathname}${url.search}`,
            page_url: pageUrl,
            body,
            terminal: terminal(body),
          }
        } catch (error) {
          record = {
            at: new Date().toISOString(),
            response_status: response.status(),
            url: url.pathname,
            page_url: pageUrl,
            terminal: false,
            error: String(error),
          }
        }
        records.push(record)
        appendFileSync(file, `${JSON.stringify(record)}\n`)
      })
      .catch(() => {})
  }
  page.on("response", handler)
  return {
    records,
    flush: () => chain,
    dispose: () => page.off("response", handler),
  }
}

async function startFromUi(
  page: Page,
  project: string,
  fixture: Fixture,
): Promise<{ response_status: number; analysis_id: string }> {
  await page.goto(
    `/?project=${project}&view=inputs&processing_dataset=${fixture.dataset_id}`,
  )
  const button = page.getByRole("button", {
    name: "Start selected context analysis",
    exact: true,
  })
  await expect(button).toBeVisible({ timeout: 60_000 })
  await expect(button).toBeEnabled()
  const responsePromise = page.waitForResponse(
    (response) => {
      if (response.request().method() !== "POST") return false
      const url = new URL(response.url())
      return (
        url.pathname ===
        `/api/v1/projects/${project}/netflow-datasets/${fixture.dataset_id}/analyses`
      )
    },
    { timeout: 60_000 },
  )
  await button.click()
  const response = await responsePromise
  expect([200, 202]).toContain(response.status())
  const value = (await response.json()) as { analysis_id?: unknown }
  if (typeof value.analysis_id !== "string" || !UUID.test(value.analysis_id))
    throw new Error("Start response did not contain a validated analysis id")
  return { response_status: response.status(), analysis_id: value.analysis_id }
}

test("real Results page shows an unfinished progress response, a later response, and terminal success", async ({
  page,
  request,
}) => {
  test.setTimeout(600_000)
  const fixture = optionalJson<Fixture>("NETFLOW_BULK_UI_SUCCESS")
  if (!fixture) {
    test.skip(true, "This scenario has no UI progress-success fixture")
    return
  }
  const evidence = env("NETFLOW_BULK_UI_EVIDENCE")
  const project = env("NETFLOW_BULK_UI_PROJECT")
  const token = await login(request)
  await setupPage(page, token)
  const eventsPath = path.join(evidence, "ui-progress-events.jsonl")
  const recorder = recordProgress(page, eventsPath)
  const region = page.getByRole("region", {
    name: "Processing progress",
    exact: true,
  })
  try {
    const started = await startFromUi(page, project, fixture)
    const resultsNavigatedAt = new Date().toISOString()
    await page.goto(
      `/projects/${project}/netflow-results?analysis=${started.analysis_id}&dataset=${fixture.dataset_id}`,
    )
    await expect(region).toBeVisible({ timeout: 60_000 })
    const first = await until(
      () =>
        recorder.records.find((event) => {
          const body = event.body
          return (
            event.at >= resultsNavigatedAt &&
            new URL(event.page_url).pathname ===
              `/projects/${project}/netflow-results` &&
            body !== undefined &&
            !event.terminal &&
            body.analysis_id === started.analysis_id &&
            body.dataset_id === fixture.dataset_id
          )
        }),
      120_000,
      "no unfinished Results-page progress response was observed",
    )
    await expect(region).toContainText("Progress status:", {
      timeout: 30_000,
    })
    await expect(region).not.toContainText("Analysis completed", {
      timeout: 10_000,
    })
    await expect(region).not.toContainText("Completed with coverage warnings", {
      timeout: 10_000,
    })
    const visibleFirst = await region.innerText()
    expect(visibleFirst).toContain("Progress status:")
    expect(visibleFirst).toContain("Files complete:")
    expect(first.response_status).toBe(200)
    const firstBody = first.body!
    expect(firstBody.project_id).toBe(project)
    expect(firstBody.analysis_id).toBe(started.analysis_id)
    expect(firstBody.dataset_id).toBe(fixture.dataset_id)
    expect(firstBody.context_revision_id).toBe(fixture.context_revision_id)
    expect(firstBody.provenance?.backend).toBe("netflow-bulk-v1")
    const firstIndex = recorder.records.indexOf(first)

    const currentResponse = await request.get(
      `/api/v1/projects/${project}/netflow-results/current`,
      { headers: { Authorization: `Bearer ${token}` } },
    )
    expect(currentResponse.ok()).toBe(true)
    const currentDuring = (await currentResponse.json()) as {
      current?: { analysis_id?: string }
    }

    const final = await until(
      () =>
        recorder.records.find((event, index) => {
          const body = event.body
          return (
            index > firstIndex &&
            body !== undefined &&
            event.terminal &&
            success(body) &&
            body.analysis_id === started.analysis_id
          )
        }),
      300_000,
      "no later terminal success progress response was observed",
    )
    expect(final.response_status).toBe(200)
    const finalBody = final.body!
    expect(finalBody.analysis_id).toBe(started.analysis_id)
    expect(finalBody.phase).toBe("SUCCEEDED")
    expect(finalBody.files_completed).toBe(finalBody.files_total)
    if (fixture.files !== undefined)
      expect(finalBody.files_total).toBe(fixture.files)
    expect(finalBody.heartbeat_at).not.toBeNull()
    await expect(region).toContainText("Phase: Analysis completed", {
      timeout: 300_000,
    })
    await expect(region).toContainText(
      `Files complete: ${finalBody.files_completed} / ${finalBody.files_total}`,
    )
    const visibleTerminal = await region.innerText()
    expect(visibleTerminal).toContain("Phase: Analysis completed")
    expect(visibleTerminal).not.toContain("Progress data did not match")
    expect(visibleTerminal).not.toContain("temporarily unavailable")

    await recorder.flush()
    writeFileSync(
      path.join(evidence, "ui-progress.json"),
      `${JSON.stringify(
        {
          status: "PASS",
          route_interception: false,
          fixture,
          analysis_id: started.analysis_id,
          start: started,
          events_path: path.relative(evidence, eventsPath),
          events: recorder.records,
          first_event: first,
          first_event_index: firstIndex,
          terminal_event: final,
          terminal_event_index: recorder.records.indexOf(final),
          current_while_running_analysis_id:
            currentDuring.current?.analysis_id ?? null,
          visible_first: visibleFirst,
          visible_terminal: visibleTerminal,
        },
        null,
        2,
      )}\n`,
    )
  } finally {
    recorder.dispose()
  }
})

test("real UI cancel observes a live lease, POST acknowledgement, requested and confirmed", async ({
  page,
  request,
}) => {
  test.setTimeout(900_000)
  const fixtures = optionalJson<Fixture[]>("NETFLOW_BULK_UI_CANCEL")
  if (!fixtures?.length) throw new Error("Missing cancel fixtures")
  const evidence = env("NETFLOW_BULK_UI_EVIDENCE")
  const project = env("NETFLOW_BULK_UI_PROJECT")
  const token = await login(request)
  await setupPage(page, token)
  const attempts: Record<string, unknown>[] = []
  let passed: Record<string, unknown> | undefined

  for (const fixture of fixtures) {
    const attemptDirectory = path.join(
      evidence,
      "ui-cancel-attempts",
      `${fixture.label}-${Date.now()}`,
    )
    mkdirSync(attemptDirectory, { recursive: true })
    const eventsPath = path.join(attemptDirectory, "progress-events.jsonl")
    const recorder = recordProgress(page, eventsPath)
    const region = page.getByRole("region", {
      name: "Processing progress",
      exact: true,
    })
    const attempt: Record<string, unknown> = {
      label: fixture.label,
      fixture,
      status: "MISSED",
      events_path: path.relative(evidence, eventsPath),
    }
    try {
      const started = await startFromUi(page, project, fixture)
      attempt.start = started
      attempt.analysis_id = started.analysis_id
      await expect(region).toBeVisible({ timeout: 60_000 })

      let liveState = "waiting"
      let live: ProgressEvent | undefined
      try {
        live = await until(
          () => {
            const lease = recorder.records.find((event) => {
              const body = event.body
              return (
                body?.status === "RUNNING" &&
                typeof body.lease_until === "string" &&
                body.analysis_id === started.analysis_id &&
                body.dataset_id === fixture.dataset_id &&
                body.context_revision_id === fixture.context_revision_id
              )
            })
            if (lease) {
              liveState = "lease"
              return lease
            }
            const done = recorder.records.find(
              (event) =>
                event.terminal &&
                event.body?.analysis_id === started.analysis_id,
            )
            if (done) {
              liveState = "terminal"
              return done
            }
            return undefined
          },
          60_000,
          "no live lease or terminal progress response was observed",
        )
      } catch (error) {
        attempt.reason = "live_lease_timeout"
        attempt.detail = String(error)
        await settleAfterMissOrFail(
          attempt,
          request,
          token,
          project,
          started.analysis_id,
        )
        continue
      }
      if (liveState !== "lease" || !live) {
        attempt.reason =
          liveState === "terminal"
            ? "terminal_before_live_lease"
            : "live_lease_not_observed"
        attempt.terminal_before_click = live
        if (liveState !== "terminal")
          await settleAfterMissOrFail(
            attempt,
            request,
            token,
            project,
            started.analysis_id,
          )
        continue
      }
      attempt.live_lease = live

      const currentResponse = await request.get(
        `/api/v1/projects/${project}/netflow-results/current`,
        { headers: { Authorization: `Bearer ${token}` } },
      )
      expect(currentResponse.ok()).toBe(true)
      const current = (await currentResponse.json()) as {
        current?: { analysis_id?: string }
      }
      attempt.current_while_running_analysis_id =
        current.current?.analysis_id ?? null

      const cancelButton = page.getByRole("button", {
        name: "Cancel bulk processing",
        exact: true,
      })
      await expect(cancelButton).toBeEnabled({ timeout: 30_000 })
      const cancelPromise = page.waitForResponse(
        (response) => {
          if (response.request().method() !== "POST") return false
          const url = new URL(response.url())
          return (
            url.pathname ===
            `/api/v1/projects/${project}/netflow-bulk/analyses/${started.analysis_id}/cancel`
          )
        },
        { timeout: 30_000 },
      )
      await cancelButton.click()
      const cancelResponse = await cancelPromise
      const acknowledgement = (await cancelResponse.json()) as {
        analysis_id?: unknown
        cancel_requested?: unknown
      }
      attempt.ack = {
        status: cancelResponse.status(),
        body: acknowledgement,
      }
      if (cancelResponse.status() !== 200)
        throw new Error("Cancel response did not return HTTP 200")
      if (acknowledgement.analysis_id !== started.analysis_id)
        throw new Error("Cancel response identity mismatch")
      if (acknowledgement.cancel_requested !== true) {
        attempt.reason = "ack_not_requested"
        await settleAfterMissOrFail(
          attempt,
          request,
          token,
          project,
          started.analysis_id,
        )
        continue
      }

      let requestedVisible = false
      try {
        await expect(region).toContainText("Cancellation requested", {
          timeout: 15_000,
        })
        requestedVisible = true
      } catch {
        requestedVisible = false
      }
      attempt.requested_visible = requestedVisible
      if (!requestedVisible) {
        attempt.reason = "requested_not_visible"
        attempt.visible_after_ack = await region.innerText()
        await settleAfterMissOrFail(
          attempt,
          request,
          token,
          project,
          started.analysis_id,
        )
        continue
      }
      attempt.visible_requested = await region.innerText()

      const terminalEvent = await until(
        () =>
          recorder.records.find(
            (event) =>
              event.body !== undefined &&
              event.terminal &&
              event.body.analysis_id === started.analysis_id,
          ),
        300_000,
        "cancellation terminal progress was not observed",
      )
      attempt.terminal = terminalEvent
      if (
        terminalEvent.body?.status !== "FAILED" ||
        terminalEvent.body.phase !== "CANCELLED"
      ) {
        attempt.reason = `terminal_${terminalEvent.body?.status ?? "unknown"}_${terminalEvent.body?.phase ?? "unknown"}`
        continue
      }

      let confirmedVisible = false
      try {
        await expect(region).toContainText("Processing cancelled", {
          timeout: 30_000,
        })
        confirmedVisible = true
      } catch {
        confirmedVisible = false
      }
      attempt.confirmed_visible = confirmedVisible
      if (!confirmedVisible) {
        attempt.reason = "confirmed_not_visible"
        attempt.visible_after_terminal = await region.innerText()
        continue
      }
      attempt.visible_confirmed = await region.innerText()
      attempt.status = "PASS"
      passed = attempt
      break
    } catch (error) {
      attempt.status = "ERROR"
      attempt.error = String(error)
      attempt.traceback = error instanceof Error ? error.stack : undefined
      throw error
    } finally {
      await recorder.flush()
      recorder.dispose()
      writeFileSync(
        path.join(attemptDirectory, "attempt.json"),
        `${JSON.stringify(attempt, null, 2)}\n`,
      )
      attempts.push(attempt)
    }
  }

  const result = passed
    ? { status: "PASS", route_interception: false, ...passed, attempts }
    : { status: "MISSED", route_interception: false, attempts }
  writeFileSync(
    path.join(evidence, "ui-cancel.json"),
    `${JSON.stringify(result, null, 2)}\n`,
  )
  if (!passed)
    throw new Error(
      "No live-lease UI cancellation was confirmed; attempt evidence is in ui-cancel-attempts/",
    )
})

test("real backend terminal progress is visibly the recorded observation", async ({
  page,
  request,
}) => {
  test.setTimeout(300_000)
  const fixtures = optionalJson<TerminalFixture[]>("NETFLOW_BULK_UI_TERMINAL")
  if (!fixtures?.length) {
    test.skip(true, "This scenario has no terminal UI fixture")
    return
  }
  const evidence = env("NETFLOW_BULK_UI_EVIDENCE")
  const project = env("NETFLOW_BULK_UI_PROJECT")
  const token = await login(request)
  await setupPage(page, token)
  const region = page.getByRole("region", {
    name: "Processing progress",
    exact: true,
  })
  const analyses: Record<string, unknown>[] = []
  for (const fixture of fixtures) {
    const recordedResponse = await request.get(
      progressPath(project, fixture.analysis_id),
      { headers: { Authorization: `Bearer ${token}` } },
    )
    expect(recordedResponse.status()).toBe(200)
    const recorded = (await recordedResponse.json()) as ProgressBody
    expect(recorded.analysis_id).toBe(fixture.analysis_id)
    expect(recorded.phase).toBe("SUCCEEDED")

    await page.goto(
      `/projects/${project}/netflow-results?analysis=${fixture.analysis_id}`,
    )
    await expect(region).toBeVisible({ timeout: 60_000 })
    const visible = await region.innerText()
    expect(visible).toContain(
      `Files complete: ${recorded.files_completed} / ${recorded.files_total}`,
    )
    expect(visible).toContain("Phase: Analysis completed")
    expect(visible).toContain(
      `Progress status: ${statusLabel(recorded.status)}`,
    )
    expect(visible).not.toContain("No heartbeat reported")
    expect(visible).not.toContain("Progress data did not match")
    expect(visible).not.toContain("temporarily unavailable")
    analyses.push({ label: fixture.label, recorded, visible })
  }
  writeFileSync(
    path.join(evidence, "ui-terminal.json"),
    `${JSON.stringify(
      {
        status: "PASS",
        route_interception: false,
        analyses,
      },
      null,
      2,
    )}\n`,
  )
})
