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
    (route) =>
      route.fulfill({
        json: {
          ...envelope,
          result_id: result,
          address_key: address.address_key,
          source: "customer",
          count: 1,
          skip: 0,
          limit: 25,
          data: [
            {
              source: "CUSTOMER",
              domain: "asset",
              version_id: ipVersion,
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
      }),
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
    (route) =>
      route.fulfill({
        json: {
          ...envelope,
          result_id: result,
          address_key: key,
          source: "customer",
          count: 0,
          skip: 0,
          limit: 25,
          data: [],
        },
      }),
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
