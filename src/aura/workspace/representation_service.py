from __future__ import annotations

import json
import subprocess
import time
from hashlib import sha256
from uuid import uuid4
from dataclasses import replace
from pathlib import Path
from typing import Any

from aura.engineering_graph.model import EngineeringGraph, EntityKind
from aura.engineering_graph.electrical import electrical_nets, materialize_electrical_nets
from aura.infrastructure.persistence.project_repository import ProjectRepository
from .representations import (GenerationResult, RepresentationRecord, RepresentationSpec,
    RepresentationSpecValidator, RepresentationStatus, RepresentationType)


CAD_VERSION = "2.0.6"
TSCIRCUIT_VERSION = "0.0.1609"


def representation_specs(graph: EngineeringGraph) -> list[RepresentationSpec]:
    coordinate = {"forward": "+X", "left": "+Y", "up": "+Z"}
    components=graph.find(kind=EntityKind.COMPONENT);mechanical=[]
    for entity in components:
        family=entity.metadata.get("family",entity.metadata.get("role",""));dims=entity.metadata.get("dimensions",{})
        value=lambda key,default:float(dims.get(key,{}).get("value",default))
        # Every physical semantic component receives a bounded, non-zero proxy.
        # A record alone is not considered physical coverage; its geometry is
        # validated below and the renderer receives the same semantic id.
        if family in {"enclosure","mounting_plate"} or entity.id=="component-enclosure": geometry={"operation":"filleted_enclosure","width":value("width",100),"depth":value("length",80),"height":value("height",40),"radius":4}
        elif family in {"container","reservoir"}:
            w,h=value("width",80),value("height",120);geometry={"operation":"loft","sections":[{"z":0,"radius":w*.4},{"z":h*.5,"radius":w*.5},{"z":h,"radius":w*.42}]}
        elif family in {"tube"} or entity.id=="component-tubing": geometry={"operation":"pipe","radius":5,"path":[[0,0,0],[30,0,15],[55,20,45],[85,25,80]]}
        elif family=="tracked_object": geometry={"operation":"sphere","radius":max(value("width",24)/2,1)}
        else: geometry={"operation":"box","width":value("width",45),"depth":value("length",30),"height":value("height",18)}
        resolution=str(entity.metadata.get("parameters",{}).get("resolution_quality","CONCEPTUAL"))
        mechanical.append(RepresentationSpec(RepresentationType.MECHANICAL_3D,(entity.id,),{"units":"mm","coordinateSystem":coordinate,"geometry":geometry,
            "semanticCoverage":{"componentId":entity.id,"family":family,"proxy":True,"renderStrategy":"family_proxy",
                "representationClass":"exact" if resolution=="EXACT" else "generic" if resolution=="COMPATIBLE_GENERIC" else "conceptual"}}))
    categories={
        "microcontroller_board":("U","controller",["VCC","GND",*[f"IO{i}" for i in range(1,9)]]),"controller":("U","controller",["VCC","GND",*[f"IO{i}" for i in range(1,9)]]),
        "temperature_sensor":("S","generic_sensor",["VCC","GND","SIGNAL"]),"light_sensor":("S","generic_sensor",["VCC","GND","SIGNAL"]),"environmental_sensor":("S","generic_sensor",["VCC","GND","SIGNAL"]),"distance_sensor":("S","generic_sensor",["VCC","GND","SIGNAL"]),"soil_moisture_sensor":("S","generic_sensor",["VCC","GND","SIGNAL"]),"motion_sensor":("S","generic_sensor",["VCC","GND","SIGNAL"]),"orientation_sensor":("S","generic_sensor",["VCC","GND","SIGNAL"]),"conceptual_sensor":("S","generic_sensor",["VCC","GND","SIGNAL"]),"moisture_sensor":("S","generic_sensor",["VCC","GND","SIGNAL"]),"soil sensing":("S","generic_sensor",["VCC","GND","SIGNAL"]),
        "mosfet_driver":("Q","mosfet",["VCC","GND","SIGNAL","OUT"]),"motor_driver":("DRV","generic_module",["VCC","GND","SIGNAL","OUT"]),"relay_module":("K","generic_module",["VCC","GND","SIGNAL","OUT"]),"bare_relay":("K","generic_module",["VCC","GND","OUT"]),"pump switching":("Q","generic_module",["VCC","GND","SIGNAL","OUT"]),"wireless_module":("W","generic_module",["VCC","GND","SIGNAL"]),
        "flyback_diode":("D","diode",["ANODE","CATHODE"]),"resistor":("R","resistor",["A","B"]),
        "fan":("M","motor",["V+","GND","CONTROL"]),"small_dc_motor":("M","motor",["V+","GND","CONTROL"]),"small_dc_pump":("M","motor",["V+","GND","CONTROL"]),"water delivery":("M","motor",["V+","GND","CONTROL"]),"indicator":("A","generic_actuator",["V+","GND","CONTROL"]),
        "servo":("M","servo",["PWM","V+","GND"]),"low_voltage_power_source":("BT","power_source",["V+","GND"]),"system power":("BT","power_source",["V+","GND"]),
    }
    counts={};circuit_components=[];references={}
    for entity in components:
        family=entity.metadata.get("family",entity.metadata.get("role",""));category=categories.get(family)
        electrical_ports=set(entity.metadata.get("interfaces",())) & {"power","ground","signal","load-output"}
        if not category and electrical_ports: category=("X","generic_module",["VCC","GND","CONTROL","OUT","SIGNAL"])
        if not category: continue
        prefix,kind,pins=category;counts[prefix]=counts.get(prefix,0)+1;ref=f"{prefix}{counts[prefix]}";references[entity.id]=ref
        circuit_components.append({"reference":ref,"semanticId":entity.id,"kind":kind,"pins":pins,"displayName":entity.name,
            "componentDefinitionId":entity.metadata.get("parameters",{}).get("component_definition_id")})
    # Circuit topology is compiled exclusively from first-class graph nets.
    if not electrical_nets(graph):
        materialize_electrical_nets(graph)  # migration path for persisted pre-net graphs
    connections=[];unconnected=[];signal_counts={}
    pin_alias={
        "controller":{"power":"VCC","5v":"VCC","3v3":"VCC","ground":"GND","gnd":"GND","signal":"IO1","gpio-pump":"IO1","gpio-sensor":"IO2"},
        "servo":{"power":"V+","ground":"GND","signal":"PWM"},
        "power_source":{"power":"V+","5v":"V+","ground":"GND"},
        "generic_sensor":{"power":"VCC","vcc":"VCC","ground":"GND","gnd":"GND","signal":"SIGNAL"},
        "generic_actuator":{"power":"V+","power+":"V+","ground":"GND","signal":"CONTROL"},
        "motor":{"power":"V+","power+":"V+","ground":"GND","signal":"CONTROL","load-output":"V+"},
        "generic_module":{"power":"VCC","ground":"GND","signal":"SIGNAL","load-output":"OUT"},
        "mosfet":{"power":"VCC","ground":"GND","signal":"SIGNAL","load-output":"OUT"},
        "diode":{"anode":"ANODE","cathode":"CATHODE"},"resistor":{"terminal-a":"A","terminal-b":"B"},
    }
    by_reference={item["reference"]:item for item in circuit_components}
    for net in electrical_nets(graph):
        resolved=[]
        for terminal in net["terminals"]:
            component_id,interface=terminal["componentId"],terminal["interfaceId"]
            reference=references.get(component_id);component=by_reference.get(reference or "")
            pin=pin_alias.get(component["kind"],{}).get(interface) if component else None
            if component and component["kind"]=="controller" and interface.startswith("signal-"):
                pin=f"IO{interface.removeprefix('signal-')}"
            elif component and component["kind"]=="controller" and interface=="signal" and net["role"] in {"control","signal"}:
                signal_counts[reference]=signal_counts.get(reference,0)+1;pin=f"IO{signal_counts[reference]}"
            if reference and component and pin in component["pins"]: resolved.append((reference,pin,component_id))
            else: unconnected.append({"netId":net["netId"],"sourceSemanticId":component_id,"interfaceId":interface,"reason":"terminal has no compatible schematic pin"})
        if len(resolved)>1:
            origin=resolved[0]
            for target in resolved[1:]: connections.append({"from":f"{origin[0]}.{origin[1]}","to":f"{target[0]}.{target[1]}","netId":net["netId"],"graphConnectionId":net["connectionIds"][0],"role":net["role"],"displayStyle":net["displayStyle"]})
    graph_ids = {entity.id for entity in graph.find(kind=EntityKind.COMPONENT)}
    topology=[]
    for net in electrical_nets(graph):
        expected=[f"{terminal['componentId']}:{terminal['interfaceId']}" for terminal in net["terminals"]]
        represented=[]
        for terminal in net["terminals"]:
            component=by_reference.get(references.get(terminal["componentId"],""));pin=pin_alias.get(component["kind"],{}).get(terminal["interfaceId"]) if component else None
            if component and component["kind"]=="controller" and terminal["interfaceId"].startswith("signal-"):
                pin=f"IO{terminal['interfaceId'].removeprefix('signal-')}"
            if component and component["kind"]=="controller" and terminal["interfaceId"]=="signal": pin=None  # legacy shared output is assigned deterministically above
            if component and component["kind"]=="controller" and terminal["interfaceId"]=="signal":
                matching=[item for item in connections if item["netId"]==net["netId"] and item["from"].startswith(f"{references[terminal['componentId']]}.") or item["netId"]==net["netId"] and item["to"].startswith(f"{references[terminal['componentId']]}")]
                if matching: pin=(matching[0]["from"] if matching[0]["from"].startswith(f"{references[terminal['componentId']]}") else matching[0]["to"]).split(".",1)[1]
            if component and pin in component["pins"]: represented.append(f"{terminal['componentId']}:{terminal['interfaceId']}")
        topology.append({"netId":net["netId"],"expectedTerminals":expected,"representedTerminals":represented,"missingTerminals":sorted(set(expected)-set(represented))})
    circuit = RepresentationSpec(RepresentationType.CIRCUIT_SCHEMATIC,
        tuple(dict.fromkeys(item["semanticId"] for item in circuit_components)),
        {"components": circuit_components, "connections": connections, "unconnected":unconnected,"netTopology":topology,
         "fidelity":{"portsComplete":not unconnected,"netsComplete":not any(item["missingTerminals"] for item in topology)}})
    validator = RepresentationSpecValidator()
    return [validator.validate(spec, graph_ids) for spec in [*mechanical, circuit] if spec.semantic_ids]



def initial_records(project_id: str, revision: int, specs: list[RepresentationSpec]) -> list[RepresentationRecord]:
    records=[]
    for spec in specs:
        suffix = spec.semantic_ids[0].removeprefix("component-") if len(spec.semantic_ids)==1 else "system"
        generator, version = ("cascade-core", CAD_VERSION) if spec.kind is RepresentationType.MECHANICAL_3D else ("tscircuit", TSCIRCUIT_VERSION)
        records.append(RepresentationRecord(f"repr-{suffix}-{'3d' if spec.kind is RepresentationType.MECHANICAL_3D else 'schematic'}",
            project_id, revision, spec.semantic_ids, spec.kind, generator=generator, generator_version=version,
            verification_status="accepted",operation_id=f"representation-{sha256(f'{project_id}|{revision}|{suffix}|{spec.kind.value}'.encode()).hexdigest()[:20]}",generation=1))
    return records


class CircuitGeneratorAdapter:
    generator_name = "tscircuit"
    generator_version = TSCIRCUIT_VERSION
    MAX_OUTPUT_BYTES = 5_000_000

    def __init__(self, timeout: float = 20.0, node_executable: str = "node", script_path: Path | None = None) -> None:
        self.timeout=timeout; self.node_executable=node_executable
        self.script_path=(script_path or Path(__file__).with_name("web") / "frontend" / "generators" / "tscircuit" / "generate-circuit.mjs").resolve()

    def can_generate(self, spec: RepresentationSpec) -> bool: return spec.kind is RepresentationType.CIRCUIT_SCHEMATIC

    def generate(self, spec: RepresentationSpec) -> GenerationResult:
        if not self.can_generate(spec): raise ValueError("Unsupported representation spec")
        started=time.perf_counter()
        try:
            completed=subprocess.run([self.node_executable, str(self.script_path)], input=json.dumps(spec.payload), text=True,
                capture_output=True, timeout=self.timeout, check=False, shell=False)
        except subprocess.TimeoutExpired as exc: raise TimeoutError(f"tscircuit generation exceeded {self.timeout}s") from exc
        if completed.returncode != 0: raise RuntimeError(f"tscircuit failed: {completed.stderr[:1000]}")
        if len(completed.stdout.encode()) > self.MAX_OUTPUT_BYTES: raise RuntimeError("tscircuit output exceeded limit")
        try: output=json.loads(completed.stdout)
        except json.JSONDecodeError as exc: raise RuntimeError("tscircuit returned malformed JSON") from exc
        if output.get("status") != "ready" or not isinstance(output.get("circuitJson"), list): raise RuntimeError("tscircuit returned an invalid result")
        metrics={key:float(value) for key,value in output.get("metrics",{}).items()}; metrics["totalRequestMs"]=(time.perf_counter()-started)*1000
        return GenerationResult(RepresentationStatus.READY, json.dumps(output["circuitJson"],separators=(",", ":")).encode(),
            dict(output.get("semanticMapping",{})), tuple(output.get("warnings",[])), metrics, "circuit-json")


class RepresentationService:
    def __init__(self, repository: ProjectRepository, circuit_generator: CircuitGeneratorAdapter | None = None) -> None:
        self.repository=repository; self.circuit_generator=circuit_generator or CircuitGeneratorAdapter()

    def persist_specs(self, project_id: str, revision: int, records: list[RepresentationRecord], specs: list[RepresentationSpec]) -> list[RepresentationRecord]:
        updated=[]
        for record,spec in zip(records,specs):
            artifact=self.repository.create_artifact(project_id,revision,list(spec.semantic_ids),spec.kind.value,
                "representation-spec" if spec.kind is RepresentationType.MECHANICAL_3D else "circuit-json")  # type: ignore[attr-defined]
            if spec.kind is RepresentationType.MECHANICAL_3D:
                self.repository.write_artifact(artifact.artifact_id,json.dumps(spec.to_dict(),separators=(",", ":")).encode(),"aura-spec","1")  # type: ignore[attr-defined]
                updated.append(record.transition(RepresentationStatus.GENERATING).transition(RepresentationStatus.READY,artifact_id=artifact.artifact_id,error=None))
            else: updated.append(self._generate_circuit(record,spec,artifact.artifact_id))
        return updated

    def _generate_circuit(self, record: RepresentationRecord, spec: RepresentationSpec, artifact_id: str) -> RepresentationRecord:
        generating=record.transition(RepresentationStatus.GENERATING)
        try:
            result=self.circuit_generator.generate(spec)
            self.repository.write_artifact(artifact_id,result.artifact or b"[]",self.circuit_generator.generator_name,self.circuit_generator.generator_version)  # type: ignore[attr-defined]
            return generating.transition(RepresentationStatus.READY,artifact_id=artifact_id,error=None)
        except Exception as exc:
            return generating.transition(RepresentationStatus.FAILED,error=str(exc)).transition(RepresentationStatus.FALLBACK)

    def regenerate_circuit(self, graph: EngineeringGraph, record: RepresentationRecord) -> RepresentationRecord:
        spec=next(spec for spec in representation_specs(graph) if spec.kind is RepresentationType.CIRCUIT_SCHEMATIC)
        stale=record.transition(RepresentationStatus.STALE) if record.status is RepresentationStatus.READY else replace(record,status=RepresentationStatus.STALE)
        artifact=self.repository.create_artifact(record.project_id,len(graph.revisions),list(spec.semantic_ids),spec.kind.value,"circuit-json")  # type: ignore[attr-defined]
        return replace(self._generate_circuit(replace(stale,operation_id=f"representation-{uuid4().hex}",generation=record.generation+1), spec, artifact.artifact_id),revision=len(graph.revisions))

    def regenerate(self, graph: EngineeringGraph, record: RepresentationRecord) -> RepresentationRecord:
        """Regenerate one graph-derived representation, retaining a usable fallback on failure."""
        if record.type is RepresentationType.CIRCUIT_SCHEMATIC:
            return self.regenerate_circuit(graph, record)
        spec = next(spec for spec in representation_specs(graph) if spec.kind is record.type and spec.semantic_ids == record.semantic_ids)
        stale = record.transition(RepresentationStatus.STALE) if record.status is RepresentationStatus.READY else replace(record,status=RepresentationStatus.STALE)
        generating = replace(stale.transition(RepresentationStatus.GENERATING),operation_id=f"representation-{uuid4().hex}",generation=record.generation+1)
        artifact = self.repository.create_artifact(record.project_id,len(graph.revisions),list(spec.semantic_ids),spec.kind.value,"representation-spec")  # type: ignore[attr-defined]
        try:
            self.repository.write_artifact(artifact.artifact_id,json.dumps(spec.to_dict(),separators=(",", ":")).encode(),"aura-spec","1")  # type: ignore[attr-defined]
            return generating.transition(RepresentationStatus.READY,artifact_id=artifact.artifact_id,revision=len(graph.revisions),error=None)
        except Exception as exc:
            return generating.transition(RepresentationStatus.FAILED,error=str(exc)).transition(RepresentationStatus.FALLBACK,revision=len(graph.revisions))
