# Exposure-Agent OctoBus packages

`cloudatlas-read/` is the product-owned, single-method read-only Service Package. Its accepted OctoBus import hashes and selected method are pinned in `cloudatlas-read.hashes.json`; the backend rejects validation when the live Package, Descriptor, Instance, Capset, token bindings, or selected method no longer match the canonical fingerprint material.

Run the deterministic public-Connect acceptance stack with:

```bash
./scripts/test-cloudatlas-fixture.sh
```

The delivered OctoBus image pins `@chaitin-ai/octobus@0.1.0` and the architecture-specific release archive SHA-256 for the real `chaitin-cli@v2606.0.4`. The package is baked into that image, and the production Compose stack imports it idempotently before starting the backend, so a source checkout mount or separate package-provisioning step is not required.

The fixture stack uses that same image, imports the product package, binds one fixture Instance to a Capset with `include_all_methods=false`, selects only `cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets`, and exercises the exact Service Package → real CLI → fixture upstream read-only GET chain. It uses test-only tokens and does not contact a real CloudAtlas; the authorized real-environment read-only [canary](../docs/runbooks/cloudatlas-canary.md) remains a deployment gate.
