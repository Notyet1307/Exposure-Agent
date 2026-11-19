import { test as base, expect, type Page } from "@playwright/test"

const UNKNOWN_ROUTE = "/this-route-does-not-exist"
const NARROW_VIEWPORT = { width: 390, height: 844 }

const account = {
  id: "00000000-0000-0000-0000-000000000325",
  email: "component@example.com",
  full_name: "Component Reader",
  is_active: true,
  is_superuser: false,
}

// Reads are synthesized so the browser never reaches a backend; any write is recorded and fails the test.
const test = base.extend<{ writes: string[] }>({
  writes: [
    async ({ page }, use) => {
      const writes: string[] = []
      await page.addInitScript(() =>
        localStorage.setItem("access_token", "component-token"),
      )
      await page.route("**/api/**", async (route) => {
        const request = route.request()
        if (request.method() !== "GET" && request.method() !== "HEAD") {
          writes.push(`${request.method()} ${new URL(request.url()).pathname}`)
          await route.fulfill({ status: 405, json: { detail: "read only" } })
          return
        }
        await route.fulfill({
          json: request.url().endsWith("/users/me")
            ? account
            : { data: [], count: 0 },
        })
      })
      await use(writes)
      expect(writes, "reading the 404 page must not write").toEqual([])
    },
    { auto: true },
  ],
})

const switcher = (page: Page) =>
  page.getByRole("combobox", { name: "Language / 语言" })

const homeAction = (page: Page, name: string) =>
  page.getByRole("button", { name, exact: true })

test("an unknown route shows the 404 page and a home action in both languages", async ({
  page,
}) => {
  await page.goto(UNKNOWN_ROUTE)
  const page404 = page.getByTestId("not-found")
  await expect(page404).toBeVisible()
  await expect(page404.getByText("404", { exact: true })).toBeVisible()
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN")
  await expect(
    page.getByText("未找到您要访问的页面。", { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole("link", { name: "返回首页", exact: true }),
  ).toHaveAttribute("href", "/")
  await expect(homeAction(page, "返回首页")).toBeVisible()

  await switcher(page).selectOption("en")
  await expect(
    page.getByText("The page you are looking for was not found.", {
      exact: true,
    }),
  ).toBeVisible()
  await expect(
    page.getByRole("link", { name: "Go Home", exact: true }),
  ).toHaveAttribute("href", "/")
  await expect(homeAction(page, "Go Home")).toBeVisible()

  await switcher(page).selectOption("zh-CN")
  await expect(homeAction(page, "返回首页")).toBeVisible()
})

test("Tab reaches the home action and Enter returns to the workspace home", async ({
  page,
}) => {
  await page.goto(UNKNOWN_ROUTE)
  const action = homeAction(page, "返回首页")
  await expect(page.getByTestId("not-found")).toBeVisible()
  for (let step = 0; step < 10; step += 1) {
    const focused = await action.evaluate(
      (element) => element === document.activeElement,
    )
    if (focused) break
    await page.keyboard.press("Tab")
  }
  await expect(action).toBeFocused()
  await page.keyboard.press("Enter")
  await expect(page).toHaveURL("/")
  await expect(page.getByTestId("not-found")).toBeHidden()
})

test("the 404 page and its action fit a narrow viewport without sideways scrolling", async ({
  page,
}) => {
  await page.setViewportSize(NARROW_VIEWPORT)
  await page.goto(UNKNOWN_ROUTE)
  const page404 = page.getByTestId("not-found")
  await expect(page404).toBeVisible()
  await expect(page404.getByText("404", { exact: true })).toBeVisible()
  const action = homeAction(page, "返回首页")
  await expect(action).toBeVisible()
  const box = await action.boundingBox()
  if (box === null) throw new Error("the home action has no rendered box")
  expect(box.x).toBeGreaterThanOrEqual(0)
  expect(box.x + box.width).toBeLessThanOrEqual(NARROW_VIEWPORT.width)
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBe(0)
})
