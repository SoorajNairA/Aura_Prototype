"""TEST 26 - Phase Omega TITAN autonomous validation suite."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aura.legacy.unreal.titan_validation import TitanValidationSuite, UnrealEnvironment  # noqa: E402


def main() -> None:
    print("=" * 60)
    print("TEST 26: TITAN Autonomous Validation Suite")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="aura_titan_validation_") as temp:
        root = Path(temp)
        env = UnrealEnvironment(editor_path=root / "MissingUnrealEditor.exe", workspace=root / "workspace")
        suite = TitanValidationSuite(root / "logs", environment=env)

        categories = {benchmark.category for benchmark in suite.benchmarks}
        expected = {
            "Editor Operation",
            "Project Understanding",
            "Blueprint Engineering",
            "Blueprint Logic",
            "Gameplay Systems",
            "AI",
            "Animation",
            "UI",
            "Input",
            "Documentation Intelligence",
            "Blueprint Intelligence",
            "Recovery",
            "Packaging",
            "Performance",
            "Long Engineering Task",
            "Autonomous Engineering",
            "Chaos",
        }
        assert expected <= categories
        assert any(benchmark.requires_packaging for benchmark in suite.benchmarks)
        assert any(benchmark.requires_pie for benchmark in suite.benchmarks)
        assert any(benchmark.chaos for benchmark in suite.benchmarks)
        print("  Benchmark category map: PASS")

        report = suite.run(live=False)
        assert report.live is False
        assert report.results
        assert all(result.status == "blocked" for result in report.results)
        assert all(not result.success for result in report.results)
        assert report.pass_rate == 0.0
        assert report.score.grade == "Blocked"
        assert report.dashboard["live_status"] == "not_live_blocked"
        assert suite.results_path.is_file()
        assert suite.dashboard_path.is_file()
        print("  No mocked success without live Unreal: PASS")

        payload = json.loads(suite.results_path.read_text(encoding="utf-8"))
        assert payload["project_name"] == "TitanValidationProject"
        assert payload["dashboard"]["blocked"] == len(suite.benchmarks)
        assert payload["average_confidence"] == 0.0
        assert "Overall" not in suite.dashboard_path.read_text(encoding="utf-8") or "Engineering score" in suite.dashboard_path.read_text(encoding="utf-8")
        print("  Report and dashboard generation: PASS")

        selected = suite.run(live=True, selected=["A01"])
        assert len(selected.results) == 1
        assert selected.results[0].benchmark_id == "A01"
        assert selected.results[0].status == "blocked"
        assert "Unreal Editor" in selected.results[0].errors[0]
        print("  Missing Unreal blocks live run safely: PASS")

    print("  TEST 26 PASS")


if __name__ == "__main__":
    main()
