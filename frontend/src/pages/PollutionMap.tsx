import { useState } from "react";
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, Tooltip } from "react-leaflet";
import { get } from "../api";
import { CATEGORY_COLOR, Chip, ErrorBox, LABEL, Loading, Page, Panel, SectionTitle, Tag, TYPE_LABEL, fmtDT, num, useApi } from "../components/ui";

export default function PollutionMap() {
  const { data, error, loading, reload } = useApi<any>(() => get("/api/map"), [], 60000);
  const [showSources, setShowSources] = useState(true);
  const [focus, setFocus] = useState<string>("ENV-ST-004");
  const [param, setParam] = useState("pm2_5");
  const cs = useApi<any>(() => get(`/api/cross-station?station_id=${focus}&parameter=${param}`), [focus, param]);
  const focusSt = data?.stations.find((s: any) => s.id === focus);

  return (
    <Page title="Pollution Map" subtitle="Geospatial monitoring view • station status, latest readings, registered sources and cross-station analysis">
      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <Loading what="map" />}
      {data && (
        <div className="grid xl:grid-cols-[1.6fr_1fr] gap-6">
          <div>
            <div className="border border-line h-[560px]">
              <MapContainer center={[16.54, 80.62]} zoom={11} style={{ height: "100%", width: "100%" }} scrollWheelZoom>
                <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
                {focusSt && (cs.data?.stations || []).filter((s: any) => s.station_id !== focus).map((s: any) => (
                  <Polyline key={s.station_id} positions={[[focusSt.latitude, focusSt.longitude], [s.latitude, s.longitude]]}
                    pathOptions={{ color: s.elevated ? "#c0392b" : "#7f8c8d", weight: 1.5, dashArray: "5 5" }} />
                ))}
                {data.stations.map((s: any) => {
                  const st = s.stale ? "stale" : s.alert_category;
                  return (
                    <CircleMarker key={s.id} center={[s.latitude, s.longitude]} radius={s.id === focus ? 13 : 10}
                      pathOptions={{ color: "#fff", weight: 2, fillColor: CATEGORY_COLOR[st] || "#1e7e34", fillOpacity: 0.95 }}
                      eventHandlers={{ click: () => { setFocus(s.id); setParam(s.key_parameter); } }}>
                      <Tooltip direction="top">{s.id}</Tooltip>
                      <Popup>
                        <div className="text-[12px] min-w-[200px]">
                          <div className="font-bold">{s.id} — {s.name}</div>
                          <div>{TYPE_LABEL[s.monitoring_type]} · {s.zone_category}</div>
                          <div className="my-1"><Chip value={st} /></div>
                          <div>{LABEL[s.key_parameter]}: <b>{s.key_reading ? `${num(s.key_reading.value, 2)} ${s.key_reading.unit}` : "—"}</b></div>
                          <div>Latest measurement: {fmtDT(s.last_measurement)}</div>
                          <div>Open alerts: {s.open_alerts}</div>
                        </div>
                      </Popup>
                    </CircleMarker>
                  );
                })}
                {showSources && data.sources.map((s: any) => (
                  <CircleMarker key={s.id} center={[s.latitude, s.longitude]} radius={5} pathOptions={{ color: "#2c3e50", weight: 1, fillColor: "#fff", fillOpacity: 1 }}>
                    <Tooltip>{s.name} (registered source — not an attribution)</Tooltip>
                  </CircleMarker>
                ))}
              </MapContainer>
            </div>
            <div className="flex flex-wrap gap-3 items-center mt-3 text-[11.5px]">
              {["Critical Review Required", "Investigation Required", "Sensor Verification Required", "Elevated", "Normal"].map((c) => (
                <span key={c} className="inline-flex items-center gap-1.5"><span className="w-3 h-3 rounded-full inline-block" style={{ background: CATEGORY_COLOR[c] }} />{c}</span>
              ))}
              <label className="inline-flex items-center gap-1.5 ml-auto"><input type="checkbox" checked={showSources} onChange={(e) => setShowSources(e.target.checked)} />Registered sources</label>
            </div>
          </div>
          <div>
            <SectionTitle>Cross-Station Analysis</SectionTitle>
            <Panel>
              <div className="flex flex-wrap gap-2">
                <select className="field" value={focus} onChange={(e) => { setFocus(e.target.value); const s = data.stations.find((x: any) => x.id === e.target.value); if (s) setParam(s.key_parameter); }} aria-label="Station">
                  {data.stations.map((s: any) => <option key={s.id} value={s.id}>{s.id}</option>)}
                </select>
                <select className="field" value={param} onChange={(e) => setParam(e.target.value)} aria-label="Parameter">
                  {(focusSt?.parameters || []).map((p: string) => <option key={p} value={p}>{LABEL[p] || p}</option>)}
                </select>
              </div>
              {cs.data && (
                <div className="mt-3 text-[13px]">
                  <Tag tone={cs.data.classification === "distributed" ? "red" : cs.data.classification === "localized" ? "amber" : "gray"}>{cs.data.classification}</Tag>
                  <p className="mt-2">{cs.data.summary}</p>
                  <p className="text-[11.5px] text-muted mt-1">Comparison radius {cs.data.radius_km} km · {cs.data.elevated_count} of {cs.data.station_count} stations elevated.</p>
                </div>
              )}
            </Panel>
            <table className="grid-table mt-3">
              <thead><tr><th>Station</th><th>km</th><th>Recent mean</th><th>State</th></tr></thead>
              <tbody>{(cs.data?.stations || []).map((s: any) => (
                <tr key={s.station_id}><td className="font-mono">{s.station_id}</td><td className="font-mono">{num(s.distance_km, 1)}</td>
                  <td className="font-mono">{num(s.recent_mean, 1)}<div className="text-[10.5px] text-muted font-sans">{s.reference_limit != null ? `ref ${s.reference_limit}` : s.basis}</div></td>
                  <td>{s.elevated ? <Tag tone="red">elevated</Tag> : <Tag tone="green">normal</Tag>}</td></tr>
              ))}</tbody>
            </table>
            <p className="text-[11.5px] text-muted mt-3">Registered sources are shown for investigation planning only. A spatial pattern never identifies a source on its own; the Alert Agent labels candidates as “source requiring investigation”.</p>
          </div>
        </div>
      )}
    </Page>
  );
}
