import { comparisonReturnFields } from "../src/lib/comparisonReturn"
import { expect, type Page, test } from "./fixtures"

test.beforeEach(async ({ page, baseURL }) => {
  if (!baseURL)
    throw new Error("The core-reading guard requires Playwright's baseURL")
  const allowedOrigin = new URL(baseURL).origin
  await page.context().route("**/*", (route) => {
    const url = new URL(route.request().url())
    if (url.origin !== allowedOrigin || url.pathname.startsWith("/api/"))
      return route.abort("blockedbyclient")
    return route.continue()
  })
})

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
    else if (
      path.startsWith(`${root}/addresses/`) &&
      path.endsWith("/evidence")
    ) {
      const query = new URL(request.url()).searchParams
      const key = decodeURIComponent(
        path.slice(`${root}/addresses/`.length, -"/evidence".length),
      )
      json = {
        ...envelope,
        result_id: result,
        address_key: key,
        source: query.get("source") === "cloud" ? "cloud" : "customer",
        data: [],
        count: 0,
        skip: Number(query.get("skip") ?? 0),
        limit: 25,
      }
    } else if (path === `${root}/supplements`)
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
  await expect(
    evidence.getByRole("heading", {
      name: "CloudAtlas observation",
      exact: true,
    }),
  ).toBeVisible()
  await expect(evidence.getByText("HTTPS", { exact: true })).toBeVisible()
  const before = page.url()
  await evidence
    .getByRole("button", { name: "CloudAtlas evidence", exact: true })
    .click()
  await expect(
    evidence.getByRole("heading", {
      name: "CloudAtlas observations",
      exact: true,
    }),
  ).toBeFocused()
  expect(page.url()).toBe(before)
  await expect(
    evidence.getByRole("region", { name: "CloudAtlas IP version" }),
  ).toBeVisible()
  await expect(
    evidence.getByRole("region", { name: "CloudAtlas PORT version" }),
  ).toBeVisible()
  await expect(
    evidence.getByText(portVersion, { exact: true }).first(),
  ).toBeVisible()
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
    (route) => {
      const query = new URL(route.request().url()).searchParams
      return route.fulfill({
        json: {
          ...envelope,
          result_id: result,
          address_key: key,
          source: query.get("source") === "cloud" ? "cloud" : "customer",
          data: [],
          count: 0,
          skip: Number(query.get("skip") ?? 0),
          limit: 25,
        },
      })
    },
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

test("evidence drawer keeps the list usable, restores focus and fits narrow screens", async ({
  page,
}, info) => {
  const writes = await serve(page)
  const address = {
    address_key: `addr:${"c".repeat(64)}`,
    canonical_ip: "2001:db8:1234:5678:abcd:ef01:2345:6789",
    classification: "both",
    customer_records: 1,
    cloud_records: 1,
    presence: { CUSTOMER: "PRESENT", CLOUD: "PRESENT" },
  }
  await page.route(`**${root}/addresses?*`, (route) =>
    route.fulfill({
      json: {
        ...envelope,
        result_id: result,
        count: 1,
        skip: 0,
        limit: 25,
        total_addresses: 3,
        data: [address],
      },
    }),
  )
  await page.route(
    (url) =>
      decodeURIComponent(url.pathname) ===
      `${root}/addresses/${address.address_key}`,
    (route) =>
      route.fulfill({ json: { ...envelope, result_id: result, address } }),
  )
  await page.route(
    (url) =>
      decodeURIComponent(url.pathname) ===
      `${root}/addresses/${address.address_key}/evidence`,
    (route) => {
      const cloud =
        new URL(route.request().url()).searchParams.get("source") === "cloud"
      return route.fulfill({
        json: {
          ...envelope,
          result_id: result,
          address_key: address.address_key,
          source: cloud ? "cloud" : "customer",
          count: cloud ? 0 : 1,
          skip: 0,
          limit: 25,
          data: cloud
            ? []
            : [
                {
                  source: "CUSTOMER",
                  domain: "customer",
                  version_id: summary.selection.customer.upload_id,
                  record_key: "synthetic-record",
                  canonical_ip: address.canonical_ip,
                  original: {
                    fields: {
                      asset_ip: address.canonical_ip,
                      start_port: 443,
                      asset_owner: "Synthetic operations team",
                      service_type: "HTTPS",
                    },
                  },
                  availability: {},
                },
              ],
        },
      })
    },
  )
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto(
    `/projects/${project}/netflow-correlation?result=${result}&binding=none`,
  )
  const table = page.getByRole("table", { name: "Comparison addresses" })
  const trigger = table.getByRole("button", { name: "View evidence" })
  const drawer = page.getByRole("dialog", { name: address.canonical_ip })
  await expect(trigger).toBeVisible()
  await page.screenshot({
    animations: "disabled",
    path: info.outputPath("comparison-desktop.png"),
    fullPage: true,
  })
  await trigger.focus()
  await page.keyboard.press("Enter")
  await expect(drawer).toBeVisible()
  await expect(
    drawer.getByRole("heading", { name: address.canonical_ip }),
  ).toBeFocused()
  await expect(table.getByRole("row").last()).toHaveAttribute(
    "data-state",
    "selected",
  )
  const input = page.getByRole("textbox", { name: "IP address", exact: true })
  await input.click()
  await expect(input).toBeFocused()
  await expect(drawer).toBeVisible()
  await drawer.getByRole("heading", { name: address.canonical_ip }).focus()
  await page.keyboard.press("Escape")
  await expect(drawer).toHaveCount(0)
  await expect(trigger).toBeFocused()
  for (const width of [1440, 1024, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    await trigger.click()
    await expect(drawer).toBeVisible()
    await expect(
      drawer.getByText("Synthetic operations team", { exact: true }),
    ).toBeVisible()
    await expect
      .poll(async () => {
        const box = await drawer.boundingBox()
        return !!box && box.x >= 0 && box.x + box.width <= width + 1
      })
      .toBe(true)
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth > window.innerWidth,
      ),
    ).toBe(false)
    await page.screenshot({
      animations: "disabled",
      path: info.outputPath(`evidence-${width}.png`),
      fullPage: false,
    })
    await drawer
      .getByRole("button", { name: "Close evidence", exact: true })
      .click()
    await expect(drawer).toHaveCount(0)
    await expect(trigger).toBeFocused()
  }
  await page.goto(
    `/projects/${project}/netflow-correlation?result=${result}&binding=none&core_address=${address.address_key}`,
  )
  await expect(drawer).toBeVisible()
  await page.keyboard.press("Escape")
  await expect(drawer).toHaveCount(0)
  await expect(table).toBeFocused()
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.evaluate(() => {
    localStorage.setItem("vite-ui-theme", "light")
    localStorage.setItem("exposure:language", "zh-CN")
  })
  await page.reload()
  await expect(
    page.getByRole("button", { name: "查看依据", exact: true }),
  ).toBeVisible()
  await page.screenshot({
    animations: "disabled",
    path: info.outputPath("comparison-light-zh.png"),
    fullPage: true,
  })
  await page.getByRole("button", { name: "查看依据", exact: true }).click()
  await expect(
    drawer.getByRole("button", { name: "关闭依据", exact: true }),
  ).toBeVisible()
  await page.screenshot({ path: info.outputPath("evidence-light-zh.png") })
  expect(writes).toEqual([])
})

test("compact filters retain fixed identity, empty-state recovery and server sorting", async ({
  page,
}) => {
  const writes = await serve(page)
  const reads: URLSearchParams[] = []
  await page.route(`**${root}/addresses?*`, (route) => {
    const query = new URL(route.request().url()).searchParams
    reads.push(query)
    if (query.get("ip") !== "192.0.2.99") return route.fallback()
    return route.fulfill({
      json: {
        ...envelope,
        result_id: result,
        count: 0,
        total_addresses: 3,
        skip: 0,
        limit: 25,
        data: [],
      },
    })
  })
  await page.goto(
    `/projects/${project}/netflow-correlation?result=${result}&binding=none`,
  )
  const core = page.getByRole("region", { name: "Core classification" })
  await core
    .getByRole("textbox", { name: "IP address", exact: true })
    .fill("192.0.2.99")
  await core.getByRole("button", { name: "Filter", exact: true }).click()
  await expect(
    core.getByText("No records match this filter in the fixed result.", {
      exact: true,
    }),
  ).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`result=${result}`))
  await core.getByRole("button", { name: "Clear filters", exact: true }).click()
  await expect(
    core.getByRole("button", { name: "View evidence" }),
  ).toBeVisible()
  await core
    .getByRole("combobox", { name: "Sort", exact: true })
    .selectOption("ip_desc")
  await expect
    .poll(() => reads.some((query) => query.get("sort") === "ip_desc"))
    .toBe(true)
  await expect(
    core.getByRole("button", { name: /All addresses 3/ }),
  ).toHaveAttribute("aria-pressed", "true")
  expect(writes).toEqual([])
})

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

async function hasVisibleFocus(target: ReturnType<typeof materialsSummary>) {
  return target.evaluate((element) => {
    const style = getComputedStyle(element)
    return (
      style.outlineStyle !== "none" && Number.parseFloat(style.outlineWidth) > 0
    )
  })
}

test("reading entries move focus locally without changing search or issuing writes", async ({
  page,
}) => {
  const writes = await serve(page)
  const methods: string[] = []
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/v1/"))
      methods.push(request.method())
  })
  await page.goto(
    `/projects/${project}/netflow-correlation?result=${result}&binding=none&core_class=cloud_only&core_page=1&core_ip=192.0.2.20&core_sort=ip_desc`,
  )
  const nav = readingNav(page)
  await expect(nav).toBeVisible()
  await expect(nav.getByText("Reading areas", { exact: true })).toBeVisible()
  await expect(
    page.getByRole("region", {
      name: "AI interpretation and reports",
      exact: true,
    }),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: /All addresses 3/ }),
  ).toBeVisible()
  const before = page.url()
  const records = recordsGroup(page)
  const heading = reportHeading(page)
  const materials = materialsSummary(page)
  const details = page.locator("details").filter({ has: materials })

  await nav
    .getByRole("button", { name: "Records and evidence", exact: true })
    .click()
  await expect(records).toBeFocused()
  expect(page.url()).toBe(before)

  await nav
    .getByRole("button", {
      name: "AI interpretation and reports",
      exact: true,
    })
    .click()
  await expect(heading).toBeFocused()
  expect(page.url()).toBe(before)

  await nav
    .getByRole("button", { name: "Materials used here", exact: true })
    .click()
  await expect(materials).toBeFocused()
  expect(await hasVisibleFocus(materials)).toBe(true)
  await expect(details).toHaveJSProperty("open", true)
  expect(page.url()).toBe(before)

  await nav
    .getByRole("button", { name: "Materials used here", exact: true })
    .click()
  await expect(details).toHaveJSProperty("open", true)
  await expect(materials).toBeFocused()
  expect(await hasVisibleFocus(materials)).toBe(true)

  await page
    .getByRole("button", { name: "Back to reading areas", exact: true })
    .click()
  await expect(nav).toBeFocused()
  expect(page.url()).toBe(before)

  await nav.focus()
  await page.keyboard.press("Tab")
  await expect(
    nav.getByRole("button", { name: "Records and evidence", exact: true }),
  ).toBeFocused()
  await page.keyboard.press("Enter")
  await expect(records).toBeFocused()
  await page.keyboard.press("Tab")
  await expect(
    page.getByRole("button", { name: /All addresses 3/ }),
  ).toBeFocused()

  await nav.focus()
  await page.keyboard.press("Tab")
  await page.keyboard.press("Tab")
  await expect(
    nav.getByRole("button", {
      name: "AI interpretation and reports",
      exact: true,
    }),
  ).toBeFocused()
  await page.keyboard.press("Space")
  await expect(heading).toBeFocused()
  await page.keyboard.press("Tab")
  await expect(
    page.getByRole("button", { name: "Back to reading areas", exact: true }),
  ).toBeFocused()

  expect(page.url()).toBe(before)
  expect(writes).toEqual([])
  expect(methods.length).toBeGreaterThan(0)
  expect(methods.every((method) => method === "GET")).toBe(true)
})

test("reading destinations clear sticky chrome without page overflow at desktop and narrow widths", async ({
  page,
}, info) => {
  await serve(page)
  for (const [width, height] of [
    [1440, 900],
    [390, 844],
    [375, 812],
  ] as const) {
    await page.setViewportSize({ width, height })
    await page.goto(
      `/projects/${project}/netflow-correlation?result=${result}&binding=none`,
    )
    const nav = readingNav(page)
    await expect(nav).toBeVisible()
    const targets = [
      ["Records and evidence", recordsGroup(page)],
      ["AI interpretation and reports", reportHeading(page)],
      ["Materials used here", materialsSummary(page)],
    ] as const
    for (const [entry, target] of targets) {
      await nav.getByRole("button", { name: entry, exact: true }).click()
      await expect(target).toBeFocused()
      expect(await hasVisibleFocus(target)).toBe(true)
      await expect
        .poll(async () => {
          const header = await page
            .locator("header.sticky")
            .first()
            .boundingBox()
          const box = await target.boundingBox()
          return !!header && !!box && box.y >= header.y + header.height - 1
        })
        .toBe(true)
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth > window.innerWidth,
        ),
      ).toBe(false)
    }
    const table = await page.evaluate(() => {
      const element = document.querySelector(
        ".comparison-core [data-slot='table-container']",
      )
      if (!(element instanceof HTMLElement)) return null
      return {
        client: element.clientWidth,
        scroll: element.scrollWidth,
        overflowX: getComputedStyle(element).overflowX,
      }
    })
    expect(table).not.toBeNull()
    expect(table?.overflowX).toBe("auto")
    if (width < 600) expect(table!.scroll).toBeGreaterThan(table!.client)
    await page.screenshot({
      animations: "disabled",
      path: info.outputPath(`reading-entries-${width}.png`),
      fullPage: false,
    })
  }
})

test("open materials and an open evidence drawer survive the reading shortcut cycle", async ({
  page,
}) => {
  const writes = await serve(page)
  const key = `addr:${"c".repeat(64)}`
  const address = {
    address_key: key,
    canonical_ip: "192.0.2.20",
    classification: "both",
    customer_records: 1,
    cloud_records: 1,
    presence: { CUSTOMER: "PRESENT", CLOUD: "PRESENT" },
  }
  await page.route(
    (url) => url.pathname === `${root}/addresses/${key}`,
    (route) =>
      route.fulfill({ json: { ...envelope, result_id: result, address } }),
  )
  await page.route(
    (url) => url.pathname === `${root}/addresses/${key}/evidence`,
    (route) => {
      const query = new URL(route.request().url()).searchParams
      return route.fulfill({
        json: {
          ...envelope,
          result_id: result,
          address_key: key,
          source: query.get("source") === "cloud" ? "cloud" : "customer",
          count: 0,
          skip: Number(query.get("skip") ?? 0),
          limit: 25,
          data: [],
        },
      })
    },
  )
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(
    `/projects/${project}/netflow-correlation?result=${result}&binding=none`,
  )
  const nav = readingNav(page)
  const materials = materialsSummary(page)
  const details = page.locator("details").filter({ has: materials })
  await materials.click()
  await expect(details).toHaveJSProperty("open", true)
  const trigger = page
    .getByRole("table", { name: "Comparison addresses" })
    .getByRole("button", { name: "View evidence" })
  await trigger.click()
  const drawer = page.getByRole("dialog", { name: address.canonical_ip })
  await expect(drawer).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Back to reading areas", exact: true }),
  ).toBeVisible()
  for (const [entry, target] of [
    ["Records and evidence", recordsGroup(page)],
    ["AI interpretation and reports", reportHeading(page)],
    ["Materials used here", materials],
  ] as const) {
    await nav.getByRole("button", { name: entry, exact: true }).click()
    await expect(target).toBeFocused()
    await expect(drawer).toBeVisible()
    await expect(details).toHaveJSProperty("open", true)
  }
  await drawer
    .getByRole("button", { name: "Close evidence", exact: true })
    .click()
  await expect(drawer).toHaveCount(0)
  await expect(page).not.toHaveURL(/core_address=/)
  await expect(details).toHaveJSProperty("open", true)
  expect(writes).toEqual([])
})

test("an explicit core refusal removes the reading entries instead of retaining content", async ({
  page,
}) => {
  const writes = await serve(page)
  let refused = false
  await page.route(
    (url) => url.pathname === `${root}/summary`,
    (route) => {
      if (!refused) return route.fallback()
      return route.fulfill({
        status: 410,
        json: { detail: { code: "comparison_material_expired" } },
      })
    },
  )
  await page.goto(
    `/projects/${project}/netflow-correlation?result=${result}&binding=none`,
  )
  await expect(readingNav(page)).toBeVisible()
  refused = true
  await page.getByRole("button", { name: "Refresh page", exact: true }).click()
  await expect(
    page.getByRole("heading", { name: "This fixed result cannot be read" }),
  ).toBeVisible()
  await expect(
    page.getByText(/Identity, access or data integrity could not be verified/),
  ).toBeVisible()
  await expect(readingNav(page)).toHaveCount(0)
  await expect(reportHeading(page)).toHaveCount(0)
  expect(page.url()).toContain(`result=${result}`)
  expect(writes).toEqual([])
})

test("deep links, material round trip and history restore fixed filters and pages", async ({
  page,
}) => {
  const writes = await serve(page)
  const upload = summary.selection.customer.upload_id
  await page.route(
    (url) => url.pathname === `/api/v1/projects/${project}/customer-ledger`,
    (route) =>
      route.fulfill({
        json: {
          project_id: project,
          upload_id: upload,
          revision_id: null,
          current_upload_id: upload,
          current_revision_id: null,
          current_profile_id: "profile-synthetic",
          upload_sha256: "e".repeat(64),
          filename: "synthetic.xlsx",
          source_created_at: "2026-10-01T00:00:00Z",
          revision: null,
          data: [],
          count: 0,
          total_records: 0,
          unique_ips: 0,
          can_edit: false,
        },
      }),
  )
  await page.route(
    (url) =>
      url.pathname === `/api/v1/projects/${project}/customer-ledger/revisions`,
    (route) => route.fulfill({ json: [] }),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/projects/${project}/customer-uploads`,
    (route) => route.fulfill({ json: { data: [], count: 0 } }),
  )
  await page.route(
    (url) =>
      url.pathname === `/api/v1/projects/${project}/comparison-results/history`,
    (route) =>
      route.fulfill({
        json: {
          ...envelope,
          count: 1,
          skip: 0,
          limit: 25,
          data: [
            {
              id: "10000000-0000-4000-8000-000000000302",
              published_at: "2026-09-01T00:00:00Z",
              customer_filename: "earlier.xlsx",
              source_name: "Synthetic CloudAtlas",
              purpose: "regular",
            },
          ],
        },
      }),
  )
  const deepLink = `/projects/${project}/netflow-correlation?result=${result}&binding=none&core_class=cloud_only&core_page=1&core_ip=192.0.2.20&core_sort=ip_desc`
  await page.goto(deepLink)
  const core = page.getByRole("region", { name: "Core classification" })
  await expect(
    core.getByRole("textbox", { name: "IP address", exact: true }),
  ).toHaveValue("192.0.2.20")
  await expect(
    core.getByRole("combobox", { name: "Sort", exact: true }),
  ).toHaveValue("ip_desc")
  await expect(
    core.getByRole("button", { name: /CloudAtlas record, not registered/ }),
  ).toHaveAttribute("aria-pressed", "true")

  await materialsSummary(page).click()
  await page.getByRole("link", { name: "Read current customer data" }).click()
  await expect(page).toHaveURL(/customer-ledger/)
  const back = page.getByRole("link", {
    name: "Return to comparison results",
  })
  await expect(back).toBeVisible()
  await back.click()
  await expect(page).toHaveURL(/netflow-correlation/)
  const returned = new URL(page.url())
  expect(returned.searchParams.get("result")).toBe(result)
  expect(returned.searchParams.get("binding")).toBe("none")
  expect(returned.searchParams.get("core_class")).toBe("cloud_only")
  expect(returned.searchParams.get("core_page")).toBe("1")
  expect(returned.searchParams.get("core_ip")).toBe("192.0.2.20")
  expect(returned.searchParams.get("core_sort")).toBe("ip_desc")
  await expect(
    core.getByText("Fixed total 3 · Matching 1 · This page 1"),
  ).toBeVisible()
  await expect(
    core.getByRole("textbox", { name: "IP address", exact: true }),
  ).toHaveValue("192.0.2.20")
  await expect(
    page.locator("details").filter({ has: materialsSummary(page) }),
  ).toHaveJSProperty("open", false)

  await page
    .getByRole("button", { name: "Historical results", exact: true })
    .click()
  await expect(
    page
      .getByRole("region", { name: "Historical results" })
      .getByText("earlier.xlsx", { exact: false }),
  ).toBeVisible()
  const historyUrl = new URL(page.url())
  expect(historyUrl.searchParams.get("core_history")).toBe("true")
  expect(historyUrl.searchParams.get("core_ip")).toBe("192.0.2.20")
  expect(historyUrl.searchParams.get("core_page")).toBe("1")
  expect(writes).toEqual([])
})

const evidenceKey = `addr:${"e".repeat(64)}`
const sharedIp = "203.0.113.10"
const profile = "60000000-0000-4000-8000-000000000301"
const otherResult = "10000000-0000-4000-8000-000000000302"
const upload = summary.selection.customer.upload_id
const pinnedSummary = {
  ...summary,
  pins: {
    CUSTOMER: {
      upload_id: upload,
      revision_id: null,
      profile_id: profile,
      profile_version: 7,
    },
    CLOUD: {
      kind: "external_versions",
      source_instance_id: source,
      space_id: "space-synthetic",
      domains: {
        ip: {
          id: ipVersion,
          source_id: source,
          instance_id: "cloud-instance",
          domain: "ip",
          space_id: "space-synthetic",
          status: "PUBLISHED",
          record_count: 14,
          complete: true,
          expected_total: 14,
          pages_read: 1,
          stop_reason: "source_complete",
          filter: { status: "valid" },
          sort: "id",
          fingerprint: "f".repeat(64),
          fetched_at: "2026-10-01T09:02:03Z",
          published_at: "2026-10-01T10:00:00Z",
          retain_until: "2027-01-01T00:00:00Z",
        },
        port: {
          id: portVersion,
          source_id: source,
          instance_id: "cloud-instance",
          domain: "port",
          space_id: "space-synthetic",
          status: "PUBLISHED",
          record_count: 13,
          complete: true,
          expected_total: 13,
          pages_read: 1,
          stop_reason: "source_complete",
          filter: {},
          sort: "id",
          fingerprint: "f".repeat(64),
          fetched_at: "2026-10-02T12:05:06Z",
          published_at: "2026-10-02T13:00:00Z",
          retain_until: "2027-01-01T00:00:00Z",
        },
      },
    },
  },
}
const longUrl = `https://portal.example.test/${"segment/".repeat(50)}end`
const customerEvidence = Array.from({ length: 30 }, (_, index) => ({
  source: "CUSTOMER",
  record_key: `customer-${index}`,
  version_id: upload,
  domain: "customer",
  canonical_ip: sharedIp,
  original: {
    fields: {
      asset_ip: sharedIp,
      start_port: index === 0 ? 0 : 443,
      end_port: index === 0 ? 0 : 443,
      web_url: index === 0 ? longUrl : undefined,
      service_type: "HTTPS",
      asset_owner: index === 1 ? undefined : `Synthetic owner ${index}`,
      serial: index === 1 ? "" : `SYN-${index}`,
    },
  },
  availability: {},
}))
const cloudEvidence = [
  ...Array.from({ length: 14 }, (_, index) => ({
    source: "CLOUD",
    record_key: `ip-${index}`,
    version_id: ipVersion,
    domain: "ip",
    canonical_ip: sharedIp,
    original: {
      ip: sharedIp,
      version: 4,
      status: "valid",
      provider: index === 0 ? null : "Synthetic provider",
      live_port: index === 0 ? 0 : 2,
    },
    availability: {},
  })),
  ...Array.from({ length: 13 }, (_, index) => ({
    source: "CLOUD",
    record_key: `port-${index}`,
    version_id: portVersion,
    domain: "port",
    canonical_ip: sharedIp,
    original: {
      ip: sharedIp,
      port: 8440 + index,
      protocol: "tcp",
      service: "HTTPS",
      banner:
        index === 0 ? "<script>alert(1)</script>synthetic banner" : undefined,
      city: index === 0 ? undefined : "Synthetic city",
      product_version: "1.25.3",
    },
    availability: {},
  })),
]

async function serveEvidencePage(
  page: Page,
  options: {
    summary?: object
    addressCounts?: { customer: number; cloud: number }
    addressTotal?: number
  } = {},
) {
  const reads: URLSearchParams[] = []
  await serve(page)
  const fixedSummary = options.summary ?? pinnedSummary
  const counts = options.addressCounts ?? { customer: 30, cloud: 27 }
  const address = {
    address_key: evidenceKey,
    canonical_ip: sharedIp,
    classification: "both",
    customer_records: counts.customer,
    cloud_records: counts.cloud,
    presence: { CUSTOMER: "PRESENT", CLOUD: "PRESENT" },
  }
  await page.route(`**${root}/summary`, (route) =>
    route.fulfill({ json: fixedSummary }),
  )
  await page.route(`**${root}/updates`, (route) =>
    route.fulfill({
      json: { ...envelope, result_id: result, state: "UNCHANGED" },
    }),
  )
  await page.route(
    (url) => url.pathname === `${root}/addresses`,
    (route) =>
      route.fulfill({
        json: {
          ...envelope,
          result_id: result,
          total_addresses: options.addressTotal ?? 1,
          count: options.addressTotal ?? 1,
          skip: 0,
          limit: 25,
          data: [address],
        },
      }),
  )
  await page.route(
    (url) =>
      decodeURIComponent(url.pathname) === `${root}/addresses/${evidenceKey}`,
    (route) =>
      route.fulfill({ json: { ...envelope, result_id: result, address } }),
  )
  await page.route(
    (url) =>
      decodeURIComponent(url.pathname) ===
      `${root}/addresses/${evidenceKey}/evidence`,
    (route) => {
      const query = new URL(route.request().url()).searchParams
      const evidenceSource =
        query.get("source") === "cloud" ? "cloud" : "customer"
      const skip = Number(query.get("skip") ?? 0)
      const records =
        evidenceSource === "customer" ? customerEvidence : cloudEvidence
      reads.push(query)
      return route.fulfill({
        json: {
          ...envelope,
          result_id: result,
          address_key: evidenceKey,
          source: evidenceSource,
          data: records.slice(skip, skip + 25),
          count: records.length,
          skip,
          limit: 25,
        },
      })
    },
  )
  return reads
}

const evidenceDrawer = (page: Page) =>
  page.getByRole("region", { name: "Fixed address evidence" })
const customerCollection = (page: Page) =>
  evidenceDrawer(page).getByRole("region", {
    name: "Customer declarations",
  })
const cloudCollection = (page: Page) =>
  evidenceDrawer(page).getByRole("region", {
    name: "CloudAtlas observations",
  })
const sourcePageNav = (page: Page, sourceName: "customer" | "cloud") =>
  evidenceDrawer(page).getByRole("navigation", {
    name:
      sourceName === "customer"
        ? "Customer evidence records pagination"
        : "CloudAtlas evidence records pagination",
  })

test("customer and cloud evidence keep independent pages, later PORT records and source jumps", async ({
  page,
}) => {
  const reads = await serveEvidencePage(page)
  const writes: string[] = []
  page.on("request", (request) => {
    if (request.url().includes("/api/") && request.method() !== "GET")
      writes.push(request.method())
  })
  await page.goto(
    `/projects/${project}/netflow-correlation?result=${result}&binding=none&core_address=${evidenceKey}`,
  )
  const customer = customerCollection(page)
  const cloud = cloudCollection(page)
  await expect(customer).toBeVisible()
  await expect(cloud).toBeVisible()
  await expect(
    customer.getByText("30 fixed records in this source", { exact: true }),
  ).toBeVisible()
  await expect(
    cloud.getByText("27 fixed records in this source", { exact: true }),
  ).toBeVisible()
  await expect(sourcePageNav(page, "customer")).toContainText("Page 1 of 2")
  await expect(sourcePageNav(page, "cloud")).toContainText("Page 1 of 2")
  expect(
    reads.some(
      (query) =>
        query.get("source") === "customer" && query.get("skip") === "0",
    ),
  ).toBe(true)
  expect(
    reads.some(
      (query) => query.get("source") === "cloud" && query.get("skip") === "0",
    ),
  ).toBe(true)
  expect(reads.some((query) => query.get("skip") === "25")).toBe(false)

  await sourcePageNav(page, "customer")
    .getByRole("button", { name: "Next", exact: true })
    .click()
  await expect(page).toHaveURL(/core_customer_page=1/)
  await expect(page).toHaveURL(/core_cloud_page=0/)
  await expect(sourcePageNav(page, "customer")).toContainText("Page 2 of 2")
  await expect(sourcePageNav(page, "cloud")).toContainText("Page 1 of 2")
  await expect(
    customer.getByRole("heading", {
      name: "Customer declaration",
      exact: true,
    }),
  ).toHaveCount(5)
  await expect(cloud.getByText("8450", { exact: true })).toBeVisible()

  await sourcePageNav(page, "cloud")
    .getByRole("button", { name: "Next", exact: true })
    .click()
  await expect(page).toHaveURL(/core_cloud_page=1/)
  await expect(sourcePageNav(page, "cloud")).toContainText("Page 2 of 2")
  await expect(sourcePageNav(page, "customer")).toContainText("Page 2 of 2")
  await expect(
    customer.getByRole("heading", {
      name: "Customer declaration",
      exact: true,
    }),
  ).toHaveCount(5)
  await expect(
    cloud.getByRole("heading", { name: "CloudAtlas observation", exact: true }),
  ).toHaveCount(2)
  await expect(cloud.getByText("8452", { exact: true })).toBeVisible()
  expect(
    reads.filter(
      (query) =>
        query.get("source") === "customer" && query.get("skip") === "25",
    ).length,
  ).toBeGreaterThan(0)
  expect(
    reads.filter(
      (query) => query.get("source") === "cloud" && query.get("skip") === "25",
    ).length,
  ).toBeGreaterThan(0)
  expect(reads.some((query) => Number(query.get("skip")) > 25)).toBe(false)

  const jumped = page.url()
  await evidenceDrawer(page)
    .getByRole("button", { name: "Customer evidence", exact: true })
    .click()
  await expect(
    customer.getByRole("heading", {
      name: "Customer declarations",
      exact: true,
    }),
  ).toBeFocused()
  expect(page.url()).toBe(jumped)
  await evidenceDrawer(page)
    .getByRole("button", { name: "CloudAtlas evidence", exact: true })
    .click()
  await expect(
    cloud.getByRole("heading", {
      name: "CloudAtlas observations",
      exact: true,
    }),
  ).toBeFocused()
  expect(page.url()).toBe(jumped)
  expect(writes).toEqual([])
})

test("legacy evidence pages materialize once, explicit zero wins and overflow is bounded", async ({
  page,
}) => {
  const reads = await serveEvidencePage(page)
  const target = `/projects/${project}/netflow-correlation?result=${result}&binding=none&core_address=${evidenceKey}`
  await page.goto(`${target}&core_evidence=cloud&core_evidence_page=1`)
  await expect(sourcePageNav(page, "customer")).toContainText("Page 1 of 2")
  await expect(sourcePageNav(page, "cloud")).toContainText("Page 2 of 2")
  expect(
    reads.some(
      (query) =>
        query.get("source") === "customer" && query.get("skip") === "0",
    ),
  ).toBe(true)
  expect(
    reads.some(
      (query) => query.get("source") === "cloud" && query.get("skip") === "25",
    ),
  ).toBe(true)
  const initial = new URL(page.url()).searchParams
  expect(initial.get("core_customer_page")).toBeNull()
  expect(initial.get("core_cloud_page")).toBeNull()

  await sourcePageNav(page, "cloud")
    .getByRole("button", { name: "Previous", exact: true })
    .click()
  await expect(page).toHaveURL(/core_customer_page=0/)
  await expect(page).toHaveURL(/core_cloud_page=0/)
  await expect(page).toHaveURL(/core_evidence_page=0/)
  await expect(sourcePageNav(page, "cloud")).toContainText("Page 1 of 2")

  await page.goto(
    `${target}&core_evidence=cloud&core_evidence_page=1&core_customer_page=0`,
  )
  await expect(sourcePageNav(page, "customer")).toContainText("Page 1 of 2")
  await expect(sourcePageNav(page, "cloud")).toContainText("Page 2 of 2")

  reads.length = 0
  const overflowing = Math.floor(Number.MAX_SAFE_INTEGER / 25) + 1
  await page.goto(`${target}&core_cloud_page=${overflowing}`)
  await expect(
    page.getByText("Invalid query parameters. Clear the filters", {
      exact: false,
    }),
  ).toBeVisible()
  expect(reads.every((query) => query.get("skip") === "0")).toBe(true)
  expect(reads.some((query) => Number(query.get("skip")) < 0)).toBe(false)
})

test("back and forward retain both source pages and closing resets them", async ({
  page,
}) => {
  await serveEvidencePage(page)
  await page.goto(
    `/projects/${project}/netflow-correlation?result=${result}&binding=none&core_address=${evidenceKey}`,
  )
  const next = (sourceName: "customer" | "cloud") =>
    sourcePageNav(page, sourceName)
      .getByRole("button", { name: "Next", exact: true })
      .click()
  await next("customer")
  await next("cloud")
  await expect(sourcePageNav(page, "customer")).toContainText("Page 2 of 2")
  await expect(sourcePageNav(page, "cloud")).toContainText("Page 2 of 2")

  await page.goBack()
  await expect(page).toHaveURL(/core_customer_page=1/)
  await expect(page).toHaveURL(/core_cloud_page=0/)
  await expect(sourcePageNav(page, "customer")).toContainText("Page 2 of 2")
  await expect(sourcePageNav(page, "cloud")).toContainText("Page 1 of 2")
  await page.goBack()
  const initial = new URL(page.url()).searchParams
  expect(initial.get("core_customer_page") ?? "0").toBe("0")
  expect(initial.get("core_cloud_page") ?? "0").toBe("0")
  await expect(sourcePageNav(page, "customer")).toContainText("Page 1 of 2")
  await expect(sourcePageNav(page, "cloud")).toContainText("Page 1 of 2")

  await page.goForward()
  await page.goForward()
  await expect(sourcePageNav(page, "customer")).toContainText("Page 2 of 2")
  await expect(sourcePageNav(page, "cloud")).toContainText("Page 2 of 2")

  await evidenceDrawer(page)
    .getByRole("button", { name: "Close evidence", exact: true })
    .click()
  await expect(evidenceDrawer(page)).toHaveCount(0)
  const closed = new URL(page.url()).searchParams
  expect(closed.get("core_address")).toBeNull()
  expect(closed.get("core_customer_page")).toBe("0")
  expect(closed.get("core_cloud_page")).toBe("0")
  expect(closed.get("core_evidence_page")).toBe("0")
})

test("classification, core page, filter, sort and result changes reset both source pages", async ({
  page,
}) => {
  await serveEvidencePage(page, { addressTotal: 26 })
  const base = `/projects/${project}/netflow-correlation?result=${result}&binding=none&core_address=${evidenceKey}`
  const openDrawer = async () => {
    await page
      .getByRole("table", { name: "Comparison addresses" })
      .getByRole("button", { name: "View evidence" })
      .click()
    await expect(evidenceDrawer(page)).toBeVisible()
  }
  const setBothPages = async () => {
    await sourcePageNav(page, "customer")
      .getByRole("button", { name: "Next", exact: true })
      .click()
    await sourcePageNav(page, "cloud")
      .getByRole("button", { name: "Next", exact: true })
      .click()
    await expect(sourcePageNav(page, "customer")).toContainText("Page 2 of 2")
    await expect(sourcePageNav(page, "cloud")).toContainText("Page 2 of 2")
  }
  const expectReset = async (pattern: RegExp) => {
    await expect(page).toHaveURL(pattern)
    const query = new URL(page.url()).searchParams
    expect(query.get("core_address")).toBeNull()
    expect(query.get("core_customer_page")).toBe("0")
    expect(query.get("core_cloud_page")).toBe("0")
    expect(query.get("core_evidence_page")).toBe("0")
    await expect(evidenceDrawer(page)).toHaveCount(0)
  }

  await page.goto(base)
  await expect(evidenceDrawer(page)).toBeVisible()
  await setBothPages()
  await page.getByRole("button", { name: /^Recorded on both sides/ }).click()
  await expectReset(/core_class=both/)

  await openDrawer()
  await setBothPages()
  const addressNext = page
    .getByRole("navigation", { name: "Comparison addresses pagination" })
    .getByRole("button", { name: "Next", exact: true })
  await addressNext.focus()
  await page.keyboard.press("Enter")
  await expectReset(/core_page=1/)

  await openDrawer()
  await setBothPages()
  await page
    .getByRole("textbox", { name: "IP address", exact: true })
    .fill(sharedIp)
  await page.getByRole("button", { name: "Filter", exact: true }).click()
  await expectReset(new RegExp(`core_ip=${sharedIp.replaceAll(".", "\\.")}`))

  await openDrawer()
  await setBothPages()
  await page
    .getByRole("combobox", { name: "Sort", exact: true })
    .selectOption("ip_desc")
  await expectReset(/core_sort=ip_desc/)

  await page.route(`**${root}/updates`, (route) =>
    route.fulfill({
      json: {
        ...envelope,
        result_id: result,
        state: "UPDATED",
        latest_result_id: otherResult,
      },
    }),
  )
  await page.route(`**/comparison-results/${otherResult}/summary`, (route) =>
    route.fulfill({ json: { ...pinnedSummary, id: otherResult } }),
  )
  await page.route(
    (url) =>
      url.pathname ===
      `/api/v1/projects/${project}/comparison-results/${otherResult}/addresses`,
    (route) =>
      route.fulfill({
        json: {
          ...envelope,
          result_id: otherResult,
          total_addresses: 0,
          count: 0,
          skip: 0,
          limit: 25,
          data: [],
        },
      }),
  )
  await openDrawer()
  await setBothPages()
  const newer = page.getByRole("button", { name: "Read the newer result" })
  await newer.focus()
  await page.keyboard.press("Enter")
  await expect(page).toHaveURL(new RegExp(`result=${otherResult}`))
  const changed = new URL(page.url()).searchParams
  expect(changed.get("core_address")).toBeNull()
  expect(changed.get("core_customer_page")).toBe("0")
  expect(changed.get("core_cloud_page")).toBe("0")
  expect(changed.get("core_evidence_page")).toBe("0")
})

test("fixed material return preserves both source pages and the legacy return field stays compatible", async ({
  page,
}) => {
  const parsed = comparisonReturnFields({
    back_result: result,
    back_customer_page: "1",
    back_cloud_page: "2",
    back_evidence_page: "1",
  })
  expect(parsed.back_customer_page).toBe(1)
  expect(parsed.back_cloud_page).toBe(2)
  expect(parsed.back_evidence_page).toBe(1)
  const legacy = comparisonReturnFields({
    back_result: result,
    back_evidence_page: "1",
  })
  expect(legacy.back_customer_page).toBeUndefined()
  expect(legacy.back_cloud_page).toBeUndefined()
  const absent = comparisonReturnFields({ back_result: result })
  expect(absent.back_customer_page).toBeUndefined()
  expect(absent.back_cloud_page).toBeUndefined()
  const zero = comparisonReturnFields({
    back_result: result,
    back_customer_page: "0",
    back_cloud_page: 0,
  })
  expect(zero.back_customer_page).toBe(0)
  expect(zero.back_cloud_page).toBe(0)
  const maxPage = Math.floor(Number.MAX_SAFE_INTEGER / 25)
  const bounded = comparisonReturnFields({
    back_result: result,
    back_customer_page: String(maxPage),
    back_cloud_page: maxPage,
  })
  expect(bounded.back_customer_page).toBe(maxPage)
  expect(bounded.back_cloud_page).toBe(maxPage)
  const overflow = comparisonReturnFields({
    back_result: result,
    back_customer_page: String(maxPage + 1),
    back_cloud_page: Number.MAX_SAFE_INTEGER,
  })
  expect(overflow.back_customer_page).toBeUndefined()
  expect(overflow.back_cloud_page).toBeUndefined()
  expect(
    comparisonReturnFields({
      back_result: result,
      back_customer_page: "1e2",
    }).back_customer_page,
  ).toBe(100)
  expect(
    comparisonReturnFields({
      back_result: result,
      back_customer_page: "1.5",
    }).back_customer_page,
  ).toBeUndefined()
  expect(
    comparisonReturnFields({
      back_result: result,
      back_customer_page: "-1",
    }).back_customer_page,
  ).toBeUndefined()

  await serveEvidencePage(page)
  await page.route(
    (url) => url.pathname === `/api/v1/projects/${project}/customer-ledger`,
    (route) =>
      route.fulfill({
        json: {
          project_id: project,
          upload_id: upload,
          revision_id: null,
          current_upload_id: upload,
          current_revision_id: null,
          current_profile_id: profile,
          upload_sha256: "e".repeat(64),
          filename: "synthetic.xlsx",
          source_created_at: "2026-10-01T00:00:00Z",
          revision: null,
          data: [],
          count: 0,
          total_records: 0,
          unique_ips: 0,
          can_edit: false,
        },
      }),
  )
  await page.route(
    (url) =>
      url.pathname === `/api/v1/projects/${project}/customer-ledger/revisions`,
    (route) => route.fulfill({ json: [] }),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/projects/${project}/customer-uploads`,
    (route) => route.fulfill({ json: { data: [], count: 0 } }),
  )
  await page.goto(
    `/projects/${project}/netflow-correlation?result=${result}&binding=none&core_address=${evidenceKey}&core_customer_page=1&core_cloud_page=1`,
  )
  await expect(sourcePageNav(page, "customer")).toContainText("Page 2 of 2")
  await expect(sourcePageNav(page, "cloud")).toContainText("Page 2 of 2")
  // The non-modal evidence sheet covers the page; keyboard activation keeps
  // the fixed address and both source pages in the URL.
  const materials = page.getByText("View the materials used here", {
    exact: true,
  })
  await materials.focus()
  await expect(materials).toBeFocused()
  await page.keyboard.press("Enter")
  const material = page
    .getByRole("link", {
      name: "Read the customer version used here",
      exact: true,
    })
    .first()
  const href = await material.getAttribute("href")
  const materialQuery = new URL(href!, "http://synthetic.test").searchParams
  expect(materialQuery.get("back_customer_page")).toBe("1")
  expect(materialQuery.get("back_cloud_page")).toBe("1")
  await expect(material).toBeVisible()
  await material.focus()
  await expect(material).toBeFocused()
  await page.keyboard.press("Enter")
  await expect(page).toHaveURL(/customer-ledger/)
  await page
    .getByRole("link", { name: "Return to comparison results", exact: true })
    .click()
  await expect(page).toHaveURL(new RegExp(`result=${result}`))
  const returned = new URL(page.url()).searchParams
  expect(returned.get("core_address")).toBe(evidenceKey)
  expect(returned.get("core_customer_page")).toBe("1")
  expect(returned.get("core_cloud_page")).toBe("1")
  expect(returned.get("core_evidence_page")).toBe("0")
  await expect(sourcePageNav(page, "customer")).toContainText("Page 2 of 2")
  await expect(sourcePageNav(page, "cloud")).toContainText("Page 2 of 2")

  await page.goto(
    `/projects/${project}/customer-ledger?back_result=${result}&back_address=${evidenceKey}&back_customer_page=1`,
  )
  await page
    .getByRole("link", { name: "Return to comparison results", exact: true })
    .click()
  await expect(page).toHaveURL(new RegExp(`result=${result}`))
  const onePage = new URL(page.url()).searchParams
  expect(onePage.get("core_customer_page")).toBe("1")
  expect(onePage.get("core_cloud_page")).toBeNull()
  await expect(sourcePageNav(page, "customer")).toContainText("Page 2 of 2")
  await expect(sourcePageNav(page, "cloud")).toContainText("Page 1 of 2")
  await sourcePageNav(page, "cloud")
    .getByRole("button", { name: "Next", exact: true })
    .click()
  await expect(page).toHaveURL(/core_customer_page=1/)
  await expect(page).toHaveURL(/core_cloud_page=1/)
  await expect(sourcePageNav(page, "customer")).toContainText("Page 2 of 2")
  await expect(sourcePageNav(page, "cloud")).toContainText("Page 2 of 2")
})

const evidenceRoute = (url: URL) =>
  decodeURIComponent(url.pathname) ===
  `${root}/addresses/${evidenceKey}/evidence`

const evidenceBase = `/projects/${project}/netflow-correlation?result=${result}&binding=none&core_address=${evidenceKey}`

test("a required-source evidence refusal denies the whole fixed result before peer content", async ({
  page,
}) => {
  await serveEvidencePage(page)
  await page.route(evidenceRoute, (route) => {
    const sourceName = new URL(route.request().url()).searchParams.get("source")
    if (sourceName !== "customer") return route.fallback()
    return route.fulfill({
      status: 410,
      json: { detail: { code: "synthetic_source_expired" } },
    })
  })
  await page.goto(evidenceBase)
  await expect(
    page.getByText("This fixed result cannot be read", { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByText("Identity, access or data integrity could not be verified", {
      exact: false,
    }),
  ).toBeVisible()
  await expect(
    page.getByText("CloudAtlas observations", { exact: true }),
  ).toHaveCount(0)
  await expect(
    page.getByText("Synthetic provider", { exact: true }),
  ).toHaveCount(0)
})

test("comparison_address_not_found is a local evidence read error, not a whole-result denial", async ({
  page,
}) => {
  await serveEvidencePage(page)
  await page.route(evidenceRoute, (route) => {
    const sourceName = new URL(route.request().url()).searchParams.get("source")
    if (sourceName !== "customer") return route.fallback()
    return route.fulfill({
      status: 404,
      json: { detail: { code: "comparison_address_not_found" } },
    })
  })
  await page.goto(evidenceBase)
  await expect(evidenceDrawer(page)).toBeVisible()
  await expect(
    customerCollection(page).getByText(
      "The fixed customer evidence could not be read. No current version was substituted or shown as empty.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(
    cloudCollection(page)
      .getByText("Synthetic provider", { exact: true })
      .first(),
  ).toBeVisible()
  await expect(
    page.getByText("This fixed result cannot be read", { exact: true }),
  ).toHaveCount(0)
})

test("temporary and refusal failures across both sources aggregate in either order", async ({
  page,
}) => {
  await serveEvidencePage(page)
  const faults: { customer?: number; cloud?: number } = {}
  await page.route(evidenceRoute, (route) => {
    const sourceName = new URL(route.request().url()).searchParams.get("source")
    const status = faults[sourceName as "customer" | "cloud"]
    if (!status) return route.fallback()
    return route.fulfill({
      status,
      json: { detail: { code: `synthetic_${status}` } },
    })
  })
  const denied = async () => {
    await expect(
      page.getByText("This fixed result cannot be read", { exact: true }),
    ).toBeVisible()
    await expect(
      page.getByText("CloudAtlas observations", { exact: true }),
    ).toHaveCount(0)
    await expect(
      page.getByText("The fixed customer evidence could not be read", {
        exact: false,
      }),
    ).toHaveCount(0)
  }

  faults.customer = 503
  faults.cloud = 410
  await page.goto(evidenceBase)
  await denied()

  faults.customer = 410
  faults.cloud = 503
  await page.goto(evidenceBase)
  await denied()

  faults.customer = 401
  faults.cloud = 403
  await page.goto(evidenceBase)
  await denied()

  faults.customer = 503
  delete faults.cloud
  await page.goto(evidenceBase)
  await expect(evidenceDrawer(page)).toBeVisible()
  await expect(
    customerCollection(page).getByText(
      "The fixed customer evidence could not be read",
      { exact: false },
    ),
  ).toBeVisible()
  await expect(
    cloudCollection(page)
      .getByText("Synthetic provider", { exact: true })
      .first(),
  ).toBeVisible()
  await expect(
    page.getByText("This fixed result cannot be read", { exact: true }),
  ).toHaveCount(0)
})

test("evidence paging, record domain and fixed version contradictions are read errors, not empty", async ({
  page,
}) => {
  await serveEvidencePage(page)
  const mode: { value: "skip" | "version" | "domain" } = { value: "skip" }
  await page.route(evidenceRoute, (route) => {
    const query = new URL(route.request().url()).searchParams
    if (query.get("source") !== "cloud") return route.fallback()
    const skip = Number(query.get("skip") ?? 0)
    const record =
      mode.value === "version"
        ? { ...cloudEvidence[0], version_id: "bad-version-id" }
        : mode.value === "domain"
          ? { ...cloudEvidence[0], domain: "port" }
          : cloudEvidence[0]
    return route.fulfill({
      json: {
        ...envelope,
        result_id: result,
        address_key: evidenceKey,
        source: "cloud",
        data: [record],
        count: 1,
        skip: mode.value === "skip" ? skip + 1 : skip,
        limit: 25,
      },
    })
  })
  const check = async () => {
    await expect(
      cloudCollection(page).getByText(
        "The fixed CloudAtlas evidence could not be read. No current version was substituted or shown as empty.",
        { exact: true },
      ),
    ).toBeVisible()
    await expect(
      customerCollection(page).getByText("Synthetic owner 0", { exact: true }),
    ).toBeVisible()
    await expect(
      page.getByText("This fixed result cannot be read", { exact: true }),
    ).toHaveCount(0)
  }

  await page.goto(evidenceBase)
  await check()
  mode.value = "version"
  await page.goto(evidenceBase)
  await check()
  mode.value = "domain"
  await page.goto(evidenceBase)
  await check()
})

test("a one-domain fixed cloud selection renders its selected records without false errors", async ({
  page,
}) => {
  await serveEvidencePage(page)
  const fixed = { value: structuredClone(pinnedSummary) }
  const cloudRows: { value: object[] } = { value: [] }
  await page.route(`**${root}/summary`, (route) =>
    route.fulfill({ json: fixed.value }),
  )
  await page.route(evidenceRoute, (route) => {
    const sourceName =
      new URL(route.request().url()).searchParams.get("source") === "cloud"
        ? "cloud"
        : "customer"
    const data =
      sourceName === "customer" ? [customerEvidence[0]] : cloudRows.value
    return route.fulfill({
      json: {
        ...envelope,
        result_id: result,
        address_key: evidenceKey,
        source: sourceName,
        data,
        count: data.length,
        skip: 0,
        limit: 25,
      },
    })
  })

  const ipOnly = structuredClone(pinnedSummary)
  ipOnly.selection.cloud.port_version_id = null
  delete ipOnly.pins.CLOUD.domains.port
  fixed.value = ipOnly
  cloudRows.value = [cloudEvidence[0]]
  await page.goto(evidenceBase)
  const cloud = cloudCollection(page)
  await expect(cloud.getByRole("alert")).toHaveCount(0)
  await expect(cloud.locator(".comparison-source-record")).toHaveCount(1)
  await expect(
    cloud.getByText("1 fixed records in this source", { exact: true }),
  ).toBeVisible()
  await expect(
    cloud
      .getByRole("region", { name: "CloudAtlas PORT version" })
      .locator("dt", { hasText: "Fixed version ID" })
      .locator("..")
      .locator("dd"),
  ).toHaveText("Not provided")

  const portOnly = structuredClone(pinnedSummary)
  portOnly.selection.cloud.ip_version_id = null
  delete portOnly.pins.CLOUD.domains.ip
  fixed.value = portOnly
  cloudRows.value = [cloudEvidence[14]]
  await page.goto(evidenceBase)
  await expect(cloud.getByRole("alert")).toHaveCount(0)
  await expect(cloud.locator(".comparison-source-record")).toHaveCount(1)
  await expect(
    cloud
      .getByRole("region", { name: "CloudAtlas IP version" })
      .locator("dt", { hasText: "Fixed version ID" })
      .locator("..")
      .locator("dd"),
  ).toHaveText("Not provided")
  await expect(
    page.getByText("This fixed result cannot be read", { exact: true }),
  ).toHaveCount(0)
})

test("unselected cloud domains and unversioned customers are read errors, not fixed records", async ({
  page,
}) => {
  await serveEvidencePage(page)
  const fixed = { value: structuredClone(pinnedSummary) }
  const rows: { customer: object[]; cloud: object[] } = {
    customer: [customerEvidence[0]],
    cloud: [cloudEvidence[0]],
  }
  await page.route(`**${root}/summary`, (route) =>
    route.fulfill({ json: fixed.value }),
  )
  await page.route(evidenceRoute, (route) => {
    const sourceName =
      new URL(route.request().url()).searchParams.get("source") === "cloud"
        ? "cloud"
        : "customer"
    const data = rows[sourceName]
    return route.fulfill({
      json: {
        ...envelope,
        result_id: result,
        address_key: evidenceKey,
        source: sourceName,
        data,
        count: data.length,
        skip: 0,
        limit: 25,
      },
    })
  })
  const cloud = cloudCollection(page)
  const customer = customerCollection(page)
  const expectCloudError = async () => {
    await expect(cloud.getByRole("alert")).toContainText(
      "The fixed CloudAtlas evidence could not be read",
    )
    await expect(cloud.locator(".comparison-source-record")).toHaveCount(0)
  }
  const expectCustomerError = async () => {
    await expect(customer.getByRole("alert")).toContainText(
      "The fixed customer evidence could not be read",
    )
    await expect(customer.locator(".comparison-source-record")).toHaveCount(0)
  }

  const ipOnly = structuredClone(pinnedSummary)
  ipOnly.selection.cloud.port_version_id = null
  delete ipOnly.pins.CLOUD.domains.port
  fixed.value = ipOnly
  rows.cloud = [cloudEvidence[14]]
  await page.goto(evidenceBase)
  await expectCloudError()
  await expect(
    customer.getByText("Synthetic owner 0", { exact: true }),
  ).toBeVisible()

  const portOnly = structuredClone(pinnedSummary)
  portOnly.selection.cloud.ip_version_id = null
  delete portOnly.pins.CLOUD.domains.ip
  fixed.value = portOnly
  rows.cloud = [cloudEvidence[0]]
  await page.goto(evidenceBase)
  await expectCloudError()
  await expect(
    customer.getByText("Synthetic owner 0", { exact: true }),
  ).toBeVisible()

  const noCustomerVersion = structuredClone(pinnedSummary)
  noCustomerVersion.pins.CUSTOMER = {}
  noCustomerVersion.selection.customer = {}
  fixed.value = noCustomerVersion
  rows.cloud = [cloudEvidence[0]]
  await page.goto(evidenceBase)
  await expectCustomerError()
  await expect(cloud.locator(".comparison-source-record")).toHaveCount(1)

  const conflicting = structuredClone(pinnedSummary)
  conflicting.selection.cloud.ip_version_id =
    "30000000-0000-4000-8000-000000000399"
  fixed.value = conflicting
  rows.customer = [customerEvidence[0]]
  rows.cloud = [cloudEvidence[0]]
  await page.goto(evidenceBase)
  await expectCloudError()

  const conflictingCustomer = structuredClone(pinnedSummary)
  conflictingCustomer.pins.CUSTOMER.revision_id =
    "50000000-0000-4000-8000-000000000399"
  fixed.value = conflictingCustomer
  rows.customer = [
    {
      ...customerEvidence[0],
      version_id: "50000000-0000-4000-8000-000000000399",
    },
  ]
  rows.cloud = [cloudEvidence[0]]
  await page.goto(evidenceBase)
  await expectCustomerError()
  await expect(cloud.locator(".comparison-source-record")).toHaveCount(1)
})

test("an unselected cloud domain cannot be restored by a retained pin", async ({
  page,
}) => {
  await serveEvidencePage(page)
  const fixed = { value: structuredClone(pinnedSummary) }
  const cloudRows: { value: object[] } = { value: [] }
  await page.route(`**${root}/summary`, (route) =>
    route.fulfill({ json: fixed.value }),
  )
  await page.route(evidenceRoute, (route) => {
    const sourceName =
      new URL(route.request().url()).searchParams.get("source") === "cloud"
        ? "cloud"
        : "customer"
    const data =
      sourceName === "customer" ? [customerEvidence[0]] : cloudRows.value
    return route.fulfill({
      json: {
        ...envelope,
        result_id: result,
        address_key: evidenceKey,
        source: sourceName,
        data,
        count: data.length,
        skip: 0,
        limit: 25,
      },
    })
  })
  const cloud = cloudCollection(page)
  const expectCloudError = async () => {
    await expect(cloud.getByRole("alert")).toContainText(
      "The fixed CloudAtlas evidence could not be read",
    )
    await expect(cloud.locator(".comparison-source-record")).toHaveCount(0)
    await expect(
      customerCollection(page).getByText("Synthetic owner 0", { exact: true }),
    ).toBeVisible()
  }

  const ipUnselected = structuredClone(pinnedSummary)
  ipUnselected.selection.cloud.ip_version_id = null
  fixed.value = ipUnselected
  cloudRows.value = [cloudEvidence[0]]
  await page.goto(evidenceBase)
  await expectCloudError()

  const portUnselected = structuredClone(pinnedSummary)
  portUnselected.selection.cloud.port_version_id = null
  fixed.value = portUnselected
  cloudRows.value = [cloudEvidence[14]]
  await page.goto(evidenceBase)
  await expectCloudError()
})

test("a selected cloud domain without a descriptive pin stays readable", async ({
  page,
}) => {
  await serveEvidencePage(page)
  const fixed = { value: structuredClone(pinnedSummary) }
  const cloudRows: { value: object[] } = { value: [] }
  await page.route(`**${root}/summary`, (route) =>
    route.fulfill({ json: fixed.value }),
  )
  await page.route(evidenceRoute, (route) => {
    const sourceName =
      new URL(route.request().url()).searchParams.get("source") === "cloud"
        ? "cloud"
        : "customer"
    const data =
      sourceName === "customer" ? [customerEvidence[0]] : cloudRows.value
    return route.fulfill({
      json: {
        ...envelope,
        result_id: result,
        address_key: evidenceKey,
        source: sourceName,
        data,
        count: data.length,
        skip: 0,
        limit: 25,
      },
    })
  })
  const cloud = cloudCollection(page)

  const ipSelected = structuredClone(pinnedSummary)
  delete ipSelected.pins.CLOUD.domains.ip
  fixed.value = ipSelected
  cloudRows.value = [cloudEvidence[0]]
  await page.goto(evidenceBase)
  await expect(cloud.getByRole("alert")).toHaveCount(0)
  await expect(cloud.locator(".comparison-source-record")).toHaveCount(1)
  await expect(
    cloud
      .getByRole("region", { name: "CloudAtlas IP version" })
      .locator("dt", { hasText: "Fixed version ID" })
      .locator("..")
      .locator("dd"),
  ).toContainText(ipVersion)

  const portSelected = structuredClone(pinnedSummary)
  delete portSelected.pins.CLOUD.domains.port
  fixed.value = portSelected
  cloudRows.value = [cloudEvidence[14]]
  await page.goto(evidenceBase)
  await expect(cloud.getByRole("alert")).toHaveCount(0)
  await expect(cloud.locator(".comparison-source-record")).toHaveCount(1)
  await expect(
    cloud
      .getByRole("region", { name: "CloudAtlas PORT version" })
      .locator("dt", { hasText: "Fixed version ID" })
      .locator("..")
      .locator("dd"),
  ).toContainText(portVersion)
})

test("invalid source pages show an explicit drawer recovery without reading evidence", async ({
  page,
}) => {
  const reads = await serveEvidencePage(page)
  const overflow = Math.floor(Number.MAX_SAFE_INTEGER / 25) + 1
  for (const query of [
    "core_customer_page=1.5",
    `core_cloud_page=${overflow}`,
  ]) {
    await page.goto(`${evidenceBase}&${query}`)
    const drawer = evidenceDrawer(page)
    await expect(drawer).toBeVisible()
    await expect(drawer.getByRole("alert")).toContainText(
      "The page or filter parameters are invalid or out of range",
    )
    await expect(drawer.getByText(/Reading/)).toHaveCount(0)
    await page.waitForTimeout(250)
    expect(reads).toHaveLength(0)
    const recovery = drawer.getByRole("button", {
      name: "Clear filters and continue",
      exact: true,
    })
    await recovery.focus()
    await expect(recovery).toBeFocused()
    await page.keyboard.press("Enter")
    await expect(drawer).toHaveCount(0)
    const reset = new URL(page.url()).searchParams
    expect(reset.get("core_address")).toBeNull()
    expect(reset.get("core_customer_page")).toBe("0")
    expect(reset.get("core_cloud_page")).toBe("0")
    expect(reset.get("core_filter_invalid")).not.toBe("true")
  }
  await page
    .getByRole("table", { name: "Comparison addresses" })
    .getByRole("button", { name: "View evidence" })
    .click()
  await expect(evidenceDrawer(page)).toBeVisible()
  await expect.poll(() => reads.length).toBeGreaterThan(0)
  await expect(
    customerCollection(page).getByText("Synthetic owner 0", { exact: true }),
  ).toBeVisible()
})

test("a late old evidence page response cannot replace the selected source page", async ({
  page,
}) => {
  await serveEvidencePage(page)
  let startPageTwo = () => {}
  const pageTwoStarted = new Promise<void>((resolve) => {
    startPageTwo = resolve
  })
  let releasePageTwo = () => {}
  const pageTwoGate = new Promise<void>((resolve) => {
    releasePageTwo = resolve
  })
  await page.route(evidenceRoute, async (route) => {
    const query = new URL(route.request().url()).searchParams
    if (query.get("source") === "customer" && query.get("skip") === "25") {
      startPageTwo()
      await pageTwoGate
    }
    return route.fallback()
  })
  await page.goto(evidenceBase)
  const customer = customerCollection(page)
  await expect(
    customer.getByText("Synthetic owner 0", { exact: true }),
  ).toBeVisible()
  await sourcePageNav(page, "customer")
    .getByRole("button", { name: "Next", exact: true })
    .click()
  await pageTwoStarted
  await page.goBack()
  await expect(sourcePageNav(page, "customer")).toContainText("Page 1 of 2")
  releasePageTwo()
  await page.waitForTimeout(300)
  await expect(
    customer.getByText("Synthetic owner 0", { exact: true }),
  ).toBeVisible()
  await expect(
    customer.getByText("Synthetic owner 25", { exact: true }),
  ).toHaveCount(0)
})

test("expiry while the drawer is open clears fixed contents and closes the drawer", async ({
  page,
}) => {
  // The controlled clock keeps the deadline open through the dev-server load;
  // expiry is advanced only after the drawer is visible.
  const now = Date.now()
  const deadline = new Date(now + 60_000).toISOString()
  const expires = structuredClone(pinnedSummary)
  expires.pins.CLOUD.domains.ip.retain_until = deadline
  expires.pins.CLOUD.domains.port.retain_until = deadline
  await serveEvidencePage(page, { summary: expires })
  await page.clock.install({ time: now })
  await page.goto(evidenceBase)
  await expect(evidenceDrawer(page)).toBeVisible()
  await page.clock.fastForward(61_000)
  await expect(
    page.getByText(
      "The selected data has expired. Restricted contents have been cleared.",
      { exact: true },
    ),
  ).toBeVisible({ timeout: 6000 })
  await expect(evidenceDrawer(page)).toHaveCount(0)
  await expect(
    page.getByText("Customer declarations", { exact: true }),
  ).toHaveCount(0)
})

test("fixed provenance, distinct versions and times, explicit zero and hostile raw text stay literal", async ({
  page,
}) => {
  const customIpVersion = "30000000-0000-4000-8000-000000000311"
  const customPortVersion = "40000000-0000-4000-8000-000000000312"
  const longIp = "2001:db8:1234:5678:9abc:def0:1234:5678"
  const hostile = "<img src=x onerror=alert(1)><script>alert('raw')</script>"
  const custom = structuredClone(pinnedSummary)
  custom.customer_filename =
    "customer-declaration-with-a-long-filename-for-wrapping.xlsx"
  custom.selection.cloud.ip_version_id = customIpVersion
  custom.selection.cloud.port_version_id = customPortVersion
  custom.pins.CLOUD.domains.ip.id = customIpVersion
  custom.pins.CLOUD.domains.port.id = customPortVersion
  custom.pins.CLOUD.domains.ip.fetched_at = "2026-10-03T01:02:03Z"
  custom.pins.CLOUD.domains.port.fetched_at = "2026-10-04T04:05:06Z"
  custom.pins.CLOUD.domains.ip.filter = {}
  custom.pins.CLOUD.domains.port.filter = {
    source: "synthetic",
    nested: { mode: "fixed" },
  }
  delete custom.pins.CLOUD.domains.ip.record_count
  await serveEvidencePage(page, { summary: custom })
  await page.route(`**${root}/updates`, (route) =>
    route.fulfill({
      json: {
        ...envelope,
        result_id: result,
        state: "UPDATED",
        latest_result_id: otherResult,
      },
    }),
  )
  await page.route(evidenceRoute, (route) => {
    const sourceName = new URL(route.request().url()).searchParams.get("source")
    const records =
      sourceName === "customer"
        ? [
            {
              source: "CUSTOMER",
              record_key: "customer-raw",
              version_id: upload,
              domain: "customer",
              canonical_ip: longIp,
              original: {
                fields: {
                  asset_ip: longIp,
                  start_port: 0,
                  end_port: 0,
                  asset_owner: undefined,
                  web_url: `https://portal.example.test/${"x".repeat(300)}`,
                },
              },
              availability: { banner: "raw" },
            },
          ]
        : [
            {
              source: "CLOUD",
              record_key: "ip-raw",
              version_id: customIpVersion,
              domain: "ip",
              canonical_ip: longIp,
              original: {
                ip: longIp,
                version: 6,
                status: "valid",
                live_port: 0,
              },
              availability: {},
            },
            {
              source: "CLOUD",
              record_key: "port-raw",
              version_id: customPortVersion,
              domain: "port",
              canonical_ip: longIp,
              original: {
                ip: longIp,
                port: 0,
                protocol: "",
                banner: hostile,
              },
              availability: {},
            },
          ]
    return route.fulfill({
      json: {
        ...envelope,
        result_id: result,
        address_key: evidenceKey,
        source: sourceName,
        data: records,
        count: records.length,
        skip: 0,
        limit: 25,
      },
    })
  })
  await page.goto(evidenceBase)
  const drawer = evidenceDrawer(page)
  const customer = customerCollection(page)
  const cloud = cloudCollection(page)
  await expect(drawer).toBeVisible()
  await expect(
    page.getByText("The current materials have updates", { exact: false }),
  ).toBeVisible()
  await expect(
    page.getByText(
      "customer-declaration-with-a-long-filename-for-wrapping.xlsx",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(
    customer.getByText(customIpVersion, { exact: true }),
  ).toHaveCount(0)
  await expect(
    customer.getByText("Not provided", { exact: true }).first(),
  ).toBeVisible()
  const startPort = customer
    .locator("dt", { hasText: "Start port" })
    .locator("xpath=following-sibling::dd[1]")
  const endPort = customer
    .locator("dt", { hasText: "End port" })
    .locator("xpath=following-sibling::dd[1]")
  await expect(startPort).toHaveText("0")
  await expect(endPort).toHaveText("0")
  const ipBlock = cloud.getByRole("region", {
    name: "CloudAtlas IP version",
  })
  const portBlock = cloud.getByRole("region", {
    name: "CloudAtlas PORT version",
  })
  await expect(
    ipBlock.getByText(customIpVersion, { exact: true }).first(),
  ).toBeVisible()
  await expect(
    portBlock.getByText(customPortVersion, { exact: true }).first(),
  ).toBeVisible()
  await expect(
    ipBlock.getByText(customPortVersion, { exact: true }),
  ).toHaveCount(0)
  await expect(
    ipBlock.getByText("Not provided", { exact: true }).first(),
  ).toBeVisible()
  await expect(ipBlock.getByText("{}", { exact: true })).toBeVisible()
  await expect(
    portBlock.getByText('"source": "synthetic"', { exact: false }),
  ).toBeVisible()
  await expect(
    customer.getByText(
      "Port role: the declared start and end ports are a customer range.",
      { exact: false },
    ),
  ).toBeVisible()
  await expect(
    cloud.getByText(
      "Port role: live_port is a CloudAtlas source-reported count in the IP domain",
      { exact: false },
    ),
  ).toBeVisible()
  await expect(
    cloud.getByText(
      "Port role: port and protocol are CloudAtlas PORT-domain observations",
      { exact: false },
    ),
  ).toBeVisible()
  await expect(
    drawer.getByText(
      "NetFlow source-side ports are read only through the existing fixed Analysis",
      { exact: false },
    ),
  ).toBeVisible()
  await expect(
    ipBlock.getByText("An empty object only means no filter was attached", {
      exact: false,
    }),
  ).toBeVisible()
  const ipCollected = await ipBlock
    .locator("dt", { hasText: "Collected at" })
    .locator("xpath=following-sibling::dd[1]")
    .textContent()
  const portCollected = await portBlock
    .locator("dt", { hasText: "Collected at" })
    .locator("xpath=following-sibling::dd[1]")
    .textContent()
  expect(ipCollected).not.toBe(portCollected)
  await expect(cloud.getByText(hostile, { exact: true })).toBeVisible()
  await expect(drawer.locator("script, img")).toHaveCount(0)
  await expect(cloud.getByText(longIp, { exact: false }).first()).toBeVisible()
  const overflow = await drawer.evaluate((element) => ({
    scrollWidth: element.scrollWidth,
    clientWidth: element.clientWidth,
    documentWidth: document.documentElement.scrollWidth,
    windowWidth: window.innerWidth,
  }))
  expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 1)
  expect(overflow.documentWidth).toBeLessThanOrEqual(overflow.windowWidth)
})

test("both columns and stacked narrow layouts keep reading controls reachable without overflow", async ({
  page,
}, testInfo) => {
  await serveEvidencePage(page)
  await page.goto(evidenceBase)
  const drawer = evidenceDrawer(page)
  await expect(drawer).toBeVisible()
  for (const width of [1440, 1280, 390, 375]) {
    await page.setViewportSize({ width, height: 900 })
    await page.waitForTimeout(150)
    const customer = customerCollection(page)
    const cloud = cloudCollection(page)
    await expect(customer).toBeVisible()
    await expect(cloud).toBeVisible()
    const customerBox = await customer.boundingBox()
    const cloudBox = await cloud.boundingBox()
    expect(customerBox).not.toBeNull()
    expect(cloudBox).not.toBeNull()
    if (width >= 1280) {
      expect(cloudBox!.x).toBeGreaterThan(customerBox!.x)
      expect(Math.abs(cloudBox!.y - customerBox!.y)).toBeLessThan(40)
      expect(customerBox!.width).toBeGreaterThanOrEqual(220)
      expect(cloudBox!.width).toBeGreaterThanOrEqual(220)
      expect(Math.abs(customerBox!.width - cloudBox!.width)).toBeLessThan(2)
    } else {
      expect(cloudBox!.y).toBeGreaterThan(customerBox!.y + 40)
    }
    const overflow = await drawer.evaluate((element) => ({
      scrollWidth: element.scrollWidth,
      clientWidth: element.clientWidth,
      documentWidth: document.documentElement.scrollWidth,
      windowWidth: window.innerWidth,
    }))
    expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 1)
    expect(overflow.documentWidth).toBeLessThanOrEqual(overflow.windowWidth)
    await expect(
      drawer.getByRole("button", { name: "Close evidence", exact: true }),
    ).toBeVisible()
    await expect(sourcePageNav(page, "customer")).toBeVisible()
    await expect(sourcePageNav(page, "cloud")).toBeVisible()
    const cloudHeading = cloud.getByRole("heading", {
      name: "CloudAtlas observations",
      exact: true,
    })
    await drawer
      .getByRole("button", { name: "CloudAtlas evidence", exact: true })
      .click()
    await expect(cloudHeading).toBeFocused()
    await page.screenshot({
      path: testInfo.outputPath(`evidence-sources-${width}.png`),
      fullPage: false,
    })
  }
})

test("count zero is an empty source and a later empty page recovers only that source", async ({
  page,
}) => {
  await serveEvidencePage(page)
  const mode: { value: "empty" | "later-empty" } = { value: "empty" }
  await page.route(evidenceRoute, (route) => {
    const query = new URL(route.request().url()).searchParams
    const sourceName = query.get("source") === "cloud" ? "cloud" : "customer"
    const skip = Number(query.get("skip") ?? 0)
    if (mode.value === "empty")
      return route.fulfill({
        json: {
          ...envelope,
          result_id: result,
          address_key: evidenceKey,
          source: sourceName,
          data: [],
          count: 0,
          skip,
          limit: 25,
        },
      })
    const records = sourceName === "customer" ? customerEvidence : cloudEvidence
    return route.fulfill({
      json: {
        ...envelope,
        result_id: result,
        address_key: evidenceKey,
        source: sourceName,
        data: skip === 25 ? [] : records.slice(skip, skip + 25),
        count: records.length,
        skip,
        limit: 25,
      },
    })
  })
  await page.goto(evidenceBase)
  const customer = customerCollection(page)
  const cloud = cloudCollection(page)
  await expect(
    customer.getByText(
      "The fixed customer source has no record for this address in this result.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(
    cloud.getByText(
      "The fixed CloudAtlas source has no record for this address in this result.",
      { exact: true },
    ),
  ).toBeVisible()

  mode.value = "later-empty"
  await page.goto(evidenceBase)
  await expect(
    customer.getByText("Synthetic owner 0", { exact: true }),
  ).toBeVisible()
  await sourcePageNav(page, "customer")
    .getByRole("button", { name: "Next", exact: true })
    .click()
  await expect(
    customer.getByText(
      "This page has no records, but the fixed source total is 30.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(
    cloud.getByText("Synthetic provider", { exact: true }).first(),
  ).toBeVisible()
  await customer
    .getByRole("button", { name: "Read this source from page 1", exact: true })
    .click()
  await expect(page).toHaveURL(/core_customer_page=0/)
  await expect(
    customer.getByText("Synthetic owner 0", { exact: true }),
  ).toBeVisible()
  await expect(sourcePageNav(page, "customer")).toContainText("Page 1 of 2")
})

test("a late old evidence address response cannot replace the newly opened address", async ({
  page,
}) => {
  await serveEvidencePage(page)
  const secondKey = `addr:${"d".repeat(64)}`
  const secondIp = "203.0.113.11"
  let startFirst = () => {}
  const firstStarted = new Promise<void>((resolve) => {
    startFirst = resolve
  })
  let releaseFirst = () => {}
  const firstGate = new Promise<void>((resolve) => {
    releaseFirst = resolve
  })
  await page.route(
    (url) => url.pathname === `${root}/addresses`,
    (route) =>
      route.fulfill({
        json: {
          ...envelope,
          result_id: result,
          total_addresses: 2,
          count: 2,
          skip: 0,
          limit: 25,
          data: [
            {
              address_key: evidenceKey,
              canonical_ip: sharedIp,
              classification: "both",
              customer_records: 1,
              cloud_records: 0,
              presence: { CUSTOMER: "PRESENT", CLOUD: "ABSENT" },
            },
            {
              address_key: secondKey,
              canonical_ip: secondIp,
              classification: "customer_only",
              customer_records: 1,
              cloud_records: 0,
              presence: { CUSTOMER: "PRESENT", CLOUD: "ABSENT" },
            },
          ],
        },
      }),
  )
  await page.route(
    (url) =>
      decodeURIComponent(url.pathname) === `${root}/addresses/${secondKey}`,
    (route) =>
      route.fulfill({
        json: {
          ...envelope,
          result_id: result,
          address: {
            address_key: secondKey,
            canonical_ip: secondIp,
            classification: "customer_only",
            customer_records: 1,
            cloud_records: 0,
            presence: { CUSTOMER: "PRESENT", CLOUD: "ABSENT" },
          },
        },
      }),
  )
  await page.route(
    (url) =>
      decodeURIComponent(url.pathname).startsWith(`${root}/addresses/`) &&
      url.pathname.endsWith("/evidence"),
    async (route) => {
      const url = new URL(route.request().url())
      const query = url.searchParams
      const address = decodeURIComponent(url.pathname).slice(
        `${root}/addresses/`.length,
        -"/evidence".length,
      )
      const sourceName = query.get("source") === "cloud" ? "cloud" : "customer"
      const skip = Number(query.get("skip") ?? 0)
      if (address === secondKey || sourceName === "cloud")
        return route.fulfill({
          json: {
            ...envelope,
            result_id: result,
            address_key: address,
            source: sourceName,
            data:
              address === secondKey && sourceName === "customer"
                ? [
                    {
                      source: "CUSTOMER",
                      record_key: "second-address",
                      version_id: upload,
                      domain: "customer",
                      canonical_ip: secondIp,
                      original: {
                        fields: {
                          asset_ip: secondIp,
                          asset_owner: "Second address owner",
                        },
                      },
                      availability: {},
                    },
                  ]
                : [],
            count: address === secondKey && sourceName === "customer" ? 1 : 0,
            skip,
            limit: 25,
          },
        })
      startFirst()
      await firstGate
      return route.fulfill({
        json: {
          ...envelope,
          result_id: result,
          address_key: address,
          source: sourceName,
          data: [
            {
              source: "CUSTOMER",
              record_key: "first-address",
              version_id: upload,
              domain: "customer",
              canonical_ip: sharedIp,
              original: {
                fields: {
                  asset_ip: sharedIp,
                  asset_owner: "First address owner",
                },
              },
              availability: {},
            },
          ],
          count: 1,
          skip,
          limit: 25,
        },
      })
    },
  )
  await page.goto(evidenceBase)
  await firstStarted
  const table = page.getByRole("table", { name: "Comparison addresses" })
  const secondRow = table
    .getByRole("button", { name: "View evidence", exact: true })
    .nth(1)
  await secondRow.focus()
  await page.keyboard.press("Enter")
  await expect
    .poll(() => new URL(page.url()).searchParams.get("core_address"))
    .toBe(secondKey)
  const customer = customerCollection(page)
  await expect(
    customer.getByText("Second address owner", { exact: true }),
  ).toBeVisible()
  expect(new URL(page.url()).searchParams.get("core_customer_page")).toBe("0")
  expect(new URL(page.url()).searchParams.get("core_cloud_page")).toBe("0")
  releaseFirst()
  await page.waitForTimeout(300)
  await expect(
    customer.getByText("Second address owner", { exact: true }),
  ).toBeVisible()
  await expect(
    customer.getByText("First address owner", { exact: true }),
  ).toHaveCount(0)
})
