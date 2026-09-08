import { expect, test } from "@playwright/test"

test("defaults to Chinese and preserves an entered login value while switching to English", async ({ page }) => {
  await page.addInitScript(() => {
    if (!sessionStorage.getItem("locale-test-ready")) {
      localStorage.removeItem("exposure-agent-locale")
      sessionStorage.setItem("locale-test-ready", "true")
    }
  })
  await page.goto("/login")
  await expect(page.getByRole("heading", { name: "登录账号" })).toBeVisible()
  await page.getByTestId("email-input").fill("person@example.com")
  await page.getByRole("button", { name: "Switch to English" }).click()
  await expect(page.getByRole("heading", { name: "Login to your account" })).toBeVisible()
  await expect(page.getByTestId("email-input")).toHaveValue("person@example.com")
  await page.reload()
  await expect(page.getByRole("heading", { name: "Login to your account" })).toBeVisible()
})
