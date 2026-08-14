"""
Base class for all PII detectors.

To add a new PII type:
  1. Create a subclass of BasePIIDetector (either here or in a new file).
  2. Implement `detect(text: str) -> list[PIIMatch]`.
  3. Register the class in detectors/__init__.py DETECTOR_REGISTRY.
  That is the ONLY place you need to edit — no monolithic regex blob.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import ClassVar


@dataclass
class PIIMatch:
    """A single PII hit inside a text string."""
    pii_type: str        # e.g. "PERSON", "PHONE", "EMAIL"
    text: str            # the raw matched text
    start: int           # char offset in the source string
    end: int             # char offset (exclusive) in the source string
    confidence: float = 1.0  # 0-1, detectors may set lower for NER hits


class BasePIIDetector:
    """
    All PII detectors must subclass this.
    Each detector is responsible for ONE logical PII category.
    """
    # Human-readable name, used for logging and the evaluation report.
    PII_TYPE: ClassVar[str] = "UNKNOWN"

    def detect(self, text: str) -> list[PIIMatch]:
        """Return all PII matches found in *text*."""
        raise NotImplementedError
