#!/usr/bin/env node
/**
 * Generic, project-agnostic agent-friendly browser control CLI (Build the Lever).
 *
 * Designed for inner-loop development debugging, bug reproduction, and UI prototyping
 * across any web project. Keeps one isolated headless Chromium instance alive via a
 * loopback control daemon bound to a per-session directory and Bearer token.
 *
 * Zero extra npm dependencies: resolves Playwright from the target project's locked
 * package.json (`--playwright-from`) or local module search path.
 *
 * Exit codes: 0 = PASS, 1 = FAIL, 2 = BLOCKED (missing runtime / invalid usage).
 */

import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const SELF_PATH = fileURLToPath(import.meta.url);

const CHROME_CANDIDATES = [
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
];

const VIEWPORT_PRESETS = {
  desktop: { width: 1280, height: 844 },
  wide: { width: 1440, height: 1000 },
  tablet: { width: 768, height: 1024 },
  mobile: { width: 390, height: 844 },
};

function printHelp() {
  console.log(`Usage: node web-control.mjs <command> [options]

Generic agent-friendly browser control CLI for inner-loop debugging and prototyping.
All commands print machine-readable JSON to stdout.

Commands:
  doctor      Read-only check of Chrome, Playwright, target URL, and session status
  start       Launch isolated headless Chrome + loopback control daemon
  status      Report live URL, title, viewport, console/network counters, and PID
  goto        Navigate to a path (relative to base URL) or full URL
  viewport    Resize viewport (<width> <height> or --preset desktop|wide|tablet|mobile)
  snapshot    Capture Playwright ARIA accessibility snapshot + interactive summary
  click       Click element by --role/--name, --text, --testid, or --selector
  fill        Fill input by --label, --testid, --placeholder, or --selector
  press       Press a keyboard key (e.g. Escape, Enter, Meta+KeyK)
  upload      Set file(s) on a file input by --label or --selector
  wait        Wait for --text, --selector, --url-contains, --network-idle, or --ms
  screenshot  Save PNG screenshot to <outPath> (--full-page, --selector)
  console     Read captured browser console messages and uncaught page errors
  network     Read captured HTTP requests (--failures-only, --clear, --limit)
  eval        Evaluate a JS expression in the page and return JSON result
  batch       Execute a JSON array of commands from <file> (supports --dry-run)
  stop        Stop only this session's owned Chrome + daemon (never deletes evidence)
  self-test   Run an end-to-end self-test against a local synthetic page

Common options:
  --session-dir <dir>       Session state dir (default: $WEB_CONTROL_SESSION_DIR or /tmp/web-control-default)
  --playwright-from <path>  Path to project package.json providing @playwright/test or playwright
  --dry-run                 Preview side-effecting action without executing (start, batch, stop)
  --help, -h                Show this help text
`);
}

function outJson(obj, exitCode = 0) {
  process.stdout.write(JSON.stringify(obj, null, 2) + "\n");
  process.exitCode = exitCode;
}

function resolveChrome() {
  const override = process.env.WEB_CONTROL_CHROME_BIN || process.env.PILOT_CHROME_BIN;
  if (override && fs.existsSync(override)) return override;
  for (const candidate of CHROME_CANDIDATES) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return null;
}

function resolvePlaywrightModule(playwrightFrom) {
  const roots = [];
  if (playwrightFrom) {
    const resolved = path.resolve(playwrightFrom);
    roots.push(fs.statSync(resolved).isDirectory() ? path.join(resolved, "package.json") : resolved);
  }
  const cwd = process.cwd();
  for (const rel of ["package.json", "frontend/package.json", "web/package.json", "app/package.json"]) {
    const p = path.join(cwd, rel);
    if (fs.existsSync(p)) roots.push(p);
  }
  roots.push(SELF_PATH);

  const tried = [];
  for (const anchor of roots) {
    try {
      const req = createRequire(anchor);
      for (const pkg of ["@playwright/test", "playwright", "playwright-core"]) {
        try {
          const mod = req(pkg);
          if (mod && mod.chromium) {
            return { chromium: mod.chromium, packageName: pkg, resolvedFrom: anchor };
          }
        } catch {
          tried.push(`${pkg}@${anchor}`);
        }
      }
    } catch {
      tried.push(anchor);
    }
  }
  const err = new Error(
    `Playwright not found. Pass --playwright-from <path/to/package.json> pointing to a workspace with @playwright/test or playwright installed.`
  );
  err.code = "PLAYWRIGHT_MISSING";
  err.tried = tried.slice(0, 6);
  throw err;
}

function parseViewport(raw, preset) {
  if (preset) {
    const found = VIEWPORT_PRESETS[preset];
    if (!found) {
      throw new Error(`Unknown --preset "${preset}". Valid presets: ${Object.keys(VIEWPORT_PRESETS).join(", ")}`);
    }
    return { ...found };
  }
  if (!raw) return { ...VIEWPORT_PRESETS.desktop };
  const m = /^(\d+)x(\d+)$/i.exec(String(raw).trim());
  if (!m) {
    throw new Error(`Invalid viewport "${raw}". Expected "<width>x<height>" (e.g. 1280x844) or --preset.`);
  }
  return { width: Number(m[1]), height: Number(m[2]) };
}

function parseFlags(argv) {
  const flags = {};
  const positionals = [];
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--") {
      positionals.push(...argv.slice(i + 1));
      break;
    }
    if (arg.startsWith("--")) {
      const eq = arg.indexOf("=");
      if (eq !== -1) {
        const key = arg.slice(2, eq);
        const val = arg.slice(eq + 1);
        appendFlag(flags, key, val);
      } else {
        const key = arg.slice(2);
        const next = argv[i + 1];
        if (next !== undefined && !next.startsWith("--")) {
          appendFlag(flags, key, next);
          i += 1;
        } else {
          appendFlag(flags, key, true);
        }
      }
    } else if (arg === "-h") {
      flags.help = true;
    } else {
      positionals.push(arg);
    }
  }
  return { flags, positionals };
}

function appendFlag(flags, key, val) {
  if (key in flags) {
    flags[key] = Array.isArray(flags[key]) ? [...flags[key], val] : [flags[key], val];
  } else {
    flags[key] = val;
  }
}

function asArray(val) {
  if (val === undefined || val === null) return [];
  return Array.isArray(val) ? val : [val];
}

function getSessionDir(flags) {
  return path.resolve(
    String(flags["session-dir"] || process.env.WEB_CONTROL_SESSION_DIR || path.join(os.tmpdir(), "web-control-default"))
  );
}

function sessionFilePath(sessionDir) {
  return path.join(sessionDir, "session.json");
}

function readSession(sessionDir) {
  const file = sessionFilePath(sessionDir);
  if (!fs.existsSync(file)) return null;
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function isPidAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function rpcCall(session, action, payload = {}) {
  const res = await fetch(`${session.control_url}/action`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${session.token}`,
    },
    body: JSON.stringify({ action, payload }),
  });
  const text = await res.text();
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    throw new Error(`Invalid daemon response (${res.status}): ${text.slice(0, 300)}`);
  }
  if (!res.ok || body.status === "FAIL") {
    const err = new Error(body.error || `Daemon action "${action}" failed with HTTP ${res.status}`);
    err.daemonResponse = body;
    throw err;
  }
  return body;
}

function requireActiveSession(sessionDir) {
  const session = readSession(sessionDir);
  if (!session) {
    const err = new Error(
      `No active session in ${sessionDir}. Run: node web-control.mjs start --url <baseUrl> --session-dir "${sessionDir}"`
    );
    err.code = "NO_SESSION";
    throw err;
  }
  if (!isPidAlive(session.pid)) {
    const err = new Error(
      `Session daemon (pid=${session.pid}) is no longer running. Run "stop" to clear stale session.json, then "start" again.`
    );
    err.code = "STALE_SESSION";
    throw err;
  }
  return session;
}

async function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const addr = srv.address();
      const port = typeof addr === "object" && addr ? addr.port : 0;
      srv.close(() => resolve(port));
    });
  });
}

async function runDaemon(configPath) {
  const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
  const { chromium } = resolvePlaywrightModule(config.playwrightFrom);
  const chromeBin = config.chromeBin || resolveChrome();
  const launchOpts = { headless: true };
  if (chromeBin) launchOpts.executablePath = chromeBin;

  const browser = await chromium.launch(launchOpts);
  const context = await browser.newContext({
    viewport: config.viewport,
    locale: config.locale || undefined,
  });

  const baseOrigin = new URL(config.baseUrl).origin;
  const blockedExternal = [];
  if (config.blockExternal) {
    await context.route("**/*", (route) => {
      const url = route.request().url();
      try {
        const parsed = new URL(url);
        if ((parsed.protocol === "http:" || parsed.protocol === "https:") && parsed.origin !== baseOrigin) {
          blockedExternal.push(parsed.origin);
          return route.abort();
        }
      } catch {}
      return route.continue();
    });
  }

  if (config.initStorage && Object.keys(config.initStorage).length > 0) {
    await context.addInitScript((entries) => {
      for (const [k, v] of Object.entries(entries)) {
        try {
          window.localStorage.setItem(k, String(v));
        } catch {}
      }
    }, config.initStorage);
  }

  const page = await context.newPage();
  page.setDefaultTimeout(config.defaultTimeoutMs || 15000);

  const consoleEvents = [];
  const networkEvents = [];
  const reqTimings = new WeakMap();

  page.on("console", (msg) => {
    consoleEvents.push({
      ts: new Date().toISOString(),
      level: msg.type(),
      text: msg.text(),
    });
    if (consoleEvents.length > 500) consoleEvents.shift();
  });
  page.on("pageerror", (err) => {
    consoleEvents.push({
      ts: new Date().toISOString(),
      level: "pageerror",
      text: String(err),
    });
    if (consoleEvents.length > 500) consoleEvents.shift();
  });
  page.on("request", (req) => {
    reqTimings.set(req, Date.now());
  });
  page.on("response", (res) => {
    const req = res.request();
    const started = reqTimings.get(req);
    let pathname = res.url();
    try {
      const u = new URL(res.url());
      pathname = u.pathname + u.search;
    } catch {}
    networkEvents.push({
      ts: new Date().toISOString(),
      method: req.method(),
      pathname,
      status: res.status(),
      ok: res.ok(),
      duration_ms: started ? Date.now() - started : null,
    });
    if (networkEvents.length > 500) networkEvents.shift();
  });
  page.on("requestfailed", (req) => {
    let pathname = req.url();
    try {
      const u = new URL(req.url());
      pathname = u.pathname + u.search;
    } catch {}
    networkEvents.push({
      ts: new Date().toISOString(),
      method: req.method(),
      pathname,
      status: 0,
      ok: false,
      failure: req.failure()?.errorText || "requestfailed",
      duration_ms: null,
    });
    if (networkEvents.length > 500) networkEvents.shift();
  });

  function resolveLocator(p) {
    let loc;
    if (p.role) {
      const opts = {};
      if (p.name !== undefined) opts.name = String(p.name);
      if (p.exact) opts.exact = true;
      loc = page.getByRole(String(p.role), opts);
    } else if (p.label !== undefined) {
      loc = page.getByLabel(String(p.label), { exact: Boolean(p.exact) });
    } else if (p.testid !== undefined) {
      loc = page.getByTestId(String(p.testid));
    } else if (p.placeholder !== undefined) {
      loc = page.getByPlaceholder(String(p.placeholder), { exact: Boolean(p.exact) });
    } else if (p.text !== undefined) {
      loc = page.getByText(String(p.text), { exact: Boolean(p.exact) });
    } else if (p.selector !== undefined) {
      loc = page.locator(String(p.selector));
    } else {
      throw new Error(
        "Target locator missing. Pass one of: --role/--name, --label, --testid, --placeholder, --text, or --selector."
      );
    }
    if (p.index !== undefined) {
      loc = loc.nth(Number(p.index));
    }
    return loc;
  }

  let shuttingDown = false;
  let idleTimer = null;
  const idleMs = Math.max(60, Number(config.idleTimeoutSec || 1800)) * 1000;

  async function shutdown() {
    if (shuttingDown) return;
    shuttingDown = true;
    if (idleTimer) clearTimeout(idleTimer);
    try {
      await context.close();
    } catch {}
    try {
      await browser.close();
    } catch {}
    try {
      server.close();
    } catch {}
    setTimeout(() => process.exit(0), 50).unref();
  }

  function bumpIdle() {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      shutdown();
    }, idleMs);
    idleTimer.unref();
  }

  async function dispatch(action, p = {}) {
    bumpIdle();
    const timeout = p.timeout ? Number(p.timeout) : undefined;
    switch (action) {
      case "status": {
        const vp = page.viewportSize();
        return {
          status: "PASS",
          pid: process.pid,
          url: page.url(),
          title: await page.title(),
          viewport: vp,
          console_total: consoleEvents.length,
          console_errors: consoleEvents.filter((e) => e.level === "error" || e.level === "pageerror").length,
          network_total: networkEvents.length,
          network_failures: networkEvents.filter((e) => !e.ok).length,
          blocked_external_count: blockedExternal.length,
        };
      }
      case "goto": {
        const target = String(p.target || "/");
        const url = /^https?:\/\//i.test(target) ? target : new URL(target, config.baseUrl).toString();
        const waitUntil = p.waitUntil || "load";
        const resp = await page.goto(url, { waitUntil, timeout });
        return {
          status: "PASS",
          url: page.url(),
          http_status: resp ? resp.status() : null,
          title: await page.title(),
        };
      }
      case "viewport": {
        const vp = parseViewport(p.viewport, p.preset);
        await page.setViewportSize(vp);
        return { status: "PASS", viewport: vp };
      }
      case "snapshot": {
        const root = p.selector ? page.locator(String(p.selector)).first() : page.locator("body");
        let aria = "";
        if (typeof root.ariaSnapshot === "function") {
          aria = await root.ariaSnapshot({ timeout });
        } else {
          aria = await root.innerText({ timeout });
        }
        const maxChars = Number(p.maxChars || 12000);
        const truncated = aria.length > maxChars;
        const summary = await page.evaluate(() => {
          const visible = (el) => {
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
          };
          const pick = (sel, limit = 30) =>
            Array.from(document.querySelectorAll(sel))
              .filter(visible)
              .slice(0, limit)
              .map((el) => ({
                tag: el.tagName.toLowerCase(),
                role: el.getAttribute("role") || null,
                testid: el.getAttribute("data-testid") || null,
                text: (el.innerText || el.getAttribute("aria-label") || el.getAttribute("placeholder") || "")
                  .trim()
                  .replace(/\s+/g, " ")
                  .slice(0, 120),
              }));
          return {
            headings: pick("h1,h2,h3,[role='heading']", 20),
            buttons: pick("button,[role='button']", 30),
            links: pick("a[href],[role='link']", 30),
            inputs: pick("input,textarea,select", 20),
            scroll_height: document.documentElement.scrollHeight,
            viewport_height: window.innerHeight,
          };
        });
        return {
          status: "PASS",
          url: page.url(),
          title: await page.title(),
          viewport: page.viewportSize(),
          truncated,
          aria_snapshot: truncated ? aria.slice(0, maxChars) + "\n... [truncated]" : aria,
          summary,
        };
      }
      case "click": {
        const loc = resolveLocator(p);
        await loc.click({ timeout });
        return { status: "PASS", url: page.url() };
      }
      case "fill": {
        const loc = resolveLocator(p);
        await loc.fill(String(p.value ?? ""), { timeout });
        return { status: "PASS", url: page.url() };
      }
      case "press": {
        await page.keyboard.press(String(p.key));
        return { status: "PASS", key: String(p.key), url: page.url() };
      }
      case "upload": {
        const loc = resolveLocator(p);
        const filePath = path.resolve(String(p.file));
        if (!fs.existsSync(filePath)) throw new Error(`Upload file not found: ${filePath}`);
        await loc.setInputFiles(filePath, { timeout });
        return { status: "PASS", file: filePath };
      }
      case "wait": {
        if (p.networkIdle) {
          await page.waitForLoadState("networkidle", { timeout });
        }
        if (p.text) {
          await page.getByText(String(p.text), { exact: Boolean(p.exact) }).first().waitFor({ timeout });
        }
        if (p.selector) {
          await page.locator(String(p.selector)).first().waitFor({ timeout });
        }
        if (p.urlContains) {
          await page.waitForURL((u) => u.toString().includes(String(p.urlContains)), { timeout });
        }
        if (p.ms) {
          await page.waitForTimeout(Number(p.ms));
        }
        return { status: "PASS", url: page.url() };
      }
      case "screenshot": {
        const outPath = path.resolve(String(p.outPath));
        fs.mkdirSync(path.dirname(outPath), { recursive: true });
        if (p.selector) {
          await page.locator(String(p.selector)).first().screenshot({ path: outPath, timeout });
        } else {
          await page.screenshot({ path: outPath, fullPage: Boolean(p.fullPage), timeout });
        }
        const stat = fs.statSync(outPath);
        return {
          status: "PASS",
          path: outPath,
          bytes: stat.size,
          url: page.url(),
          viewport: page.viewportSize(),
        };
      }
      case "console": {
        const level = String(p.level || "all");
        const limit = Number(p.limit || 100);
        const filtered =
          level === "all"
            ? consoleEvents.slice(-limit)
            : consoleEvents
                .filter((e) => e.level === level || (level === "error" && e.level === "pageerror"))
                .slice(-limit);
        if (p.clear) consoleEvents.length = 0;
        return { status: "PASS", count: filtered.length, events: filtered };
      }
      case "network": {
        const limit = Number(p.limit || 100);
        const base = p.failuresOnly ? networkEvents.filter((e) => !e.ok) : networkEvents;
        const slice = base.slice(-limit);
        if (p.clear) networkEvents.length = 0;
        return { status: "PASS", count: slice.length, events: slice, blocked_external: [...new Set(blockedExternal)] };
      }
      case "eval": {
        const expr = String(p.expression || "");
        const result = await page.evaluate((code) => {
          // eslint-disable-next-line no-new-func
          return new Function(`return (${code})`)();
        }, expr);
        return { status: "PASS", result };
      }
      case "batch": {
        const steps = Array.isArray(p.steps) ? p.steps : [];
        const results = [];
        for (let idx = 0; idx < steps.length; idx += 1) {
          const step = steps[idx];
          const res = await dispatch(step.action, step.payload || step);
          results.push({ index: idx, action: step.action, ...res });
        }
        return { status: "PASS", count: results.length, results };
      }
      case "stop": {
        setTimeout(() => shutdown(), 20).unref();
        return { status: "PASS", stopped_pid: process.pid };
      }
      default:
        throw new Error(`Unknown daemon action: ${action}`);
    }
  }

  const server = http.createServer(async (req, res) => {
    if (req.method !== "POST" || req.url !== "/action") {
      res.writeHead(404, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ status: "FAIL", error: "Not found" }));
      return;
    }
    if (req.headers.authorization !== `Bearer ${config.token}`) {
      res.writeHead(403, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ status: "FAIL", error: "Forbidden" }));
      return;
    }
    let raw = "";
    for await (const chunk of req) raw += chunk;
    try {
      const { action, payload } = JSON.parse(raw || "{}");
      const result = await dispatch(action, payload || {});
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(result));
    } catch (err) {
      res.writeHead(400, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ status: "FAIL", error: err?.message || String(err) }));
    }
  });

  await new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(config.port, "127.0.0.1", resolve);
  });

  const sessionMeta = {
    pid: process.pid,
    control_url: `http://127.0.0.1:${config.port}`,
    token: config.token,
    base_url: config.baseUrl,
    viewport: config.viewport,
    chrome_bin: chromeBin,
    started_at: new Date().toISOString(),
  };
  fs.writeFileSync(sessionFilePath(config.sessionDir), JSON.stringify(sessionMeta, null, 2) + "\n", { mode: 0o600 });
  bumpIdle();

  process.on("SIGTERM", () => shutdown());
  process.on("SIGINT", () => shutdown());
}

async function cmdDoctor(flags) {
  const sessionDir = getSessionDir(flags);
  const chromeBin = resolveChrome();
  let playwrightInfo = null;
  let playwrightError = null;
  try {
    const mod = resolvePlaywrightModule(flags["playwright-from"]);
    playwrightInfo = { package: mod.packageName, resolved_from: mod.resolvedFrom };
  } catch (err) {
    playwrightError = err.message;
  }

  let urlCheck = null;
  if (flags.url) {
    try {
      const resp = await fetch(String(flags.url));
      urlCheck = { url: String(flags.url), reachable: true, http_status: resp.status };
    } catch (err) {
      urlCheck = { url: String(flags.url), reachable: false, error: String(err.message || err) };
    }
  }

  const session = readSession(sessionDir);
  let sessionState = { active: false, session_dir: sessionDir };
  if (session) {
    const alive = isPidAlive(session.pid);
    sessionState = {
      active: alive,
      stale: !alive,
      pid: session.pid,
      base_url: session.base_url,
      session_dir: sessionDir,
    };
  }

  const ok = Boolean(playwrightInfo) && (!urlCheck || urlCheck.reachable);
  return {
    status: ok ? "PASS" : playwrightInfo ? "FAIL" : "BLOCKED",
    node: process.version,
    chrome_bin: chromeBin,
    playwright: playwrightInfo || { error: playwrightError },
    url_check: urlCheck,
    session: sessionState,
  };
}

async function cmdStart(flags) {
  const baseUrl = flags.url;
  if (!baseUrl) {
    throw new Error('Missing required "--url <baseUrl>". Example: start --url http://127.0.0.1:5173');
  }
  const sessionDir = getSessionDir(flags);
  const viewport = parseViewport(flags.viewport, flags.preset);
  const initStorage = {};
  for (const item of asArray(flags["init-storage"])) {
    const eq = String(item).indexOf("=");
    if (eq === -1) throw new Error(`Invalid --init-storage "${item}". Expected key=value.`);
    initStorage[item.slice(0, eq)] = item.slice(eq + 1);
  }

  const plan = {
    session_dir: sessionDir,
    base_url: String(baseUrl),
    viewport,
    locale: flags.locale ? String(flags.locale) : null,
    block_external: Boolean(flags["block-external"]),
    init_storage_keys: Object.keys(initStorage),
    playwright_from: flags["playwright-from"] ? path.resolve(String(flags["playwright-from"])) : null,
  };

  if (flags["dry-run"]) {
    return { status: "PASS", dry_run: true, plan };
  }

  const existing = readSession(sessionDir);
  if (existing && isPidAlive(existing.pid)) {
    throw new Error(
      `Session already active in ${sessionDir} (pid=${existing.pid}, base_url=${existing.base_url}). Run "stop" first or pass a distinct --session-dir.`
    );
  }

  // Validate Playwright up front so errors are crisp.
  resolvePlaywrightModule(flags["playwright-from"]);

  fs.mkdirSync(sessionDir, { recursive: true, mode: 0o700 });
  const port = await findFreePort();
  const token = crypto.randomBytes(24).toString("hex");
  const cfgPath = path.join(sessionDir, "daemon-config.json");
  const logPath = path.join(sessionDir, "daemon.log");

  fs.writeFileSync(
    cfgPath,
    JSON.stringify(
      {
        sessionDir,
        baseUrl: String(baseUrl),
        port,
        token,
        viewport,
        locale: flags.locale ? String(flags.locale) : null,
        blockExternal: Boolean(flags["block-external"]),
        initStorage,
        chromeBin: resolveChrome(),
        playwrightFrom: flags["playwright-from"] ? path.resolve(String(flags["playwright-from"])) : null,
        idleTimeoutSec: Number(flags["idle-timeout-sec"] || 1800),
        defaultTimeoutMs: Number(flags.timeout || 15000),
      },
      null,
      2
    ) + "\n",
    { mode: 0o600 }
  );

  // Remove stale session.json if prior daemon died.
  const sFile = sessionFilePath(sessionDir);
  if (fs.existsSync(sFile)) fs.unlinkSync(sFile);

  const outFd = fs.openSync(logPath, "a");
  const child = spawn(process.execPath, [SELF_PATH, "--_daemon", cfgPath], {
    detached: true,
    stdio: ["ignore", outFd, outFd],
  });
  child.unref();
  fs.closeSync(outFd);

  const deadline = Date.now() + 25000;
  while (Date.now() < deadline) {
    if (fs.existsSync(sFile)) {
      try {
        const meta = JSON.parse(fs.readFileSync(sFile, "utf8"));
        if (meta.pid && isPidAlive(meta.pid)) {
          const st = await rpcCall(meta, "status", {});
          return {
            status: "PASS",
            session_dir: sessionDir,
            pid: meta.pid,
            base_url: meta.base_url,
            viewport: meta.viewport,
            chrome_bin: meta.chrome_bin,
            daemon_log: logPath,
            page: st,
          };
        }
      } catch {}
    }
    if (!isPidAlive(child.pid)) {
      const logTail = fs.existsSync(logPath) ? fs.readFileSync(logPath, "utf8").slice(-800) : "";
      throw new Error(`Daemon exited prematurely. Log tail:\n${logTail}`);
    }
    await new Promise((r) => setTimeout(r, 150));
  }
  throw new Error(`Timed out waiting for daemon in ${sessionDir}. Inspect ${logPath}`);
}

async function cmdStop(flags) {
  const sessionDir = getSessionDir(flags);
  const session = readSession(sessionDir);
  if (flags["dry-run"]) {
    return {
      status: "PASS",
      dry_run: true,
      session_dir: sessionDir,
      would_stop_pid: session?.pid || null,
      alive: session ? isPidAlive(session.pid) : false,
    };
  }
  if (!session) {
    return { status: "PASS", session_dir: sessionDir, message: "No active session to stop." };
  }
  const pid = session.pid;
  if (isPidAlive(pid)) {
    try {
      await rpcCall(session, "stop", {});
    } catch {
      try {
        process.kill(pid, "SIGTERM");
      } catch {}
    }
    const deadline = Date.now() + 8000;
    while (Date.now() < deadline && isPidAlive(pid)) {
      await new Promise((r) => setTimeout(r, 100));
    }
    if (isPidAlive(pid)) {
      try {
        process.kill(pid, "SIGKILL");
      } catch {}
    }
  }
  const sFile = sessionFilePath(sessionDir);
  if (fs.existsSync(sFile)) fs.unlinkSync(sFile);
  const exited = !isPidAlive(pid);
  return {
    status: exited ? "PASS" : "FAIL",
    session_dir: sessionDir,
    stopped_pid: pid,
    exited,
  };
}

async function runSelfTest(flags) {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "web-control-selftest-"));
  const sessionDir = path.join(tmpDir, "session");
  const shotPath = path.join(tmpDir, "evidence", "selftest.png");
  let server;
  let startedPid = null;
  try {
    server = http.createServer((req, res) => {
      if (req.url === "/api/ping") {
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ok: true }));
        return;
      }
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(`<!doctype html>
<html>
<head><title>Web Control Self-Test</title></head>
<body>
  <h1>Self-Test Surface</h1>
  <label for="name-input">Item name</label>
  <input id="name-input" data-testid="name-input" />
  <button id="go-btn" type="button">Apply</button>
  <p id="out" role="status">idle</p>
  <script>
    document.getElementById('go-btn').addEventListener('click', async () => {
      const val = document.getElementById('name-input').value;
      await fetch('/api/ping');
      document.getElementById('out').textContent = 'applied:' + val;
      console.log('self-test-clicked:' + val);
    });
  </script>
</body>
</html>`);
    });
    const port = await findFreePort();
    await new Promise((resolve) => server.listen(port, "127.0.0.1", resolve));
    const baseUrl = `http://127.0.0.1:${port}`;

    const doc = await cmdDoctor({ url: baseUrl, "session-dir": sessionDir, "playwright-from": flags["playwright-from"] });
    if (doc.status !== "PASS") throw new Error(`doctor failed: ${JSON.stringify(doc)}`);

    const started = await cmdStart({
      url: baseUrl,
      "session-dir": sessionDir,
      "playwright-from": flags["playwright-from"],
      preset: "desktop",
      "block-external": true,
    });
    startedPid = started.pid;
    const session = requireActiveSession(sessionDir);

    await rpcCall(session, "goto", { target: "/", waitUntil: "networkidle" });
    const snap = await rpcCall(session, "snapshot", {});
    if (!snap.aria_snapshot.includes("Self-Test Surface")) {
      throw new Error("ARIA snapshot did not capture heading");
    }
    await rpcCall(session, "fill", { label: "Item name", value: "alpha" });
    await rpcCall(session, "click", { role: "button", name: "Apply", exact: true });
    await rpcCall(session, "wait", { text: "applied:alpha" });
    await rpcCall(session, "viewport", { preset: "mobile" });
    const shot = await rpcCall(session, "screenshot", { outPath: shotPath, fullPage: true });
    const logs = await rpcCall(session, "console", {});
    const netLog = await rpcCall(session, "network", {});
    const stopped = await cmdStop({ "session-dir": sessionDir });

    const shotSurvived = fs.existsSync(shotPath) && fs.statSync(shotPath).size > 0;
    const hasLog = logs.events.some((e) => e.text.includes("self-test-clicked:alpha"));
    const hasPing = netLog.events.some((e) => e.pathname === "/api/ping" && e.status === 200);
    const pidGone = !isPidAlive(startedPid);
    const passed = stopped.status === "PASS" && shotSurvived && hasLog && hasPing && pidGone;

    return {
      status: passed ? "PASS" : "FAIL",
      doctor: doc.status,
      aria_snapshot_ok: true,
      viewport_switch_ok: shot.viewport?.width === 390,
      console_capture_ok: hasLog,
      network_capture_ok: hasPing,
      screenshot_bytes: shot.bytes,
      screenshot_survived_stop: shotSurvived,
      daemon_exited: pidGone,
    };
  } finally {
    if (startedPid && isPidAlive(startedPid)) {
      await cmdStop({ "session-dir": sessionDir }).catch(() => {});
    }
    if (server) server.close();
  }
}

async function main() {
  const argv = process.argv.slice(2);
  if (argv[0] === "--_daemon") {
    await runDaemon(argv[1]);
    return;
  }
  if (argv.length === 0 || argv[0] === "--help" || argv[0] === "-h") {
    printHelp();
    return;
  }

  const command = argv[0];
  const { flags, positionals } = parseFlags(argv.slice(1));
  if (flags.help) {
    printHelp();
    return;
  }

  try {
    if (command === "doctor") {
      const res = await cmdDoctor(flags);
      outJson(res, res.status === "PASS" ? 0 : res.status === "BLOCKED" ? 2 : 1);
      return;
    }
    if (command === "start") {
      const res = await cmdStart(flags);
      outJson(res, 0);
      return;
    }
    if (command === "stop") {
      const res = await cmdStop(flags);
      outJson(res, res.status === "PASS" ? 0 : 1);
      return;
    }
    if (command === "self-test") {
      const res = await runSelfTest(flags);
      outJson(res, res.status === "PASS" ? 0 : 1);
      return;
    }

    const sessionDir = getSessionDir(flags);
    const session = requireActiveSession(sessionDir);

    let res;
    switch (command) {
      case "status":
        res = await rpcCall(session, "status", {});
        break;
      case "goto":
        res = await rpcCall(session, "goto", {
          target: positionals[0] || flags.url || "/",
          waitUntil: flags["wait-until"] || "load",
          timeout: flags.timeout,
        });
        break;
      case "viewport": {
        const raw = positionals.length >= 2 ? `${positionals[0]}x${positionals[1]}` : positionals[0] || flags.size;
        res = await rpcCall(session, "viewport", { viewport: raw, preset: flags.preset });
        break;
      }
      case "snapshot":
        res = await rpcCall(session, "snapshot", {
          selector: flags.selector,
          maxChars: flags["max-chars"],
          timeout: flags.timeout,
        });
        break;
      case "click":
        res = await rpcCall(session, "click", {
          role: flags.role,
          name: flags.name,
          text: flags.text,
          testid: flags.testid,
          selector: flags.selector,
          exact: Boolean(flags.exact),
          index: flags.index,
          timeout: flags.timeout,
        });
        break;
      case "fill":
        res = await rpcCall(session, "fill", {
          label: flags.label,
          testid: flags.testid,
          placeholder: flags.placeholder,
          selector: flags.selector,
          value: flags.value !== undefined ? flags.value : positionals[0],
          exact: Boolean(flags.exact),
          index: flags.index,
          timeout: flags.timeout,
        });
        break;
      case "press":
        if (!positionals[0] && !flags.key) throw new Error("Missing key. Example: press Escape");
        res = await rpcCall(session, "press", { key: positionals[0] || flags.key });
        break;
      case "upload":
        if (!flags.file) throw new Error("Missing --file <path>.");
        res = await rpcCall(session, "upload", {
          label: flags.label,
          selector: flags.selector,
          file: flags.file,
          exact: Boolean(flags.exact),
          timeout: flags.timeout,
        });
        break;
      case "wait":
        res = await rpcCall(session, "wait", {
          text: flags.text,
          selector: flags.selector,
          urlContains: flags["url-contains"],
          ms: flags.ms,
          networkIdle: Boolean(flags["network-idle"]),
          exact: Boolean(flags.exact),
          timeout: flags.timeout,
        });
        break;
      case "screenshot": {
        const outPath = positionals[0] || flags.out;
        if (!outPath) throw new Error("Missing screenshot output path. Example: screenshot /tmp/proof.png");
        res = await rpcCall(session, "screenshot", {
          outPath,
          fullPage: Boolean(flags["full-page"]),
          selector: flags.selector,
          timeout: flags.timeout,
        });
        break;
      }
      case "console":
        res = await rpcCall(session, "console", {
          level: flags.level || "all",
          clear: Boolean(flags.clear),
          limit: flags.limit,
        });
        break;
      case "network":
        res = await rpcCall(session, "network", {
          failuresOnly: Boolean(flags["failures-only"]),
          clear: Boolean(flags.clear),
          limit: flags.limit,
        });
        break;
      case "eval": {
        const expr = positionals[0] || flags.expr;
        if (!expr) throw new Error("Missing JS expression. Example: eval 'document.title'");
        res = await rpcCall(session, "eval", { expression: expr });
        break;
      }
      case "batch": {
        const file = positionals[0] || flags.file;
        if (!file) throw new Error("Missing steps JSON file. Example: batch steps.json");
        const steps = JSON.parse(fs.readFileSync(path.resolve(String(file)), "utf8"));
        if (!Array.isArray(steps)) throw new Error("Batch file must contain a JSON array of step objects.");
        if (flags["dry-run"]) {
          outJson({ status: "PASS", dry_run: true, count: steps.length, steps }, 0);
          return;
        }
        res = await rpcCall(session, "batch", { steps });
        break;
      }
      default:
        outJson(
          {
            status: "BLOCKED",
            error: `Unknown command "${command}". Run "node web-control.mjs --help" for supported subcommands.`,
          },
          2
        );
        return;
    }
    outJson(res, 0);
  } catch (err) {
    const code = err?.code === "PLAYWRIGHT_MISSING" || err?.code === "NO_SESSION" ? 2 : 1;
    outJson(
      {
        status: code === 2 ? "BLOCKED" : "FAIL",
        error: err?.message || String(err),
      },
      code
    );
  }
}

main();
