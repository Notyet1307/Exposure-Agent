import { expect, type Page, test } from "@playwright/test"

const switcher = (page: Page) =>
  page.getByRole("combobox", { name: "Language / 语言" })

const admin = {
  id: "00000000-0000-0000-0000-000000000099",
  email: "admin@example.com",
  full_name: "Admin",
  is_active: true,
  is_superuser: true,
}

async function mockAdmin(page: Page) {
  await page.addInitScript(() =>
    localStorage.setItem("access_token", "component-token"),
  )
  await page.route("**/api/v1/users/me", (route) =>
    route.fulfill({ json: admin }),
  )
  await page.route("**/api/v1/users/?*", (route) =>
    route.fulfill({
      json: {
        data: Array.from({ length: 12 }, (_, index) => ({
          ...admin,
          id: `00000000-0000-0000-0000-${String(index + 1).padStart(12, "0")}`,
          email: `user${index + 1}@example.com`,
          full_name: `Customer ${index + 1}`,
          is_superuser: false,
        })),
        count: 12,
      },
    }),
  )
}

test("language switch preserves login inputs, validation and persisted choice", async ({
  page,
}) => {
  await page.goto("/login")
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN")
  await expect(
    page.getByRole("button", { name: "登录", exact: true }),
  ).toBeVisible()
  await page.getByTestId("email-input").fill("invalid-email")
  await page.getByTestId("password-input").fill("short")
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(
    page.getByText("请输入有效的电子邮箱地址", { exact: true }),
  ).toBeVisible()
  await switcher(page).selectOption("en")
  await expect(
    page.getByText("Invalid email address", { exact: true }),
  ).toBeVisible()
  await expect(page.getByTestId("email-input")).toHaveValue("invalid-email")
  await expect(page.getByTestId("password-input")).toHaveValue("short")
  await expect(
    page.getByRole("button", { name: "Show password" }),
  ).toBeVisible()
  await page.reload()
  await expect(
    page.getByRole("button", { name: "Log In", exact: true }),
  ).toBeVisible()
  await expect(page.locator("html")).toHaveAttribute("lang", "en")
  await switcher(page).selectOption("zh-CN")
  await page.reload()
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN")
})

test("an existing authentication error translates without clearing entered credentials", async ({
  page,
}) => {
  await page.route("**/api/v1/login/access-token", (route) =>
    route.fulfill({
      status: 400,
      json: { detail: "Incorrect email or password" },
    }),
  )
  await page.goto("/login")
  await page.getByTestId("email-input").fill("customer@example.com")
  await page.getByTestId("password-input").fill("Wrong-password-123")
  await page.getByRole("button", { name: "登录", exact: true }).click()
  await expect(page.getByText("邮箱或密码错误", { exact: true })).toBeVisible()
  await switcher(page).selectOption("en")
  await expect(
    page.getByText("Incorrect email or password", { exact: true }),
  ).toBeVisible()
  await expect(page.getByTestId("email-input")).toHaveValue(
    "customer@example.com",
  )
  await expect(page.getByTestId("password-input")).toHaveValue(
    "Wrong-password-123",
  )
})

test("admin pagination and an open validated form survive language changes", async ({
  page,
}) => {
  await mockAdmin(page)
  await page.goto("/admin")
  await expect(
    page.getByRole("columnheader", { name: "电子邮箱" }),
  ).toBeVisible()
  await page.getByRole("button", { name: "转到下一页" }).click()
  await expect(
    page.getByText("user11@example.com", { exact: true }),
  ).toBeVisible()
  await switcher(page).selectOption("en")
  await expect(page.getByText("Page 2 of 2", { exact: true })).toBeVisible()
  await expect(
    page.getByText("user11@example.com", { exact: true }),
  ).toBeVisible()
  await page.getByRole("button", { name: "Add User", exact: true }).click()
  const dialog = page.getByRole("dialog")
  await dialog.getByPlaceholder("Full name").fill("Customer-provided name")
  await dialog.getByPlaceholder("Email", { exact: true }).fill("invalid-email")
  await dialog.getByRole("button", { name: "Save", exact: true }).click()
  await expect(
    dialog.getByText("Invalid email address", { exact: true }),
  ).toBeVisible()
  await dialog
    .getByRole("combobox", { name: "Language / 语言" })
    .selectOption("zh-CN")
  await expect(
    dialog.getByText("请输入有效的电子邮箱地址", { exact: true }),
  ).toBeVisible()
  await expect(dialog.locator('input[name="full_name"]')).toHaveValue(
    "Customer-provided name",
  )
  await expect(dialog.locator('input[name="email"]')).toHaveValue(
    "invalid-email",
  )
  await dialog.getByRole("button", { name: "取消", exact: true }).click()
  await expect(
    page.getByText("第 2 页，共 2 页", { exact: true }),
  ).toBeVisible()
})

for (const path of ["/login", "/admin"]) {
  test(`theme focus survives rapid reopening and Escape on ${path}`, async ({
    page,
  }) => {
    await page.addInitScript(() => {
      localStorage.setItem("exposure:language", "en")
      localStorage.setItem("vite-ui-theme", "light")
    })
    if (path === "/admin") await mockAdmin(page)
    await page.goto(path)
    const trigger = page.getByTestId("theme-button")
    await trigger.focus()
    // Hold the first exit animation to make rapid reopening deterministic.
    const closingAnimation = await page.addStyleTag({
      content:
        '[role="menu"][data-state="closed"] { animation-duration: 30s; }',
    })
    await page.keyboard.press("Enter")
    await expect(page.getByTestId("light-mode")).toBeFocused()
    await page.keyboard.press("Enter")
    await expect(page.getByRole("menu")).toHaveAttribute("data-state", "closed")
    await trigger.focus()
    await page.keyboard.press("Enter")
    await expect(page.getByRole("menu")).toHaveAttribute("data-state", "open")
    await closingAnimation.evaluate((style) => style.remove())
    await page.getByTestId("dark-mode").focus()
    await expect(page.getByTestId("dark-mode")).toBeFocused()
    await page.keyboard.press("Enter")
    await expect(page.locator("html")).toHaveClass(/dark/)
    await expect(page.getByRole("menu")).toBeHidden()
    await expect(trigger).toBeFocused()

    await page.keyboard.press("Enter")
    await expect(page.getByRole("menu")).toBeVisible()
    await page.keyboard.press("Escape")
    await expect(page.getByRole("menu")).toBeHidden()
    await expect(trigger).toBeFocused()
    await expect(page.locator("html")).toHaveClass(/dark/)
  })
}
