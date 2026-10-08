import { mkdir } from "node:fs/promises"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { expect, test } from "./fixtures"

const api = process.env.TEST_API_URL!
const workbook = (name: string) => fileURLToPath(new URL(`./fixtures/${name}`, import.meta.url))

test("customer replacement uses the real preview, preserves old versions and recovers lost replies", async ({page, request}) => {
  const login = await request.post(`${api}/api/v1/login/access-token`, {form: {
    username: process.env.FIRST_SUPERUSER!, password: process.env.FIRST_SUPERUSER_PASSWORD!,
  }})
  expect(login.ok()).toBeTruthy()
  const token = (await login.json()).access_token as string
  const headers = {Authorization: `Bearer ${token}`}
  const created = await request.post(`${api}/api/v1/projects/`, {headers, data: {name: `Product replacement ${crypto.randomUUID()}`}})
  expect(created.status()).toBe(201)
  const project = await created.json()
  const root = `${api}/api/v1/projects/${project.id}`
  await page.addInitScript((value) => localStorage.setItem("access_token", value), token)
  await page.goto(`/?project=${project.id}&view=inputs`)
  await expect(page.getByRole("heading", {name: "Data access", exact: true})).toBeVisible()
  const upload = async (name: string) => {
    await page.getByLabel("XLSX file", {exact:true}).setInputFiles(workbook(name))
    await page.locator("form").filter({has: page.getByLabel("XLSX file", {exact:true})}).getByRole("button", {name:"Upload",exact:true}).click()
    const row = page.getByRole("row").filter({hasText:name})
    await expect(row).toBeVisible()
    return row
  }
  const first = await upload("customer-upload-v1.xlsx")
  let inputs = await (await request.get(root + "/customer-uploads", {headers})).json()
  expect(inputs.current_customer_upload_id).toBeNull()
  const firstId = inputs.data[0].id as string
  await first.getByRole("button", {name:"Preview replacement"}).click()
  await expect(page.getByText("Replacement preview", {exact:true})).toBeVisible()
  expect((await (await request.get(root + "/customer-uploads", {headers})).json()).current_customer_upload_id).toBeNull()
  await page.getByRole("button", {name:"Apply replacement",exact:true}).click()
  await expect(first.getByText("Current", {exact:true})).toBeVisible()
  await expect(page.getByText("Replacement confirmed.", {exact:false})).toBeVisible()

  const second = await upload("customer-upload-stage4-second.xlsx")
  inputs = await (await request.get(root + "/customer-uploads", {headers})).json()
  const secondId = inputs.data.find((row: {display_filename:string}) => row.display_filename === "customer-upload-stage4-second.xlsx").id as string
  expect(inputs.current_customer_upload_id).toBe(firstId)
  await second.getByRole("button", {name:"Preview replacement"}).click()
  await expect(page.getByText("Replacement preview", {exact:true})).toBeVisible()
  expect((await (await request.get(root + "/customer-uploads", {headers})).json()).current_customer_upload_id).toBe(firstId)
  let applies = 0
  const applyPath = `/api/v1/projects/${project.id}/customer-ledger/replacements`
  await page.route((url) => url.pathname === applyPath, async (route) => {
    applies += 1
    const response = await route.fetch()
    expect(response.status()).toBe(201)
    await route.abort("connectionfailed")
  })
  await page.getByRole("button", {name:"Apply replacement",exact:true}).click()
  await expect(page.getByText("Replacement outcome unknown", {exact:true})).toBeVisible()
  await expect(page.getByRole("button", {name:"Preview replacement"})).toHaveCount(0)
  expect(applies).toBe(1)
  expect((await (await request.get(root + "/customer-uploads", {headers})).json()).current_customer_upload_id).toBe(secondId)
  await page.reload()
  await page.getByRole("button", {name:"Recover result",exact:true}).click()
  await expect(page.getByText("Replacement confirmed.", {exact:false})).toBeVisible()
  await expect(page.getByText("Replacement outcome unknown", {exact:true})).toHaveCount(0)
  expect(applies).toBe(1)
  const historical = await request.get(root + `/customer-ledger?upload_id=${firstId}&original=true`, {headers})
  expect(historical.ok()).toBeTruthy()
  expect((await historical.json()).upload_id).toBe(firstId)
  expect((await (await request.get(root + "/customer-uploads", {headers})).json()).current_customer_upload_id).toBe(secondId)

  const evidence = process.env.PRODUCT_LOGIC_EVIDENCE
  if (evidence) {
    await mkdir(evidence, {recursive:true})
    await page.setViewportSize({width:1366,height:900})
    await page.screenshot({path:path.join(evidence,"data-access-en-1366.png"),fullPage:true})
  }
  const writes: string[] = []
  page.on("request", (req) => {if (!['GET','HEAD','OPTIONS'].includes(req.method())) writes.push(`${req.method()} ${new URL(req.url()).pathname}`)})
  await page.reload()
  await expect(page.getByRole("heading", {name:"Data access",exact:true})).toBeVisible()
  await page.getByRole("link", {name:"Customer asset ledger",exact:true}).first().click()
  await expect(page.getByRole("heading", {name:"Customer asset ledger",exact:true})).toBeVisible()
  expect(writes).toEqual([])
})
