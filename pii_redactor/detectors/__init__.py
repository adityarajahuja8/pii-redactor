"""
Detector registry — the SINGLE place to register all PII detectors.

To add a new PII type:
  1. Create a subclass of BasePIIDetector (in regex_detectors.py or ner_detectors.py).
  2. Import it below and add an instance to DETECTOR_REGISTRY.
  That is ALL you need to do.
"""

from .regex_detectors import (
    EmailDetector,
    PhoneDetector,
    PANDetector,
    CINDetector,
    AadhaarDetector,
    SSNDetector,
    CreditCardDetector,
    IPAddressDetector,
    DOBDetector,
)
from .ner_detectors import PersonNameDetector, AddressDetector

# ============================================================
# DETECTOR_REGISTRY — add/remove detectors here only
# ============================================================
DETECTOR_REGISTRY: list = [
    EmailDetector(),
    PhoneDetector(),
    PANDetector(),
    CINDetector(),
    AadhaarDetector(),
    SSNDetector(),
    CreditCardDetector(),
    IPAddressDetector(),
    DOBDetector(),
    PersonNameDetector(),
    AddressDetector(),
]

__all__ = ["DETECTOR_REGISTRY"]
