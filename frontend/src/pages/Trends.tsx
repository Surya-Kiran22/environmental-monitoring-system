import { useEffect, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { get } from "../api";
import { ErrorBox, KV, LABEL, Loading, Page, Panel, SectionTitle, StationSelect, num, useApi } from "../components/ui";

export default function Trends() {
  const stations = useApi<any[]>(() => get("/api/stations"), []);
  const [sid, setSid] = useState("ENV-ST-004");
  const st = stations.data?.find((s) => s.id === sid);
  const [param, setParam] = useState("pm2_5");
  const [horizon, setHorizon] = useState(24);
  useEffect(() => { if (st && !st.parameters.includes(param)) setParam(st.parameters[0]); }, [st]);
  const fc = useApi<any>(() => get(`/api/forecast/${sid}?parameter=${param}&horizon=${horizon}`), [sid, param, horizon]);
  const metrics = useApi<any>(() => get("/api/models/anomaly"), []);

  const chart = [
    ...(fc.data?.history || []).map((h: any) => ({ t: h.timestamp, actual: h.value })),
    ...(fc.data?.forecast || []).map((f: any) => ({ t: f.timestamp, forecast: f.value, band: [f.lower, f.upper] })),
  ];
  const m = fc.data?.metrics_one_step || {}, b = fc.data?.persistence_baseline_one_step || {}, bt = fc.data?.backtest_24h || {};

  return (
    <Page title="Trends & Forecasting" subtitle="Historical values, gradient-boosted forecasts with evaluation metrics, and anomaly-model evaluation">
      <div className="flex flex-wrap gap-2 mb-5">
        <StationSelect stations={stations.data || []} value={sid} onChange={setSid} />
        <select className="field" value={param} onChange={(e) => setParam(e.target.value)} aria-label="Parameter">
          {(st?.parameters || []).map((p: string) => <option key={p} value={p}>{LABEL[p] || p}</option>)}
        </select>
        <select className="field" value={horizon} onChange={(e) => setHorizon(Number(e.target.value))} aria-label="Horizon">
          {[12, 24, 48].map((h) => <option key={h} value={h}>{h} h ahead</option>)}
        </select>
      </div>
      {fc.error && <ErrorBox error={fc.error} onRetry={fc.reload} />}
      {fc.loading && !fc.data && <Loading what="model training and forecast" />}
      {fc.data?.error && <div className="text-[13px] text-risk">{fc.data.error}</div>}
      {fc.data && !fc.data.error && (
        <>
          <SectionTitle>{LABEL[param]} — last 72 h and {horizon}-h forecast</SectionTitle>
          <div className="border border-line bg-white p-3 h-[340px]">
            <ResponsiveContainer>
              <ComposedChart data={chart} margin={{ top: 8, right: 12, left: -6, bottom: 4 }}>
                <CartesianGrid stroke="#eef1f4" />
                <XAxis dataKey="t" fontSize={10} minTickGap={40} tickFormatter={(t) => new Date(t).toLocaleString([], { day: "2-digit", hour: "2-digit" })} />
                <YAxis fontSize={10} />
                <Tooltip labelFormatter={(t) => new Date(t).toLocaleString()} formatter={(v: any, n: any) => [Array.isArray(v) ? `${v[0]}–${v[1]}` : v, n]} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Area dataKey="band" name="≈80% interval" fill="#c9d8ff" stroke="none" isAnimationActive={false} />
                <Line dataKey="actual" name="Measured (valid)" stroke="#1b2430" dot={false} strokeWidth={1.5} isAnimationActive={false} />
                <Line dataKey="forecast" name="Forecast" stroke="#1f5eff" strokeDasharray="5 3" dot={false} strokeWidth={2} isAnimationActive={false} />
                {param === "pm2_5" && <ReferenceLine y={60} stroke="#c0392b" strokeDasharray="4 3" label={{ value: "60 (24-h ref.)", fontSize: 10, fill: "#c0392b", position: "insideTopLeft" }} />}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <p className="text-[11.5px] text-muted mt-1.5">Future weather inputs: {fc.data.future_weather_source}. Forecasts are planning aids, not compliance findings.</p>

          <div className="grid lg:grid-cols-2 gap-6 mt-7">
            <div>
              <SectionTitle>Forecast model evaluation</SectionTitle>
              <table className="grid-table">
                <thead><tr><th>Evaluation</th><th>MAE</th><th>RMSE</th><th>MAPE</th></tr></thead>
                <tbody>
                  <tr><td>Model — one-step (test, n={m.n})</td><td className="font-mono">{num(m.mae, 2)}</td><td className="font-mono">{num(m.rmse, 2)}</td><td className="font-mono">{num(m.mape_pct, 1)}%</td></tr>
                  <tr><td>Persistence baseline (t−24 h)</td><td className="font-mono">{num(b.mae, 2)}</td><td className="font-mono">{num(b.rmse, 2)}</td><td className="font-mono">{num(b.mape_pct, 1)}%</td></tr>
                  <tr><td>Model — recursive 24-h backtest ({bt.windows} windows)</td><td className="font-mono">{num(bt.model_mae, 2)}</td><td className="font-mono">{num(bt.model_rmse, 2)}</td><td className="font-mono">{num(bt.model_mape_pct, 1)}%</td></tr>
                  <tr><td>Persistence — 24-h backtest</td><td className="font-mono">{num(bt.persistence_mae, 2)}</td><td className="font-mono">{num(bt.persistence_rmse, 2)}</td><td className="font-mono">—</td></tr>
                </tbody>
              </table>
              <div className="mt-3"><KV rows={[["Model", fc.data.model], ["Split", fc.data.split], ["Train / test rows", `${fc.data.train_rows} / ${fc.data.test_rows}`],
                ["Features", <span className="text-[11px]">{fc.data.features.join(", ")}</span>], ["Interval", fc.data.interval]]} /></div>
            </div>
            <div>
              <SectionTitle>Anomaly model evaluation</SectionTitle>
              {metrics.data && (
                <>
                  <table className="grid-table">
                    <thead><tr><th>Domain</th><th>Isolation Forest P / R / F1</th><th>Robust z-score P / R / F1</th><th>Events</th></tr></thead>
                    <tbody>{Object.entries(metrics.data.domains).map(([d, v]: any) => (
                      <tr key={d}><td className="capitalize">{d}</td>
                        <td className="font-mono">{v.isolation_forest.precision} / {v.isolation_forest.recall} / <b>{v.isolation_forest.f1}</b></td>
                        <td className="font-mono">{v.robust_zscore_baseline.precision} / {v.robust_zscore_baseline.recall} / <b>{v.robust_zscore_baseline.f1}</b></td>
                        <td className="font-mono">{v.labelled_events}/{v.test_rows}</td></tr>
                    ))}</tbody>
                  </table>
                  <Panel className="mt-3"><p className="text-[12.5px]">{metrics.data.algorithm}. {metrics.data.split}. Labels come from injected synthetic events (pollution episode, sensor spike, water deterioration, night noise). The z-score baseline is stronger for the single-parameter water deterioration; Isolation Forest is stronger for multi-pollutant air events and day/night noise patterns, so the agent uses both.</p></Panel>
                </>
              )}
            </div>
          </div>
        </>
      )}
    </Page>
  );
}
