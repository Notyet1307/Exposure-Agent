"""Independent, bounded root-domains-v1 capability; never expands assets-v1."""

SERVICE_ID = "cloudatlas-root-domains"
SOURCE_TYPE = "cloudatlas_root_domains"
CAPABILITY_PROFILE = "root-domains-v1"
FINGERPRINT_SCHEMA = "exposure-agent.cloudatlas-root-domains-fingerprint.v1"
METHODS = {
    "root_domain": "cloudatlas.rootdomains.v1.CloudAtlasRootDomainsService/ListRootDomains",
}
PACKAGE_SHA256 = "e8625d07a030b2e304ad8916602c57c1405c7c53351a75934fbfd836a66793dd"
DESCRIPTOR_SHA256 = "cb731612f31fd45f98f3b321745cd266a2dd07f7e2fa74eeb8a47c4592e0c02b"
