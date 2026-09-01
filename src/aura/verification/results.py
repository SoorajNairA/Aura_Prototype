from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from enum import Enum

from aura.engineering_graph.patches import GraphPatch


class VerificationState(str, Enum):
    TOOL_VERIFIED = "tool_verified"
    SOURCE_VERIFIED = "source_verified"
    CROSS_CHECKED = "cross_checked"
    ESTIMATED = "estimated"
    CONCEPTUAL = "conceptual"
    STALE = "stale"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class VerificationDecision(str, Enum):
    ACCEPT = "accept"
    MODIFY = "modify"
    REJECT = "reject"


@dataclass(frozen=True)
class VerificationFinding:
    id: str
    check: str
    state: VerificationState
    severity: str
    message: str
    entity_ids: tuple[str, ...]
    expected: dict[str, Any] | None = None
    actual: dict[str, Any] | None = None
    evidence_ids: tuple[str, ...] = ()
    verified_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_versions: dict[str, str] = field(default_factory=dict)
    dependency_ids: tuple[str, ...] = ()
    revision: int = 1
    machine_result: dict[str, Any] = field(default_factory=dict)
    category: str = "general"
    requirement_ids: tuple[str, ...] = ()
    net_ids: tuple[str, ...] = ()
    interface_ids: tuple[str, ...] = ()
    required_capability: str | None = None
    repair_hint: str | None = None
    blocking: bool = False

    def to_dict(self) -> dict[str, Any]:
        level="FAIL" if self.blocking or self.state is VerificationState.FAILED else "WARN" if self.severity=="warning" else "INFO"
        return {"findingId": self.id, "semanticId": self.entity_ids[0] if self.entity_ids else None,
                "code": self.check, "check": self.check, "status": self.state.value, "severity": level,
                "legacySeverity": self.severity,
                "category": self.category, "blocking": self.blocking,
                "summary": self.message, "expected": self.expected, "actual": self.actual,
                "evidenceIds": list(self.evidence_ids), "verifiedAt": self.verified_at,
                "sourceVersions": self.source_versions, "dependencyIds": list(self.dependency_ids),
                "revision": self.revision, "machineResult": self.machine_result,
                "requirementIds": list(self.requirement_ids), "netIds": list(self.net_ids),
                "interfaceIds": list(self.interface_ids),
                "requiredCapability": self.required_capability, "repairHint": self.repair_hint,
                "semanticIds": list(self.entity_ids), "entity_ids": list(self.entity_ids)}


@dataclass(frozen=True)
class VerificationResult:
    decision: VerificationDecision
    state: VerificationState
    reasons: tuple[str, ...]
    patch: GraphPatch | None
    findings: tuple[VerificationFinding, ...] = ()
    confidence_ingredients: dict[str, int] = field(default_factory=dict)
    verification_delta: dict[str, Any] | None = None

    @property
    def accepted(self) -> bool:
        return self.decision in {VerificationDecision.ACCEPT, VerificationDecision.MODIFY}
