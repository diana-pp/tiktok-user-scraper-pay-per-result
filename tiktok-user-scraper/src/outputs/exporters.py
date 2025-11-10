import csv
import json
import logging
import os
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger("exporters")

def _ensure_dir(path: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)

def _normalize_record(record: Any) -> Dict[str, Any]:
    if isinstance(record, dict):
        return record
    if is_dataclass(record):
        return asdict(record)
    # Fallback: try to use __dict__
    if hasattr(record, "__dict__"):
        return dict(record.__dict__)
    raise TypeError(f"Unsupported record type: {type(record)!r}")

def export_to_json(records: Iterable[Any], output_path: str) -> None:
    _ensure_dir(output_path)
    normalized: List[Dict[str, Any]] = [_normalize_record(r) for r in records]

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)

    logger.info("Exported %d records to JSON at %s", len(normalized), output_path)

def export_to_csv(records: Iterable[Any], output_path: str) -> None:
    _ensure_dir(output_path)
    normalized: List[Dict[str, Any]] = [_normalize_record(r) for r in records]

    if not normalized:
        # Create an empty file with no rows but still valid CSV
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            f.write("")
        logger.info("No records to export. Created empty CSV at %s", output_path)
        return

    # Collect all fieldnames across records for a robust CSV header
    fieldnames: List[str] = []
    for rec in normalized:
        for key in rec.keys():
            if key not in fieldnames:
                fieldnames.append(key)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in normalized:
            writer.writerow(rec)

    logger.info("Exported %d records to CSV at %s", len(normalized), output_path)

def export_data(
    records: Iterable[Any],
    output_path: str,
    output_format: Optional[str] = None,
) -> None:
    """
    High-level export API.

    - If output_format is provided ("json" or "csv"), that takes priority.
    - Otherwise the file extension is inspected to decide the format.
    """
    if output_format is None:
        ext = os.path.splitext(output_path)[1].lower()
        if ext == ".csv":
            output_format = "csv"
        else:
            output_format = "json"

    output_format = output_format.lower()

    logger.debug(
        "Exporting data: format=%s, output_path=%s", output_format, output_path
    )

    if output_format == "json":
        export_to_json(records, output_path)
    elif output_format == "csv":
        export_to_csv(records, output_path)
    else:
        raise ValueError(f"Unsupported output format: {output_format}")