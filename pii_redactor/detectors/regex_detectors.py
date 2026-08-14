"""
Regex-based detectors for *structured* PII:
  - Email addresses
  - Phone numbers  (Indian formats: +91, 10-digit mobile, landline with STD)
  - PAN numbers    (Indian: AAAAA9999A)
  - CIN numbers    (Corporate Identity Number: L/U + 5 digits + state + year + type + 6 digits)
  - Aadhaar numbers (12-digit, often space-separated)
  - SSN            (US format — unlikely but detected if present)
  - Credit card numbers
  - IP addresses   (v4 and v6)
  - Dates of birth (multiple date formats)

Design principle: Each format gets its own class so it can be toggled/extended independently.
"""

from __future__ import annotations
import re
from .base import BasePIIDetector, PIIMatch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_all(pattern: re.Pattern, text: str, pii_type: str,
              confidence: float = 1.0) -> list[PIIMatch]:
    """Utility: return PIIMatch list for every non-overlapping regex match."""
    matches = []
    for m in pattern.finditer(text):
        matches.append(PIIMatch(
            pii_type=pii_type,
            text=m.group(0),
            start=m.start(),
            end=m.end(),
            confidence=confidence,
        ))
    return matches


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

class EmailDetector(BasePIIDetector):
    """Detects RFC-5321-ish email addresses."""
    PII_TYPE = "EMAIL"

    _PATTERN = re.compile(
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
        re.IGNORECASE,
    )

    def detect(self, text: str) -> list[PIIMatch]:
        return _find_all(self._PATTERN, text, self.PII_TYPE)


# ---------------------------------------------------------------------------
# Phone numbers (Indian)
# ---------------------------------------------------------------------------

class PhoneDetector(BasePIIDetector):
    """
    Detects Indian phone numbers in multiple formats:
      +91 XXXXX XXXXX  |  +91-XXXXXXXXXX  |  0XX-XXXXXXXX (STD landline)
      +91 20 4505 3237  (landline with city code)
      plain 10-digit mobiles starting with 6-9
    Avoids matching purely numeric strings that are clearly financial
    figures (e.g., ₹ amounts) by requiring a non-digit boundary or
    explicit country code.
    """
    PII_TYPE = "PHONE"

    # International prefix variants: +91, 0091, 91 followed by separator
    _PATTERNS = [
        # +91 (space|dash) [optional city code space] 8-10 digit number
        re.compile(
            r"(?<!\d)"
            r"(?:\+91|0091|91)"
            r"[\s\-]?"
            r"(?:\d{2,4}[\s\-])?"   # optional STD/city code
            r"\d{3,5}[\s\-]?\d{4}"
            r"(?!\d)",
            re.IGNORECASE,
        ),
        # Standalone 10-digit mobile starting with 6,7,8,9
        re.compile(
            r"(?<!\d)[6-9]\d{9}(?!\d)"
        ),
        # STD landline: 0XX-XXXXXXX or 0XX XXXXXXX
        re.compile(
            r"(?<!\d)0\d{2,4}[\s\-]\d{6,8}(?!\d)"
        ),
    ]

    def detect(self, text: str) -> list[PIIMatch]:
        seen: set[tuple[int, int]] = set()
        matches: list[PIIMatch] = []
        for pat in self._PATTERNS:
            for m in pat.finditer(text):
                span = (m.start(), m.end())
                if span not in seen:
                    seen.add(span)
                    matches.append(PIIMatch(
                        pii_type=self.PII_TYPE,
                        text=m.group(0).strip(),
                        start=m.start(),
                        end=m.end(),
                    ))
        return matches


# ---------------------------------------------------------------------------
# PAN Number (India)
# ---------------------------------------------------------------------------

class PANDetector(BasePIIDetector):
    """
    PAN: 5 uppercase letters + 4 digits + 1 uppercase letter.
    e.g., ABCDE1234F
    Note: PAN in a prospectus is intentionally disclosed (statutory requirement),
    but flagged here as sensitive ID per the assignment spec.
    """
    PII_TYPE = "PAN"

    _PATTERN = re.compile(
        r"(?<![A-Z0-9])[A-Z]{5}[0-9]{4}[A-Z](?![A-Z0-9])"
    )

    def detect(self, text: str) -> list[PIIMatch]:
        return _find_all(self._PATTERN, text, self.PII_TYPE)


# ---------------------------------------------------------------------------
# CIN Number (India)
# ---------------------------------------------------------------------------

class CINDetector(BasePIIDetector):
    """
    Corporate Identity Number:
    L/U + 5-digit NIC code + 2-letter state + 4-digit year + PLC/LLC/NPL + 6 digits
    e.g., L72200MH2000PLC123456
    """
    PII_TYPE = "CIN"

    _PATTERN = re.compile(
        r"(?<![A-Z0-9])[LU]\d{5}[A-Z]{2}\d{4}(PLC|LLC|NPL|PTC|OPC|SGC|GAP)\d{6}(?![A-Z0-9])",
        re.IGNORECASE,
    )

    def detect(self, text: str) -> list[PIIMatch]:
        return _find_all(self._PATTERN, text, self.PII_TYPE)


# ---------------------------------------------------------------------------
# Aadhaar Number (India)
# ---------------------------------------------------------------------------

class AadhaarDetector(BasePIIDetector):
    """
    Aadhaar: 12 numeric digits, often printed as XXXX XXXX XXXX.
    We look for the space-separated format to avoid matching arbitrary numbers.
    """
    PII_TYPE = "AADHAAR"

    _PATTERN = re.compile(
        r"(?<!\d)\d{4}\s\d{4}\s\d{4}(?!\d)"
    )

    def detect(self, text: str) -> list[PIIMatch]:
        return _find_all(self._PATTERN, text, self.PII_TYPE)


# ---------------------------------------------------------------------------
# SSN (US — unlikely in Indian doc, detect if present)
# ---------------------------------------------------------------------------

class SSNDetector(BasePIIDetector):
    """US SSN: NNN-NN-NNNN. Unlikely in this doc but required by spec."""
    PII_TYPE = "SSN"

    _PATTERN = re.compile(
        r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"
    )

    def detect(self, text: str) -> list[PIIMatch]:
        return _find_all(self._PATTERN, text, self.PII_TYPE)


# ---------------------------------------------------------------------------
# Credit Card Numbers
# ---------------------------------------------------------------------------

class CreditCardDetector(BasePIIDetector):
    """
    16-digit credit card numbers (Visa/MC/Amex etc.) with optional separators.
    Uses the Luhn check stub pattern (not full Luhn) — sufficient for a doc scan.
    """
    PII_TYPE = "CREDIT_CARD"

    _PATTERN = re.compile(
        r"(?<!\d)"
        r"(?:4\d{3}|5[1-5]\d{2}|6(?:011|5\d{2})|3[47]\d{2})"
        r"[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}"
        r"(?!\d)"
    )

    def detect(self, text: str) -> list[PIIMatch]:
        return _find_all(self._PATTERN, text, self.PII_TYPE)


# ---------------------------------------------------------------------------
# IP Addresses
# ---------------------------------------------------------------------------

class IPAddressDetector(BasePIIDetector):
    """IPv4 and IPv6 addresses."""
    PII_TYPE = "IP_ADDRESS"

    _IPV4 = re.compile(
        r"(?<!\d)"
        r"(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
        r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)"
        r"(?!\d)"
    )
    _IPV6 = re.compile(
        r"(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}"
    )

    def detect(self, text: str) -> list[PIIMatch]:
        matches = _find_all(self._IPV4, text, self.PII_TYPE)
        matches += _find_all(self._IPV6, text, self.PII_TYPE)
        return matches


# ---------------------------------------------------------------------------
# Dates of Birth
# ---------------------------------------------------------------------------

class DOBDetector(BasePIIDetector):
    """
    Detects likely dates of birth in common formats:
      DD/MM/YYYY  |  DD-MM-YYYY  |  D Month YYYY  |  Month D, YYYY
    Context-awareness note: This will also match non-DOB dates (offer open dates,
    incorporation dates, etc.). The evaluation report should call this out.
    """
    PII_TYPE = "DATE_OF_BIRTH"

    _MONTHS = (
        r"(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    )

    _PATTERNS = [
        # DD/MM/YYYY or DD-MM-YYYY
        re.compile(r"(?<!\d)\d{1,2}[/\-]\d{1,2}[/\-]\d{4}(?!\d)"),
        # D Month YYYY or DD Month YYYY
        re.compile(
            r"(?<!\d)\d{1,2}\s+" + _MONTHS + r"\s+\d{4}(?!\d)",
            re.IGNORECASE,
        ),
        # Month D, YYYY
        re.compile(
            _MONTHS + r"\s+\d{1,2},?\s+\d{4}",
            re.IGNORECASE,
        ),
    ]

    def detect(self, text: str) -> list[PIIMatch]:
        seen: set[tuple[int, int]] = set()
        matches: list[PIIMatch] = []
        for pat in self._PATTERNS:
            for m in pat.finditer(text):
                span = (m.start(), m.end())
                if span not in seen:
                    seen.add(span)
                    # Lower confidence because many dates in this doc are not DOBs.
                    matches.append(PIIMatch(
                        pii_type=self.PII_TYPE,
                        text=m.group(0),
                        start=m.start(),
                        end=m.end(),
                        confidence=0.6,
                    ))
        return matches
