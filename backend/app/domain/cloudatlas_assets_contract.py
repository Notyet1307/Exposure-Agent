"""Separate, bounded assets-v1 OctoBus capability; never authorizes legacy Runs."""

SERVICE_ID = "cloudatlas-assets"
CAPABILITY_PROFILE = "assets-v1"
FINGERPRINT_SCHEMA = "exposure-agent.cloudatlas-assets-fingerprint.v1"
METHODS = {
    "ip": "cloudatlas.assets.v1.CloudAtlasAssetsService/ListIPAssets",
    "port": "cloudatlas.assets.v1.CloudAtlasAssetsService/ListPortServices",
}
PACKAGE_SHA256 = "d63abe702436da68f29866edf00c7b3ea51db01db3c5c9fbae12bcac3a57ea08"
DESCRIPTOR_SHA256 = "fcaf7b1bf2c15b7e4a47977e1c3a32823fd5d4f6dc7992e698c464ad2fc3e4b5"
