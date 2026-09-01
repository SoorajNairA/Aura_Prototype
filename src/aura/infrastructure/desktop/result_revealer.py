from __future__ import annotations

import ctypes
import logging
import os
import shutil
import subprocess
import time
import webbrowser
from pathlib import Path
from typing import Any

_logger = logging.getLogger("aura")

_SAFE_FILE_EXTENSIONS = {
    ".txt",
    ".md",
    ".json",
    ".csv",
    ".html",
    ".htm",
    ".css",
    ".js",
    ".py",
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
}

_UNSAFE_FILE_EXTENSIONS = {
    ".exe",
    ".com",
    ".bat",
    ".cmd",
    ".ps1",
    ".vbs",
    ".jscript",
    ".msi",
    ".scr",
    ".dll",
    ".sh",
}


class ResultRevealer:
    """Make successful AURA results visible using safe Windows operations."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def reveal_file(self, path: str | Path) -> bool:
        if not self.enabled:
            return False
        target = Path(path).expanduser().resolve()
        if not target.is_file() or not self._is_safe_file(target):
            _logger.info("REVEAL: file skipped path=%s safe=%s", target, self._is_safe_file(target))
            return False
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]
            _logger.info("REVEAL: file path=%s success=true", target)
            return True
        except Exception as exc:
            _logger.warning("REVEAL: file path=%s success=false error=%s", target, exc)
            return self.reveal_folder(target.parent, select=target)

    def reveal_folder(self, path: str | Path, select: str | Path | None = None) -> bool:
        if not self.enabled:
            return False
        target = Path(path).expanduser().resolve()
        if not target.is_dir():
            return False
        try:
            if select is not None:
                selected = Path(select).expanduser().resolve()
                subprocess.Popen(["explorer.exe", f"/select,{selected}"], shell=False)
            else:
                subprocess.Popen(["explorer.exe", str(target)], shell=False)
            self._focus_after_launch(process_names=("explorer.exe",))
            _logger.info("REVEAL: folder path=%s success=true", target)
            return True
        except Exception as exc:
            _logger.warning("REVEAL: folder path=%s success=false error=%s", target, exc)
            return False

    def reveal_application(self, process: Any) -> bool:
        if not self.enabled:
            return False
        pid = self._extract_pid(process)
        if pid is None:
            return False
        focused = self._focus_pid(pid)
        _logger.info("REVEAL: application pid=%s focused=%s", pid, str(focused).lower())
        return focused

    def reveal_url(self, url: str, open_url: bool = False) -> bool:
        if not self.enabled:
            return False
        opened = True
        if open_url:
            opened = bool(webbrowser.open(url))
        focused = self._focus_after_launch(
            process_names=("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe")
        )
        _logger.info(
            "REVEAL: url=%s opened=%s focused=%s",
            url,
            str(opened).lower(),
            str(focused).lower(),
        )
        return opened or focused

    def reveal_project(self, path: str | Path) -> tuple[bool, str]:
        if not self.enabled:
            return False, "disabled"
        target = Path(path).expanduser().resolve()
        if not target.is_dir():
            return False, "missing"

        vscode = self._resolve_vscode()
        if vscode is not None:
            try:
                process = subprocess.Popen([str(vscode), str(target)], shell=False)
                self._focus_after_launch(pid=process.pid, process_names=("Code.exe",))
                _logger.info("REVEAL: project path=%s method=vscode success=true", target)
                return True, "VS Code"
            except Exception as exc:
                _logger.warning("REVEAL: VS Code project open failed path=%s error=%s", target, exc)

        return self.reveal_folder(target), "Explorer"

    def _is_safe_file(self, path: Path) -> bool:
        suffix = path.suffix.lower()
        if suffix in _UNSAFE_FILE_EXTENSIONS:
            return False
        return suffix in _SAFE_FILE_EXTENSIONS

    def _extract_pid(self, process: Any) -> int | None:
        if isinstance(process, int):
            return process if process > 0 else None
        if isinstance(process, dict):
            value = process.get("pid")
            return int(value) if isinstance(value, int) and value > 0 else None
        value = getattr(process, "pid", None)
        return int(value) if isinstance(value, int) and value > 0 else None

    def _focus_after_launch(
        self,
        pid: int | None = None,
        process_names: tuple[str, ...] = (),
    ) -> bool:
        for _ in range(8):
            if pid is not None and self._focus_pid(pid):
                return True
            if process_names and self._focus_process_names(process_names):
                return True
            time.sleep(0.15)
        return False

    def _focus_pid(self, pid: int) -> bool:
        if os.name != "nt":
            return False
        user32 = ctypes.windll.user32
        found: list[int] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def callback(hwnd: int, lparam: int) -> bool:
            process_id = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            if process_id.value == pid and user32.IsWindowVisible(hwnd):
                found.append(hwnd)
                return False
            return True

        user32.EnumWindows(callback, 0)
        if not found:
            return False
        hwnd = found[0]
        user32.ShowWindow(hwnd, 9)
        return bool(user32.SetForegroundWindow(hwnd))

    def _focus_process_names(self, process_names: tuple[str, ...]) -> bool:
        if os.name != "nt":
            return False
        normalized = {name.lower() for name in process_names}
        try:
            output = subprocess.check_output(
                ["tasklist", "/fo", "csv", "/nh"],
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=3,
            )
        except Exception:
            return False
        for line in reversed(output.splitlines()):
            columns = [part.strip('"') for part in line.split('","')]
            if len(columns) < 2 or columns[0].lower() not in normalized:
                continue
            try:
                if self._focus_pid(int(columns[1])):
                    return True
            except ValueError:
                continue
        return False

    def _resolve_vscode(self) -> Path | None:
        for candidate in ("code.cmd", "Code.exe", "code.exe", "code"):
            found = shutil.which(candidate)
            if found:
                return Path(found)
        local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        for path in (
            local_app_data / "Programs" / "Microsoft VS Code" / "Code.exe",
            program_files / "Microsoft VS Code" / "Code.exe",
        ):
            if path.is_file():
                return path
        return None
