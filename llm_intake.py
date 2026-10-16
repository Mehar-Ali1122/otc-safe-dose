"""
llm_intake.py - OPTIONAL free-text intake using an LLM.

The LLM only extracts structured fields from the user's description to
PRE-FILL the guided form. It never produces drug names or doses, and its
output never reaches the rules engine directly: the user must confirm every
answer in the form. Safety properties:
  * strict whitelist sanitisation of every field (unknown keys are dropped);
  * red flags can only be pre-marked "Yes" (escalation), never "No";
  * the app works fully without an API key.

Provider: Anthropic Messages API over HTTPS (set ANTHROPIC_API_KEY, and
optionally MEDBOT_LLM_MODEL).
"""
from __future__ import annotations

import json
import os
import re

import requests

from rules import ALLERGY_OPTIONS, CONDITION_OPTIONS, MED_CATEGORY_OPTIONS, SEXES, Knowledge

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-haiku-5-5"


class IntakeError(RuntimeError):
    pass


def _system_prompt(kb: Knowledge) -> str:
    flag_ids = sorted({f["id"] for c in kb.complaints for f in kb.red_flags_for(c)})
    ingredients = sorted({d["ingredient"] for d in kb.drugs.values()})
    return (
        "You extract structured intake data from a patient's description for a medicine-safety form.\n"
        "Rules: NEVER suggest, name or dose any medicine of your own. Do not give advice. "
        "Only report what the text explicitly states; use null when unsure.\n"
        "Return ONE JSON object and nothing else, with keys:\n"
        f"  complaint: one of {sorted(kb.complaints)} or null\n"
        "  symptom_days: number or null\n  age: number or null\n"
        f"  sex: one of {list(SEXES)} or null\n  weight_kg: number or null\n"
        "  pregnant, breastfeeding, alcohol_regular: true/false/null\n"
        f"  conditions: subset of {sorted(CONDITION_OPTIONS)}\n"
        f"  current_meds: subset of {sorted(MED_CATEGORY_OPTIONS)}\n"
        f"  allergies: subset of {sorted(ALLERGY_OPTIONS)}\n"
        "  num_regular_meds: number or null\n"
        f"  prior_intake: list of {{ingredient (one of {ingredients}), total_mg_24h, hours_since_last}}\n"
        f"  red_flags_positive: subset of {flag_ids} - ONLY flags the text clearly describes.\n"
    )


def _as_num(v, lo, hi):
    if isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi:
        return v
    return None


def sanitize(raw: dict, kb: Knowledge) -> dict:
    """Keep only whitelisted, type-checked fields."""
    out: dict = {}
    if raw.get("complaint") in kb.complaints:
        out["complaint"] = raw["complaint"]
    for key, lo, hi in (("symptom_days", 0, 365), ("age", 0, 120),
                        ("weight_kg", 1, 300), ("num_regular_meds", 0, 50)):
        v = _as_num(raw.get(key), lo, hi)
        if v is not None:
            out[key] = v
    if raw.get("sex") in SEXES:
        out["sex"] = raw["sex"]
    for key in ("pregnant", "breastfeeding", "alcohol_regular"):
        if isinstance(raw.get(key), bool):
            out[key] = raw[key]
    for key, allowed in (("conditions", CONDITION_OPTIONS), ("current_meds", MED_CATEGORY_OPTIONS),
                         ("allergies", ALLERGY_OPTIONS)):
        vals = raw.get(key)
        if isinstance(vals, list):
            out[key] = [v for v in vals if v in allowed]
    ingredients = {d["ingredient"] for d in kb.drugs.values()}
    intake = []
    for e in raw.get("prior_intake") or []:
        if isinstance(e, dict) and e.get("ingredient") in ingredients:
            mg = _as_num(e.get("total_mg_24h"), 0, 20000)
            if mg is not None:
                intake.append({"ingredient": e["ingredient"], "total_mg_24h": mg,
                               "hours_since_last": _as_num(e.get("hours_since_last"), 0, 24)})
    if intake:
        out["prior_intake"] = intake
    all_flags = {f["id"] for c in kb.complaints for f in kb.red_flags_for(c)}
    pos = raw.get("red_flags_positive")
    if isinstance(pos, list):
        out["red_flags_positive"] = [f for f in pos if f in all_flags]
    return out


def extract_fields(text: str, api_key: str, kb: Knowledge, model: str | None = None,
                   timeout: int = 30) -> dict:
    if not api_key:
        raise IntakeError("No API key configured.")
    payload = {
        "model": model or os.environ.get("MEDBOT_LLM_MODEL", DEFAULT_MODEL),
        "max_tokens": 800,
        "system": _system_prompt(kb),
        "messages": [{"role": "user", "content": text[:4000]}],
    }
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    try:
        r = requests.post(API_URL, json=payload, headers=headers, timeout=timeout)
        r.raise_for_status()
        content = "".join(b.get("text", "") for b in r.json().get("content", []))
    except (requests.RequestException, ValueError) as exc:
        raise IntakeError(f"AI pre-fill unavailable: {exc}") from exc
    match = re.search(r"\{.*\}", content, re.S)
    if not match:
        raise IntakeError("AI pre-fill returned no usable data.")
    try:
        raw = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise IntakeError("AI pre-fill returned malformed data.") from exc
    return sanitize(raw, kb)
