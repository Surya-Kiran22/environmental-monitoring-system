import { useState } from "react";
import { Link } from "react-router-dom";
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { get, post } from "../api";
import { Chip, ErrorBox, Json, KV, Loading, Page, Panel, SectionTitle, STATION_COLORS, Tag, fmtTime, num, useApi } from "../components/ui";

const STATUS_TEXT: Record<string, string> = {
  INTERVENTION_REQUIRED: "ALERT_ACTIVE", ELEVATED_MONITORING: "MONITORING", NORMAL_OPERATION: "NOMINAL",
};

export default function Dashboard() {
  const { data, error, loading, reload } = useApi<any>(() => get("/api/dashboard"), [], 30000);
  const [running, setRunning] = useState(false);
  const [runErr, setRunErr] = useState<string | null>(null);

  async function run() {
    setRunning(true);
    setRunErr(null);
    try { await post("/api/pipeline/run-network", { trigger: "manual_override" }); await reload(); }
    catch (e: any) { setRunErr(e.message); }
    finally { setRunning(false); }
  }

  const risk = data?.last_run?.risk || {};
  const score: number | undefined = risk.overall_risk_score;
  const cat: string = risk.category || "NOT EVALUATED";
  const lifecycle: string = risk.lifecycle_status || "AWAITING_FIRST_RUN";
  const p = data?.parameters || {};
  const pmHigh = p.pm2_5 && p.pm2_5.value > 60;
  const ds = risk.domain_scores || {};
  const events: any[] = data?.last_run?.events || [];
  const airIds = data ? Object.keys(data.air_series?.[0] || {}).filter((k) => k !== "timestamp") : [];

  return (
    <Page title="Environmental Monitoring System" subtitle="Agentic AI Pipeline • Real-time Parameter Logging • Epsilon-Greedy Bandit">
      {error && <ErrorBox error={error} onRetry={reload} />}
      <Panel title="COMMAND PANEL: ENVIRONMENT PIPELINE">
        <div className="flex flex-wrap items-center gap-3">
          <button className="btn-go" onClick={run} disabled={running}>{running ? "Running 8 agents…" : "Run Environmental Analysis"}</button>
          <span className="btn-go pointer-events-none">Status: {data?.last_run ? (STATUS_TEXT[lifecycle] || lifecycle) : "IDLE"}</span>

          <span className="flex-1" />
          <span className={`${score !== undefined && score >= 50 ? "btn-risk" : "btn-go"} pointer-events-none`}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M12 3 2 21h20L12 3z" /><path d="M12 10v5M12 18h.01" /></svg>
            RISK_LEVEL: {cat}
          </span>
        </div>
        {runErr && <p className="text-[12.5px] text-risk mt-3">Analysis failed: {runErr}</p>}
      </Panel>

      <Panel className="mt-6">
        <div className="text-[13px] font-semibold mb-4">Overall Environmental Risk Score: {score !== undefined ? `${num(score)}%` : "—"}</div>
        <div className="relative h-[6px] bg-[#e4e8ee] rounded-full" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={score ?? 0} aria-label="Overall environmental risk score">
          <div className="absolute inset-y-0 left-0 bg-risk rounded-full" style={{ width: `${score ?? 0}%` }} />
          <div className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-[15px] h-[15px] rounded-full bg-brand border-2 border-white shadow" style={{ left: `${score ?? 0}%` }} />
        </div>
        <div className="flex justify-between font-mono text-[10px] text-muted mt-3">
          <span>0% (SAFE)</span><span>SELECTED: {cat}</span><span>100% (CRITICAL)</span>
        </div>
        <p className="text-[11px] text-muted mt-2">Monitoring-priority index from the Alert Agent (0.6 × worst domain + 0.4 × mean of AIR/WATER/NOISE). Not a regulatory index.</p>
      </Panel>

      {loading && !data && <Loading what="network state" />}
      {data && (
        <div className="grid grid-cols-1 xl:grid-cols-[1fr_1fr] gap-6 mt-7">
          <div>
            <SectionTitle>Environmental Parameters State</SectionTitle>
            <KV rows={[
              ["Location ID", data.network_id],
              ["Lifecycle Status", lifecycle],
              ["Air: PM2.5", p.pm2_5 ? <span>{num(p.pm2_5.value)} µg/m³ {pmHigh && <span className="text-risk font-semibold ml-2">▲ ELEVATED POLLUTION</span>} <span className="text-muted ml-2">({p.pm2_5.station_id})</span></span> : "—"],
              ["Air: PM10", p.pm10 ? `${num(p.pm10.value)} µg/m³ (${p.pm10.station_id})` : "—"],
              ["Water: pH", p.ph ? `${num(p.ph.value, 2)} (Score: ${num(ds.WATER ?? 0)}%)` : `(Score: ${num(ds.WATER ?? 0)}%)`],
              ["Water: Turbidity", p.turbidity ? `${num(p.turbidity.value)} NTU (${p.turbidity.station_id})` : "—"],
              ["Noise Level", p.noise ? `${num(p.noise.value)} dB(A) (Score: ${num(ds.NOISE ?? 0)}%)` : `dB (Score: ${num(ds.NOISE ?? 0)}%)`],
              ["Primary Risk Factor", risk.highest_factor || "—"],
              ["Last Evaluated", <span className="text-muted">{fmtTime(data.last_run?.finished_at)}</span>],
            ]} />

            <SectionTitle>
              <span className="mt-8 block">Air Quality Series</span>
            </SectionTitle>
            <div className="border border-line bg-white p-3 h-[300px]">
              <ResponsiveContainer>
                <LineChart data={data.air_series} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
                  <CartesianGrid stroke="#eef1f4" />
                  <XAxis dataKey="timestamp" tickFormatter={(t) => new Date(t).getHours() + ":00"} fontSize={10} minTickGap={30} />
                  <YAxis fontSize={10} unit="" />
                  <Tooltip labelFormatter={(t) => new Date(t).toLocaleString()} formatter={(v: any) => [`${v} µg/m³`]} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <ReferenceLine y={60} stroke="#c0392b" strokeDasharray="4 3" label={{ value: "60 µg/m³ (24-h ref., NAAQS)", fontSize: 10, fill: "#c0392b", position: "insideTopLeft" }} />
                  {airIds.map((id, i) => <Line key={id} dataKey={id} name={`${id} PM2.5`} stroke={STATION_COLORS[i]} dot={false} strokeWidth={1.6} connectNulls />)}
                </LineChart>
              </ResponsiveContainer>
            </div>
            <p className="text-[11px] text-muted mt-1.5">Hourly values; exceedances are only declared on the matching 24-h mean.</p>
          </div>

          <div>
            <SectionTitle right={data.last_run && <Link className="text-[12px] text-brand underline" to="/pipeline">Open execution trace</Link>}>AI Execution Timeline (Latest)</SectionTitle>
            <div className="border border-line bg-panel p-3 sm:p-4 max-h-[760px] overflow-y-auto space-y-4">
              {!events.length && <div className="text-[13px] text-muted p-3">No pipeline run yet. Use <b>Run Environmental Analysis</b> to execute the eight agents across the network.</div>}
              {events.map((e) => (
                <article key={e.version} className="bg-white border border-line shadow-[0_1px_2px_rgba(16,24,40,0.04)] px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] font-bold">{e.event}</span><Tag>v{e.version}</Tag>
                  </div>
                  <div className="text-[11px] text-muted mt-0.5 mb-2">{fmtTime(e.timestamp)}</div>
                  <Json data={e.payload} max={220} />
                </article>
              ))}
            </div>
          </div>
        </div>
      )}

      {data && (
        <>
          <SectionTitle><span className="mt-9 block">Network Status</span></SectionTitle>
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
            {[["Active stations", `${data.counts.active} / ${data.counts.stations}`, "/stations"], ["Active incidents", data.counts.open_incidents, "/incidents"],
              ["Critical alerts", data.counts.critical_alerts, "/alerts"], ["Open alerts", data.counts.open_alerts, "/alerts"],
              ["Sensor failures", data.counts.sensor_failures, "/live"], ["Open investigations", data.counts.open_investigations, "/investigations"]].map(([k, v, to]) => (
              <Link key={k as string} to={to as string} className="bg-panel border border-line px-4 py-3 hover:border-brand">
                <div className="text-[12px] text-muted">{k}</div>
                <div className="font-mono text-[20px] mt-1">{v}</div>
              </Link>
            ))}
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 mt-7">
            <div>
              <SectionTitle>Domain Status</SectionTitle>
              <table className="grid-table">
                <thead><tr><th>Domain</th><th>Worst status</th><th>Station</th><th>Stations</th><th>Stale</th></tr></thead>
                <tbody>
                  {(["air", "water", "noise"] as const).map((d) => {
                    const s = data.domain_status[d];
                    return <tr key={d}><td className="capitalize font-medium">{d} quality</td><td><Chip value={s.category} /></td><td className="font-mono">{s.station || "—"}</td><td className="font-mono">{s.stations}</td><td className="font-mono">{s.stale}</td></tr>;
                  })}
                </tbody>
              </table>
              <SectionTitle><span className="mt-6 block">Critical &amp; Priority Alerts</span></SectionTitle>
              <table className="grid-table">
                <thead><tr><th>Alert</th><th>Station</th><th>Category</th></tr></thead>
                <tbody>
                  {data.critical_alerts.length === 0 && <tr><td colSpan={3} className="text-muted">No open alerts.</td></tr>}
                  {data.critical_alerts.map((a: any) => (
                    <tr key={a.id}><td><Link className="text-brand hover:underline" to={`/alerts?id=${a.id}`}>{a.title}</Link></td><td className="font-mono">{a.station_id}</td><td><Chip value={a.category} /></td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div>
              <SectionTitle>PM2.5 Network Daily Trend (14 days)</SectionTitle>
              <div className="border border-line bg-white p-3 h-[220px]">
                <ResponsiveContainer>
                  <LineChart data={data.pm25_daily_trend} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
                    <CartesianGrid stroke="#eef1f4" />
                    <XAxis dataKey="date" fontSize={10} tickFormatter={(d) => d.slice(5)} />
                    <YAxis fontSize={10} />
                    <Tooltip formatter={(v: any) => [`${v} µg/m³`, "Daily mean PM2.5"]} />
                    <ReferenceLine y={60} stroke="#c0392b" strokeDasharray="4 3" />
                    <Line dataKey="pm2_5" stroke="#1f5eff" strokeWidth={2} dot={{ r: 2 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <SectionTitle><span className="mt-6 block">Monitoring Stations</span></SectionTitle>
              <table className="grid-table">
                <thead><tr><th>Station</th><th>Status</th><th>Risk</th><th>Last reading</th></tr></thead>
                <tbody>
                  {data.stations.map((s: any) => (
                    <tr key={s.id}><td><span className="font-mono">{s.id}</span><div className="text-[11px] text-muted">{s.name}</div></td>
                      <td><Chip value={s.stale ? "stale" : s.alert_category} /></td><td className="font-mono">{num(s.risk)}</td><td className="font-mono text-[11.5px]">{fmtTime(s.last_measurement)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </Page>
  );
}
