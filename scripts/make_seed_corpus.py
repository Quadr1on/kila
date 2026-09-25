"""Generate KILA's SYNTHETIC demo corpus into seed/. Everything here is fictional.

The organisation, people, equipment tags and numbers are invented ("Konkan Coastal Refinery",
KCR). No real MRPL documents are used or imitated.

    uv run --directory services/api python ../../scripts/make_seed_corpus.py

Outputs
  seed/kb/*.pdf                    SOPs and internal standards (text PDFs)       -> kb bucket
  seed/reports/*_scan.pdf          inspection reports as noisy image-only scans  -> uploads
  seed/reports/_truth/*.txt        exact text of each report (OCR ground truth)
  seed/sheets/*.xlsx               CML thickness log, PSV register
  seed/code/corrosion_calc/        a small Python package
Deterministic: fixed random seed, so the files are identical on every run.
"""

from __future__ import annotations

import io
import random
from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "seed"
ORG = "Konkan Coastal Refinery Ltd (fictional)"
FOOTER = "KCR internal · SYNTHETIC DEMO DOCUMENT · not a real procedure"

styles = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=15, spaceAfter=6)
H2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, spaceBefore=8, spaceAfter=4)
BODY = ParagraphStyle("b", parent=styles["BodyText"], fontSize=10, leading=13.5)
SMALL = ParagraphStyle("s", parent=BODY, fontSize=8, textColor=colors.grey)


# ------------------------------------------------------------------ knowledge base (SOPs/standards)

KB_DOCS: list[dict] = [
    {
        "id": "SOP-MNT-010", "title": "Pressure Safety Valve Testing and Recertification", "rev": "C",
        "sections": [
            ("1. Purpose", "This procedure defines how pressure safety valves (PSVs) at KCR are removed, bench tested, "
             "overhauled and recertified. A PSV protects equipment from overpressure by relieving fluid when the "
             "inlet pressure reaches the set pressure."),
            ("2. Test interval", "Every PSV shall be bench tested at least once every 24 months. PSVs in fouling, "
             "corrosive or polymerising service (for example crude overhead, sour water and amine regenerator "
             "service) shall be tested every 12 months. The interval may be extended to 36 months only with a "
             "documented risk assessment approved by the Inspection Head."),
            ("3. Acceptance criteria", "The measured popping pressure shall be within plus or minus 3 percent of the "
             "stamped set pressure for set pressures above 5 bar(g), and within plus or minus 0.15 bar for set "
             "pressures of 5 bar(g) or less. Seat leakage shall not exceed the limits in STD-ENG-120. A valve that "
             "pops outside tolerance on the as-received test shall be recorded as a failed test even if it passes "
             "after adjustment."),
            ("4. Records", "Record the as-received pop pressure, as-left pop pressure, seat tightness result, spring "
             "number and the name of the witness. Update the PSV register within 3 working days of the test."),
            ("5. Responsibilities", "The Maintenance Engineer arranges removal and isolation. The Inspection "
             "Engineer witnesses the test. Recertification is signed by the Inspection Engineer, never by the "
             "workshop technician alone."),
        ],
    },
    {
        "id": "SOP-INS-020", "title": "Heat Exchanger Shell Thickness Inspection", "rev": "B",
        "sections": [
            ("1. Scope", "Applies to shell-and-tube heat exchangers in hydrocarbon service. Condition monitoring "
             "locations (CMLs) are fixed points on the shell and nozzles where wall thickness is measured by "
             "ultrasonic testing (UT) at every inspection."),
            ("2. Corrosion rate", "The short-term corrosion rate (CR) at a CML is the loss in thickness divided by "
             "the time between the two most recent readings: CR = (t_previous - t_actual) / years between "
             "readings, in mm/year. Use the highest CR among the CMLs of a component for remaining-life "
             "calculations."),
            ("3. Remaining life", "Remaining life (RL) in years = (t_actual - t_min) / CR, where t_min is the "
             "minimum required thickness from the design calculation. If CR is zero or negative, record RL as "
             "greater than 20 years."),
            ("4. Next inspection date", "The next internal inspection shall be scheduled at the lesser of half the "
             "remaining life or 10 years from the current inspection. Where the remaining life is less than 4 "
             "years the equipment shall be referred to the Integrity Review Board."),
            ("5. Reporting", "The inspection report shall list every CML with its previous and actual thickness, "
             "the calculated corrosion rate, remaining life and the recommended next inspection date. Any CML "
             "below t_min requires an immediate fitness-for-service review."),
        ],
    },
    {
        "id": "SOP-INS-021", "title": "Piping Thickness Monitoring Programme", "rev": "A",
        "sections": [
            ("1. Purpose", "Defines the thickness monitoring programme for process piping, including CML selection, "
             "measurement frequency and data review."),
            ("2. CML selection", "Select CMLs at elbows, tees, reducers, injection points and dead legs. Injection "
             "points require CMLs from 300 mm upstream to 10 pipe diameters downstream."),
            ("3. Frequency", "Class 1 piping (flammable, toxic or high-consequence service): every 5 years or half "
             "remaining life, whichever is less. Class 2 piping: every 10 years or half remaining life. Injection "
             "points: every 3 years."),
            ("4. Data review", "Readings that show a thickness increase of more than 0.5 mm over the previous "
             "reading shall be re-measured before use, because they usually indicate a measurement error."),
        ],
    },
    {
        "id": "SOP-OPS-001", "title": "Hot Work Permit Procedure", "rev": "D",
        "sections": [
            ("1. When a hot work permit is required", "Any work that produces flame, sparks or heat able to ignite "
             "flammable material: welding, grinding, cutting, and the use of non-intrinsically-safe electrical "
             "equipment within a hazardous area."),
            ("2. Gas testing", "Before issue, the area shall be gas tested. The lower explosive limit (LEL) reading "
             "shall be 0 percent at the work point and below 10 percent LEL within 15 metres. Oxygen shall be "
             "between 19.5 and 23.5 percent by volume. Re-test every 2 hours and after any break longer than 30 "
             "minutes."),
            ("3. Isolation", "Lines within 15 metres shall be isolated, drained and blinded or confirmed free of "
             "hydrocarbons. Open drains and sewers within 15 metres shall be covered."),
            ("4. Fire watch", "A trained fire watch with a charged extinguisher shall remain at the site during the "
             "work and for 30 minutes after completion."),
            ("5. Validity", "A hot work permit is valid for one shift, maximum 8 hours, and must be revalidated by "
             "the area authority at shift change."),
        ],
    },
    {
        "id": "SOP-OPS-002", "title": "Confined Space Entry", "rev": "C",
        "sections": [
            ("1. Definition", "A confined space is an enclosed space with limited entry or exit and not designed for "
             "continuous occupancy, for example vessels, columns, tanks and pits."),
            ("2. Atmosphere testing", "Test in this order: oxygen, flammables, then toxics. Entry is allowed only when "
             "oxygen is 19.5 to 23.5 percent, flammables are below 1 percent LEL and H2S is below 1 ppm."),
            ("3. Attendant", "A standby attendant shall remain at the entry point at all times and shall never enter "
             "to attempt a rescue."),
            ("4. Rescue plan", "A written rescue plan and rescue equipment shall be available before entry."),
        ],
    },
    {
        "id": "SOP-HSE-040", "title": "H2S Exposure Response", "rev": "B",
        "sections": [
            ("1. Alarm levels", "Personal H2S monitors alarm at 5 ppm (low) and 10 ppm (high). Fixed area detectors "
             "alarm at 10 ppm and 20 ppm."),
            ("2. Immediate actions", "On a high alarm, stop work, move upwind or crosswind to the muster point and "
             "report to the control room. Do not re-enter until the area authority confirms H2S below 1 ppm."),
            ("3. Rescue", "Rescue of a casualty requires breathing apparatus. Never attempt rescue without it."),
        ],
    },
    {
        "id": "SOP-MNT-050", "title": "Centrifugal Pump Mechanical Seal Replacement", "rev": "A",
        "sections": [
            ("1. Preparation", "Obtain a work permit, isolate suction and discharge valves, drain and depressurise the "
             "casing, and lock out the motor at the switchgear."),
            ("2. Replacement", "Measure shaft run-out before fitting the new seal. Run-out shall not exceed 0.05 mm "
             "TIR. Clean the seal faces with lint-free cloth and never touch them with bare hands."),
            ("3. Commissioning", "Vent the seal chamber before start-up. Check for leakage for the first 30 minutes of "
             "operation."),
        ],
    },
    {
        "id": "SOP-OPS-030", "title": "Crude Distillation Unit Start-up Checklist", "rev": "E",
        "sections": [
            ("1. Pre-start checks", "Confirm all blinds are removed as per the blind list, all PSVs are in service, "
             "and the flare system is lined up."),
            ("2. Heating", "Raise the furnace outlet temperature at no more than 50 degC per hour until 250 degC, then "
             "at no more than 30 degC per hour to operating temperature."),
            ("3. Column", "Establish reflux before drawing side products. Keep the overhead drum level between 40 and "
             "60 percent."),
        ],
    },
    {
        "id": "SOP-OPS-060", "title": "Flare System Operation", "rev": "B",
        "sections": [
            ("1. Purpose", "The flare safely burns hydrocarbons released by relief valves and depressuring."),
            ("2. Purge gas", "Maintain a continuous purge gas flow to prevent air ingress into the flare header."),
            ("3. Smokeless operation", "Adjust steam to the flare tip to keep the flame smokeless. Record any visible "
             "smoke event longer than 5 minutes."),
        ],
    },
    {
        "id": "STD-ENG-100", "title": "Instrument Tag and Line Numbering Convention", "rev": "C",
        "sections": [
            ("1. Instrument tags", "Instrument tags follow the pattern letters-number, for example PV-101, FT-2031, "
             "LT-305. The first letter is the measured variable: P pressure, F flow, L level, T temperature. The "
             "following letters give the function: T transmitter, I indicator, C controller, V valve, SV safety "
             "valve."),
            ("2. Numbering", "The first digit of the number identifies the unit: 1 crude unit, 2 vacuum unit, 3 "
             "hydrotreater. PSVs use the prefix PSV, for example PSV-1204."),
            ("3. Line numbers", "Line numbers follow size-service-number-class, for example 6\"-P-1045-A1B, where P "
             "is process hydrocarbon and A1B is the piping class."),
        ],
    },
    {
        "id": "STD-ENG-110", "title": "Corrosion Allowance and Material Selection", "rev": "A",
        "sections": [
            ("1. Corrosion allowance", "Carbon steel in hydrocarbon service: 3 mm corrosion allowance. Sour water and "
             "amine service: 6 mm, or upgrade to stainless steel."),
            ("2. Material upgrade", "Where the measured corrosion rate exceeds 0.25 mm/year for two consecutive "
             "inspections, the Inspection Engineer shall propose a material upgrade or chemical treatment review."),
        ],
    },
    {
        "id": "GUIDE-DOC-070", "title": "Approval Note Format", "rev": "A",
        "sections": [
            ("1. Purpose", "Approval notes request a decision from the approving authority. They are drafted by the "
             "engineer and approved by a person with delegated authority."),
            ("2. Structure", "Subject; Background; Findings with references to the source reports and page numbers; "
             "Recommendation; Cost and schedule impact; Risks of not acting; Approvals required."),
            ("3. Rules", "Every number in the note shall be traceable to a source document. The note shall not "
             "state that equipment is safe to operate; that judgement belongs to the approving authority."),
        ],
    },
]


# ------------------------------------------------------------------ inspection reports

def _cml(cml, loc, t_prev, t_act, t_min, years):
    cr = round((t_prev - t_act) / years, 3)
    rl = round((t_act - t_min) / cr, 1) if cr > 0 else None
    return {"cml": cml, "loc": loc, "t_prev": t_prev, "t_act": t_act, "t_min": t_min, "cr": cr, "rl": rl}


REPORTS: list[dict] = [
    {
        "no": "IR-2026-0147", "equip": "E-2104", "desc": "Crude / residue heat exchanger, shell side",
        "unit": "Crude Distillation Unit 2", "date": date(2026, 9, 12), "prev": date(2022, 9, 20), "inspector": "A. Rao (synthetic)",
        "cmls": [
            _cml("C1", "Shell top, inlet end", 12.0, 11.1, 6.2, 4.0),
            _cml("C2", "Shell bottom, inlet end", 12.0, 10.8, 6.2, 4.0),
            _cml("C3", "Nozzle N3 (outlet)", 11.5, 9.8, 6.2, 4.0),
            _cml("C4", "Shell bottom, outlet end", 12.0, 11.4, 6.2, 4.0),
        ],
        "findings": [
            "Nozzle N3 shows the highest wall loss. Localised pitting up to 0.6 mm deep was found on the tube sheet.",
            "No cracking was detected by magnetic particle testing on the shell-to-nozzle welds.",
        ],
        "rec": "Re-inspect nozzle N3 by UT in 24 months. Review crude desalter performance for chloride carry-over.",
    },
    {
        "no": "IR-2026-0151", "equip": "V-3102", "desc": "Hydrotreater high-pressure separator",
        "unit": "Diesel Hydrotreater 3", "date": date(2026, 8, 28), "prev": date(2021, 8, 30), "inspector": "S. Menon (synthetic)",
        "cmls": [
            _cml("C1", "Shell course 1", 38.0, 37.6, 31.0, 5.0),
            _cml("C2", "Shell course 2", 38.0, 37.7, 31.0, 5.0),
            _cml("C3", "Bottom head", 40.0, 39.1, 32.5, 5.0),
        ],
        "findings": ["Wall loss is uniform and low. Minor coating breakdown on the external insulation support ring."],
        "rec": "Continue the 5-year internal inspection interval. Repair external coating at the next opportunity.",
    },
    {
        "no": "IR-2026-0155", "equip": "P-1201B", "desc": "Crude charge pump casing",
        "unit": "Crude Distillation Unit 1", "date": date(2026, 7, 14), "prev": date(2023, 7, 10), "inspector": "K. Shetty (synthetic)",
        "cmls": [
            _cml("C1", "Casing volute", 22.0, 21.1, 17.0, 3.0),
            _cml("C2", "Suction nozzle", 14.0, 13.2, 9.5, 3.0),
        ],
        "findings": ["Erosion marks at the volute tongue. Mechanical seal leaking at 5 drops per minute."],
        "rec": "Replace mechanical seal per SOP-MNT-050. Re-measure casing in 3 years.",
    },
    {
        "no": "IR-2026-0160", "equip": "6\"-P-1045-A1B", "desc": "Crude overhead line downstream of wash water injection",
        "unit": "Crude Distillation Unit 1", "date": date(2026, 6, 2), "prev": date(2023, 6, 5), "inspector": "A. Rao (synthetic)",
        "cmls": [
            _cml("C1", "Injection point +300 mm", 7.1, 5.9, 3.4, 3.0),
            _cml("C2", "Elbow E-4", 7.1, 5.6, 3.4, 3.0),
            _cml("C3", "10D downstream", 7.1, 6.5, 3.4, 3.0),
        ],
        "findings": ["Elbow E-4 shows the highest corrosion rate, consistent with ammonium chloride under-deposit corrosion."],
        "rec": "Corrosion rate exceeds 0.25 mm/year at two CMLs: propose material upgrade review per STD-ENG-110. "
               "Increase monitoring of elbow E-4 to annual.",
    },
    {
        "no": "IR-2026-0163", "equip": "PSV-1204", "desc": "Pressure safety valve on crude column overhead drum",
        "unit": "Crude Distillation Unit 1", "date": date(2026, 5, 20), "prev": date(2025, 5, 18), "inspector": "S. Menon (synthetic)",
        "cmls": [],
        "psv": {"set": 3.5, "as_received": 3.71, "as_left": 3.52},
        "findings": ["As-received pop pressure 3.71 bar(g) against a set pressure of 3.5 bar(g).",
                     "After overhaul and adjustment the valve popped at 3.52 bar(g). Seat tight."],
        "rec": "Record the as-received test as FAILED per SOP-MNT-010 section 3 (tolerance +/- 0.15 bar for set "
               "pressures of 5 bar(g) or less). Keep 12-month test interval (fouling service).",
    },
]


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.grey)
    canvas.drawString(18 * mm, 10 * mm, FOOTER)
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _doc(path_or_buf, title: str) -> SimpleDocTemplate:
    return SimpleDocTemplate(path_or_buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                             topMargin=16 * mm, bottomMargin=18 * mm, title=title, author=ORG)


def build_kb(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for d in KB_DOCS:
        story = [Paragraph(ORG, SMALL), Paragraph(f"{d['id']} &nbsp; {d['title']}", H1),
                 Paragraph(f"Revision {d['rev']} · Owner: Technical Services · Classification: Internal", SMALL),
                 Spacer(1, 6)]
        for head, text in d["sections"]:
            story += [Paragraph(head, H2), Paragraph(text, BODY)]
        _doc(str(out / f"{d['id']}.pdf"), d["title"]).build(story, onFirstPage=_footer, onLaterPages=_footer)


def report_story(r: dict) -> tuple[list, str]:
    """Returns (reportlab story, plain-text ground truth)."""
    years = round((r["date"] - r["prev"]).days / 365.25, 1)
    truth = [ORG, f"INSPECTION REPORT {r['no']}", f"Equipment: {r['equip']} {r['desc']}", f"Unit: {r['unit']}",
             f"Inspection date: {r['date']:%d-%b-%Y} Previous inspection: {r['prev']:%d-%b-%Y}",
             f"Inspector: {r['inspector']}"]
    story = [Paragraph(ORG, SMALL), Paragraph(f"INSPECTION REPORT &nbsp; {r['no']}", H1),
             Paragraph(f"<b>Equipment:</b> {r['equip']} &nbsp; {r['desc']}", BODY),
             Paragraph(f"<b>Unit:</b> {r['unit']}", BODY),
             Paragraph(f"<b>Inspection date:</b> {r['date']:%d-%b-%Y} &nbsp; <b>Previous inspection:</b> {r['prev']:%d-%b-%Y}", BODY),
             Paragraph(f"<b>Inspector:</b> {r['inspector']}", BODY), Spacer(1, 6)]
    if r["cmls"]:
        story.append(Paragraph(f"Thickness readings (UT), interval {years} years", H2))
        truth.append(f"Thickness readings (UT), interval {years} years")
        rows = [["CML", "Location", "t prev (mm)", "t actual (mm)", "t min (mm)", "CR (mm/yr)", "RL (yr)"]]
        for c in r["cmls"]:
            rows.append([c["cml"], c["loc"], f"{c['t_prev']:.1f}", f"{c['t_act']:.1f}", f"{c['t_min']:.1f}",
                         f"{c['cr']:.3f}", "-" if c["rl"] is None else f"{c['rl']:.1f}"])
        for row in rows:
            truth.append(" ".join(row))
        t = Table(rows, colWidths=[12 * mm, 52 * mm, 20 * mm, 22 * mm, 18 * mm, 20 * mm, 16 * mm])
        t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 9), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
                               ("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        story += [t, Spacer(1, 6)]
    if r.get("psv"):
        p = r["psv"]
        line = f"Set pressure {p['set']} bar(g); as-received pop {p['as_received']} bar(g); as-left pop {p['as_left']} bar(g)."
        story += [Paragraph("Bench test", H2), Paragraph(line, BODY)]
        truth += ["Bench test", line]
    story.append(Paragraph("Findings", H2))
    truth.append("Findings")
    for i, f in enumerate(r["findings"], 1):
        story.append(Paragraph(f"{i}. {f}", BODY))
        truth.append(f"{i}. {f}")
    story += [Paragraph("Recommendation", H2), Paragraph(r["rec"], BODY)]
    truth += ["Recommendation", r["rec"]]
    return story, "\n".join(truth) + "\n"


def scan(pdf_bytes: bytes, rng: random.Random, dpi: int = 150) -> bytes:
    """Rasterise each page and degrade it like a photocopied scan. Returns an image-only PDF."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(pdf_bytes)
    pages = []
    for i in range(len(pdf)):
        im = pdf[i].render(scale=dpi / 72).to_pil().convert("L")
        im = im.rotate(rng.uniform(-2.2, 2.2), resample=Image.BICUBIC, expand=False, fillcolor=255)
        im = im.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.4, 0.8)))
        a = np.asarray(im, dtype=np.float32)
        nprng = np.random.default_rng(rng.randint(0, 2**31))
        a = a * rng.uniform(0.9, 0.97) + nprng.normal(0, 9, a.shape)          # toner + sensor noise
        speck = nprng.random(a.shape)
        a[speck < 0.0015] = 0                                                  # dust specks
        a[speck > 0.9985] = 255
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=rng.randint(45, 65))               # JPEG artefacts
        pages.append(Image.open(io.BytesIO(buf.getvalue())).convert("L"))
    pdf.close()
    out = io.BytesIO()
    pages[0].save(out, format="PDF", save_all=True, append_images=pages[1:], resolution=dpi)
    return out.getvalue()


def build_reports(out: Path, rng: random.Random) -> None:
    (out / "_truth").mkdir(parents=True, exist_ok=True)
    for r in REPORTS:
        story, truth = report_story(r)
        buf = io.BytesIO()
        _doc(buf, f"Inspection report {r['no']}").build(story, onFirstPage=_footer, onLaterPages=_footer)
        (out / f"{r['no']}_scan.pdf").write_bytes(scan(buf.getvalue(), rng))
        (out / "_truth" / f"{r['no']}.txt").write_text(truth, encoding="utf-8")


def build_sheets(out: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    out.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "CML log"
    ws.append(["Report", "Equipment", "CML", "Location", "Date previous", "t previous (mm)", "Date actual",
               "t actual (mm)", "t min (mm)"])
    for r in REPORTS:
        for c in r["cmls"]:
            ws.append([r["no"], r["equip"], c["cml"], c["loc"], r["prev"], c["t_prev"], r["date"], c["t_act"], c["t_min"]])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    wb.save(out / "cml_thickness_log.xlsx")

    wb = Workbook()
    ws = wb.active
    ws.title = "PSV register"
    ws.append(["Tag", "Service", "Set pressure (barg)", "Interval (months)", "Last test", "Result", "Next due"])
    rows = [
        ("PSV-1204", "Crude column overhead drum", 3.5, 12, date(2026, 5, 20), "FAILED as-received", date(2027, 5, 20)),
        ("PSV-1210", "Crude column bottoms", 9.0, 24, date(2025, 3, 11), "PASS", date(2027, 3, 11)),
        ("PSV-2105", "Vacuum column overhead", 1.2, 12, date(2025, 11, 2), "PASS", date(2026, 11, 2)),
        ("PSV-3101", "Hydrotreater HP separator", 62.0, 24, date(2024, 10, 9), "PASS", date(2026, 10, 9)),
        ("PSV-3140", "Amine regenerator", 2.8, 12, date(2025, 7, 30), "PASS", date(2026, 7, 30)),
    ]
    for row in rows:
        ws.append(list(row))
    for cell in ws[1]:
        cell.font = Font(bold=True)
    wb.save(out / "psv_register.xlsx")


CODE_FILES = {
    "corrosion_calc/__init__.py": '"""Corrosion rate and remaining-life helpers (synthetic demo code)."""\n\n'
    "from .rates import corrosion_rate, remaining_life, next_inspection_years\n",
    "corrosion_calc/rates.py": '''"""Formulas from KCR SOP-INS-020 (synthetic)."""


def corrosion_rate(t_prev: float, t_actual: float, years: float) -> float:
    """Short-term corrosion rate in mm/year."""
    if years <= 0:
        raise ValueError("years must be positive")
    return (t_prev - t_actual) / years


def remaining_life(t_actual: float, t_min: float, cr: float) -> float | None:
    """Remaining life in years; None means 'more than 20 years' (no measurable corrosion)."""
    if cr <= 0:
        return None
    return (t_actual - t_min) / cr


def next_inspection_years(rl: float | None) -> float:
    """Lesser of half the remaining life or 10 years."""
    if rl is None:
        return 10.0
    return min(rl / 2, 10.0)
''',
    "corrosion_calc/cli.py": '''import sys

from .rates import corrosion_rate, next_inspection_years, remaining_life

if __name__ == "__main__":
    t_prev, t_act, t_min, years = map(float, sys.argv[1:5])
    cr = corrosion_rate(t_prev, t_act, years)
    rl = remaining_life(t_act, t_min, cr)
    print(f"CR={cr:.3f} mm/yr RL={rl} yr next={next_inspection_years(rl):.1f} yr")
''',
    "README.md": "# corrosion_calc\n\nSynthetic helper package used in KILA demos. Usage:\n\n"
    "    python -m corrosion_calc.cli 11.5 9.8 6.2 4.0\n",
}


def build_code(out: Path) -> None:
    for rel, text in CODE_FILES.items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def main() -> None:
    rng = random.Random(2026)
    build_kb(SEED / "kb")
    build_reports(SEED / "reports", rng)
    build_sheets(SEED / "sheets")
    build_code(SEED / "code")
    (SEED / "README.md").write_text(
        "# Seed corpus (SYNTHETIC)\n\nGenerated by `scripts/make_seed_corpus.py`. Every organisation, person, "
        "tag and number here is fictional. Do not add real plant documents to this folder.\n", encoding="utf-8")
    n = sum(1 for _ in SEED.rglob("*") if _.is_file())
    print(f"seed corpus written: {n} files under {SEED.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
