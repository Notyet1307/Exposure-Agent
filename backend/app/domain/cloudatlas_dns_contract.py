"""Independent flat DNS capability; no change to existing source packages."""

SERVICE_ID = "cloudatlas-dns"
SOURCE_TYPE = "cloudatlas_dns"
CAPABILITY_PROFILE = "dns-v1"
FINGERPRINT_SCHEMA = "exposure-agent.cloudatlas-dns-fingerprint.v1"
METHODS = {
    "dns": "cloudatlas.dns.v1.CloudAtlasDNSService/ListDNSRecords",
}
PACKAGE_SHA256 = "ec6b541911b9eec7e9df910bd3e5771a3e3e287ae6351559a1912f9aea08e621"
DESCRIPTOR_SHA256 = "6a91160f0a8c3c1146ba40fbaec35ed5c1d946edc2ae54c68d9ed70b55e4f174"
