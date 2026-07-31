# Exposure-Agent OctoBus packages

`cloudatlas-read/` is the product-owned, single-method read-only Service Package. Its accepted OctoBus import hashes and selected method are pinned in `cloudatlas-read.hashes.json`; the backend rejects validation when the live Package, Descriptor, Instance, Capset, token bindings, or selected method no longer match the canonical fingerprint material.

Run the deterministic public-Connect acceptance stack with:

```bash
./scripts/test-cloudatlas-fixture.sh
```

The stack builds OctoBus `@chaitin-ai/octobus@0.1.0`, imports the product package, binds one fixture Instance to a Capset with `include_all_methods=false`, selects only `cloudatlas.read.v1.CloudAtlasReadService/ListIPAssets`, and exercises a fixture upstream over read-only GET. It uses test-only tokens and does not contact a real CloudAtlas; the authorized real-environment read-only canary remains a deployment gate.
