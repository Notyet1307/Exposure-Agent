import { fileURLToPath } from "node:url"
import {
  LoginService,
  OpenAPI,
  ProjectMembershipsService,
  ProjectsService,
  UsersService,
} from "../src/client"
import { firstSuperuser, firstSuperuserPassword, testApiUrl } from "./config"
import { expect, test } from "./fixtures"
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
  await page.waitForURL((url) => url.pathname === "/")

  const projectSelect = page.getByRole("combobox", { name: "Project" })
  await projectSelect.selectOption(project.id)
  await expect(projectSelect).toHaveValue(project.id)
  await page.getByRole("link", { name: "Inputs", exact: true }).click()
  await page.getByLabel("XLSX file").setInputFiles(validWorkbook)
  await page
    .locator("form")
    .filter({ has: page.getByLabel("XLSX file") })
    .getByRole("button", { name: "Upload", exact: true })
    .click()

  await expect(page.getByText("Upload accepted successfully.")).toBeVisible()
  const uploadRow = page
    .getByRole("row")
    .filter({ hasText: "customer-upload-v1.xlsx" })
  await expect(uploadRow).toBeVisible()
  const acceptedInputs = await ProjectsService.readCustomerUploads({
    projectId: project.id,
  })
  const acceptedUpload = acceptedInputs.data[0]
  const uploadDetails = uploadRow.locator("details")
  await expect(
    uploadDetails.getByText(acceptedUpload.raw_sha256, { exact: true }),
  ).toBeHidden()
  await uploadDetails.locator("summary").focus()
  await page.keyboard.press("Enter")
  await expect(
    uploadDetails.getByText(acceptedUpload.raw_sha256, { exact: true }),
  ).toBeVisible()
  await expect(
    uploadDetails.getByText(acceptedUpload.id, { exact: true }),
  ).toBeVisible()
  await expect(
    uploadDetails.getByText(acceptedUpload.profile_id, { exact: true }),
  ).toBeVisible()
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"])
  await uploadDetails
    .getByRole("button", {
      name: `Copy full value: ${acceptedUpload.raw_sha256}`,
      exact: true,
    })
    .focus()
  await page.keyboard.press("Enter")
  await expect
    .poll(() => page.evaluate(() => navigator.clipboard.readText()))
    .toBe(acceptedUpload.raw_sha256)
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

  await page.route(
    (url) => url.pathname === `/api/v1/projects/${project.id}/customer-uploads`,
    (route) =>
      route.fulfill({
        json: {
          ...selectedInputs,
          count: 11,
          data: [
            {
              ...acceptedUpload,
              id: crypto.randomUUID(),
              display_filename: "different-page-input.xlsx",
            },
          ],
        },
      }),
  )
  await page.goto(`/?project=${project.id}&view=inputs&upload_page=2`)
  await expect(
    page.getByText("Current selected input", { exact: true }),
  ).toBeVisible()
  const currentInputDetails = page.locator("details").filter({
    has: page
      .locator("summary")
      .getByText("Current input details", { exact: true }),
  })
  await expect(
    currentInputDetails.getByText(acceptedUpload.id, { exact: true }),
  ).toBeHidden()
  await currentInputDetails.locator("summary").focus()
  await page.keyboard.press("Enter")
  await expect(
    currentInputDetails.getByText(acceptedUpload.id, { exact: true }),
  ).toBeVisible()
  await currentInputDetails
    .getByRole("button", {
      name: "Copy Current CustomerUpload ID",
      exact: true,
    })
    .click()
  await expect
    .poll(() => page.evaluate(() => navigator.clipboard.readText()))
    .toBe(acceptedUpload.id)
})
