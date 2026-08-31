#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SAFE_ID = /^O0[1-9][0-9]*$/u;
const SAFE_SCENARIO = /^S[1-9][0-9]*$/u;
const ALLOWED_EXECUTABLES = new Set(["bunx", "uv"]);
const ALLOWED_CWDS = new Set(["backend", "frontend"]);

function stop(code) {
  process.stderr.write(`REL-003 Oracle: FAIL (${code})\n`);
  process.exit(1);
}

if (process.argv.length !== 3) stop("oracle_argument_invalid");
const relativeArtifact = process.argv[2];
if (
  path.isAbsolute(relativeArtifact)
  || relativeArtifact.split(/[\\/]/u).includes("..")
  || !relativeArtifact.startsWith("oracles/rel-003/")
  || !relativeArtifact.endsWith(".json")
) stop("oracle_path_invalid");

let oracle;
try {
  oracle = JSON.parse(fs.readFileSync(path.join(ROOT, relativeArtifact), "utf8"));
} catch {
  stop("oracle_unreadable");
}

if (
  oracle?.schema !== "exposure-agent:rel-003-oracle:v1"
  || !SAFE_ID.test(oracle.oracleId ?? "")
  || !Array.isArray(oracle.scenarioIds)
  || oracle.scenarioIds.length === 0
  || !oracle.scenarioIds.every((id) => SAFE_SCENARIO.test(id))
  || new Set(oracle.scenarioIds).size !== oracle.scenarioIds.length
  || !Array.isArray(oracle.assertions)
  || oracle.assertions.length < 3
  || oracle.assertions.length > 8
  || !oracle.assertions.every((item) => typeof item === "string" && item.trim() === item && item.length > 0)
  || !Array.isArray(oracle.commands)
  || oracle.commands.length === 0
) stop("oracle_contract_invalid");

for (const command of oracle.commands) {
  if (
    !command
    || !ALLOWED_CWDS.has(command.cwd)
    || !Array.isArray(command.argv)
    || command.argv.length < 2
    || !ALLOWED_EXECUTABLES.has(command.argv[0])
    || !command.argv.every((item) => typeof item === "string" && item.length > 0 && !/[\u0000\r\n]/u.test(item))
  ) stop("oracle_command_invalid");
  const completed = spawnSync(command.argv[0], command.argv.slice(1), {
    cwd: path.join(ROOT, command.cwd),
    env: process.env,
    stdio: "inherit",
  });
  if (completed.error || completed.status !== 0) stop("oracle_assertion_failed");
}

process.stdout.write(`${oracle.oracleId}: PASS (${oracle.scenarioIds.join(",")})\n`);
