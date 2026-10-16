"""Unit tests for every decision rule in rules.py."""
from conftest import intake

from rules import DISCLAIMER, evaluate


def keys(res):
    return [o["drug_key"] for o in res["options"]]


# ---- Rule 1: red-flag triage ------------------------------------------------
def test_rule1_missing_complaint_asks(kb):
    r = evaluate({}, kb)
    assert r["action"] == "ASK" and r["missing"] == ["complaint"]


def test_rule1_emergency_flag(patient, kb):
    p = patient(); p["red_flags"]["thunderclap"] = True
    r = evaluate(p, kb)
    assert r["action"] == "EMERGENCY" and r["options"] == []


def test_rule1_urgent_flag(patient, kb):
    p = patient(); p["red_flags"]["new_over_50"] = True
    assert evaluate(p, kb)["action"] == "URGENT_DOCTOR"


def test_rule1_yes_escalates_even_if_others_unanswered(patient, kb):
    p = patient(); p["red_flags"] = {"head_injury": True}
    assert evaluate(p, kb)["action"] == "EMERGENCY"


def test_rule1_unanswered_flag_asks(patient, kb):
    p = patient(); p["red_flags"]["thunderclap"] = None
    r = evaluate(p, kb)
    assert r["action"] == "ASK" and "red_flags.thunderclap" in r["missing"]


def test_rule1_general_flag_applies_to_all_complaints(patient, kb):
    for c in kb.complaints:
        p = patient(c); p["red_flags"]["chest_pain"] = True
        assert evaluate(p, kb)["action"] == "EMERGENCY"


# ---- Rule 2: demographics and scope ----------------------------------------
def test_rule2_missing_weight_asks(patient, kb):
    r = evaluate(patient(weight_kg=None), kb)
    assert r["action"] == "ASK" and r["missing"] == ["weight_kg"] and r["rule"] == 2


def test_rule2_male_needs_no_pregnancy_answer(patient, kb):
    assert evaluate(patient(sex="male", pregnant=None, breastfeeding=None), kb)["action"] == "RECOMMEND"


def test_rule2_female_pregnancy_unknown_asks(patient, kb):
    assert evaluate(patient(pregnant=None), kb)["action"] == "ASK"


def test_rule2_child_referred(patient, kb):
    r = evaluate(patient(age=17), kb)
    assert r["action"] == "REFER" and r["scope"] == "out_of_scope"


def test_rule2_pregnant_and_breastfeeding_referred(patient, kb):
    assert evaluate(patient("fever", pregnant=True), kb)["action"] == "REFER"
    assert evaluate(patient("fever", breastfeeding=True), kb)["action"] == "REFER"


# ---- Rule 3: contraindications ---------------------------------------------
def test_rule3_missing_history_asks(patient, kb):
    r = evaluate(patient(allergies=None), kb)
    assert r["action"] == "ASK" and "allergies" in r["missing"]


def test_rule3_ulcer_excludes_ibuprofen(patient, kb):
    r = evaluate(patient(conditions=["peptic_ulcer_or_gi_bleed"]), kb)
    assert keys(r) == ["paracetamol"] and r["excluded"][0]["drug"] == "ibuprofen"


def test_rule3_interacting_medicine_excludes(patient, kb):
    assert keys(evaluate(patient(current_meds=["anticoagulant"]), kb)) == ["paracetamol"]


def test_rule3_allergy_excludes(patient, kb):
    assert keys(evaluate(patient(allergies=["paracetamol"]), kb)) == ["ibuprofen"]


def test_rule3_age_limit_excludes(patient, kb):
    assert keys(evaluate(patient(age=65), kb)) == ["paracetamol"]


def test_rule3_all_excluded_refers(patient, kb):
    r = evaluate(patient(allergies=["paracetamol"], current_meds=["anticoagulant"]), kb)
    assert r["action"] == "REFER" and r["rule"] == 3


def test_rule3_kidney_liver_out_of_scope(patient, kb):
    assert evaluate(patient(conditions=["kidney_disease"]), kb)["scope"] == "out_of_scope"
    assert evaluate(patient(conditions=["liver_disease"]), kb)["scope"] == "out_of_scope"


def test_rule3_elderly_polypharmacy_out_of_scope(patient, kb):
    assert evaluate(patient(age=75, num_regular_meds=2), kb)["action"] == "REFER"
    assert evaluate(patient(age=75, num_regular_meds=1), kb)["action"] == "RECOMMEND"


# ---- Rule 4: 24-hour cap ----------------------------------------------------
def test_rule4_prior_intake_required(patient, kb):
    assert evaluate(patient(prior_intake=None), kb)["missing"] == ["prior_intake"]


def test_rule4_hours_required_when_dose_taken(patient, kb):
    assert evaluate(patient(prior_intake=intake("paracetamol", 500, None)), kb)["action"] == "ASK"


def test_rule4_cap_reached_refers(patient, kb):
    r = evaluate(patient(prior_intake=intake("paracetamol", 4000, 3)), kb)
    assert r["action"] == "REFER" and r["scope"] == "cap_reached"


def test_rule4_remaining_allowance_limits_dose(patient, kb):
    o = evaluate(patient(prior_intake=intake("paracetamol", 3500, 5)), kb)["options"][0]
    assert o["dose_max_mg"] == 500 and o["remaining_mg_24h"] == 500


def test_rule4_hidden_paracetamol_from_two_products_is_summed(patient, kb):
    p = patient(prior_intake=intake("paracetamol", 2000, 6) + intake("paracetamol", 2000, 2))
    assert evaluate(p, kb)["action"] == "REFER"


def test_rule4_alcohol_lowers_cap(patient, kb):
    o = evaluate(patient(alcohol_regular=True), kb)["options"][0]
    assert o["max_24h_mg"] == 3000


def test_rule4_low_weight_limits_single_and_daily_dose(patient, kb):
    o = evaluate(patient(weight_kg=45), kb)["options"][0]
    assert o["dose_max_mg"] == 500 and o["max_24h_mg"] == 2500


def test_rule4_interval_wait_time(patient, kb):
    o = evaluate(patient(prior_intake=intake("paracetamol", 1000, 1.5)), kb)["options"][0]
    assert o["next_dose_in_h"] == 2.5


def test_rule4_loperamide_first_then_subsequent(patient, kb):
    assert evaluate(patient("diarrhoea"), kb)["options"][0]["dose_max_mg"] == 4
    assert evaluate(patient("diarrhoea", prior_intake=intake("loperamide", 4, 1)), kb)["options"][0]["dose_max_mg"] == 2


# ---- Rule 5: duration -------------------------------------------------------
def test_rule5_duration_exceeded_refers(patient, kb):
    r = evaluate(patient(symptom_days=4), kb)
    assert r["action"] == "REFER" and r["rule"] == 5


def test_rule5_duration_at_limit_allowed(patient, kb):
    assert evaluate(patient(symptom_days=3), kb)["action"] == "RECOMMEND"


# ---- Rule 6: output content -------------------------------------------------
def test_rule6_every_option_has_required_fields(patient, kb):
    r = evaluate(patient(), kb)
    assert r["disclaimer"] == DISCLAIMER and r["stop_advice"]
    for o in r["options"]:
        for f in ("display_name", "strength_mg", "dose_text", "interval_text", "max_24h_mg",
                  "remaining_mg_24h", "warnings", "source"):
            assert o[f] not in (None, "", [])


def test_rule6_never_outputs_drug_outside_formulary(patient, kb):
    for c in kb.complaints:
        for o in evaluate(patient(c), kb)["options"]:
            assert o["drug_key"] in kb.drugs
            assert o["dose_max_mg"] <= kb.drugs[o["drug_key"]]["single_dose_max_mg"]
