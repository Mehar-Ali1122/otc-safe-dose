"""
incident_log.py - Append-only CSV log for validator blocks and user reports.

Only the structured, non-identifying intake fields are stored (no names,
phone numbers or free-text identity data are collected by the app).
Set MEDBOT_INCIDENT_LOG to change the file location.
"""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from rules import APP_VERSION, BASE_DIR

FIELDS = ["timestamp_utc", "kind", "failed_checks", "inputs_json",
          "proposed_output_json", "comment", "app_version"]


def log_path(path: str | os.PathLike | None = None) -> Path:
    return Path(path or os.environ.get("MEDBOT_INCIDENT_LOG") or BASE_DIR / "incidents.csv")


def log_incident(kind: str, patient: dict, proposed: dict, failures: list | None = None,
                 comment: str = "", path: str | os.PathLike | None = None) -> Path:
    """kind: 'validator_block' or 'user_report'."""
    p = log_path(path)
    new = not p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": kind,
        "failed_checks": "; ".join(f"{f['check']}: {f['detail']}" for f in failures or []),
        "inputs_json": json.dumps(patient, sort_keys=True, default=str),
        "proposed_output_json": json.dumps(proposed, sort_keys=True, default=str),
        "comment": (comment or "")[:2000],
        "app_version": APP_VERSION,
    }
    with p.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
    return p
