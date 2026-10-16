# OTC Safe-Dose Assistant

A safety-first, rule-based chatbot that gives adults general guidance on
over-the-counter (OTC) medicines for common, self-limiting complaints:
headache, fever, mild muscle/joint pain, common cold, hay fever, heartburn
and mild diarrhoea.

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/YOUR-USERNAME/otc-safe-dose/blob/main/notebooks/OTC_Safe_Dose_Assistant_Explained.ipynb)
![Python](https://img.shields.io/badge/python-3.10%2B-blue) ![Tests](https://img.shields.io/badge/tests-60%20passing-brightgreen) ![License](https://img.shields.io/badge/license-MIT-lightgrey)

> **Research prototype. Not a medical device. Not clinically validated.**

## Screenshots

| Recommendation (all safety checks passed) | Emergency screen (red flag) |
|---|---|
| ![Recommendation](docs/screenshots/recommendation.png) | ![Emergency](docs/screenshots/emergency.png) |

## Quick start in Google Colab

Click **Open in Colab** above, then **Runtime → Run all**, and open the link printed in Part 9.
The notebook explains every file and every rule step by step.
> Every dose in `formulary.json` is a placeholder marked `VERIFY` until a
> pharmacist checks it against the official product label.

## Design in one picture

```
patient answers ─► rules.py (Rules 1-6) ─► validator.py (V0-V13) ─► GUI
   (form, or LLM         deterministic,         independent re-check;     shows answer, or
    pre-fill that the    reads formulary.json   any failure = BLOCK       RED ALARM + incident
    user confirms)       and triage.json                                  logged to incidents.csv
```

* **The LLM never chooses a drug or a dose.** It is optional and only
  pre-fills the form from free text; the user confirms every answer.
  It can pre-mark a red flag as "Yes" but never as "No".
* **The rules engine** (`rules.py`) runs strictly in order and stops at the first exit:
  1. Red-flag triage → emergency / see a doctor today
  2. Demographics and scope (adults only; pregnancy/breastfeeding referred)
  3. Contraindications (conditions, interacting medicines, allergies, age)
  4. 24-hour cap, including hidden paracetamol in combination products, and the minimum interval
  5. Self-care duration limit
  6. Recommendation card with dose, interval, cap, remaining allowance, warnings, source and disclaimer
* **The safety validator** (`validator.py`) re-implements the safety
  arithmetic independently and blocks any output that breaks a hard
  constraint. Blocked outputs show a red alarm and are logged.

## Project structure

```
otc-safe-dose/
├── app.py              Streamlit GUI (stepper, cards, cap bar, emergency/alarm screens, EN/UR)
├── rules.py            Deterministic decision engine (Rules 1-6)
├── validator.py        Independent safety validator (V0-V13)
├── pipeline.py         engine -> validator -> result or BLOCKED
├── incident_log.py     CSV log for validator blocks and user reports
├── llm_intake.py       Optional free-text pre-fill (whitelisted fields only)
├── i18n.py             English / Urdu interface strings
├── formulary.json      Drugs, doses, limits, contraindications (VERIFY placeholders)
├── triage.json         Red flags per complaint, self-care limits, emergency number
├── test_cases.json     104 labelled evaluation cases (draft gold labels)
├── evaluate.py         Penalty-weighted evaluation and fault injection
├── tests/              pytest unit tests (rules, validator, LLM sanitiser)
├── notebooks/          Fully explained Google Colab notebook
├── docs/screenshots/   App screenshots used in this README
├── LICENSE             MIT licence
├── .gitignore          Keeps logs, secrets and caches out of the repository
├── requirements.txt
└── .streamlit/config.toml
```

## Setup and running

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Optional settings (environment variables):

| Variable | Purpose | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Enables the optional free-text pre-fill | not set (form only) |
| `MEDBOT_LLM_MODEL` | Model used for pre-fill | `claude-haiku-5-5` |
| `MEDBOT_EMERGENCY_NUMBER` | Number shown on emergency screens | `1122` |
| `MEDBOT_INCIDENT_LOG` | Path of the incident CSV | `./incidents.csv` |

## Testing and evaluation

```bash
python -m pytest -q tests               # 60 unit tests: every rule and every validator check
python evaluate.py --inject-faults      # penalty scoring + validator stress test
```

`evaluate.py` scores each case twice: the raw engine and the deployed
pipeline (engine plus validator). It reports total penalty, critical-error
count, red-flag sensitivity, over-referral rate, action accuracy and a
confusion table. It exits with code 1 if the pipeline makes any critical
error, so you can use it as a CI gate.

| Event | Penalty | Critical |
|---|---|---|
| Missed red flag (dosed instead of escalating) | -100 | yes |
| Dose above single or 24-h maximum | -100 | yes |
| Contraindicated drug recommended | -80 | |
| Out-of-scope / cap-reached / over-duration case dosed | -60 | |
| Dosed with required information missing* | -60 | |
| Red flag referred instead of escalated* | -20 | |
| Unnecessary referral of a safe case | -5 | |
| Safe first-line option not offered* | -5 | |
| Missing warning or field | -2 | |
| Wrong non-dosing action (e.g., ASK instead of REFER)* | -2 | |

\* Additions to the original specification.

**Fault injection** (`--inject-faults`) feeds deliberately faulty engine
outputs to the validator: tripled doses, an invented drug, a missed
interaction, dropped warnings or disclaimer, ignored prior intake, and a
recommendation issued for red-flag cases. It reports the catch rate for each.

### How to read the current results

The current scores (0 penalty, 100% red-flag sensitivity, 100% catch rate)
show that the code does what the labels say. They do **not** show that the
system is clinically safe. The expected outcomes in `test_cases.json` were
written by the developer from the same rules, so agreement is partly
circular. For a meaningful result:

1. Have one or more clinicians write or review the gold labels without seeing the engine's output.
2. Add cases drawn from real pharmacy queries, including ambiguous ones.
3. Report inter-rater agreement between clinicians (for example, Cohen's kappa).
4. Consider a user study of whether people answer the triage questions correctly. Incorrect self-report is a major real-world failure mode that this evaluation cannot capture.

## Deployment (free)

**Streamlit Community Cloud:** push this folder to a public GitHub repository,
sign in at share.streamlit.io, choose the repository and `app.py`, and
optionally add `ANTHROPIC_API_KEY` under *Secrets*.

**Hugging Face Spaces:** create a new Space, choose the Streamlit or Docker
option offered there, and upload these files. Follow the current Spaces
documentation, because the available templates change over time.

Both platforms use temporary file systems. `incidents.csv` can be lost when
the app restarts. For real incident tracking, write to a persistent store,
such as a database or a private dataset repository.

## Updating the formulary

1. Edit the entry in `formulary.json` using the exact product you dispense (strength, form, label dose, interval, 24-h maximum, contraindications, interactions, warnings).
2. Fill in `source`, set `verified_by` and `verified_date`, and change `status` to `VERIFIED`. Set `_meta.formulary_verification_date`.
3. To add a drug, also list it under the complaint's `candidates` in `triage.json`. Any new contraindication keys must exist in `CONDITION_OPTIONS`, `MED_CATEGORY_OPTIONS` or `ALLERGY_OPTIONS` in `rules.py`.
4. Add test cases for the new entry, then run `pytest` and `python evaluate.py`. Deploy only if both pass.

## Limitations

* **Not a medical device** and not clinically validated. It does not diagnose.
* **Formulary and red flags are unverified placeholders.** A pharmacist and a clinician must review them before any public use.
* **Regulatory approval is required before real patient use.** Software that recommends doses to individuals may be regulated as Software as a Medical Device (SaMD). Check the requirements of the Drug Regulatory Authority of Pakistan (DRAP), or the authority where you deploy.
* Adults only, OTC only, seven complaints only. Children, pregnancy, breastfeeding, chronic kidney/liver disease and older adults on several medicines are referred, not dosed.
* Safety depends on honest, accurate self-report. The app cannot examine the patient.
* Medicine categories are coarse. Uncommon interactions may be missed, so "Other regular medicine" is a prompt to ask a pharmacist, not a check.
* When one ingredient's 24-hour cap is reached, the app refers the user instead of suggesting a different medicine. This is a deliberately conservative choice.
* Clinical questions are English-only. The Urdu toggle translates the interface but not the medical questions, pending professional clinical translation.
