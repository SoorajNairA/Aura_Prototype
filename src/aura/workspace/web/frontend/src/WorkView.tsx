import { useEffect, useState } from "react";
const action: Record<string, string> = {
  IN_PROGRESS: "Start / Resume",
  PAUSED: "Pause",
  COMPLETED: "Complete",
  SKIPPED: "Skip",
  ABANDONED: "Abandon",
};
export function WorkView({
  projectId,
  selectedComponentId,
  api,
}: {
  projectId: string;
  selectedComponentId?: string | null;
  api: (p: string, i?: RequestInit) => Promise<Response>;
}) {
  const [data, setData] = useState<any>({ items: [], summary: { counts: {} } }),
    [selected, setSelected] = useState<any>(),
    [reasonFor, setReasonFor] = useState<string>(),
    [reason, setReason] = useState(""),
    [error, setError] = useState(""),
    [scenario, setScenario] = useState<any>(),
    [replacement, setReplacement] = useState("SG90 Micro Servo");
  const refresh = () =>
    api(`/api/projects/${projectId}/work`)
      .then((r) => r.json())
      .then(setData);
  useEffect(() => {
    setScenario(undefined);
    setSelected(undefined);
    refresh();
  }, [projectId]);
  const transition = async (target: string) => {
    if (["PAUSED", "SKIPPED", "ABANDONED"].includes(target) && !reasonFor) {
      setReasonFor(target);
      return;
    }
    const r = await api(
        `/api/projects/${projectId}/work/${selected.id}/transition`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ targetState: target, reason }),
        },
      ),
      v = await r.json();
    if (!r.ok) {
      setError(v.detail?.code);
      return;
    }
    setSelected(v);
    setReasonFor(undefined);
    setReason("");
    setError("");
    refresh();
  };
  const create = async () => {
    const title = prompt("Engineering work title");
    if (title) {
      await api(`/api/projects/${projectId}/work`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          title,
          relatedComponentIds: selectedComponentId ? [selectedComponentId] : [],
        }),
      });
      refresh();
    }
  };
  const analyze = async () => {
    const r = await api(`/api/projects/${projectId}/scenarios`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        targetSemanticId: selectedComponentId,
        changeType: "REPLACE_COMPONENT",
        value: { name: replacement },
      }),
    });
    setScenario(await r.json());
  };
  const c = data.summary?.counts || {};
  return (
    <div className="work-view" data-testid="work-view">
      <header>
        <h1>ENGINEERING WORK</h1>
        <p>
          {data.summary?.total || 0} items · {c.COMPLETED || 0} completed ·{" "}
          {c.IN_PROGRESS || 0} in progress · {c.PAUSED || 0} paused
        </p>
        <button onClick={create}>NEW WORK</button>
      </header>
      <div className="work-grid">
        <nav>
          {!data.items.length && <p>No engineering work yet.</p>}
          {data.items.map((x: any) => (
            <button key={x.id} onClick={() => setSelected(x)}>
              <b>{x.title}</b>
              <span>{x.state.replaceAll("_", " ")}</span>
              {x.currentReason && <q>{x.currentReason}</q>}
            </button>
          ))}
        </nav>
        {selected && (
          <aside data-testid="work-detail">
            <h2>{selected.title}</h2>
            <p>{selected.description}</p>
            <b>STATE: {selected.state}</b>
            {selected.currentReason && <p>Reason: {selected.currentReason}</p>}
            <div>
              {selected.allowedTransitions.map((x: string) => (
                <button key={x} onClick={() => transition(x)}>
                  {action[x]}
                </button>
              ))}
            </div>
            {reasonFor && (
              <div role="dialog">
                <label>
                  Reason required
                  <textarea
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                  />
                </label>
                <button
                  disabled={!reason.trim()}
                  onClick={() => transition(reasonFor)}
                >
                  CONFIRM
                </button>
              </div>
            )}
            {error && <p>{error}</p>}
            <h3>RELATED</h3>
            <code>
              {[
                ...selected.relatedComponentIds,
                ...selected.relatedRequirementIds,
                ...selected.relatedFindingIds,
              ].join("\n") || "None"}
            </code>
            <h3>HISTORY</h3>
            {selected.transitionHistory.map((x: any) => (
              <p key={x.timestamp}>
                {x.fromState} → {x.toState}
                {x.reason && <> · {x.reason}</>}
              </p>
            ))}
          </aside>
        )}
      </div>
      {selectedComponentId && (
        <section className="what-if">
          <h2>WHAT-IF ANALYSIS</h2>
          <input
            aria-label="Replacement component"
            value={replacement}
            onChange={(e) => setReplacement(e.target.value)}
          />
          <button onClick={analyze}>ANALYZE</button>
          {scenario?.analysis && (
            <div data-testid="what-if-panel">
              <p>
                {scenario.analysis.current.component.name} →{" "}
                {scenario.analysis.candidate.component.name}
              </p>
              <b>CONFIDENCE: {scenario.analysis.confidence}</b>
              <p>VERIFICATION: {scenario.analysis.verification.delta.current} → {scenario.analysis.verification.delta.candidate}</p>
              <p>
                AFFECTED:{" "}
                {scenario.analysis.impact.affectedComponentIds.join(", ")}
              </p>
              {scenario.analysis.explanations.map((x: any, i: number) => (
                <p key={i}>
                  <b>{x.kind}</b> {x.message}
                </p>
              ))}
              <button
                onClick={async () => {
                  await api(
                    `/api/projects/${projectId}/scenarios/${scenario.scenarioId}`,
                    { method: "DELETE" },
                  );
                  setScenario(undefined);
                }}
              >
                DISCARD
              </button>
              <button
                disabled={!scenario.analysis.verification.accepted}
                onClick={async () => {
                  await api(
                    `/api/projects/${projectId}/scenarios/${scenario.scenarioId}/apply`,
                    { method: "POST" },
                  );
                  setScenario(undefined);
                }}
              >
                APPLY CHANGE
              </button>
              <button
                onClick={async () => {
                  await api(
                    `/api/projects/${projectId}/scenarios/${scenario.scenarioId}/work`,
                    { method: "POST" },
                  );
                  refresh();
                }}
              >
                CREATE WORK ITEM
              </button>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
