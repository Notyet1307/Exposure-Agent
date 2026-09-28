# Exposure-Agent OctoBus packages

`cloudatlas-read/` is the product-owned, single-method read-only Service Package. Its accepted OctoBus import hashes and selected method are pinned in `cloudatlas-read.hashes.json`; the backend rejects validation when the live Package, Descriptor, Instance, Capset, token bindings, or selected method no longer match the canonical fingerprint material.

`cloudatlas-assets/` is the independent `assets-v1` package. Its separate
`cloudatlas-assets.hashes.json` pins exactly
`cloudatlas.assets.v1.CloudAtlasAssetsService/ListIPAssets` and
`cloudatlas.assets.v1.CloudAtlasAssetsService/ListPortServices`. It does not
replace the legacy package, descriptor, fields or IP filter.

`cloudatlas-root-domains/` is the separate `root-domains-v1` package. Its
`cloudatlas-root-domains.hashes.json` pins only
`cloudatlas.rootdomains.v1.CloudAtlasRootDomainsService/ListRootDomains`.
It does not change either existing package or their accepted hashes.

`cloudatlas-dns/` is the independent `dns-v1` package. Its
`cloudatlas-dns.hashes.json` pins only
`cloudatlas.dns.v1.CloudAtlasDNSService/ListDNSRecords`; the three older
packages, methods and accepted hashes remain unchanged.

Run the deterministic public-Connect acceptance stack with:

```bash
./scripts/test-cloudatlas-fixture.sh
```

The delivered OctoBus image pins its Node base image, `@chaitin-ai/octobus@0.1.0` and the architecture-specific release archive SHA-256 for the real `chaitin-cli@v2606.0.4`. All four packages are baked into that image, and the production Compose stack imports them idempotently before starting the backend, so a source checkout mount or separate package-provisioning step is not required.

The fixture stack uses that same image, imports the product package, binds one fixture Instance to a Capset with `include_all_methods=false`, selects only `cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets`, and exercises the exact Service Package → real CLI → fixture upstream read-only GET chain. It uses test-only tokens and does not contact a real CloudAtlas; the authorized real-environment read-only [canary](../docs/runbooks/cloudatlas-canary.md) remains a deployment gate.

## Independent asset package

Use a separate Instance/Capset/token binding with `include_all_methods=false`
and only the two independent methods. Instance configuration fixes an HTTPS
`baseUrl` ending in `/openapi/` and a decimal-string `spaceId`; the upstream
TOKEN is an OctoBus Secret. The backend receives only its dedicated Capset token.
No credentials belong in PostgreSQL, ordinary logs or browser storage.

The package sends exact read-only GETs to `/openapi/v1/asset/ip` and
`/openapi/v1/attack/port`. IP filtering is `status=valid`; port status is left at
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

## Independent root-domain package

Create a separate Instance for service `cloudatlas-root-domains` and a separate
Capset with `include_all_methods=false`, selecting only `ListRootDomains` above.
Use the same HTTPS `/openapi/` origin and decimal-string `spaceId` configuration
shape, with the upstream TOKEN stored only as an OctoBus Secret. Set the distinct
`CLOUDATLAS_ROOT_DOMAINS_CAPSET_TOKEN` in backend and `cloudatlas-sync` environments.
An empty value denies new root syncs; it is never replaced by an IP/port token.
On the external-assets page, select `root-domains-v1`, validate metadata, and
explicitly enable the source before starting an authorized bounded sync.

This package issues only `GET /openapi/v1/asset/root-domain`, with fixed
`status=valid` and `sort=-id`, and the same TLS, deadline, streaming-size and
no-redirect protections. All 14 approved fields are required; only the six
approved ICP/WHOIS fields accept null. IDs remain decimal strings, source times
remain original strings, and domain names are not normalized or fetched.

A root source creates one `root_domain` version, not IP/port versions.
`page_size=20`, `max_pages=1`, `max_records=20` is a valid single-page budget.
Successful non-full batches are partial publications; local search, history,
pagination and detail reads do not call the source. Search is a case-insensitive
literal substring over the stored root name, not a DNS or ownership judgment.
Downgrading the root-domain migration refuses to discard root sources or data.

Run its deterministic contract checks with Node 24:

```bash
node --test tests/cloudatlas_fixture/verify_root_domains_contract.mjs
```

Verify new hashes through the pinned image as above. Synthetic checks do not
authorize real-source calls: root-domain acceptance requires a new explicit
scope, budget, private-retention deadline and cleanup authorization.

## Independent DNS package

Use a separate `cloudatlas-dns` Instance/Capset with `include_all_methods=false`
and only `ListDNSRecords`. Configure the same HTTPS `/openapi/` origin and
decimal-string space, with the upstream TOKEN held only in an OctoBus Secret.
Set `CLOUDATLAS_DNS_CAPSET_TOKEN` in backend and `cloudatlas-sync`; an empty
value denies new DNS calls and never falls back to another profile's token.
Select `dns-v1` on the external-assets page, validate metadata, then explicitly
enable synchronization. Existing token permissions are not DNS authorization.

Only `GET /openapi/v1/asset/dns` is issued, with fixed `flat=1`, `status=valid`
and `sort=-id`. All 11 approved fields are required and non-null; empty strings
and tag arrays remain valid. Source, business-group and tag IDs stay lossless
decimal strings. `bu` is a required object with required, non-null `id` and
`name`; `name` may be empty. String/array/null groups, missing children and
wrong child types reject the entire unsealed version, with no default or union
fallback. Returned `rdtype`/`status` are source strings, not query enums.
Record values remain text: no DNS resolution, URL visits, IP parsing or links
to assets. The TLS, byte-limit, deadline and no-retry protections above apply.

A sync creates only a `dns` version. Its page quota is
`min(max_pages, floor(max_records / page_size))`; `20/1/20` is a valid one-page
budget. Normal quota completion publishes a sealed partial version, not a
complete result. Local search is a case-insensitive literal substring of
`subdomain` only. Lists, pagination, fixed-version details and history use
PostgreSQL without source calls. Expiry denies access immediately; cleanup
remains source-scoped. Migration downgrade refuses while any DNS source,
task, version or head exists.
The `ce56f7081923` forward migration changes only new DNS field validation;
it does not rewrite historical records or failed versions. Its downgrade
refuses while DNS object records remain. Re-import the DNS package and
revalidate its pinned metadata after upgrade; do not auto-enable or retry
previously failed sources. The older three package hashes remain unchanged.

```bash
node --test tests/cloudatlas_fixture/verify_dns_contract.mjs
```

Verify the new package hashes through the pinned image's official import.
These synthetic checks do not satisfy ACDNS-6: real DNS reads require fresh,
explicit method/scope/budget and absolute retention/cleanup authorization in
[#262](https://github.com/Notyet1307/Exposure-Agent/issues/262). Do not reuse
legacy, IP/port or root-domain acceptance credentials or permissions.
