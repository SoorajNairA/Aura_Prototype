from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .results import VerificationFinding, VerificationResult, VerificationState


class DeltaClassification(str, Enum):
    IMPROVES = "IMPROVES"
    NEUTRAL = "NEUTRAL"
    WORSENS = "WORSENS"
    RESOLVES_ALL = "RESOLVES_ALL"
    INVALID_COMPARISON = "INVALID_COMPARISON"


@dataclass(frozen=True, order=True)
class FindingIdentity:
    code: str
    entity_ids: tuple[str, ...]
    requirement_ids: tuple[str, ...] = ()
    net_ids: tuple[str, ...] = ()
    interface_ids: tuple[str, ...] = ()
    relationship_ids: tuple[str, ...] = ()

    @classmethod
    def from_finding(cls, finding: VerificationFinding) -> "FindingIdentity":
        actual=finding.actual or {};machine=finding.machine_result or {}
        values=[]
        for source in (actual,machine):
            if source.get("connectionId"): values.append(str(source["connectionId"]))
            values.extend(map(str,source.get("connectionIds",())))
        return cls(finding.check,finding.entity_ids,finding.requirement_ids,finding.net_ids,finding.interface_ids,tuple(sorted(set(values))))

    def to_dict(self) -> dict[str, Any]:
        return {"code":self.code,"entityIds":list(self.entity_ids),"requirementIds":list(self.requirement_ids),
                "netIds":list(self.net_ids),"interfaceIds":list(self.interface_ids),"relationshipIds":list(self.relationship_ids)}


@dataclass(frozen=True)
class SeverityChange:
    finding_identity: FindingIdentity
    before: str
    after: str

    def to_dict(self) -> dict[str, Any]:
        return {"findingIdentity":self.finding_identity.to_dict(),"before":self.before,"after":self.after}


@dataclass(frozen=True)
class VerificationDelta:
    resolved_findings: tuple[VerificationFinding, ...]
    introduced_findings: tuple[VerificationFinding, ...]
    unchanged_findings: tuple[VerificationFinding, ...]
    severity_changes: tuple[SeverityChange, ...]
    readiness_before: str
    readiness_after: str
    blocking_resolved_count: int
    blocking_introduced_count: int
    classification: DeltaClassification

    def to_dict(self) -> dict[str, Any]:
        return {
            "resolvedFindings":[item.to_dict() for item in self.resolved_findings],
            "introducedFindings":[item.to_dict() for item in self.introduced_findings],
            "unchangedFindings":[item.to_dict() for item in self.unchanged_findings],
            "severityChanges":[item.to_dict() for item in self.severity_changes],
            "readinessBefore":self.readiness_before,"readinessAfter":self.readiness_after,
            "blockingResolvedCount":self.blocking_resolved_count,
            "blockingIntroducedCount":self.blocking_introduced_count,
            "classification":self.classification.value,
        }


def finding_level(finding: VerificationFinding) -> str:
    if finding.blocking or finding.state is VerificationState.FAILED: return "FAIL"
    if finding.severity=="warning" or finding.state in {VerificationState.ESTIMATED,VerificationState.CONCEPTUAL,VerificationState.STALE,VerificationState.UNSUPPORTED}: return "WARN"
    return "INFO"


def verification_readiness(result: VerificationResult) -> str:
    if any(item.blocking for item in result.findings) or result.state is VerificationState.FAILED: return "BUILD_INCOMPLETE"
    if any(finding_level(item)=="WARN" for item in result.findings) or result.state is not VerificationState.CROSS_CHECKED: return "SUPPORTED_WITH_LIMITATIONS"
    return "SUPPORTED"


def compare_verification(before: VerificationResult, after: VerificationResult) -> VerificationDelta:
    before_map={FindingIdentity.from_finding(item):item for item in before.findings}
    after_map={FindingIdentity.from_finding(item):item for item in after.findings}
    before_keys=set(before_map);after_keys=set(after_map)
    resolved=tuple(before_map[key] for key in sorted(before_keys-after_keys))
    introduced=tuple(after_map[key] for key in sorted(after_keys-before_keys))
    unchanged=tuple(after_map[key] for key in sorted(before_keys&after_keys))
    changes=[]
    rank={"INFO":0,"WARN":1,"FAIL":2}
    for key in sorted(before_keys&after_keys):
        old,new=finding_level(before_map[key]),finding_level(after_map[key])
        if old!=new: changes.append(SeverityChange(key,old,new))
    blocking_resolved=sum(finding_level(item)=="FAIL" for item in resolved)+sum(rank[item.before]==2 and rank[item.after]<2 for item in changes)
    blocking_introduced=sum(finding_level(item)=="FAIL" for item in introduced)+sum(rank[item.before]<2 and rank[item.after]==2 for item in changes)
    worsened=blocking_introduced>0 or any(rank[item.after]>rank[item.before] for item in changes)
    improved=bool(resolved) or any(rank[item.after]<rank[item.before] for item in changes)
    before_blockers=sum(finding_level(item)=="FAIL" for item in before.findings)
    after_blockers=sum(finding_level(item)=="FAIL" for item in after.findings)
    if worsened: classification=DeltaClassification.WORSENS
    elif before_blockers and not after_blockers: classification=DeltaClassification.RESOLVES_ALL
    elif improved: classification=DeltaClassification.IMPROVES
    else: classification=DeltaClassification.NEUTRAL
    return VerificationDelta(resolved,introduced,unchanged,tuple(changes),verification_readiness(before),verification_readiness(after),blocking_resolved,blocking_introduced,classification)
