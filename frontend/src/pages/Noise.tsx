import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { get } from "../api";
import { ErrorBox, KV, Loading, Page, Panel, SectionTitle, StationSelect, Tag, num, useApi } from "../components/ui";

function heatColor(v: number | null, lim: number) {
  if (v == null) return "#f1f3f6";
  const d = v - lim;
  if (d > 8) return "#c0392b";
  if (d > 3) return "#e67e22";
  if (d > 0) return "#f5c26b";
  if (d > -6) return "#cfe3f7";
  return "#e9f1fb";
}

export default function Noise() {
  const stations = useApi<any[]>(() => get("/api/stations"), []);
  const noiseStations = (stations.data || []).filter((s) => s.monitoring_type === "noise");
  const [sid, setSid] = useState("");
  useEffect(() => { if (!sid && noiseStations[0]) setSid(noiseStations[0].id); }, [noiseStations, sid]);
  const { data, error, loading, reload } = useApi<any>(() => (sid ? get(`/api/noise/${sid}`) : Promise.resolve(null)), [sid]);

  const byDate: Record<string, any> = {};
  (data?.periods || []).forEach((p: any) => { byDate[p.date] = { ...(byDate[p.date] || { date: p.date }), [p.period]: p.leq }; });
  const chart = Object.values(byDate);
  const dates = Array.from(new Set((data?.heatmap || []).map((h: any) => h.date))) as string[];
  const cell: Record<string, number | null> = {};
  (data?.heatmap || []).forEach((h: any) => { cell[`${h.date}|${h.hour}`] = h.value; });
  const nightLim = data?.limits?.night ?? 45, dayLim = data?.limits?.day ?? 55;

  return (
    <Page title="Noise Monitoring" subtitle="Noise Pollution Analysis Agent • day (06–22) and night (22–06) Leq against zone-specific configured limits">
      <div className="flex flex-wrap gap-3 items-center mb-5">
        <StationSelect stations={noiseStations} value={sid} onChange={setSid} />
      </div>
      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <Loading what="noise analysis" />}
      {data && (
        <>
          <div className="grid lg:grid-cols-[1fr_1.4fr] gap-6">
            <KV rows={[
              ["Station", `${data.station.id} — ${data.station.name}`], ["Location", data.station.location],
              ["Zone category", data.station.zone_category], ["Day limit (Leq)", `${dayLim} dB(A)`], ["Night limit (Leq)", `${nightLim} dB(A)`],
              ["Standard", data.standards?.[0]?.standard_name || "—"],
              ["Nights above limit (14 d)", <span className={data.repeated_night_periods >= 3 ? "text-risk font-semibold" : ""}>{data.repeated_night_periods}{data.repeated_night_periods >= 3 && " — repeated high night-time noise"}</span>],
            ]} />
            <Panel title="Day / night Leq by date">
              <div className="h-[250px] bg-white border border-line p-2">
                <ResponsiveContainer>
                  <BarChart data={chart} margin={{ top: 6, right: 8, left: -14, bottom: 0 }}>
                    <CartesianGrid stroke="#eef1f4" /><XAxis dataKey="date" fontSize={10} tickFormatter={(d) => d.slice(5)} /><YAxis fontSize={10} domain={[30, "auto"]} />
                    <Tooltip formatter={(v: any, n: any) => [`${v} dB(A)`, n]} /><Legend wrapperStyle={{ fontSize: 11 }} />
                    <ReferenceLine y={nightLim} stroke="#c0392b" strokeDasharray="4 3" label={{ value: `night ${nightLim}`, fontSize: 10, fill: "#c0392b", position: "insideTopLeft" }} />
                    <ReferenceLine y={dayLim} stroke="#1f5eff" strokeDasharray="4 3" label={{ value: `day ${dayLim}`, fontSize: 10, fill: "#1f5eff", position: "insideTopRight" }} />
                    <Bar dataKey="day" fill="#9db7f5" name="Day Leq" /><Bar dataKey="night" fill="#2c3e50" name="Night Leq" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Panel>
          </div>

          <SectionTitle><span className="mt-7 block">Hourly LAeq — date × hour</span></SectionTitle>
          <div className="overflow-x-auto border border-line bg-white p-3">
            <table className="text-[10px] font-mono border-separate" style={{ borderSpacing: 2 }}>
              <thead><tr><th className="pr-2 text-left font-normal text-muted">date \ hour</th>{Array.from({ length: 24 }, (_, h) => <th key={h} className={`w-7 font-normal ${h >= 22 || h < 6 ? "text-ink" : "text-muted"}`}>{h}</th>)}</tr></thead>
              <tbody>{dates.map((d) => (
                <tr key={d}><td className="pr-2 text-muted whitespace-nowrap">{d.slice(5)}</td>
                  {Array.from({ length: 24 }, (_, h) => {
                    const v = cell[`${d}|${h}`] ?? null;
                    const lim = h >= 22 || h < 6 ? nightLim : dayLim;
                    return <td key={h} title={`${d} ${h}:00 — ${v ?? "no data"} dB(A) (limit ${lim})`} className="w-7 h-5 text-center" style={{ background: heatColor(v, lim), color: v != null && v - lim > 3 ? "#fff" : "#4a5a6d" }}>{v != null ? Math.round(v) : ""}</td>;
                  })}</tr>
              ))}</tbody>
            </table>
            <p className="text-[11px] text-muted mt-2">Colour = hourly level relative to the applicable day/night limit (orange/red above). Night hours 22–06.</p>
          </div>

          <SectionTitle><span className="mt-7 block">Period assessment</span></SectionTitle>
          <table className="grid-table">
            <thead><tr><th>Date</th><th>Period</th><th>Leq</th><th>Max hourly</th><th>Hours</th><th>Limit</th><th>Result</th></tr></thead>
            <tbody>{[...(data.periods || [])].reverse().map((p: any) => (
              <tr key={p.date + p.period}><td className="font-mono">{p.date}</td><td>{p.period}</td><td className="font-mono">{num(p.leq)} dB(A)</td><td className="font-mono">{num(p.max_hourly)}</td>
                <td className="font-mono">{p.hours}{p.coverage < 0.75 && <span className="text-muted"> (incomplete)</span>}</td><td className="font-mono">{p.limit}</td>
                <td>{p.coverage < 0.75 ? <Tag>not assessed</Tag> : p.exceeded ? <Tag tone="red">above limit +{num(p.leq - p.limit)}</Tag> : <Tag tone="green">within</Tag>}</td></tr>
            ))}</tbody>
          </table>
        </>
      )}
    </Page>
  );
}
