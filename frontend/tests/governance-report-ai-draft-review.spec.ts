import { expect, type Page, test } from "@playwright/test"

const projectId = "00000000-0000-0000-0000-000000000001"
const reportId = "10000000-0000-0000-0000-000000000001"
const runId = "20000000-0000-0000-0000-000000000001"
const findingId = "50000000-0000-0000-0000-000000000001"
const evidenceId = "60000000-0000-0000-0000-000000000001"
const draftId = "70000000-0000-0000-0000-000000000001"
const completedAt = "2026-08-10T12:00:00Z"

function reportDetail(
  reviewDecision: "ACCEPTED" | "EDITED" | "REJECTED" | null = null,
) {
  return {
    id: reportId,
    governance_run_id: runId,
    run_completed_at: completedAt,
    report_contract_version: "deterministic-report-v1",
    generation_mode: "DETERMINISTIC_TEMPLATE",
    html_sha256: "1".repeat(64),
    csv_sha256: "2".repeat(64),
    created_at: completedAt,
    canonical_content: {
      report: {
        report_identity: {
          governance_run_id: runId,
          run_completed_at: completedAt,
          report_contract_version: "deterministic-report-v1",
          generation_mode: "DETERMINISTIC_TEMPLATE",
        },
        input_completeness: { complete: true, sources: [] },
        ip_consistency_summary: {
          customer_observed_asset_count: 1,
          cloudatlas_observed_asset_count: 0,
          matched_asset_count: 0,
          all_observed_ip_identities_matched: false,
          current_run_finding_count: 1,
          finding_counts: [],
        },
        current_run_lifecycle_changes: {
          total: 0,
          transition_counts: [],
        },
        open_backlog_as_of_run: {
          as_of_governance_run_id: runId,
          total: 1,
          finding_counts: [],
        },
        bounded_evidence_examples: {
          selection_owner: "EVIDENCE_SELECTOR",
          max_rendered_entries: 8,
        },
        finding_type_directions_and_limitations: {
          directions: [],
          limitations: ["The deterministic report remains authoritative."],
        },
        provenance: {
          governance_run_id: runId,
          processing_contract_version: "ip-v1",
          source_snapshot_ids: [],
          source_snapshot_hashes: [],
          finding_lifecycle_fact_count: 1,
        },
      },
      evidence_plan: {
        entries: [
          {
            coverage: "OPEN_BACKLOG",
            finding_id: findingId,
            finding_type: "UNOBSERVED_ASSET",
            canonical_ip: "198.51.100.10",
            transition_type: null,
            evidence_reference: {
              fact_type: "OBSERVATION",
              fact_id: evidenceId,
            },
          },
        ],
      },
    },
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
    ai_governance_drafts: [
      {
        id: draftId,
        governance_report_id: reportId,
        report_sha256: "c".repeat(64),
        finding_ids: [findingId],
        status: "REVIEWABLE",
        failure_code: null,
        agent_compose_run_id: "8".repeat(64),
        session_id: "9".repeat(64),
        created_at: completedAt,
        model_output: {
          report_sha256: "c".repeat(64),
          summary: "One bounded interpretation.",
          recommendations: [
            {
              finding_id: findingId,
              rescan_recommendation: "Verify the selected asset.",
              pending_verifications: ["Confirm the asset owner."],
              limitations: ["Based on one report."],
              claims: [{ claim_id: "claim-1", evidence_ids: [evidenceId] }],
            },
          ],
        },
        review_decision: reviewDecision,
        reviewed_by: reviewDecision ? "operator-id" : null,
        reviewed_at: reviewDecision ? completedAt : null,
        operator_edited_output:
          reviewDecision === "EDITED"
            ? {
                findings: [
                  {
                    finding_id: findingId,
                    rescan_recommendation: "Verify with the owner.",
                    pending_verifications: [
                      "Confirm owner.",
                      "Confirm timing.",
                    ],
                    limitations: ["No remediation evidence."],
                  },
                ],
              }
            : null,
      },
    ],
  }
}

function reportList() {
  const { canonical_content: _canonical, ...detail } = reportDetail()
  const {
    evidence: _evidence,
    ai_governance_drafts: _drafts,
    ...summary
  } = detail
  return {
    data: [summary],
    count: 1,
    page_size: 1,
    next_cursor: null,
    compatible: true,
    compatibility_code: null,
    latest_completed_run_id: runId,
    latest_completed_run_at: completedAt,
  }
}

async function installShellMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "review-test-token")
  })
  await page.route("**/api/v1/users/me", (route) =>
    route.fulfill({
      json: {
        email: "operator@example.com",
        full_name: "Project Operator",
        id: "30000000-0000-0000-0000-000000000001",
        is_active: true,
        is_superuser: false,
      },
    }),
  )
  await page.route("**/api/v1/projects/**", async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === "/api/v1/projects/") {
      await route.fulfill({
        json: {
          data: [
            {
              id: projectId,
              name: "North Plant",
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
    if (path.endsWith("/customer-upload-profile")) {
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
    if (path.endsWith("/customer-uploads")) {
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
  await installShellMocks(page)
})

test("ACCEPTED review sends the narrow payload and keeps immutable output", async ({
  page,
}) => {
  let reviewBody: unknown = null
  await page.route(
    new RegExp(
      `/api/v1/projects/${projectId}/governance-reports/${reportId}(?:\\?.*)?$`,
    ),
    (route) => route.fulfill({ json: reportDetail() }),
  )
  await page.route(
    new RegExp(
      `/api/v1/projects/${projectId}/governance-reports/${reportId}/ai-governance-drafts/${draftId}/review$`,
    ),
    async (route) => {
      reviewBody = route.request().postDataJSON()
      await route.fulfill({
        json: reportDetail("ACCEPTED").ai_governance_drafts[0],
      })
    },
  )
  await page.route(
    new RegExp(`/api/v1/projects/${projectId}/governance-reports(?:\\?.*)?$`),
    (route) => route.fulfill({ json: reportList() }),
  )

  const dialog = await openReport(page)
  for (const name of [
    "Accept draft",
    "Edit and accept draft",
    "Reject draft",
  ]) {
    await expect(
      dialog.getByRole("button", { name, exact: true }),
    ).toBeVisible()
  }
  await dialog
    .getByRole("button", { name: "Accept draft", exact: true })
    .click()

  await expect.poll(() => reviewBody).toEqual({ decision: "ACCEPTED" })
  await expect(dialog.getByText("Review ACCEPTED")).toBeVisible()
  await expect(dialog.getByText("Verify the selected asset.")).toBeVisible()
  await expect(
    dialog.getByRole("button", { name: "Accept draft", exact: true }),
  ).toHaveCount(0)
})

test("EDITED review submits only editorial fields and survives a reload", async ({
  page,
}) => {
  let terminal = false
  let reviewBody: unknown = null
  await page.route(
    new RegExp(
      `/api/v1/projects/${projectId}/governance-reports/${reportId}(?:\\?.*)?$`,
    ),
    (route) =>
      route.fulfill({ json: reportDetail(terminal ? "EDITED" : null) }),
  )
  await page.route(
    new RegExp(
      `/api/v1/projects/${projectId}/governance-reports/${reportId}/ai-governance-drafts/${draftId}/review$`,
    ),
    async (route) => {
      reviewBody = route.request().postDataJSON()
      terminal = true
      await route.fulfill({
        json: reportDetail("EDITED").ai_governance_drafts[0],
      })
    },
  )
  await page.route(
    new RegExp(`/api/v1/projects/${projectId}/governance-reports(?:\\?.*)?$`),
    (route) => route.fulfill({ json: reportList() }),
  )

  let dialog = await openReport(page)
  await dialog
    .getByRole("button", { name: "Edit and accept draft", exact: true })
    .click()
  await dialog
    .getByLabel(`Recommendation for Finding ${findingId}`)
    .fill("Verify with the owner.")
  await dialog
    .getByLabel(`Pending confirmations for Finding ${findingId}`)
    .fill("Confirm owner.\nConfirm timing.")
  await dialog
    .getByLabel(`Limitations for Finding ${findingId}`)
    .fill("No remediation evidence.")
  await dialog
    .getByRole("button", { name: "Submit edited review", exact: true })
    .click()

  await expect
    .poll(() => reviewBody)
    .toEqual({
      decision: "EDITED",
      edited_output: {
        findings: [
          {
            finding_id: findingId,
            rescan_recommendation: "Verify with the owner.",
            pending_verifications: ["Confirm owner.", "Confirm timing."],
            limitations: ["No remediation evidence."],
          },
        ],
      },
    })
  await expect(dialog.getByText("Review EDITED")).toBeVisible()

  await page.reload()
  dialog = await openReport(page)
  await expect(dialog.getByText("Review EDITED")).toBeVisible()
  await expect(
    dialog.getByRole("button", { name: "Accept draft", exact: true }),
  ).toHaveCount(0)
  const immutableRecommendation = dialog.getByTestId("ai-draft-recommendation")
  await expect(
    immutableRecommendation.getByText(findingId, { exact: true }),
  ).toBeVisible()
  await expect(
    immutableRecommendation.getByRole("link", {
      name: `Evidence citation ${evidenceId}`,
      exact: true,
    }),
  ).toBeVisible()
})

test("REJECTED review is single-submit and removes every terminal control", async ({
  page,
}) => {
  let reviewBody: unknown = null
  let reviewCount = 0
  await page.route(
    new RegExp(
      `/api/v1/projects/${projectId}/governance-reports/${reportId}(?:\\?.*)?$`,
    ),
    (route) => route.fulfill({ json: reportDetail() }),
  )
  await page.route(
    new RegExp(
      `/api/v1/projects/${projectId}/governance-reports/${reportId}/ai-governance-drafts/${draftId}/review$`,
    ),
    async (route) => {
      reviewCount += 1
      reviewBody = route.request().postDataJSON()
      await new Promise((resolve) => setTimeout(resolve, 200))
      await route.fulfill({
        json: reportDetail("REJECTED").ai_governance_drafts[0],
      })
    },
  )
  await page.route(
    new RegExp(`/api/v1/projects/${projectId}/governance-reports(?:\\?.*)?$`),
    (route) => route.fulfill({ json: reportList() }),
  )

  const dialog = await openReport(page)
  await dialog
    .getByRole("button", { name: "Reject draft", exact: true })
    .click()
  await expect(
    dialog.getByRole("button", { name: "Reject draft", exact: true }),
  ).toBeDisabled()

  await expect.poll(() => reviewBody).toEqual({ decision: "REJECTED" })
  await expect.poll(() => reviewCount).toBe(1)
  await expect(dialog.getByText("Review REJECTED")).toBeVisible()
  for (const name of [
    "Accept draft",
    "Edit and accept draft",
    "Reject draft",
  ]) {
    await expect(dialog.getByRole("button", { name, exact: true })).toHaveCount(
      0,
    )
  }
})
