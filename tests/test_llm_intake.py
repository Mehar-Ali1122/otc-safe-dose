"""The optional LLM intake can only pre-fill whitelisted fields - never drugs or doses."""
from llm_intake import sanitize


def test_sanitize_drops_unknown_keys_and_doses(kb):
    raw = {"complaint": "headache", "age": 34, "sex": "female", "recommended_drug": "tramadol",
           "dose_mg": 100, "conditions": ["kidney_disease", "made_up"],
           "prior_intake": [{"ingredient": "paracetamol", "total_mg_24h": 1000, "hours_since_last": 3},
                            {"ingredient": "codeine", "total_mg_24h": 30}],
           "red_flags_positive": ["thunderclap", "not_a_flag"]}
    out = sanitize(raw, kb)
    assert "recommended_drug" not in out and "dose_mg" not in out
    assert out["conditions"] == ["kidney_disease"]
    assert [e["ingredient"] for e in out["prior_intake"]] == ["paracetamol"]
    assert out["red_flags_positive"] == ["thunderclap"]


def test_sanitize_rejects_out_of_range_and_wrong_types(kb):
    out = sanitize({"age": 500, "weight_kg": "70", "pregnant": "no", "complaint": "cancer"}, kb)
    assert out == {}
