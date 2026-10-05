import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { get, post } from "../api";
import { Chip, ErrorBox, Json, KV, LABEL, Loading, Page, Panel, SectionTitle, Tag, fmtDT, num, useApi } from "../components/ui";

export default function Alerts() {
  const [sp, setSp] = useSearchParams();
  const [status, setStatus] = useState("open,acknowledged,confirmed");
  const { data, error, loading, reload } = useApi<any[]>(() => get(`/api/alerts${status ? `?status=${status}` : ""}`), [status]);
  const sel = data?.find((a) => a.id === sp.get("id")) || data?.[0];
  const [answer, setAnswer] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => setAnswer(null), [sel?.id]);

  async function act(action: string) {
    await post(`/api/alerts/${sel.id}/action`, { action, actor: "Environmental Officer", note: "" });
    reload();
  }
  async function ask() {
    setBusy(true);
    try { setAnswer(await post("/api/standards/ask", { question: "What standard was used for this alert?", alert_id: sel.id })); } finally { setBusy(false); }
  }
  const ev = sel?.evidence || {};

  return (
    <Page title="Alert Center" subtitle="Environmental Alert & Investigation Agent • explainable alerts, deduplicated, awaiting human review">
      <div className="flex flex-wrap gap-2 mb-5">
        {[["open,acknowledged,confirmed", "Active"], ["open", "Open"], ["rejected", "Rejected"], ["closed", "Closed"], ["", "All"]].map(([v, l]) => (
          <button key={l} className={status === v ? "btn-go btn-sm" : "btn-plain btn-sm"} onClick={() => setStatus(v)}>{l}</button>
        ))}
      </div>
      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <Loading what="alerts" />}
      {data && data.length === 0 && <div className="text-[13px] text-muted">No alerts in this view. Run the environmental analysis from the dashboard to evaluate the network.</div>}
      {data && data.length > 0 && (
        <div className="grid xl:grid-cols-[minmax(320px,0.9fr)_1.5fr] gap-6">
          <div className="border border-line bg-white divide-y divide-line max-h-[820px] overflow-y-auto">
            {data.map((a) => (
              <button key={a.id} onClick={() => setSp({ id: a.id })} className={`w-full text-left px-4 py-3 hover:bg-panel ${a.id === sel?.id ? "bg-[#f4f7ff] border-l-[3px] border-brand" : ""}`}>
                <div className="flex justify-between gap-2"><span className="font-mono text-[11.5px] text-muted">{a.id} · {a.station_id}</span><Chip value={a.category} /></div>
                <div className="text-[13px] font-medium mt-1">{a.title}</div>
                <div className="text-[11px] text-muted mt-0.5">{a.alert_type} · seen {a.occurrences}× · last {fmtDT(a.last_seen)} · <span className="uppercase">{a.status}</span></div>
              </button>
            ))}
          </div>
          {sel && (
            <div>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div><div className="font-mono text-[12px] text-muted">{sel.id} · {sel.station_id} · {LABEL[sel.parameter] || sel.parameter}</div><h2 className="text-[18px] font-bold mt-1">{sel.title}</h2></div>
                <Chip value={sel.category} />
              </div>
              <Panel className="mt-4" title="WHY THIS ALERT WAS GENERATED"><p className="text-[13px]">{ev.why}</p></Panel>
              <div className="grid md:grid-cols-3 gap-3 mt-4">
                <Block title="Measured value">{ev.measured_value ? <KV rows={[
                  ["Latest 1-h", ev.measured_value.latest_hourly != null ? `${num(ev.measured_value.latest_hourly, 2)} ${ev.measured_value.unit}` : "—"],
                  ["Period value", ev.measured_value.period_value != null ? `${num(ev.measured_value.period_value, 2)} (${ev.measured_value.period_label})` : "—"],
                  ["Data coverage", ev.measured_value.coverage != null ? `${Math.round(ev.measured_value.coverage * 100)}%` : "—"]]} /> : <p className="text-[12px] text-muted">Not applicable</p>}</Block>
                <Block title="Applicable reference limit">{ev.applicable_reference ? <KV rows={[
                  ["Limit", ev.applicable_reference.limit], ["Averaging", ev.applicable_reference.averaging_period],
                  ["Standard", <span className="font-sans text-[11.5px]">{ev.applicable_reference.standard}</span>],
                  ["Basis", ev.applicable_reference.basis]]} /> : <p className="text-[12px] text-muted">No regulatory comparison for this alert type.</p>}</Block>
                <Block title="Calculated exceedance">{ev.calculated_exceedance ? <KV rows={[
                  ["Difference", <span className="text-risk font-semibold">{ev.calculated_exceedance.difference > 0 ? "+" : ""}{num(ev.calculated_exceedance.difference, 2)}</span>],
                  ["Percentage", `${num(ev.calculated_exceedance.percentage_difference)}%`],
                  ["Valid comparison", String(ev.calculated_exceedance.comparison_valid)]]} /> : <p className="text-[12px] text-muted">Not applicable</p>}</Block>
              </div>
              {ev.calculated_exceedance && <p className="text-[11px] text-muted mt-1.5">{ev.calculated_exceedance.formula}. {ev.calculated_exceedance.averaging_note}</p>}
              <SectionTitle><span className="mt-5 block">AI Interpretation</span></SectionTitle>
              <div className="border border-line bg-white px-4 py-3 text-[13px] leading-relaxed">{sel.ai_interpretation}</div>

              {(ev.supporting?.length > 0 || ev.weather_observations?.length > 0 || ev.cross_station || ev.potential_sources?.length > 0) && (
                <>
                  <SectionTitle><span className="mt-5 block">Supporting evidence</span></SectionTitle>
                  <ul className="text-[12.5px] space-y-1.5 list-disc pl-5">
                    {(ev.supporting || []).map((s: string, i: number) => <li key={i}>{s}</li>)}
                    {ev.cross_station && <li><b>Cross-station ({ev.cross_station.elevated}):</b> {ev.cross_station.summary}</li>}
                    {(ev.weather_observations || []).map((s: string, i: number) => <li key={`w${i}`}><b>Weather:</b> {s}</li>)}
                    {ev.anomaly && <li><b>Anomaly model:</b> latest score {num(ev.anomaly.latest_score, 3)}, {ev.anomaly.anomalous_hours_24h} anomalous hour(s) in 24 h.</li>}
                    {(ev.potential_sources || []).map((s: any) => <li key={s.id}><b>{s.label}:</b> {s.name}, {s.distance_km} km {s.bearing || ""} — not confirmed.</li>)}
                  </ul>
                </>
              )}

              <div className="flex flex-wrap gap-2 mt-6">
                <button className="btn-plain btn-sm" onClick={() => act("acknowledge")}>Acknowledge</button>
                <button className="btn-go btn-sm" onClick={() => act("confirm")}>Confirm alert</button>
                <button className="btn-plain btn-sm" onClick={() => act("reject")}>Reject (false positive)</button>
                <button className="btn-plain btn-sm" onClick={() => act("close")}>Close</button>
                {sel.incident_id && <Link className="btn-plain btn-sm" to={`/investigations?id=${sel.incident_id}`}>Open incident {sel.incident_id}</Link>}
                <button className="btn-plain btn-sm" onClick={ask} disabled={busy}>What standard was used for this alert?</button>
              </div>
              {answer && (
                <Panel className="mt-4" title="STANDARDS RAG ANSWER">
                  <p className="text-[13px]">{answer.answer}</p>
                  <div className="mt-3"><KV rows={[["Source document", answer.source_document], ["Relevant section", answer.section], ["Applicable limit", answer.applicable_limit],
                    ["Averaging period", answer.averaging_period], ["Unit", answer.unit]]} /></div>
                  {answer.supporting_text && <div className="mt-3"><div className="text-[12px] font-semibold mb-1">Supporting text</div><div className="bg-white border border-line px-3 py-2 text-[12px] whitespace-pre-wrap">{answer.supporting_text}</div></div>}
                </Panel>
              )}
              <details className="mt-5"><summary className="text-[12px] text-muted cursor-pointer">Raw alert record</summary><Json data={sel} max={400} /></details>
            </div>
          )}
        </div>
      )}
    </Page>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return <div><div className="text-[12px] font-bold mb-1.5">{title}</div>{children}</div>;
}
