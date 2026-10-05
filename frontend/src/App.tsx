import { useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import LiveMonitoring from "./pages/LiveMonitoring";
import AirQuality from "./pages/AirQuality";
import WaterQuality from "./pages/WaterQuality";
import Noise from "./pages/Noise";
import Stations from "./pages/Stations";
import PollutionMap from "./pages/PollutionMap";
import Trends from "./pages/Trends";
import Alerts from "./pages/Alerts";
import Incidents from "./pages/Incidents";
import Investigations from "./pages/Investigations";
import Standards from "./pages/Standards";
import Reports from "./pages/Reports";
import PipelineDemo from "./pages/PipelineDemo";
import TechExplain from "./pages/TechExplain";

const NAV = [
  ["/", "Overview (Dashboard)"], ["/live", "Live Monitoring"], ["/air", "Air Quality"], ["/water", "Water Quality"], ["/noise", "Noise"],
  ["/stations", "Stations"], ["/map", "Pollution Map"], ["/trends", "Trends & Forecasts"], ["/alerts", "Alerts"], ["/incidents", "Incidents"],
  ["/investigations", "Investigations"], ["/standards", "Standards"], ["/reports", "Reports"], ["/pipeline", "Pipeline Demo"], ["/tech", "Technical Explain"],
];

export default function App() {
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  return (
    <div className="min-h-full flex">
      <aside className={`fixed inset-y-0 left-0 z-[1200] w-[268px] bg-[#fafafa] border-r border-line flex flex-col transition-transform lg:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}>
        <div className="bg-brand text-white h-[68px] flex items-center px-5 shrink-0">
          <span className="text-[22px] font-bold tracking-[-0.01em]">Env Intelligence</span>
        </div>
        <nav className="flex-1 overflow-y-auto py-4 px-4" aria-label="Main">
          {NAV.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"} onClick={() => setOpen(false)}
              className={({ isActive }) => `block px-2 py-[11px] text-[15px] rounded-[3px] mb-[2px] ${isActive ? "bg-[#eceef1] text-ink font-medium" : "text-[#2a2f36] hover:bg-[#f1f2f4]"}`}>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="px-6 py-3 text-[11px] text-muted border-t border-line">Decision-support only · no legal determinations</div>
      </aside>
      {open && <div className="fixed inset-0 bg-black/20 z-[1100] lg:hidden" onClick={() => setOpen(false)} />}
      <main className="flex-1 lg:ml-[268px] min-w-0">
        <div className="lg:hidden flex items-center gap-3 bg-brand text-white px-4 h-14">
          <button className="border border-white/50 px-2 py-1 text-sm" onClick={() => setOpen(true)} aria-label="Open menu">Menu</button>
          <span className="font-bold">Env Intelligence</span>
        </div>
        <div className="p-3 sm:p-8 max-w-[1500px] mx-auto" key={loc.pathname}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/live" element={<LiveMonitoring />} />
            <Route path="/air" element={<AirQuality />} />
            <Route path="/water" element={<WaterQuality />} />
            <Route path="/noise" element={<Noise />} />
            <Route path="/stations" element={<Stations />} />
            <Route path="/map" element={<PollutionMap />} />
            <Route path="/trends" element={<Trends />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/incidents" element={<Incidents />} />
            <Route path="/investigations" element={<Investigations />} />
            <Route path="/standards" element={<Standards />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/pipeline" element={<PipelineDemo />} />
            <Route path="/tech" element={<TechExplain />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
