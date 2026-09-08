import { test as base } from "@playwright/test"

// Regression suites select English without changing the product's Chinese default.
export const test = base.extend({
  page: async ({ page }, use) => {
    await page.addInitScript(() => {
      if (localStorage.getItem("exposure:language") === null) {
        localStorage.setItem("exposure:language", "en")
      }
    })
    await use(page)
  },
})

export { expect, type Page, type Route } from "@playwright/test"
