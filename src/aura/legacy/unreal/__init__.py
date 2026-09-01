"""Explicit loader for the retained Unreal engineering experiment."""

from __future__ import annotations

from typing import Any


def create_unreal_domain(*args: Any, **kwargs: Any) -> Any:
    from aura.legacy.unreal.domain import UnrealProfessionalDomain

    return UnrealProfessionalDomain(*args, **kwargs)
