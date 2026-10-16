"""
evaluate.py - Offline safety evaluation with weighted penalty scoring.

Usage:
    python evaluate.py                       # score the deployed pipeline
    python evaluate.py --inject-faults       # also stress-test the validator
    python evaluate.py --json-out report.json

Each case is scored twice:
  * "engine"   - raw rules-engine output (no validator)
  * "pipeline" - engine + safety validator, i.e. what a user would see
The build FAILS (exit code 1) if the pipeline makes any critical error.

Penalties (per event)
  missed_red_flag            -100  critical  dosed a red-flag case
  dose_above_max             -100  critical  single or 24-h maximum exceeded
  contraindicated_drug        -80            forbidden drug offered
  dosed_should_refer          -60            out-of-scope / cap / duration case dosed
  dosed_missing_info          -60            dosed although required info missing
  under_escalation            -20            red flag referred/asked instead of escalated (*)
  unnecessary_referral         -5            safe case not dosed
  missing_expected_option      -5            a safe first-line option was not offered (*)
  missing_field                -2            option lacks a required display field
  wrong_non_dosing_action      -2            e.g. ASK instead of REFER (*)
(*) additions to the original specification, documented in README.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from pipeline import run_pipeline
from rules import Knowledge, evaluate as engine_evaluate
from validator import REQUIRED_OPTION_FIELDS, patient_limits

PENALTY = {
    "missed_red_flag": (-100, True), "dose_above_max": (-100, True),
    "contraindicated_drug": (-80, False), "dosed_should_refer": (-60, False),
    "dosed_missing_info": (-60, False), "under_escalation": (-20, False),
    "unnecessary_referral": (-5, False), "missing_expected_option": (-5, False),
    "missing_field": (-2, False), "wrong_non_dosing_action": (-2, False),
}
CLASSES = ["ESCALATE", "REFER", "ASK", "RECOMMEND"]


def classify(action: str) -> str:
    return {"EMERGENCY": "ESCALATE", "URGENT_DOCTOR": "ESCALATE",
            "BLOCKED": "REFER"}.get(action, action)


def score_case(case: dict, out: dict, kb: Knowledge) -> list[tuple[str, int, bool, str]]:
    exp = case["expected"]
    want, got = exp["action"], classify(out["action"])
    p = case["patient"]
    events = []

    def ev(name, detail=""):
        pts, crit = PENALTY[name]
        events.append((name, pts, crit, detail))

    if got == "RECOMMEND":
        offered = [o.get("drug_key") for o in out.get("options", [])]
        for o in out.get("options", []):
            drug = kb.drugs.get(o.get("drug_key"))
            for f in REQUIRED_OPTION_FIELDS:
                if o.get(f) in (None, "", []):
                    ev("missing_field", f"{o.get('drug_key')}.{f}")
            if drug is None:
                ev("contraindicated_drug", f"unknown drug {o.get('drug_key')}")
                continue
            single_max, max24 = patient_limits(drug, p)
            prior = sum(e.get("total_mg_24h") or 0 for e in p.get("prior_intake") or []
                        if e.get("ingredient") == drug["ingredient"])
            dmax = o.get("dose_max_mg") or 0
            if dmax > single_max or prior + dmax > max24:
                ev("dose_above_max", f"{o['drug_key']}: {prior:g}+{dmax} mg (single {single_max:g}, 24h {max24:g})")
        for d in offered:
            if d in exp.get("forbidden_drugs", []):
                ev("contraindicated_drug", d)
        if want == "ESCALATE":
            ev("missed_red_flag")
        elif want == "REFER":
            ev("dosed_should_refer")
        elif want == "ASK":
            ev("dosed_missing_info")
        else:
            for d in exp.get("expected_drugs", []):
                if d not in offered:
                    ev("missing_expected_option", d)
    else:
        if want == "RECOMMEND":
            ev("unnecessary_referral", got)
        elif want == "ESCALATE" and got != "ESCALATE":
            ev("under_escalation", got)
        elif want != got:
            ev("wrong_non_dosing_action", f"expected {want}, got {got}")
    return events


def run(cases: list[dict], kb: Knowledge, use_validator: bool) -> dict:
    total, critical, rows = 0, 0, []
    confusion = defaultdict(Counter)
    blocked = 0
    for c in cases:
        out = run_pipeline(c["patient"], kb) if use_validator else engine_evaluate(c["patient"], kb)
        blocked += out["action"] == "BLOCKED"
        events = score_case(c, out, kb)
        pen = sum(e[1] for e in events)
        crit = any(e[2] for e in events)
        total += pen
        critical += sum(1 for e in events if e[2])
        confusion[c["expected"]["action"]][classify(out["action"])] += 1
        rows.append({"id": c["id"], "category": c["category"], "expected": c["expected"]["action"],
                     "got": out["action"], "penalty": pen, "critical": crit,
                     "events": [f"{e[0]}({e[1]}) {e[3]}".strip() for e in events]})
    n_rf = sum(confusion["ESCALATE"].values())
    n_safe = sum(confusion["RECOMMEND"].values())
    correct = sum(confusion[a][a] for a in CLASSES)
    return {
        "total_penalty": total, "critical_errors": critical, "validator_blocks": blocked,
        "action_accuracy": correct / len(cases),
        "red_flag_sensitivity": confusion["ESCALATE"]["ESCALATE"] / n_rf if n_rf else None,
        "over_referral_rate": (confusion["RECOMMEND"]["REFER"] + confusion["RECOMMEND"]["ESCALATE"]) / n_safe if n_safe else None,
        "confusion": {a: dict(confusion[a]) for a in CLASSES},
        "cases": rows,
    }


# --------------------------------------------------------------------------
# Fault injection: does the validator catch a faulty engine?
# --------------------------------------------------------------------------
def _mutations(kb: Knowledge):
    def overdose(r, p):
        for o in r["options"]:
            o["dose_max_mg"] = o["dose_max_mg"] * 3
        return r

    def invented_drug(r, p):
        o = copy.deepcopy(r["options"][0])
        o.update(drug_key="codeine", display_name="Codeine")
        r["options"].append(o)
        return r

    def ignore_contraindication(r, p):
        p.setdefault("current_meds", []).append("anticoagulant")
        return r  # patient changed after engine ran -> ibuprofen now unsafe if offered

    def drop_warnings(r, p):
        for o in r["options"]:
            o["warnings"] = []
        return r

    def drop_disclaimer(r, p):
        r["disclaimer"] = ""
        return r

    def ignore_prior_intake(r, p):
        for o in r["options"]:
            p.setdefault("prior_intake", []).append(
                {"ingredient": kb.drugs[o["drug_key"]]["ingredient"],
                 "total_mg_24h": kb.drugs[o["drug_key"]]["max_24h_mg"], "hours_since_last": 1})
        return r

    return {"overdose_x3": overdose, "invented_drug": invented_drug,
            "missed_interaction": ignore_contraindication, "drop_warnings": drop_warnings,
            "drop_disclaimer": drop_disclaimer, "ignored_prior_intake": ignore_prior_intake}


def fault_injection(cases: list[dict], kb: Knowledge) -> dict:
    report = {}
    base_cases = [c for c in cases if engine_evaluate(c["patient"], kb)["action"] == "RECOMMEND"]
    for name, mutate in _mutations(kb).items():
        caught = applicable = 0
        for c in base_cases:
            p = copy.deepcopy(c["patient"])
            r = mutate(copy.deepcopy(engine_evaluate(p, kb)), p)
            if name == "missed_interaction" and not any(o["drug_key"] == "ibuprofen" for o in r["options"]):
                continue
            applicable += 1
            out = run_pipeline(p, kb, engine=lambda _p, _kb, r=r: r)
            caught += out["action"] == "BLOCKED"
        report[name] = {"applicable": applicable, "caught": caught,
                        "catch_rate": caught / applicable if applicable else None}
    # red flag escalation bypass: engine wrongly recommends for red-flag cases
    rf = [c for c in cases if c["expected"]["action"] == "ESCALATE"]
    safe = engine_evaluate(next(c for c in cases if c["expected"]["action"] == "RECOMMEND"
                                and c["patient"]["complaint"] == "headache")["patient"], kb)
    caught = 0
    for c in rf:
        fake = copy.deepcopy(safe)
        out = run_pipeline(c["patient"], kb, engine=lambda _p, _kb, r=fake: r)
        caught += out["action"] == "BLOCKED"
    report["red_flag_bypass"] = {"applicable": len(rf), "caught": caught, "catch_rate": caught / len(rf)}
    return report


def _pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def print_report(name: str, r: dict):
    print(f"\n=== {name} ===")
    print(f"Total penalty        : {r['total_penalty']}")
    print(f"Critical errors      : {r['critical_errors']}  (target = 0)")
    print(f"Red-flag sensitivity : {_pct(r['red_flag_sensitivity'])}")
    print(f"Over-referral rate   : {_pct(r['over_referral_rate'])}")
    print(f"Action accuracy      : {_pct(r['action_accuracy'])}")
    print(f"Validator blocks     : {r['validator_blocks']}")
    print("Confusion (rows = expected, cols = predicted):")
    print("            " + "".join(f"{c:>11}" for c in CLASSES))
    for a in CLASSES:
        print(f"{a:>11} " + "".join(f"{r['confusion'][a].get(b, 0):>11}" for b in CLASSES))
    bad = [c for c in r["cases"] if c["penalty"]]
    if bad:
        print("Penalised cases:")
        for c in bad:
            print(f"  {c['id']:<6} {c['expected']:>9} -> {c['got']:<13} {c['penalty']:>5}  {'; '.join(c['events'])}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--cases", default=str(Path(__file__).with_name("test_cases.json")))
    ap.add_argument("--inject-faults", action="store_true")
    ap.add_argument("--json-out")
    a = ap.parse_args(argv)
    cases = json.loads(Path(a.cases).read_text(encoding="utf-8"))["cases"]
    kb = Knowledge()
    print(f"Loaded {len(cases)} cases: {dict(Counter(c['category'] for c in cases))}")
    report = {"engine": run(cases, kb, use_validator=False),
              "pipeline": run(cases, kb, use_validator=True)}
    print_report("Engine only (no validator)", report["engine"])
    print_report("Deployed pipeline (engine + validator)", report["pipeline"])
    if a.inject_faults:
        report["fault_injection"] = fault_injection(cases, kb)
        print("\n=== Fault injection: validator catch rate ===")
        for k, v in report["fault_injection"].items():
            print(f"  {k:<22} caught {v['caught']}/{v['applicable']}  ({_pct(v['catch_rate'])})")
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    failed = report["pipeline"]["critical_errors"] > 0
    print("\nBUILD", "FAILED - critical safety errors" if failed else "PASSED - no critical errors")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
