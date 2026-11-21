#!/usr/bin/env node
/**
 * Read-only engineering operations dashboard generator for Cindy + Pi + pstack.
 * Aggregates:
 *   1. Cindy SQLite sessions, PR links, and active schedules (strictly read-only)
 *   2. pstack subagent JSONL transcripts (surfaces hidden subagent tokens)
 *   3. Git worktree garden cleanliness and origin/main ancestry
 *   4. Verification frozen run receipts and screenshot counts
 *   5. Cindy managed Pi version & package approval status
 *
 * Writes a single self-contained static HTML file (no server, no port binding).
 */

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

function printHelp() {
  console.log(`Usage: node scripts/pstack-ops-dashboard.mjs [options]

Options:
  --repo <path>          Target git repository root (default: git top-level or cwd)
  --cindy-dir <path>     CindyGlobal data dir (default: ~/Library/Application Support/CindyGlobal)
  --state-dir <path>     pstack state dir (default: auto-resolved from cindy-package-state.json)
  --verify-dir <path>    verify tasks dir (default: ~/ops/tasks/<repo-basename>)
  --title-match <regex>  Optional extra regex to match Cindy session titles for this project
  --out <path>           Output HTML path (default: ~/ops/dashboards/pstack-ops-dashboard.html)
  --days <n>             Include sessions/subagents updated within last N days (default: 30, 0=all)
  --json                 Print machine-readable JSON summary to stdout
  --help                 Show this message
`);
}

function parseArgs(argv) {
  const opts = {
    repo: null,
    cindyDir: process.env.CINDY_DATA_DIR || path.join(os.homedir(), "Library/Application Support/CindyGlobal"),
    stateDir: null,
    verifyDir: null,
    titleMatch: null,
    out: path.join(os.homedir(), "ops/dashboards/pstack-ops-dashboard.html"),
    days: 30,
    json: false,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--help" || arg === "-h") {
      printHelp();
      process.exit(0);
    } else if (arg === "--json") {
      opts.json = true;
    } else if (arg === "--repo" && argv[i + 1]) {
      opts.repo = argv[++i];
    } else if (arg === "--cindy-dir" && argv[i + 1]) {
      opts.cindyDir = argv[++i];
    } else if (arg === "--state-dir" && argv[i + 1]) {
      opts.stateDir = argv[++i];
    } else if (arg === "--verify-dir" && argv[i + 1]) {
      opts.verifyDir = argv[++i];
    } else if (arg === "--title-match" && argv[i + 1]) {
      opts.titleMatch = argv[++i];
    } else if (arg === "--out" && argv[i + 1]) {
      opts.out = argv[++i];
    } else if (arg === "--days" && argv[i + 1]) {
      opts.days = Number(argv[++i]);
      if (!Number.isFinite(opts.days) || opts.days < 0) {
        throw new Error(`Invalid --days value: ${argv[i]}`);
      }
    } else {
      throw new Error(`Unknown or incomplete argument: ${arg}`);
    }
  }
  return opts;
}

function safeExec(cmd, args, cwd) {
  try {
    return execFileSync(cmd, args, {
      cwd,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    }).trim();
  } catch {
    return null;
  }
}

function readJsonSafe(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return null;
  }
}

function escapeHtml(val) {
  return String(val ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function fmtNum(n) {
  if (n == null || !Number.isFinite(Number(n))) return "0";
  return Math.round(Number(n)).toLocaleString("en-US");
}

function fmtTokens(n) {
  const num = Number(n || 0);
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(2)}M`;
  if (num >= 1_000) return `${(num / 1_000).toFixed(1)}K`;
  return String(Math.round(num));
}

function fmtDate(msOrIso) {
  if (!msOrIso) return "-";
  const d = typeof msOrIso === "number" ? new Date(msOrIso) : new Date(String(msOrIso));
  if (Number.isNaN(d.getTime())) return String(msOrIso);
  return d.toISOString().replace("T", " ").slice(0, 19) + "Z";
}

function inspectRuntime(cindyDir) {
  const selectedPath = path.join(cindyDir, "pi", "selected.json");
  const pkgStatePath = path.join(cindyDir, "pi-package-home", "cindy-package-state.json");
  const selected = readJsonSafe(selectedPath);
  const pkgState = readJsonSafe(pkgStatePath);

  let piBinExists = false;
  let piBinPath = null;
  if (selected?.directory) {
    piBinPath = path.join(cindyDir, "pi", selected.directory, "pi");
    piBinExists = fs.existsSync(piBinPath);
  }

  let autoStateDir = null;
  const approved = pkgState?.approvedExtensionSources || [];
  if (approved.length > 0) {
    const extDir = path.resolve(path.join(cindyDir, "pi-package-home"), approved[0]);
    const candidateState = path.join(path.dirname(extDir), "state");
    if (fs.existsSync(candidateState)) autoStateDir = candidateState;
  }

  return {
    selectedVersion: selected?.version || null,
    selectedDirectory: selected?.directory || null,
    piBinExists,
    approvedSources: approved.length,
    disabledSources: (pkgState?.disabledSources || []).length,
    unavailablePackages: (pkgState?.snapshotUnavailablePackages || []).length,
    fingerprintPrefix: approved[0]
      ? String(pkgState?.approvedExtensionFingerprints?.[approved[0]] || "").slice(0, 12)
      : null,
    autoStateDir,
  };
}

function findCindyDb(cindyDir) {
  if (!fs.existsSync(cindyDir)) return null;
  const entries = fs.readdirSync(cindyDir);
  const match = entries.find(
    (name) =>
      name.startsWith("cindy-") &&
      name.endsWith(".db") &&
      !name.includes("lock")
  );
  return match ? path.join(cindyDir, match) : null;
}

async function queryCindyDb(dbPath, repoRoot, cutoffMs, titleMatch = null) {
  if (!dbPath || !fs.existsSync(dbPath)) {
    return { available: false, sessions: [], prRefs: [], schedules: [], parentTokensTotal: 0 };
  }

  let DatabaseSync;
  try {
    ({ DatabaseSync } = await import("node:sqlite"));
  } catch {
    return { available: false, error: "node:sqlite unavailable (requires Node >= 22.5)", sessions: [], prRefs: [], schedules: [], parentTokensTotal: 0 };
  }

  const db = new DatabaseSync(dbPath, { readOnly: true });
  try {
    const tables = new Set(
      db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all().map((r) => r.name)
    );
    if (!tables.has("sessions")) {
      return { available: false, error: "sessions table not found", sessions: [], prRefs: [], schedules: [], parentTokensTotal: 0 };
    }

    const sessionCols = new Set(db.prepare("PRAGMA table_info(sessions)").all().map((r) => r.name));
    const wanted = [
      "id",
      "title",
      "project_dir",
      "working_dir",
      "agent_kind",
      "model",
      "effort",
      "status",
      "active_turn_pid",
      "total_token_usage",
      "created_at",
      "updated_at",
    ].filter((c) => sessionCols.has(c));

    const orderCol = sessionCols.has("updated_at") ? "updated_at" : "rowid";
    const allRows = db.prepare(`SELECT ${wanted.join(", ")} FROM sessions ORDER BY ${orderCol} DESC LIMIT 500`).all();

    const repoBase = path.basename(repoRoot).toLowerCase();
    const titleRegex = titleMatch ? new RegExp(titleMatch, "i") : null;
    const sessions = allRows.filter((s) => {
      const updated = Number(s.updated_at || s.created_at || 0);
      if (cutoffMs > 0 && updated > 0 && updated < cutoffMs) return false;
      const pdir = String(s.project_dir || "");
      const wdir = String(s.working_dir || "");
      const title = String(s.title || "");
      return (
        pdir.includes(repoRoot) ||
        wdir.includes(repoRoot) ||
        pdir.toLowerCase().includes(repoBase) ||
        wdir.toLowerCase().includes(repoBase) ||
        title.toLowerCase().includes(repoBase) ||
        (titleRegex ? titleRegex.test(title) : false)
      );
    });

    const prBySession = new Map();
    let prRefs = [];
    if (tables.has("session_pr_refs")) {
      const prCols = new Set(db.prepare("PRAGMA table_info(session_pr_refs)").all().map((r) => r.name));
      const sel = ["session_id", "pr_number", "url", "owner", "repo", "last_seen_at"].filter((c) => prCols.has(c));
      prRefs = db.prepare(`SELECT ${sel.join(", ")} FROM session_pr_refs ORDER BY last_seen_at DESC LIMIT 200`).all();
      for (const pr of prRefs) {
        const list = prBySession.get(pr.session_id) || [];
        list.push(pr);
        prBySession.set(pr.session_id, list);
      }
    }

    let schedules = [];
    if (tables.has("schedules")) {
      const scCols = new Set(db.prepare("PRAGMA table_info(schedules)").all().map((r) => r.name));
      const sel = ["id", "name", "kind", "cron_expr", "target_session_id", "working_dir", "enabled", "status"].filter((c) => scCols.has(c));
      if (sel.length > 0) {
        schedules = db.prepare(`SELECT ${sel.join(", ")} FROM schedules LIMIT 100`).all();
      }
    }

    const enriched = sessions.map((s) => ({
      ...s,
      prs: prBySession.get(s.id) || [],
    }));

    const parentTokensTotal = enriched.reduce((sum, s) => sum + Number(s.total_token_usage || 0), 0);
    return {
      available: true,
      dbName: path.basename(dbPath),
      sessions: enriched,
      prRefs,
      schedules,
      parentTokensTotal,
    };
  } finally {
    db.close();
  }
}

function walkJsonlFiles(dir, out = []) {
  if (!dir || !fs.existsSync(dir)) return out;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walkJsonlFiles(full, out);
    } else if (entry.isFile() && entry.name.endsWith(".jsonl")) {
      out.push(full);
    }
  }
  return out;
}

const ROLE_LABELS = {
  verify: "验证 (Verify)",
  review: "审阅 (Review)",
  explore: "探索与设计 (Explore/Design)",
  implement: "实现 (Implement)",
  other: "其他 (Other)",
};

function classifySubagentRole(firstPrompt) {
  const text = String(firstPrompt || "").slice(0, 800);
  if (!text) return "other";
  if (
    /\b(standards-only|spec-only|independent review|fresh.*review|no-comments|comment-sicko|thermos|interrogate)\b|独立.*审阅|只读审阅|只读核查/i.test(
      text
    )
  ) {
    return "review";
  }
  if (
    /\b(verify|playwright|browser|chrome|viewport|control-|self-test|smoke|journey|doctor|oracle)\b|真实浏览器|验证|双视口|视口/i.test(
      text
    )
  ) {
    return "verify";
  }
  if (
    /\b(\/how|\/why|how explorer|how explainer|why investigator|why synthesizer|code explorer|read-only explorer|architect|prototype|design sketch)\b|只读调查|探索|原型|架构/i.test(
      text
    )
  ) {
    return "explore";
  }
  if (/\b(sole.*writer|writer|implement|refactor|bug-fix|poteto-agent)\b|实现|写入|修复/i.test(text)) {
    return "implement";
  }
  return "other";
}

function scanPstackSubagents(stateDir, cutoffMs) {
  if (!stateDir || !fs.existsSync(stateDir)) {
    return {
      available: false,
      runs: [],
      byModel: [],
      byRole: [],
      verifyReviewSharePct: 0,
      totalTokens: 0,
      totalInput: 0,
      totalOutput: 0,
      totalCacheRead: 0,
    };
  }

  const files = walkJsonlFiles(stateDir).filter((f) => f.includes(`${path.sep}pstack${path.sep}`));
  const runs = [];
  const byModelMap = new Map();
  const byRoleMap = new Map();

  for (const filePath of files) {
    let stat;
    try {
      stat = fs.statSync(filePath);
    } catch {
      continue;
    }
    if (cutoffMs > 0 && stat.mtimeMs < cutoffMs) continue;

    let raw;
    try {
      raw = fs.readFileSync(filePath, "utf8");
    } catch {
      continue;
    }

    let model = "unknown";
    let thinking = "-";
    let cwd = "";
    let firstPrompt = "";
    let messages = 0;
    let input = 0;
    let output = 0;
    let cacheRead = 0;
    let cacheWrite = 0;
    let totalTokens = 0;

    for (const line of raw.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      let obj;
      try {
        obj = JSON.parse(trimmed);
      } catch {
        continue;
      }
      if (obj.type === "session" && obj.cwd) cwd = String(obj.cwd);
      if (obj.type === "model_change" && obj.modelId) {
        model = obj.provider ? `${obj.provider}/${obj.modelId}` : String(obj.modelId);
      }
      if (obj.type === "thinking_level_change" && obj.thinkingLevel) {
        thinking = String(obj.thinkingLevel);
      }
      if (obj.type === "message") {
        messages += 1;
        if (!firstPrompt && obj.message?.role === "user") {
          const content = obj.message.content;
          if (typeof content === "string") {
            firstPrompt = content.slice(0, 800);
          } else if (Array.isArray(content)) {
            firstPrompt = content
              .map((part) => (part && typeof part.text === "string" ? part.text : ""))
              .join(" ")
              .slice(0, 800);
          }
        }
      }

      const usage = obj.usage || obj.message?.usage;
      if (usage && typeof usage === "object") {
        const uIn = Number(usage.input || 0);
        const uOut = Number(usage.output || 0);
        const uCR = Number(usage.cacheRead || 0);
        const uCW = Number(usage.cacheWrite || 0);
        const uTot = Number(usage.totalTokens || uIn + uOut + uCR + uCW);
        input += uIn;
        output += uOut;
        cacheRead += uCR;
        cacheWrite += uCW;
        totalTokens += uTot;
      }
    }

    const relParts = path.relative(stateDir, filePath).split(path.sep);
    const scopeHash = relParts[0] || "-";
    const parentSession = relParts[2] || "-";
    const role = classifySubagentRole(firstPrompt);

    runs.push({
      file: path.basename(filePath),
      scopeHash,
      parentSession: parentSession.slice(0, 12),
      cwd,
      role,
      model,
      thinking,
      messages,
      input,
      output,
      cacheRead,
      cacheWrite,
      totalTokens,
      mtimeMs: stat.mtimeMs,
    });

    const cur = byModelMap.get(model) || { model, runs: 0, input: 0, output: 0, cacheRead: 0, totalTokens: 0 };
    cur.runs += 1;
    cur.input += input;
    cur.output += output;
    cur.cacheRead += cacheRead;
    cur.totalTokens += totalTokens;
    byModelMap.set(model, cur);

    const rCur = byRoleMap.get(role) || {
      role,
      label: ROLE_LABELS[role] || role,
      runs: 0,
      input: 0,
      output: 0,
      cacheRead: 0,
      totalTokens: 0,
    };
    rCur.runs += 1;
    rCur.input += input;
    rCur.output += output;
    rCur.cacheRead += cacheRead;
    rCur.totalTokens += totalTokens;
    byRoleMap.set(role, rCur);
  }

  runs.sort((a, b) => b.mtimeMs - a.mtimeMs);
  const byModel = [...byModelMap.values()].sort((a, b) => b.totalTokens - a.totalTokens);
  const totalTokens = runs.reduce((s, r) => s + r.totalTokens, 0);
  const totalInput = runs.reduce((s, r) => s + r.input, 0);
  const totalOutput = runs.reduce((s, r) => s + r.output, 0);
  const totalCacheRead = runs.reduce((s, r) => s + r.cacheRead, 0);
  const byRole = [...byRoleMap.values()]
    .map((r) => ({
      ...r,
      sharePct: totalTokens > 0 ? Number(((r.totalTokens / totalTokens) * 100).toFixed(1)) : 0,
    }))
    .sort((a, b) => b.totalTokens - a.totalTokens);
  const verifyReviewTokens =
    (byRoleMap.get("verify")?.totalTokens || 0) + (byRoleMap.get("review")?.totalTokens || 0);
  const verifyReviewSharePct =
    totalTokens > 0 ? Number(((verifyReviewTokens / totalTokens) * 100).toFixed(1)) : 0;

  return {
    available: true,
    runs,
    byModel,
    byRole,
    verifyReviewSharePct,
    totalTokens,
    totalInput,
    totalOutput,
    totalCacheRead,
  };
}

function scanWorktrees(repoRoot) {
  const raw = safeExec("git", ["-C", repoRoot, "worktree", "list", "--porcelain"]);
  if (!raw) return [];
  const entries = [];
  let cur = {};
  for (const line of `${raw}\n`.split("\n")) {
    if (!line.trim()) {
      if (cur.path) entries.push(cur);
      cur = {};
      continue;
    }
    if (line.startsWith("worktree ")) cur.path = line.slice("worktree ".length);
    else if (line.startsWith("HEAD ")) cur.head = line.slice("HEAD ".length);
    else if (line.startsWith("branch ")) cur.branch = line.slice("branch ".length).replace("refs/heads/", "");
    else if (line === "detached") cur.detached = true;
  }

  return entries.map((wt) => {
    const exists = fs.existsSync(wt.path);
    const st = exists ? safeExec("git", ["-C", wt.path, "status", "--porcelain=v1"]) : null;
    const dirtyCount = st == null ? -1 : st ? st.split("\n").filter(Boolean).length : 0;
    const aheadRaw = wt.head ? safeExec("git", ["-C", repoRoot, "rev-list", "--count", `origin/main..${wt.head}`]) : null;
    const ahead = aheadRaw != null && /^\d+$/.test(aheadRaw) ? Number(aheadRaw) : null;
    return {
      path: wt.path,
      name: path.basename(wt.path),
      isMain: path.resolve(wt.path) === path.resolve(repoRoot),
      branch: wt.branch || (wt.detached ? "(detached)" : "-"),
      head: (wt.head || "").slice(0, 12),
      exists,
      dirtyCount,
      aheadOfMain: ahead,
    };
  });
}

function scanVerifyRuns(verifyDir) {
  if (!verifyDir || !fs.existsSync(verifyDir)) return [];
  const results = [];
  for (const taskEntry of fs.readdirSync(verifyDir, { withFileTypes: true })) {
    if (!taskEntry.isDirectory()) continue;
    const taskPath = path.join(verifyDir, taskEntry.name);
    for (const runEntry of fs.readdirSync(taskPath, { withFileTypes: true })) {
      if (!runEntry.isDirectory() || !runEntry.name.startsWith("run-")) continue;
      const runPath = path.join(taskPath, runEntry.name);
      const stat = fs.statSync(runPath);
      const frozen = readJsonSafe(path.join(runPath, "frozen-assets.json"));
      const prepareExit = fs.existsSync(path.join(runPath, "prepare.exit"))
        ? fs.readFileSync(path.join(runPath, "prepare.exit"), "utf8").trim()
        : "-";
      const checkExit = fs.existsSync(path.join(runPath, "check.exit"))
        ? fs.readFileSync(path.join(runPath, "check.exit"), "utf8").trim()
        : "-";

      const evDirs = fs
        .readdirSync(runPath, { withFileTypes: true })
        .filter((d) => d.isDirectory() && d.name.startsWith("evidence"));
      let status = "NOT_RUN";
      let cleanup = "-";
      let ui = "NOT_RUN";
      let ledger = "NOT_RUN";
      let screenshots = 0;

      for (const ev of evDirs) {
        const evPath = path.join(runPath, ev.name);
        const res = readJsonSafe(path.join(evPath, "result.json"));
        if (res) {
          status = res.status || status;
          cleanup = res.cleanup || cleanup;
          ui = res.ui || ui;
          ledger = res.ledger || ledger;
        }
        const pngs = fs.readdirSync(evPath).filter((f) => f.endsWith(".png"));
        screenshots += pngs.length;
      }

      results.push({
        taskId: taskEntry.name,
        runId: runEntry.name,
        head: frozen?.product_head ? String(frozen.product_head).slice(0, 12) : "-",
        prepareExit,
        checkExit,
        status,
        cleanup,
        ui,
        ledger,
        screenshots,
        mtimeMs: stat.mtimeMs,
      });
    }
  }
  results.sort((a, b) => b.mtimeMs - a.mtimeMs);
  return results.slice(0, 30);
}

function statusBadge(val) {
  const s = String(val || "NOT_RUN").toUpperCase();
  let cls = "muted";
  if (s === "PASS" || s === "ACTIVE" || s === "CLEAN" || s === "0") cls = "ok";
  else if (s === "FAIL" || s === "DIRTY" || s === "ERROR") cls = "err";
  else if (s === "BLOCKED" || s === "ARCHIVED" || s === "PENDING") cls = "warn";
  return `<span class="badge ${cls}">${escapeHtml(val)}</span>`;
}

function renderHtml(data) {
  const combinedTokens = data.cindy.parentTokensTotal + data.subagents.totalTokens;
  const hiddenPct =
    combinedTokens > 0
      ? ((data.subagents.totalTokens / combinedTokens) * 100).toFixed(1)
      : "0.0";
  const dirtyWorktrees = data.worktrees.filter((w) => w.dirtyCount > 0).length;
  const passVerify = data.verifyRuns.filter((v) => v.status === "PASS").length;

  const sessionRows = data.cindy.sessions
    .slice(0, 40)
    .map((s) => {
      const prLinks = (s.prs || [])
        .map((p) => `<a href="${escapeHtml(p.url)}" target="_blank" rel="noreferrer">#${escapeHtml(p.pr_number)}</a>`)
        .join(" ");
      return `<tr>
        <td>${escapeHtml(s.title || s.id)}</td>
        <td>${statusBadge(s.status || "-")}</td>
        <td><code>${escapeHtml(s.model || "-")}</code>${s.effort ? ` <span class="dim">@${escapeHtml(s.effort)}</span>` : ""}</td>
        <td class="num">${fmtTokens(s.total_token_usage)}</td>
        <td>${prLinks || "-"}</td>
        <td class="mono">${escapeHtml(fmtDate(s.updated_at || s.created_at))}</td>
      </tr>`;
    })
    .join("\n");

  const modelRows = data.subagents.byModel
    .map(
      (m) => `<tr>
        <td><code>${escapeHtml(m.model)}</code></td>
        <td class="num">${fmtNum(m.runs)}</td>
        <td class="num">${fmtTokens(m.input)}</td>
        <td class="num">${fmtTokens(m.output)}</td>
        <td class="num">${fmtTokens(m.cacheRead)}</td>
        <td class="num"><strong>${fmtTokens(m.totalTokens)}</strong></td>
      </tr>`
    )
    .join("\n");

  const roleRows = (data.subagents.byRole || [])
    .map(
      (r) => `<tr>
        <td><strong>${escapeHtml(r.label)}</strong></td>
        <td class="num">${fmtNum(r.runs)}</td>
        <td class="num">${fmtTokens(r.input)}</td>
        <td class="num">${fmtTokens(r.output)}</td>
        <td class="num">${fmtTokens(r.cacheRead)}</td>
        <td class="num"><strong>${fmtTokens(r.totalTokens)}</strong></td>
        <td class="num">${escapeHtml(r.sharePct.toFixed(1))}%</td>
      </tr>`
    )
    .join("\n");

  const subagentRows = data.subagents.runs
    .slice(0, 30)
    .map(
      (r) => `<tr>
        <td class="mono">${escapeHtml(fmtDate(r.mtimeMs))}</td>
        <td><span class="badge muted">${escapeHtml(ROLE_LABELS[r.role] || r.role || "-")}</span></td>
        <td><code>${escapeHtml(r.model)}</code> <span class="dim">@${escapeHtml(r.thinking)}</span></td>
        <td class="mono">${escapeHtml(r.parentSession)}</td>
        <td class="num">${fmtNum(r.messages)}</td>
        <td class="num">${fmtTokens(r.totalTokens)}</td>
        <td class="mono dim">${escapeHtml(r.file)}</td>
      </tr>`
    )
    .join("\n");

  const wtRows = data.worktrees
    .map(
      (w) => `<tr>
        <td><strong>${escapeHtml(w.name)}</strong>${w.isMain ? ' <span class="badge ok">main-checkout</span>' : ""}</td>
        <td><code>${escapeHtml(w.branch)}</code></td>
        <td class="mono">${escapeHtml(w.head)}</td>
        <td>${w.dirtyCount === 0 ? statusBadge("CLEAN") : statusBadge(`DIRTY (${w.dirtyCount})`)}</td>
        <td class="num">${w.aheadOfMain == null ? "-" : fmtNum(w.aheadOfMain)}</td>
      </tr>`
    )
    .join("\n");

  const verifyRows = data.verifyRuns
    .map(
      (v) => `<tr>
        <td><code>${escapeHtml(v.taskId)}</code></td>
        <td class="mono">${escapeHtml(v.runId)}</td>
        <td class="mono">${escapeHtml(v.head)}</td>
        <td>${statusBadge(v.status)}</td>
        <td>${statusBadge(v.ui)} / ${statusBadge(v.ledger)}</td>
        <td class="num">${fmtNum(v.screenshots)}</td>
        <td>${statusBadge(v.cleanup)}</td>
      </tr>`
    )
    .join("\n");

  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>pstack Ops Dashboard · ${escapeHtml(path.basename(data.repoRoot))}</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #0f1218;
    --card: #171c26;
    --border: #273042;
    --text: #e6edf3;
    --dim: #8b98ad;
    --ok: #2da44e;
    --warn: #d29922;
    --err: #f85149;
    --accent: #58a6ff;
  }
  @media (prefers-color-scheme: light) {
    :root {
      --bg: #f6f8fa;
      --card: #ffffff;
      --border: #d0d7de;
      --text: #1f2328;
      --dim: #57606a;
      --accent: #0969da;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }
  main { max-width: 1320px; margin: 0 auto; padding: 24px 20px 48px; }
  header { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: baseline; gap: 12px; margin-bottom: 20px; }
  h1 { margin: 0; font-size: 22px; }
  h2 { margin: 28px 0 10px; font-size: 16px; }
  .dim { color: var(--dim); }
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }
  .kpi { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }
  .kpi .label { color: var(--dim); font-size: 12px; }
  .kpi .val { font-size: 24px; font-weight: 700; margin-top: 4px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }
  th { font-size: 12px; color: var(--dim); font-weight: 600; white-space: nowrap; }
  tr:last-child td { border-bottom: 0; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  .badge { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; border: 1px solid transparent; }
  .badge.ok { color: var(--ok); border-color: color-mix(in srgb, var(--ok) 45%, transparent); }
  .badge.warn { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 45%, transparent); }
  .badge.err { color: var(--err); border-color: color-mix(in srgb, var(--err) 45%, transparent); }
  .badge.muted { color: var(--dim); border-color: var(--border); }
  .toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
  input[type="search"] { background: var(--card); color: var(--text); border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; width: 260px; }
</style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>Cindy + Pi + pstack 工程巡检看板</h1>
      <div class="dim">生成时间 ${escapeHtml(data.generatedAt)} · 统计窗口：最近 ${data.windowDays === 0 ? "全部" : `${data.windowDays} 天`} · 只读快照</div>
    </div>
    <div class="mono dim">Pi ${escapeHtml(data.runtime.selectedVersion || "N/A")} · 适配器指纹 ${escapeHtml(data.runtime.fingerprintPrefix || "N/A")}</div>
  </header>

  <section class="kpis">
    <div class="kpi"><div class="label">受管会话 (Cindy DB)</div><div class="val">${fmtNum(data.cindy.sessions.length)}</div><div class="dim mono">PR 关联 ${fmtNum(data.cindy.prRefs.length)} 条</div></div>
    <div class="kpi"><div class="label">父会话 Token</div><div class="val">${fmtTokens(data.cindy.parentTokensTotal)}</div><div class="dim">Cindy SQLite 记账</div></div>
    <div class="kpi"><div class="label">pstack 子代理 Token</div><div class="val">${fmtTokens(data.subagents.totalTokens)}</div><div class="dim">${fmtNum(data.subagents.runs.length)} 次子代理 · 占总计 ${escapeHtml(hiddenPct)}%</div></div>
    <div class="kpi"><div class="label">验证 + 审阅占比</div><div class="val">${escapeHtml((data.subagents.verifyReviewSharePct || 0).toFixed(1))}%</div><div class="dim">子代理 Token 投入结构（对标验证杠杆）</div></div>
    <div class="kpi"><div class="label">挂载 Worktree</div><div class="val">${fmtNum(data.worktrees.length)}</div><div class="dim">脏工作树 ${fmtNum(dirtyWorktrees)} 个</div></div>
    <div class="kpi"><div class="label">Verify 证据</div><div class="val">${fmtNum(passVerify)} / ${fmtNum(data.verifyRuns.length)}</div><div class="dim">PASS / 最近记录</div></div>
    <div class="kpi"><div class="label">Cindy Pi 运行时</div><div class="val">${escapeHtml(data.runtime.selectedVersion || "N/A")}</div><div class="dim">${data.runtime.piBinExists ? "可执行文件就位" : "未检测到二进制"} · 已批准包 ${fmtNum(data.runtime.approvedSources)}</div></div>
  </section>

  <h2>1. Worktree 花园状态</h2>
  <div class="card">
    <table>
      <thead><tr><th>目录</th><th>分支</th><th>HEAD</th><th>状态</th><th class="num">领先 origin/main</th></tr></thead>
      <tbody>${wtRows || '<tr><td colspan="5" class="dim">无记录</td></tr>'}</tbody>
    </table>
  </div>

  <h2>2. pstack 子代理模型与 Token 汇总（补齐 Cindy 记账盲区）</h2>
  <div class="card">
    <table>
      <thead><tr><th>模型</th><th class="num">子代理次数</th><th class="num">Input</th><th class="num">Output</th><th class="num">CacheRead</th><th class="num">Total</th></tr></thead>
      <tbody>${modelRows || '<tr><td colspan="6" class="dim">无子代理 JSONL 记录</td></tr>'}</tbody>
    </table>
  </div>

  <h2>2b. pstack 子代理阶段 / 角色 Token 分布</h2>
  <div class="card">
    <table>
      <thead><tr><th>角色分类</th><th class="num">子代理次数</th><th class="num">Input</th><th class="num">Output</th><th class="num">CacheRead</th><th class="num">Total</th><th class="num">占比</th></tr></thead>
      <tbody>${roleRows || '<tr><td colspan="7" class="dim">无子代理 JSONL 记录</td></tr>'}</tbody>
    </table>
  </div>

  <div class="toolbar">
    <h2>3. Cindy 项目会话（${escapeHtml(path.basename(data.repoRoot))}，最近 40 条）</h2>
    <input id="sessionFilter" type="search" placeholder="筛选会话标题 / 模型 / 状态..." />
  </div>
  <div class="card">
    <table id="sessionTable">
      <thead><tr><th>标题</th><th>状态</th><th>模型</th><th class="num">父 Token</th><th>关联 PR</th><th>更新时间</th></tr></thead>
      <tbody>${sessionRows || '<tr><td colspan="6" class="dim">未检测到 Cindy SQLite 或无匹配会话</td></tr>'}</tbody>
    </table>
  </div>

  <h2>4. 最近 pstack 子代理执行记录（最近 30 条）</h2>
  <div class="card">
    <table>
      <thead><tr><th>时间</th><th>角色</th><th>模型 / 思考档</th><th>父会话</th><th class="num">消息数</th><th class="num">Token</th><th>Transcript</th></tr></thead>
      <tbody>${subagentRows || '<tr><td colspan="7" class="dim">无记录</td></tr>'}</tbody>
    </table>
  </div>

  <h2>5. 运行验证证据（${escapeHtml(path.basename(data.repoRoot))}，最近 30 次）</h2>
  <div class="card">
    <table>
      <thead><tr><th>Task ID</th><th>Run ID</th><th>HEAD</th><th>结果</th><th>UI / Ledger</th><th class="num">截图数</th><th>清理</th></tr></thead>
      <tbody>${verifyRows || '<tr><td colspan="7" class="dim">无验证记录</td></tr>'}</tbody>
    </table>
  </div>
</main>
<script>
  const input = document.getElementById("sessionFilter");
  const rows = Array.from(document.querySelectorAll("#sessionTable tbody tr"));
  if (input) {
    input.addEventListener("input", () => {
      const q = input.value.trim().toLowerCase();
      for (const tr of rows) {
        tr.style.display = !q || tr.textContent.toLowerCase().includes(q) ? "" : "none";
      }
    });
  }
</script>
</body>
</html>
`;
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const scriptDir = path.dirname(fileURLToPath(import.meta.url));
  const repoRoot = path.resolve(
    opts.repo ||
      safeExec("git", ["rev-parse", "--show-toplevel"]) ||
      safeExec("git", ["rev-parse", "--show-toplevel"], scriptDir) ||
      process.cwd()
  );
  const cutoffMs = opts.days > 0 ? Date.now() - opts.days * 86_400_000 : 0;

  const runtime = inspectRuntime(opts.cindyDir);
  const stateDir = opts.stateDir || runtime.autoStateDir;
  const verifyDir = opts.verifyDir || path.join(os.homedir(), "ops/tasks", path.basename(repoRoot));
  const dbPath = findCindyDb(opts.cindyDir);

  const cindy = await queryCindyDb(dbPath, repoRoot, cutoffMs, opts.titleMatch);
  const subagents = scanPstackSubagents(stateDir, cutoffMs);
  const worktrees = scanWorktrees(repoRoot);
  const verifyRuns = scanVerifyRuns(verifyDir);

  const data = {
    generatedAt: new Date().toISOString(),
    windowDays: opts.days,
    repoRoot,
    runtime,
    cindy,
    subagents,
    worktrees,
    verifyRuns,
  };

  const outPath = path.resolve(opts.out);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, renderHtml(data), "utf8");

  const combined = cindy.parentTokensTotal + subagents.totalTokens;
  const summary = {
    status: "PASS",
    out_html: outPath,
    generated_at: data.generatedAt,
    window_days: opts.days,
    runtime_pi_version: runtime.selectedVersion,
    cindy_db_available: cindy.available,
    cindy_sessions: cindy.sessions.length,
    cindy_parent_tokens: cindy.parentTokensTotal,
    pstack_subagent_runs: subagents.runs.length,
    pstack_subagent_tokens: subagents.totalTokens,
    hidden_subagent_share_pct:
      combined > 0 ? Number(((subagents.totalTokens / combined) * 100).toFixed(1)) : 0,
    verify_review_share_pct: subagents.verifyReviewSharePct,
    subagent_by_role: subagents.byRole.map((r) => ({
      role: r.role,
      runs: r.runs,
      tokens: r.totalTokens,
      share_pct: r.sharePct,
    })),
    worktrees_total: worktrees.length,
    worktrees_dirty: worktrees.filter((w) => w.dirtyCount > 0).length,
    verify_runs_scanned: verifyRuns.length,
    verify_pass_count: verifyRuns.filter((v) => v.status === "PASS").length,
  };

  if (opts.json) {
    console.log(JSON.stringify(summary, null, 2));
  } else {
    console.log(`Dashboard written: ${outPath}`);
    console.log(
      `Sessions=${summary.cindy_sessions} ParentTokens=${fmtTokens(summary.cindy_parent_tokens)} ` +
        `Subagents=${summary.pstack_subagent_runs} SubagentTokens=${fmtTokens(summary.pstack_subagent_tokens)} (${summary.hidden_subagent_share_pct}%) ` +
        `VerifyReview=${summary.verify_review_share_pct}% ` +
        `Worktrees=${summary.worktrees_total} (dirty=${summary.worktrees_dirty}) VerifyPass=${summary.verify_pass_count}/${summary.verify_runs_scanned}`
    );
  }
}

main().catch((err) => {
  console.error(err?.stack || String(err));
  process.exit(1);
});
