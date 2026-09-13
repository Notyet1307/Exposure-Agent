// Uses real backend replies in an owned synthetic stack; only forwards the API origin.
import { chromium, expect } from '@playwright/test'
import { readFileSync, writeFileSync } from 'node:fs'
const input=JSON.parse(readFileSync(0,'utf8'))
const browser=await chromium.launch()
let step='open fixed Run'
try {
  const context=await browser.newContext({viewport:{width:1366,height:768}})
  await context.addInitScript(token=>{localStorage.setItem('access_token',token);localStorage.setItem('exposure:language','en')},input.token)
  const page=await context.newPage(); const calls=[]; const replies=[]
  await page.route('**/api/v1/**',async route=>{
    const request=route.request(),url=new URL(request.url())
    const response=await route.fetch({url:input.api+url.pathname+url.search,timeout:180000})
    if(request.method()!=='GET') {
      calls.push({method:request.method(),path:url.pathname,status:response.status()})
      try {replies.push({path:url.pathname,body:await response.json()})} catch {}
    }
    await route.fulfill({response})
  })
  const {project_id:project,run_id:run,resource_id:resource}=input.fixture
  await page.goto(input.ui+`/?project=${project}&run=${run}&view=overview`)
  await expect(page.getByRole('region',{name:'AI workspace for this Run'})).toBeVisible({timeout:15000})
  await expect(page.getByText('Available',{exact:true})).toBeVisible()
  await page.reload()
  await page.getByRole('link',{name:'Browse assets and investigations'}).click()
  await page.locator(`a[href*="resource_id=${resource}"]`).first().click()
  await page.getByRole('navigation',{name:'Asset workflow'}).getByRole('link',{name:'AI investigation',exact:true}).click()
  await expect(page.locator('#ai-investigation-title')).toBeFocused()
  if(calls.length)throw new Error('navigation started a task')
  step='real investigation'
  const investigations=page.getByRole('region',{name:'AI investigation',exact:true})
  await investigations.getByRole('button',{name:'Investigate this asset',exact:true}).click()
  await expect(investigations.getByLabel('Follow-up question',{exact:true})).toBeEnabled({timeout:120000})
  const first=replies.find(r=>r.path.endsWith('/ai-investigations'))?.body
  if(!first?.id)throw new Error('investigation receipt missing')
  const before=calls.length
  await investigations.getByRole('button',{name:'Which evidence supports this difference?',exact:true}).click()
  if(calls.length!==before)throw new Error('shortcut submitted automatically')
  step='real follow-up'
  await investigations.getByRole('button',{name:'Submit follow-up',exact:true}).click()
  await expect.poll(()=>replies.filter(r=>r.path.endsWith('/followups')).at(-1)?.body?.id).toBeTruthy()
  const child=replies.filter(r=>r.path.endsWith('/followups')).at(-1).body
  await expect(page.locator('#followup-'+child.id)).toBeEnabled({timeout:120000})
  step='manual record'
  await page.getByRole('navigation',{name:'Asset workflow'}).getByRole('link',{name:'Manual record',exact:true}).click()
  const manual=page.getByRole('region',{name:'Manual review',exact:true})
  await manual.getByLabel('Manual conclusion',{exact:true}).fill('Synthetic workflow observation; no finding closure requested.')
  await manual.getByLabel('Items to verify',{exact:true}).fill('Verify against a later fixed Run.')
  await manual.getByRole('button',{name:'Save manual record',exact:true}).click()
  await expect(manual.getByText('Synthetic workflow observation; no finding closure requested.',{exact:true})).toBeVisible({timeout:15000})
  step='Run analysis report'
  await page.getByRole('navigation',{name:'Asset workflow'}).getByRole('link',{name:"This Run's report"}).click()
  await expect(page.locator('#analysis-reports-title')).toBeFocused()
  const reports=page.getByRole('region',{name:'AI analysis reports',exact:true})
  await reports.getByRole('button',{name:'Generate new analysis draft',exact:true}).click()
  await expect.poll(()=>replies.filter(r=>r.path.endsWith('/analysis-reports')).at(-1)?.body?.id).toBeTruthy()
  const report=replies.filter(r=>r.path.endsWith('/analysis-reports')).at(-1).body
  await reports.getByLabel('Analysis version',{exact:true}).selectOption(report.id)
  await expect(reports.getByRole('button',{name:'Edit narrative',exact:true})).toBeEnabled({timeout:120000})
  await reports.getByRole('button',{name:'Edit narrative',exact:true}).click()
  await reports.getByLabel('Business summary',{exact:true}).fill('Synthetic human-edited interpretation of the fixed Run.')
  await reports.getByRole('button',{name:'Save narrative',exact:true}).click()
  await expect(reports.getByRole('button',{name:'Confirm this version',exact:true})).toBeEnabled({timeout:15000})
  await reports.getByRole('button',{name:'Confirm this version',exact:true}).click()
  await expect(reports.getByRole('button',{name:'Edit narrative',exact:true})).toHaveCount(0)
  const auth={Authorization:'Bearer '+input.token}
  const result=await (await context.request.get(input.api+`/api/v1/projects/${project}/analysis-reports/${report.id}`,{headers:auth})).json()
  if(result.status!=='CONFIRMED' || result.original_output.text.business_summary===result.text.business_summary)throw new Error('original/edit/confirmation not separated')
  if(result.run_id!==run || !result.connection_version_id)throw new Error('report lost fixed identity')
  const investigation=await (await context.request.get(input.api+`/api/v1/projects/${project}/ai-investigations/${first.id}`,{headers:auth})).json()
  if(investigation.status!=='COMPLETED' || investigation.resource_id!==resource || investigation.run_id!==run || !investigation.connection_version_id)throw new Error('investigation identity not fixed')
  writeFileSync(input.output,JSON.stringify({status:'PASS',navigation_posts:0,shortcut_posts:0,investigation:first.id,report:report.id,report_status:result.status,original_preserved:true,connection_version:result.connection_version_id,calls},null,2))
  console.log('Real bounded AI workflow: PASS')
} catch (error) {
  const message=String(error).replaceAll(input.token,'[REDACTED]')
  writeFileSync(input.output.replace('.json','-failure.json'),JSON.stringify({step,message},null,2))
  console.error('Real AI workflow failed at: '+step)
  process.exitCode=1
} finally {await browser.close()}
