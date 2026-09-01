from __future__ import annotations

from dataclasses import replace

from aura.engineering_graph.model import EngineeringEntity, EntityKind
from aura.engineering_graph.patches import GraphOperation, GraphPatch, PatchOperation, apply_patch
from aura.verification.delta import DeltaClassification, compare_verification, verification_readiness
from aura.verification.results import VerificationDecision, VerificationFinding, VerificationResult, VerificationState
from aura.verification.service import VerificationService

from tests.test_verification_graph_integrity import component, graph, net, port


def finding(code,subject,state=VerificationState.FAILED,severity="critical",blocking=True):
    return VerificationFinding(f"id-{code}-{subject}",code,state,severity,code,(subject,),blocking=blocking)


def verification(*findings,state=None):
    state=state or (VerificationState.FAILED if any(item.blocking for item in findings) else VerificationState.ESTIMATED)
    return VerificationResult(VerificationDecision.REJECT if state is VerificationState.FAILED else VerificationDecision.ACCEPT,state,(),None,tuple(findings))


def test_delta_detects_resolved_introduced_and_unchanged_findings():
    stable=finding("STABLE","sensor",VerificationState.ESTIMATED,"warning",False)
    before=verification(finding("OLD","motor"),stable)
    after=verification(stable,finding("NEW","power"))
    delta=compare_verification(before,after)
    assert [item.check for item in delta.resolved_findings]==["OLD"]
    assert [item.check for item in delta.introduced_findings]==["NEW"]
    assert [item.check for item in delta.unchanged_findings]==["STABLE"]


def test_partial_blocker_resolution_classifies_improves():
    before=verification(finding("A","motor"),finding("B","sensor"))
    after=verification(finding("B","sensor"))
    delta=compare_verification(before,after)
    assert delta.classification is DeltaClassification.IMPROVES
    assert delta.blocking_resolved_count==1 and delta.blocking_introduced_count==0
    assert delta.readiness_after=="BUILD_INCOMPLETE"


def test_last_blocker_resolution_classifies_resolves_all():
    delta=compare_verification(verification(finding("A","motor")),verification(state=VerificationState.CROSS_CHECKED))
    assert delta.classification is DeltaClassification.RESOLVES_ALL
    assert delta.readiness_before=="BUILD_INCOMPLETE" and delta.readiness_after=="SUPPORTED"


def test_new_blocker_classifies_worsens_even_if_old_blocker_resolves():
    delta=compare_verification(verification(finding("OLD","motor")),verification(finding("NEW","controller")))
    assert delta.classification is DeltaClassification.WORSENS
    assert delta.blocking_resolved_count==1 and delta.blocking_introduced_count==1


def test_severity_improvement_and_regression_are_structured():
    failed=finding("VOLTAGE","controller")
    warned=finding("VOLTAGE","controller",VerificationState.ESTIMATED,"warning",False)
    improved=compare_verification(verification(failed),verification(warned))
    regressed=compare_verification(verification(warned),verification(failed))
    assert improved.severity_changes[0].to_dict()["before"]=="FAIL"
    assert improved.severity_changes[0].to_dict()["after"]=="WARN"
    assert improved.classification is DeltaClassification.RESOLVES_ALL
    assert regressed.classification is DeltaClassification.WORSENS


def invalid_two_blocker_graph():
    a=component("a",[port("out","signal","output")]);b=component("b",[port("out","signal","output")])
    supply=component("supply",[port("out","power_output","output")]);ground=component("return",[port("gnd","ground","input")])
    return graph(a,b,supply,ground,
        net("contention","signal",("a","out"),("b","out")),
        net("short","ground",("supply","out"),("return","gnd")))


def update_net(candidate,net_id,terminals):
    current=candidate.get(net_id);metadata=dict(current.metadata)|{"terminals":[{"componentId":owner,"interfaceId":interface} for owner,interface in terminals]}
    return GraphPatch(f"fix-{net_id}",(GraphOperation(PatchOperation.UPDATE_ENTITY,target_id=net_id,changes={"metadata":metadata}),),f"Fix {net_id}",candidate.current_revision_id)


def test_incremental_modification_accepts_one_fix_and_preserves_incomplete_readiness():
    candidate=invalid_two_blocker_graph()
    result=VerificationService().verify_modification(candidate,update_net(candidate,"contention",(("a","out"),)))
    assert result.accepted and result.state is VerificationState.FAILED
    assert result.verification_delta["classification"]=="IMPROVES"
    assert result.verification_delta["blockingResolvedCount"]==1
    assert result.verification_delta["blockingIntroducedCount"]==0
    assert verification_readiness(result)=="BUILD_INCOMPLETE"


def test_second_incremental_fix_resolves_all():
    candidate=invalid_two_blocker_graph()
    first=VerificationService().verify_modification(candidate,update_net(candidate,"contention",(("a","out"),)))
    improved=apply_patch(candidate,first.patch)
    remove_short=GraphPatch("remove-short",(GraphOperation(PatchOperation.REMOVE_ENTITY,target_id="short"),),"Remove invalid short",improved.current_revision_id)
    second=VerificationService().verify_modification(improved,remove_short)
    assert second.accepted and second.verification_delta["classification"]=="RESOLVES_ALL"
    assert second.state is VerificationState.CROSS_CHECKED


def test_fix_that_introduces_new_blocker_is_rejected():
    candidate=invalid_two_blocker_graph()
    # Remove the pre-existing short so only contention is initially blocking.
    candidate.entities.pop("short")
    fixed=dict(candidate.get("contention").metadata)|{"terminals":[{"componentId":"a","interfaceId":"out"}]}
    introduced=net("new-short","ground",("supply","out"),("return","gnd"))
    patch=GraphPatch("unsafe-fix",(
        GraphOperation(PatchOperation.UPDATE_ENTITY,target_id="contention",changes={"metadata":fixed}),
        GraphOperation(PatchOperation.ADD_ENTITY,entity=introduced),
    ),"Unsafe fix",candidate.current_revision_id)
    result=VerificationService().verify_modification(candidate,patch)
    assert not result.accepted
    assert result.verification_delta["classification"]=="WORSENS"


def test_neutral_invalid_modification_is_not_accepted():
    candidate=invalid_two_blocker_graph()
    patch=GraphPatch("rename",(GraphOperation(PatchOperation.UPDATE_ENTITY,target_id="a",changes={"name":"renamed"}),),"Rename",candidate.current_revision_id)
    result=VerificationService().verify_modification(candidate,patch)
    assert not result.accepted and result.verification_delta["classification"]=="NEUTRAL"
