"""
pipeline.py - The only path from patient input to a displayable answer:

    rules.evaluate()  ->  validator.validate()  ->  result or RED-ALARM block
"""
from __future__ import annotations

from incident_log import log_incident
from rules import DISCLAIMER, Knowledge, default_knowledge, evaluate
from validator import validate

BLOCK_MESSAGE = "Safety check failed - recommendation withheld"
FALLBACK = ("Please speak to a pharmacist or doctor before taking any medicine. "
            "If you feel very unwell, call the emergency number.")


def run_pipeline(patient: dict, kb: Knowledge | None = None,
                 log: bool = False, log_file=None, engine=evaluate) -> dict:
    """Evaluate, validate and (if any check fails) block the output.

    `engine` is injectable so the evaluation harness can test the validator
    against deliberately faulty engine outputs.
    """
    kb = kb or default_knowledge()
    proposed = engine(patient, kb)
    failures = validate(patient, proposed, kb)
    if failures:
        if log:
            log_incident("validator_block", patient, proposed, failures, path=log_file)
        return {
            "action": "BLOCKED", "rule": "validator", "reasons": [BLOCK_MESSAGE, FALLBACK],
            "failures": failures, "proposed": proposed, "options": [], "missing": [],
            "triggered_flags": [], "excluded": [], "stop_advice": None,
            "disclaimer": DISCLAIMER, "emergency_number": kb.emergency_number,
        }
    proposed["validator"] = "passed"
    return proposed
