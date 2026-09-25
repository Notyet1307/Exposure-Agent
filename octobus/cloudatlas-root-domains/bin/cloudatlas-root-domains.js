#!/usr/bin/env node

import {
  defineService, grpcError, grpcInvalidArgumentError,
  grpcPermissionDeniedError, grpcUnauthenticatedError,
  grpcUnavailableError, runServiceMain, status,
} from "@chaitin-ai/octobus-sdk";
import { listPage } from "./source.js";

async function invoke(ctx, domain) {
  try {
    return await listPage(ctx, domain);
  } catch (error) {
    switch (error?.message) {
      case "invalid_request":
      case "invalid_source_config":
        throw grpcInvalidArgumentError(error.message);
      case "cloudatlas_authentication_failed":
        throw grpcUnauthenticatedError(error.message);
      case "cloudatlas_authorization_failed":
        throw grpcPermissionDeniedError(error.message);
      case "cloudatlas_response_contract_failed":
        throw grpcError(status.DATA_LOSS, error.message);
      case "cloudatlas_connectivity_failed":
        throw grpcUnavailableError(error.message);
      default:
        // Never expose response text, configuration, credentials, or native TLS errors.
        throw grpcUnavailableError("cloudatlas_upstream_failed");
    }
  }
}

runServiceMain(defineService({
  handlers: {
    "cloudatlas.rootdomains.v1.CloudAtlasRootDomainsService/ListRootDomains": (ctx) => invoke(ctx, "root_domain"),
  },
}));
