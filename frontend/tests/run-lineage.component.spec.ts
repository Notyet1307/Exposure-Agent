import type {
  GovernanceReportDetailPublic,
  GovernanceRunLineagePublic,
  GovernanceRunPublic,
  GovernanceRunSourcesPublic,
  IPSourceComparisonsPublic,
  LineageComparisonNodePublic,
  LineageEvidenceReferencePublic,
  LineageFindingNodePublic,
  LineageReportNodePublic,
} from "../src/client"
import { expect, type Page, test } from "./fixtures"

const projectId = "00000000-0000-0000-0000-000000000001"
const otherProjectId = "00000000-0000-0000-0000-000000000002"
const runId = "60000000-0000-0000-0000-000000000001"
const newerRunId = "60000000-0000-0000-0000-000000000002"
const resourceId = "a0000000-0000-0000-0000-000000000001"
const outsideResourceId = "a0000000-0000-0000-0000-000000000021"
const findingId = "b0000000-0000-0000-0000-000000000001"
const occurrenceId = "c0000000-0000-0000-0000-000000000001"
const transitionId = "d0000000-0000-0000-0000-000000000001"
const observationId = "e0000000-0000-0000-0000-000000000001"
const completedAt = "2026-09-01T12:00:00Z"
const hash = "a".repeat(64)
const schemaHash = "b".repeat(64)
const methodHash = "c".repeat(64)
const longIp = "2001:db8:1234:5678:90ab:cdef:1234:5678"
const lineagePath = (resource?: string, run = runId, project = projectId) =>
  `/projects/${project}/runs/${run}/lineage${resource === undefined ? "" : `?resource_id=${resource}`}`
const nodes = (page: Page) =>
  page.getByRole("region", { name: "Lineage nodes", exact: true })
const details = (page: Page) =>
  page.getByRole("region", { name: "Node details", exact: true })
const node = (page: Page, kind: string, identifier: string) =>
  nodes(page).getByRole("button", {
    name: new RegExp(
      `^${kind} ${identifier.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?:$| · )`,
    ),
  })
const comparisons = (dto: GovernanceRunLineagePublic) =>
  dto.nodes.filter(
    (item): item is LineageComparisonNodePublic => item.kind === "COMPARISON",
  )
const findings = (dto: GovernanceRunLineagePublic) =>
  dto.nodes.filter(
    (item): item is LineageFindingNodePublic => item.kind === "FINDING",
  )
const reportNode = (dto: GovernanceRunLineagePublic) =>
  dto.nodes.find(
    (item): item is LineageReportNodePublic => item.kind === "REPORT",
  )!

// Controlled published DTOs exercise browser behavior, not real backend integration.
function publishedLineage({
  resource,
  run = runId,
  project = projectId,
  netflow = "active",
  legacy = false,
  partial = false,
  empty = false,
}: {
  resource?: string
  run?: string
  project?: string
  netflow?: "absent" | "active" | "zero" | "no-positive"
  legacy?: boolean
  partial?: boolean
  empty?: boolean
} = {}): GovernanceRunLineagePublic {
  const version =
    legacy || netflow === "absent"
      ? "deterministic-report-v1"
      : "deterministic-report-v2"
  const reportId = run.replace(/^6/, "9")
  const selectedResource = resource ?? resourceId
  const ip = selectedResource === outsideResourceId ? longIp : "192.0.2.1"
  const snapshotId = "70000000-0000-0000-0000-000000000001"
  const evidence = (
    fact_type: LineageEvidenceReferencePublic["fact_type"],
    fact_id: string,
    index: number,
  ) => ({
    id: `f0000000-0000-0000-0000-${String(index).padStart(12, "0")}`,
    governance_run_id: run,
    fact_type,
    fact_id,
  })
  const comparison: LineageComparisonNodePublic = {
    key: `comparison:${selectedResource}`,
    kind: "COMPARISON",
    resource_id: selectedResource,
    canonical_ip: ip,
    customer_upload_present: true,
    cloudatlas_present: false,
    classification: "customer_upload_only",
    classification_reason: "customer_upload_only",
    netflow_status: netflow === "active" ? "ACTIVE" : "UNKNOWN",
    netflow_reason:
      netflow === "absent"
        ? "netflow_input_absent"
        : netflow === "active"
          ? "positive_activity_evidence"
          : "no_positive_activity_evidence",
    content_hash: hash,
    comparison_fact_id:
      version === "deterministic-report-v1"
        ? null
        : "10000000-0000-0000-0000-000000000001",
    observations: {
      count: 1,
      data: [{ observation_id: observationId, source_snapshot_id: snapshotId }],
      truncated: false,
    },
    evidence: { count: 0, data: [], truncated: false },
  }
  if (comparison.comparison_fact_id) {
    comparison.evidence = {
      count: 1,
      data: [
        evidence("IP_SOURCE_COMPARISON", comparison.comparison_fact_id, 1),
      ],
      truncated: false,
    }
  }
  const finding: LineageFindingNodePublic = {
    key: `finding:${findingId}`,
    kind: "FINDING",
    finding_id: findingId,
    resource_id: partial ? outsideResourceId : selectedResource,
    canonical_ip: partial ? longIp : ip,
    finding_type: "UNOBSERVED_ASSET",
    occurrence_id: occurrenceId,
    transition_id: transitionId,
    transition_type: "REOPENED",
    source_snapshot_ids: [snapshotId],
    observations: {
      count: 1,
      data: [{ observation_id: observationId, source_snapshot_id: snapshotId }],
      truncated: false,
    },
    evidence: {
      count: 2,
      data: [
        evidence("FINDING_OCCURRENCE", occurrenceId, 2),
        evidence("FINDING_TRANSITION", transitionId, 3),
      ],
      truncated: false,
    },
  }
  const report: LineageReportNodePublic = {
    key: `report:${reportId}`,
    kind: "REPORT",
    governance_report_id: reportId,
    report_contract_version: version,
    generation_mode: "DETERMINISTIC_TEMPLATE",
    html_sha256: "d".repeat(64),
    csv_sha256: "e".repeat(64),
    summary:
      resource !== undefined || partial
        ? {
            customer_observed_asset_count: 31,
            cloudatlas_observed_asset_count: 22,
            matched_asset_count: 12,
            current_run_finding_count: 27,
            current_run_transition_count: 5,
            open_backlog_count: 9,
          }
        : {
            customer_observed_asset_count: 1,
            cloudatlas_observed_asset_count: 0,
            matched_asset_count: 0,
            current_run_finding_count: 1,
            current_run_transition_count: 1,
            open_backlog_count: 9,
          },
    evidence: {
      count: 2,
      data: [
        evidence("SOURCE_SNAPSHOT", snapshotId, 4),
        evidence("OBSERVATION", observationId, 5),
      ],
      truncated: false,
    },
  }
  const dto: GovernanceRunLineagePublic = {
    projection_version: "published-lineage/v1",
    project_id: project,
    governance_run_id: run,
    governance_report_id: reportId,
    run_status: "COMPLETED",
    completed_at: completedAt,
    input_contract_version: "governance-run-input-v1",
    processing_contract_version: "ip-v1",
    report_contract_version: version,
    comparison_output_hash: hash,
    view: resource === undefined ? "OVERVIEW" : "RESOURCE",
    resource_id: resource ?? null,
    status: empty ? "EMPTY" : partial ? "PARTIAL" : "COMPLETE",
    truncated: partial,
    truncation_reasons: partial
      ? [
          "comparison_limit",
          "finding_limit",
          "observation_reference_limit",
          "evidence_reference_limit",
        ]
      : [],
    totals: {
      comparison_count: resource !== undefined || partial ? 41 : 1,
      finding_event_count: resource !== undefined || partial ? 27 : 1,
    },
    coverage: {
      comparison_count: empty ? 0 : partial ? 41 : 1,
      finding_event_count: empty ? 0 : partial ? 27 : 1,
      comparison_returned: empty ? 0 : 1,
      finding_returned: empty ? 0 : 1,
    },
    nodes: [],
    edges: [],
  }
  const edge = (
    kind: GovernanceRunLineagePublic["edges"][number]["kind"],
    from: string,
    to: string,
  ) => {
    dto.edges.push({ key: `${kind}:${from}:${to}`, kind, from, to })
  }
  for (const [index, source] of (
    ["CUSTOMER_UPLOAD", "CLOUDATLAS", "NETFLOW"] as const
  ).entries()) {
    const absent = source === "NETFLOW" && netflow === "absent"
    const key = `source:${source}`
    const snapshot = `70000000-0000-0000-0000-00000000000${index + 1}`
    dto.nodes.push({
      key,
      kind: "SOURCE",
      source_type: source,
      state: absent ? "ABSENT" : "PRESENT",
      input_id: absent
        ? null
        : `80000000-0000-0000-0000-00000000000${index + 1}`,
    })
    if (absent) {
      edge("ABSENT_SOURCE_PROCESS", key, `process:${run}`)
    } else {
      dto.nodes.push({
        key: `snapshot:${snapshot}`,
        kind: "SNAPSHOT",
        snapshot_id: snapshot,
        source_type: source,
        content_sha256: hash,
        schema_fingerprint: schemaHash,
        method_fingerprint: source === "CLOUDATLAS" ? methodHash : null,
        record_count: source === "NETFLOW" && netflow === "zero" ? 0 : 31,
        valid_time_start_utc:
          source === "CUSTOMER_UPLOAD" ? null : "2026-09-01T11:00:00Z",
        valid_time_end_utc: source === "CUSTOMER_UPLOAD" ? null : completedAt,
      })
      edge("SOURCE_SNAPSHOT", key, `snapshot:${snapshot}`)
      edge("SNAPSHOT_PROCESS", `snapshot:${snapshot}`, `process:${run}`)
    }
  }
  dto.nodes.push({
    key: `process:${run}`,
    kind: "PROCESS",
    governance_run_id: run,
    processing_contract_version: "ip-v1",
    comparison_contract_version: "ip-source-comparison/v1",
    report_contract_version: version,
  })
  if (!empty) {
    dto.nodes.push(comparison, finding)
    edge("PROCESS_COMPARISON", `process:${run}`, comparison.key)
    edge("PROCESS_FINDING", `process:${run}`, finding.key)
    edge("COMPARISON_REPORT_CONTEXT", comparison.key, report.key)
    edge("FINDING_REPORT_CONTEXT", finding.key, report.key)
  }
  dto.nodes.push(report)
  edge("PROCESS_REPORT", `process:${run}`, report.key)
  if (partial) {
    // Both bounded result groups contain their first 20 items independently.
    for (let index = 2; index <= 20; index++) {
      const id = `a0000000-0000-0000-0000-${String(index).padStart(12, "0")}`
      const factId = `10000000-0000-0000-0000-${String(index).padStart(12, "0")}`
      const item = {
        ...comparison,
        key: `comparison:${id}`,
        resource_id: id,
        canonical_ip: `192.0.2.${index}`,
        comparison_fact_id: factId,
        observations: { count: 0, data: [], truncated: false },
        evidence: { count: 0, data: [], truncated: false },
      }
      dto.nodes.push(item)
      edge("PROCESS_COMPARISON", `process:${run}`, item.key)
      edge("COMPARISON_REPORT_CONTEXT", item.key, report.key)
    }
    dto.totals.finding_event_count = 27
    dto.coverage.finding_event_count = 27
    for (let index = 2; index <= 20; index++) {
      const id = `b0000000-0000-0000-0000-${String(index).padStart(12, "0")}`
      const item: LineageFindingNodePublic = {
        ...finding,
        key: `finding:${id}`,
        finding_id: id,
        occurrence_id: `c0000000-0000-0000-0000-${String(index).padStart(12, "0")}`,
        transition_id: null,
        transition_type: null,
        resource_id: `a0000000-0000-0000-0000-${String(index + 20).padStart(12, "0")}`,
        canonical_ip: `198.51.100.${index + 20}`,
        observations: { count: 0, data: [], truncated: false },
        evidence: { count: 0, data: [], truncated: false },
      }
      dto.nodes.push(item)
      edge("PROCESS_FINDING", `process:${run}`, item.key)
      edge("FINDING_REPORT_CONTEXT", item.key, report.key)
    }
    dto.coverage.comparison_returned = 20
    dto.coverage.finding_returned = 20
    comparison.observations = {
      count: 23,
      truncated: true,
      data: Array.from({ length: 20 }, (_, index) => ({
        observation_id: `e0000000-0000-0000-0000-${String(index + 1).padStart(12, "0")}`,
        source_snapshot_id: snapshotId,
      })),
    }
    report.evidence = {
      count: 24,
      truncated: true,
      data: Array.from({ length: 20 }, (_, index) =>
        evidence(
          "OBSERVATION",
          `e0000000-0000-0000-0000-${String(index + 1).padStart(12, "0")}`,
          index + 1,
        ),
      ),
    }
  }
  return dto
}

function reportDetail(
  dto: GovernanceRunLineagePublic,
): GovernanceReportDetailPublic {
  const report = reportNode(dto)
  const snapshots = dto.nodes.filter((item) => item.kind === "SNAPSHOT")
  return {
    id: dto.governance_report_id,
    governance_run_id: dto.governance_run_id,
    run_completed_at: completedAt,
    created_at: completedAt,
    report_contract_version: dto.report_contract_version,
    generation_mode: report.generation_mode,
    html_sha256: report.html_sha256,
    csv_sha256: report.csv_sha256,
    evidence: [],
    evidence_count: 0,
    evidence_max_entries: 50,
    can_request_ai_governance_draft: false,
    ai_governance_drafts: [],
    canonical_content: {
      schema_version: dto.report_contract_version,
      report: {
        report_identity: {
          project_id: dto.project_id,
          governance_run_id: dto.governance_run_id,
          report_contract_version: dto.report_contract_version,
          run_completed_at: completedAt,
          generation_mode: report.generation_mode,
        },
        input_completeness: {
          complete: true,
          sources: snapshots.map((snapshot) => ({
            source_type: snapshot.source_type,
            source_snapshot_id: snapshot.snapshot_id,
            content_sha256: snapshot.content_sha256,
            schema_version: "ip-v1",
            record_count: snapshot.record_count,
          })),
        },
        ip_consistency_summary: {
          ...report.summary,
          all_observed_ip_identities_matched: false,
          finding_counts: [
            {
              finding_type: "UNOBSERVED_ASSET",
              count: report.summary.current_run_finding_count,
            },
          ],
        },
        current_run_lifecycle_changes: {
          total: report.summary.current_run_transition_count,
          transition_counts: [
            {
              transition_type: "REOPENED",
              count: report.summary.current_run_transition_count,
            },
          ],
          changes: [],
        },
        open_backlog_as_of_run: {
          as_of_governance_run_id: dto.governance_run_id,
          total: report.summary.open_backlog_count,
          finding_counts: [
            {
              finding_type: "UNOBSERVED_ASSET",
              count: report.summary.open_backlog_count,
            },
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
              finding_type: "UNOBSERVED_ASSET",
              present: true,
              direction: "补充扫描目标并重新扫描",
            },
          ],
          limitations: ["未观测资产不表示资产不存在"],
        },
        provenance: {
          governance_run_id: dto.governance_run_id,
          processing_contract_version: "ip-v1",
          source_snapshot_ids: snapshots.map(
            (snapshot) => snapshot.snapshot_id,
          ),
          source_snapshot_hashes: snapshots.map(
            (snapshot) => snapshot.content_sha256,
          ),
          finding_lifecycle_fact_count: dto.totals.finding_event_count,
        },
        ...(dto.report_contract_version === "deterministic-report-v2"
          ? { ip_source_comparison: { results: comparisons(dto) } }
          : {}),
      },
      evidence_plan: {
        governance_run_id: dto.governance_run_id,
        report_contract_version: dto.report_contract_version,
        max_entries: 50,
        entries: [],
        ...(dto.report_contract_version === "deterministic-report-v2"
          ? { comparison_entries: [] }
          : {}),
      },
    },
  }
}

async function installMocks(
  page: Page,
  payloads: GovernanceRunLineagePublic[],
) {
  const requests: { url: URL; method: string }[] = []
  const unexpected: string[] = []
  await page.addInitScript(() =>
    localStorage.setItem("access_token", "component-token"),
  )
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/v1/"))
      requests.push({ url: new URL(request.url()), method: request.method() })
  })
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === "/api/v1/users/me") {
      await route.fulfill({
        json: {
          email: "viewer@example.com",
          full_name: "Test Viewer",
          id: "30000000-0000-0000-0000-000000000001",
          is_active: true,
          is_superuser: false,
        },
      })
      return
    }
    if (url.pathname === "/api/v1/projects/") {
      await route.fulfill({
        json: {
          data: [projectId, otherProjectId].map((id, index) => ({
            id,
            name: index ? "South Plant" : "North Plant",
            tenant_id: "00000000-0000-0000-0000-000000000010",
            created_at: completedAt,
            updated_at: completedAt,
            archived_at: null,
          })),
          count: 2,
        },
      })
      return
    }
    const match = url.pathname.match(
      /\/projects\/([^/]+)\/governance-runs\/([^/]+)\/(lineage|sources|ip-source-comparisons)$/,
    )
    if (match) {
      const runPayloads = payloads.filter(
        (dto) =>
          dto.project_id === match[1] && dto.governance_run_id === match[2],
      )
      const dto = runPayloads.find(
        (item) =>
          item.resource_id ===
          (match[3] === "lineage" ? url.searchParams.get("resource_id") : null),
      )
      if (!dto) {
        await route.fulfill({
          status: 404,
          json: { detail: "Published result unavailable" },
        })
      } else if (match[3] === "lineage") {
        await route.fulfill({ json: dto })
      } else if (match[3] === "sources") {
        await route.fulfill({
          json: {
            project_id: dto.project_id,
            governance_run_id: dto.governance_run_id,
            governance_report_id: dto.governance_report_id,
            run_status: dto.run_status,
            completed_at: dto.completed_at,
            input_contract_version: dto.input_contract_version,
            processing_contract_version: dto.processing_contract_version,
            report_contract_version: dto.report_contract_version,
            sources: dto.nodes
              .filter((item) => item.kind === "SOURCE")
              .map((source) => {
                const snapshot = dto.nodes.find(
                  (item) =>
                    item.kind === "SNAPSHOT" &&
                    item.source_type === source.source_type,
                )
                return {
                  source_type: source.source_type,
                  state: source.state,
                  input_id: source.input_id,
                  snapshot_id:
                    snapshot?.kind === "SNAPSHOT" ? snapshot.snapshot_id : null,
                  content_sha256:
                    snapshot?.kind === "SNAPSHOT"
                      ? snapshot.content_sha256
                      : null,
                  schema_fingerprint:
                    snapshot?.kind === "SNAPSHOT"
                      ? snapshot.schema_fingerprint
                      : null,
                  method_fingerprint:
                    snapshot?.kind === "SNAPSHOT"
                      ? snapshot.method_fingerprint
                      : null,
                  record_count:
                    snapshot?.kind === "SNAPSHOT"
                      ? snapshot.record_count
                      : null,
                  valid_time_start_utc:
                    snapshot?.kind === "SNAPSHOT"
                      ? snapshot.valid_time_start_utc
                      : null,
                  valid_time_end_utc:
                    snapshot?.kind === "SNAPSHOT"
                      ? snapshot.valid_time_end_utc
                      : null,
                }
              }),
          } satisfies GovernanceRunSourcesPublic,
        })
      } else {
        const rows = [
          ...new Map(
            runPayloads
              .flatMap(comparisons)
              .map((row) => [row.resource_id, row]),
          ).values(),
        ]
        const filtered = rows.filter(
          (row) =>
            (!url.searchParams.has("classification") ||
              row.classification === url.searchParams.get("classification")) &&
            (!url.searchParams.has("netflow_status") ||
              row.netflow_status === url.searchParams.get("netflow_status")),
        )
        const skip = Number(url.searchParams.get("skip") ?? 0)
        await route.fulfill({
          json: {
            project_id: dto.project_id,
            governance_run_id: dto.governance_run_id,
            governance_report_id: dto.governance_report_id,
            report_contract_version: dto.report_contract_version,
            contract_version: "ip-source-comparison/v1",
            output_hash: hash,
            data: filtered.slice(skip, skip + 25),
            count: filtered.length,
            page_size: 25,
          } satisfies IPSourceComparisonsPublic,
        })
      }
      return
    }
    if (url.pathname.endsWith("/governance-runs")) {
      const data: GovernanceRunPublic[] = payloads
        .filter(
          (dto) =>
            dto.view === "OVERVIEW" &&
            url.pathname.includes(`/projects/${dto.project_id}/`),
        )
        .map((dto) => ({
          id: dto.governance_run_id,
          trigger_id: dto.governance_run_id,
          session_id: hash,
          status: "COMPLETED",
          customer_upload_id: "80000000-0000-0000-0000-000000000001",
          customer_upload_sha256: hash,
          customer_upload_profile_id: projectId,
          customer_upload_profile_version: 1,
          source_instance_id: "80000000-0000-0000-0000-000000000002",
          cloudatlas_validated_fingerprint: hash,
          cloudatlas_capset_id: "cloudatlas-readonly",
          cloudatlas_method:
            "cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets",
          package_sha256: hash,
          descriptor_sha256: hash,
          runner_build_version: "runner-v1",
          processing_contract_version: "ip-v1",
          created_at: completedAt,
          completed_at: completedAt,
          session_terminal_at: completedAt,
          session_recovery_code: null,
          steps: [],
          snapshots: [],
        }))
      await route.fulfill({
        json: {
          data: data.reverse(),
          count: data.length,
          can_trigger: false,
          ready: false,
          readiness_code: "run_customer_upload_not_ready",
          launch_blocking_code: null,
        },
      })
      return
    }
    if (url.pathname.endsWith("/analysis-reports")) {
      await route.fulfill({ json: { data: [], count: 0, can_create: false } })
      return
    }
    if (url.pathname.endsWith("/governance-reports")) {
      await route.fulfill({
        json: {
          data: [
            ...new Map(
              payloads
                .filter((dto) =>
                  url.pathname.includes(`/projects/${dto.project_id}/`),
                )
                .map((dto) => [dto.governance_report_id, reportDetail(dto)]),
            ).values(),
          ],
          next_cursor: null,
        },
      })
      return
    }
    const report = payloads.find(
      (dto) =>
        url.pathname ===
        `/api/v1/projects/${dto.project_id}/governance-reports/${dto.governance_report_id}`,
    )
    if (report) {
      await route.fulfill({ json: reportDetail(report) })
      return
    }
    if (url.pathname.endsWith("/customer-upload-profile")) {
      await route.fulfill({
        json: {
          id: projectId,
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
    if (url.pathname.endsWith("/cloudatlas-source-instances")) {
      await route.fulfill({ json: { data: [], count: 0, can_manage: false } })
      return
    }
    unexpected.push(url.pathname)
    await route.fulfill({
      status: 500,
      json: { detail: "Unexpected API request" },
    })
  })
  return { requests, unexpected }
}

function responseGate() {
  let release = () => {}
  const ready = new Promise<void>((resolve) => {
    release = resolve
  })
  return { ready, release: () => release() }
}

test("navigates the explicit historical Run and an asset outside overview, preserving matrix filters and browser scope", async ({
  page,
}) => {
  const overview = publishedLineage({ partial: true })
  const resource = publishedLineage({ resource: outsideResourceId })
  const { requests, unexpected } = await installMocks(page, [
    overview,
    resource,
    publishedLineage({ run: newerRunId }),
  ])
  await page.goto(lineagePath())
  await expect(
    page.getByRole("heading", { name: "Run lineage", exact: true }),
  ).toBeVisible()
  await expect(node(page, "COMPARISON", longIp)).toHaveCount(0)
  await page
    .getByRole("link", { name: "View source comparison", exact: true })
    .click()
  await page
    .getByRole("combobox", { name: "Classification", exact: true })
    .selectOption("customer_upload_only")
  await expect(page).toHaveURL(/classification=customer_upload_only/)
  const filteredUrl = page.url()
  await page
    .getByRole("row")
    .filter({ has: page.getByRole("cell", { name: longIp, exact: true }) })
    .getByRole("link", { name: `Trace asset ${longIp}`, exact: true })
    .click()
  await expect(page).toHaveURL(
    (url) =>
      url.searchParams.get("resource_id") === outsideResourceId &&
      url.searchParams.get("classification") === "customer_upload_only",
  )
  await expect(node(page, "COMPARISON", longIp)).toBeVisible()
  await page.reload()
  await expect(node(page, "COMPARISON", longIp)).toBeVisible()
  await page.goBack()
  await expect(page).toHaveURL(filteredUrl)
  await page.goForward()
  await expect(node(page, "COMPARISON", longIp)).toBeVisible()
  await page
    .getByRole("link", { name: "View source comparison", exact: true })
    .click()
  await expect(page).toHaveURL(
    (url) =>
      url.pathname.endsWith("/comparison") &&
      url.searchParams.get("classification") === "customer_upload_only" &&
      url.searchParams.get("resource_id") === outsideResourceId,
  )
  await page
    .getByRole("main")
    .getByRole("link", { name: "Lineage", exact: true })
    .click()
  await page
    .getByRole("link", { name: "Back to overview", exact: true })
    .click()
  await expect(page).toHaveURL(
    (url) =>
      url.pathname === lineagePath() &&
      !url.searchParams.has("resource_id") &&
      url.searchParams.get("classification") === "customer_upload_only",
  )
  await expect(node(page, "COMPARISON", longIp)).toHaveCount(0)
  const lineageRequests = requests.filter(({ url }) =>
    url.pathname.endsWith("/lineage"),
  )
  expect(lineageRequests.every(({ url }) => url.pathname.includes(runId))).toBe(
    true,
  )
  expect(
    lineageRequests.every(({ url }) =>
      [...url.searchParams.keys()].every((key) => key === "resource_id"),
    ),
  ).toBe(true)
  expect(unexpected).toEqual([])
})

test("switches language without losing asset details, report identity or focus", async ({
  page,
}) => {
  const dto = publishedLineage({ resource: resourceId, netflow: "absent" })
  await installMocks(page, [dto])
  await page.goto(lineagePath(resourceId))
  await node(page, "FINDING", "192.0.2.1").click()
  await expect(details(page)).toContainText(occurrenceId)
  await page
    .getByRole("combobox", { name: "Language / 语言" })
    .selectOption("zh-CN")
  const chineseDetails = page.getByRole("region", {
    name: "节点详情",
    exact: true,
  })
  await expect(chineseDetails).toContainText(occurrenceId)
  await expect(chineseDetails).toContainText(observationId)
  await expect(page).toHaveURL(new RegExp(`resource_id=${resourceId}$`))
  await page
    .getByRole("combobox", { name: "Language / 语言" })
    .selectOption("en")
  await expect(node(page, "FINDING", "192.0.2.1")).toHaveAttribute(
    "aria-pressed",
    "true",
  )
  await node(page, "REPORT", dto.governance_report_id).click()
  const readReport = details(page).getByRole("button", {
    name: "Read report",
    exact: true,
  })
  await readReport.click()
  const dialog = page.getByRole("dialog")
  await expect(dialog).toContainText(dto.governance_run_id)
  await dialog
    .getByRole("combobox", { name: "Language / 语言" })
    .selectOption("zh-CN")
  await expect(dialog).toContainText(dto.governance_run_id)
  await expect(dialog).toContainText(hash)
  await expect(dialog).toContainText("补充扫描目标并重新扫描")
  await expect(dialog).toContainText("未观测资产不表示资产不存在")
  await dialog
    .getByRole("combobox", { name: "Language / 语言" })
    .selectOption("en")
  await page.keyboard.press("Escape")
  await expect(readReport).toBeFocused()
  await expect(node(page, "REPORT", dto.governance_report_id)).toHaveAttribute(
    "aria-pressed",
    "true",
  )
  await expect(page).toHaveURL(new RegExp(`resource_id=${resourceId}$`))
})

test("shows all six node details and returned reference identities, with directed paths excluding sibling Findings", async ({
  page,
}) => {
  const dto = publishedLineage({ netflow: "absent" })
  const newer = publishedLineage({ run: newerRunId })
  const laterFinding = findings(newer)[0]
  laterFinding.occurrence_id = null
  laterFinding.transition_type = "CLOSED"
  laterFinding.transition_id = "d0000000-0000-0000-0000-000000000002"
  laterFinding.evidence = { count: 0, data: [], truncated: false }
  const { unexpected } = await installMocks(page, [dto, newer])
  await page.goto(lineagePath())
  await expect(nodes(page).getByRole("button", { pressed: true })).toHaveCount(
    0,
  )
  await node(page, "SOURCE", "NETFLOW").click()
  await expect(details(page)).toContainText("ABSENT")
  await expect(
    details(page).getByText("Input ID", { exact: true }).locator(".."),
  ).toContainText(/not provided/i)
  await node(page, "SOURCE", "CUSTOMER_UPLOAD").click()
  await expect(details(page)).toContainText(
    "80000000-0000-0000-0000-000000000001",
  )
  await node(page, "SNAPSHOT", "70000000-0000-0000-0000-000000000001").click()
  await expect(
    details(page)
      .getByText("Valid time start (UTC)", { exact: true })
      .locator(".."),
  ).toContainText(/not provided/i)
  await node(page, "SNAPSHOT", "70000000-0000-0000-0000-000000000002").click()
  for (const value of [
    "70000000-0000-0000-0000-000000000002",
    hash,
    schemaHash,
    methodHash,
    "31",
  ])
    await expect(details(page)).toContainText(value)
  await expect(details(page)).toContainText("9/1/2026, 11:00:00 AM UTC")
  await expect(details(page)).toContainText("9/1/2026, 12:00:00 PM UTC")
  await node(page, "PROCESS", runId).click()
  for (const value of [
    runId,
    "ip-v1",
    "ip-source-comparison/v1",
    dto.report_contract_version,
  ])
    await expect(details(page)).toContainText(value)
  await node(page, "COMPARISON", "192.0.2.1").click()
  for (const value of [
    resourceId,
    "customer_upload_only",
    "UNKNOWN",
    "netflow_input_absent",
    hash,
    observationId,
  ])
    await expect(details(page)).toContainText(value)
  await expect(
    details(page)
      .getByText("CustomerUpload presence", { exact: true })
      .locator(".."),
  ).toContainText("Observed")
  await expect(
    details(page)
      .getByText("CloudAtlas presence", { exact: true })
      .locator(".."),
  ).toContainText("Not observed")
  const paths = page.getByRole("region", {
    name: "Selected paths",
    exact: true,
  })
  for (const kind of [
    "SOURCE_SNAPSHOT",
    "SNAPSHOT_PROCESS",
    "ABSENT_SOURCE_PROCESS",
    "PROCESS_COMPARISON",
    "COMPARISON_REPORT_CONTEXT",
  ])
    await expect(paths).toContainText(kind)
  await expect(paths).not.toContainText("PROCESS_FINDING")
  await expect(paths).not.toContainText("FINDING_REPORT_CONTEXT")
  await expect(paths).not.toContainText(findingId)
  await expect(node(page, "FINDING", "192.0.2.1")).not.toContainText(
    /Upstream|Downstream/,
  )
  await node(page, "FINDING", "192.0.2.1").click()
  for (const value of [
    findingId,
    occurrenceId,
    transitionId,
    "REOPENED",
    "UNOBSERVED_ASSET",
    observationId,
    "FINDING_OCCURRENCE",
    "FINDING_TRANSITION",
  ])
    await expect(details(page)).toContainText(value)
  await expect(
    details(page).getByText(/^(Current|Latest) status$/i),
  ).toHaveCount(0)
  await expect(paths).toContainText("PROCESS_FINDING")
  await expect(paths).toContainText("FINDING_REPORT_CONTEXT")
  await node(page, "REPORT", dto.governance_report_id).click()
  for (const value of [
    dto.governance_report_id,
    dto.report_contract_version,
    "DETERMINISTIC_TEMPLATE",
    "d".repeat(64),
    "e".repeat(64),
    "SOURCE_SNAPSHOT",
    "OBSERVATION",
  ])
    await expect(details(page)).toContainText(value)
  await expect(paths).toContainText("PROCESS_REPORT")
  await expect(
    page.getByText(/关联，非因果|association.*not caus/i).first(),
  ).toBeVisible()
  await page.goto(lineagePath(undefined, newerRunId))
  await node(page, "FINDING", "192.0.2.1").click()
  await expect(details(page)).toContainText("CLOSED")
  await page.goBack()
  await node(page, "FINDING", "192.0.2.1").click()
  await expect(details(page)).toContainText("REOPENED")
  await expect(details(page)).toContainText(transitionId)
  await node(page, "REPORT", dto.governance_report_id).click()
  await details(page)
    .getByRole("button", { name: "Read report", exact: true })
    .click()
  const dialog = page.getByRole("dialog", {
    name: "Published deterministic report",
  })
  await expect(
    dialog.getByRole("article", { name: "Immutable governance report" }),
  ).toContainText(runId)
  await expect(dialog).not.toContainText(newerRunId)
  expect(unexpected).toEqual([])
})

for (const variant of [
  {
    name: "absent v1",
    netflow: "absent",
    legacy: false,
    state: "ABSENT",
    activity: "UNKNOWN",
    reason: "netflow_input_absent",
  },
  {
    name: "historical present v1",
    netflow: "active",
    legacy: true,
    state: "PRESENT",
    activity: "ACTIVE",
    reason: "positive_activity_evidence",
  },
  {
    name: "active v2",
    netflow: "active",
    legacy: false,
    state: "PRESENT",
    activity: "ACTIVE",
    reason: "positive_activity_evidence",
  },
  {
    name: "zero-record v2",
    netflow: "zero",
    legacy: false,
    state: "PRESENT",
    activity: "UNKNOWN",
    reason: "no_positive_activity_evidence",
  },
  {
    name: "no-positive-activity v2",
    netflow: "no-positive",
    legacy: false,
    state: "PRESENT",
    activity: "UNKNOWN",
    reason: "no_positive_activity_evidence",
  },
] as const) {
  test(`preserves ${variant.name} without reinterpreting presence, activity or legacy IDs`, async ({
    page,
  }) => {
    const dto = publishedLineage(variant)
    await installMocks(page, [dto])
    await page.goto(lineagePath())
    await node(page, "SOURCE", "NETFLOW").click()
    await expect(details(page)).toContainText(variant.state)
    if (variant.netflow === "zero") {
      await node(
        page,
        "SNAPSHOT",
        "70000000-0000-0000-0000-000000000003",
      ).click()
      await expect(details(page).getByText("0", { exact: true })).toBeVisible()
    }
    await node(page, "COMPARISON", "192.0.2.1").click()
    await expect(details(page)).toContainText(variant.activity)
    await expect(details(page)).toContainText(variant.reason)
    if (dto.report_contract_version === "deterministic-report-v1") {
      await expect(details(page)).toContainText(/not applicable|不适用/i)
      await expect(details(page)).toContainText(
        /read.only projection|只读投影/i,
      )
    } else {
      await expect(details(page)).toContainText(
        comparisons(dto)[0].comparison_fact_id!,
      )
      await expect(details(page)).toContainText("IP_SOURCE_COMPARISON")
    }
    await expect(page.getByRole("alert")).toHaveCount(0)
  })
}

test("keeps partial coverage and bounded references distinct from complete Run report summary", async ({
  page,
}) => {
  const dto = publishedLineage({ partial: true })
  const resource = publishedLineage({ resource: outsideResourceId })
  const { unexpected } = await installMocks(page, [dto, resource])
  await page.goto(lineagePath())
  await expect(page.getByText("PARTIAL", { exact: true })).toBeVisible()
  for (const reason of dto.truncation_reasons)
    await expect(page.getByText(reason, { exact: true })).toBeVisible()
  await expect(
    nodes(page).getByRole("button").filter({ hasText: "COMPARISON" }),
  ).toHaveCount(20)
  await expect(
    nodes(page).getByRole("button").filter({ hasText: "FINDING" }),
  ).toHaveCount(20)
  const coverage = page.getByRole("region", {
    name: "Lineage scope and coverage",
  })
  await expect(
    coverage.getByText("Comparison coverage", { exact: true }).locator(".."),
  ).toContainText("20 / 41")
  await expect(
    coverage.getByText("Finding event coverage", { exact: true }).locator(".."),
  ).toContainText("20 / 27")
  await node(page, "COMPARISON", "192.0.2.1").click()
  await expect(
    details(page).getByRole("region", { name: "Observation references" }),
  ).toContainText("Count: 23 · Returned: 20 · Truncated: true")
  await expect(details(page)).toContainText(
    "e0000000-0000-0000-0000-000000000020",
  )
  await node(page, "REPORT", dto.governance_report_id).click()
  await expect(
    details(page).getByRole("region", { name: "Evidence references" }),
  ).toContainText("Count: 24 · Returned: 20 · Truncated: true")
  await page.goto(lineagePath(outsideResourceId))
  await node(page, "REPORT", resource.governance_report_id).click()
  await expect(details(page)).toContainText(/full.run|完整 Run/i)
  for (const [label, value] of Object.entries(reportNode(resource).summary)) {
    await expect(
      details(page).getByText(label, { exact: true }).locator(".."),
    ).toContainText(String(value))
  }
  expect(unexpected).toEqual([])
})

test("retains context for an EMPTY resource and does not equate zero Evidence with missing facts", async ({
  page,
}) => {
  const empty = publishedLineage({ resource: outsideResourceId, empty: true })
  const zeroEvidence = publishedLineage({ netflow: "absent" })
  findings(zeroEvidence)[0].evidence = { count: 0, data: [], truncated: false }
  await installMocks(page, [zeroEvidence, empty])
  await page.goto(lineagePath())
  await node(page, "FINDING", "192.0.2.1").click()
  await expect(details(page)).toContainText(findingId)
  await expect(details(page)).toContainText(/no.*sample|无.*样本/i)
  await page.goto(lineagePath(outsideResourceId))
  await expect(page.getByText("EMPTY", { exact: true })).toBeVisible()
  await expect(
    nodes(page).getByRole("button").filter({ hasText: "COMPARISON" }),
  ).toHaveCount(0)
  await expect(
    nodes(page).getByRole("button").filter({ hasText: "FINDING" }),
  ).toHaveCount(0)
  await expect(node(page, "SOURCE", "NETFLOW")).toBeVisible()
  await expect(node(page, "PROCESS", runId)).toBeVisible()
  await expect(node(page, "REPORT", empty.governance_report_id)).toBeVisible()
  await expect(
    page.getByText(
      /^(no assets|no traffic|no risk|没有资产|没有流量|没有风险)$/i,
    ),
  ).toHaveCount(0)
})

for (const mismatch of [
  "project_id",
  "governance_run_id",
  "view",
  "resource_id",
] as const) {
  test(`rejects a mismatched lineage ${mismatch} without showing its facts`, async ({
    page,
  }) => {
    const dto = publishedLineage({ resource: outsideResourceId })
    await installMocks(page, [dto])
    const wrong = {
      ...dto,
      [mismatch]:
        mismatch === "view"
          ? "OVERVIEW"
          : mismatch === "resource_id"
            ? resourceId
            : mismatch === "project_id"
              ? otherProjectId
              : newerRunId,
    }
    await page.route("**/governance-runs/*/lineage?*", (route) =>
      route.fulfill({ json: wrong }),
    )
    await page.goto(lineagePath(outsideResourceId))
    await expect(page.getByRole("alert")).toContainText(
      /identity|scope|身份|范围/i,
    )
    await expect(nodes(page)).toHaveCount(0)
    await expect(page.getByText(longIp, { exact: true })).toHaveCount(0)
  })
}

test("clears selected facts during a scope request and ignores its late response after browser back", async ({
  page,
}) => {
  const overview = publishedLineage()
  const resource = publishedLineage({ resource: outsideResourceId })
  await installMocks(page, [overview, resource])
  const gate = responseGate()
  let pending = false
  await page.route("**/governance-runs/*/lineage?*", async (route) => {
    pending = true
    await gate.ready
    await route.fallback()
  })
  await page.goto(lineagePath())
  await node(page, "COMPARISON", "192.0.2.1").click()
  await page
    .getByRole("link", { name: "View source comparison", exact: true })
    .click()
  await page
    .getByRole("row")
    .filter({ has: page.getByRole("cell", { name: longIp, exact: true }) })
    .getByRole("link", { name: `Trace asset ${longIp}`, exact: true })
    .click()
  await expect.poll(() => pending).toBe(true)
  await expect(page.getByRole("status")).toContainText(/loading/i)
  await expect(nodes(page)).toHaveCount(0)
  await expect(details(page)).toHaveCount(0)
  await page.goBack()
  await page
    .getByRole("main")
    .getByRole("link", { name: "Lineage", exact: true })
    .click()
  await expect(node(page, "COMPARISON", "192.0.2.1")).toBeVisible()
  const lateResponse = page.waitForResponse((response) =>
    response.url().includes(`resource_id=${outsideResourceId}`),
  )
  gate.release()
  await (await lateResponse).finished()
  await expect(page).toHaveURL(
    (url) =>
      url.pathname === lineagePath() && !url.searchParams.has("resource_id"),
  )
  await expect(node(page, "COMPARISON", longIp)).toHaveCount(0)
  await expect(nodes(page).getByRole("button", { pressed: true })).toHaveCount(
    0,
  )
})

for (const status of [404, 422, 503]) {
  test(`exposes ${status} without degrading to overview or an empty graph${status === 503 ? " and retries" : ""}`, async ({
    page,
  }) => {
    const resource = publishedLineage({ resource: outsideResourceId })
    const { requests } = await installMocks(page, [resource])
    let failing = true
    await page.route("**/governance-runs/*/lineage?*", async (route) => {
      if (failing)
        await route.fulfill({
          status,
          json: { detail: "Do not disclose internal scope" },
        })
      else await route.fallback()
    })
    await page.goto(lineagePath(outsideResourceId))
    await expect(page.getByRole("alert")).toContainText(
      status === 404
        ? /此 Run 或资产的已发布追溯结果不可用|published.*unavailable/i
        : status === 422
          ? /invalid|参数无效/i
          : /could not|failed|无法|失败/i,
    )
    await expect(page.getByRole("alert")).not.toContainText("Do not disclose")
    await expect(nodes(page)).toHaveCount(0)
    await expect(page).toHaveURL(
      new RegExp(`resource_id=${outsideResourceId}$`),
    )
    if (status === 503) {
      failing = false
      await page.getByRole("button", { name: /retry|try again/i }).click()
      await expect(node(page, "COMPARISON", longIp)).toBeVisible()
    }
    expect(
      requests
        .filter(({ url }) => url.pathname.endsWith("/lineage"))
        .every(
          ({ url }) =>
            url.searchParams.get("resource_id") === outsideResourceId,
        ),
    ).toBe(true)
  })
}

test("preserves invalid resource input instead of silently requesting overview", async ({
  page,
}) => {
  const { requests } = await installMocks(page, [publishedLineage()])
  await page.route("**/governance-runs/*/lineage?*", (route) =>
    route.fulfill({ status: 422, json: { detail: "Invalid resource ID" } }),
  )
  await page.goto(lineagePath("not-a-uuid"))
  await expect(page.getByRole("alert")).toContainText(/invalid|参数无效/i)
  await expect(page).toHaveURL(/resource_id=not-a-uuid$/)
  await expect(nodes(page)).toHaveCount(0)
  expect(
    requests
      .filter(({ url }) => url.pathname.endsWith("/lineage"))
      .every(({ url }) => url.searchParams.has("resource_id")),
  ).toBe(true)
})

test("supports keyboard selection, clearing, same-report reading and focus restoration at 375px", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 })
  const dto = publishedLineage({ resource: outsideResourceId })
  comparisons(dto)[0].classification_reason =
    `customer_upload_only: ${"published bounded reason ".repeat(30)}`
  const { requests, unexpected } = await installMocks(page, [dto])
  await page.goto(lineagePath(outsideResourceId))
  const comparison = node(page, "COMPARISON", longIp)
  await comparison.focus()
  await page.keyboard.press("Enter")
  await expect(comparison).toBeFocused()
  await expect(comparison).toHaveAttribute("aria-pressed", "true")
  await expect(details(page)).toContainText(hash)
  await expect(details(page)).toContainText(
    comparisons(dto)[0].classification_reason,
  )
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true)
  const graph = page.getByRole("region", { name: "Lineage graph", exact: true })
  await expect(graph).toHaveAttribute("tabindex", "0")
  await expect(graph.locator("svg")).toHaveAttribute("aria-hidden", "true")
  await page.keyboard.press("Tab")
  await expect(node(page, "FINDING", longIp)).toBeFocused()
  await page.keyboard.press("Space")
  await expect(node(page, "FINDING", longIp)).toHaveAttribute(
    "aria-pressed",
    "true",
  )
  await page.keyboard.press("Shift+Tab")
  await expect(comparison).toBeFocused()
  const clear = page.getByRole("button", {
    name: "Clear selection",
    exact: true,
  })
  await clear.focus()
  await page.keyboard.press("Enter")
  await expect(nodes(page).getByRole("button", { pressed: true })).toHaveCount(
    0,
  )
  expect(
    await page.evaluate(
      () =>
        document.activeElement !== document.body &&
        document.activeElement?.isConnected,
    ),
  ).toBe(true)
  await node(page, "REPORT", dto.governance_report_id).focus()
  await page.keyboard.press("Space")
  const readReport = details(page).getByRole("button", {
    name: "Read report",
    exact: true,
  })
  await readReport.focus()
  await page.keyboard.press("Enter")
  const dialog = page.getByRole("dialog", {
    name: "Published deterministic report",
  })
  await expect(
    dialog.getByRole("article", { name: "Immutable governance report" }),
  ).toContainText(runId)
  await expect(dialog).toContainText(dto.report_contract_version)
  await page.keyboard.press("Escape")
  await expect(dialog).toHaveCount(0)
  await expect(readReport).toBeFocused()
  await expect(node(page, "REPORT", dto.governance_report_id)).toHaveAttribute(
    "aria-pressed",
    "true",
  )
  await expect(page).toHaveURL(new RegExp(`resource_id=${outsideResourceId}$`))
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true)
  expect(
    requests
      .filter(({ url }) => url.pathname.includes("/governance-reports/"))
      .map(({ url }) => url.pathname),
  ).toEqual([
    `/api/v1/projects/${projectId}/governance-reports/${dto.governance_report_id}`,
  ])
  expect(requests.every(({ method }) => method === "GET")).toBe(true)
  expect(unexpected).toEqual([])
})

for (const mismatch of ["report", "run", "project", "contract"] as const) {
  test(`refuses mismatched ${mismatch} identity in the separately opened report`, async ({
    page,
  }) => {
    const dto = publishedLineage()
    await installMocks(page, [dto])
    const detail = reportDetail({
      ...dto,
      project_id: mismatch === "project" ? otherProjectId : projectId,
      governance_run_id: mismatch === "run" ? newerRunId : runId,
      report_contract_version:
        mismatch === "contract"
          ? "deterministic-report-v1"
          : dto.report_contract_version,
    })
    if (mismatch === "report") detail.id = newerRunId.replace(/^6/, "9")
    await page.route("**/governance-reports/*", (route) =>
      route.fulfill({ json: detail }),
    )
    await page.goto(lineagePath())
    await node(page, "REPORT", dto.governance_report_id).click()
    await details(page)
      .getByRole("button", { name: "Read report", exact: true })
      .click()
    await expect(page.getByRole("dialog").getByRole("alert")).toContainText(
      /identity mismatch/i,
    )
    await expect(
      page.getByRole("article", { name: "Immutable governance report" }),
    ).toHaveCount(0)
  })
}

for (const width of [1280, 1073, 375]) {
  test(`keeps graph zoom, directory and adjacent facts usable at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 800 })
    const dto = publishedLineage({ netflow: "absent", partial: true })
    await installMocks(page, [dto])
    await page.goto(lineagePath())
    const graph = page.getByRole("region", {
      name: "Lineage graph",
      exact: true,
    })
    const svg = graph.locator("svg")
    await expect(graph).toBeVisible()
    const initial = await svg.boundingBox()
    expect(initial).not.toBeNull()
    if (width >= 1073) expect((await graph.boundingBox())!.y).toBeLessThan(800)
    await page.getByRole("button", { name: "Zoom in", exact: true }).click()
    expect((await svg.boundingBox())!.width).toBeGreaterThan(initial!.width)
    await page.getByRole("button", { name: "Fit graph", exact: true }).click()
    const fit = await graph.evaluate((element) => ({
      width: element.clientWidth,
      height: element.clientHeight,
      svgWidth: element.querySelector("svg")!.getBoundingClientRect().width,
      svgHeight: element.querySelector("svg")!.getBoundingClientRect().height,
    }))
    expect(fit.svgWidth).toBeLessThanOrEqual(fit.width + 1)
    expect(fit.svgHeight).toBeLessThanOrEqual(fit.height + 1)
    await page.getByRole("button", { name: "Actual size", exact: true }).click()
    await graph.focus()
    await page.keyboard.press("ArrowRight")
    await expect
      .poll(() => graph.evaluate((element) => element.scrollLeft))
      .toBeGreaterThan(0)
    const directory = page.getByText("Node directory", { exact: true })
    await directory.focus()
    await page.keyboard.press("Enter")
    await expect(node(page, "SOURCE", "NETFLOW")).toBeHidden()
    await page.keyboard.press("Space")
    await expect(node(page, "SOURCE", "NETFLOW")).toBeVisible()
    await graph.evaluate((element) => element.scrollTo(0, 0))
    await graph.scrollIntoViewIfNeeded()
    const pageScroll = await page.evaluate(() => window.scrollY)
    await graph.locator("button").filter({ hasText: "NETFLOW" }).click()
    expect(await page.evaluate(() => window.scrollY)).toBe(pageScroll)
    await expect(details(page)).toContainText("ABSENT")
    const panel = page.getByRole("region", {
      name: "Node reading panel",
      exact: true,
    })
    if (width >= 1073) {
      const graphBox = (await graph.boundingBox())!
      const panelBox = (await panel.boundingBox())!
      expect(panelBox.x).toBeGreaterThanOrEqual(graphBox.x + graphBox.width)
      expect(panelBox.y).toBeLessThan(graphBox.y + 50)
    }
    await node(page, "FINDING", longIp).click()
    await expect(details(page)).toContainText(occurrenceId)
    await expect(details(page)).toContainText(observationId)
    await panel.focus()
    await page.keyboard.press("ArrowDown")
    await expect
      .poll(() => panel.evaluate((element) => element.scrollTop))
      .toBeGreaterThan(0)
    await page
      .getByRole("combobox", { name: "Language / 语言" })
      .selectOption("zh-CN")
    await expect(
      page.getByRole("region", { name: "节点详情", exact: true }),
    ).toContainText(occurrenceId)
    await expect(
      page.getByRole("button", { name: "适配画布", exact: true }),
    ).toBeVisible()
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true)
  })
}
