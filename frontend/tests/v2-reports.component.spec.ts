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

async function serve(page: Page, stateName = "READY", saved = false) {
  const state = {
    report: structuredClone(initialReport),
    saved,
    unreadable: false,
    createCalls: 0,
    patchCalls: 0,
    confirmCalls: 0,
    readCalls: 0,
    bodies: [] as object[],
    keys: [] as string[],
    loseReply: false,
  }
  await page.addInitScript(() =>
    localStorage.setItem("access_token", "synthetic-component-token"),
  )
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
    const value = () =>
      state.unreadable
        ? {
            ...state.report,
            readable: false,
            unavailable_reason: "v2_report_material_expired",
            text: null,
            original_output: null,
            material: null,
          }
        : state.report
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
        return route.fulfill({ status: 201, json: value() })
      }
      return route.fulfill({
        json: {
          data: state.saved
            ? [
                {
                  ...value(),
                  text: null,
                  original_output: null,
                  material: null,
                },
              ]
            : [],
          count: state.saved ? 1 : 0,
          can_create: stateName === "READY",
        },
      })
    }
    if (path.startsWith(`${root}/analysis-reports/v2/operations/`))
      return route.fulfill({ json: value() })
    if (path === `${root}/analysis-reports/v2/${reportId}/confirm`) {
      state.confirmCalls++
      state.report.status = "CONFIRMED"
      state.report.revision++
      state.report.confirmed_at = "2026-10-08T00:02:00Z"
      return route.fulfill({ json: value() })
    }
    if (path === `${root}/analysis-reports/v2/${reportId}/revisions`)
      return route.fulfill({ json: [] })
    if (path === `${root}/analysis-reports/v2/${reportId}`) {
      if (request.method() === "PATCH") {
        state.patchCalls++
        state.report.revision++
        const body = request.postDataJSON()
        state.report.text = structuredClone(state.report.text)
        state.report.text.claims[1].text = body.edits.check
        return route.fulfill({ json: value() })
      }
      state.readCalls++
      return route.fulfill({ json: value() })
    }
    return route.fulfill({ json: { data: [], count: 0, can_manage: false } })
  })
  return state
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
