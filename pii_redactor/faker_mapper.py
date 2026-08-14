"""
Consistent Fake-Value Mapper
=============================
Guarantees that the same real PII value always maps to the same fake value
across the entire document (i.e., a lookup table / substitution cipher).

Uses the Faker library for realistic-looking replacements:
  - PERSON    -> Indian-sounding full name (Faker locale: en_IN)
  - EMAIL     -> email derived from the fake person name
  - PHONE     -> random valid-looking Indian mobile number
  - PAN       -> syntactically valid but fake PAN
  - CIN       -> syntactically valid but fake CIN
  - AADHAAR   -> fake 12-digit Aadhaar
  - SSN       -> fake US SSN format
  - CREDIT_CARD -> fake card number (Luhn-valid via Faker)
  - IP_ADDRESS -> random private IP
  - DATE_OF_BIRTH -> randomised date ±5 years of original (preserves rough era)
  - ADDRESS   -> fake Indian street address

All mappings are cached in self._cache so the second occurrence of the same
real value gets the same fake value — critical for consistency across tables
and paragraphs.
"""

from __future__ import annotations
import re
import random
import hashlib
from faker import Faker

fake = Faker("en_IN")
fake_us = Faker("en_US")  # for SSN / credit cards
random.seed(42)
Faker.seed(42)

# ---------------------------------------------------------------------------
# Individual faker functions per PII type
# ---------------------------------------------------------------------------

def _fake_person() -> str:
    return fake.name()


def _fake_email(real: str) -> str:
    """Generate a fake email that looks structurally similar to the original."""
    local, _, domain_part = real.partition("@")
    # Use a fake name as the local part
    name_part = fake.first_name().lower() + "." + fake.last_name().lower()
    return f"{name_part}@example.com"


def _fake_phone(real: str) -> str:
    """Generate a random fake Indian mobile number in the same rough format."""
    # Detect if original has +91 prefix
    stripped = re.sub(r"[\s\-]", "", real)
    if stripped.startswith("+91") or stripped.startswith("0091"):
        digits = "".join([str(random.randint(0, 9)) for _ in range(10)])
        # Make sure it starts with 6-9 (valid mobile)
        digits = str(random.randint(6, 9)) + digits[1:]
        return f"+91 {digits[:5]} {digits[5:]}"
    elif stripped.startswith("91") and len(stripped) == 12:
        digits = str(random.randint(6, 9)) + "".join([str(random.randint(0, 9)) for _ in range(9)])
        return f"91{digits}"
    else:
        digits = str(random.randint(6, 9)) + "".join([str(random.randint(0, 9)) for _ in range(9)])
        return digits


def _fake_pan() -> str:
    """Generate a syntactically valid (but fake) PAN."""
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    p = "".join(random.choices(letters, k=5))
    n = "".join([str(random.randint(0, 9)) for _ in range(4)])
    c = random.choice(letters)
    return f"{p}{n}{c}"


def _fake_cin(real: str) -> str:
    """Generate a fake CIN preserving the real entity type code (PLC/LLC etc.)."""
    m = re.search(r"(PLC|LLC|NPL|PTC|OPC|SGC|GAP)", real, re.IGNORECASE)
    entity_type = m.group(1).upper() if m else "PLC"
    prefix = random.choice(["L", "U"])
    nic = "".join([str(random.randint(0, 9)) for _ in range(5)])
    states = ["MH", "DL", "KA", "GJ", "TN", "AP", "WB", "RJ"]
    state = random.choice(states)
    year = str(random.randint(1990, 2015))
    suffix = "".join([str(random.randint(0, 9)) for _ in range(6)])
    return f"{prefix}{nic}{state}{year}{entity_type}{suffix}"


def _fake_aadhaar() -> str:
    digits = "".join([str(random.randint(0, 9)) for _ in range(12)])
    return f"{digits[:4]} {digits[4:8]} {digits[8:]}"


def _fake_ssn() -> str:
    return fake_us.ssn()


def _fake_credit_card() -> str:
    return fake_us.credit_card_number()


def _fake_ip(real: str) -> str:
    """Return a fake private IP address."""
    return f"10.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"


def _fake_dob(real: str) -> str:
    """
    Shift date by a random offset ±1000 days.
    If we can't parse it, return a generic fake date string.
    """
    try:
        from datetime import datetime, timedelta
        # Try common formats
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d %B %Y", "%B %d, %Y", "%B %d %Y"):
            try:
                dt = datetime.strptime(real.strip(), fmt)
                offset = random.randint(-1000, 1000)
                new_dt = dt + timedelta(days=offset)
                return new_dt.strftime(fmt)
            except ValueError:
                continue
    except Exception:
        pass
    return fake.date_of_birth(minimum_age=25, maximum_age=70).strftime("%d/%m/%Y")


def _fake_address() -> str:
    return fake.address().replace("\n", ", ")


# ---------------------------------------------------------------------------
# PII type -> faker function mapping
# ---------------------------------------------------------------------------
_FAKER_MAP: dict[str, callable] = {
    "PERSON": lambda real: _fake_person(),
    "EMAIL": _fake_email,
    "PHONE": _fake_phone,
    "PAN": lambda real: _fake_pan(),
    "CIN": _fake_cin,
    "AADHAAR": lambda real: _fake_aadhaar(),
    "SSN": lambda real: _fake_ssn(),
    "CREDIT_CARD": lambda real: _fake_credit_card(),
    "IP_ADDRESS": _fake_ip,
    "DATE_OF_BIRTH": _fake_dob,
    "ADDRESS": lambda real: _fake_address(),
}


# ---------------------------------------------------------------------------
# FakeValueMapper — the public interface
# ---------------------------------------------------------------------------

class FakeValueMapper:
    """
    Thread-safe (enough for single-threaded use) lookup table that ensures
    every unique real PII value maps to the same fake replacement.

    Usage:
        mapper = FakeValueMapper()
        fake_val = mapper.get_or_create("PERSON", "Rashi Patil")
        # -> "Anjali Sharma" (deterministic for this real value)
        fake_val2 = mapper.get_or_create("PERSON", "Rashi Patil")
        # -> "Anjali Sharma" (same fake, from cache)
    """

    def __init__(self):
        # {pii_type: {normalised_real_value: fake_value}}
        self._cache: dict[str, dict[str, str]] = {}

    def _normalise(self, text: str) -> str:
        """Collapse whitespace and lowercase for cache key."""
        return re.sub(r"\s+", " ", text).strip().lower()

    def get_or_create(self, pii_type: str, real_value: str) -> str:
        """Return the consistent fake for *real_value* of *pii_type*."""
        norm = self._normalise(real_value)
        type_cache = self._cache.setdefault(pii_type, {})
        if norm not in type_cache:
            faker_fn = _FAKER_MAP.get(pii_type)
            if faker_fn:
                # Seed Faker based on a hash of the real value for determinism
                seed = int(hashlib.md5(norm.encode()).hexdigest(), 16) % (2**32)
                Faker.seed(seed)
                random.seed(seed)
                fake_val = faker_fn(real_value)
            else:
                fake_val = f"[REDACTED_{pii_type}]"
            type_cache[norm] = fake_val
        return type_cache[norm]

    def get_mapping_table(self) -> dict[str, dict[str, str]]:
        """Return the full cache for logging/auditing."""
        return self._cache
