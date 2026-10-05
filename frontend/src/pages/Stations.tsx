import { useState } from "react";
import { get, post, put } from "../api";
import { Chip, ErrorBox, LABEL, Loading, Page, Panel, SectionTitle, TYPE_LABEL, fmtDT, useApi } from "../components/ui";

const PARAMS: Record<string, string[]> = {
  air_quality: ["pm2_5", "pm10", "no2", "so2", "co", "o3"],
  water_quality: ["ph", "dissolved_oxygen", "turbidity", "conductivity", "tds", "water_temperature"],
  noise: ["noise_laeq"],
};
const blank = { id: "", name: "", monitoring_type: "air_quality", location: "", latitude: 16.51, longitude: 80.64, zone_category: "residential", water_class: "", parameters: PARAMS.air_quality };

export default function Stations() {
  const { data, error, loading, reload } = useApi<any[]>(() => get("/api/stations"), []);
  const [form, setForm] = useState<any>(blank);
  const [msg, setMsg] = useState<string | null>(null);

  async function create() {
    setMsg(null);
    try {
      await post("/api/stations", { ...form, water_class: form.water_class || null, latitude: Number(form.latitude), longitude: Number(form.longitude) });
      setMsg(`Station ${form.id} created.`);
      setForm(blank);
      reload();
    } catch (e: any) { setMsg(`Could not create station: ${e.message}`); }
  }
  async function setStatus(id: string, operational_status: string) {
    await put(`/api/stations/${id}`, { operational_status });
    reload();
  }
  const upd = (k: string, v: any) => setForm((f: any) => ({ ...f, [k]: v, ...(k === "monitoring_type" ? { parameters: PARAMS[v], zone_category: v === "water_quality" ? "water_body" : "residential" } : {}) }));

  return (
    <Page title="Monitoring Stations" subtitle="Station registry • sensors, measurement parameters, operational status and last communication">
      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <Loading what="stations" />}
      {data && (
        <div className="overflow-x-auto">
          <table className="grid-table min-w-[1050px]">
            <thead><tr><th>Station ID</th><th>Name / location</th><th>Type</th><th>Zone</th><th>Sensors</th><th>Parameters</th><th>Operational</th><th>Last communication</th><th>Alert status</th></tr></thead>
            <tbody>{data.map((s) => (
              <tr key={s.id}>
                <td className="font-mono">{s.id}</td>
                <td>{s.name}<div className="text-[11px] text-muted">{s.location} · {s.latitude?.toFixed(4)}, {s.longitude?.toFixed(4)}</div></td>
                <td>{TYPE_LABEL[s.monitoring_type]}</td>
                <td>{s.zone_category}{s.water_class && ` (Class ${s.water_class})`}</td>
                <td className="font-mono text-[11px]">{(s.sensors || []).map((x: any) => x.sensor_id).join(", ") || "—"}</td>
                <td className="text-[11.5px]">{s.parameters.map((p: string) => LABEL[p] || p).join(", ")}</td>
                <td>
                  <select className="field py-1" value={s.operational_status} onChange={(e) => setStatus(s.id, e.target.value)} aria-label={`Operational status of ${s.id}`}>
                    {["active", "maintenance", "offline"].map((o) => <option key={o}>{o}</option>)}
                  </select>
                </td>
                <td className="font-mono text-[11.5px]">{fmtDT(s.last_measurement)}</td>
                <td><Chip value={s.stale ? "stale" : s.alert_category} /></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}

      <SectionTitle><span className="mt-8 block">Add monitoring station</span></SectionTitle>
      <Panel>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 text-[12.5px]">
          {[["id", "Station ID"], ["name", "Station name"], ["location", "General location"]].map(([k, l]) => (
            <label key={k} className="flex flex-col gap-1">{l}<input className="field" value={form[k]} onChange={(e) => upd(k, e.target.value)} /></label>
          ))}
          <label className="flex flex-col gap-1">Monitoring type
            <select className="field" value={form.monitoring_type} onChange={(e) => upd("monitoring_type", e.target.value)}>
              {Object.entries(TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select></label>
          <label className="flex flex-col gap-1">Latitude<input className="field" type="number" step="0.0001" value={form.latitude} onChange={(e) => upd("latitude", e.target.value)} /></label>
          <label className="flex flex-col gap-1">Longitude<input className="field" type="number" step="0.0001" value={form.longitude} onChange={(e) => upd("longitude", e.target.value)} /></label>
          <label className="flex flex-col gap-1">Zone category
            <select className="field" value={form.zone_category} onChange={(e) => upd("zone_category", e.target.value)}>
              {["industrial", "commercial", "residential", "silence", "rural", "water_body"].map((z) => <option key={z}>{z}</option>)}
            </select></label>
          {form.monitoring_type === "water_quality" && (
            <label className="flex flex-col gap-1">Designated water class
              <select className="field" value={form.water_class} onChange={(e) => upd("water_class", e.target.value)}>
                <option value="">—</option>{["A", "B", "C", "D", "E"].map((c) => <option key={c}>{c}</option>)}
              </select></label>
          )}
        </div>
        <div className="mt-3 text-[12.5px]">Parameters:{" "}
          {PARAMS[form.monitoring_type].map((p) => (
            <label key={p} className="inline-flex items-center gap-1 mr-3">
              <input type="checkbox" checked={form.parameters.includes(p)} onChange={(e) => upd("parameters", e.target.checked ? [...form.parameters, p] : form.parameters.filter((x: string) => x !== p))} />{LABEL[p]}
            </label>
          ))}
        </div>
        <button className="btn-go mt-4" onClick={create} disabled={!form.id || !form.name}>Create station</button>
        {msg && <p className="text-[12.5px] mt-2">{msg}</p>}
      </Panel>
    </Page>
  );
}
