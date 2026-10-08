import { defineConfig } from "@playwright/test"
import base from "./playwright.netflow.config"

export default defineConfig({
  ...base,
  testMatch: /product-logic\.spec\.ts/,
  outputDir: process.env.PRODUCT_LOGIC_EVIDENCE
    ? `${process.env.PRODUCT_LOGIC_EVIDENCE}/playwright`
    : "test-results/product-logic",
  projects: [{ name: "product-logic" }],
})
