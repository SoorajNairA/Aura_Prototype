from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class PlanItem(BaseModel):
    id: str
    title: str
    owner: str = "AURA"
    due: Optional[str] = None
    dependencies: list[str] = Field(default_factory=list)
    risk: RiskLevel = RiskLevel.low
    execution_type: str = "analysis"
    status: str = "pending"


class GoalState(BaseModel):
    goal: str
    constraints: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    plan: list[PlanItem] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ActionRequest(BaseModel):
    action: str
    args: dict[str, Any] = Field(default_factory=dict)
    risk: RiskLevel = RiskLevel.low


class ActionResult(BaseModel):
    action: str
    ok: bool
    message: str
    output: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
