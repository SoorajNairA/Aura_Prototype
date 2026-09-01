export type VerificationStatus=
  |"source_verified"
  |"tool_verified"
  |"cross_checked"
  |"estimated"
  |"conceptual"
  |"failed"
  |"unsupported"
  |string;

export type WorkState="planned"|"in_progress"|"paused"|"completed"|"skipped"|"abandoned"|string;

export interface EvidencePresentation {
  evidenceId:string;
  publisher?:string;
  document?:string;
  verifiedProperty?:string;
  retrievedAt?:string;
  status?:VerificationStatus;
  sourceUrl?:string;
  details?:string;
}

export interface VerificationFindingPresentation {
  findingId:string;
  status:VerificationStatus;
  category?:string;
  summary:string;
  details?:string;
  semanticTargets:string[];
  evidenceIds:string[];
  severity?:string;
  code?:string;
}

export interface WorkHistoryEntry {
  timestamp?:string;
  fromState?:WorkState;
  toState:WorkState;
  reason?:string;
}

export interface WorkItemPresentation {
  workItemId:string;
  title:string;
  description?:string;
  state:WorkState;
  allowedTransitions:string[];
  reason?:string;
  history:WorkHistoryEntry[];
  relatedComponentIds:string[];
  relatedRequirementIds:string[];
  relatedFindingIds:string[];
}

export interface ScenarioImpactPresentation {
  scenarioId?:string;
  baseRevisionId?:string|number;
  changeSummary:string;
  changedIds:string[];
  affectedIds:string[];
  verificationBefore?:string;
  verificationAfter?:string;
  confidenceBefore?:string;
  confidenceAfter?:string;
  knownChanges:string[];
  derivedImpacts:{category?:string;summary:string;status?:string}[];
  uncertainties:string[];
  stale:boolean;
  applicable:boolean;
  compatibilityDecision?:string;
  analysisSource?:string;
}

const words=(value:unknown)=>String(value||"").trim().toLowerCase().replaceAll("-","_");

export function statusLabel(value:unknown){return words(value).replaceAll("_"," ").toUpperCase()||"UNKNOWN"}

export function statusTone(value:unknown){
  const state=words(value);
  if(state.includes("fail")||state.includes("abandon")||state.includes("unsupported")||state.includes("incompatible")||state.includes("invalid")||state.includes("reject"))return "fail";
  if(state.includes("estimate")||state.includes("concept")||state.includes("pause")||state.includes("limit")||state.includes("warn"))return "warn";
  if(state.includes("verified")||state.includes("cross_checked")||state.includes("ready")||state.includes("complete")||state.includes("pass"))return "pass";
  return "neutral";
}

export function projectStatus(project:{status?:string;capability?:{status?:string}}|undefined,verification:any){
  if(!project)return "GENERATING";
  const raw=words(project.status);
  if(raw.includes("incomplete")||raw.includes("fail"))return "BUILD INCOMPLETE";
  if(raw.includes("generat"))return "GENERATING";
  if(raw.includes("verify"))return "VERIFYING";
  const summary=verification?.summary||{};
  const limitations=Number(summary.estimated||0)+Number(summary.conceptual||0)+Number(summary.unsupported||0);
  const failed=Number(summary.failed||0);
  const capability=words(project.capability?.status);
  if(failed>0)return "READY WITH LIMITATIONS";
  if(limitations>0||capability.includes("limitation"))return "READY WITH LIMITATIONS";
  return raw.includes("ready")?"READY":statusLabel(raw);
}

export function findingPresentation(raw:any):VerificationFindingPresentation {
  return {
    findingId:String(raw?.findingId??raw?.id??"finding"),
    status:String(raw?.status??raw?.state??"unsupported"),
    category:raw?.category??raw?.domain,
    summary:String(raw?.summary??raw?.check??raw?.title??raw?.id??"Engineering finding"),
    details:raw?.details??raw?.message??raw?.reason??raw?.userMessage,
    semanticTargets:[...(raw?.semanticTargets??raw?.entity_ids??raw?.entityIds??[])],
    evidenceIds:[...(raw?.evidenceIds??raw?.evidence_ids??[])],
    severity:raw?.severity??raw?.criticality,
    code:raw?.code??raw?.checkId,
  };
}

export function evidencePresentation(raw:any,id="evidence"):EvidencePresentation {
  const source=raw?.source||{};
  return {
    evidenceId:String(raw?.evidenceId??raw?.id??id),
    publisher:raw?.publisher??source?.publisher,
    document:raw?.document??raw?.title??source?.document,
    verifiedProperty:raw?.verifiedProperty??raw?.property??raw?.claim,
    retrievedAt:raw?.retrievedAt??raw?.retrieved_at??raw?.timestamp,
    status:raw?.status??raw?.state,
    sourceUrl:raw?.sourceUrl??raw?.source_url??raw?.url??source?.url,
    details:raw?.details??raw?.summary??raw?.message,
  };
}

export function workItemPresentation(raw:any):WorkItemPresentation {
  return {
    workItemId:String(raw?.workItemId??raw?.id??"work-item"),
    title:String(raw?.title??"Engineering work item"),
    description:raw?.description,
    state:String(raw?.state??"planned").toLowerCase(),
    allowedTransitions:[...(raw?.allowedTransitions??raw?.allowed_transitions??[])],
    reason:raw?.reason??raw?.currentReason,
    history:[...(raw?.history??raw?.transitionHistory??[])],
    relatedComponentIds:[...(raw?.relatedComponentIds??raw?.related_component_ids??[])],
    relatedRequirementIds:[...(raw?.relatedRequirementIds??raw?.related_requirement_ids??[])],
    relatedFindingIds:[...(raw?.relatedFindingIds??raw?.related_finding_ids??[])],
  };
}

export function scenarioPresentation(raw:any):ScenarioImpactPresentation {
  const analysis=raw?.analysis??raw;
  const delta=analysis?.verification?.delta??{};
  const explanations=[...(analysis?.explanations??[])];
  return {
    scenarioId:raw?.scenarioId??raw?.id,
    baseRevisionId:raw?.baseRevisionId??raw?.base_revision_id,
    changeSummary:String(raw?.changeSummary??raw?.summary??explanations.find((item:any)=>item.kind==="KNOWN_CHANGE")?.message??"Candidate engineering change"),
    changedIds:[...(raw?.changedIds??raw?.changed_ids??analysis?.diff?.changedComponents??analysis?.diff?.removedComponents??[])],
    affectedIds:[...(raw?.affectedIds??raw?.affected_ids??analysis?.impact?.affectedComponentIds??[])],
    verificationBefore:raw?.verificationBefore??raw?.verification_before??delta?.readinessBefore,
    verificationAfter:raw?.verificationAfter??raw?.verification_after??delta?.readinessAfter,
    confidenceBefore:raw?.confidenceBefore??raw?.confidence_before,
    confidenceAfter:raw?.confidenceAfter??raw?.confidence_after??analysis?.confidence,
    knownChanges:[...(raw?.knownChanges??raw?.known_changes??explanations.filter((item:any)=>item.kind==="KNOWN_CHANGE"))],
    derivedImpacts:[...(raw?.derivedImpacts??raw?.derived_impacts??explanations.filter((item:any)=>item.kind==="DERIVED_IMPACT"))].map((impact:any)=>typeof impact==="string"?{summary:impact}:{...impact,summary:impact.summary??impact.message}),
    uncertainties:[...(raw?.uncertainties??explanations.filter((item:any)=>item.kind==="UNCERTAINTY"))].map((item:any)=>typeof item==="string"?item:String(item?.summary??item?.message??"Uncertainty")),
    stale:Boolean(raw?.stale),
    applicable:Boolean(raw?.applicable??analysis?.applicable??false),
    compatibilityDecision:analysis?.semanticAssessment?.decision,
    analysisSource:analysis?.ai?.source,
  };
}

export const requiresReason=(state:string)=>["paused","skipped","abandoned"].includes(words(state));

export function workSummary(items:WorkItemPresentation[]){
  return items.reduce<Record<string,number>>((counts,item)=>{const key=words(item.state);counts[key]=(counts[key]||0)+1;return counts},{});
}
