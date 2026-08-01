import { fileURLToPath } from "node:url"
import { expect, test } from "@playwright/test"

import {
  CloudatlasSourceInstancesService,
  LoginService,
  OpenAPI,
  ProjectMembershipsService,
  ProjectsService,
  UsersService,
} from "../src/client"
import { firstSuperuser, firstSuperuserPassword, testApiUrl } from "./config"
import { randomEmail, randomPassword } from "./utils/random"

const validWorkbook = fileURLToPath(
  new URL("./fixtures/customer-upload-v1.xlsx", import.meta.url),
)

test.skip(
  process.env.RUN_GOVERNANCE_E2E !== "1",
  "requires the real PostgreSQL, agent-compose, OctoBus, and CloudAtlas fixture stack",
)

test("Operator triggers a real Governance Session that publishes two snapshots", async ({
  page,
}) => {
  test.setTimeout(180_000)
  OpenAPI.BASE = testApiUrl
  const adminToken = await LoginService.loginAccessToken({
    formData: {
      username: firstSuperuser,
      password: firstSuperuserPassword,
    },
  })
  OpenAPI.TOKEN = adminToken.access_token

  const project = await ProjectsService.createProject({
    requestBody: { name: `Governance smoke ${crypto.randomUUID()}` },
  })
  const source = await CloudatlasSourceInstancesService.createCloudatlasSource({
    projectId: project.id,
    requestBody: {
      instance_id: "cloudatlas-fixture",
      capset_id: "cloudatlas-readonly",
    },
  })
  await CloudatlasSourceInstancesService.validateCloudatlasSource({
    projectId: project.id,
    sourceId: source.id,
    requestBody: { capset_token: "fixture-capset-token" },
  })
  await CloudatlasSourceInstancesService.enableCloudatlasSource({
    projectId: project.id,
    sourceId: source.id,
  })

  const email = randomEmail()
  const password = randomPassword()
  const operator = await UsersService.createUser({
    requestBody: { email, password, full_name: "Governance Operator" },
  })
  await ProjectMembershipsService.grantProjectMembership({
    projectId: project.id,
    requestBody: { user_id: operator.id, roles: ["operator"] },
  })

  await page.goto("/")
  await page.evaluate(() => localStorage.removeItem("access_token"))
  await page.goto("/login")
  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("password-input").fill(password)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/")
  const projectSelect = page.getByRole("combobox", { name: "Project" })
  await projectSelect.click()
  await page.getByRole("option", { name: project.name }).click()
  await page.getByLabel("XLSX file").setInputFiles(validWorkbook)
  await page.getByRole("button", { name: "Upload", exact: true }).click()
  const uploadRow = page
    .getByRole("row")
    .filter({ hasText: "customer-upload-v1.xlsx" })
  await uploadRow.getByRole("button", { name: "设为当前输入" }).click()

  await expect(page.getByText("Inputs ready")).toBeVisible()
  await page.getByRole("button", { name: "Trigger Run" }).click()
  await expect(
    page.getByText(
      "Governance Session accepted. Waiting for the Runner to start.",
    ),
  ).toBeVisible()
  await expect(page.getByText("COMPLETED", { exact: true })).toBeVisible({
    timeout: 120_000,
  })
  for (const step of ["LOAD_CUSTOMER", "PULL_CLOUDATLAS", "PUBLISH"]) {
    await expect(page.getByRole("cell", { name: step })).toBeVisible()
  }
  await expect(page.getByText("CUSTOMER_UPLOAD")).toBeVisible()
  await expect(page.getByText("CLOUDATLAS", { exact: true })).toBeVisible()
  await expect(page.getByText("1 records")).toHaveCount(2)
})
