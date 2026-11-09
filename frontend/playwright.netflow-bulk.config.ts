import { defineConfig, devices } from "@playwright/test"

export default defineConfig({
  testDir: "./tests",
  testMatch: /netflow-bulk-runtime\.spec\.ts/,
  outputDir: process.env.NETFLOW_BULK_UI_EVIDENCE
    ? `${process.env.NETFLOW_BULK_UI_EVIDENCE}/playwright`
    : "test-results/netflow-bulk-runtime",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 600_000,
  expect: { timeout: 30_000 },
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173",
    trace: "retain-on-failure",
  },
  projects: [{ name: "netflow-bulk-runtime" }],
})
