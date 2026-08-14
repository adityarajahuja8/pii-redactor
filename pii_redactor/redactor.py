"""
PII Redactor — Main Entry Point
=================================
Usage:
  python -m pii_redactor.redactor <input.docx> [--output <output.docx>]
                                   [--evaluate] [--annotation-file <path>]
                                   [--log-level DEBUG|INFO|WARNING]

Steps performed:
  1. Load the document.
  2. Run all detectors from DETECTOR_REGISTRY.
  3. Replace each PII with a consistent fake via FakeValueMapper.
  4. Save the redacted .docx.
  5. (Optional) Generate/evaluate annotation file.
"""

from __future__ import annotations
import argparse
import json
import logging
import sys
from pathlib import Path

from .document_processor import process_document
from .faker_mapper import FakeValueMapper
from .evaluator import (
    generate_annotation_file,
    evaluate_from_annotations,
    print_evaluation_report,
)


def main():
    parser = argparse.ArgumentParser(
        description="Redact PII from a .docx file using regex + spaCy NER."
    )
    parser.add_argument("input", help="Path to the input .docx file")
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Path for the redacted output .docx (default: <input>_redacted.docx)",
    )
    parser.add_argument(
        "--evaluate", "-e",
        action="store_true",
        help="Generate/re-evaluate annotation file and print metrics",
    )
    parser.add_argument(
        "--annotation-file", "-a",
        default=None,
        help="Path to annotation JSON (default: <input>_annotations.json)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    parser.add_argument(
        "--mapping-output", "-m",
        default=None,
        help="Path to save the PII mapping table as JSON (optional)",
    )
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("pii_redactor")

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)

    output_path = Path(args.output) if args.output else (
        input_path.parent / (input_path.stem + "_redacted.docx")
    )
    annotation_path = Path(args.annotation_file) if args.annotation_file else (
        input_path.parent / (input_path.stem + "_annotations.json")
    )

    # --- Step 1: Redact ---
    logger.info(f"Input:  {input_path}")
    logger.info(f"Output: {output_path}")
    mapper = FakeValueMapper()
    all_matches = process_document(str(input_path), str(output_path), mapper)

    # Summary by type
    from collections import Counter
    type_counts = Counter(m.pii_type for m in all_matches)
    logger.info("\nDetection summary:")
    for ptype, count in sorted(type_counts.items()):
        logger.info(f"  {ptype:<20} {count:>5} instances")
    logger.info(f"  {'TOTAL':<20} {sum(type_counts.values()):>5} instances")

    # --- Step 2: Save mapping table ---
    if args.mapping_output:
        mapping = mapper.get_mapping_table()
        with open(args.mapping_output, "w", encoding="utf-8") as f:
            json.dump(mapping, f, indent=2, ensure_ascii=False)
        logger.info(f"Mapping table saved to: {args.mapping_output}")

    # --- Step 3: Evaluate (optional) ---
    if args.evaluate:
        if not annotation_path.exists():
            logger.info(f"Generating annotation file: {annotation_path}")
            generate_annotation_file(
                str(input_path), str(annotation_path),
                max_paragraphs=100, max_tables=5
            )
            logger.info(
                "Annotation file generated. Review it for FP/FN corrections,\n"
                "then re-run with --evaluate to compute final metrics."
            )
        else:
            logger.info(f"Evaluating from: {annotation_path}")
            results = evaluate_from_annotations(str(annotation_path))
            print_evaluation_report(results)

            report_path = input_path.parent / (input_path.stem + "_eval_report.json")
            with open(report_path, "w") as f:
                json.dump(results, f, indent=2)
            logger.info(f"Evaluation report saved to: {report_path}")

    logger.info("Done.")


if __name__ == "__main__":
    main()
