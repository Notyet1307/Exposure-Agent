#!/usr/bin/env node
/**
 * Thin Exposure-Agent adapter over the generic `scripts/web-control.mjs` kernel.
 *
 * Pre-wires Exposure's locked Playwright workspace (`frontend/package.json`), default
 * language storage (`exposure:language`), external-request blocking, and a `login`
 * helper while forwarding every generic subcommand unchanged.
 */

import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(SCRIPT_DIR, "..");
const WEB_CONTROL = path.join(SCRIPT_DIR, "web-control.mjs");
const FRONTEND_PKG = path.join(REPO_ROOT, "frontend", "package.json");

function printHelp() {
  console.log(`Usage: node scripts/control-exposure.mjs <command> [options]

Thin Exposure-Agent inner-loop browser control CLI (delegates to generic web-control.mjs).

Exposure shortcuts:
  login       Sign in via /login using --email/--password (or FIRST_SUPERUSER / FIRST_SUPERUSER_PASSWORD)
  start       Defaults to --playwright-from frontend/package.json, --block-external, --init-storage exposure:language=en

Forwarded generic commands:
  doctor, start, status, goto, viewport, snapshot, click, fill, press, upload,
  wait, screenshot, console, network, eval, batch, stop, self-test

Examples:
  node scripts/control-exposure.mjs self-test
  node scripts/control-exposure.mjs start --url http://127.0.0.1:5173 --preset desktop
  node scripts/control-exposure.mjs login
  node scripts/control-exposure.mjs snapshot
  node scripts/control-exposure.mjs viewport --preset mobile
  node scripts/control-exposure.mjs screenshot /tmp/mobile-check.png --full-page
  node scripts/control-exposure.mjs stop
`);
}

function hasFlag(args, name) {
  return args.some((a) => a === `--${name}` || a.startsWith(`--${name}=`));
}

function getFlagValue(args, name) {
  for (let i = 0; i < args.length; i += 1) {
    if (args[i] === `--${name}` && args[i + 1] && !args[i + 1].startsWith("--")) {
      return args[i + 1];
    }
    if (args[i].startsWith(`--${name}=`)) {
      return args[i].slice(name.length + 3);
    }
  }
  return null;
}

function runCore(args, { capture = false } = {}) {
  const result = spawnSync(process.execPath, [WEB_CONTROL, ...args], {
    stdio: capture ? ["ignore", "pipe", "pipe"] : "inherit",
    encoding: "utf8",
  });
  return result;
}

function main() {
  const argv = process.argv.slice(2);
  if (argv.length === 0 || argv[0] === "--help" || argv[0] === "-h") {
    printHelp();
    return;
  }

  const command = argv[0];
  const rest = argv.slice(1);
  const commonSession = hasFlag(rest, "session-dir")
    ? []
    : ["--session-dir", process.env.EXPOSURE_CONTROL_SESSION_DIR || "/tmp/exposure-control-default"];

  if (command === "login") {
    const email = getFlagValue(rest, "email") || process.env.FIRST_SUPERUSER;
    const password = getFlagValue(rest, "password") || process.env.FIRST_SUPERUSER_PASSWORD;
    if (!email || !password) {
      process.stdout.write(
        JSON.stringify(
          {
            status: "BLOCKED",
            error: "Missing credentials. Pass --email/--password or set FIRST_SUPERUSER and FIRST_SUPERUSER_PASSWORD.",
          },
          null,
          2
        ) + "\n"
      );
      process.exitCode = 2;
      return;
    }
    const sessionArgs = hasFlag(rest, "session-dir")
      ? ["--session-dir", getFlagValue(rest, "session-dir")]
      : commonSession;

    const steps = [
      ["goto", "/login", "--wait-until", "networkidle", ...sessionArgs],
      ["fill", "--label", "Email", "--exact", "--value", email, ...sessionArgs],
      ["fill", "--label", "Password", "--exact", "--value", password, ...sessionArgs],
      ["click", "--role", "button", "--name", "Log In", "--exact", ...sessionArgs],
      ["wait", "--network-idle", "--ms", "300", ...sessionArgs],
      ["status", ...sessionArgs],
    ];
    let lastOut = "";
    for (const step of steps) {
      const r = runCore(step, { capture: true });
      if (r.status !== 0) {
        process.stdout.write(r.stdout || JSON.stringify({ status: "FAIL", error: r.stderr || "login step failed" }) + "\n");
        process.exitCode = r.status || 1;
        return;
      }
      lastOut = r.stdout;
    }
    let parsed = {};
    try {
      parsed = JSON.parse(lastOut);
    } catch {}
    const signedIn = parsed.url && !new URL(parsed.url).pathname.startsWith("/login");
    process.stdout.write(
      JSON.stringify(
        {
          status: signedIn ? "PASS" : "FAIL",
          signed_in: Boolean(signedIn),
          url: parsed.url || null,
          title: parsed.title || null,
        },
        null,
        2
      ) + "\n"
    );
    process.exitCode = signedIn ? 0 : 1;
    return;
  }

  const extra = [...commonSession];
  if ((command === "start" || command === "doctor" || command === "self-test") && !hasFlag(rest, "playwright-from")) {
    extra.push("--playwright-from", FRONTEND_PKG);
  }
  if (command === "start") {
    if (!hasFlag(rest, "block-external") && !hasFlag(rest, "allow-external")) {
      extra.push("--block-external");
    }
    if (!hasFlag(rest, "init-storage")) {
      const lang = getFlagValue(rest, "lang") || "en";
      extra.push("--init-storage", `exposure:language=${lang}`);
    }
  }

  // Strip wrapper-only flags before forwarding.
  const forwarded = [];
  for (let i = 0; i < rest.length; i += 1) {
    if (rest[i] === "--allow-external") continue;
    if (rest[i] === "--lang") {
      i += 1;
      continue;
    }
    if (rest[i].startsWith("--lang=")) continue;
    forwarded.push(rest[i]);
  }

  const r = runCore([command, ...forwarded, ...extra]);
  process.exitCode = r.status ?? 1;
}

main();
