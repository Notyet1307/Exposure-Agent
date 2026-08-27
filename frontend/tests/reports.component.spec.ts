import { expect, type Page, test } from "@playwright/test"

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

test.describe("Project Reports", () => {
  test.beforeEach(async ({ page }) => {
    await installBaseMocks(page)
  })

  test("uses the opaque server cursor across equal completion-time pages", async ({
    page,
  }) => {
    const requestedCursors: Array<string | null> = []
    await page.route(
      new RegExp(`/api/v1/projects/${projectId}/governance-reports(?:\\?.*)?$`),
      (route) => {
        const url = new URL(route.request().url())
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
      },
    )

    await page.goto("/")
    await page.getByRole("tab", { name: "Reports", exact: true }).click()
    await expect(page.getByText(runIds[0], { exact: true })).toBeVisible()
    await expect(page.getByText(runIds[1], { exact: true })).toBeVisible()

    await page.getByRole("button", { name: "Next" }).click()
    await expect(page.getByText(runIds[2], { exact: true })).toBeVisible()
    await expect(page.getByText(runIds[0], { exact: true })).not.toBeVisible()

    await page.getByRole("button", { name: "Previous" }).click()
    await expect(page.getByText(runIds[0], { exact: true })).toBeVisible()
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

    await page.goto("/")
    await page.getByRole("tab", { name: "Reports", exact: true }).click()
    await page.getByRole("button", { name: "Read report" }).click()
    const report = page.getByRole("dialog")

    for (const section of [
      "Report identity and generation mode",
      "Input completeness",
      "IP consistency summary",
      "Current-Run lifecycle changes",
      "Open backlog as of Run",
      "Bounded Evidence examples",
      "Finding-type directions and limitations",
      "Provenance",
    ]) {
      await expect(report.getByRole("heading", { name: section })).toBeVisible()
    }
    await expect(
      report.getByText("DETERMINISTIC_TEMPLATE").first(),
    ).toBeVisible()
    await expect(report.getByText("HTML Artifact SHA-256")).toBeVisible()
    await expect(
      report.getByText("deterministic-report-v1").first(),
    ).toBeVisible()
    await expect(report.getByText("未观测资产不表示资产不存在")).toBeVisible()
    await expect(report.locator("[data-testid='evidence-card']")).toHaveCount(8)
    await expect(
      report.getByText("finding-8", { exact: true }),
    ).not.toBeVisible()
    await expect(
      report.getByText("<script>alert('evidence')</script>"),
    ).toBeVisible()
    await expect(report.locator("script, img")).toHaveCount(0)
    const links = report.locator("[data-testid='evidence-card'] a")
    await expect(links).toHaveCount(16)
    for (let index = 0; index < 16; index += 1) {
      await expect(links.nth(index)).toHaveAttribute("href", /^#report-/)
    }
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

    await page.goto("/")
    await page.getByRole("tab", { name: "Reports", exact: true }).click()
    await page.getByRole("button", { name: "Read report" }).click()

    await expect(
      page
        .getByRole("dialog")
        .getByText(
          "With both inputs complete, all observed IP identities matched; this Run produced zero Findings.",
        ),
    ).toBeVisible()
  })

  test("stops polling after the draft Session is bound", async ({ page }) => {
    let detailReads = 0
    let requested = false
    const postedBodies: unknown[] = []
    const requestKeys: string[] = []
    await page.route(
      new RegExp(
        `/api/v1/projects/${projectId}/governance-reports(?:/.*)?(?:\\?.*)?$`,
      ),
      async (route) => {
        const request = route.request()
        const url = new URL(request.url())
        if (url.pathname.endsWith(`/${reportIds[0]}/ai-governance-drafts`)) {
          requested = true
          postedBodies.push(request.postDataJSON())
          requestKeys.push(
            (await request.allHeaders())["idempotency-key"] ?? "",
          )
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
      },
    )

    await page.goto("/")
    await page.getByRole("tab", { name: "Reports", exact: true }).click()
    await page.getByRole("button", { name: "Read report" }).click()
    const report = page.getByRole("dialog")
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
    await page.route(
      new RegExp(
        `/api/v1/projects/${projectId}/governance-reports(?:/.*)?(?:\\?.*)?$`,
      ),
      (route) => {
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
      },
    )

    await page.goto("/")
    await page.getByRole("tab", { name: "Reports", exact: true }).click()
    await page.getByRole("button", { name: "Read report" }).click()
    const report = page.getByRole("dialog")
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
    await expect(persistedDraft.getByText(`Draft ${draftId}`)).toBeVisible()
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
    await page.route(
      new RegExp(
        `/api/v1/projects/${projectId}/governance-reports(?:/.*)?(?:\\?.*)?$`,
      ),
      async (route) => {
        const request = route.request()
        const url = new URL(request.url())
        if (url.pathname.endsWith(`/${reportIds[0]}/ai-governance-drafts`)) {
          postCount += 1
          requestKeys.push(
            (await request.allHeaders())["idempotency-key"] ?? "",
          )
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
      },
    )

    await page.goto("/")
    await page.getByRole("tab", { name: "Reports", exact: true }).click()
    await page.getByRole("button", { name: "Read report" }).click()
    let report = page.getByRole("dialog")
    await report.getByRole("checkbox").first().click()
    await report.getByRole("button", { name: "Request AI draft" }).click()

    const storageKey = `exposure:ai-governance-draft:${projectId}:${reportIds[0]}:idempotency-key`
    await expect
      .poll(() =>
        page.evaluate((key) => window.sessionStorage.getItem(key), storageKey),
      )
      .toBeNull()

    await page.reload()
    await page.getByRole("tab", { name: "Reports", exact: true }).click()
    await page.getByRole("button", { name: "Read report" }).click()
    report = page.getByRole("dialog")
    await expect(report.getByRole("checkbox").first()).toBeEnabled()
    expect(postCount).toBe(1)
    expect(requestKeys).toHaveLength(1)
  })

  test("recovers a pending Session with the same key after a page reload", async ({
    page,
  }) => {
    let postCount = 0
    let recovered = false
    const requestKeys: string[] = []
    await page.route(
      new RegExp(
        `/api/v1/projects/${projectId}/governance-reports(?:/.*)?(?:\\?.*)?$`,
      ),
      async (route) => {
        const request = route.request()
        const url = new URL(request.url())
        if (url.pathname.endsWith(`/${reportIds[0]}/ai-governance-drafts`)) {
          postCount += 1
          requestKeys.push(
            (await request.allHeaders())["idempotency-key"] ?? "",
          )
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
      },
    )

    await page.goto("/")
    await page.getByRole("tab", { name: "Reports", exact: true }).click()
    await page.getByRole("button", { name: "Read report" }).click()
    let report = page.getByRole("dialog")
    await report.getByRole("checkbox").first().click()
    await report.getByRole("button", { name: "Request AI draft" }).click()
    await expect(
      report.getByRole("alert").getByText("Draft request could not be started"),
    ).toBeVisible()

    await page.reload()
    await page.getByRole("tab", { name: "Reports", exact: true }).click()
    await page.getByRole("button", { name: "Read report" }).click()
    report = page.getByRole("dialog")
    await report
      .getByRole("button", { name: "Resume your draft request" })
      .click()

    await expect(report.getByText(`Session ${draftSessionId}`)).toBeVisible()
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
    await page.route(
      new RegExp(
        `/api/v1/projects/${projectId}/governance-reports(?:/.*)?(?:\\?.*)?$`,
      ),
      async (route) => {
        const request = route.request()
        const url = new URL(request.url())
        if (url.pathname.endsWith(`/${reportIds[0]}/ai-governance-drafts`)) {
          postCount += 1
          postedBodies.push(request.postDataJSON())
          requestKeys.push(
            (await request.allHeaders())["idempotency-key"] ?? "",
          )
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
      },
    )

    await page.goto("/")
    await page.getByRole("tab", { name: "Reports", exact: true }).click()
    await page.getByRole("button", { name: "Read report" }).click()
    let report = page.getByRole("dialog")
    await report.getByRole("checkbox").first().click()
    await report.getByRole("button", { name: "Request AI draft" }).click()
    await expect(
      report.getByRole("alert").getByText("Draft request could not be started"),
    ).toBeVisible()

    await page.reload()
    await page.getByRole("tab", { name: "Reports", exact: true }).click()
    await page.getByRole("button", { name: "Read report" }).click()
    report = page.getByRole("dialog")
    await report
      .getByRole("button", { name: "Resume your draft request" })
      .click()

    await expect(report.getByText(`Session ${draftSessionId}`)).toBeVisible()
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
    await page.route(
      new RegExp(
        `/api/v1/projects/${projectId}/governance-reports(?:/.*)?(?:\\?.*)?$`,
      ),
      async (route) => {
        const request = route.request()
        const url = new URL(request.url())
        if (url.pathname.endsWith(`/${reportIds[0]}/ai-governance-drafts`)) {
          postCount += 1
          requestKeys.push(
            (await request.allHeaders())["idempotency-key"] ?? "",
          )
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
      },
    )

    await page.goto("/")
    await page.getByRole("tab", { name: "Reports", exact: true }).click()
    await page.getByRole("button", { name: "Read report" }).click()
    let report = page.getByRole("dialog")
    const findings = report.getByRole("checkbox")
    await findings.first().click()
    await report.getByRole("button", { name: "Request AI draft" }).click()
    await expect(
      report.getByRole("alert").getByText("Draft request could not be started"),
    ).toBeVisible()
    await expect(findings.nth(1)).toBeDisabled()
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
    await page.getByRole("tab", { name: "Reports", exact: true }).click()
    await page.getByRole("button", { name: "Read report" }).click()
    report = page.getByRole("dialog")
    await report
      .getByRole("button", { name: "Resume your draft request" })
      .click()

    await expect(report.getByText(`Session ${draftSessionId}`)).toBeVisible()
    expect(requestKeys).toHaveLength(2)
    expect(requestKeys[1]).toBe(requestKeys[0])
  })

  test("requires explicit selection and caps the request at eight Findings", async ({
    page,
  }) => {
    await page.route(
      new RegExp(
        `/api/v1/projects/${projectId}/governance-reports(?:/.*)?(?:\\?.*)?$`,
      ),
      (route) => {
        const url = new URL(route.request().url())
        if (url.pathname.endsWith(`/${reportIds[0]}`)) {
          return route.fulfill({ json: draftReportDetail() })
        }
        return route.fulfill({ json: reportListResponse() })
      },
    )

    await page.goto("/")
    await page.getByRole("tab", { name: "Reports", exact: true }).click()
    await page.getByRole("button", { name: "Read report" }).click()
    const report = page.getByRole("dialog")
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
})
