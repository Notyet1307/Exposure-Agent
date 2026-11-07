#!/usr/bin/env node
// Existing locked Playwright + Vite; only disposable source and synthetic credentials.
const fs = require('node:fs');
const path = require('node:path');
const {createRequire} = require('node:module');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const net = require('node:net');
const [source, evidence] = process.argv.slice(2);
const req = createRequire(path.join(source, 'frontend/package.json'));
const {chromium} = req('@playwright/test');
const vite = path.join(path.dirname(req.resolve('vite/package.json')), 'bin/vite.js');
const output = {status:'FAIL', actions:[]};
const apiBase = process.env.PILOT_API;
let frontend, browser, browserServer, apiToken;

function ok(condition, message) {
  if (!condition) throw Error(message);
}

async function apiLogin() {
  const response = await fetch(apiBase + '/api/v1/login/access-token', {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: new URLSearchParams({
      username: process.env.FIRST_SUPERUSER,
      password: process.env.FIRST_SUPERUSER_PASSWORD,
    }),
  });
  if (!response.ok) throw Error('API login failed: ' + response.status);
  const body = await response.json();
  if (!body.access_token) throw Error('API login returned no token');
  return body.access_token;
}

async function apiJson(method, urlPath) {
  const response = await fetch(apiBase + urlPath, {
    method,
    headers: {Authorization: 'Bearer ' + apiToken},
  });
  const text = await response.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null } catch {}
  return {status: response.status, body, text};
}

async function ledgerJourney(page, project, ledger) {
  apiToken = await apiLogin();
  const root = `/api/v1/projects/${project.id}`;
  const uploadPath = root + '/customer-uploads';
  const previewPath = root + '/customer-ledger/replacements/preview';
  const applyPath = root + '/customer-ledger/replacements';
  const ledgerPath = root + '/customer-ledger';
  const profile = await apiJson('GET', root + '/customer-upload-profile');
  ok(profile.status === 200, 'UI project profile read failed: ' + profile.status);
  const requiredHeaders = profile.body.required_headers;
  const expectedHeaders = JSON.parse(process.env.PILOT_REQUIRED_HEADERS);
  ok(JSON.stringify(requiredHeaders) === JSON.stringify(expectedHeaders),
    'UI project profile headers changed: ' + JSON.stringify(requiredHeaders));
  ledger.profile = {version: profile.body.version, required_headers: requiredHeaders};

  const posts = [];
  page.on('request', request => {
    if (request.method() !== 'POST') return;
    const type = request.headers()['content-type'] || '';
    posts.push({
      path: new URL(request.url()).pathname,
      body: type.includes('application/json') ? request.postDataJSON() : null,
    });
  });

  const uploadForm = page.locator('form').filter({has: page.getByLabel('XLSX file')});
  const upload = async file => {
    await page.getByLabel('XLSX file').setInputFiles(file);
    const [response] = await Promise.all([
      page.waitForResponse(r => r.request().method() === 'POST'
        && new URL(r.url()).pathname === uploadPath),
      uploadForm.getByRole('button', {name: 'Upload', exact: true}).click(),
    ]);
    const body = await response.json().catch(() => null);
    return {status: response.status(), body};
  };
  const listUploads = async () => {
    const result = await apiJson('GET', uploadPath);
    ok(result.status === 200, 'uploads read failed: ' + result.status);
    return result.body;
  };
  const readLedger = async () => {
    const result = await apiJson('GET', ledgerPath);
    ok(result.status === 200, 'ledger read failed: ' + result.status);
    return result.body;
  };
  const rejectedState = async stage => {
    const uploads = await listUploads();
    ok(uploads.current_customer_upload_id === null, stage + ': current upload changed');
    ok(uploads.count === 0, stage + ': rejected upload was listed');
    const current = await readLedger();
    ok(current.upload_id === null && current.current_upload_id === null, stage + ': ledger current changed');
    return {count: uploads.count, current_customer_upload_id: uploads.current_customer_upload_id};
  };
  const statusText = async text => {
    const locator = page.locator('[role="status"]').filter({hasText: text}).first();
    await locator.waitFor();
    return locator.innerText();
  };
  const shot = name => page.screenshot({path: path.join(evidence, name), fullPage: true});

  const beforeInvalidHeader = await rejectedState('before missing-header upload');
  const invalidHeader = await upload(process.env.PILOT_INVALID_HEADER_XLSX);
  ok(invalidHeader.status === 422, 'missing-header upload status ' + invalidHeader.status);
  const headerDetail = invalidHeader.body?.detail;
  ok(headerDetail?.code === 'missing_required_structure',
    'missing-header response code ' + JSON.stringify(invalidHeader.body));
  ok(headerDetail.field === 'web_url', 'missing-header field ' + JSON.stringify(headerDetail));
  const headerStatus = await statusText('The workbook is missing required structure.');
  ok(headerStatus.includes('Web URL'), 'missing-header diagnostic lacks Web URL: ' + headerStatus);
  ledger.invalid_header = {
    status: invalidHeader.status,
    detail: headerDetail,
    status_text: headerStatus,
    current_before: beforeInvalidHeader,
    current_after: await rejectedState('after missing-header upload'),
  };
  await shot('ui-05-invalid-header.png');

  const beforeInvalidPort = await rejectedState('before port-70000 upload');
  const invalidPort = await upload(process.env.PILOT_INVALID_PORT_XLSX);
  ok(invalidPort.status === 422, 'port-70000 upload status ' + invalidPort.status);
  const portDetail = invalidPort.body?.detail;
  ok(portDetail?.code === 'invalid_required_value',
    'port-70000 response code ' + JSON.stringify(invalidPort.body));
  ok(portDetail.field === 'start_port', 'port-70000 field ' + JSON.stringify(portDetail));
  ok(portDetail.reason === 'port_out_of_range', 'port-70000 reason ' + JSON.stringify(portDetail));
  ok(portDetail.limit === 65535, 'port-70000 limit ' + JSON.stringify(portDetail));
  const portStatus = await statusText('The workbook contains an invalid required value.');
  ok(portStatus.includes('Start port'), 'port diagnostic lacks Start port: ' + portStatus);
  ok(portStatus.includes('Port must be between 1 and 65535'), 'port diagnostic lacks range: ' + portStatus);
  ledger.invalid_port = {
    status: invalidPort.status,
    detail: portDetail,
    status_text: portStatus,
    current_before: beforeInvalidPort,
    current_after: await rejectedState('after port-70000 upload'),
  };
  await shot('ui-06-invalid-port.png');

  const valid = await upload(process.env.PILOT_VALID_XLSX);
  ok(valid.status === 201, 'valid upload status ' + valid.status);
  const uploadInfo = valid.body;
  ok(uploadInfo.display_filename === process.env.PILOT_VALID_FILENAME,
    'valid upload filename ' + uploadInfo.display_filename);
  ok(uploadInfo.record_count === 2, 'valid upload record_count ' + uploadInfo.record_count);
  ok(uploadInfo.profile_version === 1, 'valid upload profile version ' + uploadInfo.profile_version);
  await page.getByText('Upload accepted. Preview this file and set it as the current input.',
    {exact: true}).waitFor();
  const uploadRow = page.getByRole('row').filter({hasText: uploadInfo.display_filename});
  await uploadRow.waitFor();
  await uploadRow.getByText('Available', {exact: true}).waitFor();
  await page.getByText('Project input is not ready. Select one accepted CustomerUpload.',
    {exact: true}).waitFor();
  const afterUpload = await listUploads();
  ok(afterUpload.current_customer_upload_id === null, 'upload changed current before explicit apply');
  ok(afterUpload.count === 1 && afterUpload.data[0].id === uploadInfo.id,
    'accepted upload listing mismatch');
  const ledgerBefore = await readLedger();
  ok(ledgerBefore.upload_id === null && ledgerBefore.current_upload_id === null,
    'ledger current changed by upload');
  ok(posts.filter(item => item.path === applyPath).length === 0,
    'apply request sent before explicit apply');
  ledger.upload = {
    status: valid.status,
    upload_id: uploadInfo.id,
    raw_sha256: uploadInfo.raw_sha256,
    record_count: uploadInfo.record_count,
    profile_version: uploadInfo.profile_version,
    current_before: afterUpload.current_customer_upload_id,
    ledger_before: {upload_id: ledgerBefore.upload_id, current_upload_id: ledgerBefore.current_upload_id},
  };
  await shot('ui-07-upload-accepted.png');

  const [previewRequest, previewResponse] = await Promise.all([
    page.waitForRequest(r => r.method() === 'POST' && new URL(r.url()).pathname === previewPath),
    page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === previewPath),
    uploadRow.getByRole('button', {name: 'Preview selection', exact: true}).click(),
  ]);
  ok(previewResponse.status() === 200, 'preview status ' + previewResponse.status());
  const preview = await previewResponse.json();
  const previewBody = previewRequest.postDataJSON();
  ok(previewBody.candidate_upload_id === uploadInfo.id && previewBody.expected_upload_id === null,
    'preview request body ' + JSON.stringify(previewBody));
  ok(preview.candidate_upload_id === uploadInfo.id, 'preview candidate mismatch');
  ok(preview.current_upload_id === null, 'preview current upload not null');
  ok(preview.candidate_record_count === 2 && preview.candidate_unique_ips === 2,
    'preview candidate counts ' + JSON.stringify(preview));
  ok(preview.added_ips === 2 && preview.removed_ips === 0 && preview.changed_ip_declarations === 0,
    'preview diff counts ' + JSON.stringify(preview));
  await page.getByText('Selection preview', {exact: true}).waitFor();
  await page.getByRole('button', {name: 'Set as current input', exact: true}).waitFor();
  const afterPreview = await listUploads();
  ok(afterPreview.current_customer_upload_id === null, 'preview changed current upload');
  const ledgerAfterPreview = await readLedger();
  ok(ledgerAfterPreview.upload_id === null && ledgerAfterPreview.current_upload_id === null,
    'preview changed ledger current');
  ok(posts.filter(item => item.path === applyPath).length === 0,
    'apply request sent before explicit click');
  ledger.preview = {
    status: previewResponse.status(),
    request: previewBody,
    body: preview,
    current_after: afterPreview.current_customer_upload_id,
  };
  await shot('ui-08-selection-preview.png');

  const [applyRequest, applyResponse] = await Promise.all([
    page.waitForRequest(r => r.method() === 'POST' && new URL(r.url()).pathname === applyPath),
    page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === applyPath),
    page.getByRole('button', {name: 'Set as current input', exact: true}).click(),
  ]);
  ok(applyResponse.status() === 201, 'apply status ' + applyResponse.status());
  const applyBody = applyRequest.postDataJSON();
  const receipt = await applyResponse.json();
  ok(applyBody.candidate_upload_id === uploadInfo.id && applyBody.expected_upload_id === null,
    'apply request body ' + JSON.stringify(applyBody));
  ok(receipt.candidate_upload_id === uploadInfo.id && receipt.expected_upload_id === null,
    'apply receipt ' + JSON.stringify(receipt));
  ok(receipt.project_id === project.id, 'apply receipt project mismatch');
  await page.getByText('Selection confirmed. This file is now the current input; history is unchanged.',
    {exact: true}).waitFor();
  await uploadRow.getByText('Current', {exact: true}).waitFor();
  const afterApply = await listUploads();
  ok(afterApply.current_customer_upload_id === uploadInfo.id,
    'current upload pointer ' + afterApply.current_customer_upload_id);
  const ledgerAfterApply = await readLedger();
  ok(ledgerAfterApply.upload_id === uploadInfo.id, 'ledger upload id mismatch');
  ok(ledgerAfterApply.current_upload_id === uploadInfo.id, 'ledger current upload mismatch');
  ok(ledgerAfterApply.current_revision_id === null && ledgerAfterApply.revision === null,
    'first selection created a revision');
  ok(ledgerAfterApply.count === 2 && ledgerAfterApply.total_records === 2
    && ledgerAfterApply.unique_ips === 2,
  'ledger counts ' + JSON.stringify({
    count: ledgerAfterApply.count,
    total_records: ledgerAfterApply.total_records,
    unique_ips: ledgerAfterApply.unique_ips,
  }));
  const appliedRows = ledgerAfterApply.data || [];
  ok(appliedRows.length === 2, 'ledger rows ' + appliedRows.length);
  const byIp = Object.fromEntries(appliedRows.map(row => [row.canonical_ip, row]));
  ok(byIp['192.0.2.10'] && byIp['192.0.2.11'], 'ledger IP set ' + Object.keys(byIp));
  for (const ip of ['192.0.2.10', '192.0.2.11']) {
    const fields = byIp[ip].fields || {};
    ok(fields.start_port === 443 && fields.end_port === 443 && fields.is_web === '否'
      && fields.web_url === null,
    'ledger fields for ' + ip + ': ' + JSON.stringify(fields));
  }
  ledger.apply = {
    status: applyResponse.status(),
    request: applyBody,
    receipt,
    current_customer_upload_id: afterApply.current_customer_upload_id,
  };
  ledger.api_after_apply = {
    upload_id: ledgerAfterApply.upload_id,
    current_upload_id: ledgerAfterApply.current_upload_id,
    current_revision_id: ledgerAfterApply.current_revision_id,
    count: ledgerAfterApply.count,
    total_records: ledgerAfterApply.total_records,
    unique_ips: ledgerAfterApply.unique_ips,
    filename: ledgerAfterApply.filename,
    upload_sha256: ledgerAfterApply.upload_sha256,
    rows: appliedRows.map(row => ({
      position: row.position,
      canonical_ip: row.canonical_ip,
      fields: row.fields,
    })),
  };
  await shot('ui-09-current-applied.png');

  const ledgerResponse = page.waitForResponse(r => r.request().method() === 'GET'
    && new URL(r.url()).pathname === ledgerPath);
  await page.locator('[data-sidebar="sidebar"]')
    .getByRole('link', {name: 'Customer asset ledger', exact: true}).click();
  await page.waitForURL(url => new URL(url).pathname === `/projects/${project.id}/customer-ledger`);
  await ledgerResponse;
  await page.getByRole('heading', {name: 'Customer asset ledger', exact: true}).waitFor();
  await page.getByText('2 matching source records', {exact: true}).waitFor();
  await page.getByText(/2 active records/).first().waitFor();
  await page.getByText(/2 distinct IPs/).first().waitFor();
  const row10 = page.getByRole('row').filter({hasText: '192.0.2.10'});
  const row11 = page.getByRole('row').filter({hasText: '192.0.2.11'});
  await row10.waitFor();
  await row11.waitFor();
  const row10Text = await row10.innerText();
  const row11Text = await row11.innerText();
  ok(row10Text.includes('443') && row10Text.includes('—'), 'ledger row 10 fields: ' + row10Text);
  ok(row11Text.includes('443') && row11Text.includes('—'), 'ledger row 11 fields: ' + row11Text);
  await row10.getByRole('button', {name: 'Details', exact: true}).click();
  await page.getByRole('heading', {name: /192\.0\.2\.10.*Source record 1/}).first().waitFor();
  const detailText = await page.locator('section.workspace-record').innerText();
  for (const needle of ['Asset IP', '192.0.2.10', 'Start port', '443', 'End port', '443',
    'Web interface', '否', 'Web URL', 'Not provided']) {
    ok(detailText.includes(needle), 'ledger detail missing ' + needle + ': ' + detailText);
  }
  ledger.ui_ledger = {url: page.url(), rows: [row10Text, row11Text], detail: detailText};
  await shot('ui-10-ledger.png');

  await page.reload({waitUntil: 'networkidle'});
  await page.getByRole('heading', {name: 'Customer asset ledger', exact: true}).waitFor();
  await page.getByText('2 matching source records', {exact: true}).waitFor();
  const reloadedRow10 = page.getByRole('row').filter({hasText: '192.0.2.10'});
  const reloadedRow11 = page.getByRole('row').filter({hasText: '192.0.2.11'});
  await reloadedRow10.waitFor();
  await reloadedRow11.waitFor();
  ledger.reload = {
    url: page.url(),
    rows: [await reloadedRow10.innerText(), await reloadedRow11.innerText()],
  };
  await shot('ui-11-ledger-reloaded.png');
  ledger.status = 'PASS';
}

async function main() {
  const server = net.createServer();
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  await new Promise(r => server.close(r));
  const base = `http://127.0.0.1:${port}`;
  frontend = spawn(process.execPath, [vite, '--host', '127.0.0.1', '--port', String(port), '--strictPort'], {
    cwd: path.join(source, 'frontend'),
    env: {...process.env, API_PROXY_TARGET: process.env.PILOT_API},
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  const logfile = fs.createWriteStream(path.join(evidence, 'frontend.log'));
  frontend.stdout.pipe(logfile);
  frontend.stderr.pipe(logfile);
  output.frontend_pid = frontend.pid;
  output.frontend_port = port;
  let ready = false;
  for (let i = 0; i < 120; i++) {
    if (frontend.exitCode !== null) throw Error('Vite exited');
    try {
      if ((await fetch(base)).ok) {
        ready = true;
        break;
      }
    } catch {}
    await new Promise(r => setTimeout(r, 500));
  }
  if (!ready) throw Error('Vite not ready');
  browserServer = await chromium.launchServer({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
  });
  fs.writeFileSync(path.join(evidence, 'ui-browser-owner.json'),
    JSON.stringify({pid: browserServer.process().pid, source}) + '\n');
  browser = await chromium.connect(browserServer.wsEndpoint());
  if (process.env.PILOT_TIMEOUT_TEST === '1') await new Promise(() => {});
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
  // Browser external HTTP(S) requests are forbidden, not silently mocked.
  const forbidden = [];
  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (['http:', 'https:'].includes(u.protocol) && u.origin !== base) {
      forbidden.push(u.origin);
      return route.abort();
    }
    return route.continue();
  });
  await context.addInitScript(() => localStorage.setItem('exposure:language', 'en'));
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  await page.goto(base + '/login');
  await page.getByLabel('Email', {exact: true}).fill(process.env.FIRST_SUPERUSER);
  await page.getByLabel('Password', {exact: true}).fill(process.env.FIRST_SUPERUSER_PASSWORD);
  await page.getByRole('button', {name: 'Log In', exact: true}).click();
  await page.waitForURL(u => !u.pathname.startsWith('/login'));
  output.actions.push('Signed in through login form');
  await page.screenshot({path: path.join(evidence, 'ui-01-login.png'), fullPage: true});
  await page.goto(base + '/?view=create');
  await page.getByLabel('Project name', {exact: true}).fill('verification-ui-pilot');
  await page.screenshot({path: path.join(evidence, 'ui-02-create-form.png'), fullPage: true});
  const created = page.waitForResponse(r => r.request().method() === 'POST'
    && new URL(r.url()).pathname === '/api/v1/projects/');
  await page.getByRole('button', {name: 'Create and prepare inputs', exact: true}).click();
  const response = await created;
  if (response.status() !== 201) throw Error('UI project creation status ' + response.status());
  const project = await response.json();
  if (project.name !== 'verification-ui-pilot') throw Error('Created name mismatch');
  await page.waitForURL(u => u.searchParams.get('project') === project.id
    && u.searchParams.get('view') === 'inputs');
  output.actions.push('Created project through user form');
  output.project_id = project.id;
  await page.screenshot({path: path.join(evidence, 'ui-03-created.png'), fullPage: true});
  await page.reload({waitUntil: 'networkidle'});
  await page.getByRole('heading', {name: 'verification-ui-pilot', exact: true}).waitFor();
  if (new URL(page.url()).searchParams.get('project') !== project.id)
    throw Error('Refresh changed project');
  output.actions.push('Reload preserved project and visible name');
  await page.screenshot({path: path.join(evidence, 'ui-04-reloaded.png'), fullPage: true});
  if (process.env.PILOT_LEDGER === '1') {
    output.ledger = {status: 'FAIL', actions: []};
    await ledgerJourney(page, project, output.ledger);
    output.actions.push('Customer ledger invalid uploads, first selection, ledger and reload checked');
  }
  if (forbidden.length) throw Error('Unexpected external browser requests: ' + forbidden.join(','));
  output.blocked_external_requests = forbidden;
  output.status = 'PASS';
}
(async () => {
  try {
    await main();
  } catch (e) {
    output.reason = String(e);
  } finally {
    try {
      if (browser) await browser.close();
      if (browserServer) await browserServer.close();
    } catch (e) {
      output.status = 'FAIL';
      output.cleanup_error = String(e);
    }
    if (frontend && frontend.exitCode === null) {
      frontend.kill('SIGTERM');
      const timer = setTimeout(() => frontend.kill('SIGKILL'), 5000);
      await once(frontend, 'exit');
      clearTimeout(timer);
    }
    fs.writeFileSync(path.join(evidence, 'ui-result.json'),
      JSON.stringify(output, null, 2) + '\n');
    console.log('UI ' + output.status);
    process.exitCode = output.status === 'PASS' ? 0 : 1;
  }
})();
