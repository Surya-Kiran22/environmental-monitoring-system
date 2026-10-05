import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis, ComposedChart } from "recharts";
import { get, post } from "../api";
import { Chip, ErrorBox, LABEL, Loading, Panel, SectionTitle, Tag, fmtDT, num, useApi } from "./ui";

const STATUS_TONE: Record<string, "red" | "amber" | "green" | "gray" | "blue"> = {
  exceedance: "red", indicative_exceedance: "amber", indicative_hourly_above: "amber", compliant: "green",
  not_assessable: "gray", insufficient_data: "gray", no_reference: "blue", no_data: "gray",
};

export default function DomainView({ domain }: { domain: "air" | "water" }) {
  const { data, error, loading, reload } = useApi<any>(() => get(`/api/domain/${domain}`), [domain], 60000);
  const [sid, setSid] = useState<string>("");
  const [param, setParam] = useState<string>("");
  const [runMsg, setRunMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const st = data?.stations?.find((s: any) => s.station.id === sid) || data?.stations?.[0];
  useEffect(() => { if (st && !sid) setSid(st.station.id); }, [st, sid]);
  useEffect(() => { if (st) setParam((p) => (st.station.parameters.includes(p) ? p : st.station.parameters[0])); }, [st]);

  const series = useApi<any>(() => (st ? get(`/api/stations/${st.station.id}/series?hours=168`) : Promise.resolve(null)), [st?.station.id]);
  const f = st?.parameters.find((x: any) => x.parameter === param);
  const std = f?.primary?.standard;
  const flagged = useMemo(() => (series.data?.flags || []).filter((x: any) => x.parameter === param && x.flag === "suspect"), [series.data, param]);

  async function analyze() {
    if (!st) return;
    setBusy(true);
    setRunMsg(null);
    try {
      const r = await post("/api/pipeline/run", { station_id: st.station.id, trigger: "domain_page" });
      setRunMsg(`Run ${r.run_id}: ${r.overall_category || "Normal"} — risk index ${num(r.risk?.score)}. Status ${r.status}.`);
      reload();
    } catch (e: any) { setRunMsg(`Run failed: ${e.message}`); } finally { setBusy(false); }
  }

  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (loading && !data) return <Loading what={`${domain} stations`} />;
  return (
    <div>
      <div className="flex flex-wrap gap-2 mb-5" role="tablist">
        {data.stations.map((s: any) => (
          <button key={s.station.id} role="tab" aria-selected={s.station.id === st?.station.id} onClick={() => setSid(s.station.id)}
            className={`border px-3 py-2 text-left ${s.station.id === st?.station.id ? "border-brand bg-[#f4f7ff]" : "border-line bg-white hover:bg-panel"}`}>
            <div className="font-mono text-[12px]">{s.station.id}</div>
            <div className="text-[12px] text-muted">{s.station.name}</div>
            <div className="mt-1"><Chip value={s.stale ? "stale" : s.alert_category} /></div>
          </button>
        ))}
      </div>
      {st && (
        <>
          <Panel title={`${st.station.name} — ${st.station.location}`} right={<button className="btn-go btn-sm" onClick={analyze} disabled={busy}>{busy ? "Running agents…" : "Run agent analysis"}</button>}>
            <div className="text-[12.5px] text-muted">
              Zone: <b className="text-ink">{st.station.zone_category}</b>{st.station.water_class && <> · Designated class: <b className="text-ink">{st.station.water_class}</b></>}
              {" "}· Last measurement: <span className="font-mono text-ink">{fmtDT(st.last_measurement)}</span> · Open alerts: <span className="font-mono text-ink">{st.open_alerts}</span>
            </div>
            {runMsg && <div className="text-[12.5px] mt-2">{runMsg} <Link className="text-brand underline" to="/pipeline">View trace</Link></div>}
          </Panel>

          <SectionTitle><span className="mt-7 block">Parameter Assessment</span></SectionTitle>
          <div className="overflow-x-auto">
            <table className="grid-table min-w-[980px]">
              <thead><tr><th>Parameter</th><th>Measured value</th><th>Period value</th><th>Applicable reference limit</th><th>Calculated exceedance</th><th>Status</th><th>72-h trend</th></tr></thead>
              <tbody>
                {st.parameters.map((x: any) => {
                  const pr = x.primary;
                  return (
                    <tr key={x.parameter} className={`clickable ${x.parameter === param ? "bg-[#f4f7ff]" : ""}`} onClick={() => setParam(x.parameter)}>
                      <td className="font-medium">{x.label}</td>
                      <td className="font-mono">{x.measured ? `${num(x.measured.value, 2)} ${x.unit}` : "—"}<div className="text-[10.5px] text-muted">{x.measured && fmtDT(x.measured.timestamp)} · 1-h</div></td>
                      <td className="font-mono">{pr?.period_value != null ? `${num(pr.period_value, 2)}` : "—"}<div className="text-[10.5px] text-muted">{pr?.period_label}{pr?.coverage != null && ` · ${Math.round(pr.coverage * 100)}% data`}</div></td>
                      <td className="font-mono">{pr ? pr.limit_text : <span className="text-muted">none configured</span>}
                        {pr && <div className="text-[10.5px] text-muted font-sans">{pr.standard.averaging_period} · {pr.standard.id} {pr.standard.basis !== "regulatory" && <Tag tone="amber">{pr.standard.basis}</Tag>}</div>}</td>
                      <td className="font-mono">{pr?.difference != null ? <span className={pr.difference > 0 ? "text-risk font-semibold" : ""}>{pr.difference > 0 ? "+" : ""}{num(pr.difference, 2)} ({pr.percentage_difference > 0 ? "+" : ""}{num(pr.percentage_difference)}%)</span> : "—"}</td>
                      <td><Tag tone={STATUS_TONE[x.status] || "gray"}>{x.status}</Tag></td>
                      <td className="font-mono text-[11.5px]">{x.trend?.direction}{x.change_vs_baseline_pct != null && <div className="text-[10.5px] text-muted">{x.change_vs_baseline_pct > 0 ? "+" : ""}{num(x.change_vs_baseline_pct)}% vs baseline</div>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-muted mt-1.5">Difference = period value − limit; % = difference ÷ limit × 100. Computed deterministically; an exceedance is declared only when the averaging period matches the standard and data completeness ≥ 75 %.</p>

          <div className="grid grid-cols-1 xl:grid-cols-[1.35fr_1fr] gap-6 mt-7">
            <div>
              <SectionTitle right={<select className="field" value={param} onChange={(e) => setParam(e.target.value)} aria-label="Parameter">{st.station.parameters.map((p: string) => <option key={p} value={p}>{LABEL[p] || p}</option>)}</select>}>
                Historical Readings (7 days)
              </SectionTitle>
              <div className="border border-line bg-white p-3 h-[300px]">
                {series.loading && !series.data ? <Loading what="series" /> : (
                  <ResponsiveContainer>
                    <ComposedChart data={series.data?.points || []} margin={{ top: 8, right: 12, bottom: 4, left: -6 }}>
                      <CartesianGrid stroke="#eef1f4" />
                      <XAxis dataKey="timestamp" tickFormatter={(t) => new Date(t).toLocaleDateString([], { day: "2-digit", month: "short" })} fontSize={10} minTickGap={40} />
                      <YAxis fontSize={10} domain={["auto", "auto"]} />
                      <Tooltip labelFormatter={(t) => new Date(t).toLocaleString()} formatter={(v: any) => [`${v} ${f?.unit || ""}`, LABEL[param] || param]} />
                      {std?.limit_type === "max" && <ReferenceLine y={std.limit} stroke="#c0392b" strokeDasharray="4 3" label={{ value: `${std.limit} (${std.averaging_period})`, fontSize: 10, fill: "#c0392b", position: "insideTopLeft" }} />}
                      {std?.limit_type === "min" && <ReferenceLine y={std.limit} stroke="#c0392b" strokeDasharray="4 3" label={{ value: `min ${std.limit}`, fontSize: 10, fill: "#c0392b" }} />}
                      {std?.limit_type === "range" && <ReferenceLine y={std.min} stroke="#c0392b" strokeDasharray="4 3" />}
                      {std?.limit_type === "range" && <ReferenceLine y={std.max} stroke="#c0392b" strokeDasharray="4 3" />}
                      <Line dataKey={param} stroke="#1f5eff" dot={false} strokeWidth={1.5} connectNulls={false} isAnimationActive={false} />
                    </ComposedChart>
                  </ResponsiveContainer>
                )}
              </div>
              {flagged.length > 0 && <p className="text-[12px] text-[#6c3483] mt-2">{flagged.length} reading(s) flagged for sensor verification in this window (retained, excluded from compliance): {flagged.slice(0, 3).map((x: any) => `${fmtDT(x.timestamp)} = ${x.value}`).join("; ")}</p>}
            </div>
            <div>
              <SectionTitle>AI Interpretation</SectionTitle>
              <div className="space-y-2 max-h-[340px] overflow-y-auto">
                {st.parameters.map((x: any) => (
                  <div key={x.parameter} className={`border bg-white px-3 py-2 text-[12.5px] leading-relaxed ${x.parameter === param ? "border-brand" : "border-line"}`}>
                    <div className="font-semibold text-[12px] mb-0.5">{x.label}</div>{x.ai_interpretation}
                  </div>
                ))}
              </div>
              <p className="text-[11px] text-muted mt-2">Interpretation text is generated from the deterministic values on the left and reviewed by the Standards Reviewer Agent for unsupported claims.</p>
            </div>
          </div>
          <LatestAnomaly stationId={st.station.id} />
          {domain === "air" && f && <CrossStation stationId={st.station.id} parameter={param} />}
        </>
      )}
    </div>
  );
}

function CrossStation({ stationId, parameter }: { stationId: string; parameter: string }) {
  const { data, loading } = useApi<any>(() => get(`/api/cross-station?station_id=${stationId}&parameter=${parameter}`), [stationId, parameter]);
  return (
    <div className="mt-7">
      <SectionTitle>Station Comparison — {LABEL[parameter] || parameter}</SectionTitle>
      {loading && !data ? <Loading what="cross-station comparison" /> : data && (
        <>
          <Panel><div className="text-[13px]"><b>{data.classification?.replace("_", " ")}</b> — {data.summary}</div></Panel>
          <table className="grid-table mt-3">
            <thead><tr><th>Station</th><th>Distance</th><th>Recent mean</th><th>Reference / basis</th><th>Elevated</th></tr></thead>
            <tbody>{data.stations.map((s: any) => (
              <tr key={s.station_id}><td className="font-mono">{s.station_id}<div className="text-[11px] text-muted font-sans">{s.name}</div></td><td className="font-mono">{num(s.distance_km, 2)} km</td>
                <td className="font-mono">{num(s.recent_mean, 1)} ({s.window_h}-h)</td><td className="font-mono text-[11.5px]">{s.reference_limit ?? "—"} · {s.basis}</td>
                <td>{s.elevated ? <Tag tone="red">elevated</Tag> : <Tag tone="green">normal</Tag>}</td></tr>
            ))}</tbody>
          </table>
        </>
      )}
    </div>
  );
}

function LatestAnomaly({ stationId }: { stationId: string }) {
  const { data } = useApi<any>(async () => {
    const runs = await get(`/api/pipeline/runs?scope=${stationId}&limit=1`);
    return runs[0] ? get(`/api/pipeline/runs/${runs[0].id}`) : null;
  }, [stationId]);
  const an = data?.result?.anomaly;
  if (!data) return <div className="mt-7"><SectionTitle>Detected Anomalies</SectionTitle><div className="text-[13px] text-muted">No agent run yet for this station — use “Run agent analysis”.</div></div>;
  return (
    <div className="mt-7">
      <SectionTitle right={<span className="text-[11.5px] text-muted font-mono">{data.id} · {fmtDT(data.finished_at)}</span>}>Detected Anomalies (latest agent run)</SectionTitle>
      <div className="grid md:grid-cols-4 gap-3">
        {[["Latest anomaly score", num(an?.latest_score, 3)], ["Anomalous hours (24 h)", an?.anomalous_hours_24h ?? "—"],
          ["Unusual combination", an?.unusual_combination ? (an.combination_parameters || []).join(", ") : "no"],
          ["Sensor flags (48 h)", an?.sensor_flags?.length ?? 0]].map(([k, v]) => (
          <div key={k as string} className="bg-panel border border-line px-3 py-2"><div className="text-[11.5px] text-muted">{k}</div><div className="font-mono text-[15px] mt-0.5">{v as any}</div></div>
        ))}
      </div>
      {(an?.classified_changes || []).map((c: any) => (
        <div key={c.parameter} className="border border-line bg-white px-3 py-2 mt-3 text-[12.5px]">
          <b>{LABEL[c.parameter] || c.parameter}</b>: {num(c.previous_value, 2)} → {num(c.current_value, 2)} in 6 h ({num(c.change_pct)}%) — <Tag tone={c.classification === "valid_environmental_change" ? "red" : "amber"}>{c.classification}</Tag>
          <div className="text-muted mt-1">{c.classification_reason}</div>
        </div>
      ))}
      <p className="text-[12.5px] mt-3">{an?.interpretation}</p>
    </div>
  );
}
