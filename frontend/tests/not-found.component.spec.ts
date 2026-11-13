import { expect, type Page, test } from "@playwright/test"

const unknownPath = "/definitely-not-a-route-404"

const admin = {
  id: "00000000-0000-0000-0000-000000000099",
  email: "admin@example.com",
  full_name: "Admin",
  is_active: true,
  is_superuser: true,
}

async function seedAuth(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("access_token", "component-token")
  })
  await page.route("**/api/v1/users/me", (route) =>
    route.fulfill({ json: admin }),
  )
}

test("shows the 404 page with the Chinese home label by default", async ({
  page,
}) => {
  await page.goto(unknownPath)

  await expect(page.getByTestId("not-found")).toBeVisible()
  await expect(page.getByText("404", { exact: true })).toBeVisible()
  await expect(
    page.getByText("未找到您要访问的页面。", { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "返回首页", exact: true }),
  ).toBeVisible()
})

test("shows the English 404 copy and home label", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("exposure:language", "en")
  })
  await page.goto(unknownPath)

  await expect(page.getByTestId("not-found")).toBeVisible()
  await expect(
    page.getByText("The page you are looking for was not found.", {
      exact: true,
    }),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Go Home", exact: true }),
  ).toBeVisible()
})

test("the home action navigates to / by click and by Tab then Enter without writes", async ({
  page,
}) => {
  await seedAuth(page)
  const writes: string[] = []
  page.on("request", (request) => {
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method())) {
      writes.push(`${request.method()} ${request.url()}`)
    }
  })

  await page.goto(unknownPath)
  await page.getByRole("button", { name: "返回首页", exact: true }).click()
  await expect(page).toHaveURL("/")

  await page.goto(unknownPath)
  const home = page.getByRole("button", { name: "返回首页", exact: true })
  let reachedByTab = false
  for (let press = 0; press < 10 && !reachedByTab; press++) {
    await page.keyboard.press("Tab")
    reachedByTab = await home.evaluate(
      (element) => element === document.activeElement,
    )
  }
  expect(reachedByTab).toBe(true)
  await page.keyboard.press("Enter")
  await expect(page).toHaveURL("/")

  expect(writes).toEqual([])
})

test("the 404 page fits a narrow viewport without horizontal overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 667 })
  await page.goto(unknownPath)

  await expect(page.getByTestId("not-found")).toBeVisible()
  await expect(
    page.getByRole("button", { name: "返回首页", exact: true }),
  ).toBeVisible()
  const overflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
})
