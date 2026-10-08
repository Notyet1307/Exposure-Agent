import { readFileSync } from "node:fs"
import { mkdir } from "node:fs/promises"
import path from "node:path"
import { expect, test } from "./fixtures"

test.skip(
  !process.env.V2_READING_FIXTURE || !process.env.V2_READING_EVIDENCE,
  "Requires explicit isolated V2 reading fixture and evidence paths",
)

const fixture = () =>
  JSON.parse(readFileSync(process.env.V2_READING_FIXTURE!, "utf8"))

for (const fault of [500, 403, "timeout"] as const) {
  test(`real core stays readable through injected first supplement ${fault} and GET retry`, async ({
    page,
  }) => {
    const data = fixture()
    let fail = true
    const writes: string[] = []
    page.on("request", (request) => {
      if (
        request.url().includes("/api/") &&
        !["GET", "OPTIONS"].includes(request.method())
      )
        writes.push(request.method())
    })
    await page.route(
      (url) =>
        url.pathname ===
        `/api/v1/projects/${data.project_id}/comparison-results/${data.result_id}/supplements`,
      async (route) => {
        if (!fail) return route.continue()
        if (fault === "timeout") await route.abort("timedout")
        else
          await route.fulfill({
            status: fault,
            json: { detail: { code: "synthetic_injected_failure" } },
          })
      },
    )
    await page.goto(
      `/projects/${data.project_id}/netflow-correlation?result=${data.result_id}`,
    )
    const core = page.getByRole("region", { name: "Core classification" })
    await expect(
      core.getByRole("button", { name: /All addresses 3/ }),
    ).toBeVisible()
    const supplement = page.getByRole("region", {
      name: "Optional NetFlow evidence",
    })
    await expect(supplement.getByRole("alert")).toContainText(
      fault === 403 ? "denied" : "could not be read",
    )
    fail = false
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

test("real two-domain materials return to the same filtered address; desktop and mobile reading", async ({
  page,
  request,
}) => {
  const data = fixture()
  const api = process.env.TEST_API_URL!
  const login = await request.post(`${api}/api/v1/login/access-token`, {
    form: {
      username: process.env.FIRST_SUPERUSER!,
      password: process.env.FIRST_SUPERUSER_PASSWORD!,
    },
  })
  expect(login.ok()).toBeTruthy()
  const token = (await login.json()).access_token
  const addresses = await request.get(
    `${api}/api/v1/projects/${data.project_id}/comparison-results/${data.result_id}/addresses?ip=${data.address_ip}`,
    { headers: { Authorization: `Bearer ${token}` } },
  )
  expect(addresses.ok()).toBeTruthy()
  const key = (await addresses.json()).data[0].address_key
  const writes: string[] = []
  page.on("request", (r) => {
    if (r.url().includes("/api/") && !["GET", "OPTIONS"].includes(r.method()))
      writes.push(r.method())
  })
  await page.goto(
    `/projects/${data.project_id}/netflow-correlation?result=${data.result_id}&binding=none&core_class=both&core_ip=${data.address_ip}&core_sort=ip_desc&core_address=${key}`,
  )
  const detail = page.getByRole("region", { name: "Fixed address evidence" })
  await expect(
    detail.getByRole("heading", { name: data.address_ip, exact: true }),
  ).toBeFocused()
  await detail
    .getByRole("button", { name: "Close evidence", exact: true })
    .focus()
  await page.keyboard.press("Enter")
  await expect(detail).toHaveCount(0)
  await page.getByRole("button", { name: "View evidence", exact: true }).focus()
  await page.keyboard.press("Enter")
  await expect(
    detail.getByRole("heading", { name: data.address_ip, exact: true }),
  ).toBeFocused()
  for (const [domain, version, label] of [
    ["ip", data.ip_version_id, "Read the CloudAtlas IP version used here"],
    ["port", data.port_v1, "Read the CloudAtlas port version used here"],
  ]) {
    const evidence = page.getByRole("region", {
      name: "Fixed address evidence",
    })
    await expect(
      evidence.getByRole("heading", {
        name: "Customer declaration",
        exact: true,
      }),
    ).toBeVisible()
    await evidence.getByRole("link", { name: label, exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`external_version=${version}`))
    await expect(page).toHaveURL(new RegExp(`external_domain=${domain}`))
    if (domain === "port") {
      await expect(
        page.getByRole("cell", { name: "443", exact: true }),
      ).toBeVisible()
      await expect(
        page.getByText("synthetic-port-v2", { exact: true }),
      ).toHaveCount(0)
    }
    await page
      .getByRole("link", { name: "Return to comparison results", exact: true })
      .click()
    await expect(page).toHaveURL(new RegExp(`result=${data.result_id}`))
    const query = new URL(page.url()).searchParams
    expect(query.get("binding")).toBe("none")
    expect(query.get("core_class")).toBe("both")
    expect(query.get("core_page")).toBe("0")
    expect(query.get("core_ip")).toBe(data.address_ip)
    expect(query.get("core_sort")).toBe("ip_desc")
    expect(query.get("core_address")).toBe(key)
  }
  await mkdir(process.env.V2_READING_EVIDENCE!, { recursive: true })
  for (const [width, language, theme] of [
    [1366, "en", "light"],
    [1920, "en", "dark"],
    [390, "zh-CN", "dark"],
  ] as const) {
    await page.setViewportSize({ width, height: 900 })
    await page
      .getByRole("combobox", { name: "Language / 语言" })
      .selectOption(language)
    await page.evaluate(
      (value) => localStorage.setItem("vite-ui-theme", value),
      theme,
    )
    await page.reload()
    const evidence = page.getByRole("region", {
      name: language === "zh-CN" ? "固定地址依据" : "Fixed address evidence",
    })
    await expect(
      evidence.getByRole("heading", {
        name: language === "zh-CN" ? "客户声明" : "Customer declaration",
        exact: true,
      }),
    ).toBeVisible()
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy()
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({
      path: path.join(
        process.env.V2_READING_EVIDENCE!,
        `reading-${width}-${language}-${theme}.png`,
      ),
      fullPage: true,
    })
  }
  expect(writes).toEqual([])
})
