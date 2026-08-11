import { fileURLToPath } from "node:url"
import { expect, test } from "@playwright/test"

import {
  CloudatlasSourceInstancesService,
  GovernanceRunsService,
  IpResultsService,
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
const customerSnapshotSha256 =
  "ff4512058e966fd8d56d2d89572b8eea3adde6972eb573806317f7481f0c9d83"
const cloudatlasSnapshotSha256 =
  "87fda692036fb5c949cecf673178e9a72d367e284663de65115d8d1db1ca00e1"
const stage4FirstWorkbook = fileURLToPath(
  new URL("./fixtures/customer-upload-stage4-first.xlsx", import.meta.url),
)
const stage4SecondWorkbook = fileURLToPath(
  new URL("./fixtures/customer-upload-stage4-second.xlsx", import.meta.url),
)
const stage4FixtureUrl = "http://cloudatlas-fixture:18080"
const stage4MatchedIp = "192.0.2.46"
const stage4MissingIp = "198.51.100.7"
const stage4CloudOnlyIp = "203.0.113.5"

test.skip(
  process.env.RUN_GOVERNANCE_E2E !== "1",
  "requires the real PostgreSQL, agent-compose, OctoBus, and CloudAtlas fixture stack",
)
test.describe.configure({ mode: "serial" })

test("Operator completes Retry and explicit Rerun recovery with real Sessions", async ({
  page,
  request,
}) => {
  test.setTimeout(300_000)
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
  const operatorToken = await LoginService.loginAccessToken({
    formData: { username: email, password },
  })
  OpenAPI.TOKEN = operatorToken.access_token

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

  await page.getByRole("tab", { name: "Runs", exact: true }).click()
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
  for (const step of [
    "LOAD_CUSTOMER",
    "PULL_CLOUDATLAS",
    "NORMALIZE",
    "RESOLVE",
    "CHECK_FINDINGS",
    "BUILD_REPORT",
    "VALIDATE_REPORT",
    "PUBLISH",
  ]) {
    await expect(page.getByRole("cell", { name: step })).toBeVisible()
  }
  await expect(page.getByText("CUSTOMER_UPLOAD")).toBeVisible()
  await expect(page.getByText("CLOUDATLAS", { exact: true })).toBeVisible()
  await expect(page.getByText("1 records")).toHaveCount(2)

  const armed = await request.post(
    "http://cloudatlas-fixture:18080/fixture/fail-next",
  )
  expect(armed.ok()).toBeTruthy()
  await page.getByRole("button", { name: "Trigger Run" }).click()
  await expect
    .poll(
      async () =>
        (
          await GovernanceRunsService.readGovernanceRuns({
            projectId: project.id,
          })
        ).data[0]?.status,
      { timeout: 120_000 },
    )
    .toBe("FAILED_DATA")
  const failedRuns = await GovernanceRunsService.readGovernanceRuns({
    projectId: project.id,
  })
  const failedRun = failedRuns.data[0]
  expect(failedRun.steps.map((step) => [step.step_code, step.status])).toEqual([
    ["LOAD_CUSTOMER", "SUCCEEDED"],
    ["PULL_CLOUDATLAS", "FAILED"],
  ])
  await expect
    .poll(
      async () =>
        (
          await GovernanceRunsService.readGovernanceRuns({
            projectId: project.id,
          })
        ).data[0]?.can_retry,
      { timeout: 120_000 },
    )
    .toBe(true)

  await page.reload()
  await page.getByRole("tab", { name: "Runs", exact: true }).click()
  await page.getByRole("button", { name: "Retry same Session" }).click()
  await expect
    .poll(
      async () =>
        (
          await GovernanceRunsService.readGovernanceRuns({
            projectId: project.id,
          })
        ).data[0]?.status,
      { timeout: 120_000 },
    )
    .toBe("COMPLETED")
  const recovered = (
    await GovernanceRunsService.readGovernanceRuns({ projectId: project.id })
  ).data[0]
  expect(recovered.id).toBe(failedRun.id)
  expect(recovered.trigger_id).toBe(failedRun.trigger_id)
  expect(recovered.session_id).toBe(failedRun.session_id)
  expect(
    Object.fromEntries(
      recovered.steps.map((step) => [step.step_code, step.attempt]),
    ),
  ).toEqual({
    LOAD_CUSTOMER: 1,
    PULL_CLOUDATLAS: 2,
    NORMALIZE: 1,
    RESOLVE: 1,
    CHECK_FINDINGS: 1,
    BUILD_REPORT: 1,
    VALIDATE_REPORT: 1,
    PUBLISH: 1,
  })
  expect(recovered.reused_snapshot_count).toBe(1)
  expect(
    recovered.snapshots.map((snapshot) => [
      snapshot.source_type,
      snapshot.record_count,
      snapshot.content_sha256,
    ]),
  ).toEqual([
    ["CLOUDATLAS", 1, cloudatlasSnapshotSha256],
    ["CUSTOMER_UPLOAD", 1, customerSnapshotSha256],
  ])

  const secondFailure = await request.post(
    "http://cloudatlas-fixture:18080/fixture/fail-next",
  )
  expect(secondFailure.ok()).toBeTruthy()
  await expect(page.getByRole("button", { name: "Trigger Run" })).toBeVisible({
    timeout: 5_000,
  })
  await page.getByRole("button", { name: "Trigger Run" }).click()
  await expect
    .poll(
      async () =>
        (
          await GovernanceRunsService.readGovernanceRuns({
            projectId: project.id,
          })
        ).data[0]?.status,
      { timeout: 120_000 },
    )
    .toBe("FAILED_DATA")
  const unrecoverable = (
    await GovernanceRunsService.readGovernanceRuns({ projectId: project.id })
  ).data[0]
  await expect
    .poll(
      async () =>
        (
          await GovernanceRunsService.readGovernanceRuns({
            projectId: project.id,
          })
        ).data[0]?.can_retry,
      { timeout: 120_000 },
    )
    .toBe(true)

  // Stop the Runs tab polling before arming the one-shot Session probe. A
  // background read can otherwise consume the fixture's probe and make the
  // explicit retry appear recoverable (202) instead of fail-closed (409).
  await page.getByRole("tab", { name: "Inputs", exact: true }).click()
  const missNextSession = await request.post(
    "http://cloudatlas-fixture:18080/fixture/miss-next-session-query",
  )
  expect(missNextSession.ok()).toBeTruthy()
  const unknownRetry = await request.post(
    `${testApiUrl}/api/v1/projects/${project.id}/governance-runs/${unrecoverable.id}/retry`,
    {
      headers: { Authorization: `Bearer ${operatorToken.access_token}` },
    },
  )
  expect(unknownRetry.status()).toBe(409)
  expect((await unknownRetry.json()).detail.code).toBe(
    "run_session_state_unknown",
  )

  const removeBeforeResume = await request.post(
    "http://cloudatlas-fixture:18080/fixture/remove-session-before-resume",
  )
  expect(removeBeforeResume.ok()).toBeTruthy()
  const unavailableRetry = await request.post(
    `${testApiUrl}/api/v1/projects/${project.id}/governance-runs/${unrecoverable.id}/retry`,
    {
      headers: { Authorization: `Bearer ${operatorToken.access_token}` },
    },
  )
  expect(unavailableRetry.status()).toBe(409)
  expect((await unavailableRetry.json()).detail.code).toBe(
    "run_session_not_recoverable",
  )

  await page.reload()
  await page.getByRole("tab", { name: "Runs", exact: true }).click()
  await expect(
    page.getByText(
      "The original Session cannot be recovered. Use an explicit Rerun.",
    ),
  ).toBeVisible()
  await page.getByRole("button", { name: "Rerun with current inputs" }).click()
  await expect
    .poll(
      async () =>
        (
          await GovernanceRunsService.readGovernanceRuns({
            projectId: project.id,
          })
        ).data[0]?.status,
      { timeout: 120_000 },
    )
    .toBe("COMPLETED")
  const rerunRuns = await GovernanceRunsService.readGovernanceRuns({
    projectId: project.id,
  })
  expect(rerunRuns.count).toBe(4)
  expect(rerunRuns.data[0].id).not.toBe(unrecoverable.id)
  expect(rerunRuns.data[0].trigger_id).not.toBe(unrecoverable.trigger_id)
  expect(rerunRuns.data[0].session_id).not.toBe(unrecoverable.session_id)
  expect(rerunRuns.data[1].id).toBe(unrecoverable.id)
  expect(rerunRuns.data[1].status).toBe("FAILED_PROCESSING")
  const historicalRetry = await request.post(
    `${testApiUrl}/api/v1/projects/${project.id}/governance-runs/${unrecoverable.id}/retry`,
    {
      headers: { Authorization: `Bearer ${operatorToken.access_token}` },
    },
  )
  expect(historicalRetry.status()).toBe(409)
  expect((await historicalRetry.json()).detail.code).toBe(
    "run_session_not_recoverable",
  )
})

test("Project readers see published IP lifecycle results and safe failure fallback", async ({
  page,
  request,
}) => {
  test.setTimeout(360_000)
  OpenAPI.BASE = testApiUrl
  const adminToken = await LoginService.loginAccessToken({
    formData: {
      username: firstSuperuser,
      password: firstSuperuserPassword,
    },
  })
  OpenAPI.TOKEN = adminToken.access_token

  const project = await ProjectsService.createProject({
    requestBody: { name: `Stage 4 Project ${crypto.randomUUID()}` },
  })
  const source = await CloudatlasSourceInstancesService.createCloudatlasSource({
    projectId: project.id,
    requestBody: {
      instance_id: "cloudatlas-fixture",
      capset_id: "cloudatlas-readonly",
    },
  })
  await request.post(`${stage4FixtureUrl}/fixture/set-assets`, {
    data: {
      items: [{ id: 2, ip: stage4MatchedIp, status: "valid" }],
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

  const credentials: Record<
    "operator" | "viewer" | "approver",
    { email: string; password: string }
  > = {
    operator: { email: randomEmail(), password: randomPassword() },
    viewer: { email: randomEmail(), password: randomPassword() },
    approver: { email: randomEmail(), password: randomPassword() },
  }
  for (const [role, account] of Object.entries(credentials)) {
    const user = await UsersService.createUser({
      requestBody: {
        email: account.email,
        password: account.password,
        full_name: `Stage 4 ${role}`,
      },
    })
    await ProjectMembershipsService.grantProjectMembership({
      projectId: project.id,
      requestBody: {
        user_id: user.id,
        roles: [role as "operator" | "viewer" | "approver"],
      },
    })
  }

  async function loginInBrowser(account: { email: string; password: string }) {
    await page.goto("/")
    await page.evaluate(() => localStorage.removeItem("access_token"))
    await page.goto("/login")
    await page.getByTestId("email-input").fill(account.email)
    await page.getByTestId("password-input").fill(account.password)
    await page.getByRole("button", { name: "Log In" }).click()
    await page.waitForURL("/")
    const projectSelect = page.getByRole("combobox", { name: "Project" })
    await projectSelect.click()
    await page.getByRole("option", { name: project.name }).click()
  }

  async function waitForLatestStatus(status: string, previousRunId?: string) {
    await expect
      .poll(
        async () => {
          const latest = (
            await GovernanceRunsService.readGovernanceRuns({
              projectId: project.id,
            })
          ).data[0]
          return latest?.status === status && latest.id !== previousRunId
        },
        { timeout: 120_000 },
      )
      .toBe(true)
    const run = (
      await GovernanceRunsService.readGovernanceRuns({
        projectId: project.id,
      })
    ).data[0]
    if (!run) throw new Error(`No Governance Run reached ${status}.`)
    return run
  }

  const operatorToken = await LoginService.loginAccessToken({
    formData: {
      username: credentials.operator.email,
      password: credentials.operator.password,
    },
  })
  OpenAPI.TOKEN = operatorToken.access_token
  await loginInBrowser(credentials.operator)
  await page.getByLabel("XLSX file").setInputFiles(stage4FirstWorkbook)
  await page.getByRole("button", { name: "Upload", exact: true }).click()
  const firstUploadRow = page
    .getByRole("row")
    .filter({ hasText: "customer-upload-stage4-first.xlsx" })
  await firstUploadRow.getByRole("button", { name: "设为当前输入" }).click()

  await request.post(`${stage4FixtureUrl}/fixture/set-assets`, {
    data: {
      items: [
        { id: 3, ip: stage4MatchedIp, status: "valid" },
        { id: 4, ip: stage4CloudOnlyIp, status: "valid" },
      ],
    },
  })
  await page.getByRole("tab", { name: "Runs", exact: true }).click()
  await expect(page.getByText("Inputs ready")).toBeVisible()
  await page.getByRole("button", { name: "Trigger Run" }).click()
  await expect(page.getByText("COMPLETED", { exact: true })).toBeVisible({
    timeout: 120_000,
  })
  const firstRun = await waitForLatestStatus("COMPLETED")
  expect(firstRun).toBeDefined()

  await page.getByRole("tab", { name: "Assets", exact: true }).click()
  await expect(page.getByText(stage4MatchedIp, { exact: true })).toBeVisible()
  await expect(page.getByText(stage4MissingIp, { exact: true })).toBeVisible()
  await expect(page.getByText(stage4CloudOnlyIp, { exact: true })).toBeVisible()
  await page.getByRole("tab", { name: "Findings", exact: true }).click()
  await expect(
    page.getByRole("table").getByText("UNOBSERVED_ASSET", { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole("table").getByText("UNREPORTED_ASSET", { exact: true }),
  ).toBeVisible()
  const firstFindings = await IpResultsService.readFindings({
    projectId: project.id,
    status: "OPEN",
  })
  expect(firstFindings.data).toHaveLength(2)
  const missingFinding = firstFindings.data.find(
    (finding) => finding.canonical_ip === stage4MissingIp,
  )
  const cloudOnlyFinding = firstFindings.data.find(
    (finding) => finding.canonical_ip === stage4CloudOnlyIp,
  )
  expect(missingFinding).toBeDefined()
  expect(cloudOnlyFinding).toBeDefined()
  const missingFindingRow = page
    .getByRole("row")
    .filter({ hasText: stage4MissingIp })
  await missingFindingRow.getByRole("button", { name: "View details" }).click()
  await expect(page.getByRole("dialog")).toContainText("row:3")
  await expect(page.getByRole("dialog")).toContainText(
    "Confirmed Snapshot references",
  )
  await page.getByRole("button", { name: "Close" }).click()

  await page.getByRole("tab", { name: "Inputs", exact: true }).click()
  await page.getByLabel("XLSX file").setInputFiles(stage4SecondWorkbook)
  await page.getByRole("button", { name: "Upload", exact: true }).click()
  const secondUploadRow = page
    .getByRole("row")
    .filter({ hasText: "customer-upload-stage4-second.xlsx" })
  await secondUploadRow.getByRole("button", { name: "设为当前输入" }).click()
  await request.post(`${stage4FixtureUrl}/fixture/set-assets`, {
    data: {
      items: [
        { id: 3, ip: stage4MatchedIp, status: "valid" },
        { id: 4, ip: stage4CloudOnlyIp, status: "valid" },
      ],
    },
  })
  await page.getByRole("tab", { name: "Runs", exact: true }).click()
  await page.getByRole("button", { name: "Trigger Run" }).click()
  await expect(page.getByText("COMPLETED", { exact: true })).toBeVisible({
    timeout: 120_000,
  })
  const secondRun = await waitForLatestStatus("COMPLETED", firstRun.id)
  expect(secondRun.id).not.toBe(firstRun?.id)

  await page.getByRole("tab", { name: "Findings", exact: true }).click()
  await expect(page.getByText(stage4MissingIp, { exact: true })).toBeVisible()
  await page.getByRole("combobox", { name: "Finding status" }).click()
  await page.getByRole("option", { name: "CLOSED", exact: true }).click()
  await expect(page.getByText(stage4CloudOnlyIp, { exact: true })).toBeVisible()
  await expect(
    page.getByRole("table").getByText("CLOSED", { exact: true }),
  ).toBeVisible()
  const closedRow = page.getByRole("row").filter({ hasText: stage4CloudOnlyIp })
  await closedRow.getByRole("button", { name: "View details" }).click()
  await expect(page.getByRole("dialog")).toContainText("Transition · CLOSED")
  await expect(page.getByRole("dialog")).toContainText("CLOUDATLAS")
  await page.getByRole("button", { name: "Close" }).click()
  const closedFindings = await IpResultsService.readFindings({
    projectId: project.id,
    status: "CLOSED",
  })
  expect(closedFindings.data.map((finding) => finding.id)).toContain(
    cloudOnlyFinding?.id,
  )
  const openAfterSecondRun = await IpResultsService.readFindings({
    projectId: project.id,
    status: "OPEN",
  })
  expect(openAfterSecondRun.data.map((finding) => finding.id)).toContain(
    missingFinding?.id,
  )
  expect(
    openAfterSecondRun.data.find((finding) => finding.id === missingFinding?.id)
      ?.occurrence_count,
  ).toBe(1)

  await request.post(`${stage4FixtureUrl}/fixture/fail-next`)
  await page.getByRole("tab", { name: "Runs", exact: true }).click()
  await page.getByRole("button", { name: "Trigger Run" }).click()
  const failedRun = await waitForLatestStatus("FAILED_DATA", secondRun.id)
  expect(failedRun.id).not.toBe(secondRun.id)
  expect(failedRun.steps.map((step) => step.step_code)).toEqual([
    "LOAD_CUSTOMER",
    "PULL_CLOUDATLAS",
  ])
  await expect(page.getByText("FAILED_DATA", { exact: true })).toBeVisible()
  await expect(
    page.getByText("COMPLETED", { exact: true }).first(),
  ).toBeVisible()

  await page.getByRole("tab", { name: "Assets", exact: true }).click()
  await expect(
    page.getByText(`Published Run ${secondRun.id}`, { exact: true }),
  ).toBeVisible()
  await expect(page.getByText(stage4CloudOnlyIp, { exact: true })).toBeVisible()
  await page.getByRole("tab", { name: "Findings", exact: true }).click()
  await expect(page.getByText(stage4MissingIp, { exact: true })).toBeVisible()

  for (const role of ["viewer", "approver"] as const) {
    await loginInBrowser(credentials[role])
    await page.getByRole("tab", { name: "Assets", exact: true }).click()
    await expect(
      page.getByText(stage4CloudOnlyIp, { exact: true }),
    ).toBeVisible()
    await page.getByRole("tab", { name: "Findings", exact: true }).click()
    await expect(page.getByText(stage4MissingIp, { exact: true })).toBeVisible()
  }

  OpenAPI.TOKEN = adminToken.access_token
  await ProjectsService.archiveProject({ projectId: project.id })
  await loginInBrowser({
    email: firstSuperuser,
    password: firstSuperuserPassword,
  })
  await expect(
    page.getByText("Archived Project", { exact: true }),
  ).toBeVisible()
  await page.getByRole("tab", { name: "Assets", exact: true }).click()
  await expect(page.getByText(stage4CloudOnlyIp, { exact: true })).toBeVisible()
  await page.getByRole("tab", { name: "Findings", exact: true }).click()
  await expect(page.getByText(stage4MissingIp, { exact: true })).toBeVisible()
})
