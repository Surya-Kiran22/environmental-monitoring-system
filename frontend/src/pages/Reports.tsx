import { useState } from "react";
import { API, get, post } from "../api";
import { ErrorBox, KV, Loading, Page, Panel, SectionTitle, Tag, fmtDT, useApi } from "../components/ui";

export default function Reports() {
  const { data, error, loading, reload } = useApi<any[]>(() => get("/api/reports"), []);
  const [hours, setHours] = useState(168);
  const [busy, setBusy] = useState(false);
  const [sel, setSel] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function generate() {
    setBusy(true); setMsg(null);
    try { const r = await post("/api/reports/generate", { hours }); setSel(r); reload(); }
    catch (e: any) { setMsg(`Generation failed: ${e.message}`); } finally { setBusy(false); }
  }
  async function open(id: string) { setSel(await get(`/api/reports/${id}`)); }
  async function approve() { setSel(await post(`/api/reports/${sel.id}/approve`, { actor: "Environmental Officer" })); reload(); }
  const c = sel?.content;

  return (
    <Page title="Reports" subtitle="Structured environmental monitoring reports • human approval • PDF download">
      <Panel title="GENERATE REPORT">
        <div className="flex flex-wrap gap-2 items-center">
          <select className="field" value={hours} onChange={(e) => setHours(Number(e.target.value))} aria-label="Monitoring period">
            {[[24, "Last 24 hours"], [72, "Last 3 days"], [168, "Last 7 days"], [720, "Last 30 days"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <button className="btn-go" onClick={generate} disabled={busy}>{busy ? "Assembling report…" : "Generate report"}</button>
          {msg && <span className="text-[12.5px] text-risk">{msg}</span>}
        </div>
        <p className="text-[11.5px] text-muted mt-2">Built from the latest agent run per station, incidents and investigation actions, standard comparisons, anomaly metrics and the PM2.5 forecast. Reports start as drafts until an officer approves them.</p>
      </Panel>

      <div className="grid xl:grid-cols-[340px_1fr] gap-6 mt-7">
        <div>
          <SectionTitle>Report history</SectionTitle>
          {error && <ErrorBox error={error} onRetry={reload} />}
          {loading && !data && <Loading what="reports" />}
          <div className="border border-line bg-white divide-y divide-line">
            {(data || []).length === 0 && <div className="p-4 text-[13px] text-muted">No reports yet.</div>}
            {(data || []).map((r) => (
              <button key={r.id} onClick={() => open(r.id)} className={`w-full text-left px-3 py-2.5 hover:bg-panel ${sel?.id === r.id ? "bg-[#f4f7ff]" : ""}`}>
                <div className="font-mono text-[12px]">{r.id}</div>
                <div className="text-[11.5px] text-muted">{fmtDT(r.period_start)} → {fmtDT(r.period_end)}</div>
                <Tag tone={r.status === "approved" ? "green" : "amber"}>{r.status}</Tag>
              </button>
            ))}
          </div>
        </div>
        {c && (
          <div>
            <div className="flex flex-wrap justify-between gap-3 items-start">
              <div><div className="font-mono text-[12px] text-muted">{sel.id}</div><h2 className="text-[18px] font-bold">{c.title}</h2>
                <div className="text-[12.5px] text-muted">{c.monitoring_location} · {fmtDT(c.period.start)} → {fmtDT(c.period.end)}</div></div>
              <div className="flex gap-2">
                {sel.status !== "approved" && <button className="btn-go btn-sm" onClick={approve}>Approve report</button>}
                <a className="btn-plain btn-sm" href={`${API}/api/reports/${sel.id}/pdf`} target="_blank" rel="noreferrer">Download PDF</a>
              </div>
            </div>
            <div className="mt-3"><KV rows={[["Human-review status", sel.status === "approved" ? `Approved by ${sel.approved_by} (${fmtDT(sel.approved_at)})` : "Draft — pending approval"],
              ["Stations", c.stations.length], ["Incidents", c.incidents.length], ["Alerts in period", c.alerts.length], ["Standards referenced", c.source_references.length]]} /></div>
            {(["air", "water", "noise"] as const).map((k) => (
              <div key={k}>
                <SectionTitle><span className="mt-5 block capitalize">{k} summary</span></SectionTitle>
                {c[k].length === 0 ? <p className="text-[12.5px] text-muted">No analysed stations.</p> : c[k].map((s: any) => (
                  <p key={s.station_id} className="text-[12.5px] mb-1.5"><b className="font-mono">{s.station_id}</b> — {s.alert_summary}</p>
                ))}
              </div>
            ))}
            <SectionTitle><span className="mt-5 block">Standard comparisons</span></SectionTitle>
            <div className="overflow-x-auto"><table className="grid-table">
              <thead><tr><th>Station</th><th>Parameter</th><th>Measured</th><th>Reference</th><th>Difference</th><th>Status</th></tr></thead>
              <tbody>{c.comparisons.map((r: any, i: number) => (
                <tr key={i}><td className="font-mono">{r.station_id}</td><td>{r.parameter}</td><td className="font-mono">{r.measured} <span className="text-muted text-[10.5px]">{r.period}</span></td>
                  <td className="font-mono">{r.limit} [{r.averaging}]</td><td className="font-mono">{r.difference} ({r.pct}%)</td><td><Tag tone={r.status === "exceedance" ? "red" : r.status === "compliant" ? "green" : "gray"}>{r.status}</Tag></td></tr>
              ))}</tbody>
            </table></div>
            {c.forecast && <><SectionTitle><span className="mt-5 block">Forecast</span></SectionTitle>
              <p className="text-[12.5px]">PM2.5 next 24 h at {c.forecast.station_id}: mean {c.forecast.next_24h_mean}, range {c.forecast.next_24h_min}–{c.forecast.next_24h_max} µg/m³ · MAE {c.forecast.metrics_one_step.mae} (persistence {c.forecast.persistence_baseline.mae}).</p></>}
            <SectionTitle><span className="mt-5 block">Recommended actions</span></SectionTitle>
            <ul className="list-disc pl-5 text-[12.5px]">{(c.recommended_actions.length ? c.recommended_actions : ["None open."]).map((r: string) => <li key={r}>{r}</li>)}</ul>
            <p className="text-[11px] text-muted mt-4">{c.disclaimer}</p>
          </div>
        )}
      </div>
    </Page>
  );
}
