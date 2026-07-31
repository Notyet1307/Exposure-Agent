from typing import Final

from app.domain.models import CustomerUploadProfileDefinition

REQUIRED_HEADERS: Final = (
    "资产IP",
    "起始端口",
    "结束端口",
    "是否web界面",
    "web界面url",
)
WARNING_HEADERS: Final = (
    "服务类型",
    "资产负责人",
    "资产所属部门",
    "端口负责人",
    "部门",
)
OPTIONAL_HEADERS: Final = ("序号",)


def default_customer_upload_profile_definition() -> CustomerUploadProfileDefinition:
    return CustomerUploadProfileDefinition(
        required_headers=list(REQUIRED_HEADERS),
        warning_headers=list(WARNING_HEADERS),
        optional_headers=list(OPTIONAL_HEADERS),
    )
