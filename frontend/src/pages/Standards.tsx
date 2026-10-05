import { useState } from "react";
import { get, post } from "../api";
import { ErrorBox, LABEL, Loading, Page, Panel, SectionTitle, Tag, useApi } from "../components/ui";

const limitText = (s: any) => (s.limit_type === "range" ? `${s.min}–${s.max}` : `${s.limit_type === "min" ? "≥" : "≤"} ${s.limit}`) + ` ${s.unit}`;

export default function Standards() {
  const { data, error, loading, reload } = useApi<any[]>(() => get("/api/standards"), []);
  const [filter, setFilter] = useState("");
  const [q, setQ] = useState("What is the night-time noise limit for residential areas?");
  const [ans, setAns] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  async function ask() {
    setBusy(true);
    try { setAns(await post("/api/standards/ask", { question: q })); } catch (e: any) { setAns({ answer: `Failed: ${e.message}`, citations: [] }); } finally { setBusy(false); }
  }
  const rows = (data || []).filter((s) => !filter || JSON.stringify(s).toLowerCase().includes(filter.toLowerCase()));

  return (
    <Page title="Standards Library" subtitle="Configurable environmental-standard knowledge base • structured limits + retrievable source documents (RAG)">
      <Panel title="ASK THE KNOWLEDGE BASE">
        <div className="flex flex-wrap gap-2">
          <input className="field flex-1 min-w-[260px]" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ask()} aria-label="Question" />
          <button className="btn-go" onClick={ask} disabled={busy || !q}>{busy ? "Searching…" : "Search standards"}</button>
        </div>
        <div className="flex flex-wrap gap-2 mt-2">
          {["24-hour PM2.5 limit", "data completeness rule for 24-hour averages", "dissolved oxygen Class C", "CO sensor spike verification", "source attribution language"].map((s) => (
            <button key={s} className="text-[11.5px] border border-line bg-white px-2 py-1 hover:border-brand" onClick={() => setQ(s)}>{s}</button>
          ))}
        </div>
        {ans && (
          <div className="mt-4">
            <div className="bg-white border border-line px-4 py-3 text-[13px] whitespace-pre-wrap">{ans.answer}</div>
            <div className="text-[11.5px] text-muted mt-1">Mode: {ans.mode} · top source: {ans.source_document} — {ans.section}</div>
            <div className="mt-3 space-y-2">
              {(ans.citations || []).map((c: any, i: number) => (
                <details key={i} className="border border-line bg-white px-3 py-2 text-[12px]">
                  <summary className="cursor-pointer">[{i + 1}] {c.title} — {c.section} <Tag>{c.doc}</Tag> <Tag tone="blue">score {c.score}</Tag></summary>
                  <div className="whitespace-pre-wrap mt-2 text-muted">{c.text}</div>
                </details>
              ))}
            </div>
          </div>
        )}
      </Panel>

      <SectionTitle right={<input className="field" placeholder="Filter (e.g. pm2_5, noise, Class C)" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter standards" />}>
        <span className="mt-7 block">Configured standards ({rows.length})</span>
      </SectionTitle>
      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <Loading what="standards" />}
      <div className="overflow-x-auto">
        <table className="grid-table min-w-[1100px]">
          <thead><tr><th>ID</th><th>Parameter</th><th>Limit</th><th>Averaging</th><th>Applies to</th><th>Standard / section</th><th>Version</th><th>Basis</th></tr></thead>
          <tbody>{rows.map((s) => (
            <tr key={s.id}>
              <td className="font-mono text-[11.5px]">{s.id}</td><td>{LABEL[s.parameter] || s.parameter}</td><td className="font-mono">{limitText(s)}</td>
              <td className="font-mono">{s.averaging_period}</td><td className="text-[11.5px]">{(s.zones || s.water_classes || []).join(", ")}</td>
              <td className="text-[11.5px]">{s.standard_name}<div className="text-muted">{s.section} · {s.source_doc}</div></td>
              <td className="text-[11.5px]">{s.version}</td>
              <td><Tag tone={s.basis === "regulatory" ? "green" : "amber"}>{s.basis}</Tag>{s.note && <div className="text-[10.5px] text-muted mt-1">{s.note}</div>}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <p className="text-[11.5px] text-muted mt-2">Sample values transcribed from public Indian notifications for this demonstration — verify against the official gazette before operational use. Add or edit records via <span className="font-mono">POST/PUT /api/standards</span>; the retrieval index rebuilds automatically.</p>
    </Page>
  );
}
