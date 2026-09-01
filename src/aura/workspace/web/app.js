const state = {
  projectId: null,
  graph: null,
  representations: [],
  selectedId: null,
  hoverId: null,
  focusIds: new Set(),
  criticalIds: new Set(),
  verification: null,
  narrations: [],
  narrationTimer: null,
  narrationSuppressedUntil: 0,
  events: [],
  socket: null,
  lastEventId: 0,
  reconnectAttempt: 0,
  reconnectTimer: null,
};
const MAX_RECONNECT_ATTEMPTS = 6;
const $ = (id) => document.getElementById(id);
function entities(kind) {
  return state.graph ? state.graph.entities.filter((x) => x.kind === kind) : [];
}
function entity(id) {
  return state.graph?.entities.find((x) => x.id === id);
}
function highlight(id) {
  if (state.criticalIds.has(id)) return "critical";
  if (state.selectedId === id) return "selected";
  if (state.focusIds.has(id)) return "aura-focus";
  if (state.hoverId === id) return "hover";
  return "";
}
function render() {
  if (!state.graph) return;
  const project = entity(state.graph.project_id);
  $("title").textContent = project.name;
  $("tree").innerHTML = tree(project.id);
  $("canvas").innerHTML = entities("component")
    .map(
      (c) =>
        `<button class="component ${highlight(c.id)}" data-id="${c.id}">${c.name}<small><br>${c.metadata.role || ""}</small></button>`,
    )
    .join("");
  document.querySelectorAll(".component").forEach((el) => {
    el.onmouseenter = () => {
      state.hoverId = el.dataset.id;
      render();
    };
    el.onmouseleave = () => {
      state.hoverId = null;
      render();
    };
    el.onclick = () => select(el.dataset.id);
  });
  const selected = entity(state.selectedId);
  $("component-info").textContent = selected
    ? `${selected.name} — ${selected.metadata.role || ""} — ${selected.verification_status} — ${selected.metadata.description || ""}`
    : "Select a semantic component.";
  const related = selected ? entities("verification_result").filter((v) =>
    (v.metadata.semanticIds || v.metadata.entity_ids || []).includes(selected.id)) : [];
  $("component-verification").innerHTML = related.length
    ? `<h3>Verified properties, warnings, and assumptions</h3>${related.map((v) =>
      `<article class="finding ${v.verification_status}"><b>${v.metadata.check}</b><span>${v.verification_status}</span><p>${v.name}</p>${(v.metadata.evidenceIds || []).map((id) => `<button class="evidence-link" data-evidence="${id}">Inspect source</button>`).join("")}${(v.verification_status === "failed" || v.metadata.check === "flyback") ? `<button class="repair-link" data-finding="${v.id}">Ask AURA to fix</button>` : ""}</article>`).join("")}`
    : "";
  document.querySelectorAll(".evidence-link").forEach((button) =>
    button.onclick = () => inspectEvidence(button.dataset.evidence));
  document.querySelectorAll(".repair-link").forEach((button) =>
    button.onclick = () => requestRepair(button.dataset.finding));
  const summary = state.verification?.summary || {};
  $("verification-summary").innerHTML = Object.entries(summary).map(([status, count]) =>
    `<span class="status-chip ${status}"><b>${count}</b> ${status.replaceAll("_", " ")}</span>`).join("");
  $("warnings").innerHTML = entities("verification_result")
    .map(
      (v) =>
        `<li class="${v.metadata.severity || ""}">${v.name} [${v.verification_status}]</li>`,
    )
    .join("");
  $("narration-feed").innerHTML = state.narrations.slice(-8).reverse().map((n) =>
    `<button class="narration-item ${n.priority}" data-narration="${n.narrationId}">${n.text}<small>${n.kind.replaceAll("_", " ")}${n.evidenceIds.length ? ` · <span class="narration-evidence" data-evidence="${n.evidenceIds[0]}">${n.evidenceIds.length} evidence</span>` : ""}</small></button>`).join("");
  document.querySelectorAll(".narration-item").forEach((button) => button.onclick = () => {
    const item=state.narrations.find((n) => n.narrationId === button.dataset.narration);
    if(item) applyNarrationFocus(item);
  });
  document.querySelectorAll(".narration-evidence").forEach((link) => link.onclick = (event) => {event.stopPropagation();inspectEvidence(link.dataset.evidence)});
  const representation = state.representations.find(
    (x) => x.componentId === state.selectedId,
  );
  $("representation").textContent = representation
    ? `Representation: ${representation.type} — ${representation.status}; fallback: ${representation.fallbackType}`
    : "Select a component to inspect its representation state.";
  const failed = state.representations.filter((x) => x.status === "fallback" || x.status === "failed");
  if (failed.length) $("representation").insertAdjacentHTML("beforeend", `<p><b>REPRESENTATION UNAVAILABLE</b><br>The project, verification, and semantic assembly remain valid.</p>${failed.map((x) => `<button class="retry-representation" data-representation="${x.representationId}">Retry ${x.type}</button>`).join(" ")}`);
  document.querySelectorAll(".retry-representation").forEach((button) => button.onclick = () => retryRepresentation(button.dataset.representation));
}
async function retryRepresentation(id) {
  $("status").textContent = "Retrying representation; project truth remains available.";
  const response = await fetch(`/api/projects/${state.projectId}/representations/${id}/retry`, {method:"POST", headers:{"Idempotency-Key":crypto.randomUUID()}});
  if (!response.ok) { $("status").textContent = "Representation retry failed. The saved project remains valid; retry when the generator is available."; return; }
  await loadProject(); $("status").textContent = "Representation recovered.";
}
function renderProgress(){const types=new Set(state.events.map((x)=>x.type));const warnings=state.events.filter((x)=>x.type==="warning.created").length;const stages=[
  ["project.started","Understanding request"],["revision.committed","Project structure planned"],
  ["verification.completed",`Design checked${warnings?` · ${warnings} warning${warnings===1?"":"s"}`:""}`],
  ["representation.ready","Engineering representation ready"],["project.ready","Project ready"]];
  $("progress").innerHTML=stages.map(([type,label])=>`<span class="event">${types.has(type)?"✓":"○"} ${label}</span>`).join("")}
function tree(id) {
  const item = entity(id);
  const children = state.graph.entities.filter(
    (x) =>
      x.parent_id === id &&
      ![
        "verification_result",
        "connection",
        "evidence",
        "assumption",
        "requirement",
        "constraint",
      ].includes(x.kind),
  );
  return `<div class="node" data-id="${item.id}">${item.name}${children.map((x) => tree(x.id)).join("")}</div>`;
}
function select(id) {
  if (!entity(id)) return;
  state.narrationSuppressedUntil=Date.now()+3000;
  clearTimeout(state.narrationTimer);
  state.focusIds=new Set();
  state.selectedId = id;
  render();
  const frame = $("representation-view");
  frame.contentWindow?.postMessage(
    { type: "aura.workspace.selection", semanticId: id },
    location.origin,
  );
}
window.auraFocus = (ids, explanation) => {
  state.focusIds = new Set(ids.filter(entity));
  $("status").textContent = explanation;
  render();
  $("representation-view").contentWindow?.postMessage(
    { type: "aura.workspace.focus", semanticIds: [...state.focusIds] },
    location.origin,
  );
};
async function loadProject() {
  const project = await (
    await fetch(`/api/projects/${state.projectId}`)
  ).json();
  state.representations = project.representations || [];
  localStorage.setItem("aura.lastProjectId", state.projectId);
  const frame = $("representation-view");
  frame.src = `/assets/representation/index.html?projectId=${encodeURIComponent(state.projectId)}`;
  frame.style.display = "block";
  [state.graph, state.verification, state.narrations] = await Promise.all([
    fetch(`/api/projects/${state.projectId}/graph`).then((response) => response.json()),
    fetch(`/api/projects/${state.projectId}/verification`).then((response) => response.json()),
    fetch(`/api/projects/${state.projectId}/narrations`).then((response) => response.json()),
  ]);
  const revisions = await (
    await fetch(`/api/projects/${state.projectId}/revisions`)
  ).json();
  $("revisions").innerHTML = revisions
    .map((r) => `<li>${r.summary}</li>`)
    .join("");
  state.criticalIds = new Set(
    entities("verification_result")
      .filter((v) => v.metadata.severity === "critical")
      .flatMap((v) => v.metadata.entity_ids || []),
  );
  render();
}

class NoSpeechProvider { available(){return false} speak(_text,_done){_done?.()} stop(){} }
class BrowserSpeechProvider {
  available(){return "speechSynthesis" in window && "SpeechSynthesisUtterance" in window}
  speak(text,done){const utterance=new SpeechSynthesisUtterance(text);utterance.rate=1.03;utterance.onend=done;utterance.onerror=done;speechSynthesis.speak(utterance)}
  stop(){speechSynthesis.cancel()}
}
class SpeechQueue {
  constructor(provider,limit=6){this.provider=provider;this.limit=limit;this.items=[];this.active=null}
  enqueue(item){if(!voiceEnabled()||!this.provider.available())return;if(item.priority==="high"){this.provider.stop();this.active=null;this.items=this.items.filter((x)=>x.priority==="high")}this.items.push(item);this.items=this.items.slice(-this.limit);this.next()}
  next(){if(this.active||!this.items.length)return;this.active=this.items.shift();this.provider.speak(this.active.text,()=>{markSpoken(this.active);clearNarrationFocus();this.active=null;this.next()})}
  clear(){this.items=[];this.active=null;this.provider.stop()}
}
const speechQueue=new SpeechQueue(("speechSynthesis" in window)?new BrowserSpeechProvider():new NoSpeechProvider());
const voiceEnabled=()=>localStorage.getItem("aura.voice.enabled")==="true";
const spokenKey=()=>`aura.spoken.${state.projectId}`;
const spokenIds=()=>new Set(JSON.parse(localStorage.getItem(spokenKey())||"[]"));
function markSpoken(item){const ids=spokenIds();ids.add(item.narrationId);localStorage.setItem(spokenKey(),JSON.stringify([...ids].slice(-200)))}
function applyNarrationFocus(item){clearTimeout(state.narrationTimer);state.focusIds=new Set(item.semanticIds.filter(entity));render();$("representation-view").contentWindow?.postMessage({type:"aura.workspace.focus",semanticIds:[...state.focusIds]},location.origin);if(!voiceEnabled())state.narrationTimer=setTimeout(clearNarrationFocus,5000)}
function clearNarrationFocus(){state.focusIds.clear();render();$("representation-view").contentWindow?.postMessage({type:"aura.workspace.focus",semanticIds:[]},location.origin)}
function cancelNarrationFocus(){clearTimeout(state.narrationTimer);clearNarrationFocus()}
function receiveNarration(item,historical){if(state.narrations.some((x)=>x.narrationId===item.narrationId))return;state.narrations.push(item);render();if(!historical&&!spokenIds().has(item.narrationId)){if(Date.now()>state.narrationSuppressedUntil)applyNarrationFocus(item);speechQueue.enqueue(item)}}
function presentFreshNarrations(){const unspoken=state.narrations.filter((x)=>!spokenIds().has(x.narrationId));const urgent=unspoken.filter((x)=>x.priority==="high").slice(-1);const completion=unspoken.filter((x)=>x.kind==="completion").slice(-1);for(const item of [...urgent,...completion]){applyNarrationFocus(item);speechQueue.enqueue(item)}}
$("voice-enabled").checked=voiceEnabled();
$("voice-enabled").onchange=(event)=>{localStorage.setItem("aura.voice.enabled",String(event.target.checked));if(!event.target.checked)speechQueue.clear()};
$("stop-speaking").onclick=()=>speechQueue.clear();
function inspectEvidence(id) {
  const evidence = entities("evidence").find((item) => item.id === id)?.metadata;
  if (!evidence) return;
  $("evidence-detail").textContent = JSON.stringify({
    title: evidence.title, publisher: evidence.publisher, kind: evidence.kind,
    retrievedAt: evidence.retrievedAt, properties: evidence.properties,
    source: evidence.source, contentHash: evidence.contentHash,
  }, null, 2);
  $("evidence-dialog").showModal();
}
$("close-evidence").onclick = () => $("evidence-dialog").close();
async function requestRepair(findingId) {
  const response = await fetch(`/api/projects/${state.projectId}/verification/${findingId}/repair-proposal`, {method:"POST"});
  const proposal = await response.json();
  $("change").textContent = response.ok
    ? `Repair preview (not applied): ${proposal.summary}\nAffected: ${proposal.affectedSemanticIds.join(", ")}\nVerification: ${proposal.verification.checks.map((x) => `${x.state}: ${x.message}`).join("; ")}`
    : JSON.stringify(proposal);
}
function connect(after = 0) {
  clearTimeout(state.reconnectTimer);
  if (state.socket) state.socket.close();
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  state.socket = new WebSocket(
    `${scheme}://${location.host}/api/projects/${state.projectId}/events?afterEventId=${after}`,
  );
  state.socket.onmessage = async (message) => {
    const event = JSON.parse(message.data);
    if (event.eventId <= state.lastEventId) return;
    state.lastEventId = event.eventId;
    state.reconnectAttempt = 0;
    $("reconnect").hidden = true;
    state.events.push(event);
    renderProgress();
    $("timeline").insertAdjacentHTML(
      "beforeend",
      `<span class="event">${event.eventId}. ${event.type}</span>`,
    );
    if (event.type === "task.fallback_used")
      $("status").textContent = "Using deterministic fallback";
    else if (event.type === "planning.live_model")
      $("status").textContent = "Planning with live model";
    else if (event.type === "project.ready")
      $("status").textContent = "Project ready";
    if (event.type === "focus.requested")
      window.auraFocus(event.payload.entity_ids, event.payload.explanation);
    if (event.type === "narration.created") receiveNarration(event.payload,event.historical);
    if (event.type === "revision.committed") await loadProject();
  };
  state.socket.onclose = () => {
    if (!state.projectId) return;
    if (state.reconnectAttempt >= MAX_RECONNECT_ATTEMPTS) {
      $("status").textContent = "Live updates disconnected. The loaded project remains available.";
      $("reconnect").hidden = false;
      return;
    }
    const delay = Math.min(1000 * 2 ** state.reconnectAttempt++, 15000);
    state.reconnectTimer = setTimeout(() => connect(state.lastEventId), delay);
  };
}
$("reconnect").onclick = () => { state.reconnectAttempt = 0; $("reconnect").hidden = true; connect(state.lastEventId); };
$("create").onclick = async () => {
  state.events = [];
  state.lastEventId = 0;
  $("timeline").innerHTML = "";
  renderProgress();
  $("status").textContent = "Understanding objective â†’ Planning project...";
  const response = await fetch("/api/projects", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      objective: $("objective").value,
      planningMode: $("mode").value,
      operationId: crypto.randomUUID(),
    }),
  });
  if (!response.ok) {
    const error=await response.json();
    $("status").textContent = error.detail?.status === "NEEDS_CLARIFICATION" ? `Clarification needed: ${error.detail.questions?.[0]}` : `Unsupported: ${error.detail?.reasons?.[0] || "Project could not be created"}`;
    return;
  }
  const project = await response.json();
  state.projectId = project.projectId;
  speechQueue.clear();
  $("status").textContent =
    project.planningMode === "deterministic_fallback"
      ? "Using deterministic fallback"
      : "Project ready";
  await loadProject();
  presentFreshNarrations();
  connect(0);
};
$("modify").onclick = async () => {
  if (!state.selectedId) {
    $("change").textContent = "Select component-driver first.";
    return;
  }
  const response = await fetch(
    `/api/projects/${state.projectId}/modifications`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        selectedComponentId: state.selectedId,
        request: $("modification").value,
      }),
    },
  );
  const result = await response.json();
  $("change").textContent = response.ok
    ? `${result.before.name} → ${result.after.name}\n${result.summary}`
    : JSON.stringify(result);
  if (response.ok) await loadProject();
};
async function listProjects() {
  const projects = await (await fetch("/api/projects")).json();
  $("projects").innerHTML =
    '<option value="">Existing projects</option>' +
    projects
      .map(
        (p) =>
          `<option value="${p.projectId}">${p.projectId} — revision ${p.revision}</option>`,
      )
      .join("");
}
$("open-project").onclick = async () => {
  const id = $("projects").value;
  if (!id) return;
  state.projectId = id;
  speechQueue.clear();
  state.events = [];
  state.lastEventId = 0;
  $("timeline").innerHTML = "";
  renderProgress();
  await loadProject();
  connect(0);
  $("status").textContent = "Recovered persisted project";
};
listProjects();
const lastProjectId=localStorage.getItem("aura.lastProjectId");
if(lastProjectId){state.projectId=lastProjectId;loadProject().then(()=>connect(0)).catch(()=>localStorage.removeItem("aura.lastProjectId"));}
window.addEventListener("message", (event) => {
  if (
    event.origin === location.origin &&
    event.data?.type === "aura.representation.selection"
  )
    select(event.data.semanticId);
  if (event.origin === location.origin && event.data?.type === "aura.representation.user_interaction")
    cancelNarrationFocus();
});
