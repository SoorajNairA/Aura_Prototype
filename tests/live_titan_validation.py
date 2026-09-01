"""Live Project PROVING GROUNDS runner.

This script requires a real Unreal Engine installation. It does not mock,
simulate, or mark benchmarks as passed without live execution.

Usage:
    python tests/live_titan_validation.py --live
    python tests/live_titan_validation.py --live --only A01 J01 K01
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aura.legacy.unreal.titan_validation import TitanValidationSuite, UnrealEnvironment  # noqa: E402


ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Run TITAN live Unreal validation benchmarks.")
    parser.add_argument("--live", action="store_true", help="Required for live Unreal execution.")
    parser.add_argument("--editor", type=Path, default=None, help="Path to UnrealEditor-Cmd.exe or UnrealEditor.exe.")
    parser.add_argument("--workspace", type=Path, default=None, help="Disposable validation workspace.")
    parser.add_argument("--only", nargs="*", default=None, help="Benchmark IDs to run, such as A01 J01 K01.")
    args = parser.parse_args()

    env = UnrealEnvironment(editor_path=args.editor, workspace=args.workspace)
    suite = TitanValidationSuite(ROOT / "logs", environment=env)
    report = suite.run(live=args.live, selected=args.only)
    print(f"TITAN validation dashboard: {suite.dashboard_path}")
    print(f"TITAN validation results: {suite.results_path}")
    print(f"Pass rate: {report.pass_rate}%")
    print(f"Engineering score: {report.score.overall} ({report.score.grade})")
    if not args.live:
        print("Blocked: --live is required. No benchmark was treated as passed.")
        return 2
    if not env.available:
        print("Blocked: Unreal Editor was not found. Set --editor or AURA_UNREAL_EDITOR.")
        return 3
    return 0 if report.pass_rate >= 95.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
