import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rules import default_knowledge  # noqa: E402


@pytest.fixture
def kb():
    return default_knowledge()


@pytest.fixture
def patient(kb):
    """Factory for a complete, low-risk adult patient; override fields via kwargs."""
    def make(complaint="headache", **kw):
        p = dict(complaint=complaint, symptom_days=1,
                 red_flags={f["id"]: False for f in kb.red_flags_for(complaint)},
                 age=30, sex="female", weight_kg=65, pregnant=False, breastfeeding=False,
                 conditions=[], current_meds=[], allergies=[], alcohol_regular=False,
                 num_regular_meds=0, prior_intake=[])
        p.update(kw)
        return p
    return make


def intake(ing, mg, hours):
    return [{"ingredient": ing, "total_mg_24h": mg, "hours_since_last": hours}]
