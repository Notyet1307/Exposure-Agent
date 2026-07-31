#!/usr/bin/env node

import { readFileSync } from "node:fs";

function option(name, fallback = undefined) {
  const index = process.argv.indexOf(name);
  if (index === -1 || index + 1 >= process.argv.length) return fallback;
  return process.argv[index + 1];
}

const configPath = option("--config");
const status = option("--status", "valid");
const page = option("--page", "1");
const size = option("--size", "1");
if (!configPath) process.exit(2);

const config = JSON.parse(readFileSync(configPath, "utf8")).cloudAtlas;
const endpoint = new URL("/openapi/v1/asset/ip", config.url);
endpoint.searchParams.set("space_id", config.space_id);
endpoint.searchParams.set("status", status);
endpoint.searchParams.set("page", page);
endpoint.searchParams.set("size", size);

try {
  const response = await fetch(endpoint, { headers: { TOKEN: config.token } });
  const body = await response.text();
  if (!response.ok) {
    console.error(`CloudAtlas HTTP ${response.status}`);
    process.exit(1);
  }
  process.stdout.write(body);
} catch {
  console.error("CloudAtlas connection refused");
  process.exit(1);
}
