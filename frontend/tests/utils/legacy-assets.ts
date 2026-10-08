import type { Page } from "@playwright/test"

// Historical readers keep their original deep links after leaving the main menu.
export async function openLegacyAssets(page: Page) {
  await page.waitForURL(
    (url) =>
      url.searchParams.has("project") || url.pathname.startsWith("/projects/"),
  )
  const url = new URL(page.url())
  const scope = url.pathname.match(/^\/projects\/([^/]+)(?:\/runs\/([^/]+))?/)
  if (scope) {
    url.searchParams.set("project", scope[1])
    if (scope[2]) url.searchParams.set("run", scope[2])
  }
  if (!url.searchParams.has("project"))
    throw new Error("Legacy asset navigation requires an explicit project")
  url.pathname = "/"
  url.hash = ""
  url.searchParams.set("view", "assets")
  await page.goto(url.toString())
}

export async function clickHistoricalLink(page: Page, name: string) {
  const link = page.getByRole("link", { name, exact: true })
  const section = page.locator("details").filter({
    has: page.getByText("Historical governance", { exact: true }),
  })
  if ((await section.getAttribute("open")) === null)
    await page.getByText("Historical governance", { exact: true }).click()
  await link.click()
}
