import { useEffect, useRef, useState } from "react";
import { get, post, upload } from "../api";
import { Chip, ErrorBox, LABEL, Loading, Page, Panel, SectionTitle, Tag, TYPE_LABEL, fmtDT, fmtTime, num, useApi } from "../components/ui";

const SCENARIOS: Record<string, string> = {
  normal: "Normal readings", exceedance: "Air pollutant exceedance", spike: "Unrealistic CO spike",
  turbidity_rise: "Turbidity rise", night_noise: "High noise", missing: "Missing value",
};

export default function LiveMonitoring() {
  const { data, error, loading, reload } = useApi<any[]>(() => get("/api/live"), [], 10000);
  const [sid, setSid] = useState("ENV-ST-004");
  const [scenario, setScenario] = useState("normal");
  const [analyze, setAnalyze] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [log, setLog] = useState<any[]>([]);
  const [upMsg, setUpMsg] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  async function tick() {
    try {
      const r = await post("/api/ingest/simulate", { station_id: sid, scenario, analyze });
      setLog((l) => [{ ...r, station_id: sid, at: new Date().toISOString() }, ...l].slice(0, 30));
      reload();
    } catch (e: any) {
      setLog((l) => [{ error: e.message, at: new Date().toISOString() }, ...l]);
      stop();
    }
  }
  function start() { setStreaming(true); tick(); timer.current = window.setInterval(tick, analyze ? 6000 : 3000); }
  function stop() { setStreaming(false); if (timer.current) window.clearInterval(timer.current); timer.current = null; }
  useEffect(() => () => stop(), []);
  useEffect(() => { if (streaming) { stop(); } }, [sid, scenario, analyze]); // restart required after changing settings

  async function onFile(f?: File) {
    if (!f) return;
    setUpMsg("Uploading…");
    try {
      const r = await upload("/api/ingest/file", f);
      setUpMsg(`${r.file}: ${r.measurements_parsed} measurements parsed, ${r.stored} stored, ${r.rejected.length} rejected, ${r.issues.length} validation issue(s).`);
      reload();
    } catch (e: any) { setUpMsg(`Upload failed: ${e.message}`); }
  }

  return (
    <Page title="Live Monitoring" subtitle="Environmental Data Intake & Validation Agent • current readings, data quality, IoT stream and file ingestion">
      {error && <ErrorBox error={error} onRetry={reload} />}
      <div className="grid xl:grid-cols-2 gap-6">
        <Panel title="SIMULATED IOT STREAM">
          <div className="flex flex-wrap gap-2 items-center">
            <select className="field" value={sid} onChange={(e) => setSid(e.target.value)} aria-label="Station">
              {(data || []).map((s) => <option key={s.id} value={s.id}>{s.id} ({TYPE_LABEL[s.monitoring_type]})</option>)}
            </select>
            <select className="field" value={scenario} onChange={(e) => setScenario(e.target.value)} aria-label="Scenario">
              {Object.entries(SCENARIOS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <label className="text-[12.5px] flex items-center gap-1.5"><input type="checkbox" checked={analyze} onChange={(e) => setAnalyze(e.target.checked)} /> Run agents on each reading</label>
          </div>
          <div className="flex gap-2 mt-3">
            {!streaming ? <button className="btn-go" onClick={start}>Start stream</button> : <button className="btn-risk" onClick={stop}>Stop stream</button>}
            <button className="btn-plain" onClick={tick} disabled={streaming}>Send one reading</button>
          </div>
          <p className="text-[11.5px] text-muted mt-2">Each message appends the next hourly reading for every sensor on the station; it is unit-normalised and validated against the previous 48 h before storage.</p>
        </Panel>
        <Panel title="FILE / REST INGESTION">
          <input type="file" accept=".csv,.xlsx,.xls" className="text-[12.5px]" onChange={(e) => onFile(e.target.files?.[0])} aria-label="Upload CSV or Excel" />
          {upMsg && <p className="text-[12.5px] mt-2">{upMsg}</p>}
          <p className="text-[11.5px] text-muted mt-2">Long format: <span className="font-mono">station_id,timestamp,parameter,value,unit</span>. Wide format: <span className="font-mono">station_id,timestamp,pm2_5 (ug/m3),no2 (ppb)…</span> — units in headers are converted (ppb, ppm, mS/cm, °F).</p>
          <p className="text-[11.5px] text-muted mt-1">REST: <span className="font-mono">POST /api/ingest/measurements</span> with a JSON list of measurements.</p>
        </Panel>
      </div>

      {log.length > 0 && (
        <>
          <SectionTitle><span className="mt-7 block">Stream log</span></SectionTitle>
          <div className="border border-line bg-white max-h-[260px] overflow-y-auto divide-y divide-line">
            {log.map((r, i) => (
              <div key={i} className="px-3 py-2 text-[12px] font-mono">
                {r.error ? <span className="text-risk">{fmtTime(r.at)} error: {r.error}</span> : <>
                  <span className="text-muted">{fmtTime(r.at)}</span> {r.station_id} @ {fmtDT(r.timestamp)} [{r.scenario}] —{" "}
                  {r.readings.map((x: any) => `${LABEL[x.parameter] || x.parameter} ${x.value ?? "∅"}`).join(", ")}
                  {r.issues?.length > 0 && <span className="text-[#6c3483]"> · issues: {Array.from(new Set(r.issues.map((x: any) => x.type))).join(", ")}</span>}
                  {r.pipeline && <span> · agents → <b>{r.pipeline.overall_category}</b></span>}
                </>}
              </div>
            ))}
          </div>
        </>
      )}

      <SectionTitle><span className="mt-7 block">Current readings</span></SectionTitle>
      {loading && !data && <Loading what="live readings" />}
      <div className="grid md:grid-cols-2 2xl:grid-cols-4 gap-4">
        {(data || []).map((s) => (
          <article key={s.id} className="border border-line bg-white">
            <header className="px-4 py-3 border-b border-line bg-panel flex items-start justify-between gap-2">
              <div><div className="font-mono text-[12.5px] font-semibold">{s.id}</div><div className="text-[12px] text-muted">{s.name}</div></div>
              <Chip value={s.stale ? "stale" : s.alert_category} />
            </header>
            <table className="w-full text-[12.5px]">
              <tbody>
                {Object.entries(s.latest || {}).map(([p, v]: any) => (
                  <tr key={p} className="border-b border-line last:border-0">
                    <td className="px-4 py-1.5">{LABEL[p] || p}</td>
                    <td className="px-4 py-1.5 font-mono text-right">{num(v.value, 2)} <span className="text-muted">{v.unit}</span> {v.quality_flag !== "valid" && <Tag tone="amber">{v.quality_flag}</Tag>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <footer className="px-4 py-2 text-[11px] text-muted border-t border-line">Last communication: <span className="font-mono">{fmtDT(s.last_measurement)}</span>{s.stale && <span className="text-[#6c3483]"> — stale (&gt;3 h)</span>}</footer>
          </article>
        ))}
      </div>
    </Page>
  );
}
