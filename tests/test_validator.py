"""Unit tests for every validator check, the red-alarm pipeline and the incident log."""
import copy
import csv

import pytest
from conftest import intake

from pipeline import run_pipeline
from rules import evaluate
from validator import validate


def checks(p, r, kb):
    return {f["check"] for f in validate(p, r, kb)}


@pytest.fixture
def good(patient, kb):
    p = patient()
    return p, evaluate(p, kb)


def test_clean_recommendation_passes(good, kb):
    p, r = good
    assert validate(p, r, kb) == []


def test_V0_unknown_action(good, kb):
    p, r = good; r["action"] = "MAYBE"
    assert "V0_action" in checks(p, r, kb)


def test_V1_red_flag_not_escalated(good, kb):
    p, r = good; p["red_flags"]["thunderclap"] = True
    assert "V1_red_flag" in checks(p, r, kb)


def test_V1_triage_incomplete(good, kb):
    p, r = good; p["red_flags"]["thunderclap"] = None
    assert "V1_red_flag" in checks(p, r, kb)


def test_V2_options_on_refer(good, kb):
    p, r = good; r["action"] = "REFER"
    assert "V2_options_on_non_recommend" in checks(p, r, kb)


@pytest.mark.parametrize("change", [{"age": 16}, {"pregnant": True}, {"breastfeeding": True},
                                    {"conditions": ["kidney_disease"]}, {"age": 80, "num_regular_meds": 3},
                                    {"pregnant": None}])
def test_V3_scope(good, kb, change):
    p, r = good; p.update(change)
    assert "V3_scope" in checks(p, r, kb)


def test_V4_duration(good, kb):
    p, r = good; p["symptom_days"] = 10
    assert "V4_duration" in checks(p, r, kb)


def test_V5_missing_field(good, kb):
    p, r = good; r["options"][0]["warnings"] = []
    assert "V5_fields" in checks(p, r, kb)


def test_V6_invented_drug(good, kb):
    p, r = good
    o = copy.deepcopy(r["options"][0]); o.update(drug_key="tramadol", display_name="Tramadol")
    r["options"].append(o)
    assert "V6_formulary" in checks(p, r, kb)


def test_V6_wrong_strength(good, kb):
    p, r = good; r["options"][0]["strength_mg"] = 650
    assert "V6_formulary" in checks(p, r, kb)


def test_V7_dose_sanity(good, kb):
    p, r = good; r["options"][0]["dose_min_mg"] = 750
    assert "V7_dose_sanity" in checks(p, r, kb)


def test_V8_single_dose(good, kb):
    p, r = good; r["options"][0]["dose_max_mg"] = 1500
    assert "V8_single_dose" in checks(p, r, kb)


def test_V8_low_weight_single_dose(patient, kb):
    p = patient(); r = evaluate(p, kb)
    p["weight_kg"] = 45  # engine output computed for 65 kg -> 1000 mg now too high
    assert "V8_single_dose" in checks(p, r, kb)


def test_V9_24h_cap(patient, kb):
    p = patient(); r = evaluate(p, kb)
    p["prior_intake"] = intake("paracetamol", 3500, 6)
    assert "V9_24h_cap" in checks(p, r, kb)


def test_V10_interval(patient, kb):
    p = patient(prior_intake=intake("paracetamol", 1000, 1)); r = evaluate(p, kb)
    r["options"][0]["next_dose_in_h"] = 0
    assert "V10_interval" in checks(p, r, kb)


def test_V11_contraindication(good, kb):
    p, r = good; p["current_meds"] = ["anticoagulant"]
    assert "V11_contraindication" in checks(p, r, kb)


def test_V11_age_limit(good, kb):
    p, r = good; p["age"] = 70
    assert "V11_contraindication" in checks(p, r, kb)


def test_V12_displayed_cap(good, kb):
    p, r = good; r["options"][0]["max_24h_mg"] = 6000
    assert "V12_display" in checks(p, r, kb)


def test_V13_disclaimer(good, kb):
    p, r = good; r["disclaimer"] = "Take as needed."
    assert "V13_disclaimer" in checks(p, r, kb)


def test_pipeline_blocks_and_logs(patient, kb, tmp_path):
    def faulty_engine(p, k):
        r = evaluate(p, k); r["options"][0]["dose_max_mg"] = 3000
        return r
    log = tmp_path / "incidents.csv"
    out = run_pipeline(patient(), kb, log=True, log_file=log, engine=faulty_engine)
    assert out["action"] == "BLOCKED" and out["options"] == []
    rows = list(csv.DictReader(log.open()))
    assert rows[0]["kind"] == "validator_block" and "V8_single_dose" in rows[0]["failed_checks"]


def test_pipeline_passes_clean_output(patient, kb):
    assert run_pipeline(patient(), kb)["validator"] == "passed"
