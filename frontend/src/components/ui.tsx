import { ReactNode, useCallback, useEffect, useState } from "react";

export const LABEL: Record<string, string> = {
  pm2_5: "PM2.5", pm10: "PM10", no2: "NO₂", so2: "SO₂", co: "CO", o3: "O₃", ph: "pH", dissolved_oxygen: "Dissolved oxygen",
  turbidity: "Turbidity", conductivity: "Conductivity", tds: "TDS", water_temperature: "Water temp.", noise_laeq: "Noise LAeq",
};
export const TYPE_LABEL: Record<string, string> = { air_quality: "Air quality", water_quality: "Water quality", noise: "Noise" };
export const STATION_COLORS = ["#1f5eff", "#c0392b", "#1e7e34", "#8e44ad", "#d35400", "#16a085", "#7f8c8d", "#2c3e50"];

export const CATEGORY_STYLE: Record<string, string> = {
  "Critical Review Required": "bg-[#c0392b] text-white border-[#c0392b]",
  "Investigation Required": "bg-[#fff1e6] text-[#a04000] border-[#f0c29c]",
  "Sensor Verification Required": "bg-[#f4ecf7] text-[#6c3483] border-[#d7bde2]",
  Elevated: "bg-[#fff8e1] text-[#8a6d00] border-[#f1d97a]",
  Observation: "bg-[#eaf2fb] text-[#1f4e8c] border-[#b9d3f0]",
  Normal: "bg-[#eaf6ec] text-[#1e7e34] border-[#b7dfc0]",
  stale: "bg-[#f4ecf7] text-[#6c3483] border-[#d7bde2]",
  offline: "bg-[#eceff3] text-[#5d7189] border-line",
};
export const CATEGORY_COLOR: Record<string, string> = {
  "Critical Review Required": "#c0392b", "Investigation Required": "#d35400", "Sensor Verification Required": "#7d3c98",
  Elevated: "#b7950b", Observation: "#2e86c1", Normal: "#1e7e34", stale: "#7d3c98", offline: "#7f8c8d",
};

export function Page({ title, subtitle, actions, children }: { title: string; subtitle?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <div className="bg-white border border-line px-5 sm:px-9 py-8 min-h-[calc(100vh-4rem)]">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-[26px] leading-tight font-bold text-ink">{title}</h1>
          {subtitle && <p className="text-[13px] text-muted mt-1.5">{subtitle}</p>}
        </div>
        {actions}
      </div>
      <hr className="border-line mt-5 mb-6" />
      {children}
    </div>
  );
}

export function Panel({ title, children, className = "", right }: { title?: ReactNode; children: ReactNode; className?: string; right?: ReactNode }) {
  return (
    <section className={`bg-panel border border-line p-4 sm:p-5 ${className}`}>
      {(title || right) && (
        <div className="flex items-center justify-between gap-3 mb-3">
          {title && <div className="label">{title}</div>}
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-end justify-between gap-3 mb-3 mt-1">
      <h2 className="text-[16px] font-bold text-ink">{children}</h2>
      {right}
    </div>
  );
}

export function KV({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <table className="kv w-full bg-white border border-line">
      <tbody>{rows.map(([k, v], i) => <tr key={i}><td>{k}</td><td>{v}</td></tr>)}</tbody>
    </table>
  );
}

export function Chip({ value, className = "" }: { value?: string | null; className?: string }) {
  const v = value || "Normal";
  return <span className={`inline-block border px-2 py-[2px] text-[11.5px] font-semibold whitespace-nowrap rounded-[2px] ${CATEGORY_STYLE[v] || "bg-white text-ink border-line"} ${className}`}>{v}</span>;
}

export function Tag({ children, tone = "gray" }: { children: ReactNode; tone?: "gray" | "red" | "green" | "blue" | "amber" }) {
  const t = { gray: "bg-[#eceff3] text-[#4a5a6d]", red: "bg-[#fbeaea] text-[#a52a1f]", green: "bg-[#eaf6ec] text-[#1e7e34]",
    blue: "bg-[#eaf0ff] text-[#1f4fcc]", amber: "bg-[#fff6dc] text-[#86660a]" }[tone];
  return <span className={`inline-block font-mono text-[10.5px] px-1.5 py-[1px] rounded-[2px] ${t}`}>{children}</span>;
}

export function Json({ data, max = 260 }: { data: unknown; max?: number }) {
  return (
    <pre className="bg-[#f6f7f9] border-l-2 border-line font-mono text-[11px] leading-[1.55] text-[#2b3441] px-4 py-3 overflow-auto" style={{ maxHeight: max }}>
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="border border-dashed border-line bg-white px-4 py-6 text-[13px] text-muted">{children}</div>;
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="border border-[#f0b8b2] bg-[#fdf1f0] px-4 py-3 text-[13px] text-[#8e2a1f] flex items-center justify-between gap-3">
      <span>Could not reach the API: {error}. Check that the backend is running and VITE_API_URL points to it.</span>
      {onRetry && <button className="btn-plain btn-sm" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function Loading({ what = "data" }: { what?: string }) {
  return <div className="text-[13px] text-muted py-6">Loading {what}…</div>;
}

export function useApi<T>(fn: () => Promise<T>, deps: unknown[] = [], intervalMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(() => {
    setLoading(true);
    return fn().then((d) => { setData(d); setError(null); }).catch((e) => setError(String(e.message || e))).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    load();
    if (!intervalMs) return;
    const t = setInterval(load, intervalMs);
    return () => clearInterval(t);
  }, [load, intervalMs]);
  return { data, error, loading, reload: load, setData };
}

export const fmtTime = (s?: string | null) => (s ? new Date(s).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }).toLowerCase() : "—");
export const fmtDT = (s?: string | null) => (s ? new Date(s).toLocaleString([], { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—");
export const num = (v: unknown, d = 1) => (v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(d).replace(/\.0+$/, ""));

export function StationSelect({ stations, value, onChange, filter }: { stations: any[]; value: string; onChange: (v: string) => void; filter?: (s: any) => boolean }) {
  return (
    <select className="field min-w-[260px]" value={value} onChange={(e) => onChange(e.target.value)} aria-label="Station">
      {stations.filter(filter || (() => true)).map((s) => <option key={s.id} value={s.id}>{s.id} — {s.name}</option>)}
    </select>
  );
}
