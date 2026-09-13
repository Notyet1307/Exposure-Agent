// Browser operates real isolated backend APIs; only the local frontend API origin is forwarded.
import { chromium, expect } from '@playwright/test'
import { readFileSync, writeFileSync } from 'node:fs'
const input = JSON.parse(readFileSync(0, 'utf8'))
const browser = await chromium.launch()
let step = 'open'
try {
  const context = await browser.newContext({ viewport: { width: 1366, height: 768 } })
  await context.addInitScript(token => {
    localStorage.setItem('access_token', token)
    localStorage.setItem('exposure:language', 'en')
    localStorage.setItem('vite-ui-theme', 'light')
  }, input.token)
  const page = await context.newPage()
  const calls = []
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const parsed = new URL(request.url())
    const response = await route.fetch({ url: input.api + parsed.pathname + parsed.search, timeout: 180000 })
    if (parsed.pathname.includes('model-connections')) calls.push({ method: request.method(), path: parsed.pathname, status: response.status() })
    await route.fulfill({ response })
  })
  await page.goto(input.ui + '/ai-settings')
  step = 'save version'
  await page.getByLabel('Connection name', { exact: true }).fill('Browser synthetic connection')
  await page.getByLabel('API base URL').fill('http://provider-a:8080/v1')
  await page.getByLabel('Model identifier').fill('model-a')
  await page.getByLabel('API Key', { exact: true }).fill(input.key)
  await page.getByRole('button', { name: 'Save pending version', exact: true }).click()
  const pending = page.getByRole('region', { name: 'Pending connection' })
  await expect(pending).toContainText('Browser synthetic connection', { timeout: 15000 })
  step = 'real Pi verification'
  await page.getByRole('button', { name: 'Verify connection', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Activate for new tasks' })).toBeEnabled({ timeout: 120000 })
  await expect(pending).toContainText('Passed')
  step = 'activate version'
  await page.getByRole('button', { name: 'Activate for new tasks' }).click()
  await expect(page.getByRole('region', { name: 'Active connection' })).toContainText('Browser synthetic connection', { timeout: 15000 })
  step = 'disable version'
  await page.getByRole('button', { name: 'Disable current connection' }).click()
  await page.getByRole('button', { name: 'Confirm revocation', exact: true }).click()
  await expect(page.getByText('No active connection.', { exact: false })).toBeVisible({ timeout: 15000 })
  step = 'secret storage check'
  const persisted = await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage }, url: location.href }))
  if (persisted.includes(input.key) || persisted.includes('http://provider-a:8080/v1')) throw new Error('forbidden model input in browser storage')
  const snapshot = await context.request.get(input.api + '/api/v1/model-connections', { headers: { Authorization: 'Bearer ' + input.token } })
  const state = await snapshot.json()
  const created = state.connections.find(v => v.name === 'Browser synthetic connection')
  if (!created?.revoked_at || state.active_id !== null) throw new Error('disabled state missing')
  writeFileSync(input.output, JSON.stringify({ status: 'PASS', connection_id: created.id, calls, key_in_storage: false, final_state: 'disabled', validation: created.validation_evidence }, null, 2))
  console.log('Real browser connection lifecycle: PASS')
} catch {
  console.error('Real browser acceptance failed at: ' + step)
  process.exitCode = 1
} finally {
  await browser.close()
}
