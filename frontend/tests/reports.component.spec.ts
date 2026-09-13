import { writeFileSync } from "node:fs"
import { expect, type Page, test } from "./fixtures"

const projectId = "00000000-0000-0000-0000-000000000001"
const completedAt = "2026-08-10T12:00:00Z"
const reportIds = [
  "10000000-0000-0000-0000-000000000001",
  "10000000-0000-0000-0000-000000000002",
  "10000000-0000-0000-0000-000000000003",
]
const runIds = [
  "20000000-0000-0000-0000-000000000001",
  "20000000-0000-0000-0000-000000000002",
  "20000000-0000-0000-0000-000000000003",
]
const draftFindingId = "50000000-0000-0000-0000-000000000001"
const draftEvidenceId = "60000000-0000-0000-0000-000000000001"
const draftId = "70000000-0000-0000-0000-000000000001"
const draftRunId = "8".repeat(64)
const draftSessionId = "9".repeat(64)
const governanceReportsPath = new RegExp(
  `/api/v1/projects/${projectId}/governance-reports(?:/.*)?(?:\\?.*)?$`,
)
async function openReport(page: Page, navigate = true) {
  if (navigate) {
    await page.goto(`/?project=${projectId}&run=${runIds[0]}&view=reports`)
  }
  return page.getByRole("region", {
    name: /Published deterministic report|已发布的确定性报告/,
    exact: true,
  })
}
function reportSummary(index: number) {
  return {
    id: reportIds[index],
    governance_run_id: runIds[index],
    run_completed_at: completedAt,
    report_contract_version: "deterministic-report-v1",
    generation_mode: "DETERMINISTIC_TEMPLATE",
    html_sha256: String(index + 1).repeat(64),
    csv_sha256: String(index + 4).repeat(64),
    created_at: completedAt,
  }
}

function canonicalContent({ zeroFindings = false } = {}) {
  const findingCount = zeroFindings ? 0 : 9
  const entries = Array.from({ length: findingCount }, (_, index) => ({
    coverage: index === 0 ? "CURRENT_RUN_TRANSITION" : "OPEN_BACKLOG",
    finding_id:
      index === 0 ? "<img src=x onerror=alert('finding')>" : `finding-${index}`,
    finding_type: "UNOBSERVED_ASSET",
    canonical_ip: `198.51.100.${index + 1}`,
    transition_type: index === 0 ? "OPENED" : null,
    evidence_reference: {
      governance_run_id: runIds[0],
      fact_type: "OBSERVATION",
      fact_id:
        index === 0 ? "<script>alert('evidence')</script>" : `fact-${index}`,
    },
  }))

  return {
    schema_version: "deterministic-report-v1",
    report: {
      report_identity: {
        governance_run_id: runIds[0],
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
            schema_version: "<b>customer-v1</b>",
            record_count: zeroFindings ? 2 : 9,
          },
          {
            source_type: "CLOUDATLAS",
            source_snapshot_id: "snapshot-cloudatlas",
            content_sha256: "b".repeat(64),
            schema_version: "cloudatlas-v1",
            record_count: zeroFindings ? 2 : 0,
          },
        ],
      },
      ip_consistency_summary: {
        customer_observed_asset_count: zeroFindings ? 2 : 9,
        cloudatlas_observed_asset_count: zeroFindings ? 2 : 0,
        matched_asset_count: zeroFindings ? 2 : 0,
        all_observed_ip_identities_matched: zeroFindings,
        current_run_finding_count: findingCount,
        finding_counts: [
          { finding_type: "UNREPORTED_ASSET", count: 0 },
          { finding_type: "UNOBSERVED_ASSET", count: findingCount },
        ],
      },
      current_run_lifecycle_changes: {
        total: zeroFindings ? 0 : 1,
        transition_counts: [
          { transition_type: "OPENED", count: zeroFindings ? 0 : 1 },
          { transition_type: "REOPENED", count: 0 },
          { transition_type: "CLOSED", count: 0 },
        ],
        changes: [],
      },
      open_backlog_as_of_run: {
        as_of_governance_run_id: runIds[0],
        total: findingCount,
        finding_counts: [
          { finding_type: "UNREPORTED_ASSET", count: 0 },
          { finding_type: "UNOBSERVED_ASSET", count: findingCount },
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
            present: !zeroFindings,
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
        governance_run_id: runIds[0],
        processing_contract_version: "ip-v1<script>alert('contract')</script>",
        source_snapshot_ids: ["snapshot-customer", "snapshot-cloudatlas"],
        source_snapshot_hashes: ["a".repeat(64), "b".repeat(64)],
        finding_lifecycle_fact_count: findingCount,
      },
    },
    evidence_plan: {
      governance_run_id: runIds[0],
      report_contract_version: "deterministic-report-v1",
      max_entries: 50,
      entries,
    },
  }
}
function v2ReportDetail() {
  const canonical = canonicalContent({ zeroFindings: true })
  return {
    ...reportSummary(0),
    report_contract_version: "deterministic-report-v2",
    canonical_content: {
      ...canonical,
      schema_version: "deterministic-report-v2",
      report: {
        ...canonical.report,
        report_identity: {
          ...canonical.report.report_identity,
          report_contract_version: "deterministic-report-v2",
        },
        input_completeness: {
          ...canonical.report.input_completeness,
          sources: [
            ...canonical.report.input_completeness.sources,
            {
              source_type: "NETFLOW",
              source_snapshot_id: "snapshot-netflow",
              content_sha256: "c".repeat(64),
              schema_version: "netflow-ip-activity-v1",
              record_count: 1,
            },
          ],
        },
        ip_source_comparison: {
          results: [
            {
              canonical_ip: "198.51.100.1",
              classification: "OBSERVED_IN_ALL_SOURCES",
              classification_reason: "comparison-only-marker",
            },
          ],
        },
        ip_source_comparison_summary: {
          resource_count: 47,
          classification_counts: {
            matched: 31,
            customer_upload_only: 9,
            cloudatlas_only: 6,
            neither_source_observed: 1,
          },
          netflow_status_counts: { ACTIVE: 5, UNKNOWN: 42 },
          netflow_reason_counts: {
            positive_activity_observed: 5,
            netflow_input_absent: 2,
            no_positive_activity_evidence: 40,
          },
        },
      },
      evidence_plan: {
        ...canonical.evidence_plan,
        report_contract_version: "deterministic-report-v2",
        comparison_entries: [],
      },
    },
    evidence: [],
    evidence_count: 0,
    evidence_max_entries: 50,
    can_request_ai_governance_draft: false,
    ai_governance_drafts: [],
  }
}

function draftReportDetail(status?: "GENERATING" | "REVIEWABLE" | "FAILED") {
  const canonical = canonicalContent()
  canonical.evidence_plan.entries[0] = {
    ...canonical.evidence_plan.entries[0],
    finding_id: draftFindingId,
    evidence_reference: {
      governance_run_id: runIds[0],
      fact_type: "OBSERVATION",
      fact_id: draftEvidenceId,
    },
  }
  const draft = status
    ? {
        id: draftId,
        governance_report_id: reportIds[0],
        governance_run_id: runIds[0],
        report_sha256: "a".repeat(64),
        initiated_by: "30000000-0000-0000-0000-000000000001",
        model_identity: "qualified-model",
        config_fingerprint: "b".repeat(64),
        agent_compose_run_id: draftRunId,
        session_id: draftSessionId,
        status,
        failure_code: status === "FAILED" ? "provider_failed" : null,
        finding_ids: [draftFindingId],
        created_at: completedAt,
        updated_at: completedAt,
      }
    : null
  return {
    ...reportSummary(0),
    canonical_content: canonical,
    evidence: canonical.evidence_plan.entries.map((entry, index) => ({
      id: `61000000-0000-0000-0000-${String(index + 1).padStart(12, "0")}`,
      fact_type: entry.evidence_reference.fact_type,
      fact_id: entry.evidence_reference.fact_id,
    })),
    evidence_count: 9,
    evidence_max_entries: 50,
    can_request_ai_governance_draft: true,
    ai_governance_drafts: draft ? [draft] : [],
  }
}

function reportListResponse() {
  return {
    data: [reportSummary(0)],
    count: 1,
    page_size: 1,
    next_cursor: null,
    compatible: true,
    compatibility_code: null,
    latest_completed_run_id: runIds[0],
    latest_completed_run_at: completedAt,
  }
}

async function installBaseMocks(page: Page) {
  await page.route("**/api/v1/model-connections/status", (route) =>
    route.fulfill({
      json: {
        state: "active",
        configured: true,
        ready: true,
        model_identity: "fixture-current-model",
        active_version_id: "80000000-0000-4000-8000-000000000002",
      },
    }),
  )
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "component-token")
  })
  await page.route("**/api/v1/users/me", (route) =>
    route.fulfill({
      json: {
        email: "viewer@example.com",
        full_name: "Test Viewer",
        id: "30000000-0000-0000-0000-000000000001",
        is_active: true,
        is_superuser: false,
      },
    }),
  )
  await page.route("**/api/v1/projects/**", async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith("/analysis-reports")) {
      await route.fulfill({ json: { data: [], count: 0, can_create: false } })
      return
    }
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
    if (url.pathname.endsWith("/netflow-datasets")) {
      await route.fulfill({
        json: {
          data: [],
          count: 0,
          current_netflow_dataset_id: null,
          current_netflow_dataset: null,
          can_upload: false,
          can_select: false,
        },
      })
      return
    }
    await route.fallback()
  })
}

test.describe("Project Reports", () => {
  test.beforeEach(async ({ page }) => {
    await installBaseMocks(page)
  })

  test("does not offer a copy action for unavailable source metadata", async ({
    page,
  }) => {
    const canonical = canonicalContent()
    canonical.report.input_completeness.sources[0].content_sha256 = ""
    await page.route(governanceReportsPath, (route) =>
      route.fulfill({
        json: route.request().url().includes(`/${reportIds[0]}`)
          ? { ...draftReportDetail(), canonical_content: canonical }
          : reportListResponse(),
      }),
    )
    const report = await openReport(page)
    const source = report.locator("#report-input-completeness details").first()
    await source.locator("summary").focus()
    await page.keyboard.press("Enter")
    const hash = source.locator("div").filter({
      has: page.locator("dt").getByText("Content SHA-256", { exact: true }),
    })
    await expect(hash.getByText("Not available", { exact: true })).toBeVisible()
    await expect(hash.getByRole("button")).toHaveCount(0)
    await expect(
      source.getByText("snapshot-customer", { exact: true }),
    ).toBeVisible()
  })

  test("loads opaque cursor pages and pins an older published run", async ({
    page,
  }) => {
    const requestedCursors: Array<string | null> = []
    await page.route(governanceReportsPath, (route) => {
      const url = new URL(route.request().url())
      const reportIndex = reportIds.findIndex((id) =>
        url.pathname.endsWith(`/${id}`),
      )
      if (reportIndex !== -1) {
        const canonical = canonicalContent({ zeroFindings: true })
        canonical.report.report_identity.governance_run_id = runIds[reportIndex]
        canonical.report.open_backlog_as_of_run.as_of_governance_run_id =
          runIds[reportIndex]
        canonical.report.provenance.governance_run_id = runIds[reportIndex]
        canonical.evidence_plan.governance_run_id = runIds[reportIndex]
        return route.fulfill({
          json: {
            ...reportSummary(reportIndex),
            canonical_content: canonical,
            evidence: [],
            evidence_count: 0,
            evidence_max_entries: 50,
            can_request_ai_governance_draft: false,
          },
        })
      }
      const cursor = url.searchParams.get("cursor")
      requestedCursors.push(cursor)
      const secondPage = cursor === "opaque-tied-page-2"
      return route.fulfill({
        json: {
          data: secondPage
            ? [reportSummary(2)]
            : [reportSummary(0), reportSummary(1)],
          count: 3,
          page_size: secondPage ? 1 : 2,
          next_cursor: secondPage ? null : "opaque-tied-page-2",
          compatible: true,
          compatibility_code: null,
          latest_completed_run_id: runIds[0],
          latest_completed_run_at: completedAt,
        },
      })
    })

    const report = await openReport(page)
    const runSelector = page.getByRole("combobox", {
      name: "Published run",
      exact: true,
    })
    await expect(runSelector).toHaveValue(runIds[0])
    await runSelector.selectOption(runIds[2])
    await expect(page).toHaveURL(new RegExp(`run=${runIds[2]}`))
    await report
      .getByText("View evidence · Report identity", { exact: true })
      .press("Enter")
    await expect(
      report.locator("#report-identity").getByText(runIds[2], { exact: true }),
    ).toBeVisible()
    await expect(report).not.toContainText(runIds[0])
    await page.goBack()
    await expect(runSelector).toHaveValue(runIds[0])
    await report
      .getByText("View evidence · Report identity", { exact: true })
      .press("Enter")
    await expect(
      report.locator("#report-identity").getByText(runIds[0], { exact: true }),
    ).toBeVisible()
    expect(requestedCursors).toEqual([null, "opaque-tied-page-2"])
  })

  test("renders the fixed report safely with no more than eight Evidence cards", async ({
    page,
  }) => {
    const requestedPaths: string[] = []
    await page.route(
      new RegExp(
        `/api/v1/projects/${projectId}/governance-reports(?:/.*)?(?:\\?.*)?$`,
      ),
      (route) => {
        const url = new URL(route.request().url())
        requestedPaths.push(url.pathname)
        if (url.pathname.endsWith(`/${reportIds[0]}`)) {
          return route.fulfill({
            json: {
              ...reportSummary(0),
              canonical_content: canonicalContent(),
              evidence: [],
              evidence_count: 9,
              evidence_max_entries: 50,
            },
          })
        }
        return route.fulfill({
          json: {
            data: [reportSummary(0)],
            count: 1,
            page_size: 1,
            next_cursor: null,
            compatible: true,
            compatibility_code: null,
            latest_completed_run_id: runIds[0],
            latest_completed_run_at: completedAt,
          },
        })
      },
    )

    const report = await openReport(page)

    await expect(report.getByText("未观测资产不表示资产不存在")).toBeVisible()
    await expect(report.locator("[data-testid='evidence-card']")).toHaveCount(8)
    await expect(report.getByText("finding-8", { exact: true })).toHaveCount(0)
    const firstEvidence = report.getByTestId("evidence-card").first()
    await expect(
      firstEvidence.getByText("<script>alert('evidence')</script>", {
        exact: true,
      }),
    ).toBeHidden()
    await firstEvidence.locator("summary").press("Enter")
    await expect(
      firstEvidence.getByText("<script>alert('evidence')</script>", {
        exact: true,
      }),
    ).toBeVisible()
    await expect(report.locator("script, img")).toHaveCount(0)
    await expect(report.locator("#report-source-references")).toBeHidden()
    await firstEvidence
      .getByRole("link", { name: "Evidence provenance" })
      .press("Enter")
    await expect(report.locator("#report-source-references")).toBeVisible()
    expect(requestedPaths).toEqual([
      `/api/v1/projects/${projectId}/governance-reports`,
      `/api/v1/projects/${projectId}/governance-reports/${reportIds[0]}`,
    ])
  })

  test("states the complete-input conclusion for a zero-Finding report", async ({
    page,
  }) => {
    await page.route(
      new RegExp(
        `/api/v1/projects/${projectId}/governance-reports(?:/.*)?(?:\\?.*)?$`,
      ),
      (route) => {
        const url = new URL(route.request().url())
        if (url.pathname.endsWith(`/${reportIds[0]}`)) {
          return route.fulfill({
            json: {
              ...reportSummary(0),
              canonical_content: canonicalContent({ zeroFindings: true }),
              evidence: [],
              evidence_count: 0,
              evidence_max_entries: 50,
            },
          })
        }
        return route.fulfill({
          json: {
            data: [reportSummary(0)],
            count: 1,
            page_size: 1,
            next_cursor: null,
            compatible: true,
            compatibility_code: null,
            latest_completed_run_id: runIds[0],
            latest_completed_run_at: completedAt,
          },
        })
      },
    )

    const report = await openReport(page)

    await expect(
      report.getByText(
        "With CustomerUpload and CloudAtlas inputs complete, all IP identities observed by those sources matched; this Run produced zero Findings.",
      ),
    ).toBeVisible()
  })

  test("renders v2 source completeness without inventing a comparison matrix", async ({
    page,
  }) => {
    await page.route(governanceReportsPath, (route) => {
      const url = new URL(route.request().url())
      if (url.pathname.endsWith(`/${reportIds[0]}`)) {
        return route.fulfill({ json: v2ReportDetail() })
      }
      return route.fulfill({
        json: {
          ...reportListResponse(),
          data: [
            {
              ...reportSummary(0),
              report_contract_version: "deterministic-report-v2",
            },
          ],
        },
      })
    })

    const report = await openReport(page)
    const completeness = report.locator("#report-input-completeness")
    await expect(
      completeness.getByText(
        "All bounded input summaries are marked complete.",
      ),
    ).toBeVisible()
    for (const source of ["CUSTOMER_UPLOAD", "CLOUDATLAS", "NETFLOW"]) {
      await expect(
        completeness.getByText(source, { exact: true }),
      ).toBeVisible()
    }
    await expect(
      report.getByText(
        "AI governance drafts are not supported for deterministic-report-v2.",
      ),
    ).toBeVisible()
    await expect(
      report.getByText(
        "With CustomerUpload and CloudAtlas inputs complete, all IP identities observed by those sources matched; this Run produced zero Findings.",
      ),
    ).toBeVisible()
    await expect(
      report.getByRole("heading", { name: "IP source comparison" }),
    ).toHaveCount(0)
    await expect(report.getByText("comparison-only-marker")).toHaveCount(0)
    await expect(
      report.getByRole("button", { name: "Request AI draft" }),
    ).toHaveCount(0)
  })

  test("translates a known persisted draft failure without losing its identity", async ({
    page,
  }) => {
    const detail = draftReportDetail("FAILED")
    detail.ai_governance_drafts[0].failure_code = "model_binding_changed"
    await page.route(governanceReportsPath, (route) =>
      route.fulfill({
        json: new URL(route.request().url()).pathname.endsWith(
          `/${reportIds[0]}`,
        )
          ? detail
          : reportListResponse(),
      }),
    )
    const report = await openReport(page)
    await expect(report).toContainText("Failure: model_binding_changed")
    const persistedDraft = report
      .locator("#ai-governance-draft")
      .getByRole("status")
    await persistedDraft.locator("summary").press("Enter")
    await page
      .getByRole("combobox", { name: "Language / 语言" })
      .selectOption("zh-CN")
    await expect(report).toContainText(
      "model_binding_changed（草稿固定的模型绑定与当前部署配置不一致）",
    )
    await expect(
      persistedDraft.getByText(draftId, { exact: true }),
    ).toBeVisible()
    await expect(
      persistedDraft.getByText(draftSessionId, { exact: true }),
    ).toBeVisible()
    await page
      .getByRole("combobox", { name: "Language / 语言" })
      .selectOption("en")
    await expect(report).toContainText("Failure: model_binding_changed")
  })

  test("stops polling after the draft Session is bound", async ({ page }) => {
    let detailReads = 0
    let requested = false
    const postedBodies: unknown[] = []
    const requestKeys: string[] = []
    await page.route(governanceReportsPath, async (route) => {
      const request = route.request()
      const url = new URL(request.url())
      if (url.pathname.endsWith(`/${reportIds[0]}/ai-governance-drafts`)) {
        requested = true
        postedBodies.push(request.postDataJSON())
        requestKeys.push((await request.allHeaders())["idempotency-key"] ?? "")
        return route.fulfill({
          status: 202,
          json: draftReportDetail("GENERATING").ai_governance_drafts[0],
        })
      }
      if (url.pathname.endsWith(`/${reportIds[0]}`)) {
        detailReads += 1
        return route.fulfill({
          json: draftReportDetail(requested ? "GENERATING" : undefined),
        })
      }
      return route.fulfill({ json: reportListResponse() })
    })

    const report = await openReport(page)
    const requestButton = report.getByRole("button", {
      name: "Request AI draft",
    })
    await expect(report.getByText("0 of 8 selected")).toBeVisible()
    await expect(requestButton).toBeDisabled()

    await report.getByRole("checkbox").first().click()
    await expect(report.getByText("1 of 8 selected")).toBeVisible()
    await requestButton.click()

    const persistedDraft = report.locator(
      "#ai-governance-draft [role='status']",
    )
    await expect(persistedDraft.getByText("GENERATING")).toBeVisible()
    expect(postedBodies).toEqual([{ finding_ids: [draftFindingId] }])
    expect(requestKeys).toHaveLength(1)
    expect(requestKeys[0]).toMatch(/^[0-9a-f-]{36}$/)
    await expect.poll(() => detailReads).toBeGreaterThanOrEqual(2)
    const readsAfterSessionBinding = detailReads
    await page.waitForTimeout(2200)
    expect(detailReads).toBe(readsAfterSessionBinding)
  })

  test("refetches persisted report state when a draft request fails", async ({
    page,
  }) => {
    let detailReads = 0
    let postCount = 0
    await page.route(governanceReportsPath, (route) => {
      const request = route.request()
      const url = new URL(request.url())
      if (url.pathname.endsWith(`/${reportIds[0]}/ai-governance-drafts`)) {
        postCount += 1
        return route.fulfill({
          status: 503,
          json: {
            detail: {
              code: "agent_compose_session_pending",
              message: "Session identity is pending.",
            },
          },
        })
      }
      if (url.pathname.endsWith(`/${reportIds[0]}`)) {
        detailReads += 1
        return route.fulfill({
          json: draftReportDetail(postCount > 0 ? "FAILED" : undefined),
        })
      }
      return route.fulfill({ json: reportListResponse() })
    })

    const report = await openReport(page)
    await report.getByRole("checkbox").first().click()
    await report.getByRole("button", { name: "Request AI draft" }).click()

    await expect(
      report.getByRole("alert").getByText("Draft request could not be started"),
    ).toBeVisible()
    const persistedDraft = report.locator(
      "#ai-governance-draft [role='status']",
    )
    await expect(
      persistedDraft.getByText("FAILED", { exact: true }),
    ).toBeVisible()
    await persistedDraft.locator("summary").press("Enter")
    await expect(
      persistedDraft.getByText(draftId, { exact: true }),
    ).toBeVisible()
    await expect(
      persistedDraft.getByText("Failure: provider_failed"),
    ).toBeVisible()
    await expect(
      report.getByText(
        "A new draft attempt after failure is not available in this release.",
      ),
    ).toBeVisible()
    await expect(
      report.getByRole("button", { name: "Request AI draft" }),
    ).toHaveCount(0)
    await expect(report.getByRole("checkbox")).toHaveCount(0)
    await expect.poll(() => detailReads).toBeGreaterThanOrEqual(2)
    expect(postCount).toBe(1)
  })

  test("clears a rejected draft key after refresh confirms no draft exists", async ({
    page,
  }) => {
    let postCount = 0
    const requestKeys: string[] = []
    await page.route(governanceReportsPath, async (route) => {
      const request = route.request()
      const url = new URL(request.url())
      if (url.pathname.endsWith(`/${reportIds[0]}/ai-governance-drafts`)) {
        postCount += 1
        requestKeys.push((await request.allHeaders())["idempotency-key"] ?? "")
        return route.fulfill({
          status: 409,
          json: {
            detail: {
              code: "model_not_qualified",
              message: "The current model is not qualified.",
            },
          },
        })
      }
      if (url.pathname.endsWith(`/${reportIds[0]}`)) {
        return route.fulfill({ json: draftReportDetail() })
      }
      return route.fulfill({ json: reportListResponse() })
    })

    let report = await openReport(page)
    await report.getByRole("checkbox").first().click()
    await report.getByRole("button", { name: "Request AI draft" }).click()

    const storageKey = `exposure:ai-governance-draft:${projectId}:${reportIds[0]}:idempotency-key`
    await expect
      .poll(() =>
        page.evaluate((key) => window.sessionStorage.getItem(key), storageKey),
      )
      .toBeNull()

    await page.reload()
    report = await openReport(page, false)
    await expect(report.getByRole("checkbox").first()).toBeEnabled()
    expect(postCount).toBe(1)
    expect(requestKeys).toHaveLength(1)
  })

  test("clears a losing draft key after the active-generation conflict refresh", async ({
    page,
  }) => {
    const requestKeys: string[] = []
    let requestAttempted = false
    await page.route(governanceReportsPath, async (route) => {
      const request = route.request()
      const url = new URL(request.url())
      if (url.pathname.endsWith(`/${reportIds[0]}/ai-governance-drafts`)) {
        requestAttempted = true
        requestKeys.push((await request.allHeaders())["idempotency-key"] ?? "")
        return route.fulfill({
          status: 409,
          json: {
            detail: {
              code: "draft_generation_active",
              message: "This report already has an active draft generation.",
            },
          },
        })
      }
      if (url.pathname.endsWith(`/${reportIds[0]}`)) {
        return route.fulfill({
          json: draftReportDetail(requestAttempted ? "GENERATING" : undefined),
        })
      }
      return route.fulfill({ json: reportListResponse() })
    })

    const report = await openReport(page)
    await report.getByRole("checkbox").first().click()
    await report.getByRole("button", { name: "Request AI draft" }).click()

    const persistedDraft = report
      .locator("#ai-governance-draft")
      .getByRole("status")
    await persistedDraft.locator("summary").press("Enter")
    await expect(
      persistedDraft.getByText(draftId, { exact: true }),
    ).toBeVisible()
    await expect(
      report.getByRole("button", { name: "Resume your draft request" }),
    ).toHaveCount(0)
    await expect
      .poll(() =>
        page.evaluate(
          (key) => window.sessionStorage.getItem(key),
          `exposure:ai-governance-draft:${projectId}:${reportIds[0]}:idempotency-key`,
        ),
      )
      .toBeNull()
    expect(requestKeys).toHaveLength(1)
  })

  test("recovers a pending Session with the same key after a page reload", async ({
    page,
  }) => {
    let postCount = 0
    let recovered = false
    const requestKeys: string[] = []
    await page.route(governanceReportsPath, async (route) => {
      const request = route.request()
      const url = new URL(request.url())
      if (url.pathname.endsWith(`/${reportIds[0]}/ai-governance-drafts`)) {
        postCount += 1
        requestKeys.push((await request.allHeaders())["idempotency-key"] ?? "")
        if (postCount === 1) {
          return route.fulfill({
            status: 503,
            json: {
              detail: {
                code: "agent_compose_session_pending",
                message: "Session identity is pending.",
              },
            },
          })
        }
        recovered = true
        return route.fulfill({
          status: 200,
          json: draftReportDetail("GENERATING").ai_governance_drafts[0],
        })
      }
      if (url.pathname.endsWith(`/${reportIds[0]}`)) {
        if (postCount === 0) {
          return route.fulfill({ json: draftReportDetail() })
        }
        const detail = draftReportDetail("GENERATING")
        const pendingDraft = detail.ai_governance_drafts[0]
        if (!recovered && pendingDraft) pendingDraft.session_id = null
        return route.fulfill({ json: detail })
      }
      return route.fulfill({ json: reportListResponse() })
    })

    let report = await openReport(page)
    await report.getByRole("checkbox").first().click()
    await report.getByRole("button", { name: "Request AI draft" }).click()
    await expect(
      report.getByRole("alert").getByText("Draft request could not be started"),
    ).toBeVisible()

    await page.reload()
    report = await openReport(page, false)
    await report
      .getByRole("button", { name: "Resume your draft request" })
      .click()

    const persistedDraft = report
      .locator("#ai-governance-draft")
      .getByRole("status")
    await persistedDraft.locator("summary").press("Enter")
    await expect(
      persistedDraft.getByText(draftSessionId, { exact: true }),
    ).toBeVisible()
    expect(postCount).toBe(2)
    expect(requestKeys).toHaveLength(2)
    expect(requestKeys[0]).toMatch(/^[0-9a-f-]{36}$/)
    expect(requestKeys[1]).toBe(requestKeys[0])
  })

  test("replays its saved selection instead of an unrelated active draft", async ({
    page,
  }) => {
    let postCount = 0
    let recovered = false
    const postedBodies: unknown[] = []
    const requestKeys: string[] = []
    await page.route(governanceReportsPath, async (route) => {
      const request = route.request()
      const url = new URL(request.url())
      if (url.pathname.endsWith(`/${reportIds[0]}/ai-governance-drafts`)) {
        postCount += 1
        postedBodies.push(request.postDataJSON())
        requestKeys.push((await request.allHeaders())["idempotency-key"] ?? "")
        if (postCount === 1) {
          return route.fulfill({
            status: 503,
            json: {
              detail: {
                code: "agent_compose_session_pending",
                message: "Session identity is pending.",
              },
            },
          })
        }
        recovered = true
        return route.fulfill({
          status: 200,
          json: draftReportDetail("GENERATING").ai_governance_drafts[0],
        })
      }
      if (url.pathname.endsWith(`/${reportIds[0]}`)) {
        if (postCount === 0) {
          return route.fulfill({ json: draftReportDetail() })
        }
        if (recovered) {
          return route.fulfill({ json: draftReportDetail("GENERATING") })
        }
        const unrelated = draftReportDetail("GENERATING")
        const activeDraft = unrelated.ai_governance_drafts[0]
        if (activeDraft) {
          activeDraft.finding_ids = ["50000000-0000-0000-0000-000000000009"]
          activeDraft.session_id = null
        }
        return route.fulfill({ json: unrelated })
      }
      return route.fulfill({ json: reportListResponse() })
    })

    let report = await openReport(page)
    await report.getByRole("checkbox").first().click()
    await report.getByRole("button", { name: "Request AI draft" }).click()
    await expect(
      report.getByRole("alert").getByText("Draft request could not be started"),
    ).toBeVisible()

    await page.reload()
    report = await openReport(page, false)
    await report
      .getByRole("button", { name: "Resume your draft request" })
      .click()

    const persistedDraft = report
      .locator("#ai-governance-draft")
      .getByRole("status")
    await persistedDraft.locator("summary").press("Enter")
    await expect(
      persistedDraft.getByText(draftSessionId, { exact: true }),
    ).toBeVisible()
    expect(postedBodies).toEqual([
      { finding_ids: [draftFindingId] },
      { finding_ids: [draftFindingId] },
    ])
    expect(requestKeys).toHaveLength(2)
    expect(requestKeys[1]).toBe(requestKeys[0])
  })

  test("keeps an ambiguous request key when report refresh fails", async ({
    page,
  }) => {
    let postCount = 0
    let recoverAfterReload = false
    const requestKeys: string[] = []
    await page.route(governanceReportsPath, async (route) => {
      const request = route.request()
      const url = new URL(request.url())
      if (url.pathname.endsWith(`/${reportIds[0]}/ai-governance-drafts`)) {
        postCount += 1
        requestKeys.push((await request.allHeaders())["idempotency-key"] ?? "")
        if (postCount === 1) {
          return route.fulfill({
            status: 503,
            json: {
              detail: {
                code: "agent_compose_session_pending",
                message: "Session identity is pending.",
              },
            },
          })
        }
        return route.fulfill({
          status: 200,
          json: draftReportDetail("GENERATING").ai_governance_drafts[0],
        })
      }
      if (url.pathname.endsWith(`/${reportIds[0]}`)) {
        if (postCount > 0 && !recoverAfterReload) {
          return route.fulfill({
            status: 503,
            json: { detail: "unavailable" },
          })
        }
        return route.fulfill({
          json:
            postCount > 0
              ? draftReportDetail("GENERATING")
              : draftReportDetail(),
        })
      }
      return route.fulfill({ json: reportListResponse() })
    })

    let report = await openReport(page)
    const findings = report.getByRole("checkbox")
    await findings.first().click()
    await report.getByRole("button", { name: "Request AI draft" }).click()
    await expect(
      report.getByRole("alert").getByText("Draft request could not be started"),
    ).toBeVisible()
    await expect(
      report.getByRole("button", { name: "Resume your draft request" }),
    ).toBeVisible()
    await expect(
      report.getByRole("button", { name: "Request AI draft" }),
    ).toHaveCount(0)
    await expect(report.getByRole("checkbox")).toHaveCount(0)
    expect(postCount).toBe(1)
    expect(
      await page.evaluate(
        (key) => window.sessionStorage.getItem(key),
        `exposure:ai-governance-draft:${projectId}:${reportIds[0]}:idempotency-key`,
      ),
    ).toBe(
      JSON.stringify({
        idempotencyKey: requestKeys[0],
        findingIds: [draftFindingId],
      }),
    )

    recoverAfterReload = true
    await page.reload()
    report = await openReport(page, false)
    await report
      .getByRole("button", { name: "Resume your draft request" })
      .click()

    const persistedDraft = report
      .locator("#ai-governance-draft")
      .getByRole("status")
    await persistedDraft.locator("summary").press("Enter")
    await expect(
      persistedDraft.getByText(draftSessionId, { exact: true }),
    ).toBeVisible()
    expect(requestKeys).toHaveLength(2)
    expect(requestKeys[1]).toBe(requestKeys[0])
  })

  test("requires explicit selection and caps the request at eight Findings", async ({
    page,
  }) => {
    await page.route(governanceReportsPath, (route) => {
      const url = new URL(route.request().url())
      if (url.pathname.endsWith(`/${reportIds[0]}`)) {
        return route.fulfill({ json: draftReportDetail() })
      }
      return route.fulfill({ json: reportListResponse() })
    })

    const report = await openReport(page)
    const findings = report.getByRole("checkbox")

    await expect(findings).toHaveCount(9)
    await expect(report.getByText("0 of 8 selected")).toBeVisible()
    for (let index = 0; index < 8; index += 1) {
      await findings.nth(index).click()
    }
    await expect(report.getByText("8 of 8 selected")).toBeVisible()
    await expect(findings.nth(8)).toBeDisabled()

    await findings.nth(0).click()
    await expect(report.getByText("7 of 8 selected")).toBeVisible()
    await expect(findings.nth(8)).toBeEnabled()
  })

  test("removes cached report facts when a refresh returns masked access denial", async ({
    page,
  }) => {
    let accessRevoked = false
    await page.route(governanceReportsPath, (route) => {
      const pathname = new URL(route.request().url()).pathname
      if (pathname.endsWith("/ai-governance-drafts")) {
        accessRevoked = true
        return route.fulfill({ status: 404, json: { detail: "Not Found" } })
      }
      if (pathname.endsWith(`/${reportIds[0]}`)) {
        return accessRevoked
          ? route.fulfill({ status: 404, json: { detail: "Not Found" } })
          : route.fulfill({ json: draftReportDetail() })
      }
      return route.fulfill({ json: reportListResponse() })
    })
    const report = await openReport(page)
    await expect(report.locator("#report-ip-summary")).toBeVisible()
    await report.getByRole("checkbox").first().click()
    await report.getByRole("button", { name: "Request AI draft" }).click()
    await expect(report.getByRole("alert")).toContainText(
      "Report could not be loaded",
    )
    await expect(report.locator("#report-ip-summary")).toHaveCount(0)
    await expect(report.getByRole("checkbox")).toHaveCount(0)
    await expect(
      report.getByRole("button", { name: "Resume your draft request" }),
    ).toHaveCount(0)
  })
})

test.describe("Published overview", () => {
  test.beforeEach(async ({ page }) => {
    await installBaseMocks(page)
  })

  test("shows authoritative totals above 25 instead of counting comparison rows", async ({
    page,
  }) => {
    const detail = v2ReportDetail()
    await page.route(governanceReportsPath, (route) =>
      route.fulfill({
        json: new URL(route.request().url()).pathname.endsWith(
          `/${reportIds[0]}`,
        )
          ? detail
          : {
              ...reportListResponse(),
              data: [
                {
                  ...reportSummary(0),
                  report_contract_version: detail.report_contract_version,
                },
              ],
            },
      }),
    )
    await page.goto(`/?project=${projectId}&run=${runIds[0]}&view=overview`)
    const overview = page.getByRole("region", {
      name: "Published overview",
      exact: true,
    })
    await expect(
      overview
        .getByText("Compared resources", { exact: true })
        .locator("..")
        .locator("dd"),
    ).toHaveText("47")
    await expect(
      overview
        .getByText("matched", { exact: true })
        .locator("..")
        .locator("dd"),
    ).toHaveText("31")
    await expect(
      overview
        .getByText("UNKNOWN", { exact: true })
        .locator("..")
        .locator("dd"),
    ).toHaveText("42")
    await page.reload()
    await expect(
      overview
        .getByText("Compared resources", { exact: true })
        .locator("..")
        .locator("dd"),
    ).toHaveText("47")
  })

  test("marks unavailable legacy three-source counts as N/A rather than zero", async ({
    page,
  }) => {
    await page.route(governanceReportsPath, (route) =>
      route.fulfill({
        json: new URL(route.request().url()).pathname.endsWith(
          `/${reportIds[0]}`,
        )
          ? draftReportDetail()
          : reportListResponse(),
      }),
    )
    await page.goto(`/?project=${projectId}&run=${runIds[0]}&view=overview`)
    await expect(page.getByRole("alert")).toContainText(
      "Three-source summary: N/A",
    )
    await expect(
      page.getByText("Compared resources", { exact: true }),
    ).toHaveCount(0)
    await expect(
      page
        .getByRole("link", { name: "Assets & differences", exact: true })
        .last(),
    ).toHaveAttribute("href", new RegExp(`/runs/${runIds[0]}/comparison`))
  })

  test("fails closed when a v2 mandatory summary is missing", async ({
    page,
  }) => {
    const detail = v2ReportDetail()
    await page.route(governanceReportsPath, (route) =>
      route.fulfill({
        json: new URL(route.request().url()).pathname.endsWith(
          `/${reportIds[0]}`,
        )
          ? {
              ...detail,
              canonical_content: {
                ...detail.canonical_content,
                report: {
                  ...detail.canonical_content.report,
                  ip_source_comparison_summary: undefined,
                },
              },
            }
          : {
              ...reportListResponse(),
              data: [
                {
                  ...reportSummary(0),
                  report_contract_version: detail.report_contract_version,
                },
              ],
            },
      }),
    )
    await page.goto(`/?project=${projectId}&run=${runIds[0]}&view=overview`)
    await expect(page.getByRole("alert")).toContainText(
      "Published summary is not readable",
    )
    await expect(
      page.getByText("Compared resources", { exact: true }),
    ).toHaveCount(0)
    await expect(
      page.getByText("Three-source summary: N/A", { exact: true }),
    ).toHaveCount(0)
  })

  test("skips an incompatible latest result, pins the compatible run and never replaces an explicit unavailable run", async ({
    page,
  }) => {
    const probes: string[] = []
    const canonical = canonicalContent({ zeroFindings: true })
    canonical.report.report_identity.governance_run_id = runIds[1]
    canonical.report.open_backlog_as_of_run.as_of_governance_run_id = runIds[1]
    canonical.report.provenance.governance_run_id = runIds[1]
    canonical.evidence_plan.governance_run_id = runIds[1]
    await page.route(governanceReportsPath, (route) =>
      route.fulfill({
        json: new URL(route.request().url()).pathname.endsWith(
          `/${reportIds[1]}`,
        )
          ? {
              ...reportSummary(1),
              canonical_content: canonical,
              evidence: [],
              evidence_count: 0,
              evidence_max_entries: 50,
              can_request_ai_governance_draft: false,
            }
          : {
              ...reportListResponse(),
              data: [reportSummary(0), reportSummary(1)],
              count: 2,
            },
      }),
    )
    await page.route(
      `**/api/v1/projects/${projectId}/governance-runs/*/sources`,
      (route) => {
        const runId =
          new URL(route.request().url()).pathname.split("/").at(-2) ?? ""
        probes.push(runId)
        if (runId === runIds[0]) {
          return route.fulfill({
            status: 404,
            json: { detail: "No compatible published result" },
          })
        }
        return route.fulfill({
          json: {
            project_id: projectId,
            governance_run_id: runIds[1],
            governance_report_id: reportIds[1],
            run_status: "COMPLETED",
            completed_at: completedAt,
            input_contract_version: "governance-run-input-v1",
            processing_contract_version: "ip-v1",
            report_contract_version: "deterministic-report-v1",
            sources: [],
          },
        })
      },
    )
    await page.goto(`/?project=${projectId}&view=overview`)
    await expect(page).toHaveURL(new RegExp(`run=${runIds[1]}`))
    await expect(page.getByRole("alert")).toContainText(
      "Three-source summary: N/A",
    )
    expect(probes).toEqual([runIds[0], runIds[1]])
    await page.reload()
    await expect(page.getByRole("alert")).toContainText(
      "Three-source summary: N/A",
    )
    expect(probes).toEqual([runIds[0], runIds[1]])

    await page.goto(`/?project=${projectId}&run=${runIds[2]}&view=overview`)
    await expect(page.getByRole("alert")).toContainText(
      "Published Run unavailable",
    )
    await expect(page).toHaveURL(new RegExp(`run=${runIds[2]}`))
    await expect(
      page.getByRole("region", { name: "Published overview", exact: true }),
    ).toHaveCount(0)
    expect(probes).toEqual([runIds[0], runIds[1]])
  })
})

test("waits for fresh reports before pinning a cached project's latest Run", async ({
  page,
}) => {
  await installBaseMocks(page)
  let preparationReads = 0
  page.on("request", (request) => {
    if (
      /\/(customer-uploads|customer-upload-profile|netflow-datasets|cloudatlas-source-instances)$/.test(
        new URL(request.url()).pathname,
      )
    )
      preparationReads++
  })
  const otherProjectId = "00000000-0000-0000-0000-000000000002"
  await page.route(/\/api\/v1\/projects\/\?/, (route) =>
    route.fulfill({
      json: {
        data: [projectId, otherProjectId].map((id) => ({
          id,
          name: id,
          tenant_id: "00000000-0000-0000-0000-000000000010",
          archived_at: null,
          created_at: completedAt,
          updated_at: completedAt,
        })),
        count: 2,
      },
    }),
  )
  let newestPublished = false
  let release!: () => void
  const delayed = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route(
    `**/api/v1/projects/${otherProjectId}/governance-reports?*`,
    (route) =>
      route.fulfill({
        json: { ...reportListResponse(), data: [], count: 0 },
      }),
  )
  await page.route(governanceReportsPath, async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith("/governance-reports")) {
      if (newestPublished) await delayed
      return route.fulfill({
        json: {
          ...reportListResponse(),
          data: newestPublished
            ? [reportSummary(1), reportSummary(0)]
            : [reportSummary(0)],
          count: newestPublished ? 2 : 1,
        },
      })
    }
    const index = path.endsWith(reportIds[1]) ? 1 : 0
    const detail = draftReportDetail()
    detail.canonical_content.report.report_identity.governance_run_id =
      runIds[index]
    return route.fulfill({ json: { ...detail, ...reportSummary(index) } })
  })
  await page.route("**/governance-runs/*/sources", (route) => {
    const index = new URL(route.request().url()).pathname.includes(runIds[1])
      ? 1
      : 0
    return route.fulfill({
      json: {
        project_id: projectId,
        governance_run_id: runIds[index],
        governance_report_id: reportIds[index],
        report_contract_version: "deterministic-report-v1",
      },
    })
  })
  await page.goto(`/?project=${projectId}`)
  await expect(page).toHaveURL(new RegExp(`run=${runIds[0]}`))
  await expect(
    page.getByRole("heading", { name: "Published overview" }),
  ).toBeVisible()
  expect(
    preparationReads,
    "pinning an existing result must not mount input preparation",
  ).toBe(0)
  await page.goto(`/?project=${projectId}&run=`)
  await expect(
    page.getByText("Published Run unavailable", { exact: true }),
  ).toBeVisible()
  expect(preparationReads).toBe(0)
  await page.goBack()
  await expect(page).toHaveURL(new RegExp(`run=${runIds[0]}`))
  await page
    .getByRole("combobox", { name: "Project", exact: true })
    .selectOption(otherProjectId)
  await expect(
    page.getByRole("heading", { name: "Prepare this comparison" }),
  ).toBeVisible()
  newestPublished = true
  const refresh = page.waitForRequest(
    (request) =>
      new URL(request.url()).pathname ===
      `/api/v1/projects/${projectId}/governance-reports`,
  )
  await page
    .getByRole("combobox", { name: "Project", exact: true })
    .selectOption(projectId)
  await refresh
  // Hold the fresh response through a rendering turn: cached latest must not become an explicit pin.
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  )
  release()
  await expect(page).toHaveURL(new RegExp(`run=${runIds[1]}`))
  await expect(page.getByRole("alert")).toContainText(
    "Three-source summary: N/A",
  )
})

test("hides cached Run choices after a masked access-denial refresh", async ({
  page,
}) => {
  await installBaseMocks(page)
  let denied = false
  await page.route(governanceReportsPath, (route) => {
    if (
      new URL(route.request().url()).pathname.endsWith("/governance-reports")
    ) {
      return denied
        ? route.fulfill({ status: 404, json: { detail: "Project not found" } })
        : route.fulfill({ json: reportListResponse() })
    }
    return route.fulfill({ json: draftReportDetail() })
  })
  await page.goto(`/?project=${projectId}&run=${runIds[0]}`)
  const runs = page.getByRole("combobox", {
    name: "Published run",
    exact: true,
  })
  await expect(runs).toBeEnabled()
  await expect(runs).toHaveValue(runIds[0])
  const selectedOption = runs.locator(`option[value="${runIds[0]}"]`)
  const publishedLabel = await selectedOption.textContent()
  denied = true
  await page.evaluate(() => window.dispatchEvent(new Event("visibilitychange")))
  await expect(page.getByRole("alert")).toContainText(
    "Published results could not be loaded",
  )
  await expect(runs).toBeDisabled()
  await expect(runs).toHaveValue(runIds[0])
  await expect(selectedOption).not.toHaveText(publishedLabel!)
  await expect(page).toHaveURL(new RegExp(`run=${runIds[0]}`))
})

const analysisIds = [
  "a0000000-0000-0000-0000-000000000001",
  "a0000000-0000-0000-0000-000000000002",
  "a0000000-0000-0000-0000-000000000003",
]
const analysisPath = new RegExp(
  `/api/v1/projects/${projectId}/analysis-reports(?:/.*)?(?:\\?.*)?$`,
)

function analysisVersion(
  index: number,
  status: "GENERATING" | "DRAFT" | "CONFIRMED" | "FAILED" = "DRAFT",
) {
  const text = {
    business_summary: `Analysis ${index}: reconcile the recorded source difference.`,
    key_differences: "The asset appears only in the customer source.",
    investigation_progress: "No investigation records were captured.",
    next_steps: "Verify the source scope before changing any finding.",
  }
  const ready = status === "DRAFT" || status === "CONFIRMED"
  return {
    id: analysisIds[index],
    project_id: projectId,
    connection_version_id:
      index === 0 ? "a0000000-0000-0000-0000-000000000001" : null,
    run_id: runIds[0],
    status,
    created_at: completedAt,
    completed_at: status === "GENERATING" ? null : completedAt,
    confirmed_at: status === "CONFIRMED" ? completedAt : null,
    created_by_id: "30000000-0000-0000-0000-000000000001",
    edited_by_id: null as string | null,
    edited_at: null as string | null,
    confirmed_by_id:
      status === "CONFIRMED" ? "30000000-0000-0000-0000-000000000001" : null,
    revision: 1,
    failure_code:
      status === "FAILED"
        ? "model_output_invalid"
        : status === "GENERATING"
          ? "session_pending"
          : null,
    original_output: ready
      ? {
          text: { ...text },
          citation_ids: ["M-0"],
          gaps: ["No investigation records."],
        }
      : null,
    text: ready ? text : null,
    material: {
      captured_at: completedAt,
      report_id: reportIds[0],
      report_contract_version: "deterministic-report-v2",
      summary: { resource_count: 47, netflow_input_state: "absent" },
      items: [
        {
          citation_id: "M-0",
          kind: "deterministic_summary",
          identity: `run:${runIds[0]}:report:${reportIds[0]}`,
          recorded_at: completedAt,
          data: { resource_count: 47 },
        },
      ],
      gaps: ["No later investigation materials."],
      truncated: false,
    },
    materials_changed: false,
  }
}

test.describe("Analysis reports", () => {
  test.beforeEach(async ({ page }) => {
    await installBaseMocks(page)
    await page.route(governanceReportsPath, (route) => {
      if (
        new URL(route.request().url()).pathname.endsWith(`/${reportIds[0]}`)
      ) {
        return route.fulfill({ json: v2ReportDetail() })
      }
      return route.fulfill({
        json: {
          ...reportListResponse(),
          data: [
            {
              ...reportSummary(0),
              report_contract_version: "deterministic-report-v2",
            },
          ],
        },
      })
    })
  })

  test("shows a persisted connection version or legacy label", async ({
    page,
  }) => {
    const records = [analysisVersion(0), analysisVersion(1)]
    await page.route(analysisPath, (route) => {
      const path = new URL(route.request().url()).pathname
      return route.fulfill({
        json: records.find((item) => path.endsWith(`/${item.id}`)) ?? {
          data: records,
          count: records.length,
          can_create: true,
        },
      })
    })
    await openReport(page)
    const panel = page.getByRole("region", { name: "AI analysis reports" })
    await expect(panel.getByLabel("Analysis version")).toContainText(
      "Connection a0000000",
    )
    await expect(panel.getByLabel("Analysis version")).toContainText(
      "Legacy connection",
    )
  })

  test("keeps an explicitly selected old version and its update notice through unknown and failed generation", async ({
    page,
  }) => {
    const old = { ...analysisVersion(0, "CONFIRMED"), materials_changed: true }
    const newer = { ...analysisVersion(1), materials_changed: true }
    const failed = analysisVersion(2, "FAILED")
    const generating = analysisVersion(2, "GENERATING")
    let records = [newer, old]
    const keys: string[] = []
    await page.route(analysisPath, async (route) => {
      const request = route.request()
      const path = new URL(request.url()).pathname
      if (request.method() === "POST") {
        keys.push((await request.allHeaders())["idempotency-key"])
        if (keys.length === 1) {
          return route.fulfill({
            status: 503,
            json: { detail: "Session result unknown" },
          })
        }
        const result = keys.length === 2 ? generating : failed
        records = [result, ...records.filter((item) => item.id !== result.id)]
        return route.fulfill({ json: result })
      }
      const selected = records.find((item) => path.endsWith(`/${item.id}`))
      return route.fulfill({
        json: selected ?? {
          data: records,
          count: records.length,
          can_create: true,
        },
      })
    })
    await openReport(page)
    const panel = page.getByRole("region", {
      name: "AI analysis reports",
      exact: true,
    })
    await panel.getByLabel("Analysis version").selectOption(old.id)
    await expect(panel.getByLabel("Analysis version")).not.toContainText(old.id)
    await expect(panel.getByLabel("Analysis version")).not.toContainText(
      newer.id,
    )
    await expect(
      panel.getByRole("region", { name: "Report narrative" }),
    ).toContainText(old.text!.business_summary)
    const notice = panel
      .getByRole("alert")
      .filter({ hasText: "New materials are NOT included" })
    await notice
      .getByRole("button", { name: "Generate new analysis draft" })
      .click()
    await expect(
      panel
        .getByRole("alert")
        .filter({ hasText: "Report generation was not confirmed" }),
    ).toBeVisible()
    await expect(panel.getByLabel("Analysis version")).toHaveValue(old.id)
    await notice.getByRole("button", { name: "Resume report request" }).click()
    await expect(panel.getByLabel("Analysis version")).toHaveValue(old.id)
    await expect(
      panel.getByRole("region", { name: "Report narrative" }),
    ).toContainText(old.text!.business_summary)
    await expect(notice).toBeVisible()
    expect(keys[0]).toBeTruthy()
    expect(keys[1]).toBe(keys[0])
    await page.reload()
    await expect(
      panel.getByText("Generation outcome is still unknown", { exact: true }),
    ).toBeVisible()
    await expect(
      panel.getByRole("button", { name: "Generate new analysis draft" }),
    ).toHaveCount(0)
    await panel.getByLabel("Analysis version").selectOption(old.id)
    await notice.getByRole("button", { name: "Resume report request" }).click()
    await expect(panel.getByLabel("Analysis version")).toHaveValue(old.id)
    await expect(
      panel.getByRole("region", { name: "Report narrative" }),
    ).toContainText(old.text!.business_summary)
    expect(keys).toEqual([keys[0], keys[0], keys[0]])
    await panel.getByLabel("Analysis version").selectOption(failed.id)
    await expect(
      panel.getByText("This version failed to generate", { exact: true }),
    ).toBeVisible()
    await expect(
      panel.getByRole("region", { name: "Report narrative" }),
    ).toHaveCount(0)
    await panel.getByLabel("Analysis version").selectOption(newer.id)
    await expect(notice).toBeVisible()
    await expect(
      notice.getByRole("button", { name: "Generate new analysis draft" }),
    ).toBeEnabled()
  })

  test("retains conflicted edits, confirms separately, and preserves original citations on narrow screens", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    const version = analysisVersion(0)
    let record = {
      ...version,
      material: {
        ...version.material,
        summary: {
          ...v2ReportDetail().canonical_content.report,
          input_capabilities: {
            netflow: {
              status: "COMPLETED",
              input_state: "present",
              coverage: "UNKNOWN",
              capability: "POSITIVE_IP_ACTIVITY",
              source_snapshot_id: "snapshot-netflow",
              positive_activity_resource_count: 5,
            },
          },
        },
      },
    }
    record.material.summary.input_completeness.sources.forEach(
      (source, index) => {
        source.schema_version = String(index + 1).repeat(64)
      },
    )
    const originalGap = "No successful later verification is available."
    record.original_output!.gaps = [originalGap]
    let rejectFirstEdit = true
    let confirmations = 0
    await page.route(analysisPath, async (route) => {
      const request = route.request()
      const path = new URL(request.url()).pathname
      if (request.method() === "PATCH") {
        const body = request.postDataJSON()
        if (rejectFirstEdit) {
          rejectFirstEdit = false
          record = {
            ...record,
            revision: 2,
            text: {
              ...record.text!,
              business_summary: "Another operator's saved explanation.",
            },
          }
          return route.fulfill({
            status: 409,
            json: { detail: "revision_conflict" },
          })
        }
        expect(body.expected_revision).toBe(2)
        record = {
          ...record,
          revision: 3,
          text: body.text,
          edited_by_id: "30000000-0000-0000-0000-000000000002",
          edited_at: "2026-08-11T12:00:00Z",
        }
        return route.fulfill({ json: record })
      }
      if (path.endsWith("/confirm")) {
        confirmations += 1
        expect(request.postDataJSON()).toEqual({ expected_revision: 3 })
        record = {
          ...record,
          revision: 4,
          status: "CONFIRMED",
          confirmed_by_id: record.edited_by_id,
          confirmed_at: "2026-08-11T13:00:00Z",
        }
        return route.fulfill({ json: record })
      }
      return route.fulfill({
        json: path.endsWith(`/${record.id}`)
          ? record
          : { data: [record], count: 1, can_create: true },
      })
    })
    await openReport(page)
    const panel = page.getByRole("region", {
      name: "AI analysis reports",
      exact: true,
    })
    const identities = panel.locator("details").filter({
      has: page
        .locator("summary")
        .getByText("Report identifiers and authors", { exact: true }),
    })
    await expect(
      identities.getByText(record.run_id, { exact: true }),
    ).not.toBeVisible()
    await expect(
      panel.getByText("Material captured", { exact: true }),
    ).toBeVisible()
    await identities.locator("summary").focus()
    await page.keyboard.press("Enter")
    await expect(
      identities.getByText(record.run_id, { exact: true }),
    ).toBeVisible()
    await page.context().grantPermissions(["clipboard-read", "clipboard-write"])
    await identities
      .getByRole("button", { name: "Copy Fixed base Run", exact: true })
      .focus()
    await page.keyboard.press("Enter")
    await expect
      .poll(() => page.evaluate(() => navigator.clipboard.readText()))
      .toBe(record.run_id)
    const summary = panel.getByRole("region", {
      name: "Fixed deterministic summary",
      exact: true,
    })
    const fixedMaterial = summary.locator("details").filter({
      has: page.locator("summary").getByText("View fixed source material", {
        exact: true,
      }),
    })
    await expect(fixedMaterial).not.toHaveAttribute("open", "")
    await expect(
      summary.getByText("generation mode", { exact: true }),
    ).not.toBeVisible()
    await expect(page.locator("#report-ip-summary")).toContainText(
      "Customer observed assets: 2",
    )
    await expect(page.locator("#report-input-completeness")).toContainText(
      "NETFLOW",
    )
    await expect(
      summary
        .locator(":scope > dl > div")
        .filter({
          has: page.locator("dt").getByText("UNKNOWN", { exact: true }),
        })
        .locator("dd"),
    ).toHaveText("42")
    await expect(
      summary
        .locator(":scope > dl > div")
        .filter({
          has: page
            .locator("dt")
            .getByText("NetFlow coverage", { exact: true }),
        })
        .getByText("UNKNOWN", { exact: true }),
    ).toBeVisible()
    for (const source of record.material.summary.input_completeness.sources) {
      await expect(
        fixedMaterial.getByText(source.schema_version, { exact: true }),
      ).not.toBeVisible()
    }
    const schemaHash =
      record.material.summary.input_completeness.sources[0].schema_version
    await fixedMaterial.locator(":scope > summary").focus()
    await page.keyboard.press("Enter")
    const schemaDetails = fixedMaterial.locator("details").filter({
      has: page.getByText(schemaHash, { exact: true }),
    })
    await schemaDetails.locator("summary").focus()
    await page.keyboard.press("Enter")
    await expect(
      schemaDetails.getByText(schemaHash, { exact: true }),
    ).toBeVisible()
    await schemaDetails
      .getByRole("button", {
        name: `Copy full value: ${schemaHash}`,
        exact: true,
      })
      .focus()
    await page.keyboard.press("Enter")
    await expect
      .poll(() => page.evaluate(() => navigator.clipboard.readText()))
      .toBe(schemaHash)
    const hash =
      record.material.summary.input_completeness.sources[0].content_sha256
    const hashDetails = fixedMaterial
      .locator("details")
      .filter({ hasText: hash })
      .first()
    await expect(hashDetails.getByText(hash, { exact: true })).not.toBeVisible()
    await hashDetails.locator("summary").focus()
    await page.keyboard.press("Enter")
    await expect(hashDetails.getByText(hash, { exact: true })).toBeVisible()
    await hashDetails
      .getByRole("button", { name: `Copy full value: ${hash}`, exact: true })
      .focus()
    await page.keyboard.press("Enter")
    await expect
      .poll(() => page.evaluate(() => navigator.clipboard.readText()))
      .toBe(hash)
    await fixedMaterial.locator(":scope > summary").focus()
    await page.keyboard.press("Enter")
    await expect(
      fixedMaterial.getByText(schemaHash, { exact: true }),
    ).not.toBeVisible()
    await panel
      .getByRole("button", { name: "Edit narrative", exact: true })
      .click()
    const editors = panel.getByRole("textbox")
    await expect(editors).toHaveCount(4)
    for (const editor of await editors.all()) {
      const layout = await editor.evaluate((element) => {
        const style = getComputedStyle(element)
        const bounds = element.getBoundingClientRect()
        return {
          visibleLines:
            (element.clientHeight -
              Number.parseFloat(style.paddingTop) -
              Number.parseFloat(style.paddingBottom)) /
            Number.parseFloat(style.lineHeight),
          lineSpacing:
            Number.parseFloat(style.lineHeight) /
            Number.parseFloat(style.fontSize),
          fitsViewport: bounds.left >= 0 && bounds.right <= window.innerWidth,
          resizable: style.resize !== "none",
        }
      })
      expect(layout.visibleLines).toBeGreaterThanOrEqual(8)
      expect(layout.lineSpacing).toBeGreaterThanOrEqual(1.5)
      expect(layout.fitsViewport).toBe(true)
      expect(layout.resizable).toBe(true)
    }
    await panel
      .getByLabel("Business summary", { exact: true })
      .fill("Retain my explanation during conflict.")
    await panel
      .getByRole("button", { name: "Save narrative", exact: true })
      .click()
    await expect(
      panel.getByLabel("Business summary", { exact: true }),
    ).toHaveValue("Retain my explanation during conflict.")
    await expect(
      panel.getByRole("button", { name: "Save narrative", exact: true }),
    ).toBeDisabled()
    await panel.getByRole("button", { name: "Cancel edit" }).click()
    await panel
      .getByRole("button", { name: "Edit narrative", exact: true })
      .click()
    await panel
      .getByLabel("Business summary", { exact: true })
      .fill("Human explanation after checking the current revision.")
    await panel
      .getByRole("button", { name: "Save narrative", exact: true })
      .click()
    const narrative = panel.getByRole("region", { name: "Report narrative" })
    await expect(narrative).toContainText(
      "Human explanation after checking the current revision.",
    )
    expect(confirmations).toBe(0)
    await expect(
      panel.getByText(originalGap, { exact: true }),
    ).not.toBeVisible()
    await expect(
      panel.getByText(record.material.gaps[0], { exact: true }),
    ).toBeVisible()
    await panel
      .getByRole("button", { name: "Confirm this version", exact: true })
      .click()
    await expect(
      panel.getByRole("button", { name: "Edit narrative", exact: true }),
    ).toHaveCount(0)
    await expect(
      panel.getByText("Human-confirmed", { exact: true }),
    ).toBeVisible()
    expect(confirmations).toBe(1)
    await expect(
      panel.getByText(originalGap, { exact: true }),
    ).not.toBeVisible()
    const original = panel.locator("details").filter({
      hasText: "Original AI draft · preserved unchanged",
    })
    await original.locator("summary").focus()
    await page.keyboard.press("Enter")
    await expect(original.getByText(originalGap, { exact: true })).toBeVisible()
    await expect(
      panel
        .getByRole("region", { name: "Frozen materials and citations" })
        .getByText(originalGap, { exact: true }),
    ).toHaveCount(0)
    await expect(original).toContainText(
      analysisVersion(0).text!.business_summary,
    )
    await expect(original).not.toContainText(
      "Human explanation after checking the current revision.",
    )
    const source = panel.locator("details").filter({
      has: page.locator("summary").filter({ hasText: "Cited source" }),
    })
    await expect(source.locator("summary")).not.toContainText(
      record.material.items[0].citation_id,
    )
    await expect(
      source.getByText(record.material.items[0].identity, { exact: true }),
    ).not.toBeVisible()
    await source.locator("summary").focus()
    await page.keyboard.press("Enter")
    await expect(
      source.getByText(record.material.items[0].identity, { exact: true }),
    ).toBeVisible()
    await source
      .getByRole("button", { name: "Copy Full record identity", exact: true })
      .focus()
    await page.keyboard.press("Enter")
    await expect
      .poll(() => page.evaluate(() => navigator.clipboard.readText()))
      .toBe(record.material.items[0].identity)
    await expect(
      source.getByText("Recorded time", { exact: true }),
    ).toBeVisible()
    expect(
      await panel.evaluate(
        (element) => element.scrollWidth <= element.clientWidth + 1,
      ),
    ).toBe(true)
  })

  test("keeps Viewer access read-only and hides cached materials after revoked access", async ({
    page,
  }) => {
    const record = { ...analysisVersion(0), materials_changed: true }
    let revoked = false
    await page.route(analysisPath, (route) => {
      if (revoked)
        return route.fulfill({ status: 404, json: { detail: "Not Found" } })
      const path = new URL(route.request().url()).pathname
      return route.fulfill({
        json: path.endsWith(`/${record.id}`)
          ? record
          : { data: [record], count: 1, can_create: false },
      })
    })
    await openReport(page)
    const panel = page.getByRole("region", {
      name: "AI analysis reports",
      exact: true,
    })
    await expect(
      panel.getByRole("region", { name: "Report narrative" }),
    ).toBeVisible()
    await expect(
      panel.getByText("New materials are NOT included in this version", {
        exact: true,
      }),
    ).toBeVisible()
    await expect(
      panel.getByRole("button", {
        name: /Generate new analysis draft|Edit narrative|Confirm this version/,
      }),
    ).toHaveCount(0)
    revoked = true
    await panel
      .getByRole("button", { name: "Refresh analysis reports" })
      .click()
    await expect(
      panel.getByText("Analysis report could not be read", { exact: true }),
    ).toBeVisible()
    await expect(
      panel.getByRole("region", { name: "Report narrative" }),
    ).toHaveCount(0)
    await expect(
      panel.getByRole("region", { name: "Frozen materials and citations" }),
    ).toHaveCount(0)
    await expect(panel.getByLabel("Analysis version")).toHaveValue(record.id)
  })
})

test("rejects analysis material from another deterministic report instead of displaying cross-scope prose", async ({
  page,
}) => {
  await installBaseMocks(page)
  await page.route(governanceReportsPath, (route) =>
    route.fulfill({
      json: new URL(route.request().url()).pathname.endsWith(`/${reportIds[0]}`)
        ? v2ReportDetail()
        : {
            ...reportListResponse(),
            data: [
              {
                ...reportSummary(0),
                report_contract_version: "deterministic-report-v2",
              },
            ],
          },
    }),
  )
  const record = analysisVersion(0)
  record.material.report_id = reportIds[1]
  await page.route(analysisPath, (route) =>
    route.fulfill({ json: { data: [record], count: 1, can_create: true } }),
  )
  await openReport(page)
  const panel = page.getByRole("region", {
    name: "AI analysis reports",
    exact: true,
  })
  await expect(
    panel.getByText("Analysis report could not be read", { exact: true }),
  ).toBeVisible()
  await expect(
    panel.getByText(record.text!.business_summary, { exact: true }),
  ).toHaveCount(0)
  await expect(
    panel.getByRole("button", { name: "Generate new analysis draft" }),
  ).toHaveCount(0)
})

async function installWorkflow(page: Page) {
  // Deny every unspecified API request; these tests never touch live business APIs.
  await page.route("**/api/**", (route) =>
    route.fulfill({
      status: 404,
      json: { detail: "Unspecified fixture route" },
    }),
  )
  await installBaseMocks(page)
  await page.route(governanceReportsPath, (route) => {
    const index = reportIds.findIndex((id) =>
      new URL(route.request().url()).pathname.endsWith(`/${id}`),
    )
    if (index >= 0) {
      const detail = JSON.parse(
        JSON.stringify(v2ReportDetail())
          .replaceAll(reportIds[0], reportIds[index])
          .replaceAll(runIds[0], runIds[index]),
      )
      return route.fulfill({ json: detail })
    }
    return route.fulfill({
      json: {
        ...reportListResponse(),
        data: [0, 1].map((i) => ({
          ...reportSummary(i),
          report_contract_version: "deterministic-report-v2",
        })),
      },
    })
  })
}

test.describe("Visible AI workflow", () => {
  test("home links retain Run scope and never generate on open or refresh", async ({
    page,
  }) => {
    await installWorkflow(page)
    const writes: string[] = []
    page.on("request", (request) => {
      if (request.method() === "POST") writes.push(request.url())
    })
    await page.goto(`/?project=${projectId}&run=${runIds[0]}&view=overview`)
    const area = page.getByRole("region", { name: "AI workspace for this Run" })
    await expect(
      area.getByText("fixture-current-model", { exact: true }),
    ).toBeVisible()
    await page.reload()
    await area
      .getByRole("link", { name: "Open this Run's AI interpretation" })
      .click()
    await expect(page).toHaveURL(
      new RegExp(`run=${runIds[0]}.*#analysis-reports-title`),
    )
    await expect(page.locator("#analysis-reports-title")).toBeFocused()
    await expect(
      page.getByRole("button", { name: "Generate new analysis draft" }),
    ).toHaveCount(0)
    expect(writes).toEqual([])
  })

  test("model failures preserve authoritative totals and historical reading", async ({
    page,
  }) => {
    await installWorkflow(page)
    await page.route("**/api/v1/model-connections/status", (route) =>
      route.fulfill({ status: 503, json: { detail: "Unavailable" } }),
    )
    await page.goto(`/?project=${projectId}&run=${runIds[0]}&view=overview`)
    await expect(
      page.getByText("Status unknown", { exact: true }),
    ).toBeVisible()
    const overview = page.getByRole("region", {
      name: "Published overview",
      exact: true,
    })
    await expect(
      overview
        .getByText("Compared resources", { exact: true })
        .locator("..")
        .locator("dd"),
    ).toHaveText("47")
    await expect(
      page.getByRole("link", { name: "Open this Run's AI interpretation" }),
    ).toBeEnabled()
    await page.route("**/api/v1/model-connections/status", (route) =>
      route.fulfill({
        json: {
          state: "unconfigured",
          configured: false,
          ready: false,
          model_identity: null,
        },
      }),
    )
    await page.getByRole("button", { name: "Read status again" }).click()
    await expect(
      page.getByText("Not configured", { exact: true }),
    ).toBeVisible()
    expect(new URL(page.url()).searchParams.get("run")).toBe(runIds[0])
  })

  test("late report response cannot update another Run or its recovery state", async ({
    page,
  }) => {
    await installWorkflow(page)
    let release = () => {}
    let entered = () => {}
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    const started = new Promise<void>((resolve) => {
      entered = resolve
    })
    await page.route(analysisPath, async (route) => {
      if (route.request().method() === "POST") {
        entered()
        await gate
        return route.fulfill({ status: 201, json: analysisVersion(0) })
      }
      return route.fulfill({ json: { data: [], count: 0, can_create: true } })
    })
    await openReport(page)
    await page
      .getByRole("button", { name: "Generate new analysis draft" })
      .click()
    await started
    await page
      .getByRole("combobox", { name: "Published run", exact: true })
      .selectOption(runIds[1])
    await expect(page).toHaveURL(new RegExp(`run=${runIds[1]}`))
    release()
    await expect(
      page.getByRole("button", { name: "Generate new analysis draft" }),
    ).toBeVisible()
    await expect(
      page.getByText("Analysis 0: reconcile the recorded source difference.", {
        exact: true,
      }),
    ).toHaveCount(0)
    const persisted = await page.evaluate(() => ({ ...sessionStorage }))
    const oldKey = `exposure:analysis-report:30000000-0000-0000-0000-000000000001:${projectId}:${runIds[0]}:idempotency-key`
    expect(JSON.parse(persisted[oldKey]).reportId).toBeNull()
    expect(Object.keys(persisted).some((key) => key.includes(runIds[1]))).toBe(
      false,
    )
  })

  test("another actor does not inherit an unresolved report intent", async ({
    page,
  }) => {
    await installWorkflow(page)
    await page.addInitScript(
      ({ projectId, runId }) =>
        sessionStorage.setItem(
          `exposure:analysis-report:30000000-0000-0000-0000-000000000001:${projectId}:${runId}:idempotency-key`,
          JSON.stringify({
            key: "40000000-0000-4000-8000-000000000001",
            reportId: null,
          }),
        ),
      { projectId, runId: runIds[0] },
    )
    await page.route("**/api/v1/users/me", (route) =>
      route.fulfill({
        json: {
          id: "30000000-0000-4000-8000-000000000099",
          email: "other@example.test",
          is_active: true,
          is_superuser: false,
        },
      }),
    )
    await page.route(analysisPath, (route) =>
      route.fulfill({ json: { data: [], count: 0, can_create: true } }),
    )
    await openReport(page)
    await expect(
      page.getByRole("button", { name: "Generate new analysis draft" }),
    ).toBeVisible()
    await expect(
      page.getByRole("button", { name: "Resume report request" }),
    ).toHaveCount(0)
  })

  for (const width of [390, 1366, 1920])
    test(`AI overview layout at ${width}`, async ({ page }) => {
      await installWorkflow(page)
      await page.setViewportSize({ width, height: width === 1920 ? 1080 : 768 })
      await page.emulateMedia({ reducedMotion: "reduce" })
      await page.goto(`/?project=${projectId}&run=${runIds[0]}&view=overview`)
      await expect(
        page.getByText("fixture-current-model", { exact: true }),
      ).toBeVisible()
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true)
      await page.screenshot({
        path: `/tmp/expux03-home-${width}-en.png`,
        fullPage: true,
      })
      await page.evaluate(() => {
        localStorage.setItem("exposure:language", "zh-CN")
        localStorage.setItem("vite-ui-theme", "light")
      })
      await page.reload()
      await expect(
        page.getByRole("heading", { name: "本轮 AI 工作区" }),
      ).toBeVisible()
      await expect(
        page.getByText("fixture-current-model", { exact: true }),
      ).toBeVisible()
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true)
      await page.screenshot({
        path: `/tmp/expux03-home-${width}-zh.png`,
        fullPage: true,
      })
    })
})

test("measures five local report-start feedback samples", async ({ page }) => {
  await installWorkflow(page)
  let records: ReturnType<typeof analysisVersion>[] = []
  await page.route(analysisPath, async (route) => {
    if (route.request().method() === "POST") {
      await new Promise((resolve) => setTimeout(resolve, 350))
      records = [analysisVersion(0)]
      return route.fulfill({ status: 201, json: records[0] })
    }
    const path = new URL(route.request().url()).pathname
    return route.fulfill({
      json: records.find((record) => path.endsWith(`/${record.id}`)) ?? {
        data: records,
        count: records.length,
        can_create: true,
      },
    })
  })
  const samples: number[] = []
  const longTasks: number[] = []
  for (let i = 0; i < 5; i++) {
    records = []
    await openReport(page)
    await expect(
      page.getByRole("button", {
        name: "Generate new analysis draft",
        exact: true,
      }),
    ).toBeEnabled()
    const result = await page.evaluate(async () => {
      const tasks: number[] = []
      const observer = new PerformanceObserver((list) => {
        for (const item of list.getEntries()) tasks.push(item.duration)
      })
      observer.observe({ type: "longtask", buffered: false })
      const button = [...document.querySelectorAll("button")].find(
        (b) => b.textContent?.trim() === "Generate new analysis draft",
      )!
      await new Promise(requestAnimationFrame)
      const start = performance.now()
      button.click()
      const elapsed = await new Promise<number>((resolve) => {
        const frame = () => {
          if (
            document.body.textContent?.includes("Starting report…") ||
            performance.now() - start > 1000
          )
            resolve(performance.now() - start)
          else requestAnimationFrame(frame)
        }
        requestAnimationFrame(frame)
      })
      await new Promise((resolve) => setTimeout(resolve, 450))
      observer.disconnect()
      return { elapsed, tasks }
    })
    samples.push(result.elapsed)
    longTasks.push(...result.tasks)
    await expect(
      page.getByRole("button", { name: "Edit narrative", exact: true }),
    ).toBeVisible()
    await expect(
      page.getByRole("button", {
        name: "Generate new analysis draft",
        exact: true,
      }),
    ).toBeEnabled()
  }
  writeFileSync(
    `/tmp/expux03-feedback-${process.env.EXPUX03_PERF_PHASE ?? "candidate"}.json`,
    JSON.stringify(
      {
        samples,
        longTasks,
        provider: "MOCK_DELAY_350MS",
        browser: "Chromium",
        viewport: page.viewportSize(),
      },
      null,
      2,
    ),
  )
  expect(Math.max(...samples)).toBeLessThanOrEqual(100)
  expect(longTasks.every((duration) => duration <= 200)).toBe(true)
})
