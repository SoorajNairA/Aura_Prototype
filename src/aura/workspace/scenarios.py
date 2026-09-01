from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field
from aura.engineering_graph.model import EngineeringGraph, EntityKind
from aura.engineering_graph.patches import GraphOperation,GraphPatch,PatchOperation,apply_patch
from aura.verification.delta import compare_verification
from aura.verification.service import VerificationService

class ScenarioError(ValueError):
    def __init__(self,code:str,message:str,status:int=422):super().__init__(message);self.code=code;self.message=message;self.status=status

class CandidateSemantics(BaseModel):
    """Structured model judgment for a direct component substitution."""
    model_config=ConfigDict(extra="forbid")
    decision:Literal["COMPATIBLE","INCOMPATIBLE","UNCERTAIN"]
    candidateName:str=Field(min_length=1,max_length=200)
    candidateFamily:str=Field(min_length=1,max_length=100)
    candidateFunctionalRoles:list[str]=Field(default_factory=list,max_length=24)
    interfaceCompatibility:Literal["COMPATIBLE","ADAPTER_REQUIRED","INCOMPATIBLE","UNKNOWN"]
    confidence:Literal["HIGH","MEDIUM","LOW"]
    rationale:str=Field(min_length=1,max_length=1200)
    missingRequiredRoles:list[str]=Field(default_factory=list,max_length=24)
    requiredChanges:list[str]=Field(default_factory=list,max_length=24)
    assumptions:list[str]=Field(default_factory=list,max_length=24)

class LiveScenarioAnalyzer:
    """Uses the configured structured model to judge replacement semantics."""
    def __init__(self,provider:Any):self.provider=provider

    def assess_replacement(self,graph:EngineeringGraph,target_id:str,value:dict[str,Any])->tuple[CandidateSemantics,dict[str,Any]]:
        if target_id not in graph.entities or graph.get(target_id).kind is not EntityKind.COMPONENT:
            raise ScenarioError("SCENARIO_TARGET_INVALID","What-If target must be a current component")
        if not isinstance(value,dict) or not str(value.get("name","")).strip():
            raise ScenarioError("SCENARIO_CHANGE_INVALID","Replacement name is required")
        target=graph.get(target_id)
        parameters=target.metadata.get("parameters",{})
        relationships=[]
        for relation in graph.relationships.values():
            if target_id not in {relation.source_id,relation.target_id}:continue
            other_id=relation.target_id if relation.source_id==target_id else relation.source_id
            other=graph.entities.get(other_id)
            relationships.append({"id":relation.id,"type":relation.type,
                "direction":"outgoing" if relation.source_id==target_id else "incoming",
                "other":{"id":other_id,"name":other.name if other else other_id,
                    "family":other.metadata.get("family") if other else None},"metadata":relation.metadata})
        context={
            "project":graph.get(graph.project_id).name,
            "requirements":[{"name":entity.name,"metadata":entity.metadata} for entity in graph.find(kind=EntityKind.REQUIREMENT)],
            "target":{"id":target.id,"name":target.name,"family":target.metadata.get("family"),
                "functionalRoles":parameters.get("functional_roles",[]),"parameters":parameters,
                "dimensions":target.metadata.get("dimensions",{})},
            "existingRelationships":relationships,
            "candidateRequest":value,
        }
        instruction=("Evaluate whether the requested candidate can directly replace the target in this existing engineering graph "
            "without silently changing the target's primary purpose or the connected system behavior. Use engineering knowledge, "
            "not keyword matching. Reuse an exact target functional-role token in candidateFunctionalRoles only when the candidate "
            "really preserves that function. Mark COMPATIBLE only when every required functional role and existing interface can be "
            "preserved without adding components or redesigning relationships. Use UNCERTAIN when specifications are insufficient, "
            "ADAPTER_REQUIRED when extra hardware or relationship changes are needed, and INCOMPATIBLE for a different primary function. "
            "Return only the requested schema.")
        result=self.provider.generate_structured([{"role":"user","content":json.dumps(context,separators=(",",":"),sort_keys=True)}],
            system_prompt=instruction,max_tokens=700,response_schema=CandidateSemantics.model_json_schema())
        try:assessment=CandidateSemantics.model_validate_json(result.text)
        except Exception as exc:raise ScenarioError("SCENARIO_AI_RESPONSE_INVALID","AI scenario analysis returned an invalid structured decision",502) from exc
        required_roles={str(role) for role in parameters.get("functional_roles",[]) if str(role)}
        candidate_roles={str(role) for role in assessment.candidateFunctionalRoles if str(role)}
        role_preserved=required_roles<=candidate_roles and not assessment.missingRequiredRoles
        applicable=(assessment.decision=="COMPATIBLE" and assessment.interfaceCompatibility=="COMPATIBLE" and role_preserved)
        metadata={"source":"structured_model","inputTokens":getattr(result,"input_tokens",None),
            "outputTokens":getattr(result,"output_tokens",None),"totalTokens":getattr(result,"total_tokens",None),"roleContractPreserved":role_preserved,
            "applicable":applicable}
        return assessment,metadata

@dataclass(frozen=True)
class EngineeringScenario:
    id:str;project_id:str;base_revision:int;base_revision_id:str|None;target_id:str;change_type:str;patch:GraphPatch;candidate_graph:EngineeringGraph;analysis:dict[str,Any]
    def to_dict(self):return {"scenarioId":self.id,"projectId":self.project_id,"baseRevision":self.base_revision,"baseRevisionId":self.base_revision_id,"targetSemanticId":self.target_id,"changeType":self.change_type,"applicable":self.analysis.get("applicable",False),"analysis":self.analysis}

def _confidence(findings)->str:
    if any(x.severity=="critical" and x.state.value=="failed" for x in findings):return "INVALID"
    if any(x.state.value in {"failed","unsupported","conceptual"} for x in findings):return "LOW"
    if any(x.severity=="warning" or x.state.value in {"estimated","stale"} for x in findings):return "MEDIUM"
    return "HIGH"

def analyze(graph:EngineeringGraph,target_id:str,change_type:str,value:Any,assessment:CandidateSemantics|None=None,model_metadata:dict[str,Any]|None=None)->EngineeringScenario:
    if target_id not in graph.entities or graph.get(target_id).kind is not EntityKind.COMPONENT:raise ScenarioError("SCENARIO_TARGET_INVALID","What-If target must be a current component")
    target=graph.get(target_id);meta=dict(target.metadata);changes={};known=[]
    if change_type=="REPLACE_COMPONENT":
        if not isinstance(value,dict) or not str(value.get("name","")).strip():raise ScenarioError("SCENARIO_CHANGE_INVALID","Replacement name is required")
        if assessment is None:raise ScenarioError("SCENARIO_AI_REQUIRED","Replacement What-If analysis requires the configured AI model",503)
        old=target.name;params=dict(meta.get("parameters",{}));params.update({k:v for k,v in value.get("properties",{}).items() if isinstance(k,str) and isinstance(v,(str,int,float,bool))})
        params["functional_roles"]=list(assessment.candidateFunctionalRoles);params["resolution_quality"]="CONCEPTUAL"
        meta["family"]=assessment.candidateFamily;meta["parameters"]=params
        if value.get("componentDefinitionId"):
            definition=str(value["componentDefinitionId"]);meta["component_definition_id"]=definition;params["component_definition_id"]=definition
        else:
            meta.pop("component_definition_id",None);params.pop("component_definition_id",None);params.pop("component_definition_version",None)
        changes={"name":assessment.candidateName,"metadata":meta};known.append({"kind":"KNOWN_CHANGE","message":f"{old} evaluated against {changes['name']}","semanticIds":[target_id]})
    elif change_type=="MODIFY_PROPERTY":
        if not isinstance(value,dict) or not isinstance(value.get("path"),str) or value["path"] not in {"dimensions.width.value","dimensions.length.value","dimensions.height.value","parameters.voltage_v","parameters.current_a"}:raise ScenarioError("SCENARIO_CHANGE_INVALID","Property is outside the bounded What-If surface")
        path=value["path"].split(".");copy=dict(meta);cursor=copy
        for key in path[:-1]:cursor[key]=dict(cursor.get(key,{}));cursor=cursor[key]
        old=cursor.get(path[-1]);cursor[path[-1]]=value.get("value");changes={"metadata":copy};known.append({"kind":"KNOWN_CHANGE","message":f"{value['path']} changed from {old} to {value.get('value')}","semanticIds":[target_id]})
    elif change_type=="REMOVE_COMPONENT":changes={};known.append({"kind":"KNOWN_CHANGE","message":f"{target.name} removed","semanticIds":[target_id]})
    else:raise ScenarioError("SCENARIO_CHANGE_INVALID","Unsupported What-If change type")
    operation=GraphOperation(PatchOperation.REMOVE_ENTITY,target_id=target_id) if change_type=="REMOVE_COMPONENT" else GraphOperation(PatchOperation.UPDATE_ENTITY,target_id=target_id,changes=changes)
    operations=tuple(GraphOperation(PatchOperation.REMOVE_RELATIONSHIP,target_id=relation.id) for relation in graph.relationships.values() if change_type=="REMOVE_COMPONENT" and target_id in {relation.source_id,relation.target_id})+(operation,)
    patch=GraphPatch(f"scenario-patch-{uuid4().hex}",operations,f"What-If {change_type.lower().replace('_',' ')}",graph.current_revision_id)
    try:candidate=apply_patch(graph,patch)
    except Exception as exc:raise ScenarioError("SCENARIO_CANDIDATE_INVALID",str(exc)) from exc
    verifier=VerificationService()
    verification=verifier.verify_modification(graph,patch)
    candidate_verification=verifier.verify_graph(candidate)
    verification_delta=compare_verification(verifier.verify_graph(graph),candidate_verification).to_dict()
    direct={target_id};adjacent=set();relationship_changes=[]
    for relation in graph.relationships.values():
        if target_id in {relation.source_id,relation.target_id}:
            other=relation.target_id if relation.source_id==target_id else relation.source_id;adjacent.add(other);relationship_changes.append(relation.id)
    indirect=set()
    for relation in graph.relationships.values():
        if relation.source_id in adjacent:indirect.add(relation.target_id)
        if relation.target_id in adjacent:indirect.add(relation.source_id)
    indirect-=direct|adjacent
    finding_records={x.id:x for x in (*candidate_verification.findings,*verification.findings)}
    findings=[x.to_dict() for x in finding_records.values()]
    derived=[{"kind":"DERIVED_IMPACT","message":f"Relationship {rid} must be re-evaluated","semanticIds":[target_id]} for rid in relationship_changes]
    if assessment is not None:
        derived.insert(0,{"kind":"DERIVED_IMPACT","category":"AI COMPATIBILITY","message":assessment.rationale,
            "status":assessment.decision,"semanticIds":[target_id]})
    uncertainty=[{"kind":"UNCERTAINTY","message":x["summary"],"semanticIds":x.get("semanticIds",[]),"findingId":x["findingId"]} for x in findings if x.get("severity") in {"WARN","FAIL"}]
    if assessment is not None:
        uncertainty.extend({"kind":"UNCERTAINTY","message":message,"semanticIds":[target_id]} for message in (*assessment.requiredChanges,*assessment.assumptions))
    applicable=(model_metadata or {}).get("applicable",True) if change_type=="REPLACE_COMPONENT" else verification.accepted
    if assessment is not None and not applicable:
        verification_delta={**verification_delta,"readinessAfter":"INCOMPATIBLE","classification":"REGRESSED"}
    analysis={"current":{"revision":len(graph.revisions),"component":{"id":target.id,"name":target.name,"family":target.metadata.get("family")}},"candidate":{"component":None if change_type=="REMOVE_COMPONENT" else {"id":target.id,"name":candidate.get(target.id).name,"family":candidate.get(target.id).metadata.get("family"),"functionalRoles":candidate.get(target.id).metadata.get("parameters",{}).get("functional_roles",[])}},
        "diff":{"changedComponents":[] if change_type=="REMOVE_COMPONENT" else [target_id],"addedComponents":[],"removedComponents":[target_id] if change_type=="REMOVE_COMPONENT" else [],"changedRelationships":relationship_changes},
        "impact":{"directlyChanged":sorted(direct),"directlyAffected":sorted(adjacent),"indirectlyAffected":sorted(indirect),"affectedComponentIds":sorted((direct|adjacent|indirect)&{x.id for x in graph.find(kind=EntityKind.COMPONENT)})},
        "verification":{"accepted":verification.accepted and bool(applicable),"state":"incompatible" if assessment is not None and not applicable else candidate_verification.state.value,"findings":findings,"delta":verification_delta},
        "confidence":assessment.confidence if assessment is not None else _confidence(tuple(finding_records.values())),"applicable":bool(applicable),
        "semanticAssessment":assessment.model_dump() if assessment is not None else None,"ai":model_metadata,"explanations":[*known,*derived,*uncertainty]}
    return EngineeringScenario(f"scenario-{uuid4().hex}",graph.project_id,len(graph.revisions),graph.current_revision_id,target_id,change_type,patch,candidate,analysis)
