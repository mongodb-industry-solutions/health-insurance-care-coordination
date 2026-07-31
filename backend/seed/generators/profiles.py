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

from dataclasses import dataclass, field


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

    # Timeline & guideline linkage
    enrollment_date: str        # ISO date; anchors the claims timeline
    plan_tier: str              # tier the requested therapy sits in (biologics: specialty)
    guideline_id: str

    # Where the case lands in the bounded-authority model
    case_type: str

    # Insurance / eligibility axis (defaults keep existing profiles unchanged)
    eligibility_status: str = "active"      # "active" | "termed"
    coverage_end_date: str | None = None    # ISO date; set when coverage lapsed

    # Additional standing diagnoses beyond the primary condition. Each is a full
    # diagnosis entry ({code, system, display, status}) merged into the member's
    # clinical_history.diagnoses[]. Kept off the prior-auth path (which keys off
    # the primary diagnosis_code); exists so other consumers — e.g. a care-gaps
    # platform — can read comorbidities from the same member object.
    comorbidities: list[dict] = field(default_factory=list)

    # Small notes that make the narrative legible in the data
    tags: list[str] = field(default_factory=list)

    # --- Official-data-model additions (defaults keep existing literals valid) ---
    # The member references a Policy (which references the plan). If unset, the
    # generator derives one deterministically from the member id.
    policy_number: str | None = None
    state: str = "OH"
    preferred_language: str = "en"          # ISO language code
    provider_id: str | None = None          # embedded managing-provider id
    provider_specialty: str = "Rheumatology"
    annual_premium: float = 4200.0          # modeled, not used in any math


# --- Maria: the canonical clean-approval story from the narrative ------------

MARIA = PatientProfile(
    member_id="MBR-2026-44109",
    plan_id="PLAN-PPO-7731",
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
    enrollment_date="2025-10-01",
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
    plan_id="PLAN-PPO-7731",
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
    enrollment_date="2025-09-15",
    plan_tier="specialty",
    guideline_id="CMG-PSA-2026.1",
    case_type="clean_approval",
    tags=["psoriatic-arthritis", "step-therapy-satisfied", "clean"],
)


# --- Aisha: genuinely ambiguous -> routed to a medical director -------------

AISHA = PatientProfile(
    member_id="MBR-2026-60417",
    plan_id="PLAN-HMO-4420",
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
    enrollment_date="2025-11-01",
    plan_tier="specialty",
    guideline_id="CMG-IBD-2026.2",
    case_type="human_review",
    tags=["crohns", "comorbidities", "atypical-presentation"],
)


# --- David: step therapy not met -> denial recommendation, MD must close ----

DAVID = PatientProfile(
    member_id="MBR-2026-73305",
    plan_id="PLAN-PPO-7731",
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
    enrollment_date="2026-02-01",
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
    plan_id="PLAN-HMO-STD-3300",   # standard-only plan: specialty NOT covered
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
    enrollment_date="2025-08-01",
    plan_tier="specialty",         # the therapy needs specialty; her plan doesn't cover it
    guideline_id="CMG-RA-2026.3",
    case_type="coverage_denial",
    tags=["rheumatoid-arthritis", "step-therapy-satisfied", "specialty-not-covered"],
)


# --- Frank: coverage lapsed before the request — eligibility fails -----------

FRANK = PatientProfile(
    member_id="MBR-2026-90733",
    plan_id="PLAN-PPO-7731",
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
    managing_provider="Dr. Okafor",
    enrollment_date="2025-03-01",
    plan_tier="specialty",
    guideline_id="CMG-PSA-2026.1",
    case_type="ineligible",
    eligibility_status="termed",
    coverage_end_date="2026-05-31",   # coverage ended before the (2026) request
    tags=["psoriatic-arthritis", "coverage-lapsed", "ineligible"],
)


ALL_PROFILES = [MARIA, ROBERT, AISHA, DAVID, GRACE, FRANK]
