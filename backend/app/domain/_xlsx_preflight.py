from __future__ import annotations

import struct
from pathlib import Path, PurePosixPath
from typing import Final
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from defusedxml import ElementTree  # type: ignore[import-untyped]
from defusedxml.common import DefusedXmlException  # type: ignore[import-untyped]

MAX_ZIP_ENTRIES: Final = 2_048
MAX_ENTRY_UNCOMPRESSED_BYTES: Final = 64 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES: Final = 256 * 1024 * 1024
MAX_CENTRAL_DIRECTORY_BYTES: Final = 4 * 1024 * 1024
_MAX_EOCD_TAIL_BYTES: Final = 65_557
_ZIP64_SENTINEL_16: Final = 0xFFFF
_ZIP64_SENTINEL_32: Final = 0xFFFFFFFF

_EOCD = struct.Struct("<4s4H2LH")
_CENTRAL_HEADER = struct.Struct("<4s6H3L5H2L")
_EOCD_SIGNATURE: Final = b"PK\x05\x06"
_CENTRAL_SIGNATURE: Final = b"PK\x01\x02"
_RELATIONSHIP_NS: Final = (
    "http://schemas.openxmlformats.org/package/2006/relationships"
)


class PreflightError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _resource_limit() -> PreflightError:
    return PreflightError("workbook_resource_limit")


def _safe_member_name(raw_name: bytes, flags: int) -> str:
    encoding = "utf-8" if flags & 0x800 else "cp437"
    try:
        name = raw_name.decode(encoding)
    except UnicodeDecodeError as exc:
        raise PreflightError("malformed_workbook") from exc
    pure_name = PurePosixPath(name)
    if not name or "\\" in name or pure_name.is_absolute() or ".." in pure_name.parts:
        raise PreflightError("malformed_workbook")
    return name


def _check_central_directory(path: Path) -> None:
    try:
        file_size = path.stat().st_size
        if file_size < _EOCD.size:
            raise PreflightError("malformed_workbook")

        tail_size = min(file_size, _MAX_EOCD_TAIL_BYTES)
        with path.open("rb") as workbook_file:
            workbook_file.seek(file_size - tail_size)
            tail = workbook_file.read(tail_size)
            signature_offset = tail.rfind(_EOCD_SIGNATURE)
            if signature_offset < 0 or signature_offset + _EOCD.size > len(tail):
                raise PreflightError("malformed_workbook")
            (
                signature,
                disk_number,
                central_disk,
                disk_entries,
                total_entries,
                central_size,
                central_offset,
                comment_length,
            ) = _EOCD.unpack_from(tail, signature_offset)
            eocd_offset = file_size - tail_size + signature_offset
            if (
                signature != _EOCD_SIGNATURE
                or eocd_offset + _EOCD.size + comment_length != file_size
            ):
                raise PreflightError("malformed_workbook")
            if disk_number != 0 or central_disk != 0 or disk_entries != total_entries:
                raise PreflightError("malformed_workbook")
            if (
                total_entries == _ZIP64_SENTINEL_16
                or central_size == _ZIP64_SENTINEL_32
            ):
                raise PreflightError("malformed_workbook")
            if total_entries > MAX_ZIP_ENTRIES:
                raise _resource_limit()
            if central_size > MAX_CENTRAL_DIRECTORY_BYTES:
                raise _resource_limit()
            if central_offset + central_size > eocd_offset:
                raise PreflightError("malformed_workbook")

            workbook_file.seek(central_offset)
            central = workbook_file.read(central_size)
    except PreflightError:
        raise
    except OSError as exc:
        raise PreflightError("malformed_workbook") from exc

    cursor = 0
    total_uncompressed = 0
    largest_entry = 0
    names: set[str] = set()
    parsed_entries = 0
    while cursor < len(central):
        if cursor + _CENTRAL_HEADER.size > len(central):
            raise PreflightError("malformed_workbook")
        (
            signature,
            _made_by,
            _needed,
            flags,
            compression,
            _modified_time,
            _modified_date,
            _crc32,
            compressed_size,
            uncompressed_size,
            name_length,
            extra_length,
            member_comment_length,
            disk_start,
            _internal_attributes,
            _external_attributes,
            local_offset,
        ) = _CENTRAL_HEADER.unpack_from(central, cursor)
        if signature != _CENTRAL_SIGNATURE:
            raise PreflightError("malformed_workbook")
        variable_size = name_length + extra_length + member_comment_length
        next_cursor = cursor + _CENTRAL_HEADER.size + variable_size
        if next_cursor > len(central):
            raise PreflightError("malformed_workbook")
        if (
            compressed_size == _ZIP64_SENTINEL_32
            or uncompressed_size == _ZIP64_SENTINEL_32
            or local_offset == _ZIP64_SENTINEL_32
            or disk_start == _ZIP64_SENTINEL_16
        ):
            raise PreflightError("malformed_workbook")
        if flags & 0x1 or compression not in (ZIP_STORED, ZIP_DEFLATED):
            raise PreflightError("malformed_workbook")
        name_start = cursor + _CENTRAL_HEADER.size
        name = _safe_member_name(
            central[name_start : name_start + name_length], flags
        )
        if name in names:
            raise PreflightError("malformed_workbook")
        names.add(name)
        total_uncompressed += uncompressed_size
        largest_entry = max(largest_entry, uncompressed_size)
        cursor = next_cursor
        parsed_entries += 1

    if parsed_entries != total_entries or cursor != central_size:
        raise PreflightError("malformed_workbook")
    if largest_entry > MAX_ENTRY_UNCOMPRESSED_BYTES:
        raise _resource_limit()
    if total_uncompressed > MAX_TOTAL_UNCOMPRESSED_BYTES:
        raise _resource_limit()


def _relationship_is_forbidden(relationship_type: str) -> bool:
    suffix = relationship_type.rsplit("/", maxsplit=1)[-1]
    return suffix in {
        "activeXControl",
        "activeXControlBinary",
        "attachedToolbars",
        "connections",
        "control",
        "ctrlProp",
        "externalLink",
        "externalLinkPath",
        "oleObject",
        "package",
        "vbaProject",
        "vmlDrawing",
    }


def _content_type_is_forbidden(content_type: str) -> bool:
    lowered = content_type.casefold()
    return any(
        marker in lowered
        for marker in (
            "activex",
            "attachedtoolbars",
            "connections+xml",
            "ctrlprop",
            "externallink",
            "oleobject",
            "vbaproject",
            "vmldrawing",
        )
    )


def _is_xml_content_type(content_type: str) -> bool:
    lowered = content_type.casefold()
    return (
        lowered == "application/xml"
        or lowered.endswith("+xml")
        or lowered
        == "application/vnd.openxmlformats-officedocument.vmldrawing"
    )


def _is_formula_element(local_name: str) -> bool:
    normalized = local_name.casefold()
    return (
        normalized == "f"
        or normalized.startswith("formula")
        or normalized.endswith("formula")
    )


def _looks_like_xml_part(archive: ZipFile, name: str) -> bool:
    with archive.open(name) as part:
        first_chunk = True
        while chunk := part.read(64 * 1024):
            whitespace = b"\xef\xbb\xbf \t\r\n" if first_chunk else b" \t\r\n"
            leading = chunk.lstrip(whitespace)
            if leading:
                return leading.startswith(b"<")
            first_chunk = False
    return False


def _inspect_ooxml(archive: ZipFile) -> None:
    names = set(archive.namelist())
    declared_xml_parts: set[str] = set()
    xml_extensions: set[str] = set()
    if "[Content_Types].xml" not in names:
        raise PreflightError("malformed_workbook")

    try:
        with archive.open("[Content_Types].xml") as content_types_file:
            for _event, element in ElementTree.iterparse(
                content_types_file, events=("end",)
            ):
                content_type = element.attrib.get("ContentType", "")
                if _content_type_is_forbidden(content_type):
                    raise PreflightError("unsupported_workbook_feature")
                local_name = element.tag.rsplit("}", maxsplit=1)[-1]
                if _is_xml_content_type(content_type):
                    if local_name == "Override":
                        part_name = element.attrib.get("PartName", "").lstrip("/")
                        if part_name:
                            declared_xml_parts.add(part_name)
                    elif local_name == "Default":
                        extension = element.attrib.get("Extension", "").casefold()
                        if extension:
                            xml_extensions.add(f".{extension}")
                element.clear()

        for name in names:
            if (
                name.startswith(
                    ("xl/activeX/", "xl/ctrlProps/", "xl/embeddings/", "xl/externalLinks/")
                )
                or name in {
                    "xl/attachedToolbars.bin",
                    "xl/connections.xml",
                    "xl/vbaProject.bin",
                }
            ):
                raise PreflightError("unsupported_workbook_feature")

        for relationship_name in sorted(
            name for name in names if name.endswith(".rels")
        ):
            with archive.open(relationship_name) as relationship_file:
                for _event, element in ElementTree.iterparse(
                    relationship_file, events=("end",)
                ):
                    if (
                        element.tag == f"{{{_RELATIONSHIP_NS}}}Relationship"
                        and _relationship_is_forbidden(element.attrib.get("Type", ""))
                    ):
                        raise PreflightError("unsupported_workbook_feature")
                    element.clear()

        xml_names = sorted(
            name
            for name in names
            if name in declared_xml_parts
            or any(name.casefold().endswith(ext) for ext in xml_extensions)
            or _looks_like_xml_part(archive, name)
        )
        workbook_found = False
        for xml_name in xml_names:
            workbook_sheet_count = 0
            with archive.open(xml_name) as xml_file:
                for _event, element in ElementTree.iterparse(xml_file, events=("end",)):
                    local_name = element.tag.rsplit("}", maxsplit=1)[-1]
                    if xml_name == "xl/workbook.xml" and local_name == "sheet":
                        workbook_found = True
                        workbook_sheet_count += 1
                        if element.attrib.get("state", "visible").casefold() != "visible":
                            raise PreflightError("unsupported_workbook_feature")
                    if _is_formula_element(local_name):
                        raise PreflightError("unsupported_workbook_feature")
                    if (
                        local_name == "ClientData"
                        and element.attrib.get("ObjectType", "").casefold() != "note"
                    ):
                        raise PreflightError("unsupported_workbook_feature")
                    element.clear()
            if xml_name == "xl/workbook.xml" and workbook_sheet_count != 1:
                raise PreflightError("unsupported_workbook_feature")
        if not workbook_found:
            raise PreflightError("malformed_workbook")
    except PreflightError:
        raise
    except (ElementTree.ParseError, DefusedXmlException, KeyError, OSError) as exc:
        raise PreflightError("malformed_workbook") from exc


def preflight_xlsx(path: Path) -> None:
    _check_central_directory(path)
    try:
        with ZipFile(path) as archive:
            _inspect_ooxml(archive)
    except PreflightError:
        raise
    except (BadZipFile, OSError, RuntimeError, ValueError) as exc:
        raise PreflightError("malformed_workbook") from exc
