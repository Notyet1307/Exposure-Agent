import { fileURLToPath } from "node:url"
import { expect, test } from "@playwright/test"

import {
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

test("Operator uploads a valid v1 workbook and sees its digest", async ({
  page,
}) => {
  OpenAPI.BASE = testApiUrl
  const adminToken = await LoginService.loginAccessToken({
    formData: {
      username: firstSuperuser,
      password: firstSuperuserPassword,
    },
  })
  OpenAPI.TOKEN = adminToken.access_token

  const project = await ProjectsService.createProject({
    requestBody: { name: `Upload smoke ${crypto.randomUUID()}` },
  })
  const otherProject = await ProjectsService.createProject({
    requestBody: { name: `Other smoke ${crypto.randomUUID()}` },
  })
  const email = randomEmail()
  const password = randomPassword()
  const operator = await UsersService.createUser({
    requestBody: { email, password, full_name: "Upload Operator" },
  })
  await ProjectMembershipsService.grantProjectMembership({
    projectId: project.id,
    requestBody: { user_id: operator.id, roles: ["operator"] },
  })
  await ProjectMembershipsService.grantProjectMembership({
    projectId: otherProject.id,
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
  await expect(projectSelect).toContainText(project.name)
  await page.getByLabel("XLSX file").setInputFiles(validWorkbook)
  await page.getByRole("button", { name: "Upload", exact: true }).click()

  await expect(page.getByText("Upload accepted successfully.")).toBeVisible()
  const uploadRow = page
    .getByRole("row")
    .filter({ hasText: "customer-upload-v1.xlsx" })
  await expect(uploadRow).toBeVisible()
  await expect(uploadRow.getByText(/^[a-f0-9]{64}$/)).toBeVisible()
  await expect(uploadRow.getByText("v1", { exact: true })).toBeVisible()
  await expect(page.getByText("Project input is not ready.")).toBeVisible()

  await uploadRow.getByRole("button", { name: "Set as current input" }).click()

  await expect(uploadRow.getByText("Current", { exact: true })).toBeVisible()
  const selectedInputs = await ProjectsService.readCustomerUploads({
    projectId: project.id,
  })
  expect(selectedInputs.current_customer_upload_id).toBe(
    selectedInputs.data[0].id,
  )
})
