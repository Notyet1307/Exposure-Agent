// Uses real backend replies in an owned synthetic stack; only forwards the API origin.
import { chromium, expect } from '@playwright/test'
import { readFileSync, writeFileSync } from 'node:fs'
import {createServer, request as httpRequest} from 'node:http'
import {createHash} from 'node:crypto'
const input=JSON.parse(readFileSync(0,'utf8'))
// Serve the unchanged Compose frontend over loopback so secure-context APIs work.
// This is only a local acceptance transport, not a product ingress override.
let proxy
if(input.create_published_run) {
  const upstream=new URL(input.ui)
  proxy=createServer((request,response)=>{
    const forwarded=httpRequest(new URL(request.url,upstream),{method:request.method,headers:{...request.headers,host:upstream.host}},result=>{
      response.writeHead(result.statusCode,result.headers);result.pipe(response)
    })
    forwarded.on('error',()=>{response.writeHead(502);response.end()})
    request.pipe(forwarded)
  })
  await new Promise(resolve=>proxy.listen(0,'127.0.0.1',resolve))
  input.ui='http://127.0.0.1:'+proxy.address().port
}
const browser=await chromium.launch()
let step='open fixed Run'
let page
const calls=[]
try {
  const context=await browser.newContext({viewport:{width:1366,height:768}})
  await context.addInitScript(token=>{localStorage.setItem('access_token',token);localStorage.setItem('exposure:language','en')},input.token)
  page=await context.newPage(); const replies=[]
  if(input.create_published_run) page.on('response',async response=>{
    const request=response.request(),url=new URL(response.url())
    if(url.pathname.startsWith('/api/v1/')&&request.method()!=='GET') {
      calls.push({method:request.method(),path:url.pathname,status:response.status()})
      try {replies.push({path:url.pathname,body:await response.json()})} catch {}
    }
  })
  else await page.route('**/api/v1/**',async route=>{
    const request=route.request(),url=new URL(request.url())
    const response=await route.fetch({url:input.api+url.pathname+url.search,timeout:180000})
    if(request.method()!=='GET') {
      calls.push({method:request.method(),path:url.pathname,status:response.status()})
      try {replies.push({path:url.pathname,body:await response.json()})} catch {}
    }
    await route.fulfill({response})
  })
  let fixture=input.fixture
  let creationPublicationCalls=[]
  if(input.create_published_run) {
    step='create and publish a real Run'
    const fixtureResponse=await context.request.post('http://cloudatlas-fixture:18080/fixture/set-assets',{data:{items:[{id:46,ip:'192.0.2.46',status:'valid'}]}})
    if(!fixtureResponse.ok())throw new Error('fixture assets were not configured')
    await page.goto(input.ui+'/')
    await page.getByRole('link',{name:'New comparison project'}).last().click()
    const name='EXP-UX-04 chain '+crypto.randomUUID()
    await page.getByLabel('Project name',{exact:true}).fill(name)
    await page.getByRole('button',{name:'Create and prepare inputs'}).click()
    await expect(page).toHaveURL(/view=inputs/)
    const project=new URL(page.url()).searchParams.get('project')
    if(!project)throw new Error('project creation did not fix scope')
    await page.getByLabel('XLSX file').setInputFiles(input.workbook)
    await page.locator('form').filter({has:page.getByLabel('XLSX file')}).getByRole('button',{name:'Upload',exact:true}).click()
    const upload=page.getByRole('row').filter({hasText:'first-comparison.xlsx'})
    await expect(upload).toBeVisible({timeout:15000})
    await upload.getByRole('button',{name:'Set as current input'}).click()
    await page.getByLabel('NetFlow dataset file').setInputFiles({name:'present.csv',mimeType:'text/csv',buffer:Buffer.from('IP_SRC_ADDR,IP_DST_ADDR,PROTOCOL,L4_SRC_PORT,L4_DST_PORT\n192.0.2.20,192.0.2.46,6,443,80\n')})
    await page.getByRole('button',{name:'Upload',exact:true}).last().click()
    await page.getByRole('button',{name:'Select present.csv as current NetFlowDataset',exact:true}).click()
    await page.getByRole('link',{name:'CloudAtlas',exact:true}).click()
    await page.getByLabel('OctoBus Instance ID').fill('cloudatlas-fixture')
    await page.getByLabel('Read-only Capset ID').fill('cloudatlas-readonly')
    await page.getByRole('button',{name:'Save binding'}).click()
    await page.getByLabel('Capset token',{exact:true}).fill(input.cloudatlas_capset_token)
    await page.getByRole('button',{name:'Validate source'}).click()
    await page.getByRole('button',{name:'Enable source'}).click()
    await page.getByRole('link',{name:'Inputs',exact:true}).click()
    await page.getByRole('link',{name:'Review inputs and start'}).click()
    await page.getByLabel('Use these versions for this comparison').check()
    await page.getByRole('button',{name:'Trigger Run',exact:true}).click()
    await expect(page).toHaveURL(/view=overview/,{timeout:120000})
    const run=new URL(page.url()).searchParams.get('run')
    if(!run)throw new Error('published overview did not fix Run')
    const auth={Authorization:'Bearer '+input.token}
    const runs=await (await context.request.get(input.api+`/api/v1/projects/${project}/governance-runs`,{headers:auth})).json()
    if(!runs.data.some(item=>item.id===run&&item.published))throw new Error('Run was not published')
    const comparisons=await (await context.request.get(input.api+`/api/v1/projects/${project}/governance-runs/${run}/ip-source-comparisons`,{headers:auth})).json()
    const resource=comparisons.data.at(0)?.resource_id
    if(!resource)throw new Error('published Run has no comparison resource')
    fixture={project_id:project,run_id:run,resource_id:resource}
    creationPublicationCalls=calls.slice()
    calls.splice(0);replies.splice(0)
  }
  const {project_id:project,run_id:run,resource_id:resource}=fixture
  const findingSnapshot=async()=>{
    const response=await context.request.get(input.api+`/api/v1/projects/${project}/findings?limit=100`,{headers:{Authorization:'Bearer '+input.token}})
    if(response.status()!==200)throw new Error('Finding readback failed')
    const data=await response.json()
    if(data.count>100)throw new Error('Finding snapshot truncated')
    return createHash('sha256').update(JSON.stringify(data.data.sort((a,b)=>a.id.localeCompare(b.id)))).digest('hex')
  }
  const findingBefore=input.create_published_run?await findingSnapshot():null
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
  if(result.run_id!==run || result.connection_version_id!==input.connection_version)throw new Error('report lost fixed identity')
  const investigation=await (await context.request.get(input.api+`/api/v1/projects/${project}/ai-investigations/${first.id}`,{headers:auth})).json()
  if(investigation.status!=='COMPLETED' || investigation.resource_id!==resource || investigation.run_id!==run || investigation.connection_version_id!==input.connection_version)throw new Error('investigation identity not fixed')
  const findingAfter=input.create_published_run?await findingSnapshot():null
  if(findingBefore!==findingAfter)throw new Error('AI workflow changed Finding facts')
  await page.unrouteAll({behavior:'wait'})
  writeFileSync(input.output,JSON.stringify({finding_before: findingBefore,finding_after: findingAfter,status:'PASS',project_id:project,run_id:run,resource_id:resource,navigation_posts:0,shortcut_posts:0,creation_publication_calls:creationPublicationCalls,investigation:first.id,report:report.id,report_status:result.status,original_preserved:true,connection_version:result.connection_version_id,calls},null,2))
  console.log('Real bounded AI workflow: PASS')
} catch (error) {
  const message=String(error).replaceAll(input.token,'[REDACTED]')
  writeFileSync(input.output.replace('.json','-failure.json'),JSON.stringify({step,message,calls,visible_text:page?(await page.locator('body').innerText()).slice(0,4000):null},null,2))
  console.error('Real AI workflow failed at: '+step)
  process.exitCode=1
} finally {await browser.close();if(proxy){proxy.closeAllConnections();await new Promise(resolve=>proxy.close(resolve))}}
