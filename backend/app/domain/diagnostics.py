"""One frozen diagnostic value shared by upload, ledger, route and UI surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LocationOrigin = Literal["worksheet", "ledger"]
Measurement = Literal["exact", "declared", "received"]
DiagnosticUnit = Literal["bytes", "entries", "port_number"]


@dataclass(frozen=True)
class Diagnostic:
    code: str
    field: str | None = None
    row: int | None = None
    column: int | None = None
    reason: str | None = None
    location: LocationOrigin | None = None
    limit: int | None = None
    observed: int | None = None
    measurement: Measurement | None = None
    unit: DiagnosticUnit | None = None

    def detail_fields(self) -> dict[str, object]:
        """Additive wire fields; absent values stay absent for old shapes."""
        fields: dict[str, object] = {}
        if self.field is not None:
            fields["field"] = self.field
        if self.row is not None:
            fields["row"] = self.row
        if self.column is not None:
            fields["column"] = self.column
        if self.reason is not None:
            fields["reason"] = self.reason
        if self.location is not None:
            fields["location"] = self.location
        if self.limit is not None:
            fields["limit"] = self.limit
        if self.observed is not None:
            fields["observed"] = self.observed
        if self.measurement is not None:
            fields["measurement"] = self.measurement
        if self.unit is not None:
            fields["unit"] = self.unit
        return fields
