import { expect, type Page, test } from "@playwright/test"

const projectId = "00000000-0000-0000-0000-000000000001"
const reportId = "10000000-0000-0000-0000-000000000001"
const runId = "20000000-0000-0000-0000-000000000001"
const userId = "30000000-0000-0000-0000-000000000001"
const findingId = "50000000-0000-0000-0000-000000000001"
const evidenceId = "60000000-0000-0000-0000-000000000001"
const draftId = "70000000-0000-0000-0000-000000000001"
const newDraftId = "70000000-0000-0000-0000-000000000002"
const completedAt = "2026-08-10T12:00:00Z"

function canonicalContent() {
  const entry = {
    coverage: "OPEN_BACKLOG",
    finding_id: findingId,
    finding_type: "UNOBSERVED_ASSET",
    canonical_ip: "198.51.100.10",
    transition_type: null,
    evidence_reference: {
      governance_run_id: runId,
      fact_type: "OBSERVATION",
      fact_id: evidenceId,
    },
  }
  return {
    schema_version: "deterministic-report-v1",
    report: {
      report_identity: {
        governance_run_id: runId,
        project_id: projectId,
        run_completed_at: completedAt,
        report_contract_version: "deterministic-report-v1",
        generation_mode: "DETERMINISTIC_TEMPLATE",
      },
      input_completeness: {
        complete: true,
        sources: [
          {
            source_type: "CUSTOMER_UPLOAD",
            source_snapshot_id: "snapshot-customer",
            content_sha256: "a".repeat(64),
            schema_version: "customer-v1",
            record_count: 1,
          },
          {
            source_type: "CLOUDATLAS",
            source_snapshot_id: "snapshot-cloudatlas",
            content_sha256: "b".repeat(64),
            schema_version: "cloudatlas-v1",
            record_count: 0,
          },
        ],
      },
      ip_consistency_summary: {
        customer_observed_asset_count: 1,
        cloudatlas_observed_asset_count: 0,
        matched_asset_count: 0,
        all_observed_ip_identities_matched: false,
        current_run_finding_count: 1,
        finding_counts: [
          { finding_type: "UNREPORTED_ASSET", count: 0 },
          { finding_type: "UNOBSERVED_ASSET", count: 1 },
        ],
      },
      current_run_lifecycle_changes: {
        total: 0,
        transition_counts: [
          { transition_type: "OPENED", count: 0 },
          { transition_type: "REOPENED", count: 0 },
          { transition_type: "CLOSED", count: 0 },
        ],
        changes: [],
      },
      open_backlog_as_of_run: {
        as_of_governance_run_id: runId,
        total: 1,
        finding_counts: [
          { finding_type: "UNREPORTED_ASSET", count: 0 },
          { finding_type: "UNOBSERVED_ASSET", count: 1 },
        ],
        findings: [],
      },
      bounded_evidence_examples: {
        selection_owner: "EVIDENCE_SELECTOR",
        max_selected_entries: 50,
        max_rendered_entries: 8,
      },
      finding_type_directions_and_limitations: {
        directions: [
          {
            finding_type: "UNREPORTED_ASSET",
            present: false,
            direction: "向客户系统补充资产记录",
          },
          {
            finding_type: "UNOBSERVED_ASSET",
            present: true,
            direction: "补充扫描目标并重新扫描",
          },
        ],
        limitations: [
          "未观测资产不表示资产不存在",
          "本报告不分配严重性、优先级、责任、置信度或根因",
          "本报告不构成已批准动作，也不提供资产级处置动作",
        ],
      },
      provenance: {
        governance_run_id: runId,
        processing_contract_version: "ip-v1",
        source_snapshot_ids: ["snapshot-customer", "snapshot-cloudatlas"],
        source_snapshot_hashes: ["a".repeat(64), "b".repeat(64)],
        finding_lifecycle_fact_count: 1,
      },
    },
    evidence_plan: {
      governance_run_id: runId,
      report_contract_version: "deterministic-report-v1",
      max_entries: 50,
      entries: [entry],
    },
  }
}

function modelOutput() {
  return {
    report_sha256: "c".repeat(64),
    summary: "One bounded customer-internal interpretation.",
    recommendations: [
      {
        finding_id: findingId,
        rescan_recommendation: "Verify the selected unobserved asset.",
        pending_verifications: ["Confirm the asset owner."],
        limitations: ["One bounded observation."],
        claims: [
          {
            claim_id: "claim-selected-finding",
            evidence_ids: [evidenceId],
          },
        ],
      },
    ],
  }
}

function draft(status: "REVIEWABLE" | "FAILED") {
  return {
    id: draftId,
    governance_report_id: reportId,
    governance_run_id: runId,
    report_sha256: "c".repeat(64),
    finding_ids: [findingId],
    status,
    failure_code: status === "FAILED" ? "model_run_failed" : null,
    agent_compose_run_id: "8".repeat(64),
    session_id: "9".repeat(64),
    model_output: status === "REVIEWABLE" ? modelOutput() : null,
    review_decision: null,
    operator_edited_output: null,
    reviewed_at: null,
    created_at: completedAt,
  }
}

function reportDetail(aiDraft = draft("REVIEWABLE")) {
  return {
    id: reportId,
    governance_run_id: runId,
    run_completed_at: completedAt,
    report_contract_version: "deterministic-report-v1",
    generation_mode: "DETERMINISTIC_TEMPLATE",
    html_sha256: "1".repeat(64),
    csv_sha256: "4".repeat(64),
    created_at: completedAt,
    canonical_content: canonicalContent(),
    evidence: [
      {
        id: "61000000-0000-0000-0000-000000000001",
        governance_run_id: runId,
        fact_type: "OBSERVATION",
        fact_id: evidenceId,
      },
    ],
    evidence_count: 1,
    evidence_max_entries: 50,
    can_request_ai_governance_draft: true,
    ai_governance_drafts: [aiDraft],
  }
}

function reportList() {
  return {
    data: [
      {
        id: reportId,
        governance_run_id: runId,
        run_completed_at: completedAt,
        report_contract_version: "deterministic-report-v1",
        generation_mode: "DETERMINISTIC_TEMPLATE",
        html_sha256: "1".repeat(64),
        csv_sha256: "4".repeat(64),
        created_at: completedAt,
      },
    ],
    count: 1,
    page_size: 1,
    next_cursor: null,
    compatible: true,
    compatibility_code: null,
    latest_completed_run_id: runId,
    latest_completed_run_at: completedAt,
  }
}

async function installBaseMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "rel003-oracle-token")
  })
  await page.route("**/api/v1/users/me", (route) =>
    route.fulfill({
      json: {
        email: "operator@example.com",
        full_name: "Project Operator",
        id: userId,
        is_active: true,
        is_superuser: false,
      },
    }),
  )
  await page.route("**/api/v1/projects/**", async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === "/api/v1/projects/") {
      await route.fulfill({
        json: {
          data: [
            {
              name: "North Plant",
              id: projectId,
              tenant_id: "00000000-0000-0000-0000-000000000010",
              created_at: completedAt,
              updated_at: completedAt,
              archived_at: null,
            },
          ],
          count: 1,
        },
      })
      return
    }
    if (url.pathname.endsWith("/customer-upload-profile")) {
      await route.fulfill({
        json: {
          id: "40000000-0000-0000-0000-000000000001",
          version: 1,
          required_headers: ["资产IP"],
          warning_headers: [],
          optional_headers: [],
        },
      })
      return
    }
    if (url.pathname.endsWith("/customer-uploads")) {
      await route.fulfill({
        json: {
          data: [],
          count: 0,
          current_customer_upload_id: null,
          can_upload: false,
          can_select: false,
        },
      })
      return
    }
    await route.fallback()
  })
}

async function openReport(page: Page) {
  await page.goto("/")
  await page.getByRole("tab", { name: "Reports", exact: true }).click()
  await page.getByRole("button", { name: "Read report" }).click()
  return page.getByRole("dialog")
}

test.beforeEach(async ({ page }) => {
  await installBaseMocks(page)
})

test("Operator reviews immutable recommendations and completes one terminal decision", async ({
  page,
}) => {
  let terminal = false
  let reviewBody: unknown = null
  await page.route(
    new RegExp(
      `/api/v1/projects/${projectId}/governance-reports/${reportId}(?:\\?.*)?$`,
    ),
    (route) =>
      route.fulfill({
        json: reportDetail({
          ...draft("REVIEWABLE"),
          review_decision: terminal ? "ACCEPTED" : null,
          reviewed_at: terminal ? completedAt : null,
        }),
      }),
  )
  await page.route(
    new RegExp(
      `/api/v1/projects/${projectId}/governance-reports/${reportId}/ai-governance-drafts/${draftId}/review$`,
    ),
    async (route) => {
      reviewBody = route.request().postDataJSON()
      terminal = true
      await route.fulfill({
        json: {
          ...draft("REVIEWABLE"),
          review_decision: "ACCEPTED",
          reviewed_at: completedAt,
        },
      })
    },
  )
  await page.route(
    new RegExp(`/api/v1/projects/${projectId}/governance-reports(?:\\?.*)?$`),
    (route) => route.fulfill({ json: reportList() }),
  )

  const dialog = await openReport(page)
  await expect(
    dialog.getByText("Verify the selected unobserved asset."),
  ).toBeVisible()
  await expect(dialog.getByText(evidenceId)).toBeVisible()
  await expect(
    dialog.getByRole("button", { name: "Accept draft" }),
  ).toBeVisible()
  await expect(
    dialog.getByRole("button", { name: "Edit and accept draft" }),
  ).toBeVisible()
  await expect(
    dialog.getByRole("button", { name: "Reject draft" }),
  ).toBeVisible()

  await dialog.getByRole("button", { name: "Accept draft" }).click()

  await expect.poll(() => reviewBody).toEqual({ decision: "ACCEPTED" })
  await expect(dialog.getByText("Review ACCEPTED")).toBeVisible()
  await expect(
    dialog.getByRole("button", { name: "Accept draft" }),
  ).toHaveCount(0)
  await expect(
    dialog.getByText("Verify the selected unobserved asset."),
  ).toBeVisible()
})

test("failed history stays visible and only an explicit action starts a fresh attempt", async ({
  page,
}) => {
  let postCount = 0
  let idempotencyKey: string | null = null
  await page.route(
    new RegExp(
      `/api/v1/projects/${projectId}/governance-reports/${reportId}(?:\\?.*)?$`,
    ),
    (route) => route.fulfill({ json: reportDetail(draft("FAILED")) }),
  )
  await page.route(
    new RegExp(
      `/api/v1/projects/${projectId}/governance-reports/${reportId}/ai-governance-drafts$`,
    ),
    async (route) => {
      postCount += 1
      idempotencyKey = route.request().headers()["idempotency-key"] ?? null
      await route.fulfill({
        status: 202,
        json: {
          ...draft("REVIEWABLE"),
          id: newDraftId,
          status: "GENERATING",
          model_output: null,
        },
      })
    },
  )
  await page.route(
    new RegExp(`/api/v1/projects/${projectId}/governance-reports(?:\\?.*)?$`),
    (route) => route.fulfill({ json: reportList() }),
  )

  const dialog = await openReport(page)
  await expect(dialog.getByText("Failure: model_run_failed")).toBeVisible()
  await expect.poll(() => postCount).toBe(0)
  await dialog.getByLabel(new RegExp(findingId)).check()
  await dialog.getByRole("button", { name: "Start new attempt" }).click()

  await expect.poll(() => postCount).toBe(1)
  expect(idempotencyKey).toMatch(
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
  )
  await expect(dialog.getByText(`Draft ${newDraftId}`)).toBeVisible()
  await expect(dialog.getByText("Failure: model_run_failed")).toBeVisible()
})
