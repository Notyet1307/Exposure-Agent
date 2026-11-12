import type { Locator } from "@playwright/test"

import { expect, type Page, type Route, test } from "./fixtures"

const project = "00000000-0000-4000-8000-000000000398"
const result = "10000000-0000-4000-8000-000000000398"
const reportId = "20000000-0000-4000-8000-000000000398"
const addressReportId = "21000000-0000-4000-8000-000000000398"
const upload = "30000000-0000-4000-8000-000000000398"
const version = "40000000-0000-4000-8000-000000000398"
const source = "50000000-0000-4000-8000-000000000398"
const root = `/api/v1/projects/${project}`
const ref = `core:${result}`
const countRef = `fact:${result}:counts`
const addressKey = `addr:${"a".repeat(64)}`
const addressRef = `fact:${result}:${addressKey}`
const screenshots =
  "/Users/yet/ops/tasks/exposure2026/report-sections-20261112/rework-01/author/tests/screenshots"
const conflictBody = {
  detail: {
    code: "analysis_report_revision_conflict",
    message: "synthetic revision conflict",
  },
}
const expiredBody = {
  detail: {
    code: "v2_report_material_expired",
    message: "synthetic material expiry",
  },
}

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

type Claim =
  | {
      id: string
      type: "fact"
      fact_refs: string[]
      evidence_refs: string[]
    }
  | {
      id: string
      type: "explanation" | "hypothesis" | "gap" | "action"
      text: string
      fact_refs: string[]
      evidence_refs: string[]
    }

type Text = {
  summary: string[]
  sections: Array<{ id: string; claim_ids: string[] }>
  claims: Claim[]
  priority_cases: Array<{
    address_key: string
    why_review: string
    next_check: string
    evidence_refs: string[]
  }>
  limitations: string[]
}

type Material = {
  captured_at: string
  subject: {
    result_id: string
    supplement_binding_id: null
    address_key: string | null
  }
  identity: {
    pins: {
      CUSTOMER: {
        upload_id: string
        revision_id: null
        profile_version: number
      }
      CLOUD: { domains: { ip: { id: string; fetched_at: string } } }
    }
  }
  summary: typeof summary
  facts: Record<
    string,
    { kind: string; value: unknown; evidence_refs: string[] }
  >
  items: Array<{
    citation_id: string
    kind: string
    identity: string
    data: Record<string, unknown>
  }>
  samples: Array<{
    address_key: string
    canonical_ip: string
    evidence_refs: string[]
  }>
  coverage: {
    sampled_addresses: number
    eligible_addresses: number
    omitted_addresses: number
    omitted_source_records: number
  }
  limitations: string[]
}

type Report = {
  subject_kind: string
  result_id: string
  supplement_binding_id: null
  audience: "management" | "operations"
  language: "en" | "zh"
  address_key: string | null
  id: string
  project_id: string
  status: "DRAFT" | "CONFIRMED" | "GENERATING" | "FAILED"
  revision: number
  created_at: string
  completed_at: string | null
  edited_at: string | null
  confirmed_at: string | null
  created_by_id: string
  edited_by_id: string | null
  confirmed_by_id: string | null
  connection_version_id: string | null
  config_fingerprint: string
  material_sha256: string
  failure_code: string | null
  readable: boolean
  unavailable_reason: string | null
  materials_changed: boolean | null
  valid_until: string | null
  original_output: { contract_version: string; text: Text } | null
  text: Text | null
  material: Material | null
}

type SaveBody = {
  expected_revision?: number
  edits?: Record<string, string>
  case_edits?: Record<string, { why_review: string; next_check: string }>
}

type Failure = { status: number; body: unknown }
type Gate = {
  promise: Promise<void>
  release: () => void
  status: number
  body: unknown
  hits: number
  fulfilled: number
}
type World = {
  reports: Record<string, Report>
  order: string[]
  history: Record<string, unknown[]>
  historyStatus: number
  patchBodies: SaveBody[]
  patchUrls: string[]
  patchCount: number
  confirmBodies: SaveBody[]
  confirmCount: number
  createCount: number
  onPatch: ((report: Report) => Failure | null) | null
  rereadFailures: Failure[]
  rereadGate: Gate | null
  patchGate: Gate | null
  detailRefusal: Failure | null
}

function managementText(variant: "old" | "new" | "long" = "new"): Text {
  const long = "L".repeat(220)
  const shared =
    variant === "old"
      ? "Shared claim old text."
      : variant === "long"
        ? `Long unbroken token ${long}`
        : "Shared claim new text."
  const check =
    variant === "old"
      ? "Adjacent claim old text."
      : variant === "long"
        ? `Adjacent unbroken token ${long}`
        : "Adjacent claim new text."
  const why =
    variant === "old"
      ? "Why old case text."
      : variant === "long"
        ? `Why unbroken token ${long}`
        : "Why new case text."
  const next =
    variant === "old"
      ? "Next old case text."
      : variant === "long"
        ? `Next unbroken token ${long}`
        : "Next new case text."
  return {
    summary: ["summary_only", "shared"],
    sections: [
      { id: "conclusion", claim_ids: ["fixed"] },
      { id: "differences", claim_ids: ["shared", "check"] },
      { id: "priority", claim_ids: ["shared"] },
      { id: "netflow", claim_ids: ["check"] },
      { id: "next_steps", claim_ids: ["shared"] },
      { id: "appendix", claim_ids: ["fixed"] },
    ],
    claims: [
      {
        id: "fixed",
        type: "fact",
        fact_refs: [countRef],
        evidence_refs: [ref],
      },
      {
        id: "shared",
        type: "action",
        text: shared,
        fact_refs: [],
        evidence_refs: [ref],
      },
      {
        id: "check",
        type: "explanation",
        text: check,
        fact_refs: [],
        evidence_refs: [ref],
      },
      {
        id: "summary_only",
        type: "gap",
        text: "Summary only claim text.",
        fact_refs: [],
        evidence_refs: [ref],
      },
      {
        id: "unplaced",
        type: "hypothesis",
        text: "Unplaced claim text.",
        fact_refs: [],
        evidence_refs: [ref],
      },
    ],
    priority_cases: [
      {
        address_key: addressKey,
        why_review: why,
        next_check: next,
        evidence_refs: [ref],
      },
    ],
    limitations: ["The actual observation window was not provided."],
  }
}

function addressText(): Text {
  return {
    summary: ["address_fixed", "address_note"],
    sections: [
      { id: "known_facts", claim_ids: ["address_fixed"] },
      { id: "possible_explanations", claim_ids: ["address_note"] },
      { id: "missing_evidence", claim_ids: ["address_note"] },
      { id: "next_checks", claim_ids: ["address_check"] },
    ],
    claims: [
      {
        id: "address_fixed",
        type: "fact",
        fact_refs: [addressRef],
        evidence_refs: [ref],
      },
      {
        id: "address_note",
        type: "explanation",
        text: "Address note old text.",
        fact_refs: [],
        evidence_refs: [ref],
      },
      {
        id: "address_check",
        type: "action",
        text: "Address check old text.",
        fact_refs: [],
        evidence_refs: [ref],
      },
    ],
    priority_cases: [],
    limitations: ["The actual observation window was not provided."],
  }
}

function materialFor(address: boolean): Material {
  return {
    captured_at: "2026-10-08T00:00:00Z",
    subject: {
      result_id: result,
      supplement_binding_id: null,
      address_key: address ? addressKey : null,
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
      ...(address
        ? {
            [addressRef]: {
              kind: "address",
              value: { address_key: addressKey },
              evidence_refs: [ref],
            },
          }
        : {}),
    },
    items: [
      { citation_id: ref, kind: "CORE_RESULT", identity: result, data: {} },
    ],
    samples: address
      ? []
      : [
          {
            address_key: addressKey,
            canonical_ip: "192.0.2.10",
            evidence_refs: [ref],
          },
        ],
    coverage: {
      sampled_addresses: 1,
      eligible_addresses: 3,
      omitted_addresses: 2,
      omitted_source_records: 0,
    },
    limitations: ["The actual observation window was not provided."],
  }
}

function reportFor(
  id: string,
  values: Partial<Report> & { text?: Text } = {},
): Report {
  const text = values.text ?? managementText("new")
  return {
    subject_kind: "core_comparison_v2",
    result_id: result,
    supplement_binding_id: null,
    audience: "management",
    language: "en",
    address_key: null,
    id,
    project_id: project,
    status: "DRAFT",
    revision: 2,
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
    original_output: null,
    material: materialFor(values.address_key === addressKey),
    ...values,
    text,
  }
}

function snapshot(options: {
  id: string
  revision: number
  text: Text
  reportId?: string
  status?: unknown
  recordedAt?: unknown
  actorId?: unknown
}): Record<string, unknown> {
  const has = (key: keyof typeof options) => Object.hasOwn(options, key)
  return {
    id: options.id,
    report_id: options.reportId ?? reportId,
    revision: options.revision,
    status: has("status") ? options.status : "DRAFT",
    text: structuredClone(options.text),
    actor_id: has("actorId") ? options.actorId : "synthetic-operator",
    recorded_at: has("recordedAt")
      ? options.recordedAt
      : "2026-10-08T00:01:00Z",
  }
}

function makeWorld(options: { revision?: number } = {}): World {
  const revision = options.revision ?? 2
  const current = revision === 1 ? managementText("old") : managementText("new")
  const management = reportFor(reportId, { revision, text: current })
  const address = reportFor(addressReportId, {
    id: addressReportId,
    revision: 1,
    audience: "operations",
    address_key: addressKey,
    text: addressText(),
    material: materialFor(true),
  })
  const history =
    revision === 1
      ? [
          snapshot({
            id: "history-1",
            revision: 1,
            text: current,
            recordedAt: "2026-10-08T00:01:00Z",
          }),
        ]
      : [
          snapshot({
            id: "history-2",
            revision: revision,
            text: current,
            recordedAt: "2026-10-08T00:02:00Z",
          }),
          snapshot({
            id: "history-1",
            revision: revision - 1,
            text: managementText("old"),
            recordedAt: "2026-10-08T00:01:00Z",
          }),
        ]
  return {
    reports: { [reportId]: management, [addressReportId]: address },
    order: [reportId],
    history: { [reportId]: history, [addressReportId]: [] },
    historyStatus: 0,
    patchBodies: [],
    patchUrls: [],
    patchCount: 0,
    confirmBodies: [],
    confirmCount: 0,
    createCount: 0,
    onPatch: null,
    rereadFailures: [],
    rereadGate: null,
    patchGate: null,
    detailRefusal: null,
  }
}

function savedReport(report: Report, body: SaveBody): Report {
  const next = structuredClone(report)
  if (next.text) {
    const edits = body.edits ?? {}
    next.text.claims = next.text.claims.map((claim) =>
      claim.type === "fact"
        ? claim
        : edits[claim.id] === undefined
          ? claim
          : { ...claim, text: edits[claim.id] },
    )
    const caseEdits = body.case_edits ?? {}
    next.text.priority_cases = next.text.priority_cases.map((item) => {
      const edit = caseEdits[item.address_key]
      return edit
        ? {
            ...item,
            why_review: edit.why_review,
            next_check: edit.next_check,
          }
        : item
    })
  }
  next.revision = report.revision + 1
  next.edited_at = "2026-10-08T00:03:00Z"
  next.edited_by_id = "synthetic-operator"
  return next
}

async function serveWorld(page: Page, world: World) {
  await page.addInitScript(() => {
    const marker: { armed: boolean; marked: number; paths: string[] } = {
      armed: false,
      marked: 0,
      paths: [],
    }
    ;(window as unknown as { __rereadMarker: typeof marker }).__rereadMarker =
      marker
    document.addEventListener(
      "click",
      (event) => {
        const target = event.target
        if (!(target instanceof Element)) return
        const button = target.closest("button")
        if (button?.textContent?.includes("Re-read")) marker.armed = true
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
      ;(this as unknown as { __rereadOpen?: [string, string] }).__rereadOpen = [
        String(method).toUpperCase(),
        String(url),
      ]
      return Reflect.apply(nativeOpen, this, [method, url, ...rest])
    } as typeof prototype.open
    prototype.send = function (this: XMLHttpRequest, ...args: unknown[]) {
      const opened = (this as unknown as { __rereadOpen?: [string, string] })
        .__rereadOpen
      const path = opened ? new URL(opened[1], location.href).pathname : ""
      if (
        marker.armed &&
        opened?.[0] === "GET" &&
        /\/analysis-reports\/v2\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
          path,
        )
      ) {
        marker.armed = false
        marker.marked++
        marker.paths.push(path)
        this.setRequestHeader("x-test-reread", "1")
      }
      return Reflect.apply(nativeSend, this, args)
    } as typeof prototype.send
  })
  await page.addInitScript(() => {
    if (sessionStorage.getItem("component-auth-seeded") !== null) return
    localStorage.setItem("access_token", "synthetic-component-token")
    sessionStorage.setItem("component-auth-seeded", "1")
  })
  const json = (route: Route, value: unknown, status = 200) =>
    route.fulfill({ status, json: value })
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    if (path === "/api/v1/users/me")
      return json(route, {
        id: "synthetic-user",
        email: "synthetic@example.com",
        is_active: true,
        is_superuser: true,
      })
    if (path === "/api/v1/projects/")
      return json(route, {
        data: [
          { id: project, name: "Synthetic report project", status: "active" },
        ],
        count: 1,
      })
    if (path === `${root}/comparison-results/${result}/summary`)
      return json(route, summary)
    if (path === `${root}/comparison-results/${result}/updates`)
      return json(route, {
        contract_version: "core-comparison-v2",
        project_id: project,
        result_id: result,
        state: "UNCHANGED",
      })
    if (path === `${root}/comparison-results/${result}/addresses`)
      return json(route, {
        contract_version: "core-comparison-v2",
        project_id: project,
        result_id: result,
        total_addresses: 3,
        data: [],
        count: 0,
      })
    if (path === `${root}/comparison-results/${result}/addresses/${addressKey}`)
      return json(route, {
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
      })
    if (
      path ===
      `${root}/comparison-results/${result}/addresses/${addressKey}/evidence`
    )
      return json(route, {
        contract_version: "core-comparison-v2",
        project_id: project,
        result_id: result,
        address_key: addressKey,
        source: url.searchParams.get("source") ?? "customer",
        data: [],
        count: 0,
        skip: Number(url.searchParams.get("skip") ?? "0"),
        limit: Number(url.searchParams.get("limit") ?? "25"),
      })
    if (path === `${root}/analysis-reports/v2/readiness`)
      return json(route, {
        project_id: project,
        result_id: result,
        supplement_binding_id: null,
        state: "READY",
        can_create: true,
      })
    if (path === `${root}/analysis-reports/v2`) {
      if (request.method() === "POST") {
        world.createCount++
        return json(
          route,
          reportFor(reportId, { text: managementText("new") }),
          201,
        )
      }
      const addressScope = url.searchParams.get("address_key") !== null
      const ids = addressScope ? [addressReportId] : world.order
      const skip = Number(url.searchParams.get("skip") ?? "0")
      const limit = Number(url.searchParams.get("limit") ?? "25")
      const rows = ids.slice(skip, skip + limit).flatMap((id) => {
        const report = world.reports[id]
        if (!report) return []
        return [
          {
            ...structuredClone(report),
            text: null,
            original_output: null,
            material: null,
          },
        ]
      })
      return json(route, { data: rows, count: ids.length, can_create: true })
    }
    if (path.startsWith(`${root}/analysis-reports/v2/operations/`))
      return json(route, world.reports[reportId] ?? null)
    if (
      path.startsWith(`${root}/analysis-reports/v2/`) &&
      path.endsWith("/confirm")
    ) {
      const id = path.split("/").at(-2) ?? ""
      const report = world.reports[id]
      if (!report) return json(route, { detail: "not found" }, 404)
      const body = request.postDataJSON() as SaveBody
      world.confirmCount++
      world.confirmBodies.push(body)
      const confirmed = {
        ...structuredClone(report),
        status: "CONFIRMED" as const,
        revision: report.revision + 1,
        confirmed_at: "2026-10-08T00:04:00Z",
        confirmed_by_id: "synthetic-operator",
      }
      world.reports[id] = confirmed
      return json(route, confirmed)
    }
    if (
      path.startsWith(`${root}/analysis-reports/v2/`) &&
      path.endsWith("/revisions")
    ) {
      const id = path.split("/").at(-2) ?? ""
      if (world.historyStatus)
        return json(
          route,
          {
            detail: { code: "synthetic_history_failure", message: "synthetic" },
          },
          world.historyStatus,
        )
      return json(route, world.history[id] ?? [])
    }
    if (
      path.startsWith(`${root}/analysis-reports/v2/`) &&
      request.method() === "PATCH"
    ) {
      const id = path.slice(`${root}/analysis-reports/v2/`.length)
      const report = world.reports[id]
      if (!report) return json(route, { detail: "not found" }, 404)
      const body = request.postDataJSON() as SaveBody
      if (world.patchGate) {
        const gate = world.patchGate
        gate.hits++
        await gate.promise
        gate.fulfilled++
        if (gate.status !== 200) return json(route, gate.body, gate.status)
      }
      world.patchCount++
      world.patchUrls.push(request.url())
      world.patchBodies.push(body)
      const override = world.onPatch?.(report) ?? null
      if (override) return json(route, override.body, override.status)
      const saved = savedReport(report, body)
      world.reports[id] = saved
      return json(route, saved)
    }
    if (
      path.startsWith(`${root}/analysis-reports/v2/`) &&
      !path.slice(`${root}/analysis-reports/v2/`.length).includes("/")
    ) {
      const id = path.slice(`${root}/analysis-reports/v2/`.length)
      const report = world.reports[id]
      if (!report) return json(route, { detail: "not found" }, 404)
      const isReread = request.headers()["x-test-reread"] === "1"
      if (!isReread && world.detailRefusal)
        return json(route, world.detailRefusal.body, world.detailRefusal.status)
      if (isReread && world.rereadGate) {
        const gate = world.rereadGate
        gate.hits++
        await gate.promise
        gate.fulfilled++
        if (gate.status !== 200) return json(route, gate.body, gate.status)
      }
      if (isReread && world.rereadFailures.length) {
        const failure = world.rereadFailures.shift()
        if (failure) return json(route, failure.body, failure.status)
      }
      return json(route, report)
    }
    return json(route, { detail: "synthetic unmatched route" }, 404)
  })
}

const openPage = (page: Page) =>
  page.goto(
    `/projects/${project}/netflow-correlation?result=${result}&binding=none`,
  )

async function openFull(
  page: Page,
  name = "AI interpretation for this comparison",
) {
  const panel = page.getByRole("region", { name })
  await expect(
    panel.getByRole("button", { name: "View full report", exact: true }),
  ).toBeVisible()
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  return panel
}

const historyDetails = (panel: Locator) =>
  panel.locator("details").filter({ hasText: "Human revision history" })

const navBeforeReportBody = (page: Page, id: string) =>
  page.evaluate(
    ({ headingId }) => {
      const navigation = document.querySelector(
        'nav[aria-label="Report chapters"]',
      )
      const heading = document.getElementById(headingId)
      return (
        !!navigation &&
        !!heading &&
        !!(
          navigation.compareDocumentPosition(heading) &
          Node.DOCUMENT_POSITION_FOLLOWING
        )
      )
    },
    { headingId: `${id}-chapter-facts` },
  )

async function openHistory(panel: Locator) {
  const details = historyDetails(panel)
  await details.locator("summary").click()
  return details
}

test("an editing draft cannot page away or write to a report selected later", async ({
  page,
}) => {
  const world = makeWorld()
  const ids = Array.from(
    { length: 26 },
    (_, index) =>
      `22000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
  )
  world.order = ids
  world.reports = Object.fromEntries(
    ids.map((id, index) => [
      id,
      reportFor(id, {
        revision: 1,
        text: managementText("new"),
        created_at: `2026-10-08T00:${String(index).padStart(2, "0")}:00Z`,
      }),
    ]),
  )
  await serveWorld(page, world)
  await openPage(page)
  const panel = await openFull(page)
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  await expect(panel.getByLabel("Interpretation · shared")).toBeVisible()
  const nav = panel.getByRole("navigation", {
    name: "Report versions pagination",
  })
  await expect(
    nav.getByRole("button", { name: "Next", exact: true }),
  ).toBeDisabled()
  await expect(panel.getByLabel("Saved report version")).toBeDisabled()

  await panel.getByLabel("Saved report version").evaluate((element) => {
    element.removeAttribute("disabled")
    element.closest("fieldset")?.removeAttribute("disabled")
  })
  await panel.getByLabel("Saved report version").selectOption(ids[1])
  await nav.getByRole("button", { name: "Next", exact: true }).click()
  await expect(panel.getByRole("alert")).toContainText(
    "Save or discard your draft before changing report versions or pages.",
  )
  await expect(panel.getByLabel("Saved report version")).toHaveValue(ids[0])
  await expect(nav.getByText("Page 1 of 2")).toBeVisible()

  await panel
    .getByLabel("Interpretation · shared")
    .fill("Only the captured report may receive this draft.")
  await panel
    .getByRole("button", { name: "Save report revision", exact: true })
    .click()
  await expect.poll(() => world.patchCount).toBe(1)
  expect(world.patchUrls[0]).toContain(ids[0])
  expect(world.patchUrls.some((value) => value.includes(ids[1]))).toBe(false)
  expect(world.patchBodies[0]?.expected_revision).toBe(1)
  expect(world.createCount).toBe(0)
  await expect(
    panel.getByText("Draft; review required", { exact: true }),
  ).toBeVisible()
})

test("version pagination stays disabled and guarded while a save is in flight", async ({
  page,
}) => {
  const world = makeWorld()
  const ids = Array.from(
    { length: 26 },
    (_, index) =>
      `23000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
  )
  world.order = ids
  world.reports = Object.fromEntries(
    ids.map((id, index) => [
      id,
      reportFor(id, {
        revision: 1,
        text: managementText("new"),
        created_at: `2026-10-08T00:${String(index).padStart(2, "0")}:00Z`,
      }),
    ]),
  )
  await serveWorld(page, world)
  await openPage(page)
  const panel = await openFull(page)
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  await panel
    .getByLabel("Interpretation · shared")
    .fill("Busy save must freeze version controls.")
  let release = () => {}
  const promise = new Promise<void>((resolve) => {
    release = resolve
  })
  world.patchGate = {
    promise,
    release,
    status: 200,
    body: null,
    hits: 0,
    fulfilled: 0,
  }
  const responsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "PATCH" &&
      new URL(response.url()).pathname.endsWith(`/v2/${ids[0]}`),
  )
  await panel
    .getByRole("button", { name: "Save report revision", exact: true })
    .click()
  await expect.poll(() => world.patchGate?.hits).toBe(1)
  const nav = panel.getByRole("navigation", {
    name: "Report versions pagination",
  })
  await expect(
    nav.getByRole("button", { name: "Next", exact: true }),
  ).toBeDisabled()
  await expect(panel.getByLabel("Saved report version")).toBeDisabled()
  await expect(
    panel.getByText(
      "Report version and page changes are unavailable until the current operation ends or the draft is saved or discarded.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(
    panel.getByRole("button", { name: "Save report revision", exact: true }),
  ).toBeDisabled()
  release()
  expect((await responsePromise).status()).toBe(200)
  await expect(panel.getByLabel("Interpretation · shared")).toHaveCount(0)
  await expect(
    panel.getByText("Draft; review required", { exact: true }),
  ).toBeVisible()
  expect(world.patchCount).toBe(1)
})

test("chapter locators reach every section, the single shared editor and read-only facts", async ({
  page,
}) => {
  const world = makeWorld()
  await serveWorld(page, world)
  await openPage(page)
  const panel = await openFull(page)
  const nav = panel.getByRole("navigation", { name: "Report chapters" })
  expect(await navBeforeReportBody(page, reportId)).toBe(true)
  await nav
    .getByRole("button", {
      name: "This comparison's conclusion",
      exact: true,
    })
    .focus()
  await page.keyboard.press("Enter")
  await expect(
    page.locator(`[id="${reportId}-chapter-conclusion"]`),
  ).toBeFocused()
  const sections: Array<[string, string]> = [
    ["conclusion", "This comparison's conclusion"],
    ["differences", "Main differences and their meaning"],
    ["priority", "Objects to verify first"],
    ["netflow", "NetFlow observations and limits"],
    ["next_steps", "Suggested next steps"],
    ["appendix", "Data scope and evidence"],
  ]
  for (const [id, title] of sections) {
    await nav.getByRole("button", { name: title, exact: true }).click()
    await expect(page.locator(`[id="${reportId}-chapter-${id}"]`)).toBeFocused()
  }
  await nav
    .getByRole("button", { name: "Fixed comparison facts", exact: true })
    .click()
  await expect(page.locator(`[id="${reportId}-chapter-facts"]`)).toBeFocused()
  await nav
    .getByRole("button", { name: "Suggested verification order", exact: true })
    .click()
  await expect(
    page.locator(`[id="${reportId}-chapter-priority_cases"]`),
  ).toBeFocused()
  await nav.getByRole("button", { name: "Data limits", exact: true }).click()
  await expect(page.locator(`[id="${reportId}-chapter-limits"]`)).toBeFocused()
  await nav
    .getByRole("button", { name: "Fixed source versions", exact: true })
    .click()
  await expect(page.locator(`[id="${reportId}-chapter-sources"]`)).toBeFocused()
  await expect(
    nav.getByRole("button", { name: "Report summary", exact: true }),
  ).toHaveCount(0)

  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  expect(await navBeforeReportBody(page, reportId)).toBe(true)
  await expect(panel.getByLabel("Interpretation · shared")).toHaveCount(1)
  await expect(panel.getByLabel("Interpretation · fixed")).toHaveCount(0)
  await expect(
    panel.getByRole("button", {
      name: "Focus shared claim shared",
      exact: true,
    }),
  ).toHaveCount(2)
  await expect(
    panel.getByText(
      "Also appears in: Report summary · Objects to verify first · Suggested next steps",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(
    panel.getByLabel(`Why verify this object · ${addressKey}`),
  ).toHaveCount(1)
  await expect(
    panel.getByLabel(`What to verify next · ${addressKey}`),
  ).toHaveCount(1)

  await nav.getByRole("button", { name: "Report summary", exact: true }).click()
  await expect(panel.getByLabel("Interpretation · summary_only")).toBeFocused()
  await nav
    .getByRole("button", {
      name: "Main differences and their meaning",
      exact: true,
    })
    .click()
  await expect(panel.getByLabel("Interpretation · shared")).toBeFocused()
  await nav
    .getByRole("button", { name: "This comparison's conclusion", exact: true })
    .click()
  await expect(
    page.locator(`[id="${reportId}-chapter-conclusion"]`),
  ).toBeFocused()
  await nav
    .getByRole("button", { name: "Not placed in a chapter", exact: true })
    .click()
  await expect(panel.getByLabel("Interpretation · unplaced")).toBeFocused()
  await nav
    .getByRole("button", { name: "Suggested verification order", exact: true })
    .click()
  await expect(
    panel.getByLabel(`Why verify this object · ${addressKey}`),
  ).toBeFocused()
})

test("the Report summary locator appears only for a real summary-only group", async ({
  page,
}) => {
  const world = makeWorld()
  const text = managementText("new")
  text.summary = ["shared"]
  world.reports[reportId] = reportFor(reportId, { revision: 2, text })
  await serveWorld(page, world)
  await openPage(page)
  const panel = await openFull(page)
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  const nav = panel.getByRole("navigation", { name: "Report chapters" })
  await expect(
    nav.getByRole("button", { name: "Report summary", exact: true }),
  ).toHaveCount(0)
  await expect(
    nav.getByRole("button", { name: "Not placed in a chapter", exact: true }),
  ).toBeVisible()
  await expect(panel.getByLabel("Interpretation · summary_only")).toBeVisible()
  await expect(panel.getByLabel("Interpretation · shared")).toHaveCount(1)
})

test("a fixed address report locates and edits its own four chapters", async ({
  page,
}) => {
  const world = makeWorld()
  await serveWorld(page, world)
  await page.goto(
    `/projects/${project}/netflow-correlation?result=${result}&binding=none&core_address=${addressKey}`,
  )
  const panel = await openFull(page, "Explain this difference")
  const nav = panel.getByRole("navigation", { name: "Report chapters" })
  const sections: Array<[string, string]> = [
    ["known_facts", "Known facts"],
    ["possible_explanations", "Possible explanations"],
    ["missing_evidence", "Missing evidence"],
    ["next_checks", "Suggested checks"],
  ]
  for (const [id, title] of sections) {
    await nav.getByRole("button", { name: title, exact: true }).click()
    await expect(
      page.locator(`[id="${addressReportId}-chapter-${id}"]`),
    ).toBeFocused()
  }
  await nav
    .getByRole("button", { name: "Fixed address facts", exact: true })
    .click()
  await expect(
    page.locator(`[id="${addressReportId}-chapter-facts"]`),
  ).toBeFocused()
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  await expect(panel.getByLabel("Interpretation · address_note")).toHaveCount(1)
  await expect(panel.getByLabel("Interpretation · address_fixed")).toHaveCount(
    0,
  )
  await expect(panel.getByLabel("Interpretation · address_check")).toBeVisible()
  await expect(
    panel.getByRole("button", {
      name: "Focus shared claim address_note",
      exact: true,
    }),
  ).toHaveCount(1)
  expect(world.createCount).toBe(0)
})

test("save stays a draft, confirmation is separate, and reading controls never write", async ({
  page,
}) => {
  const world = makeWorld()
  await serveWorld(page, world)
  await openPage(page)
  const panel = await openFull(page)
  const writes: string[] = []
  page.on("request", (request) => {
    if (request.method() !== "GET" && request.url().includes("/api/v1/"))
      writes.push(`${request.method()} ${new URL(request.url()).pathname}`)
  })
  const nav = panel.getByRole("navigation", { name: "Report chapters" })
  await nav
    .getByRole("button", {
      name: "Main differences and their meaning",
      exact: true,
    })
    .click()
  await panel.getByRole("button", { name: "Show summary", exact: true }).click()
  await panel
    .getByRole("button", { name: "View full report", exact: true })
    .click()
  const details = await openHistory(panel)
  await details.getByRole("button", { name: /^Revision 1/ }).click()
  await expect(
    details.getByText("This is the first recorded revision"),
  ).toBeVisible()
  await page.waitForTimeout(250)
  expect(writes).toEqual([])
  expect(world.createCount).toBe(0)

  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  await panel
    .getByLabel("Interpretation · check")
    .fill("Operator drafted explanation.")
  await panel
    .getByRole("button", { name: "Save report revision", exact: true })
    .click()
  await expect.poll(() => world.patchCount).toBe(1)
  await expect(
    panel.getByText("Draft; review required", { exact: true }),
  ).toBeVisible()
  expect(world.confirmCount).toBe(0)
  expect(world.patchBodies[0]?.edits?.check).toBe(
    "Operator drafted explanation.",
  )
  await expect(
    panel.getByRole("button", {
      name: "Confirm this report version",
      exact: true,
    }),
  ).toBeVisible()

  await panel
    .getByRole("button", { name: "Confirm this report version", exact: true })
    .click()
  await expect.poll(() => world.confirmCount).toBe(1)
  expect(world.confirmBodies[0]?.expected_revision).toBe(3)
  await expect(
    panel.getByText("Confirmed report version", { exact: true }),
  ).toBeVisible()
  await expect(
    panel.getByRole("button", { name: "Edit interpretation", exact: true }),
  ).toHaveCount(0)
  await expect(panel.getByLabel("Interpretation · check")).toHaveCount(0)
  expect(world.createCount).toBe(0)
})

test("adjacent history shows full before and after prose and true affected chapters", async ({
  page,
}) => {
  const world = makeWorld()
  await serveWorld(page, world)
  await openPage(page)
  const panel = await openFull(page)
  const details = await openHistory(panel)
  await expect(details.getByText("Recorded snapshots")).toBeVisible()
  await expect(
    details.getByText("Full text changed between these adjacent revisions."),
  ).toBeVisible()
  const affected = details.getByText(/Affected chapters/)
  await expect(affected).toContainText("Report summary")
  await expect(affected).toContainText("Main differences and their meaning")
  await expect(affected).toContainText("Objects to verify first")
  await expect(affected).toContainText("NetFlow observations and limits")
  await expect(affected).toContainText("Suggested next steps")
  await expect(affected).toContainText("Suggested verification order")
  await expect(affected).not.toContainText("This comparison's conclusion")
  const before = details.getByRole("region", { name: "Before revision 1" })
  const after = details.getByRole("region", { name: "After revision 2" })
  await expect(before).toContainText("Shared claim old text.")
  await expect(before).toContainText("Adjacent claim old text.")
  await expect(before).toContainText("Why old case text.")
  await expect(after).toContainText("Shared claim new text.")
  await expect(after).toContainText("Adjacent claim new text.")
  await expect(after).toContainText("Why new case text.")
  await expect(before).not.toContainText("Shared claim new text.")
  await expect(after).not.toContainText("Shared claim old text.")

  await details.getByRole("button", { name: /^Revision 1/ }).click()
  await expect(
    details.getByText("This is the first recorded revision"),
  ).toBeVisible()
  await expect(
    details.getByRole("region", { name: "Initial revision" }),
  ).toContainText("Shared claim old text.")
  await expect(
    details.getByRole("region", { name: /^Before revision/ }),
  ).toHaveCount(0)
})

test("same text with a confirmation is described as confirmation only", async ({
  page,
}) => {
  const world = makeWorld()
  const text = managementText("new")
  world.history[reportId] = [
    snapshot({
      id: "history-2",
      revision: 2,
      text,
      status: "CONFIRMED",
      recordedAt: "2026-10-08T00:02:00Z",
    }),
    snapshot({
      id: "history-1",
      revision: 1,
      text,
      status: "DRAFT",
      recordedAt: "2026-10-08T00:01:00Z",
    }),
  ]
  await serveWorld(page, world)
  await openPage(page)
  const panel = await openFull(page)
  const details = await openHistory(panel)
  await expect(
    details.getByText(
      "This adjacent step only confirmed the same text. Confirmation does not prove the narrative is correct.",
    ),
  ).toBeVisible()
  await expect(
    details.getByText(
      "No narrative text changed between these adjacent revisions.",
    ),
  ).toHaveCount(0)
  await expect(
    details.getByRole("button", { name: /^Revision 2 · Confirmed/ }),
  ).toBeVisible()
  await expect(
    details.getByRole("region", { name: "Before revision 1" }),
  ).toBeVisible()
})

test("history is honest at the first revision and across a missing predecessor", async ({
  page,
}) => {
  const world = makeWorld()
  world.history[reportId] = [
    snapshot({
      id: "history-3",
      revision: 3,
      text: managementText("new"),
      recordedAt: "2026-10-08T00:03:00Z",
    }),
    snapshot({
      id: "history-1",
      revision: 1,
      text: managementText("old"),
      recordedAt: "2026-10-08T00:01:00Z",
    }),
  ]
  await serveWorld(page, world)
  await openPage(page)
  const panel = await openFull(page)
  const details = await openHistory(panel)
  await expect(
    details.getByText(
      "Revision 2 is not available, so no comparison is shown across the gap.",
    ),
  ).toBeVisible()
  const selected = details.getByRole("region", {
    name: "Selected revision 3",
  })
  await expect(selected).toBeVisible()
  await expect(selected).toContainText("Shared claim new text.")
  await expect(selected).toContainText("Adjacent claim new text.")
  await expect(
    details.getByRole("region", { name: /^Before revision/ }),
  ).toHaveCount(0)
  await expect(
    details.getByText("Full text changed between these adjacent revisions."),
  ).toHaveCount(0)
  await expect(
    details.getByText(
      "No narrative text changed between these adjacent revisions.",
    ),
  ).toHaveCount(0)
  await details.getByRole("button", { name: /^Revision 1/ }).click()
  await expect(
    details.getByText("This is the first recorded revision"),
  ).toBeVisible()
  await expect(
    details.getByRole("region", { name: "Initial revision" }),
  ).toBeVisible()
})

test("empty history is distinct from a protected-structure mismatch", async ({
  page,
}) => {
  const world = makeWorld()
  world.history[reportId] = []
  await serveWorld(page, world)
  await openPage(page)
  let panel = await openFull(page)
  let details = await openHistory(panel)
  await expect(
    details.getByText("No revision history is available for this report yet."),
  ).toBeVisible()
  await expect(details.getByRole("alert")).toHaveCount(0)

  const changed = structuredClone(managementText("new"))
  changed.sections = changed.sections.map((section) =>
    section.id === "differences"
      ? { ...section, claim_ids: ["shared"] }
      : section,
  )
  world.history[reportId] = [
    snapshot({ id: "history-2", revision: 2, text: changed }),
    snapshot({ id: "history-1", revision: 1, text: managementText("old") }),
  ]
  await openPage(page)
  panel = await openFull(page)
  details = await openHistory(panel)
  await expect(
    details.getByText(
      "Revision 2 does not match this report's current verified fixed structure. Its body is suppressed, and no changed or unchanged text is claimed.",
    ),
  ).toBeVisible()
  await expect(
    details.getByRole("region", {
      name: /^(Before revision|Initial revision|Selected revision)/,
    }),
  ).toHaveCount(0)
  await expect(
    details.getByText(
      "No narrative text changed between these adjacent revisions.",
    ),
  ).toHaveCount(0)
  await expect(
    details.getByText("Full text changed between these adjacent revisions."),
  ).toHaveCount(0)
})

test("invalid history is rejected rather than shown as an empty or plausible diff", async ({
  page,
}) => {
  const world = makeWorld()
  await serveWorld(page, world)
  const valid = snapshot({
    id: "history-2",
    revision: 2,
    text: managementText("new"),
  })
  const variants = [
    {
      rows: [valid, { ...valid, id: "history-duplicate" }],
      label: "duplicate revision",
    },
    {
      rows: [{ ...valid, report_id: "29999999-9999-4999-8999-999999999999" }],
      label: "foreign report",
    },
    {
      rows: [{ ...valid, text: { ...managementText("new"), claims: [] } }],
      label: "incomplete text",
    },
    {
      rows: [
        {
          ...valid,
          text: {
            ...managementText("new"),
            summary: ["shared", "missing-pointer"],
          },
        },
      ],
      label: "repeated reference to an unknown claim",
    },
    {
      rows: [
        {
          ...valid,
          text: {
            ...managementText("new"),
            claims: [
              ...managementText("new").claims,
              {
                id: "shared",
                type: "action",
                text: "Duplicate claim identity.",
                fact_refs: [],
                evidence_refs: [ref],
              },
            ],
          },
        },
      ],
      label: "duplicate claim identity",
    },
  ]
  for (const variant of variants) {
    world.history[reportId] = variant.rows
    await openPage(page)
    const panel = await openFull(page)
    const details = await openHistory(panel)
    await expect(
      details.getByText(
        "Revision history is invalid for this report. It is not treated as empty, and no snapshot body is shown.",
      ),
    ).toBeVisible()
    await expect(
      details.getByText(
        "No revision history is available for this report yet.",
      ),
    ).toHaveCount(0)
    await expect(
      details.getByRole("region", { name: /^Before revision/ }),
    ).toHaveCount(0)
  }
})

test("history metadata is not fabricated when status, time and actor are missing", async ({
  page,
}) => {
  const world = makeWorld()
  world.history[reportId] = [
    snapshot({
      id: "history-2",
      revision: 2,
      text: managementText("new"),
      status: undefined,
      recordedAt: "not-a-date",
      actorId: undefined,
    }),
    snapshot({
      id: "history-1",
      revision: 1,
      text: managementText("old"),
      status: undefined,
      recordedAt: undefined,
      actorId: undefined,
    }),
  ]
  await serveWorld(page, world)
  await openPage(page)
  const panel = await openFull(page)
  const details = await openHistory(panel)
  await expect(details.getByText("Recorded snapshots")).toBeVisible()
  await expect(details.getByText("Status unavailable").first()).toBeVisible()
  await expect(details.getByText("Time unavailable").first()).toBeVisible()
  await expect(details.getByText("Author unavailable").first()).toBeVisible()
  await expect(details.getByText("Confirmed", { exact: true })).toHaveCount(0)
})

test("a failed history read is retryable and never presented as empty", async ({
  page,
}) => {
  const world = makeWorld()
  world.historyStatus = 503
  await serveWorld(page, world)
  await openPage(page)
  const panel = await openFull(page)
  const details = await openHistory(panel)
  await expect(
    details.getByText(
      "Revision history could not be read. No snapshot content is shown.",
    ),
  ).toBeVisible()
  await expect(
    details.getByText("No revision history is available for this report yet."),
  ).toHaveCount(0)
  world.historyStatus = 0
  await details
    .getByRole("button", { name: "Re-read revision history", exact: true })
    .click()
  await expect(details.getByText("Recorded snapshots")).toBeVisible()
})

test("a revision conflict keeps the old draft, rereads without rebasing, and restarts explicitly", async ({
  page,
}) => {
  const world = makeWorld({ revision: 1 })
  world.onPatch = (report) => {
    const next = structuredClone(world.reports[report.id] ?? report)
    next.revision = 2
    next.text = managementText("new")
    world.reports[report.id] = next
    return { status: 409, body: conflictBody }
  }
  await serveWorld(page, world)
  await openPage(page)
  const panel = await openFull(page)
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  await panel
    .getByLabel("Interpretation · shared")
    .fill("My unsaved operator text.")
  await panel
    .getByRole("button", { name: "Save report revision", exact: true })
    .click()
  await expect(
    panel.getByText(
      "This version changed since it was read. Your unsaved edits are kept; re-read the same version before saving or confirming again.",
    ),
  ).toBeVisible()
  await expect(panel.getByLabel("Interpretation · shared")).toHaveValue(
    "My unsaved operator text.",
  )
  await expect(
    panel.getByRole("button", { name: "Save report revision", exact: true }),
  ).toBeDisabled()
  expect(world.patchCount).toBe(1)

  await panel
    .getByRole("button", { name: "Re-read this report", exact: true })
    .click()
  await expect(
    panel.getByText(
      "The same report is readable at draft revision 2. Your text was not rebased; copy it if needed, then explicitly discard and restart.",
    ),
  ).toBeVisible()
  await expect(panel.getByLabel("Interpretation · shared")).toHaveValue(
    "My unsaved operator text.",
  )
  await expect(
    panel.getByRole("button", { name: "Save report revision", exact: true }),
  ).toBeDisabled()
  expect(world.patchCount).toBe(1)

  world.onPatch = null
  await panel
    .getByRole("button", {
      name: "Discard and restart from latest revision",
      exact: true,
    })
    .click()
  await expect(panel.getByLabel("Interpretation · shared")).toHaveValue(
    "Shared claim new text.",
  )
  await expect(
    panel.getByRole("button", { name: "Save report revision", exact: true }),
  ).toBeDisabled()
  await panel
    .getByLabel("Interpretation · check")
    .fill("Second explicit save text.")
  await panel
    .getByRole("button", { name: "Save report revision", exact: true })
    .click()
  await expect.poll(() => world.patchCount).toBe(2)
  expect(world.patchBodies[1]?.expected_revision).toBe(2)
  expect(world.patchBodies[1]?.edits?.check).toBe("Second explicit save text.")
})

test("a report confirmed during editing keeps copyable text and blocks blind retry", async ({
  page,
}) => {
  const world = makeWorld({ revision: 1 })
  world.onPatch = (report) => {
    const next = structuredClone(world.reports[report.id] ?? report)
    next.revision = 2
    next.status = "CONFIRMED"
    next.confirmed_at = "2026-10-08T00:04:00Z"
    next.text = managementText("new")
    world.reports[report.id] = next
    return { status: 409, body: conflictBody }
  }
  await serveWorld(page, world)
  await openPage(page)
  const panel = await openFull(page)
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  await panel
    .getByLabel("Interpretation · shared")
    .fill("User text kept for copy.")
  await panel
    .getByRole("button", { name: "Save report revision", exact: true })
    .click()
  await panel
    .getByRole("button", { name: "Re-read this report", exact: true })
    .click()
  const copy = panel.getByRole("region", { name: "Unsaved draft text" })
  await expect(copy).toBeVisible()
  await expect(copy).toContainText("User text kept for copy.")
  await expect(
    panel.getByRole("button", { name: "Save report revision", exact: true }),
  ).toHaveCount(0)
  await expect(
    panel.getByRole("button", {
      name: "Confirm this report version",
      exact: true,
    }),
  ).toHaveCount(0)
  await expect(panel.getByLabel("Interpretation · shared")).toHaveCount(0)
  expect(world.patchCount).toBe(1)
  await copy.getByRole("button", { name: "Discard draft", exact: true }).click()
  await expect(copy).toHaveCount(0)
  await expect(
    panel.getByText("Confirmed report version", { exact: true }),
  ).toBeVisible()
  expect(world.patchCount).toBe(1)
})

test("a temporary reread failure keeps the draft and a later refusal clears it", async ({
  page,
}) => {
  const world = makeWorld({ revision: 1 })
  world.onPatch = (report) => {
    const next = structuredClone(world.reports[report.id] ?? report)
    next.revision = 2
    next.text = managementText("new")
    world.reports[report.id] = next
    return { status: 409, body: conflictBody }
  }
  await serveWorld(page, world)
  await openPage(page)
  const panel = await openFull(page)
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  await panel
    .getByLabel("Interpretation · shared")
    .fill("Draft survives all rereads.")
  await panel
    .getByRole("button", { name: "Save report revision", exact: true })
    .click()
  world.rereadFailures.push({
    status: 503,
    body: { detail: { code: "synthetic_temporary", message: "synthetic" } },
  })
  await panel
    .getByRole("button", { name: "Re-read this report", exact: true })
    .click()
  await expect(
    panel.getByText(
      "This report could not be read temporarily. Your draft is kept; re-read the same report before saving or discarding.",
    ),
  ).toBeVisible()
  await expect(panel.getByLabel("Interpretation · shared")).toHaveValue(
    "Draft survives all rereads.",
  )
  await expect(
    panel.getByRole("button", { name: "Save report revision", exact: true }),
  ).toBeDisabled()
  await panel
    .getByRole("button", { name: "Re-read this report", exact: true })
    .click()
  await expect(
    panel.getByText(/The same report is readable at draft revision 2/),
  ).toBeVisible()
  expect(world.patchCount).toBe(1)
})

test("a delayed refusal clears a collapsed draft instead of reviving it", async ({
  page,
}) => {
  const world = makeWorld()
  await serveWorld(page, world)
  await openPage(page)
  const panel = await openFull(page)
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  await panel
    .getByLabel("Interpretation · shared")
    .fill("Collapsed draft must vanish.")
  let release = () => {}
  const promise = new Promise<void>((resolve) => {
    release = resolve
  })
  world.rereadGate = {
    promise,
    release,
    status: 410,
    body: expiredBody,
    hits: 0,
    fulfilled: 0,
  }
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  await expect.poll(() => world.rereadGate?.hits).toBe(1)
  await panel.getByRole("button", { name: "Show summary", exact: true }).click()
  release()
  await expect(
    panel.getByText(
      "This report's fixed material period has expired. Its summary, original, revisions and printing are unavailable; the C+A core remains readable.",
    ),
  ).toBeVisible()
  await expect(panel.getByLabel("Interpretation · shared")).toHaveCount(0)
  await expect(panel.getByText("Collapsed draft must vanish.")).toHaveCount(0)
  expect(world.rereadGate?.fulfilled).toBe(1)
  expect(world.patchCount).toBe(0)
})

test("375 and 390 pixels stay inside the viewport with wrapping editors and keyboard reachability", async ({
  page,
}) => {
  const world = makeWorld()
  world.reports[reportId] = reportFor(reportId, {
    revision: 2,
    text: managementText("long"),
  })
  world.history[reportId] = []
  await serveWorld(page, world)
  for (const width of [375, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await openPage(page)
    const panel = await openFull(page)
    expect(await navBeforeReportBody(page, reportId)).toBe(true)
    const read = await page.evaluate(() => {
      const region = document.querySelector(
        '[aria-label="AI interpretation for this comparison"]',
      )
      return {
        document: document.documentElement.scrollWidth,
        viewport: window.innerWidth,
        panel: region instanceof HTMLElement ? region.scrollWidth : 0,
        panelClient: region instanceof HTMLElement ? region.clientWidth : 0,
      }
    })
    expect(read.document).toBeLessThanOrEqual(read.viewport + 1)
    expect(read.panel).toBeLessThanOrEqual(read.panelClient + 1)
    await page.screenshot({
      path: `${screenshots}/item10-report-${width}-read.png`,
      fullPage: true,
    })

    const nav = panel.getByRole("navigation", { name: "Report chapters" })
    await nav.getByRole("button").first().focus()
    const readFocus: string[] = []
    for (let index = 0; index < 40; index++) {
      await page.keyboard.press("Tab")
      const descriptor = await page.evaluate(() => {
        const element = document.activeElement
        if (!(element instanceof HTMLElement)) return ""
        return `${element.tagName}|${element.getAttribute("aria-label") ?? ""}|${(element.textContent ?? "").trim().slice(0, 80)}`
      })
      readFocus.push(descriptor)
      if (descriptor.includes("Human revision history")) break
    }
    expect(
      readFocus.some((value) => value.includes("Edit interpretation")),
    ).toBe(true)
    expect(
      readFocus.some((value) => value.includes("Confirm this report version")),
    ).toBe(true)
    expect(
      readFocus.some((value) => value.includes("Human revision history")),
    ).toBe(true)

    await panel
      .getByRole("button", { name: "Edit interpretation", exact: true })
      .click()
    expect(await navBeforeReportBody(page, reportId)).toBe(true)
    await panel
      .getByLabel("Interpretation · shared")
      .fill("Keyboard reachable edit.")
    const boxes = await panel
      .getByLabel(/^Interpretation · /)
      .evaluateAll((elements) =>
        elements.map((element) => {
          const box = element.getBoundingClientRect()
          return {
            left: box.left,
            right: box.right,
            scroll: element.scrollWidth,
            client: element.clientWidth,
          }
        }),
      )
    for (const box of boxes) {
      expect(box.left).toBeGreaterThanOrEqual(-1)
      expect(box.right).toBeLessThanOrEqual(width + 1)
      expect(box.scroll).toBeLessThanOrEqual(box.client + 1)
    }
    await nav.getByRole("button").first().focus()
    const editFocus: string[] = []
    for (let index = 0; index < 60; index++) {
      await page.keyboard.press("Tab")
      const descriptor = await page.evaluate(() => {
        const element = document.activeElement
        if (!(element instanceof HTMLElement)) return ""
        return `${element.tagName}|${element.getAttribute("aria-label") ?? ""}|${(element.textContent ?? "").trim().slice(0, 80)}`
      })
      editFocus.push(descriptor)
      if (descriptor.includes("Human revision history")) break
    }
    expect(
      editFocus.some((value) => value.includes("Interpretation · shared")),
    ).toBe(true)
    expect(
      editFocus.some((value) => value.includes("Save report revision")),
    ).toBe(true)
    expect(editFocus.some((value) => value.includes("Cancel edits"))).toBe(true)
    expect(
      editFocus.some((value) => value.includes("Human revision history")),
    ).toBe(true)
    const edit = await page.evaluate(() => {
      const region = document.querySelector(
        '[aria-label="AI interpretation for this comparison"]',
      )
      return {
        document: document.documentElement.scrollWidth,
        viewport: window.innerWidth,
        panel: region instanceof HTMLElement ? region.scrollWidth : 0,
        panelClient: region instanceof HTMLElement ? region.clientWidth : 0,
      }
    })
    expect(edit.document).toBeLessThanOrEqual(edit.viewport + 1)
    expect(edit.panel).toBeLessThanOrEqual(edit.panelClient + 1)
    await page.screenshot({
      path: `${screenshots}/item10-report-${width}-edit.png`,
      fullPage: true,
    })
  }
})

test("an unplaced claim edit appears in history with old and new prose and the unplaced chapter", async ({
  page,
}) => {
  const world = makeWorld()
  const before = structuredClone(managementText("new"))
  const beforeClaim = before.claims.find((claim) => claim.id === "unplaced")
  if (beforeClaim && beforeClaim.type !== "fact")
    beforeClaim.text = "Unplaced claim old text."
  const after = structuredClone(managementText("new"))
  world.reports[reportId] = reportFor(reportId, {
    revision: 2,
    text: structuredClone(before),
  })
  world.history[reportId] = [
    snapshot({
      id: "history-3",
      revision: 3,
      text: after,
      recordedAt: "2026-10-08T00:03:00Z",
    }),
    snapshot({
      id: "history-2",
      revision: 2,
      text: before,
      recordedAt: "2026-10-08T00:02:00Z",
    }),
  ]
  await serveWorld(page, world)
  await openPage(page)
  const panel = await openFull(page)
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  await expect(panel.getByLabel("Interpretation · unplaced")).toHaveCount(1)
  await panel
    .getByLabel("Interpretation · unplaced")
    .fill("Unplaced operator text.")
  await panel
    .getByRole("button", { name: "Save report revision", exact: true })
    .click()
  await expect.poll(() => world.patchCount).toBe(1)
  expect(world.patchBodies[0]?.expected_revision).toBe(2)
  expect(world.patchBodies[0]?.edits?.unplaced).toBe("Unplaced operator text.")
  expect(world.patchBodies[0]?.edits?.shared).toBe("Shared claim new text.")
  await expect(panel.getByLabel("Interpretation · unplaced")).toHaveCount(0)

  const details = await openHistory(panel)
  await expect(
    details.getByText("Full text changed between these adjacent revisions."),
  ).toBeVisible()
  const affected = details.getByText(/Affected chapters/)
  await expect(affected).toContainText("Not placed in a chapter")
  await expect(affected).not.toContainText("Not derived")
  const beforeRegion = details.getByRole("region", {
    name: "Before revision 2",
  })
  const afterRegion = details.getByRole("region", { name: "After revision 3" })
  await expect(beforeRegion).toContainText("Unplaced claim old text.")
  await expect(beforeRegion).toContainText("Not placed in a chapter")
  await expect(afterRegion).toContainText("Unplaced claim text.")
  await expect(afterRegion).toContainText("Not placed in a chapter")
  await expect(beforeRegion).not.toContainText("Unplaced claim text.")
  await expect(afterRegion).not.toContainText("Unplaced claim old text.")
})

test("server-valid repeated summary and section pointers render one canonical editor", async ({
  page,
}) => {
  const world = makeWorld()
  const repeated = managementText("new")
  repeated.summary = ["summary_only", "shared", "shared"]
  repeated.sections = repeated.sections.map((section) =>
    section.id === "differences"
      ? { ...section, claim_ids: ["shared", "check", "shared"] }
      : section.id === "priority" || section.id === "next_steps"
        ? { ...section, claim_ids: ["shared", "shared"] }
        : section,
  )
  const previous = structuredClone(repeated)
  const shared = previous.claims.find((claim) => claim.id === "shared")
  if (shared && shared.type !== "fact") shared.text = "Shared claim old text."
  world.reports[reportId] = reportFor(reportId, {
    revision: 2,
    text: structuredClone(repeated),
  })
  world.history[reportId] = [
    snapshot({ id: "history-2", revision: 2, text: repeated }),
    snapshot({ id: "history-1", revision: 1, text: previous }),
  ]
  const consoleErrors: string[] = []
  page.on("console", (message) => {
    if (message.type() === "error" && message.text().includes("same key"))
      consoleErrors.push(message.text())
  })
  await serveWorld(page, world)
  await openPage(page)
  const panel = await openFull(page)
  const details = await openHistory(panel)
  await expect(details.getByText("Recorded snapshots")).toBeVisible()
  await expect(
    details.getByText("Full text changed between these adjacent revisions."),
  ).toBeVisible()
  const affected = details.getByText(/Affected chapters/)
  await expect(affected).toContainText("Report summary")
  await expect(affected).toContainText("Main differences and their meaning")
  await expect(affected).not.toContainText("Not derived")
  await page.waitForTimeout(100)
  expect(consoleErrors).toEqual([])

  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  await expect(panel.getByLabel("Interpretation · shared")).toHaveCount(1)
  await expect(
    panel.getByText(
      "Also appears in: Report summary · Objects to verify first · Suggested next steps",
      { exact: true },
    ),
  ).toBeVisible()
})

test("selected and predecessor snapshots are validated against the current verified structure", async ({
  page,
}) => {
  const world = makeWorld()
  const current = structuredClone(managementText("new"))
  const corrupt = (text: Text): Text => {
    const value = structuredClone(text)
    const fact = value.claims.find((claim) => claim.id === "fixed")
    if (fact && fact.type === "fact")
      fact.fact_refs = ["fact:outside-verified-material"]
    return value
  }
  await serveWorld(page, world)

  const scenarios: Array<{
    label: string
    rows: Record<string, unknown>[]
    message: string
  }> = [
    {
      label: "initial corruption",
      rows: [
        snapshot({
          id: "history-1",
          revision: 1,
          text: corrupt(current),
          recordedAt: "2026-10-08T00:01:00Z",
        }),
      ],
      message:
        "Revision 1 does not match this report's current verified fixed structure. Its body is suppressed, and no changed or unchanged text is claimed.",
    },
    {
      label: "gap corruption",
      rows: [
        snapshot({
          id: "history-3",
          revision: 3,
          text: corrupt(current),
          recordedAt: "2026-10-08T00:03:00Z",
        }),
        snapshot({
          id: "history-1",
          revision: 1,
          text: managementText("old"),
          recordedAt: "2026-10-08T00:01:00Z",
        }),
      ],
      message:
        "Revision 3 does not match this report's current verified fixed structure. Its body is suppressed, and no changed or unchanged text is claimed.",
    },
    {
      label: "identically corrupted adjacent pair",
      rows: [
        snapshot({
          id: "history-2",
          revision: 2,
          text: corrupt(current),
          status: "CONFIRMED",
          recordedAt: "2026-10-08T00:02:00Z",
        }),
        snapshot({
          id: "history-1",
          revision: 1,
          text: corrupt(current),
          recordedAt: "2026-10-08T00:01:00Z",
        }),
      ],
      message:
        "Revision 2 does not match this report's current verified fixed structure. Its body is suppressed, and no changed or unchanged text is claimed.",
    },
  ]

  for (const scenario of scenarios) {
    world.history[reportId] = scenario.rows
    await openPage(page)
    const panel = await openFull(page)
    const details = await openHistory(panel)
    await expect(details.getByText("Recorded snapshots")).toBeVisible()
    await expect(
      details.getByText(scenario.message, { exact: true }),
    ).toBeVisible()
    await expect(
      details.getByRole("region", {
        name: /^(Before revision|Initial revision|Selected revision)/,
      }),
    ).toHaveCount(0)
    await expect(
      details.getByText("This adjacent step only confirmed the same text."),
    ).toHaveCount(0)
    await expect(
      details.getByText("Full text changed between these adjacent revisions."),
    ).toHaveCount(0)
    await expect(
      details.getByText(
        "No narrative text changed between these adjacent revisions.",
      ),
    ).toHaveCount(0)
  }

  world.history[reportId] = [
    snapshot({ id: "history-2", revision: 2, text: managementText("new") }),
    snapshot({
      id: "history-1",
      revision: 1,
      text: corrupt(managementText("old")),
      recordedAt: "2026-10-08T00:01:00Z",
    }),
  ]
  await openPage(page)
  let panel = await openFull(page)
  let details = await openHistory(panel)
  await expect(
    details.getByText(
      "Revision 1 does not match this report's current verified fixed structure, so no comparison is shown. Only the selected revision 2 body is shown, and no changed or unchanged text is claimed.",
      { exact: true },
    ),
  ).toBeVisible()
  const selected = details.getByRole("region", {
    name: "Selected revision 2",
  })
  await expect(selected).toBeVisible()
  await expect(selected).toContainText("Shared claim new text.")
  await expect(
    details.getByRole("region", { name: /^Before revision/ }),
  ).toHaveCount(0)
  await expect(
    details.getByText("Full text changed between these adjacent revisions."),
  ).toHaveCount(0)

  world.history[reportId] = [
    snapshot({ id: "history-2", revision: 2, text: managementText("new") }),
    snapshot({ id: "history-1", revision: 1, text: managementText("old") }),
  ]
  await openPage(page)
  panel = await openFull(page)
  details = await openHistory(panel)
  await expect(
    details.getByText("Full text changed between these adjacent revisions."),
  ).toBeVisible()
  await expect(
    details.getByRole("region", { name: "Before revision 1" }),
  ).toBeVisible()
  await expect(
    details.getByRole("region", { name: "After revision 2" }),
  ).toBeVisible()
  await expect(details.getByRole("alert")).toHaveCount(0)
})

test("history without current verified report text is explicitly unavailable", async ({
  page,
}) => {
  const world = makeWorld()
  world.reports[reportId] = {
    ...reportFor(reportId, { revision: 2 }),
    text: null,
  }
  await serveWorld(page, world)
  await openPage(page)
  const panel = await openFull(page)
  const details = await openHistory(panel)
  await expect(details.getByText("Recorded snapshots")).toBeVisible()
  await expect(
    details.getByText(
      "This report's current verified fixed structure is unavailable, so no revision body can be validated or shown.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(
    details.getByRole("region", {
      name: /^(Before revision|Initial revision|Selected revision)/,
    }),
  ).toHaveCount(0)
})

test("a late readable reread cannot restore a cleared draft after a 403 refusal", async ({
  page,
}) => {
  const world = makeWorld({ revision: 1 })
  world.onPatch = (report) => {
    const next = structuredClone(world.reports[report.id] ?? report)
    next.revision = 2
    next.text = managementText("new")
    world.reports[report.id] = next
    return { status: 409, body: conflictBody }
  }
  await serveWorld(page, world)
  await openPage(page)
  const panel = await openFull(page)
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  await panel.getByLabel("Interpretation · shared").fill("Race draft text.")
  await panel
    .getByRole("button", { name: "Save report revision", exact: true })
    .click()
  await expect(
    panel.getByText(
      "This version changed since it was read. Your unsaved edits are kept; re-read the same version before saving or confirming again.",
    ),
  ).toBeVisible()

  let release = () => {}
  const promise = new Promise<void>((resolve) => {
    release = resolve
  })
  world.rereadGate = {
    promise,
    release,
    status: 200,
    body: null,
    hits: 0,
    fulfilled: 0,
  }
  world.detailRefusal = {
    status: 403,
    body: { detail: "synthetic permission refusal" },
  }
  await panel
    .getByRole("button", { name: "Re-read this report", exact: true })
    .click()
  await expect.poll(() => world.rereadGate?.hits).toBe(1)
  await expect(
    panel.getByText(
      "This account is not allowed to read this report. Its summary, original, revisions and printing are unavailable; the C+A core remains readable.",
    ),
  ).toBeVisible({ timeout: 12000 })
  release()
  await expect.poll(() => world.rereadGate?.fulfilled).toBe(1)
  await page.waitForTimeout(200)
  expect(world.patchCount).toBe(1)

  world.detailRefusal = null
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  await expect(
    panel.getByText("Draft; review required", { exact: true }),
  ).toBeVisible()
  await expect(
    panel.getByRole("button", { name: "Save report revision", exact: true }),
  ).toHaveCount(0)
  await expect(
    panel.getByText(/The same report is readable at draft revision/),
  ).toHaveCount(0)

  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  await panel
    .getByLabel("Interpretation · shared")
    .fill("Fresh reread control.")
  world.onPatch = () => ({ status: 409, body: conflictBody })
  await panel
    .getByRole("button", { name: "Save report revision", exact: true })
    .click()
  await expect(
    panel.getByText(
      "This version changed since it was read. Your unsaved edits are kept; re-read the same version before saving or confirming again.",
    ),
  ).toBeVisible()
  world.onPatch = null
  await panel
    .getByRole("button", { name: "Re-read this report", exact: true })
    .click()
  await expect(
    panel.getByText(/The same report is readable at draft revision 2/),
  ).toBeVisible()
  await expect(panel.getByLabel("Interpretation · shared")).toHaveValue(
    "Fresh reread control.",
  )
})

test("a late readable reread cannot restore a cleared draft after a material 410 refusal", async ({
  page,
}) => {
  const world = makeWorld({ revision: 1 })
  world.onPatch = (report) => {
    const next = structuredClone(world.reports[report.id] ?? report)
    next.revision = 2
    next.text = managementText("new")
    world.reports[report.id] = next
    return { status: 409, body: conflictBody }
  }
  await serveWorld(page, world)
  await openPage(page)
  const panel = await openFull(page)
  await panel
    .getByRole("button", { name: "Edit interpretation", exact: true })
    .click()
  await panel
    .getByLabel("Interpretation · shared")
    .fill("Expiry race draft text.")
  await panel
    .getByRole("button", { name: "Save report revision", exact: true })
    .click()
  await expect(
    panel.getByText(
      "This version changed since it was read. Your unsaved edits are kept; re-read the same version before saving or confirming again.",
    ),
  ).toBeVisible()

  let release = () => {}
  const promise = new Promise<void>((resolve) => {
    release = resolve
  })
  world.rereadGate = {
    promise,
    release,
    status: 200,
    body: null,
    hits: 0,
    fulfilled: 0,
  }
  world.detailRefusal = { status: 410, body: expiredBody }
  await panel
    .getByRole("button", { name: "Re-read this report", exact: true })
    .click()
  await expect.poll(() => world.rereadGate?.hits).toBe(1)
  await expect(
    panel.getByText(
      "This report's fixed material period has expired. Its summary, original, revisions and printing are unavailable; the C+A core remains readable.",
    ),
  ).toBeVisible({ timeout: 12000 })
  release()
  await expect.poll(() => world.rereadGate?.fulfilled).toBe(1)
  await page.waitForTimeout(200)
  expect(world.patchCount).toBe(1)

  world.detailRefusal = null
  await panel
    .getByRole("button", { name: "Re-read report state", exact: true })
    .click()
  await expect(
    panel.getByText("Draft; review required", { exact: true }),
  ).toBeVisible()
  await expect(
    panel.getByRole("button", { name: "Save report revision", exact: true }),
  ).toHaveCount(0)
  await expect(
    panel.getByText(/The same report is readable at draft revision/),
  ).toHaveCount(0)
})
