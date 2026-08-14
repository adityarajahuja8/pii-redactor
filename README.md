# PII Redaction Tool — Red Herring Prospectus

## Overview

This tool automatically detects and redacts Personally Identifiable Information (PII) from a `.docx` file — specifically an Indian IPO Red Herring Prospectus — and produces a redacted `.docx` that preserves original formatting (headings, tables, fonts, styles). Every occurrence of the same real PII value maps to the same fake replacement (consistent pseudonymisation).

---

## Project Structure

```
pii_redactor/
├── __init__.py
├── redactor.py              # CLI entry point
├── document_processor.py   # docx read/write, run-level text replacement
├── faker_mapper.py          # Consistent fake-value cache (real→fake lookup table)
├── evaluator.py             # Ground-truth annotation + precision/recall metrics
└── detectors/
    ├── __init__.py          # ← ONLY place to register a new detector
    ├── base.py              # BasePIIDetector + PIIMatch dataclass
    ├── regex_detectors.py   # Email, Phone, PAN, CIN, Aadhaar, SSN, CC, IP, DOB
    └── ner_detectors.py     # spaCy PERSON names, address heuristic
```

### Adding a New PII Type

1. Create a subclass of `BasePIIDetector` (in `regex_detectors.py` or a new file).
2. Implement `detect(text: str) -> list[PIIMatch]`.
3. Add an instance to `DETECTOR_REGISTRY` in `detectors/__init__.py`.

That is the **only** file you need to edit.

---

## Usage

```bash
# Basic redaction
python -m pii_redactor.redactor "Red Herring Prospectus.docx"

# With explicit output and mapping table
python -m pii_redactor.redactor "Red Herring Prospectus.docx" \
    --output "Redacted.docx" \
    --mapping-output "pii_mapping.json"

# Generate annotation file for evaluation
python -m pii_redactor.redactor "Red Herring Prospectus.docx" --evaluate

# After manually reviewing annotations.json, re-run for metrics
python -m pii_redactor.redactor "Red Herring Prospectus.docx" \
    --evaluate --annotation-file annotations.json
```

---

## Approach: Regex + spaCy NER Hybrid

### Why not pure regex for names and addresses?

A prospectus embeds names in highly varied sentence structures:

> *"Contact Person: Sarthak Malvadkar, Company Secretary... Telephone: +91 20 4505 3237"*  
> *"Mr. Nitin Kumar Gupta, Independent Director (DIN: 00123456)"*  
> *"We hereby appoint Rashi Patil (Age: 34 years, residing at...)"*

A regex name detector would require:
- An exhaustive dictionary of all Indian first names × last names (millions of combinations).
- Separate patterns for "Mr./Ms./Dr." prefixes, compound surnames, middle initials.
- Context awareness to exclude terms like "India", "SEBI", "Companies Act" (which look lexically identical to names to a regex).

**spaCy's statistical NER** generalises across unseen names because it was trained on contextual patterns in surrounding tokens, not string matching alone.

### Why spaCy over Presidio?

Microsoft Presidio wraps spaCy and adds rule-based recognisers. It's excellent for a production system. For this assignment, using spaCy directly:
- Gives full transparency and control over the NER pipeline.
- Avoids the extra Presidio dependency layer.
- Makes it easier to extend with custom recognisers for PAN/CIN (which Presidio doesn't natively support for India).

---

## PII Types Covered

| PII Type | Method | Notes |
|---|---|---|
| **Person Names** | spaCy NER (PERSON) | Extends span to include Mr./Dr./CA. prefixes |
| **Email Addresses** | Regex | Standard RFC-5321 pattern |
| **Phone Numbers** | Regex | +91, 10-digit mobile, STD landline, city code formats |
| **PAN Numbers** | Regex | AAAAA9999A format |
| **CIN Numbers** | Regex | L/U + NIC + state + year + entity type + serial |
| **Aadhaar Numbers** | Regex | Space-separated 12-digit format |
| **SSN** | Regex | US format (NNN-NN-NNNN) — flagged if present |
| **Credit Card Numbers** | Regex | 16-digit Visa/MC/Amex pattern |
| **IP Addresses** | Regex | IPv4 and IPv6 |
| **Dates of Birth** | Regex | DD/MM/YYYY, DD-MM-YYYY, "D Month YYYY" |
| **Physical Addresses** | Heuristic | Sentences with ≥2 Indian address keywords or 6-digit PIN |

### Explicitly NOT Redacted

- **Company names**: The company's own name (e.g., "Sigmoidoscopy Ltd.") appears on every page and is not PII — it is the subject of the prospectus, not a person's private information. SEBI requires it to be clearly identified. Redacting it would render the document meaningless.
- **Director Identification Numbers (DINs)**: DINs are public regulatory identifiers filed with MCA and required to be disclosed in a DRHP/RHP. They are not treated as sensitive IDs by SEBI guidelines.
- **Generic dates** (offer open/close dates, incorporation dates, financial year periods): These are business dates, not dates of birth. The DOB detector has a confidence of 0.6 and is context-filtered in the annotation review.

---

## Tradeoffs, False Positives, and False Negatives

### Observed on this document

**Phone numbers (High recall, moderate precision)**  
- ✅ Detected formats: `+91 20 4505 3237`, `+91-9876543210`, `020-XXXXXXXX`  
- ⚠️ False positives: Some 10-digit financial figures (e.g., "₹ 9,876,543,210") if the rupee symbol was absent in a particular run. The pattern requires a non-digit boundary, which eliminates most but not all.

**PAN numbers (High precision, moderate recall)**  
- ✅ Detected correctly where PAN format (5 uppercase letters + 4 digits + 1 letter) appears.  
- ⚠️ False negatives: PANs written with spaces or dashes (non-standard) are missed.  
- ⚠️ False positives: Regulatory section codes that coincidentally match PAN format (e.g., some SEBI circular references like "SEBI/CFD/..." that happen to match the letter-digit pattern — rare but possible).

**CIN numbers (High precision)**  
- ✅ Very specific format; near-zero false positive rate.  
- ⚠️ False negatives: CINs with non-standard separator characters.

**Person names (Good recall, some false positives)**  
- ✅ Caught names in running text, director tables, KMP profiles.  
- ⚠️ False positives: spaCy occasionally tags organisation abbreviations (e.g., "ICICI", "HDFC" following "Bankers:") as PERSON. The blocklist catches common ones.  
- ⚠️ False negatives: Names in ALL-CAPS table headers (spaCy's NER is less accurate on all-caps text). Names in Hindi script are not detected.

**Dates of birth (Low precision by design)**  
- ⚠️ Many date-format matches in a prospectus are NOT DOBs — they are offer opening/closing dates, financial year dates, AGM dates. The detector sets confidence=0.6 and the annotation review removes these.  
- ✅ Actual DOBs in director/KMP profiles are caught.

**Addresses (High recall, lower precision)**  
- ✅ Registered office addresses, RTA addresses, banker addresses are detected.  
- ⚠️ City mentions in sentences like "...listed on the Mumbai Stock Exchange..." trigger the keyword heuristic. These are false positives at the sentence level.

**Section headers misfire**  
- "Sr. No." column headers: NOT flagged (no PII pattern matches).  
- "Amount (₹)" column headers: NOT flagged.  
- "Companies Act, 2013": NOT flagged (not a PII type we detect).  
- "Table 3 – Financial Summary": NOT flagged.

---

## Implementation Notes

### Formatting Preservation

The tool operates at the `docx.Run` level — the smallest formatting unit in `.docx` XML. Each run has its own font, size, bold, italic, underline properties. By modifying `run.text` rather than rebuilding paragraphs from scratch, all styles are preserved. Only the character content changes.

### Consistent Pseudonymisation

The `FakeValueMapper` uses an MD5 hash of the real value as a Faker seed, making replacement deterministic: the same real name always produces the same fake name across the entire document and across re-runs.

### Dependencies

```
python-docx   # .docx I/O
spacy         # NER pipeline
en_core_web_sm  # spaCy English model (sm: fast; lg: more accurate)
faker         # Realistic fake value generation
tqdm          # Progress display
```

Install:
```bash
pip install python-docx spacy faker tqdm
pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
```
