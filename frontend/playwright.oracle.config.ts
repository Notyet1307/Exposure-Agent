import { defineConfig, devices } from "@playwright/test"

const baseURL = "http://127.0.0.1:41737"

export default defineConfig({
  testDir: "./oracles",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: "line",
  use: {
    ...devices["Desktop Chrome"],
    baseURL,
    trace: "on-first-retry",
  },
  projects: [{ name: "rel003-oracle", testMatch: /.*\.spec\.ts/ }],
  webServer: {
    command: "bun run dev -- --host 127.0.0.1 --port 41737 --strictPort",
    url: baseURL,
    reuseExistingServer: false,
  },
})
