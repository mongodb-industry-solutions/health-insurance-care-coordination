"""Patient profiles that drive synthetic data generation.

A *profile* is a compact, human-readable description of a member and their care
trajectory. The generator (`member_generator.py`) expands each profile into the
full set of documents — member record, adjudicated claims, and an authorization
— that make the record realistic for the agents to read.

Keeping profiles as plain data (not documents) means adding a new, realistic
patient is a matter of describing them, not hand-writing MongoDB documents.

`case_type` encodes where the case lands in the bounded-authority model:
  - "clean_approval"  : criteria-clear, agent confirms (Maria's story)
  - "human_review"    : genuinely ambiguous, routed to a medical director
  - "denial"          : clinical denial recommendation; medical director must close it
  - "coverage_denial" : plan does not cover the requested tier (benefit exclusion)
  - "ineligible"      : coverage lapsed / member not eligible on the plan

The last two are *administrative* determinations (benefit design and eligibility),
distinct from the clinical medical-necessity axis. They can be closed by the agent
because they are factual benefit/eligibility calls, not clinical judgment — the
"a human must close it" rule applies to medical-necessity denials.
"""

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta


# --- Dates are relative, not hardcoded ---------------------------------------
# A profile's dates have to hold two invariants at the moment the demo runs:
#   1. the first-line trial is entirely in the PAST (it is documented history), and
#   2. the policy term still COVERS today (term = enrollment + 1 year, see
#      `member_generator.build_policy`).
# A hardcoded enrollment date satisfies both only for a few months, then silently
# breaks one of them — an expired term turns every case into an eligibility denial
# at Step 1, so profiles that exist to exercise the coverage or clinical steps
# never reach them. Profiles therefore declare *offsets* and the ISO dates the
# generator consumes are derived at seed time.

# Set SEED_TODAY=YYYY-MM-DD to pin the anchor — for reproducing a specific run.
_SEED_TODAY_ENV = "SEED_TODAY"


def seed_today() -> date:
    """The 'today' every profile's dates are measured back from."""
    pinned = os.environ.get(_SEED_TODAY_ENV)
    if pinned:
        return datetime.strptime(pinned.strip(), "%Y-%m-%d").date()
    return date.today()


def _iso(day: date) -> str:
    return day.isoformat()


# A provider is one entity with one id, however many members they treat. Derived
# per-member ids would give Dr. Patel a different id on each of his three
# patients, which is wrong the moment anything groups cases by physician.
#
# `Dr. Patel` and `Dr. Ibrahim` are taken from source/documents/claims.json. The
# other two are not attested in any source document — they follow the same
# PROV-{STATE}-{NNNNN} convention and are scoped to the state each provider
# practises in, but they are invented and should be reconciled if a provider
# registry ever lands upstream.
PROVIDERS = {
    "Dr. Patel": "PROV-IL-00201",       # from claims.json (CLM-IL-2026-77201)
    "Dr. Ibrahim": "PROV-CA-00688",     # from claims.json (CLM-CA-2026-90220)
    "Dr. Okafor": "PROV-TX-00347",      # invented
    "Dr. Nguyen": "PROV-NY-00512",      # invented
}


@dataclass
class TrialGap:
    """A pause in a medication trial the naive matcher would misread."""
    start_offset_days: int      # days after trial start when the gap begins
    duration_days: int
    clinical_reason: str        # the "why" a second agent surfaces from notes


@dataclass
class PatientProfile:
    member_id: str
    plan_id: str
    name: str
    birth_date: str
    gender: str
    occupation: str

    # Condition & first-line (step therapy) trial
    diagnosis_code: str
    diagnosis_system: str
    diagnosis_display: str
    first_line_drug: str
    first_line_rxnorm: str
    trial_months: int
    trial_outcome: str          # e.g. "inadequate"
    trial_gap: TrialGap | None

    # Requested next step (the biologic under consideration)
    considered_therapy: str
    considered_rxnorm: str
    managing_provider: str

    # Timeline & guideline linkage. `enrollment_date` is derived (see below), not
    # declared: it is a function of the trial length and today's date.
    plan_tier: str              # tier the requested therapy sits in (biologics: specialty)
    guideline_id: str

    # Where the case lands in the bounded-authority model
    case_type: str

    # Insurance / eligibility axis (defaults keep existing profiles unchanged)
    eligibility_status: str = "active"      # "active" | "termed"
    # Days before today that coverage ended. Set only for a lapsed member (Frank);
    # `coverage_end_date` below turns it into the ISO date the generator writes.
    coverage_ended_days_ago: int | None = None

    # Days between the end of the first-line trial and today. Keeps the documented
    # history in the past while leaving the policy term (enrollment + 1 year) with
    # ~2 months of runway, so a seeded database stays valid for a while.
    post_trial_settle_days: int = 30

    # Additional standing diagnoses beyond the primary condition. Each is a full
    # diagnosis entry ({code, system, display, status}) merged into the member's
    # clinical_history.diagnoses[]. Kept off the prior-auth path (which keys off
    # the primary diagnosis_code); exists so other consumers — e.g. a care-gaps
    # platform — can read comorbidities from the same member object.
    comorbidities: list[dict] = field(default_factory=list)

    # Small notes that make the narrative legible in the data
    tags: list[str] = field(default_factory=list)

    # --- Official-data-model additions (defaults keep existing literals valid) ---
    # The member references a Policy (which references the plan). Set explicitly
    # from `source/documents/policies_3.json` — the shared source of truth for
    # policy identifiers — rather than derived, so the seeded records line up with
    # the documents the insurance-agent work is written against.
    policy_number: str | None = None
    state: str = "OH"
    preferred_language: str = "en"          # ISO language code
    provider_id: str | None = None          # embedded managing-provider id
    provider_specialty: str = "Rheumatology"
    annual_premium: float = 4200.0          # modeled, not used in any math
    # Distribution attribution carried on the Policy. Opaque to every decision
    # path — present because the official model (and the source documents) carry
    # them, not because anything reads them.
    agent_id: str | None = None
    agency_id: str | None = None

    # --- Derived dates --------------------------------------------------------
    # Mirrors `member_generator._trial_dates`: diagnosis lands 14 days after
    # enrollment, the trial starts 14 days after that, and each trial month is
    # modeled as 30 days. Enrollment is therefore however long ago the whole
    # trajectory needs to have started for it to have finished
    # `post_trial_settle_days` ago.
    DX_OFFSET_DAYS = 14
    TRIAL_START_OFFSET_DAYS = 14
    DAYS_PER_TRIAL_MONTH = 30

    @property
    def enrollment_days_ago(self) -> int:
        return (
            self.DX_OFFSET_DAYS
            + self.TRIAL_START_OFFSET_DAYS
            + self.DAYS_PER_TRIAL_MONTH * self.trial_months
            + self.post_trial_settle_days
        )

    @property
    def enrollment_date(self) -> str:
        """ISO enrollment date; anchors the policy term and the claims timeline."""
        return _iso(seed_today() - timedelta(days=self.enrollment_days_ago))

    @property
    def coverage_end_date(self) -> str | None:
        """ISO date coverage ended, or None while coverage is in force."""
        if self.coverage_ended_days_ago is None:
            return None
        return _iso(seed_today() - timedelta(days=self.coverage_ended_days_ago))


# --- Maria: the canonical clean-approval story from the narrative ------------

MARIA = PatientProfile(
    member_id="MBR-2026-44109",
    plan_id="PLAN-PPO-SPEC-4471",
    policy_number="POL-HP-2026-04410",
    state="IL",
    agent_id="AGT-00118",
    agency_id="AGY-00042",
    name="Maria Reyes",
    birth_date="1983-04-12",
    gender="female",
    occupation="School librarian",
    diagnosis_code="M06.9",
    diagnosis_system="ICD-10",
    diagnosis_display="Rheumatoid arthritis",
    first_line_drug="Methotrexate",
    first_line_rxnorm="6851",
    trial_months=7,
    trial_outcome="inadequate",
    trial_gap=TrialGap(
        # Aligned to the ~day-90 refill so the pharmacy record shows a missing
        # refill (no fill activity) — the "gap" the second agent must explain.
        start_offset_days=88,
        duration_days=10,
        clinical_reason="10-day hold during respiratory infection; not a discontinuation",
    ),
    considered_therapy="secukinumab",
    considered_rxnorm="1656663",
    managing_provider="Dr. Patel",
    plan_tier="specialty",
    guideline_id="CMG-RA-2026.3",
    case_type="clean_approval",
    # Hypertension comorbidity — inert for prior auth, but makes Maria eligible
    # for cardiovascular care-gap measures (e.g. HEDIS CBP) in the care-gaps demo.
    comorbidities=[
        {
            "code": "I10",
            "system": "ICD-10",
            "display": "Essential (primary) hypertension",
            "status": "active",
        }
    ],
    tags=["rheumatoid-arthritis", "step-therapy-satisfied", "explained-gap"],
)


# --- Robert: another clean approval, no gap, different condition ------------

ROBERT = PatientProfile(
    member_id="MBR-2026-51882",
    plan_id="PLAN-PPO-SPEC-4471",
    policy_number="POL-HP-2026-05188",
    state="TX",
    agent_id="AGT-00229",
    agency_id="AGY-00042",
    name="Robert Chen",
    birth_date="1975-11-03",
    gender="male",
    occupation="Warehouse supervisor",
    diagnosis_code="L40.50",
    diagnosis_system="ICD-10",
    diagnosis_display="Psoriatic arthritis",
    first_line_drug="Methotrexate",
    first_line_rxnorm="6851",
    trial_months=8,
    trial_outcome="inadequate",
    trial_gap=None,
    considered_therapy="adalimumab",
    considered_rxnorm="327361",
    managing_provider="Dr. Okafor",
    plan_tier="specialty",
    guideline_id="CMG-PSA-2026.1",
    case_type="clean_approval",
    tags=["psoriatic-arthritis", "step-therapy-satisfied", "clean"],
)


# --- Aisha: genuinely ambiguous -> routed to a medical director -------------

AISHA = PatientProfile(
    member_id="MBR-2026-60417",
    plan_id="PLAN-HMO-SPEC-2290",
    policy_number="POL-HP-2026-06041",
    state="NY",
    agent_id="AGT-00301",
    agency_id="AGY-00077",
    name="Aisha Bello",
    birth_date="1990-07-22",
    gender="female",
    occupation="Graphic designer",
    diagnosis_code="K50.90",
    diagnosis_system="ICD-10",
    diagnosis_display="Crohn's disease",
    first_line_drug="Azathioprine",
    first_line_rxnorm="1256",
    trial_months=6,
    trial_outcome="partial",
    trial_gap=None,
    considered_therapy="ustekinumab",
    considered_rxnorm="1364454",
    managing_provider="Dr. Nguyen",
    plan_tier="specialty",
    guideline_id="CMG-IBD-2026.2",
    case_type="human_review",
    tags=["crohns", "comorbidities", "atypical-presentation"],
)


# --- David: step therapy not met -> denial recommendation, MD must close ----

DAVID = PatientProfile(
    member_id="MBR-2026-73305",
    plan_id="PLAN-PPO-SPEC-4471",
    policy_number="POL-HP-2026-08841",
    agent_id="AGT-00421",
    agency_id="AGY-00071",
    name="David Thompson",
    birth_date="1968-02-17",
    gender="male",
    occupation="Accountant",
    diagnosis_code="M06.9",
    diagnosis_system="ICD-10",
    diagnosis_display="Rheumatoid arthritis",
    first_line_drug="Methotrexate",
    first_line_rxnorm="6851",
    trial_months=3,
    trial_outcome="inadequate",
    trial_gap=None,
    considered_therapy="secukinumab",
    considered_rxnorm="1656663",
    managing_provider="Dr. Patel",
    plan_tier="specialty",
    guideline_id="CMG-RA-2026.3",
    case_type="denial",
    state="IL",
    tags=["rheumatoid-arthritis", "step-therapy-insufficient"],
)


# --- Grace: clinically fine, but her plan does not cover the specialty tier ---
# Benefit (coverage) denial — an administrative call, not a medical-necessity one.

GRACE = PatientProfile(
    member_id="MBR-2026-88214",
    plan_id="PLAN-PPO-STD-1100",   # standard-only plan: specialty NOT covered
    policy_number="POL-HP-2026-08821",
    state="IL",
    agent_id="AGT-00118",
    agency_id="AGY-00042",
    name="Grace Kim",
    birth_date="1979-09-30",
    gender="female",
    occupation="Bus driver",
    diagnosis_code="M06.9",
    diagnosis_system="ICD-10",
    diagnosis_display="Rheumatoid arthritis",
    first_line_drug="Methotrexate",
    first_line_rxnorm="6851",
    trial_months=7,                # step therapy satisfied — isolates the benefit axis
    trial_outcome="inadequate",
    trial_gap=None,
    considered_therapy="secukinumab",
    considered_rxnorm="1656663",
    managing_provider="Dr. Patel",
    plan_tier="specialty",         # the therapy needs specialty; her plan doesn't cover it
    guideline_id="CMG-RA-2026.3",
    case_type="coverage_denial",
    tags=["rheumatoid-arthritis", "step-therapy-satisfied", "specialty-not-covered"],
)


# --- Frank: coverage lapsed before the request — eligibility fails -----------

FRANK = PatientProfile(
    member_id="MBR-2026-90733",
    plan_id="PLAN-PPO-SPEC-4471",
    policy_number="POL-HP-2026-09073",
    state="CA",
    agent_id="AGT-00555",
    agency_id="AGY-00090",
    name="Frank Alvarez",
    birth_date="1972-06-08",
    gender="male",
    occupation="Electrician",
    diagnosis_code="L40.50",
    diagnosis_system="ICD-10",
    diagnosis_display="Psoriatic arthritis",
    first_line_drug="Methotrexate",
    first_line_rxnorm="6851",
    trial_months=8,                # clinically fine — isolates the eligibility axis
    trial_outcome="inadequate",
    trial_gap=None,
    considered_therapy="adalimumab",
    considered_rxnorm="327361",
    # Provider taken from source/documents/claims.json (CLM-CA-2026-90220), the
    # source of truth for this member's care team. Distinct from Robert's
    # Dr. Okafor: Frank is the California case. The id comes from PROVIDERS.
    managing_provider="Dr. Ibrahim",
    plan_tier="specialty",
    guideline_id="CMG-PSA-2026.1",
    case_type="ineligible",
    eligibility_status="termed",
    # Coverage ended a month before the request — the eligibility gate must fail
    # on a date that is in the past however long after seeding the demo runs.
    coverage_ended_days_ago=30,
    tags=["psoriatic-arthritis", "coverage-lapsed", "ineligible"],
)


ALL_PROFILES = [MARIA, ROBERT, AISHA, DAVID, GRACE, FRANK]
