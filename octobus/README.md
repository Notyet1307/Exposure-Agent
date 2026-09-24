# Exposure-Agent OctoBus packages

`cloudatlas-read/` is the product-owned, single-method read-only Service Package. Its accepted OctoBus import hashes and selected method are pinned in `cloudatlas-read.hashes.json`; the backend rejects validation when the live Package, Descriptor, Instance, Capset, token bindings, or selected method no longer match the canonical fingerprint material.

`cloudatlas-assets/` is the independent `assets-v1` package. Its separate
`cloudatlas-assets.hashes.json` pins exactly
`cloudatlas.assets.v1.CloudAtlasAssetsService/ListIPAssets` and
`cloudatlas.assets.v1.CloudAtlasAssetsService/ListPortServices`. It does not
replace the legacy package, descriptor, fields or IP filter.

Run the deterministic public-Connect acceptance stack with:

```bash
./scripts/test-cloudatlas-fixture.sh
```

The delivered OctoBus image pins its Node base image, `@chaitin-ai/octobus@0.1.0` and the architecture-specific release archive SHA-256 for the real `chaitin-cli@v2606.0.4`. Both packages are baked into that image, and the production Compose stack imports them idempotently before starting the backend, so a source checkout mount or separate package-provisioning step is not required.

The fixture stack uses that same image, imports the product package, binds one fixture Instance to a Capset with `include_all_methods=false`, selects only `cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets`, and exercises the exact Service Package → real CLI → fixture upstream read-only GET chain. It uses test-only tokens and does not contact a real CloudAtlas; the authorized real-environment read-only [canary](../docs/runbooks/cloudatlas-canary.md) remains a deployment gate.

## Independent asset package

Use a separate Instance/Capset/token binding with `include_all_methods=false`
and only the two independent methods. Instance configuration fixes an HTTPS
`baseUrl` ending in `/openapi/` and a decimal-string `spaceId`; the upstream
TOKEN is an OctoBus Secret. The backend receives only its dedicated Capset token.
No credentials belong in PostgreSQL, ordinary logs or browser storage.

The package sends exact read-only GETs to `/openapi/ip/` and
`/openapi/port/service/`. IP filtering is `status=valid`; port status is left at
the source default. Requests carry explicit pagination, `sort=-id`, per-response
byte and wall-time limits. TLS chain and hostname verification are mandatory;
redirects, compressed bodies, streaming overflow, malformed JSON and invalid
approved fields fail closed. Decimal IDs remain strings across JavaScript.
Only approved fields are projected; unknown fields produce a count-only warning,
never raw field names or values.

Run the bounded-client and field-contract checks without a real source:

```bash
node --test tests/cloudatlas_fixture/verify_assets_contract.mjs
```

Regenerate/verify accepted package hashes through the pinned delivery image's
official `octobus service import` and compare its returned Package/Descriptor
SHA-256 values with the manifest. Do not substitute a host `npm pack` hash:
host Node/compression versions can produce different gzip bytes even when the
tar payload is identical. Any deliberate new-package change requires updating
its manifest and matching backend contract pins together; never repin the
legacy package as part of that update.

These deterministic checks do not prove real customer field coverage or grant
production read/retention authorization. The independent profile requires its
own approved bounded real-environment acceptance; the legacy canary remains
separate.
