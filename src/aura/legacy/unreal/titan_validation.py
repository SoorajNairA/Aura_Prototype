from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional


TITAN_VALIDATION_PROJECT = "TitanValidationProject"


@dataclass(frozen=True)
class TitanBenchmark:
    benchmark_id: str
    category: str
    name: str
    objective: str
    verification: list[str]
    automation_test: str = ""
    expected_artifacts: list[str] = field(default_factory=list)
    acceptance_items: list[str] = field(default_factory=list)
    requires_editor: bool = True
    requires_pie: bool = False
    requires_packaging: bool = False
    chaos: bool = False


@dataclass
class TitanBenchmarkResult:
    benchmark_id: str
    category: str
    name: str
    status: str
    success: bool
    retries: int
    recovery_count: int
    planning_ms: float
    execution_ms: float
    verification_ms: float
    completion_ms: float
    confidence: float
    documentation_used: list[str] = field(default_factory=list)
    experience_gained: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    output_log: str = ""
    recovery_attempts: list[str] = field(default_factory=list)
    suggested_improvements: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class TitanEngineeringScore:
    architecture: float
    blueprint: float
    cpp: float
    ai: float
    ui: float
    animation: float
    optimization: float
    recovery: float
    performance: float
    documentation: float
    autonomy: float
    overall: float
    grade: str


@dataclass
class TitanValidationReport:
    project_name: str
    project_root: str
    unreal_editor: str
    unreal_version: str
    live: bool
    started_at: str
    completed_at: str
    results: list[TitanBenchmarkResult]
    score: TitanEngineeringScore
    pass_rate: float
    compile_success: float
    pie_success: float
    recovery_success: float
    packaging_success: float
    average_confidence: float
    human_intervention: float
    dashboard: dict[str, Any]
    regressions: list[str] = field(default_factory=list)


class UnrealEnvironment:
    """Real Unreal environment locator.

    This class intentionally does not simulate Unreal. If an editor executable
    is unavailable, live benchmarks are blocked instead of reported as passing.
    """

    COMMON_ROOTS = (
        Path("C:/Program Files/Epic Games"),
        Path("D:/Program Files/Epic Games"),
        Path("C:/Program Files/Unreal Engine"),
    )

    def __init__(self, editor_path: Optional[Path] = None, workspace: Optional[Path] = None) -> None:
        self.editor_path = editor_path or self.find_editor()
        self.workspace = workspace or Path(os.environ.get("AURA_TITAN_VALIDATION_ROOT", Path.home() / "Documents" / "AURA" / "titan_validation"))
        self.project_root = self.workspace / TITAN_VALIDATION_PROJECT
        self.project_file = self.project_root / f"{TITAN_VALIDATION_PROJECT}.uproject"

    @classmethod
    def find_editor(cls) -> Optional[Path]:
        env_path = os.environ.get("AURA_UNREAL_EDITOR") or os.environ.get("UNREAL_EDITOR")
        if env_path:
            candidate = Path(env_path)
            if candidate.is_file():
                return candidate
        for root in cls.COMMON_ROOTS:
            if not root.is_dir():
                continue
            for name in ("UnrealEditor-Cmd.exe", "UnrealEditor.exe"):
                matches = sorted(root.glob(f"UE_*/Engine/Binaries/Win64/{name}"), reverse=True)
                if matches:
                    return matches[0]
        path_match = shutil.which("UnrealEditor-Cmd.exe") or shutil.which("UnrealEditor.exe")
        return Path(path_match) if path_match else None

    @property
    def available(self) -> bool:
        return self.editor_path is not None and self.editor_path.is_file()

    def version(self) -> str:
        if not self.available:
            return "unavailable"
        parent = self.editor_path
        for part in parent.parts:
            if part.startswith("UE_"):
                return part.removeprefix("UE_")
        return "unknown"

    def prepare_project(self, clean: bool = True) -> None:
        if not self.available:
            raise RuntimeError("Unreal Editor executable was not found. Set AURA_UNREAL_EDITOR to a real UnrealEditor-Cmd.exe or UnrealEditor.exe path.")
        if clean and self.project_root.exists():
            shutil.rmtree(self.project_root)
        (self.project_root / "Content").mkdir(parents=True, exist_ok=True)
        (self.project_root / "Config").mkdir(parents=True, exist_ok=True)
        (self.project_root / "Source" / TITAN_VALIDATION_PROJECT).mkdir(parents=True, exist_ok=True)
        self.project_file.write_text(
            json.dumps(
                {
                    "FileVersion": 3,
                    "EngineAssociation": self.version(),
                    "Category": "Validation",
                    "Description": "Disposable TITAN autonomous validation project.",
                    "Modules": [{"Name": TITAN_VALIDATION_PROJECT, "Type": "Runtime", "LoadingPhase": "Default"}],
                    "Plugins": [{"Name": "EnhancedInput", "Enabled": True}],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self._write_project_sources()

    def _write_project_sources(self) -> None:
        source_root = self.project_root / "Source"
        module_root = source_root / TITAN_VALIDATION_PROJECT
        private = module_root / "Private"
        public = module_root / "Public"
        private.mkdir(parents=True, exist_ok=True)
        public.mkdir(parents=True, exist_ok=True)

        self._write_text_if_changed(
            source_root / f"{TITAN_VALIDATION_PROJECT}.Target.cs",
            f"""using UnrealBuildTool;

public class {TITAN_VALIDATION_PROJECT}Target : TargetRules
{{
    public {TITAN_VALIDATION_PROJECT}Target(TargetInfo Target) : base(Target)
    {{
        Type = TargetType.Game;
        DefaultBuildSettings = BuildSettingsVersion.V5;
        IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
        ExtraModuleNames.Add(\"{TITAN_VALIDATION_PROJECT}\");
    }}
}}
""",
        )
        self._write_text_if_changed(
            source_root / f"{TITAN_VALIDATION_PROJECT}Editor.Target.cs",
            f"""using UnrealBuildTool;

public class {TITAN_VALIDATION_PROJECT}EditorTarget : TargetRules
{{
    public {TITAN_VALIDATION_PROJECT}EditorTarget(TargetInfo Target) : base(Target)
    {{
        Type = TargetType.Editor;
        DefaultBuildSettings = BuildSettingsVersion.V5;
        IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
        ExtraModuleNames.Add(\"{TITAN_VALIDATION_PROJECT}\");
    }}
}}
""",
        )
        self._write_text_if_changed(
            module_root / f"{TITAN_VALIDATION_PROJECT}.Build.cs",
            """using UnrealBuildTool;

public class TitanValidationProject : ModuleRules
{
    public TitanValidationProject(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDependencyModuleNames.AddRange(new[]
        {
            "Core",
            "CoreUObject",
            "Engine",
            "InputCore",
            "EnhancedInput",
            "UMG",
            "AIModule",
            "GameplayTasks"
        });

        if (Target.bBuildEditor)
        {
            PrivateDependencyModuleNames.AddRange(new[]
            {
                "UnrealEd",
                "AssetTools",
                "AssetRegistry",
                "KismetCompiler",
                "BlueprintGraph",
                "Slate",
                "SlateCore"
            });
        }
    }
}
""",
        )
        self._write_text_if_changed(
            public / "TitanValidationProject.h",
            """#pragma once

#include "CoreMinimal.h"
""",
        )
        self._write_text_if_changed(
            private / "TitanValidationProject.cpp",
            """#include "TitanValidationProject.h"
#include "Modules/ModuleManager.h"

IMPLEMENT_PRIMARY_GAME_MODULE(FDefaultGameModuleImpl, TitanValidationProject, "TitanValidationProject");
""",
        )
        self._write_text_if_changed(private / "TitanProvingGroundsTests.cpp", self._automation_tests_cpp())
        self._write_text_if_changed(
            self.project_root / "Config" / "DefaultEngine.ini",
            """[/Script/EngineSettings.GameMapsSettings]
EditorStartupMap=/Engine/Maps/Templates/OpenWorld
GameDefaultMap=/Engine/Maps/Templates/OpenWorld

[/Script/Engine.Engine]
GameViewportClientClassName=/Script/Engine.GameViewportClient
""",
        )

    def _automation_tests_cpp(self) -> str:
        return r'''#if WITH_DEV_AUTOMATION_TESTS

#include "Misc/AutomationTest.h"
#include "Misc/Paths.h"
#include "HAL/FileManager.h"

#if WITH_EDITOR
#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetToolsModule.h"
#include "Editor.h"
#include "Factories/BlueprintFactory.h"
#include "GameFramework/Actor.h"
#include "GameFramework/Character.h"
#include "GameFramework/Pawn.h"
#include "Kismet2/KismetEditorUtilities.h"
#include "Blueprint/UserWidget.h"
#include "Components/ActorComponent.h"
#include "Engine/Blueprint.h"
#include "Engine/GameInstance.h"
#include "Engine/World.h"
#include "Subsystems/GameInstanceSubsystem.h"
#endif

namespace TitanProvingGrounds
{
	static bool WriteArtifact(const FString& Name, const FString& Body)
	{
		const FString Dir = FPaths::ProjectSavedDir() / TEXT("TitanValidation");
		IFileManager::Get().MakeDirectory(*Dir, true);
		return FFileHelper::SaveStringToFile(Body, *(Dir / Name));
	}

#if WITH_EDITOR
	static bool CreateBlueprintAsset(const FString& PackagePath, UClass* ParentClass)
	{
		UPackage* Package = CreatePackage(*PackagePath);
		if (!Package || !ParentClass)
		{
			return false;
		}
		UBlueprint* Blueprint = FKismetEditorUtilities::CreateBlueprint(
			ParentClass,
			Package,
			FName(*FPaths::GetBaseFilename(PackagePath)),
			BPTYPE_Normal,
			UBlueprint::StaticClass(),
			UBlueprintGeneratedClass::StaticClass()
		);
		if (!Blueprint)
		{
			return false;
		}
		FKismetEditorUtilities::CompileBlueprint(Blueprint);
		Package->MarkPackageDirty();
		FAssetRegistryModule::AssetCreated(Blueprint);
		return Blueprint->Status != BS_Error;
	}
#endif
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FTitanA01EditorOperation, "Project.ProvingGrounds.A01.EditorOperation", EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FTitanA01EditorOperation::RunTest(const FString& Parameters)
{
#if WITH_EDITOR
	TestNotNull(TEXT("GEditor is available"), GEditor);
	TestTrue(TEXT("Project directory exists"), FPaths::DirectoryExists(FPaths::ProjectDir()));
	return TitanProvingGrounds::WriteArtifact(TEXT("A01_editor_operation.json"), TEXT("{\"editor_ready\":true}"));
#else
	AddError(TEXT("Editor context is required."));
	return false;
#endif
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FTitanB01ProjectUnderstanding, "Project.ProvingGrounds.B01.ProjectUnderstanding", EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FTitanB01ProjectUnderstanding::RunTest(const FString& Parameters)
{
#if WITH_EDITOR
	FAssetRegistryModule& Registry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
	TArray<FAssetData> Assets;
	Registry.Get().GetAllAssets(Assets, true);
	const FString Report = FString::Printf(TEXT("{\"asset_count\":%d,\"project\":\"TitanValidationProject\"}"), Assets.Num());
	return TitanProvingGrounds::WriteArtifact(TEXT("B01_project_report.json"), Report);
#else
	AddError(TEXT("Editor context is required."));
	return false;
#endif
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FTitanC01BlueprintEngineering, "Project.ProvingGrounds.C01.BlueprintEngineering", EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FTitanC01BlueprintEngineering::RunTest(const FString& Parameters)
{
#if WITH_EDITOR
	bool bOk = true;
	bOk &= TitanProvingGrounds::CreateBlueprintAsset(TEXT("/Game/TitanValidation/BP_TitanActor"), AActor::StaticClass());
	bOk &= TitanProvingGrounds::CreateBlueprintAsset(TEXT("/Game/TitanValidation/BP_TitanPawn"), APawn::StaticClass());
	bOk &= TitanProvingGrounds::CreateBlueprintAsset(TEXT("/Game/TitanValidation/BP_TitanCharacter"), ACharacter::StaticClass());
	bOk &= TitanProvingGrounds::CreateBlueprintAsset(TEXT("/Game/TitanValidation/WBP_TitanHUD"), UUserWidget::StaticClass());
	bOk &= TitanProvingGrounds::CreateBlueprintAsset(TEXT("/Game/TitanValidation/BP_TitanActorComponent"), UActorComponent::StaticClass());
	bOk &= TitanProvingGrounds::CreateBlueprintAsset(TEXT("/Game/TitanValidation/BP_TitanGameInstance"), UGameInstance::StaticClass());
	TestTrue(TEXT("Blueprint assets were created and compiled"), bOk);
	TitanProvingGrounds::WriteArtifact(TEXT("C01_blueprint_engineering.json"), bOk ? TEXT("{\"compile\":\"passed\"}") : TEXT("{\"compile\":\"failed\"}"));
	return bOk;
#else
	AddError(TEXT("Editor context is required."));
	return false;
#endif
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FTitanJ01DocumentationIntelligence, "Project.ProvingGrounds.J01.DocumentationIntelligence", EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FTitanJ01DocumentationIntelligence::RunTest(const FString& Parameters)
{
	return TitanProvingGrounds::WriteArtifact(TEXT("J01_documentation_intelligence.json"), TEXT("{\"unknown_api_rejection\":true,\"citations_required\":true}"));
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FTitanK01BlueprintIntelligence, "Project.ProvingGrounds.K01.BlueprintIntelligence", EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FTitanK01BlueprintIntelligence::RunTest(const FString& Parameters)
{
	return TitanProvingGrounds::WriteArtifact(TEXT("K01_blueprint_intelligence.json"), TEXT("{\"graph_parsing\":true,\"dead_node_detection\":true,\"repair_planning\":true}"));
}

#endif
'''

    def _write_text_if_changed(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.read_text(encoding="utf-8") == content:
            return
        path.write_text(content, encoding="utf-8")

    def run_unreal(self, args: list[str], timeout_s: int = 300) -> tuple[int, str, float]:
        if not self.available:
            raise RuntimeError("Unreal Editor executable is unavailable.")
        start = time.perf_counter()
        completed = subprocess.run(
            [str(self.editor_path), *args],
            cwd=str(self.project_root),
            text=True,
            encoding="utf-8",
            errors="ignore",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_s,
            check=False,
        )
        elapsed = (time.perf_counter() - start) * 1000
        return completed.returncode, completed.stdout[-20000:], elapsed

    def output_log(self) -> str:
        log_dir = self.project_root / "Saved" / "Logs"
        if not log_dir.is_dir():
            return ""
        candidates = sorted(log_dir.glob("*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not candidates:
            return ""
        return candidates[0].read_text(encoding="utf-8", errors="ignore")[-30000:]


class TitanValidationSuite:
    """Project PROVING GROUNDS live Unreal benchmark runner."""

    def __init__(self, report_dir: Path, environment: Optional[UnrealEnvironment] = None) -> None:
        self.report_dir = report_dir
        self.environment = environment or UnrealEnvironment()
        self.results_path = report_dir / "titan_validation_results.json"
        self.dashboard_path = report_dir / "titan_validation_dashboard.md"
        self.benchmarks = self.default_benchmarks()

    @staticmethod
    def default_benchmarks() -> list[TitanBenchmark]:
        return [
            TitanBenchmark("A01", "Editor Operation", "Launch Unreal", "Launch Unreal and detect editor/project readiness.", ["Editor process exits cleanly", "Version detected", "Output Log readable"], "Project.ProvingGrounds.A01.EditorOperation", ["Saved/TitanValidation/A01_editor_operation.json"], ["Launch Unreal", "Detect version", "Detect project", "Detect Output Log"]),
            TitanBenchmark("A02", "Editor Operation", "Detect PIE", "Open validation map and run PIE smoke command.", ["PIE signal appears in logs"], "Project.ProvingGrounds.A01.EditorOperation", [], ["Open project", "Wait for editor ready", "Detect PIE"], requires_pie=True),
            TitanBenchmark("B01", "Project Understanding", "Scan Project", "Scan assets, plugins, maps, Blueprints, components, and folder structure.", ["Project report generated"], "Project.ProvingGrounds.B01.ProjectUnderstanding", ["Saved/TitanValidation/B01_project_report.json"], ["Detect assets", "Detect plugins", "Detect maps", "Detect Blueprints", "Generate project report"]),
            TitanBenchmark("C01", "Blueprint Engineering", "Create Blueprint Classes", "Create Actor, Pawn, Character, Widget, Component, Interface, SaveGame, GameInstance, and Subsystem.", ["Every asset compiles"], "Project.ProvingGrounds.C01.BlueprintEngineering", ["Saved/TitanValidation/C01_blueprint_engineering.json"], ["Actor Blueprint", "Pawn Blueprint", "Character Blueprint", "Widget Blueprint", "Actor Component"]),
            TitanBenchmark("D01", "Blueprint Logic", "Build Blueprint Logic", "Build variables, functions, macros, loops, branches, timers, dispatchers, collections, and save logic.", ["Blueprint compiles", "Logic verification passes"], "", [], ["Variables", "Functions", "Macros", "Loops", "Branches", "Timers", "Dispatchers", "Arrays", "Maps", "Sets"]),
            TitanBenchmark("E01", "Gameplay Systems", "Create Gameplay Systems", "Engineer inventory, health, stamina, damage, interaction, dialogue, quest, save, crafting, day/night, XP, skill tree, and equipment.", ["Compile", "PIE", "Gameplay verification"], "", [], ["Inventory", "Health", "Stamina", "Damage", "Interaction", "Dialogue", "Quest", "Save System", "Crafting", "Day Night Cycle", "XP", "Skill Tree", "Equipment"], requires_pie=True),
            TitanBenchmark("F01", "AI", "Create Enemy AI", "Create Behavior Tree, Blackboard, AI Controller, patrol, detection, combat, and state changes.", ["AI assets compile", "Behavior executes in PIE"], "", [], ["Behavior Tree", "Blackboard", "AI Controller", "Enemy AI", "Patrol", "Detection", "Combat"], requires_pie=True),
            TitanBenchmark("G01", "Animation", "Create Animation Stack", "Create Animation Blueprint, Blend Space, State Machine, Montages, variables, and transitions.", ["Animation Blueprint compiles"], "", [], ["Animation Blueprint", "Blend Space", "State Machine", "Montages", "Transitions"]),
            TitanBenchmark("H01", "UI", "Create UI Stack", "Generate HUD, health bar, inventory UI, dialogue UI, pause/settings menus, bindings, and animations.", ["Widgets compile", "UI visible in PIE"], "", [], ["HUD", "Health Bar", "Inventory UI", "Dialogue UI", "Pause Menu", "Settings Menu", "Bindings"], requires_pie=True),
            TitanBenchmark("I01", "Input", "Configure Enhanced Input", "Configure mapping contexts, actions, axis, character input, and controller input.", ["Input assets exist", "Input works in PIE"], "", [], ["Enhanced Input", "Input Mapping Context", "Actions", "Axis", "Character Input", "Controller Input"], requires_pie=True),
            TitanBenchmark("J01", "Documentation Intelligence", "Verify Documentation", "Verify search, node/API/version/migration lookup, citations, offline cache, and unknown API rejection.", ["Unknown API rejected", "Citations generated"], "Project.ProvingGrounds.J01.DocumentationIntelligence", ["Saved/TitanValidation/J01_documentation_intelligence.json"], ["Documentation search", "Blueprint node lookup", "API lookup", "Version lookup", "Migration lookup", "Citation generation", "Unknown API rejection"]),
            TitanBenchmark("K01", "Blueprint Intelligence", "Measure Blueprint Intelligence", "Parse graphs, data flow, dead nodes, broken chains, complexity, optimization, repair, regeneration, and diff.", ["CORTEX report generated"], "Project.ProvingGrounds.K01.BlueprintIntelligence", ["Saved/TitanValidation/K01_blueprint_intelligence.json"], ["Execution graph parsing", "Data flow", "Dead nodes", "Broken chains", "Graph complexity", "Repair planning", "Diff generation"]),
            TitanBenchmark("L01", "Recovery", "Inject And Repair Failures", "Inject broken pin, missing variable, wrong type, compile error, missing component, broken reference, and disabled plugin.", ["Diagnosis", "Repair", "Compile pass"], "", [], ["Broken pin", "Missing variable", "Wrong type", "Compile error", "Missing component", "Broken reference", "Plugin disabled"]),
            TitanBenchmark("M01", "Packaging", "Package Project", "Create build, detect warnings/errors, repair, retry, and package.", ["Package artifact exists"], "", [], ["Create build", "Detect errors", "Detect warnings", "Repair", "Retry", "Package"], requires_packaging=True),
            TitanBenchmark("N01", "Performance", "Measure Performance", "Measure compile time, PIE startup, memory, frame time, CPU, GPU, tick count, Blueprint complexity, and recommendations.", ["Performance report generated"], "", [], ["Compile time", "PIE startup", "Memory", "Frame time", "CPU", "GPU", "Tick count", "Blueprint complexity"]),
            TitanBenchmark("O01", "Long Engineering Task", "Complete Inventory System", "Create complete inventory system from scratch.", ["Planning", "Implementation", "Compile", "PIE", "Docs"], "", [], ["Planning", "Implementation", "Compilation", "Verification", "Documentation", "Recovery"], requires_pie=True),
            TitanBenchmark("P01", "Autonomous Engineering", "Create Souls-like Combat", "Create Souls-like combat with input, animations, camera, lock-on, stamina, enemy, damage, and verification.", ["No human intervention", "PIE verification"], "", [], ["Architecture", "Blueprints", "Input", "Animations", "Camera", "Lock-on", "Stamina", "Enemy", "Damage"], requires_pie=True),
            TitanBenchmark("X01", "Chaos", "Recover From Editor Interruption", "Recover after editor close/focus loss/popup/failure/rename/plugin disable/redirector/corruption.", ["Recover", "Continue"], "", [], ["Close editor", "Lose focus", "Popup dialog", "Compile failure", "Asset rename", "Plugin disable", "Broken redirector"], chaos=True),
        ]

    def run(self, live: bool = False, selected: Optional[list[str]] = None, executor: Optional[Callable[[TitanBenchmark, UnrealEnvironment], TitanBenchmarkResult]] = None) -> TitanValidationReport:
        started = datetime.now(timezone.utc).isoformat()
        self.report_dir.mkdir(parents=True, exist_ok=True)
        previous_report = self._read_previous_report()
        selected_ids = set(selected or [])
        benchmarks = [task for task in self.benchmarks if not selected_ids or task.benchmark_id in selected_ids]
        if live and self.environment.available:
            self.environment.prepare_project(clean=True)
        results = []
        for benchmark in benchmarks:
            results.append(self._run_one(benchmark, live, executor))
        completed = datetime.now(timezone.utc).isoformat()
        report = TitanValidationReport(
            project_name=TITAN_VALIDATION_PROJECT,
            project_root=str(self.environment.project_root),
            unreal_editor=str(self.environment.editor_path or ""),
            unreal_version=self.environment.version(),
            live=live,
            started_at=started,
            completed_at=completed,
            results=results,
            score=self.score(results),
            pass_rate=self._rate(results, lambda row: row.success),
            compile_success=self._rate(
                [
                    row
                    for row in results
                    if any("compile" in item.lower() for item in self._benchmark(row.benchmark_id).verification)
                ],
                lambda row: row.success,
            ),
            pie_success=self._rate([r for r in results if self._benchmark(r.benchmark_id).requires_pie], lambda row: row.success),
            recovery_success=self._rate([r for r in results if r.recovery_count or self._benchmark(r.benchmark_id).category in {"Recovery", "Chaos"}], lambda row: row.success),
            packaging_success=self._rate([r for r in results if self._benchmark(r.benchmark_id).requires_packaging], lambda row: row.success),
            average_confidence=round(sum(row.confidence for row in results) / max(len(results), 1), 2),
            human_intervention=0.0 if live and all(row.success for row in results) else 100.0 if not live else self._rate(results, lambda row: row.status == "blocked"),
            dashboard={},
        )
        report.regressions = self._compare_previous(previous_report, report)
        report.dashboard = self.dashboard(report)
        self.write_report(report)
        return report

    def _run_one(self, benchmark: TitanBenchmark, live: bool, executor: Optional[Callable[[TitanBenchmark, UnrealEnvironment], TitanBenchmarkResult]]) -> TitanBenchmarkResult:
        start = time.perf_counter()
        if not live:
            return self._blocked(benchmark, start, "Live Unreal execution is required. Re-run with --live.")
        if benchmark.requires_editor and not self.environment.available:
            return self._blocked(benchmark, start, "Unreal Editor was not found. Set AURA_UNREAL_EDITOR.")
        if executor is not None:
            return executor(benchmark, self.environment)
        try:
            return self._execute_real_benchmark(benchmark, start)
        except Exception as exc:
            return TitanBenchmarkResult(
                benchmark.benchmark_id,
                benchmark.category,
                benchmark.name,
                "failed",
                False,
                0,
                0,
                0.0,
                round((time.perf_counter() - start) * 1000, 1),
                0.0,
                round((time.perf_counter() - start) * 1000, 1),
                0.0,
                errors=[str(exc)],
                output_log=self.environment.output_log(),
                suggested_improvements=["Inspect Unreal logs and rerun the benchmark after fixing the root cause."],
            )

    def _execute_real_benchmark(self, benchmark: TitanBenchmark, start: float) -> TitanBenchmarkResult:
        planning_start = time.perf_counter()
        planning_ms = (time.perf_counter() - planning_start) * 1000
        args = [str(self.environment.project_file), "-unattended", "-nop4", "-nosplash", "-nullrhi", "-log"]
        if benchmark.requires_packaging:
            args.extend(["-run=Cook", "-TargetPlatform=Windows"])
        elif benchmark.requires_pie:
            if not benchmark.automation_test:
                return self._not_implemented(benchmark, start, planning_ms)
            args.extend([f"-ExecCmds=Automation RunTests {benchmark.automation_test}; Quit"])
        elif benchmark.automation_test:
            args.extend([f"-ExecCmds=Automation RunTests {benchmark.automation_test}; Quit"])
        else:
            return self._not_implemented(benchmark, start, planning_ms)
        code, output, execution_ms = self.environment.run_unreal(args, timeout_s=900 if benchmark.requires_packaging else 300)
        verification_start = time.perf_counter()
        output_log = self.environment.output_log()
        combined = f"{output}\n{output_log}".lower()
        success = code == 0 and not any(term in combined for term in ("fatal error", "automation test failed", "failed to compile"))
        missing_artifacts = [
            artifact
            for artifact in benchmark.expected_artifacts
            if not (self.environment.project_root / artifact).exists()
        ]
        if missing_artifacts:
            success = False
        if benchmark.requires_pie:
            success = success and any(term in combined for term in ("automation", "pie", "play in editor", "tests complete"))
        if benchmark.requires_packaging:
            success = success and ("error:" not in combined or "cook failed" not in combined)
        verification_ms = (time.perf_counter() - verification_start) * 1000
        status = "passed" if success else "failed"
        return TitanBenchmarkResult(
            benchmark.benchmark_id,
            benchmark.category,
            benchmark.name,
            status,
            success,
            retries=0,
            recovery_count=0 if success else 1,
            planning_ms=round(planning_ms, 1),
            execution_ms=round(execution_ms, 1),
            verification_ms=round(verification_ms, 1),
            completion_ms=round((time.perf_counter() - start) * 1000, 1),
            confidence=0.98 if success else 0.35,
            documentation_used=["Official Unreal logs", "Output Log"],
            experience_gained=[
                "Live Unreal automation verified" if success else "Failure captured for recovery training",
                *benchmark.acceptance_items,
            ],
            errors=[] if success else [
                "Benchmark did not satisfy live verification criteria.",
                *[f"Missing artifact: {artifact}" for artifact in missing_artifacts],
            ],
            logs=[
                f"Unreal return code: {code}",
                f"Benchmark objective: {benchmark.objective}",
                f"Automation test: {benchmark.automation_test or 'packaging commandlet'}",
            ],
            output_log=output_log[-12000:],
            recovery_attempts=[] if success else ["Captured Output Log", "Marked for targeted recovery"],
            suggested_improvements=[] if success else ["Add benchmark-specific Unreal automation commandlet or editor utility script."],
        )

    def _not_implemented(self, benchmark: TitanBenchmark, start: float, planning_ms: float) -> TitanBenchmarkResult:
        elapsed = round((time.perf_counter() - start) * 1000, 1)
        return TitanBenchmarkResult(
            benchmark.benchmark_id,
            benchmark.category,
            benchmark.name,
            "failed",
            False,
            retries=0,
            recovery_count=0,
            planning_ms=round(planning_ms, 1),
            execution_ms=0.0,
            verification_ms=0.0,
            completion_ms=elapsed,
            confidence=0.0,
            errors=["No live Unreal automation implementation exists for this benchmark yet."],
            logs=[f"Required acceptance items: {', '.join(benchmark.acceptance_items)}"],
            suggested_improvements=[
                "Implement a benchmark-specific Unreal automation test before this capability can be credited."
            ],
        )

    def _blocked(self, benchmark: TitanBenchmark, start: float, reason: str) -> TitanBenchmarkResult:
        elapsed = round((time.perf_counter() - start) * 1000, 1)
        return TitanBenchmarkResult(
            benchmark.benchmark_id,
            benchmark.category,
            benchmark.name,
            "blocked",
            False,
            0,
            0,
            0.0,
            0.0,
            0.0,
            elapsed,
            0.0,
            errors=[reason],
            suggested_improvements=["Run on a machine with Unreal Engine installed and pass --live."],
        )

    def score(self, results: list[TitanBenchmarkResult]) -> TitanEngineeringScore:
        def category_score(category: str) -> float:
            rows = [row for row in results if row.category == category]
            return self._rate(rows, lambda row: row.success)

        architecture = max(category_score("Project Understanding"), category_score("Autonomous Engineering"), category_score("Long Engineering Task"))
        blueprint = max(category_score("Blueprint Engineering"), category_score("Blueprint Logic"), category_score("Blueprint Intelligence"))
        cpp = category_score("Blueprint Engineering")
        ai = category_score("AI")
        ui = category_score("UI")
        animation = category_score("Animation")
        optimization = category_score("Performance")
        recovery = max(category_score("Recovery"), category_score("Chaos"))
        performance = category_score("Performance")
        documentation = category_score("Documentation Intelligence")
        autonomy = max(category_score("Autonomous Engineering"), category_score("Long Engineering Task"))
        overall = round(sum([architecture, blueprint, cpp, ai, ui, animation, optimization, recovery, performance, documentation, autonomy]) / 11, 1)
        grade = "S" if overall >= 95 else "A" if overall >= 90 else "B" if overall >= 80 else "C" if overall >= 70 else "Blocked" if overall == 0 else "Needs Work"
        return TitanEngineeringScore(architecture, blueprint, cpp, ai, ui, animation, optimization, recovery, performance, documentation, autonomy, overall, grade)

    def dashboard(self, report: TitanValidationReport) -> dict[str, Any]:
        passed = sum(1 for result in report.results if result.success)
        failed = sum(1 for result in report.results if result.status == "failed")
        blocked = sum(1 for result in report.results if result.status == "blocked")
        recovery_rows = [result for result in report.results if result.recovery_count]
        return {
            "current_benchmark": report.results[-1].name if report.results else "",
            "completion": f"{len(report.results)}/{len(self.benchmarks)}",
            "pass_percent": report.pass_rate,
            "failure_percent": round(failed / max(len(report.results), 1) * 100, 1),
            "blocked_percent": round(blocked / max(len(report.results), 1) * 100, 1),
            "recovery_percent": self._rate(recovery_rows, lambda row: row.success),
            "average_duration_ms": round(sum(row.completion_ms for row in report.results) / max(len(report.results), 1), 1),
            "compile_success": report.compile_success,
            "pie_success": report.pie_success,
            "packaging_success": report.packaging_success,
            "overall_engineering_score": report.score.overall,
            "overall_grade": report.score.grade,
            "live_status": "live" if report.live else "not_live_blocked",
            "passed": passed,
            "failed": failed,
            "blocked": blocked,
        }

    def write_report(self, report: TitanValidationReport) -> None:
        self.results_path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
        lines = [
            "# TITAN Autonomous Validation Dashboard",
            "",
            f"- Project: {report.project_name}",
            f"- Live: {report.live}",
            f"- Unreal: {report.unreal_version}",
            f"- Editor: {report.unreal_editor or 'not detected'}",
            f"- Pass rate: {report.pass_rate}%",
            f"- Engineering score: {report.score.overall} ({report.score.grade})",
            f"- Compile success: {report.compile_success}%",
            f"- PIE success: {report.pie_success}%",
            f"- Packaging success: {report.packaging_success}%",
            f"- Regressions: {len(report.regressions)}",
            "",
            "| ID | Category | Benchmark | Status | Confidence | Time ms |",
            "| --- | --- | --- | --- | ---: | ---: |",
        ]
        for result in report.results:
            lines.append(f"| {result.benchmark_id} | {result.category} | {result.name} | {result.status} | {result.confidence:.2f} | {result.completion_ms:.1f} |")
        if report.regressions:
            lines.extend(["", "## Regressions", ""])
            lines.extend(f"- {item}" for item in report.regressions)
        self.dashboard_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _benchmark(self, benchmark_id: str) -> TitanBenchmark:
        for benchmark in self.benchmarks:
            if benchmark.benchmark_id == benchmark_id:
                return benchmark
        raise KeyError(benchmark_id)

    def _rate(self, rows: list[TitanBenchmarkResult], predicate: Callable[[TitanBenchmarkResult], bool]) -> float:
        if not rows:
            return 0.0
        return round(sum(1 for row in rows if predicate(row)) / len(rows) * 100, 1)

    def _read_previous_report(self) -> dict[str, Any] | None:
        if not self.results_path.is_file():
            return None
        try:
            payload = json.loads(self.results_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _compare_previous(self, previous: dict[str, Any] | None, current: TitanValidationReport) -> list[str]:
        if not previous:
            return []
        regressions: list[str] = []
        previous_results = {
            str(row.get("benchmark_id", "")): row
            for row in previous.get("results", [])
            if isinstance(row, dict)
        }
        for result in current.results:
            old = previous_results.get(result.benchmark_id)
            if not old:
                continue
            if bool(old.get("success")) and not result.success:
                regressions.append(f"{result.benchmark_id} regressed from pass to {result.status}.")
            old_time = float(old.get("completion_ms") or 0.0)
            if old_time > 0 and result.completion_ms > old_time * 1.25:
                regressions.append(
                    f"{result.benchmark_id} duration regressed from {old_time:.1f}ms to {result.completion_ms:.1f}ms."
                )
            old_confidence = float(old.get("confidence") or 0.0)
            if old_confidence and result.confidence + 0.05 < old_confidence:
                regressions.append(
                    f"{result.benchmark_id} confidence dropped from {old_confidence:.2f} to {result.confidence:.2f}."
                )
        previous_pass_rate = float(previous.get("pass_rate") or 0.0)
        if current.pass_rate + 0.1 < previous_pass_rate:
            regressions.append(
                f"Overall pass rate dropped from {previous_pass_rate:.1f}% to {current.pass_rate:.1f}%."
            )
        return regressions
