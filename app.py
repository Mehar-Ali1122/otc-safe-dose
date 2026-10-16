"""
app.py - Streamlit GUI for the OTC Safe-Dose Assistant.

Flow:  Triage -> Profile -> Safety checks -> Recommendation
Every screen is driven by the rules engine's output (run through the safety
validator): the engine says which answers are still missing, and the GUI
renders the matching step. Nothing is shown that has not passed validation.

Run locally:   streamlit run app.py
"""
from __future__ import annotations

import html
import json
import os

import streamlit as st

import llm_intake
from i18n import t
from incident_log import log_incident
from pipeline import run_pipeline
from rules import (ALLERGY_OPTIONS, APP_VERSION, CONDITION_OPTIONS, MED_CATEGORY_OPTIONS,
                   Knowledge, stage_of_field)

st.set_page_config(page_title="OTC Safe-Dose Assistant", page_icon="💊",
                   layout="wide", initial_sidebar_state="expanded")


@st.cache_resource
def get_kb() -> Knowledge:
    return Knowledge()


KB = get_kb()
ss = st.session_state
for _k, _v in {"patient": {}, "lang": "en", "prefill": {}, "run_id": 0,
               "logged": [], "api_key": ""}.items():
    if _k not in ss:
        ss[_k] = _v


def T(key: str) -> str:
    return t(key, ss.lang)


def k(name: str) -> str:
    """Widget key that resets on 'Start over'."""
    return f"{ss.run_id}_{name}"


def esc(x) -> str:
    return html.escape(str(x))


def rtl() -> str:
    return " rtl" if ss.lang == "ur" else ""


# --------------------------------------------------------------------------
# Styling
# --------------------------------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&family=Noto+Nastaliq+Urdu:wght@400;700&display=swap');
.stApp { font-family: 'Inter', system-ui, sans-serif; font-size: 1.04rem; }
.app-header { background: linear-gradient(135deg, #0f766e 0%, #1d4ed8 100%); color: #fff;
  padding: 1.15rem 1.5rem; border-radius: 18px; margin-bottom: .7rem;
  box-shadow: 0 8px 24px rgba(15,118,110,.25); }
.app-header h1 { color: #fff; font-size: 1.75rem; margin: 0; font-weight: 800; padding: 0; }
.app-header p { margin: .25rem 0 0; opacity: .95; }
.disclaimer { border-left: 5px solid #d97706; background: rgba(217,119,6,.10);
  padding: .65rem 1rem; border-radius: 10px; font-size: .97rem; margin-bottom: .4rem; }
.disclaimer a { font-weight: 800; }
.stepper { display: flex; gap: .5rem; margin: .9rem 0 1.1rem; flex-wrap: wrap; }
.step { flex: 1 1 130px; padding: .6rem .7rem; border-radius: 12px; text-align: center;
  border: 1.5px solid rgba(15,118,110,.4); font-weight: 600; font-size: .93rem; opacity: .6; }
.step.done { background: rgba(15,118,110,.15); opacity: 1; }
.step.active { background: #0f766e; color: #fff; opacity: 1; border-color: #0f766e; }
.step.stopped { background: #b91c1c; color: #fff; opacity: 1; border-color: #b91c1c; }
.emergency { background: #b91c1c; color: #fff; padding: 1.8rem 1.4rem; border-radius: 18px; text-align: center; }
.emergency h2 { color: #fff; margin-top: 0; }
.emergency .num a { color: #fff; font-size: 3.4rem; font-weight: 800; text-decoration: none; letter-spacing: .04em; }
.emergency ul { text-align: left; display: inline-block; margin-top: .6rem; }
.urgent { background: #c2410c; color: #fff; padding: 1.5rem 1.3rem; border-radius: 18px; }
.urgent h2 { color: #fff; margin-top: 0; }
.urgent a { color: #fff; font-weight: 800; }
.alarm { background: #b91c1c; color: #fff; padding: 1rem 1.3rem; border-radius: 14px;
  font-weight: 800; font-size: 1.15rem; animation: pulse 1.6s infinite; margin-bottom: .8rem; }
@keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(185,28,28,.65); }
  70% { box-shadow: 0 0 0 16px rgba(185,28,28,0); } 100% { box-shadow: 0 0 0 0 rgba(185,28,28,0); } }
@media (prefers-reduced-motion: reduce) { .alarm { animation: none; } }
.badge-ok { display: inline-block; background: #15803d; color: #fff; padding: .4rem .95rem;
  border-radius: 999px; font-weight: 700; margin-bottom: .5rem; }
.card { border: 1.5px solid rgba(15,118,110,.4); border-radius: 16px; padding: 1.1rem 1.3rem;
  margin: .7rem 0; background: rgba(15,118,110,.05); }
.card h3 { margin: 0 0 .5rem; padding: 0; }
.card.refer { border-color: rgba(217,119,6,.6); background: rgba(217,119,6,.07); }
table.dose { width: 100%; border-collapse: collapse; margin: .4rem 0 .8rem; }
table.dose th, table.dose td { text-align: left; padding: .45rem .55rem; border-bottom: 1px solid rgba(128,128,128,.25); vertical-align: top; }
table.dose th { width: 38%; font-weight: 600; opacity: .85; }
.capbar { height: 20px; border-radius: 10px; background: rgba(128,128,128,.22); overflow: hidden; display: flex; }
.capbar .prior { background: #64748b; }
.caplabel { font-size: .9rem; margin: .3rem 0 .6rem; }
.wait { background: rgba(217,119,6,.15); border: 1.5px solid #d97706; border-radius: 10px; padding: .55rem .8rem; font-weight: 700; margin-bottom: .6rem; }
.verify { background: rgba(217,119,6,.12); border: 1px dashed #d97706; padding: .45rem .75rem; border-radius: 10px; font-size: .88rem; }
.footer { opacity: .75; font-size: .85rem; margin-top: 2rem; border-top: 1px solid rgba(128,128,128,.25); padding-top: .7rem; }
.rtl { direction: rtl; text-align: right; font-family: 'Noto Nastaliq Urdu', serif; line-height: 2.1; }
</style>
""", unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Header, sidebar
# --------------------------------------------------------------------------
num = KB.emergency_number
st.markdown(f"""
<div class="app-header{rtl()}"><h1>💊 {esc(T('app_title'))}</h1><p>{esc(T('app_subtitle'))}</p></div>
<div class="disclaimer{rtl()}">⚠️ {esc(T('disclaimer'))} <a href="tel:{esc(num)}">{esc(num)}</a>.</div>
""", unsafe_allow_html=True)

with st.sidebar:
    lang = st.radio(T("language"), ["en", "ur"], horizontal=True,
                    format_func=lambda x: "English" if x == "en" else "اردو",
                    index=0 if ss.lang == "en" else 1)
    if lang != ss.lang:
        ss.lang = lang
        st.rerun()
    st.markdown(f"### 🩺 {T('profile')}")
    p = ss.patient

    def row(label, value):
        if value not in (None, [], {}):
            st.markdown(f"**{label}:** {esc(value)}")

    if p.get("complaint"):
        row("Problem", KB.complaints[p["complaint"]]["label"])
    row("Duration (days)", p.get("symptom_days"))
    if p.get("red_flags"):
        row("Red flags", "Yes ⚠️" if any(p["red_flags"].values()) else "None reported")
    row("Age", p.get("age"))
    row("Sex", (p.get("sex") or "").capitalize() or None)
    row("Weight (kg)", p.get("weight_kg"))
    if p.get("pregnant") or p.get("breastfeeding"):
        row("Pregnant / breastfeeding", "Yes")
    if p.get("conditions") is not None:
        row("Conditions", ", ".join(CONDITION_OPTIONS[c] for c in p["conditions"]) or "None")
    if p.get("current_meds") is not None:
        row("Regular medicines", ", ".join(MED_CATEGORY_OPTIONS[m] for m in p["current_meds"]) or "None")
    if p.get("allergies") is not None:
        row("Allergies", ", ".join(ALLERGY_OPTIONS[a] for a in p["allergies"]) or "None")
    if p.get("prior_intake"):
        row("Taken in last 24 h", "; ".join(f"{e['ingredient']} {e['total_mg_24h']:g} mg"
                                             for e in p["prior_intake"]) or None)
    if not p:
        st.caption("Your answers will appear here as you go.")
    st.divider()
    if st.button(f"🔄 {T('start_over')}", use_container_width=True):
        ss.patient, ss.prefill = {}, {}
        ss.run_id += 1
        st.rerun()
    with st.expander("⚙️ Optional AI text intake"):
        ss.api_key = st.text_input("Anthropic API key", value=ss.api_key, type="password",
                                   help="Optional. Used only to pre-fill the form from a free-text "
                                        "description. Never used to choose medicines or doses.")
        st.caption("Leave empty to use the guided form only (fully functional).")
    with st.expander("ℹ️ About & limitations"):
        st.markdown("Research prototype. **Not a medical device**, not clinically validated, "
                    "no diagnosis. Doses come from a formulary that must be verified by a "
                    "pharmacist. Adults only, OTC medicines only.")


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------
result = run_pipeline(ss.patient, KB)
if result["action"] == "BLOCKED":
    sig = json.dumps(ss.patient, sort_keys=True, default=str)
    if sig not in ss.logged:  # log each blocked state once, not on every rerun
        log_incident("validator_block", ss.patient, result["proposed"], result["failures"])
        ss.logged.append(sig)

STAGES = [("triage", "step_triage"), ("profile", "step_profile"),
          ("safety", "step_safety"), ("recommendation", "step_rec")]


def stage_state(res: dict) -> tuple[str, str]:
    a = res["action"]
    if a == "ASK":
        return stage_of_field(res["missing"][0]), "active"
    if a in ("EMERGENCY", "URGENT_DOCTOR"):
        return "triage", "stopped"
    if a == "REFER":
        return {1: "triage", 2: "profile", 3: "safety", 4: "safety"}.get(res["rule"], "recommendation"), "stopped"
    if a == "BLOCKED":
        return "recommendation", "stopped"
    return "recommendation", "done"


cur, state = stage_state(result)
names = [s for s, _ in STAGES]
html_steps = []
for i, (s, label) in enumerate(STAGES):
    cls = "done" if i < names.index(cur) else (state if s == cur else "")
    icon = {"done": "✓", "active": "●", "stopped": "■"}.get(cls, str(i + 1))
    html_steps.append(f'<div class="step {cls}{rtl()}">{icon} {esc(T(label))}</div>')
st.markdown(f'<div class="stepper">{"".join(html_steps)}</div>', unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Intake steps
# --------------------------------------------------------------------------
YES_NO = ["No", "Yes"]


def _int(v):
    return int(v) if v is not None else None


def yn_index(v):
    return {False: 0, True: 1}.get(v)


def ai_prefill_box():
    key = ss.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    with st.container(border=True):
        st.markdown("**💬 Describe your problem in your own words** *(optional)*")
        txt = st.text_area("Description", key=k("free_text"), label_visibility="collapsed",
                           placeholder="e.g., I'm 34, female, about 60 kg. I've had a tension headache "
                                       "since yesterday and took 2 cold & flu tablets this morning...")
        if st.button("✨ Pre-fill the form for me", disabled=not (key and txt.strip()), key=k("ai_go")):
            try:
                with st.spinner("Reading your description..."):
                    ss.prefill = llm_intake.extract_fields(txt, key, KB)
                ss.run_id += 1
                st.rerun()
            except llm_intake.IntakeError as exc:
                st.warning(f"{exc} You can continue with the form below.")
        if not key:
            st.caption("AI pre-fill is off (no API key). The guided form below works fully without it.")


def triage_step():
    pre, p = ss.prefill, ss.patient
    if not p and not pre:
        ai_prefill_box()
    if pre:
        st.info("Some answers were pre-filled from your description. Please check every answer.")
    with st.chat_message("assistant", avatar="🩺"):
        st.markdown("**Let's start with safety.** What is the main problem, and do you have any warning signs?")
        keys = list(KB.complaints)
        default = p.get("complaint") or pre.get("complaint")
        complaint = st.selectbox("Main problem", keys, format_func=lambda c: KB.complaints[c]["label"],
                                 index=keys.index(default) if default in keys else None,
                                 placeholder="Choose the main problem", key=k("complaint"))
        days = st.number_input("How many days have you had it? (0 = started today)", min_value=0,
                               max_value=365, step=1, key=k("days"),
                               value=_int(p.get("symptom_days", pre.get("symptom_days"))))
        if complaint is None:
            return
        if ss.lang == "ur":
            st.caption(T("clinical_en_only"))
        st.markdown("**Do you have any of the following?** Please answer every question.")
        answers = {}
        prev = p.get("red_flags") or {}
        for f in KB.red_flags_for(complaint):
            v = prev.get(f["id"])
            if v is None and f["id"] in pre.get("red_flags_positive", []):
                v = True
            ans = st.radio(f["text"], YES_NO, index=yn_index(v), horizontal=True,
                           key=k(f"rf_{complaint}_{f['id']}"))
            answers[f["id"]] = None if ans is None else ans == "Yes"
        if any(answers.values()):
            st.error("⚠️ A 'Yes' answer means you need medical help rather than self-treatment.")
        if st.button("Continue →", type="primary", key=k("triage_go")):
            if days is None or None in answers.values():
                st.error("Please answer every question before continuing.")
                return
            p.update(complaint=complaint, symptom_days=int(days), red_flags=answers)
            st.rerun()


def profile_step():
    pre, p = ss.prefill, ss.patient
    with st.chat_message("assistant", avatar="🩺"):
        st.markdown("**A few details about you.** These decide whether self-care is safe and which dose fits.")
        c1, c2 = st.columns(2)
        age = c1.number_input("Age (years)", min_value=0, max_value=120, step=1, key=k("age"),
                              value=_int(p.get("age", pre.get("age"))))
        w = p.get("weight_kg", pre.get("weight_kg"))
        weight = c2.number_input("Weight (kg)", min_value=1.0, max_value=300.0, step=0.5, format="%.1f",
                                 key=k("weight"), value=float(w) if w is not None else None)
        sexes = ["female", "male", "other"]
        sdef = p.get("sex", pre.get("sex"))
        sex = st.radio("Sex", sexes, format_func=str.capitalize, horizontal=True, key=k("sex"),
                       index=sexes.index(sdef) if sdef in sexes else None)
        preg = bf = None
        if sex in ("female", "other"):
            preg = st.radio("Are you pregnant or could you be pregnant?", YES_NO, horizontal=True,
                            key=k("preg"), index=yn_index(p.get("pregnant", pre.get("pregnant"))))
            bf = st.radio("Are you breastfeeding?", YES_NO, horizontal=True, key=k("bf"),
                          index=yn_index(p.get("breastfeeding", pre.get("breastfeeding"))))
        if st.button("Continue →", type="primary", key=k("profile_go")):
            if age is None or weight is None or sex is None or (sex != "male" and (preg is None or bf is None)):
                st.error("Please answer every question before continuing.")
                return
            p.update(age=int(age), weight_kg=float(weight), sex=sex,
                     pregnant=(preg == "Yes") if sex != "male" else False,
                     breastfeeding=(bf == "Yes") if sex != "male" else False)
            st.rerun()


def safety_step():
    pre, p = ss.prefill, ss.patient
    complaint = p["complaint"]
    with st.chat_message("assistant", avatar="🩺"):
        st.markdown("**Safety checks.** Your health conditions, regular medicines and allergies "
                    "decide which medicines are safe for you. *Leave a list empty if none apply.*")
        conds = st.multiselect("Health conditions", list(CONDITION_OPTIONS), format_func=CONDITION_OPTIONS.get,
                               default=p.get("conditions", pre.get("conditions", [])), key=k("conds"),
                               placeholder="None")
        meds = st.multiselect("Regular medicines", list(MED_CATEGORY_OPTIONS),
                              format_func=MED_CATEGORY_OPTIONS.get, key=k("meds"), placeholder="None",
                              default=p.get("current_meds", pre.get("current_meds", [])))
        alls = st.multiselect("Medicine allergies", list(ALLERGY_OPTIONS), format_func=ALLERGY_OPTIONS.get,
                              default=p.get("allergies", pre.get("allergies", [])), key=k("alls"),
                              placeholder="None")
        c1, c2 = st.columns(2)
        alc = c1.radio("Do you drink alcohol regularly (most days)?", YES_NO, horizontal=True, key=k("alc"),
                       index=yn_index(p.get("alcohol_regular", pre.get("alcohol_regular"))))
        nmeds = c2.number_input("How many regular prescribed medicines do you take?", min_value=0,
                                max_value=50, step=1, key=k("nmeds"),
                                value=_int(p.get("num_regular_meds", pre.get("num_regular_meds"))))

        st.markdown("#### 🕒 Medicines already taken in the last 24 hours")
        st.warning("**Check every pack.** Many cold & flu, sinus and 'extra strength' products contain "
                   "**hidden paracetamol**. Add the paracetamol from *all* products to the total.")
        prev = {e["ingredient"]: e for e in (p.get("prior_intake") or pre.get("prior_intake") or [])}
        ingredients = []
        for d in KB.candidates_for(complaint):
            ing = KB.drugs[d]["ingredient"]
            if ing not in ingredients:
                ingredients.append(ing)
        intake, incomplete = [], False
        for ing in ingredients:
            name = next(v["display_name"] for v in KB.drugs.values() if v["ingredient"] == ing)
            e = prev.get(ing, {})
            c1, c2 = st.columns(2)
            mg = c1.number_input(f"Total {name} in last 24 h (mg) - 0 if none", min_value=0.0,
                                 max_value=20000.0, step=1.0, format="%g", key=k(f"mg_{ing}"),
                                 value=float(e["total_mg_24h"]) if e.get("total_mg_24h") is not None else None)
            hrs = c2.number_input("Hours since the last dose", min_value=0.0, max_value=24.0, step=0.5,
                                  format="%g", key=k(f"h_{ing}"), disabled=not mg,
                                  value=float(e["hours_since_last"]) if e.get("hours_since_last") is not None else None)
            if mg is None or (mg > 0 and hrs is None):
                incomplete = True
            intake.append({"ingredient": ing, "total_mg_24h": mg or 0,
                           "hours_since_last": hrs if mg else None})
        with st.expander("🧮 Help me add it up"):
            a, b = st.columns(2)
            n = a.number_input("Number of tablets/sachets taken", min_value=0, step=1, key=k("calc_n"))
            per = b.number_input("mg of the ingredient per tablet (see pack)", min_value=0.0, step=1.0,
                                 format="%g", key=k("calc_mg"))
            st.markdown(f"= **{n * per:g} mg** - add this to the total above.")

        if st.button("Run safety checks →", type="primary", key=k("safety_go")):
            if alc is None or nmeds is None or incomplete:
                st.error("Please answer every question (enter 0 mg if you took none).")
                return
            p.update(conditions=conds, current_meds=meds, allergies=alls,
                     alcohol_regular=alc == "Yes", num_regular_meds=int(nmeds), prior_intake=intake)
            st.rerun()


# --------------------------------------------------------------------------
# Result screens
# --------------------------------------------------------------------------
def report_box(res: dict):
    with st.expander("🚩 Report incorrect advice"):
        txt = st.text_area("What was wrong? Please do not include names or contact details.",
                           key=k("report_txt"))
        if st.button("Send report for clinician review", key=k("report_btn")):
            log_incident("user_report", ss.patient, res, comment=txt)
            st.success("Thank you - your report has been logged for clinician review.")


def emergency_screen(res: dict):
    items = "".join(f"<li>{esc(f['text'])}</li>" for f in res["triggered_flags"])
    st.markdown(f"""
    <div class="emergency" role="alert">
      <h2 class="{rtl().strip()}">🚨 {esc(T('emergency_title'))}</h2>
      <p class="{rtl().strip()}" style="font-size:1.15rem">{esc(T('emergency_body'))}</p>
      <div class="num"><a href="tel:{esc(num)}">📞 {esc(num)}</a></div>
      <p class="{rtl().strip()}">{esc(T('call_now'))}</p>
      <ul>{items}</ul>
    </div>""", unsafe_allow_html=True)


def urgent_screen(res: dict):
    items = "".join(f"<li>{esc(f['text'])}</li>" for f in res["triggered_flags"])
    st.markdown(f"""
    <div class="urgent" role="alert">
      <h2 class="{rtl().strip()}">🩺 {esc(T('urgent_title'))}</h2>
      <p class="{rtl().strip()}">{esc(T('urgent_body'))} <a href="tel:{esc(num)}">📞 {esc(num)}</a></p>
      <ul>{items}</ul>
    </div>""", unsafe_allow_html=True)


def refer_screen(res: dict):
    reasons = "".join(f"<li>{esc(r)}</li>" for r in res["reasons"])
    excl = "".join(f"<li><b>{esc(e['display_name'])}</b>: {esc('; '.join(e['reasons']))}</li>"
                   for e in res.get("excluded", []))
    excl_html = f"<p><b>Medicines ruled out for you:</b></p><ul>{excl}</ul>" if excl else ""
    stop = f"<p>{esc(res['stop_advice'])}</p>" if res.get("stop_advice") else ""
    st.markdown(f"""
    <div class="card refer"><h3 class="{rtl().strip()}">🧑‍⚕️ {esc(T('refer_title'))}</h3>
      <ul>{reasons}</ul>{excl_html}{stop}
      <p><i>{esc(res['disclaimer'])}</i></p></div>""", unsafe_allow_html=True)


def blocked_screen(res: dict):
    st.markdown(f'<div class="alarm" role="alert">🚨 {esc(T("alarm"))}</div>', unsafe_allow_html=True)
    st.error(res["reasons"][1])
    with st.expander("Technical details (logged for review)"):
        for f in res["failures"]:
            st.markdown(f"- `{f['check']}` - {esc(f['detail'])}")


def option_card(i: int, o: dict):
    cap, prior, dmax = o["max_24h_mg"], o["prior_mg_24h"], o["dose_max_mg"]
    total = (prior + dmax) / cap
    color = "#15803d" if total <= 0.5 else ("#d97706" if total <= 0.85 else "#b91c1c")
    rows = [("Medicine", o["display_name"]), ("Strength", f"{o['strength_mg']} mg {o['form']}"),
            ("Dose", o["dose_text"]), ("How often", o["interval_text"]),
            ("Maximum in 24 h", f"{cap:g} mg"), ("Already taken (last 24 h)", f"{prior:g} mg"),
            ("Still allowed in the next 24 h", f"{o['remaining_mg_24h']:g} mg"),
            ("How to take", o["administration"])]
    table = "".join(f"<tr><th>{esc(a)}</th><td>{esc(b)}</td></tr>" for a, b in rows)
    wait = (f'<div class="wait">⏳ Do not take the next dose for another {o["next_dose_in_h"]:g} hours.</div>'
            if o["next_dose_in_h"] > 0 else "")
    notes = "".join(f"<li>{esc(n)}</li>" for n in o["limit_notes"])
    warns = "".join(f"<li>{esc(w)}</li>" for w in o["warnings"] + o["interactions"])
    verify = ("" if o["verification_status"] == "VERIFIED" else
              '<div class="verify">🔶 Prototype data: this dose entry has not yet been verified by a pharmacist.</div>')
    st.markdown(f"""
    <div class="card">
      <h3>Option {i}: {esc(o['display_name'])}</h3>{wait}
      <table class="dose">{table}</table>
      <div class="capbar" role="img" aria-label="24-hour limit used">
        <div class="prior" style="width:{100 * prior / cap:.1f}%"></div>
        <div style="width:{100 * dmax / cap:.1f}%; background:{color}"></div></div>
      <div class="caplabel">24-hour limit: {prior:g} mg taken + up to {dmax:g} mg now = <b>{prior + dmax:g} of {cap:g} mg</b></div>
      {f'<ul>{notes}</ul>' if notes else ''}
      <p><b>⚠️ Important</b></p><ul>{warns}</ul>
      <p style="font-size:.88rem;opacity:.8"><b>Source:</b> {esc(o['source'])}</p>{verify}
    </div>""", unsafe_allow_html=True)


def recommend_screen(res: dict):
    st.markdown(f'<span class="badge-ok">✅ {esc(T("safety_ok"))}</span>', unsafe_allow_html=True)
    if len(res["options"]) > 1:
        st.markdown("Choose **one** of these options - do not take them together unless a pharmacist advises it.")
    for i, o in enumerate(res["options"], 1):
        option_card(i, o)
    if res.get("excluded"):
        st.markdown("**Ruled out for you:** " + "; ".join(
            f"{e['display_name']} ({'; '.join(e['reasons'])})" for e in res["excluded"]))
    st.info(f"🗓️ {res['stop_advice']}")
    st.markdown(f"**{res['disclaimer']}**")


# --------------------------------------------------------------------------
# Router
# --------------------------------------------------------------------------
action = result["action"]
if action == "ASK":
    {"triage": triage_step, "profile": profile_step, "safety": safety_step}[cur]()
else:
    {"EMERGENCY": emergency_screen, "URGENT_DOCTOR": urgent_screen, "REFER": refer_screen,
     "BLOCKED": blocked_screen, "RECOMMEND": recommend_screen}[action](result)
    c1, c2 = st.columns(2)
    if action in ("EMERGENCY", "URGENT_DOCTOR") and c1.button("I answered a question by mistake - review answers", key=k("review_rf")):
        ss.patient.pop("red_flags", None)
        ss.run_id += 1
        st.rerun()
    if c2.button(f"🔄 {T('start_over')}", key=k("restart_main")):
        ss.patient, ss.prefill = {}, {}
        ss.run_id += 1
        st.rerun()
    report_box(result)

vdate = KB.verification_date or "NOT YET VERIFIED"
st.markdown(f"""<div class="footer"><span class="{rtl().strip()}">🔒 {esc(T('privacy'))}</span><br>
Version {APP_VERSION} · Formulary verification date: <b>{esc(vdate)}</b> ·
Research prototype - not a medical device.</div>""", unsafe_allow_html=True)
