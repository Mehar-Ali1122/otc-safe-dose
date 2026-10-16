"""
validator.py - Independent safety validator (defence in depth).

Runs AFTER the rules engine and BEFORE anything is shown to the user.
It deliberately re-implements the safety arithmetic instead of calling the
engine's helper functions, so that a bug in rules.py is not silently
repeated here. It only reads data (formulary/triage) from the Knowledge object.

Checks
  V0  action is a known value
  V1  red flags: any "yes" must be escalated; a recommendation needs a
      complete and fully negative triage
  V2  no options attached to a non-recommendation
  V3  patient in scope (adult, not pregnant/breastfeeding, no kidney/liver
      disease, not 75+ with >= 2 regular medicines)
  V4  symptom duration within the self-care limit
  V5  every option has all required display fields
  V6  drug exists in the formulary, is a candidate for this complaint, and
      its name/strength match the formulary (no invented drugs)
  V7  dose sanity: 0 < min <= max, whole tablets
  V8  dose <= single-dose maximum (patient-specific)
  V9  prior intake + dose <= 24-hour maximum (patient-specific)
  V10 minimum interval respected
  V11 no contraindicated drug (condition, interacting medicine, allergy, age)
  V12 displayed 24-h maximum and remaining allowance are correct
  V13 disclaimer present
"""
from __future__ import annotations

from rules import ACTIONS, DISCLAIMER, Knowledge, default_knowledge

ESCALATE = {"EMERGENCY", "URGENT_DOCTOR"}
REQUIRED_OPTION_FIELDS = (
    "drug_key", "display_name", "strength_mg", "form", "dose_min_mg", "dose_max_mg",
    "dose_text", "interval_text", "min_interval_h", "max_24h_mg", "prior_mg_24h",
    "remaining_mg_24h", "next_dose_in_h", "warnings", "source", "verification_status",
)


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def patient_limits(drug: dict, p: dict) -> tuple[float, float]:
    """Independent computation of (single-dose max, 24-h max) in mg."""
    s = drug["strength_mg"]
    single_max = drug["single_dose_max_mg"]
    max24 = drug["max_24h_mg"]
    red = drug.get("reduced_limits") or {}
    if red:
        w = p.get("weight_kg")
        applies = red.get("applies_if", [])
        low = _num(w) and w < red.get("low_weight_threshold_kg", 0)
        if (p.get("alcohol_regular") and "alcohol_regular" in applies) or (low and "low_weight" in applies):
            max24 = min(max24, red["max_24h_mg"])
        if low:
            single_max = min(single_max, (red["per_kg_single_mg"] * w + 1e-9) // s * s)
            max24 = min(max24, (red["per_kg_24h_mg"] * w + 1e-9) // s * s)
    return single_max, max24


def _prior(p: dict, ingredient: str) -> tuple[float, float | None]:
    total, last = 0.0, None
    for e in p.get("prior_intake") or []:
        if e.get("ingredient") != ingredient:
            continue
        mg = e.get("total_mg_24h") or 0
        if mg > 0:
            total += mg
            h = e.get("hours_since_last")
            if _num(h):
                last = h if last is None else min(last, h)
    return total, last


def validate(patient: dict, result: dict, kb: Knowledge | None = None) -> list[dict]:
    """Return a list of failures; an empty list means the output is safe to show."""
    kb = kb or default_knowledge()
    fails: list[dict] = []

    def fail(check: str, detail: str):
        fails.append({"check": check, "detail": detail})

    action = result.get("action")
    if action not in ACTIONS:
        fail("V0_action", f"Unknown action {action!r}")
        return fails

    complaint = patient.get("complaint")
    answers = patient.get("red_flags") or {}
    flags = kb.red_flags_for(complaint) if complaint in kb.complaints else []
    positive = [f["id"] for f in flags if answers.get(f["id"]) is True]
    if positive and action not in ESCALATE:
        fail("V1_red_flag", f"Red flag(s) {positive} reported but action is {action}")

    if action != "RECOMMEND":
        if result.get("options"):
            fail("V2_options_on_non_recommend", "Medicine options attached to a non-recommendation")
        return fails

    # ---- patient-level checks for a recommendation -------------------------
    if complaint not in kb.complaints:
        fail("V1_red_flag", "Recommendation without a known complaint / triage")
        return fails
    incomplete = [f["id"] for f in flags if answers.get(f["id"]) is not False]
    if incomplete:
        fail("V1_red_flag", f"Triage not completed/negative for: {incomplete}")

    age = patient.get("age")
    conds = set(patient.get("conditions") or [])
    if not _num(age) or age < 18:
        fail("V3_scope", "Patient is not a confirmed adult")
    if patient.get("pregnant") is True or patient.get("breastfeeding") is True:
        fail("V3_scope", "Pregnant or breastfeeding")
    if patient.get("sex") != "male" and (patient.get("pregnant") is None or patient.get("breastfeeding") is None):
        fail("V3_scope", "Pregnancy/breastfeeding status unknown")
    if conds & {"kidney_disease", "liver_disease"}:
        fail("V3_scope", "Chronic kidney/liver disease")
    if _num(age) and age >= 75 and (patient.get("num_regular_meds") or 0) >= 2:
        fail("V3_scope", "Age 75+ with multiple regular medicines")

    days = patient.get("symptom_days")
    if not _num(days) or days > kb.max_self_care_days(complaint):
        fail("V4_duration", f"Symptom duration {days} exceeds self-care limit")

    if result.get("disclaimer") != DISCLAIMER:
        fail("V13_disclaimer", "Mandatory disclaimer missing or altered")

    options = result.get("options") or []
    if not options:
        fail("V5_fields", "Recommendation contains no options")

    meds = set(patient.get("current_meds") or [])
    allergies = set(patient.get("allergies") or [])
    for opt in options:
        miss = [f for f in REQUIRED_OPTION_FIELDS if opt.get(f) in (None, "", [])]
        if miss:
            fail("V5_fields", f"{opt.get('drug_key')}: missing {miss}")
            continue
        key = opt["drug_key"]
        drug = kb.drugs.get(key)
        if drug is None:
            fail("V6_formulary", f"Drug {key!r} is not in the formulary")
            continue
        if key not in kb.complaints[complaint]["candidates"] or complaint not in drug["indications"]:
            fail("V6_formulary", f"{key} is not a listed option for {complaint}")
        if opt["display_name"] != drug["display_name"] or opt["strength_mg"] != drug["strength_mg"]:
            fail("V6_formulary", f"{key}: name/strength differ from the formulary")

        s = drug["strength_mg"]
        dmin, dmax = opt["dose_min_mg"], opt["dose_max_mg"]
        if not (_num(dmin) and _num(dmax) and 0 < dmin <= dmax) or dmin % s or dmax % s:
            fail("V7_dose_sanity", f"{key}: invalid dose range {dmin}-{dmax} mg")
            continue

        single_max, max24 = patient_limits(drug, patient)
        if dmax > single_max:
            fail("V8_single_dose", f"{key}: {dmax} mg exceeds single-dose max {single_max:g} mg")
        prior, last = _prior(patient, drug["ingredient"])
        if prior + dmax > max24:
            fail("V9_24h_cap", f"{key}: {prior:g} + {dmax} mg exceeds 24-h max {max24:g} mg")
        if prior > 0:
            if last is None:
                fail("V10_interval", f"{key}: time of last dose unknown")
            elif last < drug["min_interval_h"] and opt["next_dose_in_h"] + 1e-6 < drug["min_interval_h"] - last:
                fail("V10_interval", f"{key}: minimum interval of {drug['min_interval_h']} h not respected")

        ci = drug.get("contraindications") or {}
        bad = (conds & set(ci.get("conditions", []))) | (meds & set(ci.get("med_categories", []))) \
            | (allergies & set(ci.get("allergies", [])))
        if bad:
            fail("V11_contraindication", f"{key}: contraindicated by {sorted(bad)}")
        if drug.get("avoid_if_age_gte") is not None and _num(age) and age >= drug["avoid_if_age_gte"]:
            fail("V11_contraindication", f"{key}: not for age {drug['avoid_if_age_gte']}+")

        if opt["max_24h_mg"] != max24 or abs(opt["remaining_mg_24h"] - (max24 - prior)) > 1e-6:
            fail("V12_display", f"{key}: displayed cap/remaining allowance is wrong")
    return fails
