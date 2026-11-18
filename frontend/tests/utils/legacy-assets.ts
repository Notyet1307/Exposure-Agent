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

const historicalViews = {
  Overview: "overview",
  Reports: "reports",
  Runs: "runs",
  Findings: "findings",
} as const

export async function clickHistoricalLink(page: Page, name: string) {
  const mappedView =
    historicalViews[name as keyof typeof historicalViews] ?? name.toLowerCase()
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
    throw new Error(
      `Historical navigation (${name}) requires a project context`,
    )
  url.pathname = "/"
  url.hash = ""
  url.searchParams.set("view", mappedView)
  const nextUrl = `${url.pathname}${url.search}${url.hash}`
  await page.evaluate((target) => {
    window.history.pushState({}, "", target)
    window.dispatchEvent(new PopStateEvent("popstate"))
  }, nextUrl)
}
