from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Any, Iterable

from aura.engineering_graph.model import EngineeringGraph, EntityKind
from aura.infrastructure.persistence.project_repository import StoredEvent


class NarrationKind(str, Enum):
    PROJECT_PROGRESS = "project_progress"
    ENGINEERING_DECISION = "engineering_decision"
    VERIFICATION_EXPLANATION = "verification_explanation"
    WARNING = "warning"
    MODIFICATION_SUMMARY = "modification_summary"
    COMPLETION = "completion"


class NarrationPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


@dataclass(frozen=True)
class GroundedFact:
    fact_id: str
    text: str
    status: str
    semantic_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    numeric_tokens: tuple[str, ...] = ()


@dataclass(frozen=True)
class GroundedNarrationContext:
    event_type: str
    allowed_facts: tuple[GroundedFact, ...]

    @property
    def fact_ids(self) -> set[str]: return {x.fact_id for x in self.allowed_facts}
    @property
    def semantic_ids(self) -> set[str]: return {i for x in self.allowed_facts for i in x.semantic_ids}
    @property
    def numeric_tokens(self) -> set[str]: return {i for x in self.allowed_facts for i in x.numeric_tokens}


@dataclass(frozen=True)
class NarrationCandidate:
    kind: NarrationKind
    text: str
    semantic_ids: tuple[str, ...]
    verification_finding_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    priority: NarrationPriority = NarrationPriority.NORMAL
    facts: tuple[GroundedFact, ...] = ()


@dataclass(frozen=True)
class NarrationEvent:
    narration_id: str
    project_id: str
    revision: int
    event_id: int
    kind: NarrationKind
    text: str
    semantic_ids: tuple[str, ...]
    verification_finding_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    priority: NarrationPriority
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        value=asdict(self)
        return {"narrationId":value["narration_id"],"projectId":value["project_id"],
                "revision":value["revision"],"eventId":value["event_id"],"kind":self.kind.value,
                "text":value["text"],"semanticIds":list(value["semantic_ids"]),
                "verificationFindingIds":list(value["verification_finding_ids"]),
                "evidenceIds":list(value["evidence_ids"]),"priority":self.priority.value,
                "createdAt":value["created_at"]}


class BoundedVertexPhraser:
    """Optional wording polish; never expands the supplied facts."""
    def __init__(self, provider: Any, max_words: int = 35): self.provider=provider;self.max_words=max_words

    def phrase(self, candidate: NarrationCandidate) -> str:
        context=GroundedNarrationContext("narration",candidate.facts)
        schema={"type":"object","additionalProperties":False,"required":["text","usedFactIds"],
                "properties":{"text":{"type":"string"},"usedFactIds":{"type":"array","items":{"type":"string"}}}}
        try:
            result=self.provider.generate_structured([{"role":"user","content":json.dumps({"intent":candidate.text,
                "allowedFacts":[asdict(x) for x in candidate.facts],"tone":"competent engineer, restrained",
                "maximumWords":self.max_words})}],system_prompt="Rephrase only supplied facts. Do not add technical or numeric claims.",max_tokens=120,response_schema=schema)
            payload=json.loads(result.text); text=str(payload["text"]).strip(); used=set(payload["usedFactIds"])
            if not used or not used <= context.fact_ids or len(text.split())>self.max_words: raise ValueError("invalid phrasing")
            supplied=context.numeric_tokens
            if any(token not in supplied for token in re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?",text)): raise ValueError("invented numeric claim")
            return text
        except Exception:
            return candidate.text


class NarrationCoalescer:
    """Small bounded queue used by presentation adapters."""
    def __init__(self, limit: int = 8): self.limit=limit;self._items: list[NarrationCandidate]=[]
    def push(self,item:NarrationCandidate)->tuple[NarrationCandidate,...]:
        if item.priority is NarrationPriority.HIGH:
            self._items=[x for x in self._items if x.priority is not NarrationPriority.LOW]
            return (item,)
        if self._items and self._items[-1].kind==item.kind and self._items[-1].semantic_ids==item.semantic_ids:
            self._items[-1]=item
        else:self._items.append(item)
        self._items=self._items[-self.limit:]
        return ()
    def flush(self)->tuple[NarrationCandidate,...]: items=tuple(self._items);self._items.clear();return items


class NarrationService:
    MAX_WORDS=60

    def candidates(self,event:StoredEvent,graph:EngineeringGraph,representations:list[dict[str,Any]])->tuple[NarrationCandidate,...]:
        if event.type=="narration.created": return ()
        ids=tuple(i for i in event.semantic_ids if i in graph.entities)
        if event.type=="project.started":
            return (self._candidate(NarrationKind.PROJECT_PROGRESS,"Planning the committed project structure.",ids,NarrationPriority.NORMAL),)
        if event.type=="warning.created":
            finding_id=event.payload.get("finding_id");finding=graph.entities.get(finding_id)
            if finding:
                target_ids=tuple(finding.metadata.get("semanticIds",finding.metadata.get("entity_ids",ids)))
                evidence=tuple(finding.metadata.get("evidenceIds",()))
                status=finding.verification_status
                qualifier={"estimated":" remains an estimate","conceptual":" remains conceptual","failed":" failed verification"}.get(status," has a verification warning")
                text=f"Verification for {self._names(graph,target_ids)}{qualifier}: {finding.name}"
                fact=GroundedFact(f"fact-{finding.id}",finding.name,status,target_ids,evidence,self._numbers(finding.name))
                return (self._candidate(NarrationKind.WARNING,text,target_ids,NarrationPriority.HIGH,(finding.id,),evidence,(fact,)),)
        if event.type=="verification.failed":
            reasons=event.payload.get("reasons",[]);text=f"Verification failed: {reasons[0] if reasons else 'the proposed design did not pass deterministic checks.'}"
            fact=GroundedFact("fact-verification-failed",text,"failed",ids,(),self._numbers(text))
            return (self._candidate(NarrationKind.WARNING,text,ids,NarrationPriority.HIGH,facts=(fact,)),)
        if event.type=="verification.completed":
            findings=[x for x in graph.find(kind=EntityKind.VERIFICATION_RESULT) if x.verification_status in {"source_verified","cross_checked","estimated","conceptual"}]
            selected=[next((x for x in findings if x.verification_status==status),None) for status in ("cross_checked","source_verified")]
            result=[]
            for preferred in (x for x in selected if x is not None):
                target_ids=tuple(preferred.metadata.get("semanticIds",preferred.metadata.get("entity_ids",())))
                evidence=tuple(preferred.metadata.get("evidenceIds",()))
                prefix={"source_verified":"Manufacturer documentation supports this result: ","cross_checked":"Independent evidence and a deterministic rule agree: ","estimated":"This remains estimated: ","conceptual":"This remains conceptual: "}[preferred.verification_status]
                fact=GroundedFact(f"fact-{preferred.id}",preferred.name,preferred.verification_status,target_ids,evidence,self._numbers(preferred.name))
                result.append(self._candidate(NarrationKind.VERIFICATION_EXPLANATION,prefix+preferred.name,target_ids,NarrationPriority.NORMAL,(preferred.id,),evidence,(fact,)))
            return tuple(result)
        if event.type=="modification.preview_ready":
            affected=tuple(event.payload.get("affected",ids));regenerated=tuple(event.payload.get("regenerated",()))
            unchanged=tuple(event.payload.get("unchanged",()))
            text=f"The change can update {self._names(graph,affected)}. {len(regenerated)} representation{'s' if len(regenerated)!=1 else ''} will regenerate."
            if "electronics" in unchanged:text+=" Dependency analysis leaves the electronics unchanged."
            fact=GroundedFact("fact-modification-preview",text,"tool_verified",affected,(),self._numbers(text))
            return (self._candidate(NarrationKind.MODIFICATION_SUMMARY,text,affected,NarrationPriority.NORMAL,facts=(fact,)),)
        if event.type=="modification.committed":
            diff=event.payload.get("diff",{});affected=tuple(diff.get("affected",ids));regenerated=tuple(diff.get("regenerated",()))
            text=f"Revision {event.revision} applied to {self._names(graph,affected)}. Regenerated {len(regenerated)} affected representation{'s' if len(regenerated)!=1 else ''}."
            if "electronics" in diff.get("unchanged",()):text+=" The electrical system was unchanged by dependency analysis."
            fact=GroundedFact("fact-modification-committed",text,"tool_verified",affected,(),self._numbers(text))
            return (self._candidate(NarrationKind.MODIFICATION_SUMMARY,text,affected,NarrationPriority.HIGH,facts=(fact,)),)
        if event.type=="representation.fallback":
            return (self._candidate(NarrationKind.WARNING,f"The exact representation for {self._names(graph,ids)} was unavailable, so the Workspace retained a conceptual proxy.",ids,NarrationPriority.NORMAL),)
        if event.type=="project.ready":
            components=len(graph.find(kind=EntityKind.COMPONENT));subsystems=len(graph.find(kind=EntityKind.SUBSYSTEM));findings=graph.find(kind=EntityKind.VERIFICATION_RESULT)
            source=sum(x.verification_status=="source_verified" for x in findings);estimated=sum(x.verification_status=="estimated" for x in findings);failed=sum(x.verification_status=="failed" for x in findings)
            text=f"Project ready with {components} components across {subsystems} subsystems: {source} source-verified checks, {estimated} estimates, and {failed} failed checks."
            fact=GroundedFact("fact-project-summary",text,"tool_verified",(graph.project_id,),(),self._numbers(text))
            return (self._candidate(NarrationKind.COMPLETION,text,(graph.project_id,),NarrationPriority.NORMAL,facts=(fact,)),)
        return ()

    def events(self,committed:Iterable[StoredEvent],graph:EngineeringGraph,representations:list[dict[str,Any]])->list[NarrationEvent]:
        result=[]
        for event in committed:
            for candidate in self.candidates(event,graph,representations):
                text=" ".join(candidate.text.split()[:self.MAX_WORDS])
                digest=sha256(f"{event.project_id}|{event.event_id}|{candidate.kind.value}|{text}".encode()).hexdigest()[:20]
                result.append(NarrationEvent(f"narration-{digest}",event.project_id,event.revision,event.event_id,candidate.kind,text,
                    candidate.semantic_ids,candidate.verification_finding_ids,candidate.evidence_ids,candidate.priority,event.timestamp))
        return result

    @staticmethod
    def _candidate(kind,text,ids,priority=NarrationPriority.NORMAL,finding_ids=(),evidence_ids=(),facts=()):
        return NarrationCandidate(kind,text,tuple(dict.fromkeys(ids)),tuple(finding_ids),tuple(evidence_ids),priority,tuple(facts))
    @staticmethod
    def _names(graph,ids):
        names=[graph.entities[i].name for i in ids if i in graph.entities]
        return ", ".join(names) if names else "the affected design"
    @staticmethod
    def _numbers(text):return tuple(re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?",text))
