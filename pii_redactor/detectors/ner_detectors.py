"""
spaCy NER-based detectors for *unstructured* PII:
  - PERSON names
  - Physical addresses (LOC/GPE + heuristic post-processing)

Why not pure regex for names?
-------------------------------
A prospectus like this one embeds names inside legal sentences:
  "Contact Person: Sarthak Malvadkar, Company Secretary"
  "Mr. Nitin Kumar Gupta, Independent Director"
  "Rashi Patil (DIN: 00123456)"

Regex for names requires an exhaustive first/last name dictionary and fails on:
  - Uncommon Indian surnames
  - Names spanning 3+ tokens (middle initials, "Dr." prefix, etc.)
  - Names that are also common words (e.g., "Anand", "Sharma")

spaCy's statistical NER generalizes across unseen names because it was trained on
contextual patterns, not just string matching.

Tradeoffs (documented in README):
  + Better recall on novel names
  - Occasional false positives on organisation names (tagged PERSON)
  - Misses names in ALL-CAPS tabular cells (NER struggles with case)
  - spaCy's en_core_web_lg is English-centric; mixed Hindi/English text can confuse it
"""

from __future__ import annotations
import re
import logging
from .base import BasePIIDetector, PIIMatch

logger = logging.getLogger(__name__)

# Lazy-load spaCy so the module can be imported even if spaCy isn't installed
# (though the detectors will raise if actually called without it).
_nlp = None


def _get_nlp():
    global _nlp
    if _nlp is None:
        import spacy
        # Try large model, then small model by name, then small model by package import
        for model_name in ["en_core_web_lg", "en_core_web_sm"]:
            try:
                _nlp = spacy.load(model_name)
                logger.info(f"Loaded spaCy model: {model_name}")
                return _nlp
            except OSError:
                if model_name == "en_core_web_lg":
                    logger.warning("en_core_web_lg not found, trying en_core_web_sm...")
                continue
        
        # Try direct package import fallback (for whl installations)
        try:
            import en_core_web_sm
            _nlp = en_core_web_sm.load()
            logger.info("Loaded spaCy model via direct import: en_core_web_sm")
            return _nlp
        except Exception as e:
            raise RuntimeError(
                "No spaCy model found. Please install en_core_web_sm model."
            ) from e
    return _nlp


# ---------------------------------------------------------------------------
# Honorifics / title prefixes — used to extend NER spans backwards
# ---------------------------------------------------------------------------
_HONORIFICS = re.compile(
    r"\b(?:Mr\.?|Mrs\.?|Ms\.?|Dr\.?|Prof\.?|Shri\.?|Smt\.?|CA\.?|CS\.?)\s*$",
    re.IGNORECASE,
)


def _extend_span_for_honorific(text: str, start: int) -> int:
    """If text before `start` ends with an honorific, include it."""
    prefix = text[:start]
    m = _HONORIFICS.search(prefix)
    if m:
        return m.start()
    return start


# ---------------------------------------------------------------------------
# PERSON name detector
# ---------------------------------------------------------------------------

# Legal/financial terms that spaCy en_core_web_sm mis-tags as PERSON
# in IPO prospectus language. Extended aggressively to cut false positives.
_PERSON_BLOCKLIST = {
    # Legal offer terms
    "offer", "the offer", "initial public offering", "ipo",
    # Roles used as nouns (not names)
    "directors", "director", "promoters", "promoter", "promoter selling shareholders",
    "shareholders", "shareholder", "investors", "investor",
    "bankers", "banker", "members", "member",
    "management", "board", "syndicate", "brlm", "brlms",
    "book running lead manager", "book running lead managers",
    "registrar", "compliance officer", "company secretary",
    "lead manager", "lead managers", "underwriter",
    # Financial/regulatory terms
    "reference rate", "base rate", "repo rate",
    "act", "companies act", "the act", "sebi",
    "rbi", "rbi guidelines", "fema", "income tax act",
    "schedule", "annexure", "section", "clause",
    # Generic proper nouns spaCy elevates
    "india", "government", "government of india",
    "mumbai", "delhi", "pune", "chennai", "kolkata",
    "sebi", "rbi", "bse", "nse",
    "the company", "our company",
    # Org abbreviations spaCy confuses for persons
    "icai", "icsi", "icici", "hdfc", "kotak", "axis",
    "nuvama", "sbicap", "careEdge", "care",
}

# A valid person name span:
#  - Optional honorific  + 1-4 capitalised name tokens
#  - Tokens must be mostly alpha (not mixed with digits/symbols)
_VALID_NAME_RE = re.compile(
    r"^(?:Mr\.?|Mrs\.?|Ms\.?|Dr\.?|Prof\.?|Shri\.?|Smt\.?|CA\.?|CS\.?|Er\.?)?"
    r"\s*[A-Z][a-zA-Z'\-]{1,}(?:\s+[A-Z][a-zA-Z'\-]{1,}){0,4}$"
)


class PersonNameDetector(BasePIIDetector):
    """
    Uses spaCy NER PERSON entities to detect people's names.

    Post-processing pipeline:
      1. Skip tokens in _PERSON_BLOCKLIST
      2. Skip spans shorter than 3 chars or longer than 5 words
      3. Validate span against _VALID_NAME_RE (must look like a name, not a phrase)
      4. Extend span backward to include preceding honorifics
    """
    PII_TYPE = "PERSON"

    def _is_valid_name(self, text: str) -> bool:
        norm = text.strip().lower()
        if norm in _PERSON_BLOCKLIST:
            return False
        # Each word in blocklist check (single-word FPs like "Offer", "Directors")
        words = norm.split()
        if len(words) == 1 and norm in _PERSON_BLOCKLIST:
            return False
        # Reject if too long (phrases, not names)
        if len(words) > 5:
            return False
        # Structural check
        if not _VALID_NAME_RE.match(text.strip()):
            return False
        return True

    def detect(self, text: str) -> list[PIIMatch]:
        nlp = _get_nlp()
        doc = nlp(text)
        matches = []
        for ent in doc.ents:
            if ent.label_ != "PERSON":
                continue
            raw = ent.text.strip()
            if not self._is_valid_name(raw):
                continue
            # Extend backward for honorifics
            start = _extend_span_for_honorific(text, ent.start_char)
            end = ent.end_char
            matched_text = text[start:end]
            matches.append(PIIMatch(
                pii_type=self.PII_TYPE,
                text=matched_text,
                start=start,
                end=end,
                confidence=0.85,
            ))
        return matches


# ---------------------------------------------------------------------------
# Physical Address detector
# ---------------------------------------------------------------------------

# Indian address keywords that strongly suggest a physical address block
_ADDR_KEYWORDS = re.compile(
    r"\b(?:Plot\s*No\.?|Flat\s*No\.?|Door\s*No\.?|Block\s*No\.?|"
    r"Survey\s*No\.?|Gat\s*No\.?|Khasra\s*No\.?|"
    r"Floor|Building|Tower|Wing|Phase|Sector|Zone|"
    r"Industrial\s+(?:Area|Estate)|MIDC|"
    r"PIN\s*(?:Code)?|Pincode|"
    r"Road|Street|Lane|Marg|Nagar|Colony|Layout|"
    r"Maharashtra|Karnataka|Gujarat|Rajasthan|Tamil\s*Nadu|"
    r"Telangana|Andhra|Kerala|Punjab|Haryana|"
    r"Pune|Mumbai|Bengaluru|Bangalore|Hyderabad|Chennai|"
    r"Delhi|Kolkata|Ahmedabad|Surat|Jaipur|Lucknow|Noida|Gurugram)\b",
    re.IGNORECASE,
)

_PIN_PATTERN = re.compile(r"\b\d{6}\b")

# Street-level tokens: presence of these alongside city keywords strongly
# indicates a physical address rather than a jurisdiction mention.
# e.g. "11/3, 11/4" or "201, Tower 2" vs "Maharashtra at Mumbai" (no street tokens)
_STREET_TOKENS = re.compile(
    r"\b(?:\d+[\/\-]\d+|\d{1,4}\s*,\s*\w|No\.\s*\d|Plot|Flat|Floor|"
    r"Taluka|Village|Off\s+\w|Baner|Khed|Chakan|Birdewadi|Pallod)\b",
    re.IGNORECASE,
)


class AddressDetector(BasePIIDetector):
    """
    Detects Indian physical addresses using a two-stage approach:
      1. 6-digit PIN code present → high confidence address
      2. ≥2 address keywords AND ≥1 street-level token → address
         (requires the street token to avoid triggering on jurisdiction
         mentions like "...the Registrar of Companies, Maharashtra at Mumbai...")

    Tradeoff: This improves precision vs. the previous 2-keyword-only rule while
    maintaining high recall for registered/corporate office addresses.
    """
    PII_TYPE = "ADDRESS"

    def detect(self, text: str) -> list[PIIMatch]:
        matches = []
        # Split into sentences for sentence-level heuristic
        sentences = re.split(r'(?<=[.!?])\s+', text)
        offset = 0
        for sent in sentences:
            kw_hits = len(_ADDR_KEYWORDS.findall(sent))
            pin_hits = len(_PIN_PATTERN.findall(sent))
            street_hits = len(_STREET_TOKENS.findall(sent))

            # Rule 1: PIN code is a near-certain address signal
            is_address = pin_hits > 0
            # Rule 2: multiple keywords + at least one street-level token
            if not is_address and kw_hits >= 2 and street_hits >= 1:
                is_address = True

            if is_address:
                matches.append(PIIMatch(
                    pii_type=self.PII_TYPE,
                    text=sent,
                    start=offset,
                    end=offset + len(sent),
                    confidence=0.80,
                ))
            offset += len(sent) + 1  # +1 for the space removed by split
        return matches
