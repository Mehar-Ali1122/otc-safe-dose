"""
rules.py - Deterministic decision engine for the OTC Safe-Dose Assistant.

The engine never invents drugs or doses. Every drug name, strength, dose,
interval and 24-hour maximum is read from formulary.json; every red-flag
question and self-care duration limit is read from triage.json.

Decision rules run strictly in order and stop at the first exit:
    Rule 1  Red-flag triage           -> EMERGENCY / URGENT_DOCTOR / ASK
    Rule 2  Demographics and scope    -> ASK / REFER
    Rule 3  Contraindications         -> ASK / REFER
    Rule 4  24-hour cap and interval  -> ASK / REFER
    Rule 5  Self-care duration limit  -> REFER
    Rule 6  Build the recommendation  -> RECOMMEND

A patient is a plain dict. A value of None means "not answered yet";
an empty list means "answered: none".
"""
from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

APP_VERSION = "0.1.0"
BASE_DIR = Path(__file__).resolve().parent
DISCLAIMER = ("This is general information, not a diagnosis. "
              "Confirm with a pharmacist or doctor.")

ACTIONS = ("ASK", "EMERGENCY", "URGENT_DOCTOR", "REFER", "RECOMMEND")

# Option lists shown in the GUI. Keys are referenced by formulary.json.
CONDITION_OPTIONS = {
    "kidney_disease": "Long-term kidney disease",
    "liver_disease": "Long-term liver disease (e.g., cirrhosis, hepatitis)",
    "peptic_ulcer_or_gi_bleed": "Stomach ulcer, or stomach/bowel bleeding (ever)",
    "asthma_nsaid_sensitive": "Asthma that gets worse with aspirin or ibuprofen",
    "heart_failure": "Heart failure",
    "high_blood_pressure": "High blood pressure",
    "inflammatory_bowel_disease": "Crohn's disease or ulcerative colitis",
}
MED_CATEGORY_OPTIONS = {
    "anticoagulant": "Blood thinner (e.g., warfarin, rivaroxaban, apixaban)",
    "antiplatelet": "Antiplatelet (e.g., low-dose aspirin, clopidogrel)",
    "nsaid": "Another anti-inflammatory painkiller (e.g., diclofenac, naproxen, mefenamic acid)",
    "oral_corticosteroid": "Steroid tablets (e.g., prednisolone)",
    "ssri_snri": "Antidepressant SSRI/SNRI (e.g., sertraline, fluoxetine)",
    "lithium": "Lithium",
    "methotrexate": "Methotrexate",
    "bp_diuretic_acei_arb": "Blood-pressure tablets: ACE inhibitor, ARB or diuretic",
    "other": "Other regular medicine",
}
ALLERGY_OPTIONS = {
    "paracetamol": "Paracetamol",
    "ibuprofen": "Ibuprofen",
    "nsaid_aspirin": "Aspirin or other NSAIDs",
    "cetirizine_hydroxyzine": "Cetirizine or hydroxyzine",
    "loperamide": "Loperamide",
    "calcium_carbonate": "Calcium carbonate / antacids",
}

TRIAGE_FIELDS = ("complaint", "symptom_days")
PROFILE_FIELDS = ("age", "sex", "weight_kg", "pregnant", "breastfeeding")
HISTORY_FIELDS = ("conditions", "current_meds", "allergies",
                  "alcohol_regular", "num_regular_meds")
SEXES = ("female", "male", "other")


# --------------------------------------------------------------------------
# Knowledge base
# --------------------------------------------------------------------------
def _load(name: str) -> dict:
    with open(BASE_DIR / name, encoding="utf-8") as fh:
        return json.load(fh)


class Knowledge:
    """Read-only access to formulary.json and triage.json."""

    def __init__(self, formulary: dict | None = None, triage: dict | None = None):
        self.formulary = formulary if formulary is not None else _load("formulary.json")
        self.triage = triage if triage is not None else _load("triage.json")

    @property
    def drugs(self) -> dict:
        return self.formulary["drugs"]

    @property
    def complaints(self) -> dict:
        return self.triage["complaints"]

    @property
    def emergency_number(self) -> str:
        return os.environ.get("MEDBOT_EMERGENCY_NUMBER") or self.triage["emergency_number"]

    @property
    def verification_date(self) -> str | None:
        return self.formulary["_meta"].get("formulary_verification_date")

    def red_flags_for(self, complaint: str) -> list[dict]:
        return list(self.triage["general_red_flags"]) + list(self.complaints[complaint]["red_flags"])

    def candidates_for(self, complaint: str) -> list[str]:
        return list(self.complaints[complaint]["candidates"])

    def max_self_care_days(self, complaint: str) -> int:
        return self.complaints[complaint]["max_self_care_days"]


@lru_cache(maxsize=1)
def default_knowledge() -> Knowledge:
    return Knowledge()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def stage_of_field(field: str) -> str:
    """Map a missing field to the GUI stage that collects it."""
    if field in TRIAGE_FIELDS or field.startswith("red_flags."):
        return "triage"
    if field in PROFILE_FIELDS:
        return "profile"
    return "safety"


def floor_to(value: float, step: int) -> int:
    """Round down to a whole number of tablets/capsules."""
    return int(math.floor(value / step + 1e-9) * step)


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and not math.isnan(x)


def effective_limits(drug: dict, patient: dict) -> dict:
    """Single-dose and 24-hour limits after patient-specific reductions."""
    s = drug["strength_mg"]
    single_min = drug["single_dose_min_mg"]
    single_max = drug["single_dose_max_mg"]
    max_24h = drug["max_24h_mg"]
    notes: list[str] = []
    red = drug.get("reduced_limits")
    if red:
        weight = patient.get("weight_kg")
        low_weight = _is_num(weight) and weight < red.get("low_weight_threshold_kg", 0)
        triggers = []
        if patient.get("alcohol_regular") and "alcohol_regular" in red["applies_if"]:
            triggers.append("regular alcohol use")
        if low_weight and "low_weight" in red["applies_if"]:
            triggers.append(f"body weight under {red['low_weight_threshold_kg']} kg")
        if triggers:
            max_24h = min(max_24h, red["max_24h_mg"])
            notes.append("Lower daily maximum because of " + " and ".join(triggers) + ".")
        if low_weight:
            single_max = min(single_max, floor_to(red["per_kg_single_mg"] * weight, s))
            max_24h = min(max_24h, floor_to(red["per_kg_24h_mg"] * weight, s))
            notes.append("Dose limited by body weight.")
    return {"single_min": single_min, "single_max": single_max,
            "max_24h": max_24h, "notes": notes}


def contraindication_reasons(drug: dict, patient: dict) -> list[str]:
    ci = drug.get("contraindications") or {}
    reasons = []
    for c in patient.get("conditions") or []:
        if c in ci.get("conditions", []):
            reasons.append(f"Not suitable with: {CONDITION_OPTIONS.get(c, c)}")
    for m in patient.get("current_meds") or []:
        if m in ci.get("med_categories", []):
            reasons.append(f"Interacts with: {MED_CATEGORY_OPTIONS.get(m, m)}")
    for a in patient.get("allergies") or []:
        if a in ci.get("allergies", []):
            reasons.append(f"Allergy: {ALLERGY_OPTIONS.get(a, a)}")
    limit_age = drug.get("avoid_if_age_gte")
    if limit_age is not None and _is_num(patient.get("age")) and patient["age"] >= limit_age:
        reasons.append(f"Not for self-care at age {limit_age}+ without professional advice")
    return reasons


def prior_intake_for(patient: dict, ingredient: str) -> tuple[float, float | None]:
    """Total mg taken in the last 24 h and hours since the most recent dose."""
    entries = [e for e in (patient.get("prior_intake") or [])
               if e.get("ingredient") == ingredient and (e.get("total_mg_24h") or 0) > 0]
    total = sum(e["total_mg_24h"] for e in entries)
    hours = [e["hours_since_last"] for e in entries if _is_num(e.get("hours_since_last"))]
    return total, (min(hours) if hours else None)


def scope_reasons_demographic(patient: dict) -> list[str]:
    r = []
    if patient["age"] < 18:
        r.append("This tool is for adults (18+) only. Children's doses depend on weight and product - "
                 "please ask a pharmacist or doctor.")
    if patient.get("pregnant"):
        r.append("Medicines in pregnancy need professional advice.")
    if patient.get("breastfeeding"):
        r.append("Medicines while breastfeeding need professional advice.")
    return r


def scope_reasons_history(patient: dict) -> list[str]:
    r = []
    conds = set(patient.get("conditions") or [])
    if "kidney_disease" in conds:
        r.append("Long-term kidney disease changes which medicines and doses are safe.")
    if "liver_disease" in conds:
        r.append("Long-term liver disease changes which medicines and doses are safe.")
    if patient["age"] >= 75 and (patient.get("num_regular_meds") or 0) >= 2:
        r.append("At 75+ with several regular medicines, a pharmacist should review interactions.")
    return r


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------
def _new_result(kb: Knowledge) -> dict:
    return {"action": None, "rule": None, "reasons": [], "missing": [],
            "triggered_flags": [], "options": [], "excluded": [],
            "stop_advice": None, "disclaimer": DISCLAIMER,
            "emergency_number": kb.emergency_number}


def _finish(res: dict, action: str, rule: int, **kw) -> dict:
    res["action"] = action
    res["rule"] = rule
    for k, v in kw.items():
        res[k] = v
    return res


def evaluate(patient: dict, kb: Knowledge | None = None) -> dict:
    """Run Rules 1-6 in order; return a result dict."""
    kb = kb or default_knowledge()
    res = _new_result(kb)

    # ---- Rule 1: red-flag triage -------------------------------------------
    complaint = patient.get("complaint")
    if complaint not in kb.complaints:
        return _finish(res, "ASK", 1, missing=["complaint"])
    flags = kb.red_flags_for(complaint)
    answers = patient.get("red_flags") or {}
    triggered = [f for f in flags if answers.get(f["id"]) is True]
    if triggered:  # any "yes" escalates immediately, even if others unanswered
        action = ("EMERGENCY" if any(f["severity"] == "emergency" for f in triggered)
                  else "URGENT_DOCTOR")
        return _finish(res, action, 1, triggered_flags=triggered,
                       reasons=["Red-flag symptom reported - no medicine is suggested."])
    missing = [f"red_flags.{f['id']}" for f in flags if answers.get(f["id"]) not in (True, False)]
    days = patient.get("symptom_days")
    if not _is_num(days) or days < 0:
        missing.append("symptom_days")
    if missing:
        return _finish(res, "ASK", 1, missing=missing)

    # ---- Rule 2: demographics and scope ------------------------------------
    missing = [f for f in ("age", "weight_kg") if not _is_num(patient.get(f))]
    if patient.get("sex") not in SEXES:
        missing.append("sex")
    elif patient["sex"] != "male":
        missing += [f for f in ("pregnant", "breastfeeding")
                    if not isinstance(patient.get(f), bool)]
    if missing:
        return _finish(res, "ASK", 2, missing=missing)
    out = scope_reasons_demographic(patient)
    if out:
        return _finish(res, "REFER", 2, reasons=out, scope="out_of_scope")

    # ---- Rule 3: contraindications -----------------------------------------
    missing = [f for f in HISTORY_FIELDS if patient.get(f) is None]
    if missing:
        return _finish(res, "ASK", 3, missing=missing)
    out = scope_reasons_history(patient)
    if out:
        return _finish(res, "REFER", 3, reasons=out, scope="out_of_scope")
    eligible = []
    for key in kb.candidates_for(complaint):
        drug = kb.drugs[key]
        why = contraindication_reasons(drug, patient)
        if why:
            res["excluded"].append({"drug": key, "display_name": drug["display_name"], "reasons": why})
        else:
            eligible.append(key)
    if not eligible:
        return _finish(res, "REFER", 3, reasons=[
            "None of the first-line medicines for this problem are suitable for you. "
            "A pharmacist or doctor can suggest a safe alternative."])

    # ---- Rule 4: 24-hour cap and interval ----------------------------------
    intake = patient.get("prior_intake")
    if intake is None:
        return _finish(res, "ASK", 4, missing=["prior_intake"])
    if any((e.get("total_mg_24h") or 0) > 0 and not _is_num(e.get("hours_since_last"))
           for e in intake):
        return _finish(res, "ASK", 4, missing=["prior_intake"])
    plans = []
    for key in eligible:
        drug = kb.drugs[key]
        lim = effective_limits(drug, patient)
        if lim["single_max"] < lim["single_min"]:
            res["excluded"].append({"drug": key, "display_name": drug["display_name"],
                                    "reasons": ["Body weight too low for the standard tablet strength"]})
            continue
        prior, hrs = prior_intake_for(patient, drug["ingredient"])
        remaining = lim["max_24h"] - prior
        if remaining < lim["single_min"]:
            return _finish(res, "REFER", 4, scope="cap_reached", reasons=[
                f"You have already taken {prior:g} mg of {drug['display_name']} in the last 24 hours "
                f"(maximum for you: {lim['max_24h']} mg). Do NOT take any more. "
                "Speak to a pharmacist; if you took more than the maximum, get medical help now."])
        plans.append((key, drug, lim, prior, hrs, remaining))
    if not plans:
        return _finish(res, "REFER", 4, reasons=["No standard dose is suitable - ask a pharmacist."])

    # ---- Rule 5: self-care duration limit ----------------------------------
    stop_advice = kb.complaints[complaint]["stop_advice"]
    max_days = kb.max_self_care_days(complaint)
    if days > max_days:
        return _finish(res, "REFER", 5, stop_advice=stop_advice, reasons=[
            f"You have had this for {days:g} days; self-treatment is only advised for up to "
            f"{max_days} days. Please see a doctor."])

    # ---- Rule 6: build the recommendation ----------------------------------
    options = [_build_option(key, drug, lim, prior, hrs, remaining)
               for key, drug, lim, prior, hrs, remaining in plans]
    return _finish(res, "RECOMMEND", 6, options=options, stop_advice=stop_advice)


def _count(mg: int, strength: int, unit: str) -> str:
    n = mg // strength
    return f"{n} {unit}{'s' if n != 1 else ''}"


def _build_option(key, drug, lim, prior, hrs, remaining) -> dict:
    s = drug["strength_mg"]
    cap_now = floor_to(remaining, s)
    if "first_dose_mg" in drug:  # e.g., loperamide: 4 mg first, then 2 mg
        dose = drug["first_dose_mg"] if prior == 0 else drug["subsequent_dose_mg"]
        dose = min(dose, lim["single_max"], cap_now)
        dmin = dmax = dose
    else:
        dmin = lim["single_min"]
        dmax = min(lim["single_max"], cap_now)
    unit = drug["unit"]
    if dmin == dmax:
        dose_text = f"{dmin} mg ({_count(dmin, s, unit)})"
    else:
        dose_text = f"{dmin}-{dmax} mg ({dmin // s}-{dmax // s} {unit}s)"
    next_in = 0.0
    if prior > 0 and hrs is not None:
        next_in = max(0.0, drug["min_interval_h"] - hrs)
    return {
        "drug_key": key,
        "display_name": drug["display_name"],
        "strength_mg": s,
        "form": drug["form"],
        "dose_min_mg": dmin,
        "dose_max_mg": dmax,
        "dose_text": dose_text,
        "interval_text": drug["interval_text"],
        "min_interval_h": drug["min_interval_h"],
        "max_24h_mg": lim["max_24h"],
        "prior_mg_24h": prior,
        "remaining_mg_24h": lim["max_24h"] - prior,
        "next_dose_in_h": next_in,
        "administration": drug["administration"],
        "warnings": list(drug["warnings"]),
        "interactions": list(drug.get("interactions", [])),
        "limit_notes": lim["notes"],
        "source": drug["source"],
        "verification_status": drug["status"],
    }
