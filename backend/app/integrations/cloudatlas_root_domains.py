from app.domain import cloudatlas_root_domains_contract as contract
from app.integrations.cloudatlas_assets import OctobusCloudAtlasAssetsClient


class OctobusCloudAtlasRootDomainsClient(OctobusCloudAtlasAssetsClient):
    SERVICE_ID = contract.SERVICE_ID
    SOURCE_TYPE = contract.SOURCE_TYPE
    PACKAGE_SHA256 = contract.PACKAGE_SHA256
    DESCRIPTOR_SHA256 = contract.DESCRIPTOR_SHA256
    DOMAIN_METHODS = contract.METHODS
    METHODS = tuple(contract.METHODS.values())
    FINGERPRINT_SCHEMA = contract.FINGERPRINT_SCHEMA
    CAPABILITY_PROFILE = contract.CAPABILITY_PROFILE
