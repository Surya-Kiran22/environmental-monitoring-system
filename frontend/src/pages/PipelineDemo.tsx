import { useEffect, useState } from "react";
import { get, post } from "../api";
import { Chip, ErrorBox, Json, Loading, Page, Panel, SectionTitle, Tag, fmtDT, fmtTime, num, useApi } from "../components/ui";

const FLOW = [
  ["intake", "Intake & Validation"], ["domain", "Air / Water / Noise"], ["weather", "Weather & Context"], ["anomaly", "Anomaly & Trend"],
  ["alert", "Alert & Investigation"], ["reviewer", "Standards Reviewer"], ["human_gate", "Human review gate"],
];

export default function PipelineDemo() {
  const stations = useApi<any[]>(() => get("/api/stations"), []);
  const runs = useApi<any[]>(() => get("/api/pipeline/runs?limit=40"), []);
  const [scope, setScope] = useState("ENV-ST-004");
  const [rid, setRid] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = useApi<any>(() => (rid ? get(`/api/pipeline/runs/${rid}`) : Promise.resolve(null)), [rid]);
  useEffect(() => { if (!rid && runs.data?.length) setRid(runs.data.find((r) => r.scope !== "NETWORK")?.id || runs.data[0].id); }, [runs.data, rid]);

  async function execute() {
    setBusy(true); setErr(null);
    try {
      const r = scope === "NETWORK" ? await post("/api/pipeline/run-network", { trigger: "pipeline_demo" }) : await post("/api/pipeline/run", { station_id: scope, trigger: "pipeline_demo" });
      await runs.reload(); setRid(r.run_id);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  async function decide(decision: string) {
    const r = await post(`/api/pipeline/runs/${rid}/decision`, { decision, actor: "Environmental Officer", note: "" });
    await runs.reload(); run.reload();
    if (r.reassessment?.run_id) setRid(r.reassessment.run_id);
  }
  const d = run.data;
  const executed = new Set((d?.trace || []).map((t: any) => (["air_quality", "water_quality", "noise"].includes(t.node) ? "domain" : t.node)));
  const reassessed = (d?.trace || []).filter((t: any) => t.node === "alert").length > 1;
  const review = d?.result?.review;

  return (
    <Page title="Pipeline Demo" subtitle="Agent execution visibility • LangGraph state machine, tool/API calls, retrieved standards, model outputs, reviewer feedback and human decision">
      <Panel title="COMMAND PANEL: RUN AGENT WORKFLOW">
        <div className="flex flex-wrap gap-2 items-center">
          <select className="field" value={scope} onChange={(e) => setScope(e.target.value)} aria-label="Scope">
            <option value="NETWORK">Whole network (8 stations)</option>
            {(stations.data || []).map((s) => <option key={s.id} value={s.id}>{s.id} — {s.name}</option>)}
          </select>
          <button className="btn-go" onClick={execute} disabled={busy}>{busy ? "Agents running…" : "Execute pipeline"}</button>
          {err && <span className="text-risk text-[12.5px]">{err}</span>}
        </div>
      </Panel>

      <SectionTitle><span className="mt-7 block">Workflow graph</span></SectionTitle>
      <div className="flex flex-wrap items-center gap-1.5">
        {FLOW.map(([k, l], i) => (
          <div key={k} className="flex items-center gap-1.5">
            <div className={`border px-3 py-2 text-[12px] ${executed.has(k) ? "bg-brand text-white border-brand" : "bg-white border-line text-muted"}`}>{l}{k === "alert" && reassessed && " ×2"}</div>
            {i < FLOW.length - 1 && <span className="text-muted">→</span>}
          </div>
        ))}
      </div>
      <p className="text-[11.5px] text-muted mt-2">Conditional edges: the intake node routes to the Air, Water or Noise agent by station type; the reviewer can send the draft back to the alert agent once for reassessment before the human-review gate.</p>

      <div className="grid xl:grid-cols-[300px_1fr] gap-6 mt-7">
        <div>
          <SectionTitle>Run history</SectionTitle>
          {runs.error && <ErrorBox error={runs.error} onRetry={runs.reload} />}
          <div className="border border-line bg-white divide-y divide-line max-h-[900px] overflow-y-auto">
            {(runs.data || []).map((r) => (
              <button key={r.id} onClick={() => setRid(r.id)} className={`w-full text-left px-3 py-2 hover:bg-panel ${rid === r.id ? "bg-[#f4f7ff] border-l-[3px] border-brand" : ""}`}>
                <div className="font-mono text-[11.5px]">{r.id}</div>
                <div className="text-[12px]">{r.scope} · <span className="text-muted">{r.trigger}</span></div>
                <div className="flex gap-1.5 mt-1 flex-wrap"><Tag tone={r.status.includes("await") ? "amber" : r.status === "approved" ? "green" : r.status === "failed" ? "red" : "gray"}>{r.status}</Tag>
                  {r.risk?.alert_category && <Chip value={r.risk.alert_category} />}</div>
              </button>
            ))}
          </div>
        </div>
        <div>
          {run.loading && !d && <Loading what="run" />}
          {d && (
            <>
              <div className="flex flex-wrap justify-between gap-3 items-start">
                <div><div className="font-mono text-[12px] text-muted">{d.id} · started {fmtDT(d.started_at)}</div>
                  <h2 className="text-[18px] font-bold">{d.scope === "NETWORK" ? "Network run" : `Station ${d.scope}`} — {d.status}</h2></div>
                <div className="flex gap-2 flex-wrap">
                  <button className="btn-go btn-sm" onClick={() => decide("approve")}>Approve findings</button>
                  <button className="btn-plain btn-sm" onClick={() => decide("reject")}>Reject</button>
                  <button className="btn-plain btn-sm" onClick={() => decide("request_reassessment")}>Request reassessment</button>
                </div>
              </div>
              {d.human_decision && <Panel className="mt-3" title="HUMAN DECISION"><span className="text-[13px]">{d.human_decision.decision} by {d.human_decision.actor} at {fmtDT(d.human_decision.timestamp)}</span></Panel>}
              {d.scope === "NETWORK" && (
                <>
                  <SectionTitle><span className="mt-5 block">Network events</span></SectionTitle>
                  <div className="space-y-3">{(d.events || []).map((e: any) => (
                    <div key={e.version} className="bg-white border border-line px-4 py-3"><b className="text-[13px]">{e.event}</b> <Tag>v{e.version}</Tag><div className="text-[11px] text-muted mb-2">{fmtTime(e.timestamp)}</div><Json data={e.payload} /></div>
                  ))}</div>
                  <SectionTitle><span className="mt-5 block">Station runs</span></SectionTitle>
                  <table className="grid-table"><thead><tr><th>Run</th><th>Station</th><th>Category</th><th>Risk</th></tr></thead>
                    <tbody>{(d.result?.children || []).map((c: any) => (
                      <tr key={c.run_id} className="clickable" onClick={() => setRid(c.run_id)}><td className="font-mono">{c.run_id}</td><td className="font-mono">{c.station_id}</td><td><Chip value={c.overall_category} /></td><td className="font-mono">{num(c.risk?.score)}</td></tr>
                    ))}</tbody></table>
                </>
              )}
              {d.scope !== "NETWORK" && (
                <>
                  <SectionTitle><span className="mt-5 block">Agent execution trace</span></SectionTitle>
                  <ol className="space-y-4">
                    {(d.trace || []).map((t: any, i: number) => (
                      <li key={i} className="border border-line bg-white">
                        <div className="flex flex-wrap justify-between gap-2 px-4 py-2.5 bg-panel border-b border-line">
                          <div><span className="font-mono text-[11px] text-muted mr-2">step {i + 1}</span><b className="text-[13px]">{t.agent}</b> <Tag>{t.node}</Tag> {t.llm_used && <Tag tone="blue">LLM</Tag>}</div>
                          <span className="font-mono text-[11px] text-muted">{t.duration_ms} ms</span>
                        </div>
                        <div className="p-4 grid lg:grid-cols-2 gap-4">
                          <div><div className="text-[12px] font-semibold mb-1">Input</div><Json data={t.input} max={160} />
                            <div className="text-[12px] font-semibold mt-3 mb-1">Tool / API calls ({t.tool_calls.length})</div>
                            {t.tool_calls.map((c: any, j: number) => (
                              <details key={j} className="mb-1.5"><summary className="text-[12px] font-mono cursor-pointer">{c.tool}</summary><Json data={c} max={220} /></details>
                            ))}
                          </div>
                          <div><div className="text-[12px] font-semibold mb-1">Output / findings</div><Json data={t.output} max={420} /></div>
                        </div>
                      </li>
                    ))}
                  </ol>
                  {review && (
                    <>
                      <SectionTitle><span className="mt-6 block">Reviewer feedback — {review.verdict} ({review.checks_passed}/{review.checks_total} checks)</span></SectionTitle>
                      <table className="grid-table"><thead><tr><th>Check</th><th>Alert</th><th>Result</th><th>Detail</th></tr></thead>
                        <tbody>{review.checks.map((c: any, i: number) => (
                          <tr key={i}><td>{c.check}</td><td className="text-[11.5px]">{c.alert || "—"}</td><td>{c.passed ? <Tag tone="green">pass</Tag> : <Tag tone="red">fail</Tag>}</td><td className="text-[11.5px] font-mono">{c.detail}</td></tr>
                        ))}</tbody></table>
                      {(review.issues.length > 0 || review.corrections.length > 0) && <div className="mt-3"><Json data={{ issues: review.issues, corrections: review.corrections }} /></div>}
                    </>
                  )}
                </>
              )}
            </>
          )}
        </div>
      </div>
    </Page>
  );
}
