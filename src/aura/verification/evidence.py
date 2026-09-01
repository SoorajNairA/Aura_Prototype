from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Any


class EvidenceKind(str, Enum):
    MANUFACTURER_DATASHEET = "manufacturer_datasheet"
    MANUFACTURER_PRODUCT_PAGE = "manufacturer_product_page"
    AUTHORITATIVE_STANDARD = "authoritative_standard"
    DETERMINISTIC_TOOL = "deterministic_tool"
    CURATED_COMPONENT_RECORD = "curated_component_record"
    ENGINEERING_ASSUMPTION = "engineering_assumption"


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    kind: EvidenceKind
    title: str
    source: str
    publisher: str
    retrieved_at: str
    content_hash: str
    applies_to: tuple[str, ...]
    properties: tuple[str, ...]
    source_version: str | None = None

    @classmethod
    def curated(cls, evidence_id: str, kind: EvidenceKind, title: str, source: str,
                publisher: str, properties: tuple[str, ...], source_version: str | None = None) -> "EvidenceRecord":
        normalized = "|".join((title, source, publisher, source_version or "", *properties))
        return cls(evidence_id, kind, title, source, publisher,
                   datetime.now(timezone.utc).isoformat(), sha256(normalized.encode()).hexdigest(),
                   (), properties, source_version)

    def for_targets(self, *ids: str) -> "EvidenceRecord":
        return EvidenceRecord(**(asdict(self) | {"kind": self.kind, "applies_to": tuple(ids),
                                                  "properties": self.properties}))

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["kind"] = self.kind.value
        value["evidenceId"] = value.pop("evidence_id")
        value["retrievedAt"] = value.pop("retrieved_at")
        value["contentHash"] = value.pop("content_hash")
        value["appliesTo"] = list(value.pop("applies_to"))
        value["sourceVersion"] = value.pop("source_version")
        value["properties"] = list(value["properties"])
        return value
