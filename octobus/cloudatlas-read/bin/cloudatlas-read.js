#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  defineService,
  grpcError,
  grpcInvalidArgumentError,
  grpcPermissionDeniedError,
  grpcUnauthenticatedError,
  grpcUnavailableError,
  runServiceMain,
  status as grpcStatus,
} from "@chaitin-ai/octobus-sdk";

const statuses = new Set(["valid", "await", "ignored", "invalid"]);
const CLOUDATLAS_CLI_TIMEOUT_MS = 60_000;

function cliFailure(result) {
  const detail = `${result.error?.message || ""}\n${result.stderr || ""}`.toLowerCase();
  if (/\b401\b|unauthenticated|authentication/.test(detail)) {
    return grpcUnauthenticatedError("cloudatlas_authentication_failed");
  }
  if (/\b403\b|permission denied|forbidden/.test(detail)) {
    return grpcPermissionDeniedError("cloudatlas_authorization_failed");
  }
  if (
    /timed out|timeout|etimedout|connection refused|econnrefused|connection reset|econnreset|could not connect|no such host|enotfound|network is unreachable|enetunreach|\beof\b/.test(
      detail,
    )
  ) {
    return grpcUnavailableError("cloudatlas_connectivity_failed");
  }
  return grpcUnavailableError("cloudatlas_upstream_failed");
}

function listIPAssets(ctx) {
  const requestedStatus = String(ctx.request.status || "valid");
  const page = Number(ctx.request.page || 1);
  const size = Number(ctx.request.size || 1);
  if (!statuses.has(requestedStatus)) throw grpcInvalidArgumentError("unsupported_status");
  if (!Number.isInteger(page) || page < 1) throw grpcInvalidArgumentError("invalid_page");
  if (!Number.isInteger(size) || size < 1 || size > 200) throw grpcInvalidArgumentError("invalid_size");

  const directory = mkdtempSync(join(tmpdir(), "cloudatlas-read-"));
  const configPath = join(directory, "config.json");
  let result;
  try {
    writeFileSync(
      configPath,
      JSON.stringify({
        cloudAtlas: {
          url: ctx.config.baseUrl,
          space_id: ctx.config.spaceId,
          token: ctx.secret.token,
        },
      }),
      { mode: 0o600 },
    );
    result = spawnSync(
      "chaitin-cli",
      [
        "--config",
        configPath,
        "cloudAtlas",
        "--output",
        "json",
        "--insecure=false",
        "asset",
        "ip",
        "list",
        "--status",
        requestedStatus,
        "--page",
        String(page),
        "--size",
        String(size),
      ],
      {
        encoding: "utf8",
        maxBuffer: 1024 * 1024,
        timeout: CLOUDATLAS_CLI_TIMEOUT_MS,
      },
    );
  } finally {
    rmSync(directory, { force: true, recursive: true });
  }
  if (result.error || result.status !== 0) throw cliFailure(result);

  let payload;
  try {
    payload = JSON.parse(result.stdout);
  } catch {
    throw grpcError(grpcStatus.DATA_LOSS, "cloudatlas_response_contract_failed");
  }
  if (
    !Array.isArray(payload.items) ||
    !Number.isInteger(payload.current) ||
    !Number.isInteger(payload.size) ||
    !Number.isInteger(payload.total) ||
    payload.items.some(
      (item) =>
        !Number.isInteger(item?.id) ||
        typeof item?.ip !== "string" ||
        typeof item?.status !== "string",
    )
  ) {
    throw grpcError(grpcStatus.DATA_LOSS, "cloudatlas_response_contract_failed");
  }
  return {
    items: payload.items.map(({ id, ip, status }) => ({
      id: String(id),
      ip,
      status,
    })),
    page: payload.current,
    size: payload.size,
    total: payload.total,
  };
}

const service = defineService({
  handlers: {
    "cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets": listIPAssets,
  },
});

runServiceMain(service);
