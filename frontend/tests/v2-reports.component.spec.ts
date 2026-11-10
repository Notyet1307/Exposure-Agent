import { expect, type Page, test } from "./fixtures"

const project = "00000000-0000-4000-8000-000000000298"
const result = "10000000-0000-4000-8000-000000000298"
const reportId = "20000000-0000-4000-8000-000000000298"
const upload = "30000000-0000-4000-8000-000000000298"
const version = "40000000-0000-4000-8000-000000000298"
const source = "50000000-0000-4000-8000-000000000298"
const root = `/api/v1/projects/${project}`
const ref = `core:${result}`
const countRef = `fact:${result}:counts`
const addressKey = `addr:${"a".repeat(64)}`
const summary = {
  contract_version: "core-comparison-v2",
  project_id: project,
  id: result,
  scope_key: "a".repeat(64),
  purpose: "regular",
  rule_version: "canonical-ip-presence-v1",
  status: "PUBLISHED",
  published_at: "2026-10-08T00:00:00Z",
  created_at: "2026-10-08T00:00:00Z",
  customer_filename: "synthetic.xlsx",
  source_name: "Synthetic source",
  input_sha256: "b".repeat(64),
  selection: {
    network_namespace: "synthetic",
    customer: { upload_id: upload, revision_id: null },
    cloud: {
      kind: "external_versions",
      source_instance_id: source,
      ip_version_id: version,
      port_version_id: null,
    },
    netflow: null,
    history_run_id: null,
  },
  pins: { CLOUD: { domains: {} } },
  sources: [],
  comparison_state: "AVAILABLE",
  total_addresses: 3,
  both: 1,
  cloud_only: 1,
  customer_only: 1,
}

const text = {
  summary: ["fixed", "check"],
  sections: [
    "conclusion",
    "differences",
    "priority",
    "netflow",
    "next_steps",
    "appendix",
  ].map((id) => ({
    id,
    claim_ids: id === "conclusion" || id === "appendix" ? ["fixed"] : ["check"],
  })),
  claims: [
    { id: "fixed", type: "fact", fact_refs: [countRef], evidence_refs: [ref] },
    {
      id: "check",
      type: "action",
      text: "Verify the registration and collection scope for this discrepancy.",
      fact_refs: [],
      evidence_refs: [ref],
    },
  ],
  priority_cases: [],
  limitations: ["The actual observation window was not provided."],
}
const initialReport = {
  subject_kind: "core_comparison_v2",
  result_id: result,
  supplement_binding_id: null,
  audience: "management",
  language: "en",
  address_key: null,
  id: reportId,
  project_id: project,
  status: "DRAFT",
  revision: 1,
  created_at: "2026-10-08T00:00:00Z",
  completed_at: "2026-10-08T00:01:00Z",
  edited_at: null,
  confirmed_at: null,
  created_by_id: "synthetic-user",
  edited_by_id: null,
  confirmed_by_id: null,
  connection_version_id: null,
  config_fingerprint: "c".repeat(64),
  material_sha256: "d".repeat(64),
  failure_code: null,
  readable: true,
  unavailable_reason: null,
  materials_changed: false,
  valid_until: null,
  original_output: { contract_version: "v2-ai-output-v1", text },
  text,
  material: {
    captured_at: "2026-10-08T00:00:00Z",
    subject: {
      result_id: result,
      supplement_binding_id: null,
      address_key: null,
    },
    identity: {
      pins: {
        CUSTOMER: { upload_id: upload, revision_id: null, profile_version: 1 },
        CLOUD: {
          domains: { ip: { id: version, fetched_at: "2026-10-08T00:00:00Z" } },
        },
      },
    },
    summary,
    facts: {
      [countRef]: { kind: "counts", value: summary, evidence_refs: [ref] },
    },
    items: [
      { citation_id: ref, kind: "CORE_RESULT", identity: result, data: {} },
    ],
    samples: [],
    coverage: {
      sampled_addresses: 0,
      eligible_addresses: 3,
      omitted_addresses: 3,
      omitted_source_records: 0,
    },
    limitations: text.limitations,
  },
}

async function serve(
  page: Page,
  stateName = "READY",
  saved = false,
  paged = false,
) {
  const state = {
    report: structuredClone(initialReport),
    saved,
    unreadable: false,
    unavailableReason: "v2_report_material_expired" as string | null,
    detailUnreadable: false,
    detailUnavailableReason: "v2_report_material_expired" as string | null,
    createCalls: 0,
    patchCalls: 0,
    confirmCalls: 0,
    readCalls: 0,
    bodies: [] as object[],
    keys: [] as string[],
    loseReply: false,
    failDetail: 0,
    failList: 0,
    failHistory: 0,
    failNextDetail: 0,
    failDetailBody: null as unknown,
    failListBody: null as unknown,
    patchStatus: 0,
    patchBody: null as unknown,
    confirmStatus: 0,
    confirmBody: null as unknown,
    nextDetailId: null as string | null,
    historyPaths: [] as string[],
    detailId: null as string | null,
    detailText: null as string | null,
    patchId: null as string | null,
    confirmId: null as string | null,
    listUnreadable: false,
    listUnavailableReason: "v2_report_material_expired" as string | null,
    detailPaths: [] as string[],
    pageIds: [] as string[],
    reportsById: null as Record<string, typeof initialReport> | null,
    gateDetail: null as null | {
      id: string
      gate: Promise<void>
      status: number
    },
    gateHits: 0,
    gateFulfilled: 0,
    gateHistory: null as null | {
      gate: Promise<void>
      status: number
    },
    gateHistoryHits: 0,
    gateHistoryFulfilled: 0,
    gatePrintDetail: null as null | {
      id: string
      gate: Promise<void>
      status: number
    },
    printGateHits: 0,
    printGateFulfilled: 0,
    printGatePath: null as string | null,
  }
  if (paged) {
    state.saved = true
    state.pageIds = Array.from(
      { length: 26 },
      (_, index) =>
        `21000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
    )
    state.reportsById = Object.fromEntries(
      state.pageIds.map((id, index) => {
        const report = structuredClone(initialReport)
        report.id = id
        report.text.claims[1].text = `Body for version ${index + 1}`
        return [id, report]
      }),
    )
  }
  const reportValue = (id = reportId, override = false) => {
    const base =
      (state.reportsById ? state.reportsById[id] : undefined) ?? state.report
    if (!override) return base
    const identified = state.detailId ? { ...base, id: state.detailId } : base
    if (!state.detailText || !identified.text) return identified
    return {
      ...identified,
      text: {
        ...identified.text,
        claims: identified.text.claims.map((claim) =>
          claim.id === "check" ? { ...claim, text: state.detailText! } : claim,
        ),
      },
    }
  }
  const value = (id = reportId, override = false) => {
    const report = reportValue(id, override)
    if (state.unreadable)
      return {
        ...report,
        readable: false,
        unavailable_reason: state.unavailableReason,
        text: null,
        original_output: null,
        material: null,
      }
    return report
  }
  await page.addInitScript(() => {
    // Re-seeding would fake a logged-in document after the client logout.
    if (sessionStorage.getItem("component-auth-seeded") !== null) return
    localStorage.setItem("access_token", "synthetic-component-token")
    sessionStorage.setItem("component-auth-seeded", "1")
  })
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(),
      url = new URL(request.url()),
      path = url.pathname
    if (path === "/api/v1/users/me")
      return route.fulfill({
        json: {
          id: "synthetic-user",
          email: "synthetic@example.com",
          is_active: true,
          is_superuser: true,
        },
      })
    if (path === "/api/v1/projects/")
      return route.fulfill({
        json: {
          data: [
            { id: project, name: "Synthetic V2 project", status: "active" },
          ],
          count: 1,
        },
      })
    if (path === `${root}/comparison-results/${result}/summary`)
      return route.fulfill({ json: summary })
    if (path === `${root}/comparison-results/${result}/updates`)
      return route.fulfill({
        json: {
          contract_version: "core-comparison-v2",
          project_id: project,
          result_id: result,
          state: "UNCHANGED",
        },
      })
    if (path === `${root}/comparison-results/${result}/addresses`)
      return route.fulfill({
        json: {
          contract_version: "core-comparison-v2",
          project_id: project,
          result_id: result,
          total_addresses: 3,
          data: [],
          count: 0,
        },
      })
    if (path === `${root}/comparison-results/${result}/addresses/${addressKey}`)
      return route.fulfill({
        json: {
          contract_version: "core-comparison-v2",
          project_id: project,
          result_id: result,
          address: {
            address_key: addressKey,
            canonical_ip: "192.0.2.10",
            classification: "cloud_only",
            customer_records: 0,
            cloud_records: 1,
            presence: {},
          },
        },
      })
    if (
      path ===
      `${root}/comparison-results/${result}/addresses/${addressKey}/evidence`
    )
      return route.fulfill({
        json: {
          contract_version: "core-comparison-v2",
          project_id: project,
          result_id: result,
          address_key: addressKey,
          source: url.searchParams.get("source") ?? "customer",
          data: [],
          count: 0,
          skip: 0,
          limit: 25,
        },
      })
    if (path === `${root}/analysis-reports/v2/readiness`)
      return route.fulfill({
        json: {
          project_id: project,
          result_id: result,
          supplement_binding_id: null,
          state: stateName,
          can_create: stateName === "READY",
        },
      })
    if (path === `${root}/analysis-reports/v2`) {
      if (request.method() === "POST") {
        state.createCalls++
        state.bodies.push(request.postDataJSON())
        state.keys.push(request.headers()["idempotency-key"])
        state.saved = true
        if (state.loseReply) {
          state.loseReply = false
          return route.abort("connectionfailed")
        }
        return route.fulfill({ status: 201, json: value(reportId, true) })
      }
      if (state.failList)
        return route.fulfill({
          status: state.failList,
          json: state.failListBody ?? {
            detail: { code: "synthetic_list_failure", message: "synthetic" },
          },
        })
      if (state.reportsById) {
        const skip = Number(url.searchParams.get("skip") ?? "0")
        const limit = Number(url.searchParams.get("limit") ?? "25")
        const ids = state.pageIds.slice(skip, skip + limit)
        return route.fulfill({
          json: {
            data: ids.map((id) => ({
              ...value(id),
              text: null,
              original_output: null,
              material: null,
            })),
            count: state.pageIds.length,
            can_create: stateName === "READY",
          },
        })
      }
      const rows = state.saved
        ? [
            {
              ...value(),
              text: null,
              original_output: null,
              material: null,
            },
          ]
        : []
      if (state.listUnreadable && rows[0]) {
        rows[0] = {
          ...rows[0],
          readable: false,
          unavailable_reason: state.listUnavailableReason,
        }
      }
      return route.fulfill({
        json: {
          data: rows,
          count: rows.length,
          can_create: stateName === "READY",
        },
      })
    }
    if (path.startsWith(`${root}/analysis-reports/v2/operations/`))
      return route.fulfill({ json: value(reportId, true) })
    if (path === `${root}/analysis-reports/v2/${reportId}/confirm`) {
      state.confirmCalls++
      if (state.confirmStatus)
        return route.fulfill({
          status: state.confirmStatus,
          json: state.confirmBody ?? {
            detail: { code: "synthetic_confirm_failure", message: "synthetic" },
          },
        })
      state.report.status = "CONFIRMED"
      state.report.revision++
      state.report.confirmed_at = "2026-10-08T00:02:00Z"
      return route.fulfill({
        json: { ...value(reportId, true), id: state.confirmId ?? reportId },
      })
    }
    if (
      path.startsWith(`${root}/analysis-reports/v2/`) &&
      path.endsWith("/revisions")
    ) {
      state.historyPaths.push(path)
      if (state.failHistory)
        return route.fulfill({
          status: state.failHistory,
          json: {
            detail: {
              code: "synthetic_history_failure",
              message: "synthetic",
            },
          },
        })
      if (state.gateHistory) {
        state.gateHistoryHits++
        await state.gateHistory.gate
        await route.fulfill({
          status: state.gateHistory.status,
          json: {
            detail: {
              code: "synthetic_history_failure",
              message: "synthetic",
            },
          },
        })
        state.gateHistoryFulfilled++
        return
      }
      return route.fulfill({ json: [] })
    }
    if (path.startsWith(`${root}/analysis-reports/v2/`)) {
      const id = path.slice(`${root}/analysis-reports/v2/`.length)
      if (request.method() === "PATCH" && id === reportId) {
        state.patchCalls++
        if (state.patchStatus)
          return route.fulfill({
            status: state.patchStatus,
            json: state.patchBody ?? {
              detail: { code: "synthetic_patch_failure", message: "synthetic" },
            },
          })
        state.report.revision++
        const body = request.postDataJSON()
        state.report.text = structuredClone(state.report.text)
        state.report.text.claims[1].text = body.edits.check
        return route.fulfill({
          json: { ...value(reportId, true), id: state.patchId ?? reportId },
        })
      }
      state.detailPaths.push(path)
      state.readCalls++
      if (state.failDetail)
        return route.fulfill({
          status: state.failDetail,
          json: state.failDetailBody ?? {
            detail: { code: "synthetic_read_failure", message: "synthetic" },
          },
        })
      if (state.failNextDetail) {
        state.failNextDetail = 0
        return route.fulfill({
          status: 503,
          json: {
            detail: { code: "synthetic_next_failure", message: "synthetic" },
          },
        })
      }
      const printGate = state.gatePrintDetail
      if (
        printGate &&
        printGate.id === id &&
        request.headers()["x-test-print-read"] === "1"
      ) {
        state.printGateHits++
        state.printGatePath = path
        await printGate.gate
        state.printGateFulfilled++
        if (printGate.status !== 200)
          return route.fulfill({
            status: printGate.status,
            json: {
              detail: { code: "synthetic_gate_failure", message: "synthetic" },
            },
          })
      }
      let gated = false
      if (state.gateDetail && state.gateDetail.id === id) {
        gated = true
        state.gateHits++
        await state.gateDetail.gate
        if (state.gateDetail.status !== 200) {
          await route.fulfill({
            status: state.gateDetail.status,
            json: {
              detail: { code: "synthetic_gate_failure", message: "synthetic" },
            },
          })
          state.gateFulfilled++
          return
        }
      }
      if (state.reportsById && !state.reportsById[id])
        return route.fulfill({
          status: 404,
          json: { detail: "Analysis report not found" },
        })
      if (!state.reportsById && id !== reportId)
        return route.fulfill({
          status: 404,
          json: { detail: "Analysis report not found" },
        })
      if (state.nextDetailId) {
        const injected = state.nextDetailId
        state.nextDetailId = null
        await route.fulfill({
          json: { ...value(id, true), id: injected },
        })
        if (gated) state.gateFulfilled++
        return
      }
      const report = value(id, true)
      await route.fulfill({
        json: state.detailUnreadable
          ? {
              ...report,
              readable: false,
              unavailable_reason: state.detailUnavailableReason,
              text: null,
              original_output: null,
              material: null,
            }
          : report,
      })
      if (gated) state.gateFulfilled++
      return
    }
    return route.fulfill({ json: { data: [], count: 0, can_manage: false } })
  })
  return state
}

const deferred = () => {
  let release = () => {}
  const promise = new Promise<void>((resolve) => {
    release = resolve
  })
  return { promise, release }
}

async function installPrintWindow(page: Page) {
  await page.addInitScript(() => {
    window.print = () => {
      document.body.dataset.printCalls = String(
        Number(document.body.dataset.printCalls ?? 0) + 1,
      )
    }
  })
}

// Marks the next detail GET sent after the Print click with a test-only header.
// The manual print read and the 5s detail poll share a URL, so the route must
// gate the marked request instead of guessing which GET came first.
async function installPrintRequestMarker(page: Page) {
  await page.addInitScript(() => {
    const marker = { armed: false, marked: 0, paths: [] as string[] }
    ;(
      window as unknown as { __printRequestMarker: typeof marker }
    ).__printRequestMarker = marker
    // Arm during the capture phase of the click, before React runs the handler.
    // The manual read is sent in the following microtask, so no timer task can
    // slip between the click and the marked request.
    document.addEventListener(
      "click",
      (event) => {
        const target = event.target
        if (!(target instanceof Element)) return
        const button = target.closest("button")
        if (button?.textContent?.includes("Print report")) marker.armed = true
      },
      true,
    )
    const prototype = XMLHttpRequest.prototype
    const nativeOpen = prototype.open
    const nativeSend = prototype.send
    prototype.open = function (
      this: XMLHttpRequest,
      method: string,
      url: string | URL,
      ...rest: unknown[]
    ) {
      ;(this as unknown as { __testOpen?: [string, string] }).__testOpen = [
        String(method).toUpperCase(),
        String(url),
      ]
      return Reflect.apply(nativeOpen, this, [method, url, ...rest])
    } as typeof prototype.open
    prototype.send = function (this: XMLHttpRequest, ...args: unknown[]) {
      const opened = (this as unknown as { __testOpen?: [string, string] })
        .__testOpen
      const path = opened ? new URL(opened[1], location.href).pathname : ""
      if (
        marker.armed &&
        opened?.[0] === "GET" &&
        /\/analysis-reports\/v2\/[^/]+$/.test(path)
      ) {
        marker.armed = false
        marker.marked += 1
        marker.paths.push(path)
        this.setRequestHeader("x-test-print-read", "1")
      }
      return Reflect.apply(nativeSend, this, args)
    } as typeof prototype.send
  })
}

// Holds the render-before-print RAF pair until the test flushes it, so a
// refusal can be delivered deterministically between GET success and print.
async function installPrintRafHold(page: Page) {
  await page.addInitScript(() => {
    const hold = {
      armed: false,
      queue: [] as FrameRequestCallback[],
      nextId: 1,
    }
    ;(window as unknown as { __printRafHold: typeof hold }).__printRafHold =
      hold
    const native = window.requestAnimationFrame.bind(window)
    window.requestAnimationFrame = (callback) => {
      if (hold.armed) {
        hold.queue.push(callback)
        return hold.nextId++
      }
      return native(callback)
    }
    ;(window as unknown as { __flushPrintRaf: () => number }).__flushPrintRaf =
      () => {
        const callbacks = hold.queue
        hold.queue = []
        callbacks.forEach((callback) => {
          callback(performance.now())
        })
        return callbacks.length
      }
  })
}

const open = (page: Page) =>
  page.goto(
    `/projects/${project}/netflow-correlation?result=${result}&binding=none`,
  )

test("one explicit generation supplies summary/full report; editing and confirmation stay distinct", async ({
  page,
}) => {
  const state = await serve(page)
  await open(page)
  const panel = page.getByRole("region", {
    name: "AI interpretation for this comparison",
  })
  await expect(
    panel.getByRole("button", {
      name: "Generate AI interpretation report",
      exact: true,
    }),
  ).toBeEnabled()
  expect(state.createCalls).toBe(0)
  await panel
    .getByRole("button", {
      name: "Generate AI interpretation report",
      exact: true,
    })
    .click()
  await expect(
    panel.getByText("Draft; review required", { exact: true }),
  ).toBeVisible()
  expect(state.createCalls).toBe(1)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  await expect(
    panel.getByRole("heading", {
      name: "This comparison's conclusion",
      exact: true,
    }),
  ).toBeVisible()
  expect(state.createCalls).toBe(1)
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  await panel
    .getByLabel("Interpretation · check", { exact: true })
    .fill(
      "Verify the declared owner and collection scope before changing the conclusion.",
    )
  await panel
    .getByRole("button", { name: "Save report revision", exact: true })
    .click()
  await expect.poll(() => state.patchCalls).toBe(1)
  expect(state.confirmCalls).toBe(0)
  await panel
    .getByRole("button", { name: "Confirm this report version", exact: true })
    .click()
  await expect(
    panel.getByText("Confirmed report version", { exact: true }),
  ).toBeVisible()
  expect(state.confirmCalls).toBe(1)
  expect(state.createCalls).toBe(1)
  const sent = state.bodies[0] as Record<string, unknown>
  expect(sent.result_id).toBe(result)
  expect(sent.supplement_binding_id).toBeNull()
  expect(sent).not.toHaveProperty("run_id")
})

for (const stateName of [
  "NOT_CONFIGURED",
  "NOT_ENABLED",
  "NOT_QUALIFIED",
  "MATERIAL_UNAVAILABLE",
  "NO_PERMISSION",
]) {
  test(`unavailable generation state ${stateName} keeps fixed core readable`, async ({
    page,
  }) => {
    const state = await serve(page, stateName)
    await open(page)
    await expect(
      page.getByRole("button", {
        name: "Generate AI interpretation report",
        exact: true,
      }),
    ).toBeDisabled()
    await expect(
      page
        .getByRole("region", { name: "Core classification" })
        .getByRole("button", { name: /All addresses 3/ }),
    ).toBeVisible()
    expect(state.createCalls).toBe(0)
  })
}

test("lost creation reply recovers the original receipt without a second generation", async ({
  page,
}) => {
  const state = await serve(page)
  state.loseReply = true
  await open(page)
  const panel = page.getByRole("region", {
    name: "AI interpretation for this comparison",
  })
  await panel
    .getByRole("button", {
      name: "Generate AI interpretation report",
      exact: true,
    })
    .click()
  await panel
    .getByRole("button", { name: "Read original report receipt", exact: true })
    .click()
  await expect(
    panel.getByText("Draft; review required", { exact: true }),
  ).toBeVisible()
  expect(state.createCalls).toBe(1)
})

test("an exact fixed address exposes its explanation without an automatic model request", async ({
  page,
}) => {
  const state = await serve(page)
  await page.goto(
    `/projects/${project}/netflow-correlation?result=${result}&binding=none&core_address=${addressKey}`,
  )
  const panel = page.getByRole("region", {
    name: "Explain this difference",
  })
  await expect(
    panel.getByRole("button", {
      name: "Generate this explanation",
      exact: true,
    }),
  ).toBeEnabled()
  expect(state.createCalls).toBe(0)
})

test("printing reauthorizes and rejects an unreadable report without using cached prose", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await page.addInitScript(() => {
    window.print = () => {
      document.body.dataset.printCalls = String(
        Number(document.body.dataset.printCalls ?? 0) + 1,
      )
    }
  })
  await open(page)
  const panel = page.getByRole("region", {
    name: "AI interpretation for this comparison",
  })
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  const before = state.readCalls
  state.unreadable = true
  await panel.getByRole("button", { name: "Print report", exact: true }).click()
  await expect(
    panel.getByRole("alert").filter({ hasText: "reauthorized" }),
  ).toBeVisible()
  expect(state.readCalls).toBeGreaterThan(before)
  expect(
    await page.evaluate(() => document.body.dataset.printCalls),
  ).toBeUndefined()
  expect(state.createCalls).toBe(0)
  await expect(
    panel.getByText(
      "Verify the registration and collection scope for this discrepancy.",
      { exact: true },
    ),
  ).toHaveCount(0)
})

const v2Panel = (page: Page) =>
  page.getByRole("region", {
    name: "AI interpretation for this comparison",
  })

test("temporary detail failure is temporary, retains unsaved edits and re-reads the same report", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  const editor = panel.getByLabel("Interpretation · check", { exact: true })
  await editor.fill("Temporary failure keeps this unsaved text.")
  state.failDetail = 503
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  const temporary = panel.getByRole("alert").filter({ hasText: "temporarily" })
  await expect(temporary).toBeVisible()
  await expect(temporary).not.toContainText("permissions")
  await expect(temporary).not.toContainText("expired")
  await expect(editor).toHaveCount(0)
  expect(state.createCalls).toBe(0)
  state.failDetail = 0
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  await expect(editor).toBeVisible()
  await expect(editor).toHaveValue("Temporary failure keeps this unsaved text.")
  await panel
    .getByRole("button", { name: "Save report revision", exact: true })
    .click()
  await expect.poll(() => state.patchCalls).toBe(1)
  expect(state.createCalls).toBe(0)
  expect(state.detailPaths.every((path) => path.endsWith(`/${reportId}`))).toBe(
    true,
  )
})

test("temporary report list failure keeps unsaved edits and restores them after re-read", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  const editor = panel.getByLabel("Interpretation · check", { exact: true })
  await editor.fill("Temporary list failure keeps this edit.")
  state.failList = 503
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  const temporary = panel.getByRole("alert").filter({ hasText: "temporarily" })
  await expect(temporary).toBeVisible()
  await expect(temporary).not.toContainText("permissions")
  await expect(editor).toHaveCount(0)
  expect(state.createCalls).toBe(0)
  state.failList = 0
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  await expect(panel.getByLabel("Saved report version")).toHaveValue(reportId)
  await expect(editor).toBeVisible()
  await expect(editor).toHaveValue("Temporary list failure keeps this edit.")
  expect(state.createCalls).toBe(0)
})

test("temporary revision history failure keeps the fixed report body and unsaved edits", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  state.failHistory = 503
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  const temporary = panel.getByRole("alert").filter({ hasText: "temporarily" })
  await expect(temporary).toBeVisible()
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  const editor = panel.getByLabel("Interpretation · check", { exact: true })
  await editor.fill("Temporary history failure keeps this edit.")
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  await expect(temporary).toBeVisible()
  await expect(editor).toBeVisible()
  await expect(editor).toHaveValue("Temporary history failure keeps this edit.")
  await expect(
    panel
      .getByText(
        "Verify the registration and collection scope for this discrepancy.",
        {
          exact: true,
        },
      )
      .first(),
  ).toBeVisible()
  expect(state.createCalls).toBe(0)
  state.failHistory = 0
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  await expect(temporary).toHaveCount(0)
  await expect(panel.getByLabel("Saved report version")).toHaveValue(reportId)
  await expect(editor).toHaveValue("Temporary history failure keeps this edit.")
  expect(state.createCalls).toBe(0)
})

test("404 read failure is distinct from expired and says not found or unauthorized", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  await panel
    .getByLabel("Interpretation · check", { exact: true })
    .fill("This edit must be cleared by an explicit refusal.")
  state.failDetail = 404
  state.failDetailBody = { detail: "Analysis report not found" }
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  const notFound = panel
    .getByRole("alert")
    .filter({ hasText: "not found, or this account is not authorized" })
  await expect(notFound).toBeVisible()
  await expect(notFound).not.toContainText("expired")
  await expect(
    panel.getByLabel("Interpretation · check", { exact: true }),
  ).toHaveCount(0)
  state.failDetail = 0
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  await expect(
    panel
      .getByText(
        "Verify the registration and collection scope for this discrepancy.",
        { exact: true },
      )
      .first(),
  ).toBeVisible()
  await expect(
    panel.getByLabel("Interpretation · check", { exact: true }),
  ).toHaveCount(0)
  expect(state.createCalls).toBe(0)
  expect(state.detailPaths.every((path) => path.endsWith(`/${reportId}`))).toBe(
    true,
  )
})

test("410 read failure is shown as expired, not as not found", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await open(page)
  const panel = v2Panel(page)
  state.failDetail = 410
  state.failDetailBody = {
    detail: {
      code: "v2_report_material_expired",
      message: "fixed material expired",
    },
  }
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  const expired = panel.getByRole("alert").filter({ hasText: "expired" })
  await expect(expired).toBeVisible()
  await expect(expired).not.toContainText("not found")
  await expect(
    panel.getByText(
      "Verify the registration and collection scope for this discrepancy.",
      { exact: true },
    ),
  ).toHaveCount(0)
  expect(state.createCalls).toBe(0)
})

for (const [reason, expected] of [
  ["v2_report_material_expired", "fixed material period has expired"],
  ["v2_report_material_unavailable", "no longer available"],
  ["v2_report_material_invalid", "failed its integrity check"],
  [null, "explicitly unreadable"],
] as const) {
  test(`unreadable report reason ${reason ?? "unknown"} has a distinct message`, async ({
    page,
  }) => {
    const state = await serve(page, "READY", true)
    state.unreadable = true
    state.unavailableReason = reason
    await open(page)
    const panel = v2Panel(page)
    await expect(
      panel.getByRole("alert").filter({ hasText: expected }),
    ).toBeVisible()
    await expect(
      panel.getByText(
        "This report is unreadable under its fixed material permissions or cutoff.",
      ),
    ).toHaveCount(0)
    await expect(
      panel.getByText(
        "Verify the registration and collection scope for this discrepancy.",
        { exact: true },
      ),
    ).toHaveCount(0)
    expect(state.createCalls).toBe(0)
  })
}

test("authorization denial clears content and edits without redirecting", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  await panel
    .getByLabel("Interpretation · check", { exact: true })
    .fill("Authorization denial must clear this text.")
  state.failDetail = 403
  state.failDetailBody = {
    detail: { code: "project_role_denied", message: "Operator role required" },
  }
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  const denied = panel
    .getByRole("alert")
    .filter({ hasText: "not allowed to read" })
  await expect(denied).toBeVisible()
  await expect(page).not.toHaveURL(/\/login/)
  await expect(
    panel.getByRole("region", { name: "Fixed comparison facts" }),
  ).toHaveCount(0)
  await expect(
    panel.getByLabel("Interpretation · check", { exact: true }),
  ).toHaveCount(0)
  state.failDetail = 0
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  await expect(
    panel
      .getByText(
        "Verify the registration and collection scope for this discrepancy.",
        { exact: true },
      )
      .first(),
  ).toBeVisible()
  await expect(
    panel.getByLabel("Interpretation · check", { exact: true }),
  ).toHaveCount(0)
  expect(state.createCalls).toBe(0)
})

for (const [status, detail] of [
  [401, "Not authenticated"],
  [403, "Could not validate credentials"],
] as const) {
  test(`authentication failure ${status} ${detail} follows the client redirect`, async ({
    page,
  }) => {
    const state = await serve(page, "READY", true)
    state.failDetail = status
    state.failDetailBody = { detail }
    await open(page)
    await expect(page).toHaveURL(/\/login/)
    expect(
      await page.evaluate(() => localStorage.getItem("access_token")),
    ).toBeNull()
    await page.reload()
    await expect(page).toHaveURL(/\/login/)
    await expect(page.getByTestId("email-input")).toBeVisible()
    expect(
      await page.evaluate(() => localStorage.getItem("access_token")),
    ).toBeNull()
    expect(state.createCalls).toBe(0)
  })
}

test("unknown read failure is generic, does not claim permission or expiry, and retains edits", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  const editor = panel.getByLabel("Interpretation · check", { exact: true })
  await editor.fill("An unknown failure keeps my unsaved text.")
  state.failDetail = 418
  state.failDetailBody = { detail: "synthetic unknown failure" }
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  const unknown = panel
    .getByRole("alert")
    .filter({ hasText: "cause is unknown" })
  await expect(unknown).toBeVisible()
  await expect(unknown).not.toContainText("permission")
  await expect(unknown).not.toContainText("expired")
  state.failDetail = 0
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  await expect(editor).toBeVisible()
  await expect(editor).toHaveValue("An unknown failure keeps my unsaved text.")
  expect(state.createCalls).toBe(0)
})

test("an inactive account 400 is an explicit refusal and clears content and edits", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  await panel
    .getByLabel("Interpretation · check", { exact: true })
    .fill("Inactive account must clear this edit.")
  state.failDetail = 400
  state.failDetailBody = { detail: "Inactive user" }
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  const inactive = panel
    .getByRole("alert")
    .filter({ hasText: "This account is inactive" })
  await expect(inactive).toBeVisible()
  await expect(inactive).not.toContainText("not allowed to read")
  await expect(inactive).not.toContainText("temporarily")
  await expect(
    panel.getByLabel("Interpretation · check", { exact: true }),
  ).toHaveCount(0)
  await expect(
    panel
      .getByText(
        "Verify the registration and collection scope for this discrepancy.",
        {
          exact: true,
        },
      )
      .first(),
  ).toHaveCount(0)
  await expect(
    panel.getByRole("button", { name: "Edit interpretation", exact: true }),
  ).toHaveCount(0)
  await expect(
    panel.getByRole("button", {
      name: "Confirm this report version",
      exact: true,
    }),
  ).toHaveCount(0)
  await expect(
    panel.getByRole("button", { name: "Save report revision", exact: true }),
  ).toHaveCount(0)
  await expect(
    panel.getByRole("button", { name: "Generate AI interpretation report" }),
  ).toHaveCount(0)
  expect(state.createCalls).toBe(0)

  state.failDetail = 0
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  await expect(
    panel
      .getByText(
        "Verify the registration and collection scope for this discrepancy.",
        {
          exact: true,
        },
      )
      .first(),
  ).toBeVisible()
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  const recovered = panel.getByLabel("Interpretation · check", {
    exact: true,
  })
  await expect(recovered).toHaveValue(
    "Verify the registration and collection scope for this discrepancy.",
  )
  await expect(recovered).not.toHaveValue(
    "Inactive account must clear this edit.",
  )
  expect(state.createCalls).toBe(0)
})

test("an unrelated 400 stays unknown and retains unsaved edits", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  const editor = panel.getByLabel("Interpretation · check", { exact: true })
  await editor.fill("Other 400 keeps this edit.")
  state.failDetail = 400
  state.failDetailBody = { detail: "Synthetic bad request" }
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  const unknown = panel
    .getByRole("alert")
    .filter({ hasText: "cause is unknown" })
  await expect(unknown).toBeVisible()
  await expect(unknown).not.toContainText("inactive")
  await expect(unknown).not.toContainText("not allowed")
  await expect(editor).toHaveCount(0)
  state.failDetail = 0
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  await expect(editor).toBeVisible()
  await expect(editor).toHaveValue("Other 400 keeps this edit.")
  expect(state.createCalls).toBe(0)
})

test("a selected list row marked unreadable clears content even when detail succeeds", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  await panel
    .getByLabel("Interpretation · check", { exact: true })
    .fill("List refusal must clear this text.")
  state.listUnreadable = true
  state.listUnavailableReason = "v2_report_material_expired"
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  await expect(
    panel.getByRole("alert").filter({ hasText: "expired" }),
  ).toBeVisible()
  await expect(
    panel.getByText(
      "Verify the registration and collection scope for this discrepancy.",
      { exact: true },
    ),
  ).toHaveCount(0)
  await expect(
    panel.getByLabel("Interpretation · check", { exact: true }),
  ).toHaveCount(0)
  expect(state.createCalls).toBe(0)
})

test("a detail response for another report id fails closed without showing its body", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  state.detailId = "21000000-0000-4000-8000-000000000299"
  state.detailText = "Wrong report body must stay hidden."
  await open(page)
  const panel = v2Panel(page)
  await expect(
    panel.getByText("Wrong report body must stay hidden.", { exact: true }),
  ).toHaveCount(0)
  await expect(
    panel.getByRole("alert").filter({ hasText: "cause is unknown" }),
  ).toBeVisible()
  expect(state.createCalls).toBe(0)
})

test("a temporary print read failure neither prints nor clears the report", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await page.addInitScript(() => {
    window.print = () => {
      document.body.dataset.printCalls = String(
        Number(document.body.dataset.printCalls ?? 0) + 1,
      )
    }
  })
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  const before = state.readCalls
  state.failNextDetail = 503
  await panel.getByRole("button", { name: "Print report", exact: true }).click()
  await expect(
    panel.getByRole("alert").filter({ hasText: "temporarily" }),
  ).toBeVisible()
  expect(state.readCalls).toBeGreaterThan(before)
  expect(
    await page.evaluate(() => document.body.dataset.printCalls),
  ).toBeUndefined()
  await expect(
    panel
      .getByText(
        "Verify the registration and collection scope for this discrepancy.",
        { exact: true },
      )
      .first(),
  ).toBeVisible()
  expect(state.createCalls).toBe(0)
})

test("a late same-identity print read after an explicit refusal neither prints nor revives content", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await installPrintWindow(page)
  await installPrintRequestMarker(page)
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  let release = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  state.gatePrintDetail = { id: reportId, gate, status: 200 }
  await panel.getByRole("button", { name: "Print report", exact: true }).click()
  await expect.poll(() => state.printGateHits).toBe(1)
  state.failDetail = 403
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "visible",
    })
    window.dispatchEvent(new Event("visibilitychange"))
  })
  const denied = panel
    .getByRole("alert")
    .filter({ hasText: "not allowed to read" })
  await expect(denied).toBeVisible()
  release()
  await expect.poll(() => state.printGateFulfilled).toBe(1)
  await expect(
    panel.getByRole("button", { name: "Re-read report state", exact: true }),
  ).toBeEnabled()
  expect(
    await page.evaluate(() => document.body.dataset.printCalls),
  ).toBeUndefined()
  await expect(denied).toBeVisible()
  await expect(
    panel
      .getByText(
        "Verify the registration and collection scope for this discrepancy.",
        {
          exact: true,
        },
      )
      .first(),
  ).toHaveCount(0)
  await expect(
    panel.getByRole("button", { name: "Edit interpretation", exact: true }),
  ).toHaveCount(0)
  expect(state.createCalls).toBe(0)
})

test("a late print success after paging to another version neither prints nor replaces it", async ({
  page,
}) => {
  const state = await serve(page, "READY", true, true)
  await installPrintWindow(page)
  await installPrintRequestMarker(page)
  await open(page)
  const panel = v2Panel(page)
  await expect(
    panel.getByText("Body for version 1", { exact: true }).first(),
  ).toBeVisible()
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  let release = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  state.gatePrintDetail = { id: state.pageIds[0], gate, status: 200 }
  await panel.getByRole("button", { name: "Print report", exact: true }).click()
  await expect.poll(() => state.printGateHits).toBe(1)
  await panel
    .getByRole("navigation", { name: "Report versions pagination" })
    .getByRole("button", { name: "Next", exact: true })
    .click()
  await expect(panel.getByLabel("Saved report version")).toHaveValue(
    state.pageIds[25],
  )
  await expect(
    panel.getByText("Body for version 26", { exact: true }).first(),
  ).toBeVisible()
  release()
  await expect.poll(() => state.printGateFulfilled).toBe(1)
  await expect(
    panel.getByRole("button", { name: "Print report", exact: true }),
  ).toBeEnabled()
  expect(
    await page.evaluate(() => document.body.dataset.printCalls),
  ).toBeUndefined()
  await expect(
    panel.getByText("Body for version 26", { exact: true }).first(),
  ).toBeVisible()
  expect(state.createCalls).toBe(0)
})

test("a late print rejection after paging to another version does not clear it", async ({
  page,
}) => {
  const state = await serve(page, "READY", true, true)
  await installPrintWindow(page)
  await installPrintRequestMarker(page)
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  let release = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  state.gatePrintDetail = { id: state.pageIds[0], gate, status: 503 }
  await panel.getByRole("button", { name: "Print report", exact: true }).click()
  await expect.poll(() => state.printGateHits).toBe(1)
  await panel
    .getByRole("navigation", { name: "Report versions pagination" })
    .getByRole("button", { name: "Next", exact: true })
    .click()
  await expect(panel.getByLabel("Saved report version")).toHaveValue(
    state.pageIds[25],
  )
  await expect(
    panel.getByText("Body for version 26", { exact: true }).first(),
  ).toBeVisible()
  release()
  await expect.poll(() => state.printGateFulfilled).toBe(1)
  await expect(
    panel.getByRole("button", { name: "Print report", exact: true }),
  ).toBeEnabled()
  expect(
    await page.evaluate(() => document.body.dataset.printCalls),
  ).toBeUndefined()
  await expect(
    panel.getByText("Body for version 26", { exact: true }).first(),
  ).toBeVisible()
  await expect(
    panel.getByText(
      "This report is unreadable under its fixed material permissions or cutoff.",
    ),
  ).toHaveCount(0)
  expect(state.createCalls).toBe(0)
})

for (const status of [200, 503, 403] as const) {
  test(`a late detail response after switching A to B does not change B (${status})`, async ({
    page,
  }) => {
    const state = await serve(page, "READY", true, true)
    let release = () => {}
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    state.gateDetail = { id: state.pageIds[0], gate, status }
    await open(page)
    const panel = v2Panel(page)
    await expect.poll(() => state.gateHits).toBeGreaterThan(0)
    await panel
      .getByLabel("Saved report version")
      .selectOption(state.pageIds[1])
    await expect(
      panel.getByText("Body for version 2", { exact: true }).first(),
    ).toBeVisible()
    release()
    await expect.poll(() => state.gateFulfilled).toBeGreaterThan(0)
    await expect(
      panel.getByText("Body for version 2", { exact: true }).first(),
    ).toBeVisible()
    await expect(
      panel.getByText("Body for version 1", { exact: true }),
    ).toHaveCount(0)
    if (status !== 200)
      await expect(
        panel.getByRole("alert").filter({
          hasText: status === 503 ? "temporarily" : "not allowed to read",
        }),
      ).toHaveCount(0)
    expect(state.createCalls).toBe(0)
  })
}

test("an explicitly unreadable report with an unknown reason purges content, edits and polling", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  const editor = panel.getByLabel("Interpretation · check", { exact: true })
  await editor.fill("Explicit unreadable must purge this.")
  state.detailUnreadable = true
  state.detailUnavailableReason = null
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  const unreadable = panel
    .getByRole("alert")
    .filter({ hasText: "explicitly unreadable" })
  await expect(unreadable).toBeVisible()
  await expect(unreadable).not.toContainText("cause is unknown")
  await expect(unreadable).not.toContainText("permission")
  await expect(unreadable).not.toContainText("expired")
  await expect(
    panel.getByLabel("Interpretation · check", { exact: true }),
  ).toHaveCount(0)
  await expect(
    panel.getByText("Reading report versions…", { exact: true }),
  ).toHaveCount(0)
  await expect(
    panel.getByText("Reading generation readiness…", { exact: true }),
  ).toHaveCount(0)
  await expect(
    panel.getByRole("button", { name: "Generate AI interpretation report" }),
  ).toHaveCount(0)
  await expect(
    panel.getByText(
      "Verify the registration and collection scope for this discrepancy.",
      { exact: true },
    ),
  ).toHaveCount(0)
  await page.waitForTimeout(300)
  const reads = state.readCalls
  state.failDetail = 503
  await page.waitForTimeout(5500)
  expect(state.readCalls).toBe(reads)
  await expect(unreadable).toBeVisible()
  await expect(unreadable).not.toContainText("temporarily")
  state.failDetail = 0
  state.detailUnreadable = false
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  await expect(
    panel
      .getByText(
        "Verify the registration and collection scope for this discrepancy.",
        { exact: true },
      )
      .first(),
  ).toBeVisible()
  await expect(
    panel.getByLabel("Interpretation · check", { exact: true }),
  ).toHaveCount(0)
  expect(state.createCalls).toBe(0)
})

test("a selected list row unreadable with an unknown reason never shows a readable detail body", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  state.listUnreadable = true
  state.listUnavailableReason = null
  let release = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  state.gateDetail = { id: reportId, gate, status: 200 }
  await open(page)
  const panel = v2Panel(page)
  await expect(
    panel.getByRole("alert").filter({ hasText: "explicitly unreadable" }),
  ).toBeVisible()
  await expect(
    panel.getByText(
      "Verify the registration and collection scope for this discrepancy.",
      { exact: true },
    ),
  ).toHaveCount(0)
  await expect.poll(() => state.gateHits).toBeGreaterThan(0)
  release()
  await expect.poll(() => state.gateFulfilled).toBeGreaterThan(0)
  await expect(
    panel.getByText(
      "Verify the registration and collection scope for this discrepancy.",
      { exact: true },
    ),
  ).toHaveCount(0)
  await expect(
    panel.getByRole("alert").filter({ hasText: "explicitly unreadable" }),
  ).toBeVisible()
  expect(state.createCalls).toBe(0)
})

test("an explicit versions refusal wins over a temporary detail failure", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  const editor = panel.getByLabel("Interpretation · check", { exact: true })
  await editor.fill("Refusal must win and clear this.")
  state.failDetail = 503
  state.failList = 403
  state.failListBody = {
    detail: { code: "project_role_denied", message: "Operator role required" },
  }
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  const denied = panel
    .getByRole("alert")
    .filter({ hasText: "not allowed to read" })
  await expect(denied).toBeVisible()
  await expect(denied).not.toContainText("temporarily")
  await expect(
    panel.getByLabel("Interpretation · check", { exact: true }),
  ).toHaveCount(0)
  await expect(
    panel.getByText(
      "Verify the registration and collection scope for this discrepancy.",
      { exact: true },
    ),
  ).toHaveCount(0)
  state.failDetail = 0
  state.failList = 0
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  await expect(
    panel
      .getByText(
        "Verify the registration and collection scope for this discrepancy.",
        { exact: true },
      )
      .first(),
  ).toBeVisible()
  await expect(
    panel.getByLabel("Interpretation · check", { exact: true }),
  ).toHaveCount(0)
  expect(state.createCalls).toBe(0)
})

test("a save response for another report id keeps the edit and does not clear it", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  const editor = panel.getByLabel("Interpretation · check", { exact: true })
  await editor.fill("Wrong save id must keep this edit.")
  state.patchId = "21000000-0000-4000-8000-000000000299"
  await panel
    .getByRole("button", { name: "Save report revision", exact: true })
    .click()
  await expect.poll(() => state.patchCalls).toBe(1)
  await expect(editor).toBeVisible()
  await expect(editor).toHaveValue("Wrong save id must keep this edit.")
  await expect(
    panel
      .getByRole("alert")
      .filter({ hasText: "could not be saved or confirmed" }),
  ).toBeVisible()
  expect(state.createCalls).toBe(0)
})

test("a print re-read for another report id does not print or replace the report", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await page.addInitScript(() => {
    window.print = () => {
      document.body.dataset.printCalls = String(
        Number(document.body.dataset.printCalls ?? 0) + 1,
      )
    }
  })
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  state.detailText = "Injected wrong-id body."
  state.nextDetailId = "21000000-0000-4000-8000-000000000299"
  await panel.getByRole("button", { name: "Print report", exact: true }).click()
  await expect(
    panel
      .getByRole("alert")
      .filter({ hasText: "could not be verified for printing" }),
  ).toBeVisible()
  expect(
    await page.evaluate(() => document.body.dataset.printCalls),
  ).toBeUndefined()
  await expect(
    panel.getByText("Injected wrong-id body.", { exact: true }),
  ).toHaveCount(0)
  await expect(
    panel.getByRole("button", { name: "Edit interpretation", exact: true }),
  ).toBeVisible()
  await expect(
    panel
      .getByText(
        "Verify the registration and collection scope for this discrepancy.",
        {
          exact: true,
        },
      )
      .first(),
  ).toBeVisible()
  expect(state.createCalls).toBe(0)
})

for (const [code, message] of [
  ["v2_report_material_unavailable", "no longer available"],
  ["v2_report_material_invalid", "failed its integrity check"],
  ["v2_report_material_expired", "material period has expired"],
] as const) {
  test(`a 409 ${code} on save clears the edit and blocks the report`, async ({
    page,
  }) => {
    const state = await serve(page, "READY", true)
    await open(page)
    const panel = v2Panel(page)
    await panel
      .getByRole("button", { name: "View full report", exact: true })
      .click()
    await panel
      .getByRole("button", { name: "Edit interpretation", exact: true })
      .click()
    await panel
      .getByLabel("Interpretation · check", { exact: true })
      .fill("Material refusal must clear this edit.")
    state.patchStatus = 409
    state.patchBody = {
      detail: {
        code,
        message: "fixed material unavailable",
      },
    }
    await panel
      .getByRole("button", { name: "Save report revision", exact: true })
      .click()
    await expect.poll(() => state.patchCalls).toBe(1)
    await expect(
      panel.getByRole("alert").filter({ hasText: message }),
    ).toBeVisible()
    await expect(
      panel.getByLabel("Interpretation · check", { exact: true }),
    ).toHaveCount(0)
    await expect(
      panel
        .getByText(
          "Verify the registration and collection scope for this discrepancy.",
          {
            exact: true,
          },
        )
        .first(),
    ).toHaveCount(0)
    await expect(
      panel.getByRole("button", { name: "Edit interpretation", exact: true }),
    ).toHaveCount(0)
    expect(state.createCalls).toBe(0)
  })
}

test("a 409 revision conflict keeps unsaved edits and shows a distinct message", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  const editor = panel.getByLabel("Interpretation · check", { exact: true })
  await editor.fill("Revision conflict keeps this edit.")
  state.patchStatus = 409
  state.patchBody = {
    detail: { code: "revision_conflict", message: "expected revision changed" },
  }
  await panel
    .getByRole("button", { name: "Save report revision", exact: true })
    .click()
  await expect.poll(() => state.patchCalls).toBe(1)
  const conflict = panel
    .getByRole("alert")
    .filter({ hasText: "This version changed since it was read." })
  await expect(conflict).toBeVisible()
  await expect(conflict).not.toContainText("no longer available")
  await expect(conflict).not.toContainText("not allowed")
  await expect(editor).toBeVisible()
  await expect(editor).toHaveValue("Revision conflict keeps this edit.")
  await expect(
    panel
      .getByText(
        "Verify the registration and collection scope for this discrepancy.",
        {
          exact: true,
        },
      )
      .first(),
  ).toBeVisible()
  await expect(
    panel.getByRole("button", { name: "Save report revision", exact: true }),
  ).toBeVisible()
  expect(state.createCalls).toBe(0)
})

test("a 409 revision conflict on confirm keeps the report and shows the distinct message", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  state.confirmStatus = 409
  state.confirmBody = {
    detail: { code: "revision_conflict", message: "expected revision changed" },
  }
  await panel
    .getByRole("button", { name: "Confirm this report version", exact: true })
    .click()
  await expect.poll(() => state.confirmCalls).toBe(1)
  await expect(
    panel
      .getByRole("alert")
      .filter({ hasText: "This version changed since it was read." }),
  ).toBeVisible()
  await expect(
    panel
      .getByText(
        "Verify the registration and collection scope for this discrepancy.",
        {
          exact: true,
        },
      )
      .first(),
  ).toBeVisible()
  await expect(
    panel.getByRole("button", {
      name: "Confirm this report version",
      exact: true,
    }),
  ).toBeVisible()
  expect(state.createCalls).toBe(0)
})

test("a history refusal hides the fixed report body and actions", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  await panel
    .getByLabel("Interpretation · check", { exact: true })
    .fill("History refusal must clear this unsaved edit.")
  state.failHistory = 403
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  await expect(
    panel.getByRole("alert").filter({ hasText: "not allowed to read" }),
  ).toBeVisible()
  await expect(
    panel.getByText(
      "Verify the registration and collection scope for this discrepancy.",
      { exact: true },
    ),
  ).toHaveCount(0)
  await expect(
    panel.getByRole("button", { name: "Edit interpretation", exact: true }),
  ).toHaveCount(0)
  await expect(
    panel.getByText("Reading report versions…", { exact: true }),
  ).toHaveCount(0)
  state.failHistory = 0
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  await expect(
    panel
      .getByText(
        "Verify the registration and collection scope for this discrepancy.",
        { exact: true },
      )
      .first(),
  ).toBeVisible()
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  const recovered = panel.getByLabel("Interpretation · check", {
    exact: true,
  })
  await expect(recovered).toHaveValue(
    "Verify the registration and collection scope for this discrepancy.",
  )
  await expect(recovered).not.toHaveValue(
    "History refusal must clear this unsaved edit.",
  )
  expect(state.createCalls).toBe(0)
})

test("a revision history refusal wins over a simultaneous detail failure on re-read", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  await expect(
    panel
      .getByText(
        "Verify the registration and collection scope for this discrepancy.",
        {
          exact: true,
        },
      )
      .first(),
  ).toBeVisible()
  const historyBefore = state.historyPaths.length
  state.failDetail = 503
  state.failHistory = 403
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  const denied = panel
    .getByRole("alert")
    .filter({ hasText: "not allowed to read" })
  await expect(denied).toBeVisible()
  await expect(denied).not.toContainText("temporarily")
  await expect(
    panel.getByRole("alert").filter({ hasText: "temporarily" }),
  ).toHaveCount(0)
  await expect(
    panel
      .getByText(
        "Verify the registration and collection scope for this discrepancy.",
        {
          exact: true,
        },
      )
      .first(),
  ).toHaveCount(0)
  await expect(
    panel.getByLabel("Interpretation · check", { exact: true }),
  ).toHaveCount(0)
  await expect(
    panel.getByRole("button", { name: "Edit interpretation", exact: true }),
  ).toHaveCount(0)
  expect(state.createCalls).toBe(0)
  expect(state.historyPaths.length).toBeGreaterThan(historyBefore)
  expect(
    state.historyPaths.every((path) => path.endsWith(`/${reportId}/revisions`)),
  ).toBe(true)
})

test("re-reading after a history refusal explicitly gets the same report history", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  state.failHistory = 403
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  await expect(
    panel.getByRole("alert").filter({ hasText: "not allowed to read" }),
  ).toBeVisible()
  await expect(
    panel
      .getByText(
        "Verify the registration and collection scope for this discrepancy.",
        {
          exact: true,
        },
      )
      .first(),
  ).toHaveCount(0)
  const historyBefore = state.historyPaths.length
  state.failHistory = 0
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  await expect(
    panel
      .getByText(
        "Verify the registration and collection scope for this discrepancy.",
        {
          exact: true,
        },
      )
      .first(),
  ).toBeVisible()
  await expect
    .poll(() => state.historyPaths.length)
    .toBeGreaterThan(historyBefore)
  expect(
    state.historyPaths
      .slice(historyBefore)
      .every((path) => path.endsWith(`/${reportId}/revisions`)),
  ).toBe(true)
  expect(state.createCalls).toBe(0)
  expect(state.patchCalls).toBe(0)
  expect(state.confirmCalls).toBe(0)
})

test("a history refusal that arrives before a gated detail failure stays the read problem", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  let release = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  state.gateDetail = { id: reportId, gate, status: 503 }
  state.failHistory = 403
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  const denied = panel
    .getByRole("alert")
    .filter({ hasText: "not allowed to read" })
  await expect(denied).toBeVisible()
  await expect(
    panel.getByRole("alert").filter({ hasText: "temporarily" }),
  ).toHaveCount(0)
  release()
  await expect.poll(() => state.gateFulfilled).toBeGreaterThan(0)
  await expect(denied).toBeVisible()
  await expect(denied).not.toContainText("temporarily")
  await expect(
    panel.getByRole("alert").filter({ hasText: "temporarily" }),
  ).toHaveCount(0)
  await expect(
    panel
      .getByText(
        "Verify the registration and collection scope for this discrepancy.",
        {
          exact: true,
        },
      )
      .first(),
  ).toHaveCount(0)
  await expect(
    panel.getByLabel("Interpretation · check", { exact: true }),
  ).toHaveCount(0)
  await expect(
    panel.getByRole("button", { name: "Edit interpretation", exact: true }),
  ).toHaveCount(0)
  expect(state.createCalls).toBe(0)
})

test("a later history refusal replaces a temporary detail failure", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  let release = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  state.gateHistory = { gate, status: 403 }
  state.failDetail = 503
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  await expect.poll(() => state.gateHistoryHits).toBeGreaterThan(0)
  const temporary = panel.getByRole("alert").filter({ hasText: "temporarily" })
  await expect(temporary).toBeVisible()
  release()
  await expect.poll(() => state.gateHistoryFulfilled).toBeGreaterThan(0)
  const denied = panel
    .getByRole("alert")
    .filter({ hasText: "not allowed to read" })
  await expect(denied).toBeVisible()
  await expect(temporary).toHaveCount(0)
  await expect(
    panel
      .getByText(
        "Verify the registration and collection scope for this discrepancy.",
        {
          exact: true,
        },
      )
      .first(),
  ).toHaveCount(0)
  await expect(
    panel.getByLabel("Interpretation · check", { exact: true }),
  ).toHaveCount(0)
  await expect(
    panel.getByRole("button", { name: "Edit interpretation", exact: true }),
  ).toHaveCount(0)
  expect(state.createCalls).toBe(0)
})

test("a late print refusal after paging to another version does not clear it", async ({
  page,
}) => {
  const state = await serve(page, "READY", true, true)
  await installPrintWindow(page)
  await installPrintRequestMarker(page)
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  let release = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  state.gatePrintDetail = { id: state.pageIds[0], gate, status: 403 }
  await panel.getByRole("button", { name: "Print report", exact: true }).click()
  await expect.poll(() => state.printGateHits).toBe(1)
  await panel
    .getByRole("navigation", { name: "Report versions pagination" })
    .getByRole("button", { name: "Next", exact: true })
    .click()
  await expect(panel.getByLabel("Saved report version")).toHaveValue(
    state.pageIds[25],
  )
  await expect(
    panel.getByText("Body for version 26", { exact: true }).first(),
  ).toBeVisible()
  release()
  await expect.poll(() => state.printGateFulfilled).toBe(1)
  await expect(
    panel.getByRole("button", { name: "Print report", exact: true }),
  ).toBeEnabled()
  expect(
    await page.evaluate(() => document.body.dataset.printCalls),
  ).toBeUndefined()
  await expect(
    panel.getByText("Body for version 26", { exact: true }).first(),
  ).toBeVisible()
  await expect(
    panel.getByRole("alert").filter({ hasText: "not allowed to read" }),
  ).toHaveCount(0)
  expect(state.createCalls).toBe(0)
})

test("a permitted print still calls window.print exactly once", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await installPrintWindow(page)
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  await panel.getByRole("button", { name: "Print report", exact: true }).click()
  await expect
    .poll(() => page.evaluate(() => document.body.dataset.printCalls))
    .toBe("1")
  expect(await page.evaluate(() => document.body.dataset.printCalls)).toBe("1")
  expect(state.createCalls).toBe(0)
})

for (const [status, refusal] of [
  [403, "not allowed to read"],
  [410, "fixed material period has expired"],
] as const) {
  test(`a history ${status} that arrives after collapsing to summary still blocks the report`, async ({
    page,
  }) => {
    const state = await serve(page, "READY", true)
    const history = deferred()
    state.gateHistory = { gate: history.promise, status }
    await open(page)
    const panel = v2Panel(page)
    await panel
      .getByRole("button", { name: "View full report", exact: true })
      .click()
    await expect.poll(() => state.gateHistoryHits).toBe(1)
    await panel
      .getByRole("button", { name: "Edit interpretation", exact: true })
      .click()
    await panel
      .getByLabel("Interpretation · check", { exact: true })
      .fill("History refusal after collapse must clear this edit.")
    await panel
      .getByRole("button", { name: "Show summary", exact: true })
      .click()
    await expect(
      panel
        .getByText(
          "Verify the registration and collection scope for this discrepancy.",
          { exact: true },
        )
        .first(),
    ).toBeVisible()
    history.release()
    await expect.poll(() => state.gateHistoryFulfilled).toBe(1)
    const denied = panel.getByRole("alert").filter({ hasText: refusal })
    await expect(denied).toBeVisible()
    if (status === 410) {
      await expect(denied).not.toContainText("cause is unknown")
      await expect(denied).not.toContainText("not allowed to read")
    }
    await expect(
      panel.getByText(
        "Verify the registration and collection scope for this discrepancy.",
        { exact: true },
      ),
    ).toHaveCount(0)
    await expect(
      panel.getByLabel("Interpretation · check", { exact: true }),
    ).toHaveCount(0)
    await expect(
      panel.getByRole("button", { name: "Edit interpretation", exact: true }),
    ).toHaveCount(0)
    await expect(
      panel.getByRole("button", { name: "Print report", exact: true }),
    ).toHaveCount(0)
    await expect(
      panel.getByRole("button", { name: "Save report revision", exact: true }),
    ).toHaveCount(0)
    await expect(
      panel.getByRole("button", {
        name: "Confirm this report version",
        exact: true,
      }),
    ).toHaveCount(0)
    await expect(
      panel.getByRole("button", {
        name: "Generate AI interpretation report",
      }),
    ).toHaveCount(0)
    expect(state.createCalls).toBe(0)

    state.gateHistory = null
    await panel
      .getByRole("button", { name: "Re-read report state", exact: true })
      .click()
    await expect(
      panel
        .getByText(
          "Verify the registration and collection scope for this discrepancy.",
          { exact: true },
        )
        .first(),
    ).toBeVisible()
    await panel
      .getByRole("button", { name: "View full report", exact: true })
      .click()
    await panel
      .getByRole("button", { name: "Edit interpretation", exact: true })
      .click()
    const recovered = panel.getByLabel("Interpretation · check", {
      exact: true,
    })
    await expect(recovered).toHaveValue(
      "Verify the registration and collection scope for this discrepancy.",
    )
    await expect(recovered).not.toHaveValue(
      "History refusal after collapse must clear this edit.",
    )
    expect(state.createCalls).toBe(0)
  })
}

test("a history refusal after collapsing to summary cancels a pending print read", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await installPrintWindow(page)
  await installPrintRequestMarker(page)
  const history = deferred()
  state.gateHistory = { gate: history.promise, status: 403 }
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  await expect.poll(() => state.gateHistoryHits).toBe(1)
  const printRead = deferred()
  state.gatePrintDetail = { id: reportId, gate: printRead.promise, status: 200 }
  await panel.getByRole("button", { name: "Print report", exact: true }).click()
  await expect.poll(() => state.printGateHits).toBe(1)
  expect(
    await page.evaluate(
      () =>
        (
          window as unknown as {
            __printRequestMarker: { marked: number; paths: string[] }
          }
        ).__printRequestMarker.paths,
    ),
  ).toEqual([`${root}/analysis-reports/v2/${reportId}`])
  await panel.getByRole("button", { name: "Show summary", exact: true }).click()
  history.release()
  await expect.poll(() => state.gateHistoryFulfilled).toBe(1)
  const denied = panel
    .getByRole("alert")
    .filter({ hasText: "not allowed to read" })
  await expect(denied).toBeVisible()
  printRead.release()
  await expect.poll(() => state.printGateFulfilled).toBe(1)
  await expect(
    panel.getByRole("button", { name: "Re-read report state", exact: true }),
  ).toBeEnabled()
  expect(await page.evaluate(() => document.body.dataset.printCalls)).toBe(
    undefined,
  )
  await expect(denied).toBeVisible()
  await expect(
    panel.getByText(
      "Verify the registration and collection scope for this discrepancy.",
      { exact: true },
    ),
  ).toHaveCount(0)
  await expect(
    panel.getByRole("button", { name: "Edit interpretation", exact: true }),
  ).toHaveCount(0)
  await expect(
    panel.getByRole("button", { name: "Print report", exact: true }),
  ).toHaveCount(0)
  expect(state.createCalls).toBe(0)
})

test("a history refusal during the held print frames cancels printing", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await installPrintWindow(page)
  await installPrintRequestMarker(page)
  await installPrintRafHold(page)
  const history = deferred()
  state.gateHistory = { gate: history.promise, status: 403 }
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  await expect.poll(() => state.gateHistoryHits).toBe(1)
  const printRead = deferred()
  state.gatePrintDetail = { id: reportId, gate: printRead.promise, status: 200 }
  await panel.getByRole("button", { name: "Print report", exact: true }).click()
  await expect.poll(() => state.printGateHits).toBe(1)
  await page.evaluate(() => {
    ;(
      window as unknown as { __printRafHold: { armed: boolean } }
    ).__printRafHold.armed = true
  })
  printRead.release()
  await expect.poll(() => state.printGateFulfilled).toBe(1)
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (
            window as unknown as {
              __printRafHold: { queue: unknown[] }
            }
          ).__printRafHold.queue.length,
      ),
    )
    .toBe(1)
  history.release()
  await expect.poll(() => state.gateHistoryFulfilled).toBe(1)
  const denied = panel
    .getByRole("alert")
    .filter({ hasText: "not allowed to read" })
  await expect(denied).toBeVisible()
  await page.evaluate(() => {
    ;(window as unknown as { __flushPrintRaf: () => number }).__flushPrintRaf()
  })
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (
            window as unknown as {
              __printRafHold: { queue: unknown[] }
            }
          ).__printRafHold.queue.length,
      ),
    )
    .toBe(1)
  await page.evaluate(() => {
    ;(window as unknown as { __flushPrintRaf: () => number }).__flushPrintRaf()
  })
  await page.evaluate(() => {
    ;(
      window as unknown as { __printRafHold: { armed: boolean } }
    ).__printRafHold.armed = false
  })
  await expect(
    panel.getByRole("button", { name: "Re-read report state", exact: true }),
  ).toBeEnabled()
  expect(await page.evaluate(() => document.body.dataset.printCalls)).toBe(
    undefined,
  )
  await expect(denied).toBeVisible()
  expect(state.createCalls).toBe(0)
})

const coreEnvelope = {
  contract_version: "core-comparison-v2",
  project_id: project,
}
const addressRows = Array.from({ length: 30 }, (_, index) => ({
  address_key: `addr:${String(index + 1).padStart(64, "0")}`,
  canonical_ip: `192.0.2.${index + 1}`,
  classification: "both",
  customer_records: 1,
  cloud_records: 1,
  presence: { CUSTOMER: "PRESENT", CLOUD: "PRESENT" },
}))

async function serveAddressPage(page: Page) {
  const reads: URLSearchParams[] = []
  const addressesPath = `${root}/comparison-results/${result}/addresses`
  await page.route(
    (url) => url.pathname === addressesPath,
    (route) => {
      const query = new URL(route.request().url()).searchParams
      reads.push(query)
      const ip = query.get("ip")
      const matched = ip
        ? addressRows.filter((row) => row.canonical_ip === ip)
        : addressRows
      const sorted =
        query.get("sort") === "ip_desc" ? [...matched].reverse() : matched
      const skip = Number(query.get("skip") ?? 0)
      const limit = Number(query.get("limit") ?? 25)
      return route.fulfill({
        json: {
          ...coreEnvelope,
          result_id: result,
          total_addresses: addressRows.length,
          count: sorted.length,
          skip,
          limit,
          data: sorted.slice(skip, skip + limit),
        },
      })
    },
  )
  await page.route(
    (url) => url.pathname.startsWith(`${addressesPath}/`),
    (route) => {
      const requestUrl = new URL(route.request().url())
      const rest = decodeURIComponent(
        requestUrl.pathname.slice(`${addressesPath}/`.length),
      )
      if (rest.endsWith("/evidence")) {
        const key = rest.slice(0, -"/evidence".length)
        return route.fulfill({
          json: {
            ...coreEnvelope,
            result_id: result,
            address_key: key,
            source: requestUrl.searchParams.get("source") ?? "customer",
            count: 0,
            skip: 0,
            limit: 25,
            data: [],
          },
        })
      }
      const row = addressRows.find((value) => value.address_key === rest)
      if (!row)
        return route.fulfill({
          status: 404,
          json: { detail: { code: "comparison_address_not_found" } },
        })
      return route.fulfill({
        json: { ...coreEnvelope, result_id: result, address: row },
      })
    },
  )
  return reads
}

const readingNav = (page: Page) =>
  page.getByRole("navigation", { name: "Reading areas" })
const recordsGroup = (page: Page) =>
  page.getByRole("group", { name: "Records and evidence" })
const reportHeading = (page: Page) =>
  page.getByRole("heading", {
    name: "AI interpretation and reports",
    exact: true,
  })
const materialsSummary = (page: Page) =>
  page.getByText("View the materials used here", { exact: true })

async function visitReadingArea(page: Page, entry: string) {
  await readingNav(page)
    .getByRole("button", { name: entry, exact: true })
    .click()
}

test("reading shortcuts retain the report node, version page, full body, draft and filters", async ({
  page,
}) => {
  const state = await serve(page, "READY", false, true)
  const reads = await serveAddressPage(page)
  const methods: string[] = []
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/v1/"))
      methods.push(request.method())
  })
  await page.goto(
    `/projects/${project}/netflow-correlation?result=${result}&binding=none&core_class=both&core_page=1&core_sort=ip_desc`,
  )
  const core = page.getByRole("region", { name: "Core classification" })
  await expect(
    core.getByText("Fixed total 30 · Matching 30 · This page 5"),
  ).toBeVisible()
  await expect(
    core.getByRole("button", { name: /Recorded on both sides 1/ }),
  ).toHaveAttribute("aria-pressed", "true")
  const ipInput = core.getByRole("textbox", {
    name: "IP address",
    exact: true,
  })
  await ipInput.fill("198.51.100.")

  const panel = v2Panel(page)
  await expect(panel.getByLabel("Saved report version")).toHaveValue(
    state.pageIds[0],
  )
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  await expect(
    panel.getByText("Body for version 1", { exact: true }).first(),
  ).toBeVisible()
  await panel
    .getByRole("navigation", { name: "Report versions pagination" })
    .getByRole("button", { name: "Next", exact: true })
    .click()
  await expect(panel.getByLabel("Saved report version")).toHaveValue(
    state.pageIds[25],
  )
  await expect(
    panel.getByText("Body for version 26", { exact: true }).first(),
  ).toBeVisible()
  await expect(
    panel.getByRole("button", { name: "Show summary", exact: true }),
  ).toBeVisible()
  await expect(
    panel
      .getByRole("navigation", { name: "Report versions pagination" })
      .getByText("Page 2 of 2"),
  ).toBeVisible()
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  const editor = panel.getByLabel("Interpretation · check", { exact: true })
  await editor.fill("Draft kept across reading shortcuts.")
  await expect(
    panel.getByRole("button", { name: "Save report revision", exact: true }),
  ).toBeEnabled()
  await panel.evaluate((element) =>
    element.setAttribute("data-reading-node", "kept"),
  )
  const node = await panel.elementHandle()
  const before = page.url()
  for (const [entry, target] of [
    ["Records and evidence", recordsGroup(page)],
    ["AI interpretation and reports", reportHeading(page)],
    ["Materials used here", materialsSummary(page)],
  ] as const) {
    await visitReadingArea(page, entry)
    await expect(target).toBeFocused()
  }
  await page
    .getByRole("button", { name: "Back to reading areas", exact: true })
    .click()
  await expect(readingNav(page)).toBeFocused()
  expect(page.url()).toBe(before)
  await expect(panel).toHaveAttribute("data-reading-node", "kept")
  expect(
    await node!.evaluate(
      (element, current) => element === current,
      await panel.elementHandle(),
    ),
  ).toBe(true)
  await expect(panel.getByLabel("Saved report version")).toHaveValue(
    state.pageIds[25],
  )
  await expect(
    panel
      .getByRole("navigation", { name: "Report versions pagination" })
      .getByText("Page 2 of 2"),
  ).toBeVisible()
  await expect(
    panel.getByRole("button", { name: "Show summary", exact: true }),
  ).toBeVisible()
  await expect(editor).toHaveValue("Draft kept across reading shortcuts.")
  await expect(
    panel.getByRole("button", { name: "Save report revision", exact: true }),
  ).toBeEnabled()
  await expect(ipInput).toHaveValue("198.51.100.")
  await expect(
    core.getByRole("button", { name: /Recorded on both sides 1/ }),
  ).toHaveAttribute("aria-pressed", "true")
  await expect(
    core.getByText("Fixed total 30 · Matching 30 · This page 5"),
  ).toBeVisible()
  const url = new URL(page.url())
  expect(url.searchParams.get("core_page")).toBe("1")
  expect(url.searchParams.get("core_sort")).toBe("ip_desc")
  expect(url.searchParams.get("core_class")).toBe("both")
  expect(state.createCalls).toBe(0)
  expect(state.patchCalls).toBe(0)
  expect(state.confirmCalls).toBe(0)
  expect(methods.every((method) => method === "GET")).toBe(true)
  expect(reads.some((query) => query.get("skip") === "25")).toBe(true)
})

test("open materials and an open evidence drawer survive shortcuts while the page report draft is kept", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await serveAddressPage(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  const editor = panel.getByLabel("Interpretation · check", { exact: true })
  const draft = "Page report draft survives materials and drawer."
  await editor.fill(draft)
  const materials = materialsSummary(page)
  const details = page.locator("details").filter({ has: materials })
  await materials.click()
  await expect(details).toHaveJSProperty("open", true)
  const table = page.getByRole("table", { name: "Comparison addresses" })
  await table.getByRole("button", { name: "View evidence" }).first().click()
  const drawer = page.getByRole("dialog")
  await expect(drawer).toBeVisible()
  await expect(
    drawer.getByRole("heading", { name: addressRows[0].canonical_ip }),
  ).toBeFocused()
  await expect(editor).toHaveValue(draft)
  const before = page.url()
  for (const [entry, target] of [
    ["Records and evidence", recordsGroup(page)],
    ["AI interpretation and reports", reportHeading(page)],
    ["Materials used here", materials],
  ] as const) {
    await visitReadingArea(page, entry)
    await expect(target).toBeFocused()
    await expect(drawer).toBeVisible()
    await expect(details).toHaveJSProperty("open", true)
    await expect(editor).toHaveValue(draft)
  }
  await page
    .getByRole("button", { name: "Back to reading areas", exact: true })
    .click()
  await expect(readingNav(page)).toBeFocused()
  await expect(drawer).toBeVisible()
  await expect(details).toHaveJSProperty("open", true)
  expect(page.url()).toBe(before)
  await drawer
    .getByRole("button", { name: "Close evidence", exact: true })
    .click()
  await expect(drawer).toHaveCount(0)
  await expect(page).not.toHaveURL(/core_address=/)
  await expect(editor).toHaveValue(draft)
  await expect(details).toHaveJSProperty("open", true)
  await table.getByRole("button", { name: "View evidence" }).nth(1).click()
  await expect(drawer).toBeVisible()
  await expect(
    drawer.getByRole("heading", { name: addressRows[1].canonical_ip }),
  ).toBeFocused()
  await expect(editor).toHaveValue(draft)
  await drawer
    .getByRole("button", { name: "Close evidence", exact: true })
    .click()
  await expect(drawer).toHaveCount(0)
  expect(state.createCalls).toBe(0)
  expect(state.patchCalls).toBe(0)
})

test("shortcut activity stays read-only and empty or unavailable report states remain reachable", async ({
  page,
}) => {
  const state = await serve(page, "NOT_CONFIGURED", false)
  const methods: string[] = []
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/v1/"))
      methods.push(request.method())
  })
  await open(page)
  await visitReadingArea(page, "AI interpretation and reports")
  await expect(reportHeading(page)).toBeFocused()
  const panel = v2Panel(page)
  await expect(
    panel.getByText("No model connection is configured.", { exact: true }),
  ).toBeVisible()
  await expect(
    panel.getByText(
      "No report for this fixed scope yet. Facts and evidence remain available below.",
      { exact: true },
    ),
  ).toBeVisible()
  const before = page.url()
  for (const [entry, target] of [
    ["Records and evidence", recordsGroup(page)],
    ["Materials used here", materialsSummary(page)],
    ["AI interpretation and reports", reportHeading(page)],
  ] as const) {
    await visitReadingArea(page, entry)
    await expect(target).toBeFocused()
  }
  await page
    .getByRole("button", { name: "Back to reading areas", exact: true })
    .click()
  expect(page.url()).toBe(before)
  expect(state.createCalls).toBe(0)
  expect(state.patchCalls).toBe(0)
  expect(state.confirmCalls).toBe(0)
  expect(methods.length).toBeGreaterThan(0)
  expect(methods.every((method) => method === "GET")).toBe(true)
})

test("a new result notice leaves the fixed identity and reading shortcuts unchanged", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await page.route(
    (url) => url.pathname === `${root}/comparison-results/${result}/updates`,
    (route) =>
      route.fulfill({
        json: {
          ...coreEnvelope,
          result_id: result,
          state: "UNCHANGED",
          latest_result_id: "10000000-0000-4000-8000-000000000299",
        },
      }),
  )
  await open(page)
  const notice = page.getByText(
    "A newer result is available. This page has not changed version.",
  )
  await expect(notice).toBeVisible()
  const before = page.url()
  for (const entry of [
    "Records and evidence",
    "AI interpretation and reports",
    "Materials used here",
  ]) {
    await visitReadingArea(page, entry)
  }
  await page
    .getByRole("button", { name: "Back to reading areas", exact: true })
    .click()
  await expect(notice).toBeVisible()
  expect(new URL(page.url()).searchParams.get("result")).toBe(result)
  expect(page.url()).toBe(before)
  expect(state.createCalls).toBe(0)
})

test("a delayed old report response does not replace the selected version during shortcuts", async ({
  page,
}) => {
  const state = await serve(page, "READY", true, true)
  const gate = deferred()
  state.gateDetail = { id: state.pageIds[0], gate: gate.promise, status: 200 }
  await open(page)
  const panel = v2Panel(page)
  await expect.poll(() => state.gateHits).toBeGreaterThan(0)
  await panel.getByLabel("Saved report version").selectOption(state.pageIds[1])
  await expect(
    panel.getByText("Body for version 2", { exact: true }).first(),
  ).toBeVisible()
  const before = page.url()
  for (const entry of [
    "Records and evidence",
    "AI interpretation and reports",
    "Materials used here",
  ]) {
    await visitReadingArea(page, entry)
  }
  gate.release()
  await expect.poll(() => state.gateFulfilled).toBeGreaterThan(0)
  await expect(
    panel.getByText("Body for version 2", { exact: true }).first(),
  ).toBeVisible()
  await expect(
    panel.getByText("Body for version 1", { exact: true }),
  ).toHaveCount(0)
  await expect(panel.getByRole("alert")).toHaveCount(0)
  expect(page.url()).toBe(before)
  expect(state.createCalls).toBe(0)
})

test("temporary failures keep the draft through shortcuts; explicit expiry clears it", async ({
  page,
}) => {
  const state = await serve(page, "READY", true)
  await open(page)
  const panel = v2Panel(page)
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  const editor = panel.getByLabel("Interpretation · check", { exact: true })
  const draft = "Temporary source failure keeps this draft."
  await editor.fill(draft)
  state.failDetail = 503
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  await expect(
    panel.getByRole("alert").filter({ hasText: "temporarily" }),
  ).toBeVisible()
  await expect(editor).toHaveCount(0)
  for (const entry of [
    "Records and evidence",
    "AI interpretation and reports",
    "Materials used here",
  ]) {
    await visitReadingArea(page, entry)
  }
  state.failDetail = 0
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  await expect(editor).toBeVisible()
  await expect(editor).toHaveValue(draft)
  state.failDetail = 410
  state.failDetailBody = {
    detail: {
      code: "v2_report_material_expired",
      message: "fixed material expired",
    },
  }
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  const expired = panel.getByRole("alert").filter({ hasText: "expired" })
  await expect(expired).toBeVisible()
  await expect(editor).toHaveCount(0)
  await expect(panel.getByText(draft)).toHaveCount(0)
  await visitReadingArea(page, "AI interpretation and reports")
  await expect(reportHeading(page)).toBeFocused()
  await expect(expired).toBeVisible()
  await expect(editor).toHaveCount(0)
  state.failDetail = 0
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  await expect(editor).toHaveCount(0)
  expect(state.createCalls).toBe(0)
  expect(state.patchCalls).toBe(0)
})
