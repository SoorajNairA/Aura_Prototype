import {describe,expect,it} from "vitest";
import {findingPresentation,projectStatus,requiresReason,scenarioPresentation,workItemPresentation,workSummary} from "./presentation";

describe("workspace presentation contracts",()=>{
  it("keeps verification categories distinct from project status",()=>{
    expect(projectStatus({status:"ready",capability:{status:"SUPPORTED"}},{summary:{tool_verified:4,failed:0}})).toBe("READY");
    expect(projectStatus({status:"ready",capability:{status:"SUPPORTED_WITH_LIMITATIONS"}},{summary:{estimated:1,failed:0}})).toBe("READY WITH LIMITATIONS");
    expect(findingPresentation({id:"f1",state:"conceptual",entity_ids:["component-a"]})).toMatchObject({findingId:"f1",status:"conceptual",semanticTargets:["component-a"]});
  });

  it("normalizes backend work items without deciding their transitions",()=>{
    const item=workItemPresentation({id:"w1",title:"Verify actuator",state:"PAUSED",allowed_transitions:["in_progress"],reason:"Awaiting mass"});
    expect(item.state).toBe("paused");
    expect(item.allowedTransitions).toEqual(["in_progress"]);
    expect(workSummary([item])).toEqual({paused:1});
    expect(requiresReason("PAUSED")).toBe(true);
    expect(requiresReason("COMPLETED")).toBe(false);
  });

  it("presents scenario output without deriving impact",()=>{
    const scenario=scenarioPresentation({id:"s1",summary:"Replace servo",changed_ids:["servo"],affected_ids:["mount"],derived_impacts:["Mount changed"],applicable:true});
    expect(scenario).toMatchObject({scenarioId:"s1",changedIds:["servo"],affectedIds:["mount"],derivedImpacts:[{summary:"Mount changed"}]});
    const integrated=scenarioPresentation({scenarioId:"s2",baseRevisionId:"r1",analysis:{
      diff:{changedComponents:["servo"]},impact:{affectedComponentIds:["servo","mount"]},
      verification:{delta:{readinessBefore:"BUILD_INCOMPLETE",readinessAfter:"SUPPORTED_WITH_LIMITATIONS"}},confidence:"MEDIUM",
      applicable:false,semanticAssessment:{decision:"INCOMPATIBLE"},ai:{source:"structured_model",model:"gemini-test"},
      explanations:[{kind:"KNOWN_CHANGE",message:"Servo replaced"},{kind:"DERIVED_IMPACT",message:"Mount must be checked"},{kind:"UNCERTAINTY",message:"Torque is estimated"}],
    }});
    expect(integrated).toMatchObject({scenarioId:"s2",changedIds:["servo"],affectedIds:["servo","mount"],verificationBefore:"BUILD_INCOMPLETE",verificationAfter:"SUPPORTED_WITH_LIMITATIONS",derivedImpacts:[{summary:"Mount must be checked"}],uncertainties:["Torque is estimated"],applicable:false,compatibilityDecision:"INCOMPATIBLE",analysisSource:"structured_model"});
    expect(integrated).not.toHaveProperty("analysisModel");
  });
});
