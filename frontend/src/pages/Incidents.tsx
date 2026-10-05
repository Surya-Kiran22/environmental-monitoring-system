import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { get } from "../api";
import { Chip, ErrorBox, LABEL, Loading, Page, Tag, fmtDT, useApi } from "../components/ui";

export default function Incidents() {
  const [status, setStatus] = useState("");
  const { data, error, loading, reload } = useApi<any[]>(() => get(`/api/incidents${status ? `?status=${status}` : ""}`), [status]);
  const nav = useNavigate();
  return (
    <Page title="Environmental Incidents" subtitle="Incidents created by the Alert Agent when configured conditions are met • one open incident per station and event type">
      <div className="flex flex-wrap gap-2 mb-5">
        {[["", "All"], ["open", "Open"], ["under_review,field_inspection_requested,investigating", "In investigation"], ["escalated", "Escalated"], ["closed", "Closed"]].map(([v, l]) => (
          <button key={l} className={status === v ? "btn-go btn-sm" : "btn-plain btn-sm"} onClick={() => setStatus(v)}>{l}</button>
        ))}
      </div>
      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <Loading what="incidents" />}
      {data && (
        <div className="overflow-x-auto">
          <table className="grid-table min-w-[1000px]">
            <thead><tr><th>Incident ID</th><th>Station</th><th>Parameter(s)</th><th>Title</th><th>Start</th><th>Measurement</th><th>Applicable reference</th><th>Priority</th><th>Status</th><th>Investigation</th></tr></thead>
            <tbody>
              {data.length === 0 && <tr><td colSpan={10} className="text-muted">No incidents. They appear after an analysis run finds Investigation-level conditions.</td></tr>}
              {data.map((i) => (
                <tr key={i.id} className="clickable" onClick={() => nav(`/investigations?id=${i.id}`)}>
                  <td className="font-mono">{i.id}</td><td className="font-mono">{i.station_id}</td>
                  <td>{String(i.parameter).split(",").map((p) => LABEL[p] || p).join(", ")}</td>
                  <td>{i.title}</td><td className="font-mono text-[11.5px]">{fmtDT(i.start_time)}</td>
                  <td className="font-mono text-[11.5px]">{i.measurement?.period_value != null ? `${i.measurement.period_value} ${i.measurement.unit}` : i.measurement?.latest_hourly ?? "—"}</td>
                  <td className="font-mono text-[11.5px]">{i.applicable_reference?.limit || "—"}{i.applicable_reference?.averaging_period && ` (${i.applicable_reference.averaging_period})`}</td>
                  <td><Chip value={i.priority} /></td><td><Tag tone={i.status === "closed" ? "green" : i.status === "escalated" ? "red" : "blue"}>{i.status}</Tag></td>
                  <td className="text-[11.5px]">{i.investigation_status}{i.assigned_to && <div className="text-muted">→ {i.assigned_to}</div>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Page>
  );
}
