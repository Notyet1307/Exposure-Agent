import { defineConfig, devices } from "@playwright/test"

export default defineConfig({
  testDir: "./tests",
  testMatch: /netflow-usability\.spec\.ts/,
  outputDir: process.env.NETFLOW_USABILITY_EVIDENCE
    ? `${process.env.NETFLOW_USABILITY_EVIDENCE}/playwright`
    : "test-results/netflow-usability",
  workers: 1,
  retries: 0,
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173",
    trace: "retain-on-failure",
  },
  projects: [{ name: "netflow-usability" }],
})
