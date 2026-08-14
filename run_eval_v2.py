"""
Re-run evaluation with improved detector outputs.
Run this AFTER the final redaction completes.
"""
import subprocess, sys

# Step 1: Re-generate annotations with improved detectors
print("Step 1: Regenerating annotation file with improved detectors...")
result = subprocess.run(
    [sys.executable, "-m", "pii_redactor.redactor",
     "Red Herring Prospectus.docx",
     "--evaluate",
     "--annotation-file", "annotations_v2.json",
     "--log-level", "WARNING"],
    capture_output=True, text=True, cwd="."
)
print(result.stdout[-2000:] if result.stdout else "")
print(result.stderr[-2000:] if result.stderr else "")

# Step 2: Apply annotation corrections
print("\nStep 2: Applying annotation corrections...")
import json, re

with open("annotations_v2.json", encoding="utf-8") as f:
    annotations = json.load(f)

PERSON_BLOCKLIST = {
    "offer", "the offer", "directors", "director", "promoters", "promoter",
    "shareholders", "shareholder", "investors", "investor", "bankers", "banker",
    "members", "member", "management", "board", "syndicate", "brlm", "brlms",
    "reference rate", "base rate", "repo rate",
    "act", "companies act", "the act", "schedule", "annexure", "section",
    "india", "government", "mumbai", "delhi", "pune", "sebi", "rbi", "bse", "nse",
    "the company", "our company", "icai", "icsi",
}

def is_financial_date(text, context):
    ctx = context.lower()
    for kw in ["fiscal", "fy ", "financial year", "quarter", "ended",
               "period ended", "year ended", "allotment", "bid open",
               "listing", "incorporation", "resolution", "certificate",
               "companies act", "act, 19", "act, 20"]:
        if kw in ctx:
            if any(x in ctx for x in ["age:", "born", "date of birth"]):
                return False
            return True
    return False

corrected = []
fp_count = tp_count = 0
for entry in annotations:
    context = entry["text"]
    dets = []
    for det in entry["detections"]:
        ptype, text = det["pii_type"], det["text"]
        is_fp = det.get("fp", False)
        if ptype == "PERSON" and text.strip().lower() in PERSON_BLOCKLIST:
            is_fp = True
        elif ptype == "DATE_OF_BIRTH" and is_financial_date(text, context):
            is_fp = True
        if is_fp:
            fp_count += 1
        else:
            tp_count += 1
        dets.append({**det, "fp": is_fp})
    corrected.append({**entry, "detections": dets})

print(f"  Total detections: {fp_count + tp_count}")
print(f"  FP marked: {fp_count}  ({fp_count/(fp_count+tp_count):.1%})")
print(f"  TP kept:   {tp_count}  ({tp_count/(fp_count+tp_count):.1%})")

with open("corrected_v2.json", "w", encoding="utf-8") as f:
    json.dump(corrected, f, indent=2, ensure_ascii=False)

# Step 3: Compute metrics
from pii_redactor.evaluator import evaluate_from_annotations, print_evaluation_report
results = evaluate_from_annotations("corrected_v2.json")
print_evaluation_report(results)

import json
with open("eval_report_v2.json", "w") as f:
    json.dump(results, f, indent=2)
print("Saved: eval_report_v2.json")
