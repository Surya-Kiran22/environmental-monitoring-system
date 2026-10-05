"""Render a structured report to PDF with ReportLab (Platypus)."""
from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BLUE = colors.HexColor("#1f5eff")
INK = colors.HexColor("#1b2430")
MUTED = colors.HexColor("#5b6b7f")
LINE = colors.HexColor("#d5dbe3")
RED = colors.HexColor("#c0392b")

FONT, BOLD = "Helvetica", "Helvetica-Bold"
_FD = __import__("pathlib").Path(__file__).parent / "fonts"
for path, name in ((str(_FD / "DejaVuSans.ttf"), "DejaVu"), (str(_FD / "DejaVuSans-Bold.ttf"), "DejaVu-Bold")):
    try:
        pdfmetrics.registerFont(TTFont(name, path))
        if name == "DejaVu":
            FONT = name
        else:
            BOLD = name
    except Exception:  # noqa: BLE001 - fall back to Helvetica (µ/³ still render via WinAnsi)
        pass

ss = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=ss["Title"], fontName=BOLD, fontSize=19, textColor=INK, alignment=TA_LEFT, spaceAfter=2)
H2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName=BOLD, fontSize=12.5, textColor=INK, spaceBefore=10, spaceAfter=4)
BODY = ParagraphStyle("b", parent=ss["BodyText"], fontName=FONT, fontSize=9, leading=12.5, textColor=INK)
SMALL = ParagraphStyle("s", parent=BODY, fontSize=7.8, leading=10, textColor=MUTED)
CELL = ParagraphStyle("c", parent=BODY, fontSize=7.8, leading=9.6)


def _p(t, st=BODY):
    return Paragraph(str(t if t is not None else "—").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), st)


def _table(head, rows, widths):
    data = [[_p(h, ParagraphStyle("th", parent=CELL, fontName=BOLD)) for h in head]] + [[_p(c, CELL) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f5f8")), ("GRID", (0, 0), (-1, -1), 0.5, LINE),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def render(rep: dict) -> bytes:
    c = rep["content"]
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"{c['title']} {rep['id']}", author="Env Intelligence")
    W = doc.width
    el = [_p("Env Intelligence", ParagraphStyle("brand", parent=BODY, textColor=BLUE, fontName=BOLD, fontSize=10)), _p(c["title"], H1),
          _p(f"Report {rep['id']} · Monitoring location: {c['monitoring_location']} · Period {c['period']['start'][:16].replace('T', ' ')} to "
             f"{c['period']['end'][:16].replace('T', ' ')}", SMALL)]
    review = "APPROVED by " + (rep.get("approved_by") or "") + " at " + (rep.get("approved_at") or "")[:16].replace("T", " ") if rep["status"] == "approved" else "DRAFT — pending human review and approval"
    el += [Spacer(1, 4), _table(["Human-review status"], [[review]], [W]), Spacer(1, 6)]
    el.append(_p("Monitoring stations", H2))
    el.append(_table(["Station", "Name", "Type", "Location"], [[s["id"], s["name"], s["type"].replace("_", " "), s["location"]] for s in c["stations"]],
                     [W * .17, W * .33, W * .15, W * .35]))
    for key, title in (("air", "Air-quality summary"), ("water", "Water-quality summary"), ("noise", "Noise summary")):
        el.append(_p(title, H2))
        if not c.get(key):
            el.append(_p("No analysed stations in scope.", SMALL))
        for s in c.get(key, []):
            el.append(_p(f"<b>{s['station_id']}</b> — {s['name']}: {s.get('category') or 'Normal'} (risk index {s.get('risk')})".replace("<b>", "").replace("</b>", "")))
            if s.get("alert_summary"):
                el.append(_p(s["alert_summary"], SMALL))
    el.append(_p("Weather conditions", H2))
    w = c.get("weather") or {}
    cur = w.get("current") or {}
    el.append(_p(f"Source: {cur.get('source')} · observed {cur.get('observed_at')} · {cur.get('temperature')} °C, {cur.get('humidity')} % RH, "
                 f"wind {cur.get('wind_speed')} m/s from {cur.get('wind_direction')}°, rain {cur.get('rainfall')} mm"))
    for o in w.get("observations") or []:
        el.append(_p("• " + o, SMALL))
    el.append(_p("Environmental-standard comparisons", H2))
    el.append(_p("Measured value, applicable reference and calculated difference are deterministic; averaging periods match the standard.", SMALL))
    el.append(_table(["Station", "Parameter", "Measured", "Reference", "Difference", "%", "Status"],
                     [[r["station_id"], r["parameter"], f"{r['measured']} ({r['period']})", f"{r['limit']} [{r['averaging']}]",
                       r["difference"], r["pct"], r["status"]] for r in c.get("comparisons", [])],
                     [W * .13, W * .12, W * .2, W * .2, W * .1, W * .08, W * .17]))
    el.append(_p("Detected anomalies", H2))
    for a in c.get("anomalies", []) or [{"station_id": "—", "items": ["No anomalies requiring investigation."]}]:
        el.append(_p(f"{a['station_id']}: " + " ".join(a["items"]), SMALL))
    m = c.get("anomaly_model_metrics") or {}
    if m:
        el.append(_table(["Domain", "Isolation Forest P / R / F1", "z-score baseline P / R / F1"],
                         [[d, f"{v['isolation_forest']['precision']} / {v['isolation_forest']['recall']} / {v['isolation_forest']['f1']}",
                           f"{v['robust_zscore_baseline']['precision']} / {v['robust_zscore_baseline']['recall']} / {v['robust_zscore_baseline']['f1']}"]
                          for d, v in m.items()], [W * .2, W * .4, W * .4]))
    el.append(_p("Pollution trends & forecast", H2))
    for s in c.get("air", []):
        el.append(_p(f"{s['station_id']}: " + ", ".join(f"{k} {v}" for k, v in (s.get("trends") or {}).items() if v), SMALL))
    fc = c.get("forecast")
    if fc:
        el.append(_p(f"{fc['parameter']} 24-h forecast for {fc['station_id']} ({fc['model']}): mean {fc['next_24h_mean']}, range {fc['next_24h_min']}–{fc['next_24h_max']} µg/m³. "
                     f"One-step MAE {fc['metrics_one_step'].get('mae')}, RMSE {fc['metrics_one_step'].get('rmse')}, MAPE {fc['metrics_one_step'].get('mape_pct')} % "
                     f"(persistence MAE {fc['persistence_baseline'].get('mae')}). 24-h backtest MAE {fc['backtest_24h'].get('model_mae')} vs persistence "
                     f"{fc['backtest_24h'].get('persistence_mae')}. Future weather: {fc['future_weather_source']}."))
    el.append(_p("Environmental incidents & investigation findings", H2))
    if not c.get("incidents"):
        el.append(_p("No incidents in scope.", SMALL))
    for i in c.get("incidents", []):
        block = [_p(f"{i['id']} · {i['station_id']} · {i['parameter']} · {i['priority']} · status {i['status']} ({i['investigation_status']})", CELL),
                 _p(i["title"], SMALL)]
        for a in i["actions"][-6:]:
            block.append(_p(f"  {str(a['timestamp'])[:16].replace('T', ' ')} — {a['action']} by {a['actor']}: {a['note'] or ''}", SMALL))
        el.append(KeepTogether(block + [Spacer(1, 3)]))
    el.append(_p("Recommended actions (for officer decision)", H2))
    for r in c.get("recommended_actions") or ["No open recommendations."]:
        el.append(_p("• " + r))
    el.append(_p("Source references", H2))
    el.append(_table(["Standard ID", "Standard", "Section", "Document", "Version", "Basis"],
                     [[s["id"], s["standard_name"], s["section"], s["source_doc"], s["version"], s["basis"]] for s in c.get("source_references", [])],
                     [W * .17, W * .2, W * .2, W * .15, W * .16, W * .12]))
    el += [Spacer(1, 8), _p(c["disclaimer"], SMALL)]

    def footer(cv, d):
        cv.saveState()
        cv.setFont(FONT, 7)
        cv.setFillColor(MUTED)
        cv.drawString(16 * mm, 9 * mm, f"Env Intelligence · {rep['id']} · {review[:60]}")
        cv.drawRightString(A4[0] - 16 * mm, 9 * mm, f"Page {d.page}")
        cv.restoreState()
    doc.build(el, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
