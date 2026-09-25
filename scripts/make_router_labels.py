"""Generate the SYNTHETIC labelled request set for router calibration: seed/router_labels.jsonl.

Each line: {"id", "text", "lang", "attachments": [kinds], "task_type", "difficulty", "needs_vision"}.
English requests come from templates x slot values; Hindi and Kannada requests are hand-written.
All equipment, tags and numbers are fictional (Konkan Coastal Refinery). Deterministic (seed 7).

    uv run --directory services/api python ../../scripts/make_router_labels.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
rng = random.Random(7)

EQUIP = ["E-2104", "V-3102", "P-1201B", "C-101", "T-4401", "E-1105", "K-2201", "F-101"]
TAGS = ["PSV-1204", "PV-101", "FT-2031", "LT-305", "TIC-4410", "PSV-3101"]
REPORTS = ["IR-2026-0147", "IR-2026-0151", "IR-2026-0155", "IR-2026-0160", "IR-2026-0163"]
UNITS = ["crude unit", "vacuum unit", "hydrotreater", "amine unit", "flare system"]
VENDORS = ["Deccan Valves", "Malabar Pumps", "Sahyadri Instruments", "Coastal Gaskets"]

# (template, difficulty, needs_vision, attachments)
T: dict[str, list[tuple[str, str, bool, list[str]]]] = {
    "approval_note": [
        ("Draft an approval note recommending re-inspection of {equip} based on the attached report", "high", False, ["pdf_scanned"]),
        ("Prepare an approval note for replacing the mechanical seal on {equip}", "medium", False, []),
        ("Write a recommendation note to extend the PSV test interval for {tag} to 36 months", "high", False, []),
        ("Draft a note seeking approval to run {equip} until the next turnaround given the findings in {report}", "high", False, ["pdf_scanned"]),
        ("Put together an approval request for the material upgrade of the {unit} overhead line", "high", False, []),
        ("Make a short approval note for procuring spares for {tag}", "low", False, []),
        ("Write the approval note for the corrosion findings in {report} with cost and risk", "high", False, ["pdf_scanned"]),
        ("Draft a management approval memo for a temporary repair clamp on {equip}", "high", False, []),
    ],
    "inspection_summary": [
        ("Summarise the findings of inspection report {report}", "low", False, ["pdf_scanned"]),
        ("What did the inspector find on {equip} in the attached scan?", "low", False, ["pdf_scanned"]),
        ("List all CMLs below minimum thickness in {report}", "medium", False, ["pdf_scanned"]),
        ("Extract the recommendations from the attached inspection report", "low", False, ["pdf_scanned"]),
        ("Give me the key findings and the next inspection date from {report}", "medium", False, ["pdf_scanned"]),
        ("Summarise this photographed inspection sheet for {equip}", "medium", True, ["image"]),
        ("Pull out every thickness reading from the scanned report for {equip} into a list", "medium", False, ["pdf_scanned"]),
        ("Read the handwritten remarks on the attached inspection page and summarise them", "medium", True, ["image"]),
    ],
    "engineering_calc": [
        ("Calculate the corrosion rate for {equip} CML C3: {a} mm to {b} mm over 4 years", "medium", False, []),
        ("Compute the remaining life if t_actual is {b} mm, t_min is 6.2 mm and the rate is 0.4 mm/yr", "medium", False, []),
        ("Convert {n} bar(g) to kPa absolute", "low", False, []),
        ("Check the PSV sizing for {tag} relieving 12,000 kg/h of hydrocarbon vapour", "high", False, []),
        ("Verify the minimum required thickness for a 10 inch pipe at 40 barg, design 300 C", "high", False, []),
        ("What is the next inspection date if remaining life is {n} years?", "low", False, []),
        ("Recalculate all corrosion rates in {report} and flag any errors", "high", False, ["pdf_scanned"]),
        ("Work out the pressure drop across the {unit} exchanger at 340 m3/h", "high", False, []),
    ],
    "pid_digitise": [
        ("Digitise the attached P&ID and list all instrument tags", "high", True, ["image"]),
        ("Read this P&ID drawing and give me a tag register", "high", True, ["pdf_scanned"]),
        ("Which valves are connected to {tag} on the attached drawing?", "medium", True, ["image"]),
        ("Extract the line numbers from the P&ID sheet for the {unit}", "medium", True, ["pdf_scanned"]),
        ("Trace the flow path from {equip} to the flare on this P&ID", "high", True, ["image"]),
        ("Find every control loop shown on the attached engineering drawing", "high", True, ["image"]),
        ("List the equipment shown on this drawing of the {unit}", "medium", True, ["pdf_scanned"]),
        ("Mark up the instrument bubbles on the scanned P&ID", "medium", True, ["image"]),
    ],
    "code_task": [
        ("Fix the bug in this python function that computes the corrosion rate", "medium", False, ["code"]),
        ("Write a python script to read the CML log and compute remaining life", "medium", False, []),
        ("Explain what this code does", "low", False, ["code"]),
        ("Add unit tests for the remaining_life function", "medium", False, ["code"]),
        ("Refactor this module so it reads thresholds from a config file", "medium", False, ["code"]),
        ("Why does this script crash with a division by zero when the rate is 0?", "medium", False, ["code"]),
        ("Write a SQL query to list PSVs overdue for testing", "low", False, []),
        ("Port this VBA macro from the inspection workbook to python", "high", False, ["code"]),
    ],
    "correspondence": [
        ("Reply to {vendor} asking for a revised quotation for {tag} spares", "low", False, []),
        ("Draft an email to the {unit} shift in-charge about the permit for hot work tomorrow", "low", False, []),
        ("Write a letter to {vendor} rejecting the delivery because the test certificates are missing", "medium", False, []),
        ("Respond to the vendor query in the attached letter about the gasket material", "medium", False, ["pdf_text"]),
        ("Send a polite reminder to {vendor} about the overdue calibration report", "low", False, []),
        ("Draft a reply to the contractor explaining why the scaffold permit was cancelled", "medium", False, []),
        ("Write a covering letter for the inspection report {report} to the plant manager", "low", False, []),
        ("Compose an email to procurement escalating the late delivery of {equip} parts", "low", False, []),
    ],
    "sheet_analysis": [
        ("From the attached spreadsheet, which equipment has the fastest corrosion?", "medium", False, ["sheet"]),
        ("Which PSVs in the register are overdue for testing?", "low", False, ["sheet"]),
        ("Pivot the CML log by equipment and show the worst reading per item", "medium", False, ["sheet"]),
        ("Clean up this spreadsheet and remove duplicate readings", "low", False, ["sheet"]),
        ("Plot the thickness trend for {equip} from the attached workbook", "medium", False, ["sheet"]),
        ("Compare this month's instrument calibration sheet with last month's", "medium", False, ["sheet"]),
        ("Count how many CMLs in the sheet are below 1.2 times t_min", "low", False, ["sheet"]),
        ("Merge the two workbooks and flag readings that disagree by more than 0.5 mm", "high", False, ["sheet"]),
    ],
    "general_qa": [
        ("What is the PSV test interval?", "low", False, []),
        ("How often must the area be re-tested for gas during hot work?", "low", False, []),
        ("What does the SOP say about confined space entry atmosphere limits?", "low", False, []),
        ("What is the corrosion allowance for carbon steel in amine service?", "low", False, []),
        ("Who signs the recertification of a PSV?", "low", False, []),
        ("What alarm level do personal H2S monitors use?", "low", False, []),
        ("What does tag {tag} mean according to the numbering convention?", "low", False, []),
        ("Explain the difference between CR and remaining life in our inspection standard", "medium", False, []),
    ],
}

# Hand-written Hindi (hi) and Kannada (kn) requests: (text, task_type, difficulty, needs_vision, attachments)
HI = [
    ("इस निरीक्षण रिपोर्ट का सारांश बनाइए", "inspection_summary", "low", False, ["pdf_scanned"]),
    ("रिपोर्ट में दिए गए मुख्य निष्कर्ष बताइए", "inspection_summary", "low", False, ["pdf_scanned"]),
    ("E-2104 की दोबारा जाँच के लिए अनुमोदन नोट तैयार कीजिए", "approval_note", "high", False, ["pdf_scanned"]),
    ("सील बदलने के लिए स्वीकृति नोट लिखिए", "approval_note", "medium", False, []),
    ("संक्षारण दर की गणना कीजिए: 11.5 मिमी से 9.8 मिमी, 4 वर्ष में", "engineering_calc", "medium", False, []),
    ("12.5 bar(g) को kPa में बदलिए", "engineering_calc", "low", False, []),
    ("इस P&ID ड्रॉइंग से सभी टैग निकालिए", "pid_digitise", "high", True, ["image"]),
    ("इस चित्र में PSV-1204 से जुड़े वाल्व कौन से हैं?", "pid_digitise", "medium", True, ["image"]),
    ("इस पायथन कोड में गलती ठीक कीजिए", "code_task", "medium", False, ["code"]),
    ("यह कोड क्या करता है, समझाइए", "code_task", "low", False, ["code"]),
    ("विक्रेता को संशोधित कोटेशन के लिए ईमेल लिखिए", "correspondence", "low", False, []),
    ("ठेकेदार को परमिट रद्द होने के बारे में पत्र लिखिए", "correspondence", "medium", False, []),
    ("इस स्प्रेडशीट में सबसे तेज़ संक्षारण किस उपकरण में है?", "sheet_analysis", "medium", False, ["sheet"]),
    ("रजिस्टर में कौन से PSV परीक्षण के लिए लंबित हैं?", "sheet_analysis", "low", False, ["sheet"]),
    ("PSV परीक्षण का अंतराल क्या है?", "general_qa", "low", False, []),
    ("हॉट वर्क के दौरान गैस परीक्षण कितनी बार करना होता है?", "general_qa", "low", False, []),
]
KN = [
    ("ಈ ತಪಾಸಣಾ ವರದಿಯ ಸಾರಾಂಶ ನೀಡಿ", "inspection_summary", "low", False, ["pdf_scanned"]),
    ("ವರದಿಯಲ್ಲಿನ ಮುಖ್ಯ ಅಂಶಗಳನ್ನು ತಿಳಿಸಿ", "inspection_summary", "low", False, ["pdf_scanned"]),
    ("E-2104 ಮರುತಪಾಸಣೆಗೆ ಅನುಮೋದನಾ ಟಿಪ್ಪಣಿ ಸಿದ್ಧಪಡಿಸಿ", "approval_note", "high", False, ["pdf_scanned"]),
    ("ಸೀಲ್ ಬದಲಾವಣೆಗೆ ಅನುಮತಿ ಟಿಪ್ಪಣಿ ಬರೆಯಿರಿ", "approval_note", "medium", False, []),
    ("ತುಕ್ಕು ದರವನ್ನು ಲೆಕ್ಕ ಹಾಕಿ: 4 ವರ್ಷಗಳಲ್ಲಿ 11.5 ಮಿಮೀ ನಿಂದ 9.8 ಮಿಮೀ", "engineering_calc", "medium", False, []),
    ("12.5 bar(g) ಅನ್ನು kPa ಗೆ ಪರಿವರ್ತಿಸಿ", "engineering_calc", "low", False, []),
    ("ಈ P&ID ರೇಖಾಚಿತ್ರದಿಂದ ಎಲ್ಲಾ ಟ್ಯಾಗ್‌ಗಳನ್ನು ಪಟ್ಟಿ ಮಾಡಿ", "pid_digitise", "high", True, ["image"]),
    ("ಈ ಚಿತ್ರದಲ್ಲಿ PSV-1204 ಗೆ ಸಂಪರ್ಕವಿರುವ ಕವಾಟಗಳು ಯಾವುವು?", "pid_digitise", "medium", True, ["image"]),
    ("ಈ ಪೈಥಾನ್ ಕೋಡ್‌ನಲ್ಲಿನ ದೋಷವನ್ನು ಸರಿಪಡಿಸಿ", "code_task", "medium", False, ["code"]),
    ("ಈ ಕೋಡ್ ಏನು ಮಾಡುತ್ತದೆ ಎಂದು ವಿವರಿಸಿ", "code_task", "low", False, ["code"]),
    ("ಪರಿಷ್ಕೃತ ದರಪಟ್ಟಿಗಾಗಿ ಮಾರಾಟಗಾರರಿಗೆ ಇಮೇಲ್ ಬರೆಯಿರಿ", "correspondence", "low", False, []),
    ("ಪರವಾನಗಿ ರದ್ದಾದ ಬಗ್ಗೆ ಗುತ್ತಿಗೆದಾರರಿಗೆ ಪತ್ರ ಬರೆಯಿರಿ", "correspondence", "medium", False, []),
    ("ಈ ಸ್ಪ್ರೆಡ್‌ಶೀಟ್‌ನಲ್ಲಿ ಯಾವ ಉಪಕರಣದಲ್ಲಿ ತುಕ್ಕು ವೇಗವಾಗಿದೆ?", "sheet_analysis", "medium", False, ["sheet"]),
    ("ರಿಜಿಸ್ಟರ್‌ನಲ್ಲಿ ಯಾವ PSV ಗಳ ಪರೀಕ್ಷೆ ಬಾಕಿ ಇದೆ?", "sheet_analysis", "low", False, ["sheet"]),
    ("PSV ಪರೀಕ್ಷೆಯ ಅವಧಿ ಎಷ್ಟು?", "general_qa", "low", False, []),
    ("ಹಾಟ್ ವರ್ಕ್ ಸಮಯದಲ್ಲಿ ಅನಿಲ ಪರೀಕ್ಷೆಯನ್ನು ಎಷ್ಟು ಬಾರಿ ಮಾಡಬೇಕು?", "general_qa", "low", False, []),
]


# How engineers actually phrase requests; varies the surface form without changing the label.
PREFIXES = ["", "", "Please ", "Can you ", "KILA, ", "I need you to ", "Quickly ", "For the audit, "]
SUFFIXES = ["", "", ".", " please", " before the shift meeting", " for the review", " asap", "?"]


def fill(t: str) -> str:
    text = t.format(equip=rng.choice(EQUIP), tag=rng.choice(TAGS), report=rng.choice(REPORTS),
                    unit=rng.choice(UNITS), vendor=rng.choice(VENDORS), a=rng.choice(["11.5", "12.0", "7.1"]),
                    b=rng.choice(["9.8", "10.8", "5.6"]), n=rng.choice(["3.5", "8.5", "12.5", "62"]))
    prefix = rng.choice(PREFIXES)
    if prefix:
        text = prefix + text[0].lower() + text[1:]
    suffix = rng.choice(SUFFIXES)
    return text.rstrip("?.") + suffix if suffix else text


def main() -> None:
    rows = []
    for task, templates in T.items():
        for tmpl, diff, vision, att in templates:
            seen = set()
            for _ in range(12):  # draw until 4 distinct phrasings per template
                if len(seen) == 4:
                    break
                text = fill(tmpl)
                if text in seen:
                    continue
                seen.add(text)
                rows.append({"text": text, "lang": "en", "attachments": att, "task_type": task,
                             "difficulty": diff, "needs_vision": vision})
    for lang, items in (("hi", HI), ("kn", KN)):
        for text, task, diff, vision, att in items:
            rows.append({"text": text, "lang": lang, "attachments": att, "task_type": task,
                         "difficulty": diff, "needs_vision": vision})
    rng.shuffle(rows)
    out = ROOT / "seed" / "router_labels.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for i, r in enumerate(rows):
            f.write(json.dumps({"id": f"r{i:03d}", **r}, ensure_ascii=False) + "\n")
    from collections import Counter

    print(f"{len(rows)} labelled requests -> {out.relative_to(ROOT)}")
    print("by task:", dict(Counter(r["task_type"] for r in rows)))
    print("by lang:", dict(Counter(r["lang"] for r in rows)), " by difficulty:", dict(Counter(r["difficulty"] for r in rows)),
          " vision:", sum(r["needs_vision"] for r in rows))


if __name__ == "__main__":
    main()
