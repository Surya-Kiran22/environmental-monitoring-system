import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { get, post } from "../api";
import { Chip, ErrorBox, KV, Loading, Page, Panel, SectionTitle, Tag, fmtDT, useApi } from "../components/ui";

const ACTIONS: [string, string][] = [
  ["review", "Review alert"], ["verify_sensor", "Verify sensor information"], ["request_field_inspection", "Request field inspection"],
  ["start_investigation", "Start investigation"], ["assign", "Assign investigation"], ["add_observation", "Add observation"],
  ["add_lab_result", "Add laboratory result"], ["confirm_anomaly", "Confirm anomaly"], ["reject_anomaly", "Reject anomaly (false positive)"],
  ["correct_regulatory_comparison", "Record correction to regulatory comparison"], ["escalate", "Escalate"], ["close", "Close incident"], ["reopen", "Reopen"],
];

export default function Investigations() {
  const [sp, setSp] = useSearchParams();
  const list = useApi<any[]>(() => get("/api/incidents"), []);
  const id = sp.get("id") || list.data?.find((i) => i.status !== "closed")?.id || list.data?.[0]?.id;
  const inc = useApi<any>(() => (id ? get(`/api/incidents/${id}`) : Promise.resolve(null)), [id]);
  const [action, setAction] = useState("review");
  const [note, setNote] = useState("");
  const [actor, setActor] = useState("Environmental Officer");
  const [assignee, setAssignee] = useState("");
  const [labK, setLabK] = useState("");
  const [labV, setLabV] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  async function submit() {
    setMsg(null);
    try {
      await post(`/api/incidents/${id}/actions`, { action, actor, note, assigned_to: assignee || null,
        lab_result: action === "add_lab_result" && labK ? { [labK]: labV } : null });
      setNote(""); setLabK(""); setLabV("");
      setMsg("Recorded.");
      inc.reload(); list.reload();
    } catch (e: any) { setMsg(`Failed: ${e.message}`); }
  }
  async function feedback(useful: boolean) {
    await post(`/api/incidents/${id}/recommendation-feedback`, { useful, actor });
    setMsg(`Feedback recorded — the epsilon-greedy recommender updates its estimate for this action.`);
    inc.reload();
  }
  const d = inc.data, ev = d?.evidence || {}, rec = d?.recommendation;

  return (
    <Page title="Investigation Center" subtitle="Human-in-the-loop review • verify, inspect, record findings and close or escalate incidents">
      {list.error && <ErrorBox error={list.error} onRetry={list.reload} />}
      {list.loading && !list.data && <Loading what="incidents" />}
      {list.data && (
        <div className="grid xl:grid-cols-[300px_1fr] gap-6">
          <div className="border border-line bg-white divide-y divide-line max-h-[820px] overflow-y-auto">
            {list.data.map((i) => (
              <button key={i.id} onClick={() => setSp({ id: i.id })} className={`w-full text-left px-3 py-2.5 hover:bg-panel ${i.id === id ? "bg-[#f4f7ff] border-l-[3px] border-brand" : ""}`}>
                <div className="font-mono text-[11.5px]">{i.id}</div>
                <div className="text-[12.5px] mt-0.5">{i.station_id} · {i.title}</div>
                <div className="mt-1 flex gap-1.5 flex-wrap"><Chip value={i.priority} /><Tag tone={i.status === "closed" ? "green" : "blue"}>{i.status}</Tag></div>
              </button>
            ))}
            {list.data.length === 0 && <div className="p-4 text-[13px] text-muted">No incidents yet.</div>}
          </div>
          {d && (
            <div>
              <div className="flex flex-wrap justify-between gap-3">
                <div><div className="font-mono text-[12px] text-muted">{d.id} · {d.station_id}</div><h2 className="text-[18px] font-bold">{d.title}</h2></div>
                <div className="flex gap-2 items-start"><Chip value={d.priority} /><Tag tone="blue">{d.status}</Tag></div>
              </div>
              <div className="grid lg:grid-cols-2 gap-5 mt-4">
                <KV rows={[["Incident ID", d.id], ["Parameter(s)", d.parameter], ["Station", d.station_id], ["Start time", fmtDT(d.start_time)],
                  ["Investigation status", d.investigation_status], ["Assigned to", d.assigned_to || "—"],
                  ["Measurement", d.measurement?.period_value != null ? `${d.measurement.period_value} ${d.measurement.unit} (${d.measurement.period_label})` : d.measurement?.latest_hourly ?? "—"],
                  ["Applicable reference", d.applicable_reference ? `${d.applicable_reference.limit} · ${d.applicable_reference.averaging_period} · ${d.applicable_reference.standard_id}` : "—"]]} />
                <div>
                  <Panel title="EVIDENCE"><p className="text-[12.5px] leading-relaxed">{ev.why}</p><p className="text-[12.5px] leading-relaxed mt-2 text-muted">{ev.interpretation}</p>
                    <div className="text-[11.5px] mt-2">Linked alerts: {(d.alerts || []).map((a: any) => <Link key={a.id} className="text-brand underline mr-2" to={`/alerts?id=${a.id}`}>{a.id}</Link>)}</div>
                  </Panel>
                  {rec && (
                    <Panel className="mt-3" title="RECOMMENDED NEXT STEP (EPSILON-GREEDY BANDIT)">
                      <p className="text-[13px] font-medium">{rec.recommended_action}</p>
                      <p className="text-[11.5px] text-muted mt-1">Context {rec.context} · mode {rec.mode} · ε = {rec.epsilon}. Ranked: {(rec.ranked || []).map((r: any) => `${r.action} (${r.expected_usefulness})`).join("; ")}</p>
                      <div className="flex gap-2 mt-2"><button className="btn-go btn-sm" onClick={() => feedback(true)}>Useful</button><button className="btn-plain btn-sm" onClick={() => feedback(false)}>Not useful</button></div>
                    </Panel>
                  )}
                </div>
              </div>

              <SectionTitle><span className="mt-7 block">Record officer action</span></SectionTitle>
              <Panel>
                <div className="grid md:grid-cols-3 gap-3 text-[12.5px]">
                  <label className="flex flex-col gap-1">Action<select className="field" value={action} onChange={(e) => setAction(e.target.value)}>{ACTIONS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
                  <label className="flex flex-col gap-1">Officer<input className="field" value={actor} onChange={(e) => setActor(e.target.value)} /></label>
                  {action === "assign" && <label className="flex flex-col gap-1">Assign to<input className="field" value={assignee} onChange={(e) => setAssignee(e.target.value)} /></label>}
                  {action === "add_lab_result" && <>
                    <label className="flex flex-col gap-1">Lab parameter<input className="field" value={labK} onChange={(e) => setLabK(e.target.value)} placeholder="e.g. turbidity_grab_NTU" /></label>
                    <label className="flex flex-col gap-1">Lab value<input className="field" value={labV} onChange={(e) => setLabV(e.target.value)} placeholder="e.g. 13.1" /></label></>}
                </div>
                <label className="flex flex-col gap-1 text-[12.5px] mt-3">Note / observation<textarea className="field min-h-[70px]" value={note} onChange={(e) => setNote(e.target.value)} /></label>
                <button className="btn-go mt-3" onClick={submit}>Record action</button>
                {msg && <span className="text-[12.5px] ml-3">{msg}</span>}
              </Panel>

              <SectionTitle><span className="mt-7 block">Action history</span></SectionTitle>
              <ol className="border-l-2 border-line ml-2 space-y-3">
                {(d.actions || []).map((a: any, i: number) => (
                  <li key={i} className="pl-4 relative text-[12.5px]">
                    <span className="absolute -left-[6px] top-1.5 w-[10px] h-[10px] rounded-full bg-brand" />
                    <div><b>{a.action.replace(/_/g, " ")}</b> by {a.actor} <span className="text-muted font-mono text-[11px]">{fmtDT(a.timestamp)}</span></div>
                    {a.note && <div className="text-muted">{a.note}</div>}
                    {a.data?.lab_result && <div className="font-mono text-[11.5px]">lab: {JSON.stringify(a.data.lab_result)}</div>}
                    {a.data?.assigned_to && <div className="text-[11.5px]">assigned to {a.data.assigned_to}</div>}
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      )}
    </Page>
  );
}
