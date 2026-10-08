import { expect, type Page, test } from "./fixtures"

const project = "00000000-0000-4000-8000-000000000301"
const result = "10000000-0000-4000-8000-000000000301"
const source = "20000000-0000-4000-8000-000000000301"
const ipVersion = "30000000-0000-4000-8000-000000000301"
const portVersion = "40000000-0000-4000-8000-000000000301"
const root = `/api/v1/projects/${project}/comparison-results/${result}`
const envelope = { contract_version: "core-comparison-v2", project_id: project }
const summary = {
  ...envelope,
  id: result,
  scope_key: "a".repeat(64),
  purpose: "regular",
  status: "PUBLISHED",
  rule_version: "canonical-ip-presence-v1",
  published_at: "2026-10-01T00:00:00Z",
  created_at: "2026-10-01T00:00:00Z",
  customer_applied_at: "2026-10-01T00:00:00Z",
  customer_filename: "synthetic.xlsx",
  source_name: "Synthetic CloudAtlas",
  input_sha256: "b".repeat(64),
  selection: {
    network_namespace: "synthetic",
    customer: {
      upload_id: "50000000-0000-4000-8000-000000000301",
      revision_id: null,
    },
    cloud: {
      kind: "external_versions",
      source_instance_id: source,
      ip_version_id: ipVersion,
      port_version_id: portVersion,
    },
    netflow: null,
    history_run_id: null,
  },
  pins: { CLOUD: { domains: {} } },
  total_addresses: 3,
  comparison_state: "AVAILABLE",
  both: 1,
  customer_only: 1,
  cloud_only: 1,
  sources: [],
}

// Mocked HTTP proves route behavior only; it is not database or model acceptance.
async function serve(page: Page) {
  const writes: string[] = []
  await page.addInitScript(() =>
    localStorage.setItem("access_token", "synthetic-component-token"),
  )
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (request.method() !== "GET") writes.push(request.method())
    let json: object = { data: [], count: 0, can_manage: false }
    if (path === "/api/v1/users/me")
      json = {
        id: "synthetic-user",
        email: "synthetic@example.test",
        is_active: true,
        is_superuser: false,
      }
    else if (path === "/api/v1/projects/")
      json = {
        data: [{ id: project, name: "Synthetic project", status: "active" }],
        count: 1,
      }
    else if (path === `${root}/summary`) json = summary
    else if (path === `${root}/updates`)
      json = { ...envelope, result_id: result, state: "UNCHANGED" }
    else if (path === `${root}/addresses`)
      json = {
        ...envelope,
        result_id: result,
        count: 1,
        skip: 0,
        limit: 25,
        total_addresses: 3,
        data: [
          {
            address_key: `addr:${"c".repeat(64)}`,
            canonical_ip: "192.0.2.20",
            classification: "both",
            customer_records: 1,
            cloud_records: 1,
            presence: { CUSTOMER: "PRESENT", CLOUD: "PRESENT" },
          },
        ],
      }
    else if (path === `${root}/supplements`)
      json = { ...envelope, result_id: result, id: null, state: "NOT_PROVIDED" }
    await route.fulfill({ json })
  })
  return writes
}

for (const fault of [500, 403, "timeout"] as const) {
  test(`first supplement ${fault} keeps core readable and offers explicit retry`, async ({
    page,
  }) => {
    const writes = await serve(page)
    let failed = true
    let faultReads = 0
    await page.route(`**${root}/supplements`, async (route) => {
      if (failed) {
        faultReads += 1
        if (fault === "timeout") await route.abort("timedout")
        else
          await route.fulfill({
            status: fault,
            json: { detail: { code: "synthetic_read_failure" } },
          })
      } else
        await route.fulfill({
          json: {
            ...envelope,
            result_id: result,
            id: null,
            state: "NOT_PROVIDED",
          },
        })
    })
    await page.goto(`/projects/${project}/netflow-correlation?result=${result}`)
    await expect.poll(() => faultReads).toBeGreaterThan(0)
    const core = page.getByRole("region", { name: "Core classification" })
    await expect(
      core.getByRole("button", { name: /All addresses 3/ }),
    ).toBeVisible()
    await expect(
      core.getByText("Evidence unavailable", { exact: true }),
    ).toBeVisible()
    const supplement = page.getByRole("region", {
      name: "Optional NetFlow evidence",
    })
    await expect(supplement.getByRole("alert")).toBeVisible()
    await expect(
      supplement.getByText("Reading the evidence binding…", { exact: true }),
    ).toHaveCount(0)
    failed = false
    await supplement
      .getByRole("button", { name: "Retry reading evidence", exact: true })
      .click()
    await expect(page).toHaveURL(/binding=none/)
    await expect(
      core.getByRole("button", { name: /All addresses 3/ }),
    ).toBeVisible()
    expect(writes).toEqual([])
  })
}

test("each CloudAtlas domain opens its own fixed material version", async ({
  page,
}) => {
  const writes = await serve(page)
  await page.goto(
    `/projects/${project}/netflow-correlation?result=${result}&binding=none&core_class=cloud_only&core_page=2&core_ip=192.0.2.20&core_sort=ip_desc`,
  )
  await page.getByText("View the materials used here", { exact: true }).click()
  for (const [domain, version, name] of [
    ["ip", ipVersion, "Read the CloudAtlas IP version used here"],
    ["port", portVersion, "Read the CloudAtlas port version used here"],
  ]) {
    const link = page.getByRole("link", { name, exact: true })
    await expect(link).toBeVisible()
    const href = await link.getAttribute("href")
    const query = new URL(href!, "http://synthetic.test").searchParams
    expect(query.get("external_domain")).toBe(domain)
    expect(query.get("external_version")).toBe(version)
    expect(query.get("back_result")).toBe(result)
    expect(query.get("back_binding")).toBe("none")
    expect(query.get("back_class")).toBe("cloud_only")
    expect(query.get("back_page")).toBe("2")
    expect(query.get("back_ip")).toBe("192.0.2.20")
    expect(query.get("back_sort")).toBe("ip_desc")
  }
  expect(writes).toEqual([])
})

test("fixed evidence shows business fields, missing values and escaped source text", async ({
  page,
}) => {
  const writes = await serve(page)
  const key = `addr:${"c".repeat(64)}`
  await page.route(
    (url) => decodeURIComponent(url.pathname) === `${root}/addresses/${key}`,
    (route) =>
      route.fulfill({
        json: {
          ...envelope,
          result_id: result,
          address: {
            address_key: key,
            canonical_ip: "192.0.2.20",
            classification: "both",
            customer_records: 1,
            cloud_records: 1,
            presence: { CUSTOMER: "PRESENT", CLOUD: "PRESENT" },
          },
        },
      }),
  )
  const untrusted = "<img src=x onerror=alert(1)>declared owner"
  await page.route(
    (url) =>
      decodeURIComponent(url.pathname) === `${root}/addresses/${key}/evidence`,
    (route) => {
      const cloud =
        new URL(route.request().url()).searchParams.get("source") === "cloud"
      return route.fulfill({
        json: {
          ...envelope,
          result_id: result,
          address_key: key,
          source: cloud ? "cloud" : "customer",
          count: 1,
          skip: 0,
          limit: 25,
          data: [
            {
              source: cloud ? "CLOUD" : "CUSTOMER",
              record_key: "synthetic-record",
              version_id: cloud
                ? portVersion
                : summary.selection.customer.upload_id,
              domain: cloud ? "port" : "customer",
              canonical_ip: "192.0.2.20",
              original: cloud
                ? {
                    ip: "192.0.2.20",
                    port: 443,
                    protocol: "tcp",
                    service: "HTTPS",
                  }
                : {
                    fields: {
                      asset_ip: "192.0.2.20",
                      start_port: 0,
                      asset_owner: untrusted,
                    },
                  },
              availability: {},
            },
          ],
        },
      })
    },
  )
  await page.goto(
    `/projects/${project}/netflow-correlation?result=${result}&binding=none&core_address=${key}`,
  )
  const evidence = page.getByRole("region", { name: "Fixed address evidence" })
  await expect(
    evidence.getByRole("heading", {
      name: "Customer declaration",
      exact: true,
    }),
  ).toBeVisible()
  await expect(evidence.getByText(untrusted, { exact: true })).toBeVisible()
  await expect(evidence.locator("dd").filter({ hasText: /^0$/ })).toBeVisible()
  await expect(
    evidence.getByText("Not provided", { exact: true }).first(),
  ).toBeVisible()
  await expect(evidence.locator("img")).toHaveCount(0)
  await evidence
    .getByRole("button", { name: "CloudAtlas evidence", exact: true })
    .click()
  await expect(
    evidence.getByRole("heading", {
      name: "CloudAtlas observation",
      exact: true,
    }),
  ).toBeVisible()
  await expect(evidence.getByText("HTTPS", { exact: true })).toBeVisible()
  await expect(
    evidence.getByRole("region", { name: "NetFlow corroboration" }),
  ).toBeVisible()
  await expect(
    evidence.getByRole("region", { name: "Limits and sources" }),
  ).toBeVisible()
  await expect(
    page.getByRole("link", { name: "AI settings", exact: true }),
  ).toBeVisible()
  expect(writes).toEqual([])
})

test("a deep-linked address outside this page reads its own fixed flow annotation", async ({
  page,
}) => {
  await serve(page)
  const binding = "60000000-0000-4000-8000-000000000301"
  const key = `addr:${"d".repeat(64)}`
  const reads: string[][] = []
  await page.route(`**${root}/supplements/${binding}`, (route) =>
    route.fulfill({
      json: {
        ...envelope,
        result_id: result,
        id: binding,
        state: "ACTIVE",
        valid_until: "2099-01-01T00:00:00Z",
      },
    }),
  )
  await page.route(
    (url) => decodeURIComponent(url.pathname) === `${root}/addresses/${key}`,
    (route) =>
      route.fulfill({
        json: {
          ...envelope,
          result_id: result,
          address: {
            address_key: key,
            canonical_ip: "192.0.2.30",
            classification: "cloud_only",
            customer_records: 0,
            cloud_records: 1,
            presence: { CLOUD: "PRESENT" },
          },
        },
      }),
  )
  await page.route(
    (url) =>
      decodeURIComponent(url.pathname) === `${root}/addresses/${key}/evidence`,
    (route) =>
      route.fulfill({
        json: {
          ...envelope,
          result_id: result,
          address_key: key,
          source: "cloud",
          data: [],
          count: 0,
          skip: 0,
          limit: 25,
        },
      }),
  )
  await page.route(`**${root}/supplements/${binding}/addresses?*`, (route) => {
    const query = new URL(route.request().url()).searchParams
    const ips = query.getAll("ip")
    if (query.get("only_supplemental") !== "true") reads.push(ips)
    return route.fulfill({
      json: {
        ...envelope,
        result_id: result,
        binding_id: binding,
        analysis_id: "70000000-0000-4000-8000-000000000301",
        skip: 0,
        limit: 100,
        count: ips.includes("192.0.2.30") ? 1 : 0,
        data: ips.includes("192.0.2.30")
          ? [
              {
                canonical_ip: "192.0.2.30",
                in_core: true,
                observation_count: 2,
                source_records: 3,
              },
            ]
          : [],
      },
    })
  })
  await page.goto(
    `/projects/${project}/netflow-correlation?result=${result}&binding=${binding}&core_address=${key}&core_evidence=cloud`,
  )
  const flow = page.getByRole("region", { name: "NetFlow corroboration" })
  await expect(
    flow.getByText("Flow records in this batch", { exact: true }),
  ).toBeVisible()
  expect(reads.some((ips) => ips.includes("192.0.2.30"))).toBeTruthy()
})
