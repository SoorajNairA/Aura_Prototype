from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .llm import LLMService
from .models import GoalState, PlanItem, RiskLevel


class PlannerAgent:
    def __init__(self, llm: LLMService) -> None:
        self.llm = llm

    def create_plan(self, goal: str, known_constraints: dict) -> GoalState:
        fallback = {
            "constraints": known_constraints,
            "tasks": [
                {
                    "id": "T1",
                    "title": "Clarify objective scope and timeline",
                    "owner": "AURA",
                    "risk": "low",
                    "execution_type": "analysis",
                },
                {
                    "id": "T2",
                    "title": "Build budget, milestones, and dependencies",
                    "owner": "AURA",
                    "risk": "low",
                    "execution_type": "planning",
                },
                {
                    "id": "T3",
                    "title": "Execute highest-impact low-risk actions first",
                    "owner": "AURA",
                    "risk": "medium",
                    "execution_type": "execution",
                },
            ],
        }

        payload = self.llm.generate_json(
            system_prompt=(
                "You are Planner Agent in AURA. Decompose goals into actionable tasks "
                "with owner, risk (low|medium|high), dependencies, and execution_type."
            ),
            user_prompt=f"Goal: {goal}\nConstraints: {known_constraints}",
            fallback=fallback,
        )

        tasks = payload.get("tasks", fallback["tasks"])
        constraints = payload.get("constraints", known_constraints)

        plan = [
            PlanItem(
                id=t.get("id", f"T{i+1}"),
                title=t.get("title", "Unnamed task"),
                owner=t.get("owner", "AURA"),
                due=t.get("due"),
                dependencies=t.get("dependencies", []),
                risk=RiskLevel(t.get("risk", "low")),
                execution_type=t.get("execution_type", "analysis"),
                status="pending",
            )
            for i, t in enumerate(tasks)
        ]

        now = datetime.now(timezone.utc).isoformat()
        return GoalState(
            goal=goal,
            constraints=constraints,
            context={"source": "voice"},
            plan=plan,
            created_at=now,
            updated_at=now,
        )

    def critique_and_revise(self, goal_state: GoalState, world_state: dict[str, Any]) -> GoalState:
        plan_payload = [item.model_dump() for item in goal_state.plan]
        critique = self.llm.critique_plan(goal_state.goal, plan_payload, world_state)
        revised = critique.get("revised_tasks", plan_payload)
        if isinstance(revised, list) and revised:
            goal_state.plan = [
                PlanItem(
                    id=t.get("id", f"T{i+1}"),
                    title=t.get("title", "Unnamed task"),
                    owner=t.get("owner", "AURA"),
                    due=t.get("due"),
                    dependencies=t.get("dependencies", []),
                    risk=RiskLevel(t.get("risk", "low")),
                    execution_type=t.get("execution_type", "analysis"),
                    status=t.get("status", "pending"),
                )
                for i, t in enumerate(revised)
            ]

        goal_state.context["critic"] = {
            "risks": critique.get("risks", []),
            "improvements": critique.get("improvements", []),
        }
        goal_state.updated_at = datetime.now(timezone.utc).isoformat()
        return goal_state

    def replan_after_failure(self, goal_state: GoalState, failed_task_id: str, reason: str) -> GoalState:
        fallback = {
            "tasks": [
                {
                    "id": f"{failed_task_id}-ALT1",
                    "title": f"Alternative path after failure: {reason}",
                    "risk": "low",
                    "execution_type": "analysis",
                }
            ]
        }

        payload = self.llm.generate_json(
            system_prompt=(
                "You are Planner Agent. A task failed. Propose replacement tasks that "
                "keep the same high-level objective moving."
            ),
            user_prompt=(
                f"Goal: {goal_state.goal}\n"
                f"Failed task: {failed_task_id}\n"
                f"Reason: {reason}\n"
                f"Current constraints: {goal_state.constraints}"
            ),
            fallback=fallback,
        )

        new_tasks = payload.get("tasks", fallback["tasks"])
        for i, t in enumerate(new_tasks):
            goal_state.plan.append(
                PlanItem(
                    id=t.get("id", f"R{i+1}"),
                    title=t.get("title", "Fallback task"),
                    owner=t.get("owner", "AURA"),
                    due=t.get("due"),
                    dependencies=t.get("dependencies", []),
                    risk=RiskLevel(t.get("risk", "low")),
                    execution_type=t.get("execution_type", "analysis"),
                    status="pending",
                )
            )

        goal_state.updated_at = datetime.now(timezone.utc).isoformat()
        return goal_state
