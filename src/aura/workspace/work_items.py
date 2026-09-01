from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4
from threading import RLock


class WorkState(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    ABANDONED = "ABANDONED"


VALID_TRANSITIONS: dict[WorkState, tuple[WorkState, ...]] = {
    WorkState.PLANNED: (WorkState.IN_PROGRESS, WorkState.SKIPPED, WorkState.ABANDONED),
    WorkState.IN_PROGRESS: (WorkState.PAUSED, WorkState.COMPLETED, WorkState.ABANDONED),
    WorkState.PAUSED: (WorkState.IN_PROGRESS, WorkState.SKIPPED, WorkState.ABANDONED),
    WorkState.COMPLETED: (), WorkState.SKIPPED: (), WorkState.ABANDONED: (),
}
REASON_REQUIRED = {WorkState.PAUSED, WorkState.SKIPPED, WorkState.ABANDONED}


class WorkDomainError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 422) -> None:
        super().__init__(message); self.code = code; self.message = message; self.status = status

    def to_dict(self) -> dict[str, Any]: return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class WorkStateTransition:
    from_state: WorkState
    to_state: WorkState
    reason: str | None
    timestamp: str
    actor: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"fromState": self.from_state.value, "toState": self.to_state.value,
                "reason": self.reason, "timestamp": self.timestamp, "actor": self.actor}


@dataclass(frozen=True)
class EngineeringWorkItem:
    id: str; project_id: str; title: str; description: str; category: str
    state: WorkState; related_component_ids: tuple[str, ...]; related_requirement_ids: tuple[str, ...]
    related_finding_ids: tuple[str, ...]; created_at: str; updated_at: str
    transition_history: tuple[WorkStateTransition, ...] = (); revision_id: str | None = None
    source: str = "manual"

    def to_dict(self) -> dict[str, Any]:
        return {"id":self.id,"projectId":self.project_id,"revisionId":self.revision_id,"title":self.title,
            "description":self.description,"category":self.category,"state":self.state.value,
            "relatedComponentIds":list(self.related_component_ids),"relatedRequirementIds":list(self.related_requirement_ids),
            "relatedFindingIds":list(self.related_finding_ids),"createdAt":self.created_at,"updatedAt":self.updated_at,
            "transitionHistory":[item.to_dict() for item in self.transition_history],"source":self.source,
            "allowedTransitions":[state.value for state in VALID_TRANSITIONS[self.state]],
            "currentReason":next((item.reason for item in reversed(self.transition_history) if item.to_state is self.state and item.reason),None)}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EngineeringWorkItem":
        history=tuple(WorkStateTransition(WorkState(x["fromState"]),WorkState(x["toState"]),x.get("reason"),x["timestamp"],x.get("actor")) for x in value.get("transitionHistory",()))
        item=cls(value["id"],value["projectId"],value["title"],value.get("description",""),value.get("category","engineering"),WorkState(value["state"]),
            tuple(value.get("relatedComponentIds",())),tuple(value.get("relatedRequirementIds",())),tuple(value.get("relatedFindingIds",())),
            value["createdAt"],value["updatedAt"],history,value.get("revisionId"),value.get("source","manual"))
        previous=WorkState.PLANNED; timestamp=""
        for transition in item.transition_history:
            if transition.from_state is not previous or transition.to_state not in VALID_TRANSITIONS[previous] or transition.timestamp < timestamp:
                raise WorkDomainError("WORK_HISTORY_INVALID","Persisted work history violates transition invariants")
            previous=transition.to_state;timestamp=transition.timestamp
        if previous is not item.state:raise WorkDomainError("WORK_HISTORY_INVALID","Persisted work state does not match transition history")
        return item


class EngineeringWorkService:
    MAX_REASON_LENGTH = 1000
    def __init__(self, repository: Any) -> None: self.repository=repository;self._lock=RLock()

    def create(self, project_id: str, title: str, description: str = "", category: str = "engineering",
               related_component_ids: list[str] | None = None, related_requirement_ids: list[str] | None = None,
               related_finding_ids: list[str] | None = None, revision_id: str | None = None, source: str = "manual") -> EngineeringWorkItem:
        if self.repository.get_project(project_id) is None: raise WorkDomainError("WORK_PROJECT_NOT_FOUND","Project does not exist",status=404)
        title=title.strip(); description=description.strip()
        if not title or len(title)>200: raise WorkDomainError("WORK_TITLE_INVALID","Work title must contain 1 to 200 characters")
        graph=self.repository.get_project(project_id).graph
        def refs(values: list[str] | None, kinds: set[str], code: str) -> tuple[str,...]:
            result=tuple(dict.fromkeys(values or ()))
            if any(x not in graph.entities or graph.entities[x].kind.value not in kinds for x in result): raise WorkDomainError(code,"Related engineering entity is not part of this project")
            return result
        now=datetime.now(timezone.utc).isoformat()
        item=EngineeringWorkItem(f"work-{uuid4().hex}",project_id,title,description,category.strip() or "engineering",WorkState.PLANNED,
            refs(related_component_ids,{"component"},"WORK_COMPONENT_INVALID"),refs(related_requirement_ids,{"requirement"},"WORK_REQUIREMENT_INVALID"),
            tuple(dict.fromkeys(related_finding_ids or ())),now,now,revision_id=revision_id,source=source)
        self.repository.save_work_item(item.to_dict()); return item

    def list(self, project_id: str) -> list[EngineeringWorkItem]:
        return [EngineeringWorkItem.from_dict(x) for x in self.repository.list_work_items(project_id)]

    def get(self, project_id: str, work_item_id: str) -> EngineeringWorkItem:
        value=self.repository.get_work_item(project_id,work_item_id)
        if value is None: raise WorkDomainError("WORK_ITEM_NOT_FOUND","Work item was not found in this project",status=404)
        return EngineeringWorkItem.from_dict(value)

    def transition(self, project_id: str, work_item_id: str, target_state: str, reason: str | None = None, actor: str | None = None) -> EngineeringWorkItem:
        with self._lock:
            item=self.get(project_id,work_item_id)
            try: target=WorkState(target_state)
            except ValueError as exc: raise WorkDomainError("WORK_STATE_INVALID","Unknown work state") from exc
            if target not in VALID_TRANSITIONS[item.state]:
                raise WorkDomainError("WORK_TRANSITION_INVALID",f"{item.state.value.replace('_',' ').title()} work cannot transition directly to {target.value.replace('_',' ').title()}.")
            normalized=reason.strip() if reason else None
            if target in REASON_REQUIRED and not normalized: raise WorkDomainError("WORK_REASON_REQUIRED",f"A reason is required before work can be {target.value.lower()}.")
            if normalized and len(normalized)>self.MAX_REASON_LENGTH: raise WorkDomainError("WORK_REASON_INVALID",f"Reason must not exceed {self.MAX_REASON_LENGTH} characters")
            now=datetime.now(timezone.utc).isoformat(); transition=WorkStateTransition(item.state,target,normalized,now,actor.strip() if actor and actor.strip() else None)
            updated=replace(item,state=target,updated_at=now,transition_history=(*item.transition_history,transition))
            self.repository.save_work_item(updated.to_dict()); return updated

    def summary(self, project_id: str) -> dict[str, Any]:
        items=self.list(project_id); counts={state.value:sum(x.state is state for x in items) for state in WorkState}
        return {"total":len(items),"counts":counts}
