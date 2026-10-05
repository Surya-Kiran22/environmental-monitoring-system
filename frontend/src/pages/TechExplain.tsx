import { get } from "../api";
import { KV, Page, Panel, SectionTitle, Tag, useApi } from "../components/ui";

const STAGES = ["Environmental sensors / CSV / REST / IoT", "Data Intake & Validation Agent", "Air · Water · Noise Agents", "Weather & Context Agent",
  "Anomaly & Trend Agent", "Standards RAG + Alert Agent", "Standards Reviewer Agent", "Human investigation", "Reporting (PDF)"];

const AGENTS = [
  ["1", "Environmental Data Intake & Validation", "Loads 30 days, normalises units, flags missing/duplicate/impossible/unrealistic/stale/flat-lined values (kept, never deleted) and emits the structured observation.", "validation.validate_long, db.load_measurements"],
  ["2", "Air Quality Analysis", "Retrieves applicable NAAQS records, builds matching averages, computes deterministic differences, trends, persistence and cross-station comparison.", "standards.applicable, compliance.evaluate, cross_station.compare"],
  ["3", "Water Quality Analysis", "Compares instantaneous readings with configured ranges / minimums, detects significant 6-h changes for classification.", "standards.applicable, compliance.evaluate, water.detect_changes"],
  ["4", "Noise Pollution Analysis", "Computes day (06–22) and night (22–06) Leq, compares with zone limits and counts repeated exceedances.", "compliance.noise_periods"],
  ["5", "Weather & Environmental Context", "Calls Open-Meteo (stored with source + timestamp), analyses wind, rain and humidity co-occurrence with associative language only.", "weather_api.current (Open-Meteo)"],
  ["6", "Pollution Anomaly & Trend Detection", "Isolation Forest + robust z-scores + Theil–Sen trend; classifies changes as environmental change, sensor anomaly or data-quality issue.", "ml.isolation_forest.fit_or_cache / score"],
  ["7", "Environmental Alert & Investigation", "Consolidates evidence into categorised, explained alerts; risk index; upwind source screening; epsilon-greedy recommendation.", "geo.source_investigation, risk.compute, bandit.recommend"],
  ["8", "Environmental Standards & Reviewer", "Re-verifies KB match, units, averaging period, recomputed difference, source retrievability; detects causal/legal/attribution claims; requests reassessment.", "rag.supporting_text"],
];

export default function TechExplain() {
  const health = useApi<any>(() => get("/api/health"), []);
  const graph = useApi<any>(() => get("/api/pipeline/graph"), []);
  return (
    <Page title="Technical Explanation" subtitle="Architecture, agent roles, agent-to-agent communication and methodology">
      <SectionTitle>System architecture</SectionTitle>
      <div className="flex flex-wrap items-center gap-1.5">
        {STAGES.map((s, i) => (
          <div key={s} className="flex items-center gap-1.5"><div className="border border-line bg-panel px-3 py-2 text-[12px]">{s}</div>{i < STAGES.length - 1 && <span className="text-muted">→</span>}</div>
        ))}
      </div>

      <div className="grid lg:grid-cols-2 gap-6 mt-7">
        <KV rows={[
          ["Orchestration", health.data ? `${health.data.orchestration} StateGraph` : "—"],
          ["LLM", health.data ? (health.data.llm ? `enabled (${health.data.llm_provider})` : "not configured — deterministic templates") : "—"],
          ["Graph nodes", graph.data ? graph.data.nodes.join(" → ") : "—"],
          ["Workflow state", "Typed state dict; trace/events use additive reducers; every run persisted in pipeline_runs"],
          ["Database", "SQLAlchemy — SQLite locally, PostgreSQL / TimescaleDB via DATABASE_URL"],
          ["Vector retrieval", "TF-IDF cosine index over KB sections + standard records (swappable for pgvector/Chroma)"],
        ]} />
        <Panel title="AGENT-TO-AGENT COMMUNICATION">
          <p className="text-[12.5px] leading-relaxed">Agents communicate through the shared LangGraph state, never by free text alone. Intake writes <span className="font-mono">observation</span>, <span className="font-mono">validation</span> and cleaned frames; domain agents write <span className="font-mono">findings</span> (each with measured value, reference, calculated exceedance and interpretation) and <span className="font-mono">cross_station</span>; Weather writes <span className="font-mono">weather_context</span>; Anomaly writes <span className="font-mono">anomaly</span> and classifies the water agent's <span className="font-mono">water_changes</span>; Alert writes a <span className="font-mono">draft</span>; the Reviewer writes <span className="font-mono">review</span> and, when it finds unsupported claims, <span className="font-mono">review_feedback</span>, which routes control back to the Alert agent (max one loop). Every agent appends to <span className="font-mono">trace</span> and <span className="font-mono">events</span>.</p>
        </Panel>
      </div>

      <SectionTitle><span className="mt-7 block">Agents</span></SectionTitle>
      <div className="overflow-x-auto"><table className="grid-table min-w-[900px]">
        <thead><tr><th>#</th><th>Agent</th><th>Responsibility</th><th>Tools</th></tr></thead>
        <tbody>{AGENTS.map((a) => <tr key={a[0]}><td className="font-mono">{a[0]}</td><td className="font-medium">{a[1]}</td><td className="text-[12px]">{a[2]}</td><td className="font-mono text-[11px]">{a[3]}</td></tr>)}</tbody>
      </table></div>

      <div className="grid lg:grid-cols-2 gap-6 mt-7">
        {[
          ["Regulatory comparison", "Limits come only from the configured knowledge base. The compliance tool builds the average that matches the standard's averaging period, requires ≥ 75 % data completeness, and reports Difference = value − limit and % = Difference ÷ limit × 100. Single hourly values are never compared with 24-h or annual limits; annual standards are 'not assessable' with 30 days of data."],
          ["Anomaly detection", "Isolation Forest per domain on robust-standardised readings, first differences, time encodings and weather; trained on data older than 48 h so a current event is never part of its own baseline. Evaluated against injected synthetic labels and compared with a robust z-score baseline."],
          ["Forecasting", "HistGradientBoostingRegressor on lags (1,2,3,6,24 h), rolling means, temperature, humidity, wind and time features; chronological 5-day hold-out; MAE/RMSE/MAPE vs. persistence; recursive 24-h backtests; ≈80 % interval from backtest residuals."],
          ["Explainability & safety", "Each alert separates measured value, applicable reference, calculated exceedance and AI interpretation, and states why it was generated. Weather is described as co-occurrence; sources are only 'potential contributing source' or 'source requiring investigation'. The reviewer blocks causal, legal or penalty language."],
        ].map(([t, b]) => <Panel key={t} title={t.toUpperCase()}><p className="text-[12.5px] leading-relaxed">{b}</p></Panel>)}
      </div>

      <SectionTitle><span className="mt-7 block">Alert categories</span></SectionTitle>
      <div className="flex flex-wrap gap-2 text-[12px]">
        {["Normal", "Observation", "Elevated", "Investigation Required", "Sensor Verification Required", "Critical Review Required"].map((c) => <Tag key={c}>{c}</Tag>)}
      </div>
      <p className="text-[12px] text-muted mt-2">Critical = valid exceedance ≥ 50 % above a regulatory limit (screening benchmarks are capped at Investigation Required). Normal and Observation stay in the run record; Elevated and above become alerts; Investigation-level and above open or update an incident.</p>
    </Page>
  );
}
