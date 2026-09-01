from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from aura.legacy.assistant.models import ActionRequest, RiskLevel


@dataclass(frozen=True)
class PathSafetyDecision:
    decision: str
    target: Path
    reason: str
    risk: RiskLevel

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"

    @property
    def requires_confirmation(self) -> bool:
        return self.decision == "confirm"

    @property
    def denied(self) -> bool:
        return self.decision == "deny"


class SafetyLayer:
    HIGH_RISK_ACTIONS = {
        "send_email",
        "purchase_item",
        "delete_path",
        "publish_post",
    }

    def classify(self, action: str) -> RiskLevel:
        if action in self.HIGH_RISK_ACTIONS:
            return RiskLevel.high
        return RiskLevel.low

    def requires_confirmation(self, request: ActionRequest) -> bool:
        return request.risk == RiskLevel.high

    def requires_path_confirmation(
        self,
        action: str,
        path: str,
        workspace_root: Path,
        approved_roots: tuple[Path, ...] = (),
    ) -> bool:
        """Return True when a filesystem mutation crosses a trust boundary."""
        return self.assess_path(action, path, workspace_root, approved_roots).requires_confirmation

    def assess_path(
        self,
        action: str,
        path: str,
        workspace_root: Path,
        approved_roots: tuple[Path, ...] = (),
    ) -> PathSafetyDecision:
        if action not in {"create_folder", "create_file", "write_text_file"}:
            return PathSafetyDecision("allow", Path(path), "Action has no filesystem mutation.", RiskLevel.low)

        raw = str(path).strip()
        if not raw:
            return PathSafetyDecision("deny", Path("."), "Path cannot be empty.", RiskLevel.high)

        workspace = workspace_root.expanduser().resolve()
        raw_path = Path(raw).expanduser()
        scoped_path = raw_path if raw_path.is_absolute() else workspace / raw_path
        roots = self._approved_roots(workspace, approved_roots)

        try:
            target = scoped_path.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            return PathSafetyDecision("deny", scoped_path, f"Path cannot be resolved safely: {exc}", RiskLevel.high)

        if self._has_traversal(raw_path) and not self._is_inside_any(target, roots):
            return PathSafetyDecision("deny", target, "Path traversal escapes the approved workspace.", RiskLevel.high)

        if self._touches_reparse_escape(scoped_path, roots):
            return PathSafetyDecision("deny", target, "Path crosses a symlink or junction outside approved scope.", RiskLevel.high)

        if self._is_sensitive_path(target):
            return PathSafetyDecision("deny", target, "Path targets a sensitive system or credential location.", RiskLevel.high)

        if self._is_inside_any(target, roots):
            if action == "create_file" and target.exists():
                return PathSafetyDecision("confirm", target, "Existing file requires replacement approval.", RiskLevel.medium)
            if action == "write_text_file" and target.is_file() and target.stat().st_size > 0:
                return PathSafetyDecision("confirm", target, "Existing file content requires overwrite approval.", RiskLevel.medium)
            return PathSafetyDecision("allow", target, "Path is inside approved workspace.", RiskLevel.low)

        return PathSafetyDecision("confirm", target, "Path is outside approved workspace.", RiskLevel.medium)

    def _approved_roots(self, workspace_root: Path, approved_roots: tuple[Path, ...]) -> tuple[Path, ...]:
        roots = [workspace_root]
        roots.extend(root.expanduser().resolve() for root in approved_roots)
        unique: list[Path] = []
        for root in roots:
            if root not in unique:
                unique.append(root)
        return tuple(unique)

    def _has_traversal(self, path: Path) -> bool:
        return any(part == ".." for part in path.parts)

    def _is_inside_any(self, target: Path, roots: tuple[Path, ...]) -> bool:
        for root in roots:
            try:
                if target == root or target.is_relative_to(root):
                    return True
            except ValueError:
                continue
        return False

    def _touches_reparse_escape(self, raw_path: Path, roots: tuple[Path, ...]) -> bool:
        probe = Path(raw_path.anchor) if raw_path.is_absolute() and raw_path.anchor else Path.cwd()
        parts = raw_path.parts
        if raw_path.is_absolute() and raw_path.anchor:
            parts = parts[1:]
        for part in parts:
            if part in {"", "."}:
                continue
            probe = probe / part
            try:
                if probe.exists() and (probe.is_symlink() or self._is_windows_reparse_point(probe)):
                    resolved = probe.resolve(strict=False)
                    if not self._is_inside_any(resolved, roots):
                        return True
            except OSError:
                return True
        return False

    def _is_windows_reparse_point(self, path: Path) -> bool:
        if os.name != "nt":
            return False
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction):
            try:
                if is_junction():
                    return True
            except OSError:
                return True
        try:
            return bool(path.lstat().st_file_attributes & 0x400)
        except (AttributeError, OSError):
            return False

    def _is_sensitive_path(self, target: Path) -> bool:
        text = str(target).lower()
        sensitive_markers = (
            "\\windows",
            "\\program files",
            "\\program files (x86)",
            "\\programdata",
            "\\appdata\\roaming\\microsoft\\windows\\start menu",
            "\\.ssh",
            "\\.gnupg",
            "\\credentials",
            "\\system32",
        )
        if any(marker in text for marker in sensitive_markers):
            return True
        drive_root = target.anchor and str(target) == target.anchor
        return bool(drive_root)
