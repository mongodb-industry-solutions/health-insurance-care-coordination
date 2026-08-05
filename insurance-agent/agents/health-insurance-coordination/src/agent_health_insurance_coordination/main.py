"""
Prior-authorization agent built on the Magenta SDK.

Implements the data model and tool catalog documented in
`insurance-agent/sources/Prior_Authorization_Agent_Reference.md`:

- the Member document is read once as the operational foundation, with Policy,
  Plan, Claim, Audit Log and Clinical Guideline read alongside it
- every reasoning step is written to an Audit Log trace tagged with the memory
  type it represents (semantic / taxonomic / episodic / procedural)
- bounded authority is enforced in the tools themselves: the agent may close
  administrative determinations and high-confidence approvals, but a clinical
  denial can only ever be closed by a medical director

The platform launches this code in supported runtime roles:
    RUNNER_MODE=aer            -> Full LangGraph execution
    RUNNER_MODE=tool           -> Tool function execution
    RUNNER_MODE=memory-server  -> Long-term memory service
"""

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Annotated, Literal, Optional, TypedDict, cast

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from magenta_sdklanggraph import App
from runner_shared.models import SuspendPayload

from agent_health_insurance_coordination.pa_store import (
    CLINICAL_MEMORY_TYPES,
    ClaimProvider,
    NewClaim,
    ReasoningStep,
    aggregate_confidence,
    check_treatment_coverage as coverage_for_plan,
    create_prior_auth_store,
    evaluate_eligibility,
    evaluate_step_therapy as apply_step_therapy_gate,
    new_claim_id,
    summarize_trial_history,
    today_iso,
)

# =============================================================================
# Logging Setup
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)
load_dotenv()

# =============================================================================
# Configuration
# =============================================================================

# MongoDB config. The prior-authorization data model lives in
# `health_insurance_agent`, which is created and seeded outside this app —
# never point this at another database and never reshape what is already there.
MONGODB_URI = os.environ.get("MONGODB_URI", "")
MONGODB_DATABASE = os.environ.get("MONGODB_DATABASE", "health_insurance_agent")


def _build_runtime_llm() -> BaseChatModel:
    """Create the default chat model from agent.yaml hints + environment secrets."""
    llm_config = getattr(app, "llm_config", None)
    configured_provider = (getattr(llm_config, "provider", None) or "").strip().lower()
    configured_model = getattr(llm_config, "model", None)
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    anthropic_base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
    openai_base_url = os.environ.get("OPENAI_BASE_URL", "")

    def _build_gemini() -> BaseChatModel:
        from langchain_google_genai import ChatGoogleGenerativeAI

        model_name = configured_model or "gemini-2.5-flash"
        return cast(Any, ChatGoogleGenerativeAI)(
            api_key=gemini_key,
            model=model_name,
            temperature=0,
        )

    def _build_openai() -> BaseChatModel:
        from langchain_openai import ChatOpenAI

        model_name = configured_model or "gpt-5.4-mini"
        kwargs: dict[str, Any] = {
            "api_key": openai_key,
            "model": model_name,
            "temperature": 0,
        }
        if openai_base_url:
            if "grove-foundry" in openai_base_url:
                kwargs["base_url"] = openai_base_url.split("/v1")[0] + "/v1"
                kwargs["default_headers"] = {"api-key": openai_key}
            else:
                kwargs["base_url"] = openai_base_url.rstrip("/")
        return cast(Any, ChatOpenAI)(**kwargs)

    def _build_anthropic() -> BaseChatModel:
        from langchain_anthropic import ChatAnthropic

        model_name = configured_model or "claude-sonnet-4-6"
        kwargs = {
            "api_key": anthropic_key,
            "model_name": model_name,
            "temperature": 0,
        }
        if anthropic_base_url:
            if "grove-foundry" in anthropic_base_url:
                kwargs["base_url"] = anthropic_base_url.split("/v1")[0].rstrip("/")
                kwargs["default_headers"] = {"api-key": anthropic_key}
            else:
                kwargs["base_url"] = anthropic_base_url.rstrip("/")
        return cast(Any, ChatAnthropic)(**kwargs)

    builders = {
        "gemini": (gemini_key, _build_gemini),
        "openai": (openai_key, _build_openai),
        "anthropic": (anthropic_key, _build_anthropic),
    }

    if configured_provider:
        if configured_provider not in builders:
            raise RuntimeError(
                "Unsupported config.provider in agent.yaml. Use one of: anthropic, gemini, openai."
            )
        provider_key, provider_builder = builders[configured_provider]
        if provider_key:
            return provider_builder()
        raise RuntimeError(
            f"agent.yaml config.provider is set to {configured_provider!r}, "
            "but the matching API key is missing from .env."
        )

    for provider_key, provider_builder in builders.values():
        if provider_key:
            return provider_builder()

    raise RuntimeError(
        "No LLM API key found. Set GEMINI_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY."
    )


# =============================================================================
# Runtime Setup
# =============================================================================
APP_NAME = "Health insurance coordination"

app = App(
    app_name=APP_NAME,
)
logger.info("✅ App created")

store = create_prior_auth_store(MONGODB_URI, MONGODB_DATABASE)

# =============================================================================
# Decision Constants
# =============================================================================

# Outcomes the model recognises, shared by audit_log.outcome.decision and
# claims.status.
VALID_DECISIONS = ("approved", "approved_restricted", "denied", "pending")

# Grounds on which the agent itself may close a case (Guardrails table, §7 of
# the reference document). Everything else goes to a medical director.
AGENT_CLOSABLE_REASONS = (
    "benefit_exclusion",
    "eligibility_lapsed",
    "clinical_approval_within_threshold",
)

# Used when a guideline is unavailable, so an approval can never be closed by
# the agent on a permissive default.
DEFAULT_CONFIDENCE_THRESHOLD = 0.90

ESCALATION_REASON_CLINICAL_DENIAL = "clinical_denial_requires_physician_closure"
ESCALATION_REASON_LOW_CONFIDENCE = "confidence_below_guideline_threshold"


# =============================================================================
# Tool helpers
# =============================================================================


def _no_store() -> str:
    return json.dumps(
        {
            "error": "MongoDB is not configured. Set MONGODB_URI in .env; "
            f"MONGODB_DATABASE must remain {MONGODB_DATABASE!r}."
        }
    )


def _split_list(raw: str) -> list[str]:
    """Parse a delimited tool argument into a list.

    Tool arguments stay scalar strings so every provider's function-calling
    schema handles them identically. `;`, newlines and `|` separate items;
    spaces never do, because the items themselves contain spaces.
    """
    if not raw:
        return []
    for delimiter in ("\n", "|"):
        raw = raw.replace(delimiter, ";")
    return [part.strip() for part in raw.split(";") if part.strip()]


def _as_object(raw: str) -> dict:
    """Parse a step input/output argument, accepting JSON or plain prose."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {"summary": raw}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _guideline_threshold(guideline: Optional[dict]) -> float:
    if not guideline:
        return DEFAULT_CONFIDENCE_THRESHOLD
    return float(guideline.get("confidence_threshold") or DEFAULT_CONFIDENCE_THRESHOLD)


def _has_clinical_reasoning(trace: dict) -> bool:
    """True when episodic/procedural steps were recorded on this trace.

    This is what distinguishes a clinical determination from an administrative
    one, and therefore who is allowed to close it.
    """
    return any(
        (step.get("memoryType") or "") in CLINICAL_MEMORY_TYPES for step in trace.get("steps") or []
    )


# =============================================================================
# Member context tools
# =============================================================================


@app.tool(is_local=False)
def get_member_profile(member_id: str) -> str:
    """Retrieve the full Member record — the starting point of every request.

    Returns eligibility, demographics, clinical history (diagnoses, medications,
    treatment responses, clinical notes), the current care plan and the rolling
    summary. Call this before any other tool when handling a new request.

    Args:
        member_id: Member business key (e.g. "MBR-2026-44109")
    """
    if store is None:
        return _no_store()
    member = store.get_member(member_id)
    if not member:
        return json.dumps({"error": f"No member found: {member_id}"})
    return json.dumps(member, indent=2, default=str)


@app.tool(is_local=False)
def get_member_claims(member_id: str) -> str:
    """List every claim filed for a member, in service-date order.

    Use this to see the member's care and pharmacy history, including the fills
    that reveal refill gaps in a step-therapy trial.

    Args:
        member_id: Member business key (e.g. "MBR-2026-44109")
    """
    if store is None:
        return _no_store()
    claims = store.list_claims_by_member(member_id)
    return json.dumps({"count": len(claims), "claims": claims}, indent=2, default=str)


@app.tool(is_local=False)
def get_comparable_cases(
    condition: str,
    drug_class: str = "",
    prior_therapy_months: float = 0.0,
) -> str:
    """Episodic memory across members: prior outcomes for a similar clinical profile.

    Returns aggregate counts, trace/claim identifiers and de-identified
    presentation profiles only — never another member's PHI. Use it to support
    the current case's reasoning, never to replace it.

    Args:
        condition: ICD-10 code (e.g. "M06.9")
        drug_class: Drug class being requested (e.g. "biologic")
        prior_therapy_months: Documented months of prior conventional therapy
    """
    if store is None:
        return _no_store()
    result = store.find_comparable_cases(condition, drug_class, prior_therapy_months)
    return json.dumps(result, indent=2, default=str)


@app.tool(is_local=False)
def update_member_summary(
    member_id: str,
    last_authorization_status: str,
    open_authorization_delta: int = 0,
) -> str:
    """Refresh Member.summary after a decision closes. Never leave it stale.

    Run this at the end of every closed decision so the next request starts from
    an already-informed record.

    Args:
        member_id: Member business key
        last_authorization_status: Status of the decision just recorded
            (approved, approved_restricted, denied, pending_review)
        open_authorization_delta: +1 when opening an authorization, -1 when one closes
    """
    if store is None:
        return _no_store()
    summary = store.update_member_summary(
        member_id, last_authorization_status, open_authorization_delta
    )
    if summary is None:
        return json.dumps({"error": f"No member found: {member_id}"})
    return json.dumps({"memberId": member_id, "summary": summary}, indent=2, default=str)


# =============================================================================
# Policy & Plan tools
# =============================================================================


@app.tool(is_local=False)
def get_policy_by_member(member_id: str) -> str:
    """Retrieve the Policy held by a member (Member.policyId -> Policy.policyNumber).

    Args:
        member_id: Member business key (e.g. "MBR-2026-44109")
    """
    if store is None:
        return _no_store()
    policy = store.get_policy_by_member(member_id)
    if not policy:
        return json.dumps({"error": f"No policy found for member: {member_id}"})
    return json.dumps(policy, indent=2, default=str)


@app.tool(is_local=False)
def verify_eligibility_on_date(policy_id: str, service_date: str = "") -> str:
    """First administrative gate: was coverage active on the requested service date?

    Evaluates policy status together with the effective period. If `eligible` is
    false with reason "eligibility_lapsed", STOP: record the gate on the trace,
    recommend denial, and close it yourself as an administrative determination.
    No clinical reasoning should run.

    Args:
        policy_id: Policy number (e.g. "POL-2026-90733")
        service_date: Date of service as YYYY-MM-DD. Defaults to today.
    """
    if store is None:
        return _no_store()
    policy = store.get_policy(policy_id)
    if not policy:
        return json.dumps({"error": f"No policy found: {policy_id}"})
    result = evaluate_eligibility(policy, service_date or today_iso())
    result["policyId"] = policy.get("policyNumber")
    result["planId"] = policy.get("planId")
    result["serviceDate"] = service_date or today_iso()
    return json.dumps(result, indent=2, default=str)


@app.tool(is_local=False)
def get_plan_by_policy(plan_id: str) -> str:
    """Retrieve the Plan a policy is enrolled in, including treatments[] and steps[].

    Args:
        plan_id: Plan business key from Policy.planId (e.g. "PLAN-PPO-7731")
    """
    if store is None:
        return _no_store()
    plan = store.get_plan(plan_id)
    if not plan:
        return json.dumps({"error": f"No plan found: {plan_id}"})
    return json.dumps(plan, indent=2, default=str)


@app.tool(is_local=False)
def check_treatment_coverage(
    plan_id: str,
    treatment_code: str = "",
    condition: str = "",
    drug: str = "",
) -> str:
    """Second administrative gate: does the plan cover this treatment, and which steps?

    Resolves the treatment by code + condition, or by drug name + condition when
    no code is known. Interpret the result as follows:
    - covered false -> STOP. Recommend denial and close it yourself as a
      benefit-exclusion administrative determination; no clinical reasoning runs.
    - restriction "partial" -> the decision must be `approved_restricted`, never a
      plain approval; the member carries the cost of the uncovered steps.

    Args:
        plan_id: Plan business key (e.g. "PLAN-PPO-7731")
        treatment_code: Treatment/procedure code (e.g. "J3590")
        condition: ICD-10 code the treatment is requested for (e.g. "M06.9")
        drug: Drug name, used when no treatment code is available (e.g. "secukinumab")
    """
    if store is None:
        return _no_store()
    plan = store.get_plan(plan_id)
    if not plan:
        return json.dumps({"error": f"No plan found: {plan_id}"})
    result = coverage_for_plan(plan, treatment_code, condition, drug)
    result["planId"] = plan.get("planId")
    return json.dumps(result, indent=2, default=str)


# =============================================================================
# Clinical guideline / reasoning tools
# =============================================================================


@app.tool(is_local=False)
def get_applicable_guideline(condition: str) -> str:
    """Retrieve the current Clinical Guideline for a condition.

    This is the reference data the clinical steps reason over: drug
    classification (taxonomic memory), step-therapy criteria (procedural
    memory), and the `confidence_threshold` the bounded-authority gate uses.
    Its `_id` is what the trace records as contextSnapshot.guidelineRef.

    Args:
        condition: ICD-10 code (e.g. "M06.9")
    """
    if store is None:
        return _no_store()
    guideline = store.get_guideline_for_condition(condition)
    if not guideline:
        return json.dumps({"found": False, "condition": condition})
    return json.dumps({"found": True, "guidelineRef": guideline["_id"], **guideline}, default=str)


@app.tool(is_local=False)
def normalize_clinical_concept(
    requested_drug: str,
    member_id: str = "",
    member_diagnosis_codes: str = "",
) -> str:
    """Semantic memory: confirm the requested treatment and the member's on-file
    diagnosis refer to the same clinical concept, even across vocabularies.

    Reads the member's diagnoses straight off the Member record (pass
    `member_diagnosis_codes` only to override them), and matches them against
    the conditions the guidelines classify this drug under.

    Args:
        requested_drug: Drug being requested (e.g. "secukinumab")
        member_id: Member business key, used to read diagnoses from the record
        member_diagnosis_codes: Optional override, e.g. "M06.9;I10"
    """
    if store is None:
        return _no_store()

    codes = [c.upper() for c in _split_list(member_diagnosis_codes)]
    if not codes and member_id:
        member = store.get_member(member_id)
        if not member:
            return json.dumps({"error": f"No member found: {member_id}"})
        codes = [
            (d.get("code") or "").upper()
            for d in ((member.get("clinical_history") or {}).get("diagnoses") or [])
            if (d.get("status") or "active") == "active"
        ]
    if not codes:
        return json.dumps(
            {"matched": False, "reason": "no_diagnosis_codes_available", "confidence": 0.0}
        )

    guidelines = store.find_guidelines_classifying(requested_drug)
    guideline_conditions = [(g.get("condition") or "").upper() for g in guidelines]
    matched = [c for c in codes if c in guideline_conditions]

    if matched:
        return json.dumps(
            {
                "matched": True,
                "matchedCondition": matched[0],
                "guidelineRef": next(
                    g["_id"] for g in guidelines if (g.get("condition") or "").upper() == matched[0]
                ),
                "confidence": 0.98,
                "detail": (
                    f"Matched requested therapy {requested_drug} to condition {matched[0]} "
                    "already on the member record."
                ),
            },
            indent=2,
        )
    return json.dumps(
        {
            "matched": False,
            "matchedCondition": None,
            "memberDiagnosisCodes": codes,
            "guidelineConditions": guideline_conditions,
            "confidence": 0.40,
            "detail": (
                f"No guideline classifies {requested_drug} for any condition on this member's "
                "record. Treat the clinical concept as unconfirmed and escalate."
            ),
        },
        indent=2,
    )


@app.tool(is_local=False)
def classify_treatment(drug: str, condition: str) -> str:
    """Taxonomic memory: a treatment's class, tier and prior-auth status.

    Reads Clinical Guideline.classification. When the drug is not individually
    enumerated, reasons from the category — the guideline for the condition
    still fixes the coverage tier — and returns a lower confidence to reflect
    that the answer was inferred rather than stated.

    Args:
        drug: Drug name (e.g. "secukinumab")
        condition: ICD-10 code (e.g. "M06.9")
    """
    if store is None:
        return _no_store()
    guideline = store.get_guideline_for_condition(condition)
    if not guideline:
        return json.dumps(
            {"error": f"No clinical guideline on file for condition {condition}", "confidence": 0.0}
        )

    classification = (guideline.get("classification") or {}).get(drug.strip().lower())
    if classification:
        return json.dumps(
            {
                "class": classification.get("class"),
                "tier": classification.get("tier"),
                "priorAuthRequired": classification.get("prior_auth_required"),
                "guidelineRef": guideline["_id"],
                "inferred": False,
                "confidence": 0.97,
                "detail": (
                    f"Classified {drug} as {classification.get('class')} -> "
                    f"{classification.get('tier')} tier; prior auth required: "
                    f"{classification.get('prior_auth_required')}."
                ),
            },
            indent=2,
        )

    inferred_tier = (guideline.get("criteria") or {}).get("coverage_tier")
    return json.dumps(
        {
            "class": None,
            "tier": inferred_tier,
            "priorAuthRequired": True,
            "guidelineRef": guideline["_id"],
            "inferred": True,
            "confidence": 0.75,
            "detail": (
                f"{drug} is not individually enumerated in {guideline['_id']}. Reasoning from "
                f"category: treatments for {condition} fall under the {inferred_tier} tier and "
                "require prior authorization. Confidence reduced because this was inferred."
            ),
        },
        indent=2,
    )


@app.tool(is_local=False)
def evaluate_step_therapy(
    condition: str,
    documented_drug: str,
    documented_months: float,
    required_drug: str = "",
    required_months: float = 0.0,
) -> str:
    """Procedural memory: apply the encoded step-therapy criteria to the documented trial.

    When `required_drug`/`required_months` are omitted they are read from the
    guideline for the condition, so the same versioned criteria are applied to
    every member with that condition.

    Args:
        condition: ICD-10 code (e.g. "M06.9")
        documented_drug: Conventional therapy documented on the member record
        documented_months: Effective documented trial duration in months
        required_drug: Optional override of the required conventional therapy
        required_months: Optional override of the required minimum duration
    """
    if store is None:
        return _no_store()
    guideline = store.get_guideline_for_condition(condition)
    criteria = ((guideline or {}).get("criteria") or {}).get("step_therapy") or {}
    needed_drug = required_drug or criteria.get("drug") or ""
    needed_months = float(required_months or criteria.get("min_months") or 0)

    if not needed_drug or not needed_months:
        return json.dumps(
            {
                "error": f"No step-therapy criteria on file for condition {condition}",
                "satisfied": False,
                "confidence": 0.0,
            }
        )

    result = apply_step_therapy_gate(float(documented_months), needed_months)
    drug_matches = documented_drug.strip().lower() == needed_drug.strip().lower()
    if not drug_matches:
        result["satisfied"] = False
        result["confidence"] = 0.85
        result["detail"] = (
            f"Step therapy requires {needed_drug}; the documented trial is {documented_drug} "
            "— required conventional therapy not documented."
        )

    result.update(
        {
            "condition": condition.upper(),
            "requiredDrug": needed_drug,
            "requiredMonths": needed_months,
            "documentedDrug": documented_drug,
            "documentedMonths": documented_months,
            "guidelineRef": (guideline or {}).get("_id"),
            "confidenceThreshold": _guideline_threshold(guideline),
        }
    )
    return json.dumps(result, indent=2, default=str)


@app.tool(is_local=False)
def review_treatment_response_history(member_id: str, drug: str) -> str:
    """Episodic memory, within-member: investigate the member's own trial history.

    Establishes the effective trial duration and surfaces anomalies (a
    medication hold, a refill gap) before one invalidates an otherwise adequate
    trial. An anomaly that no clinical note explains must NOT be resolved in the
    member's favour: it lowers confidence and leans toward escalation.

    Args:
        member_id: Member business key
        drug: Conventional therapy to review (e.g. "Methotrexate")
    """
    if store is None:
        return _no_store()
    member = store.get_member(member_id)
    if not member:
        return json.dumps({"error": f"No member found: {member_id}"})

    result = summarize_trial_history(member, drug)
    unexplained = result["anomalyDetected"] and not result["anomalyExplained"]
    result["confidence"] = 0.60 if unexplained else 0.95
    if unexplained:
        result["detail"] = (
            f"An interruption in the {drug} trial is on file but no clinical note explains it. "
            "Do not credit the full duration — reduce confidence and escalate."
        )
    elif result["anomalyDetected"]:
        result["detail"] = (
            f"Member trial: {drug} {result['effectiveTrialMonths']:g} months documented. "
            f"An interruption was investigated and explained: {result['explanation']}"
        )
    else:
        result["detail"] = (
            f"Member trial: {drug} {result['effectiveTrialMonths']:g} months documented; "
            "no interruptions on file."
        )
    return json.dumps(result, indent=2, default=str)


@app.tool(is_local=False)
def compute_decision_confidence(step_confidences: str, criteria_satisfied: bool = True) -> str:
    """Aggregate step confidences into the overall decision confidence.

    The aggregation is fixed and documented, because the bounded-authority gate
    keys off this number: the overall confidence is the MINIMUM of the step
    confidences, minus a fixed 0.55 penalty when a clinical criterion was
    evaluated and not satisfied. High confidence that a criterion failed is not
    confidence in the adverse decision that follows.

    Args:
        step_confidences: Step confidences, e.g. "0.98;0.97;0.95;0.90"
        criteria_satisfied: False when a clinical gate (e.g. step therapy) failed
    """
    values: list[float] = []
    for raw in _split_list(step_confidences.replace(",", ";")):
        try:
            values.append(float(raw))
        except ValueError:
            return json.dumps({"error": f"Not a confidence value: {raw!r}"})
    if not values:
        return json.dumps({"error": "No step confidences provided"})

    overall = aggregate_confidence(values, criteria_satisfied)
    return json.dumps(
        {
            "overallConfidence": overall,
            "stepConfidences": values,
            "criteriaSatisfied": criteria_satisfied,
            "method": "min(stepConfidences) - 0.55 when a clinical criterion is not satisfied",
        },
        indent=2,
    )


# =============================================================================
# Claim tools
# =============================================================================


@app.tool(is_local=False)
def create_claim(
    member_id: str,
    procedure_code: str,
    procedure_desc: str,
    diagnosis_code: str,
    diagnosis_display: str,
    billed_amt: float,
    claim_type: str = "specialty_pharmacy",
    service_date: str = "",
) -> str:
    """Open a claim for a requested or delivered service, with status "pending".

    The policy comes from the Member record and the treating provider from
    `current_care_plan.managing_provider`, so the claim is consistent with the
    record it was raised from.

    Args:
        member_id: Member business key
        procedure_code: Procedure/service code; must match Plan.treatments[].treatmentCode
        procedure_desc: Human-readable description of the procedure
        diagnosis_code: Diagnosis supporting medical necessity; matches treatments[].condition
        diagnosis_display: Human-readable diagnosis description
        billed_amt: Total amount billed by the provider
        claim_type: specialty_pharmacy, pharmacy or medical
        service_date: Date of service as YYYY-MM-DD. Defaults to today.
    """
    if store is None:
        return _no_store()
    member = store.get_member(member_id)
    if not member:
        return json.dumps({"error": f"No member found: {member_id}"})

    provider = ((member.get("current_care_plan") or {}).get("managing_provider")) or {}
    if not provider.get("providerId"):
        return json.dumps(
            {"error": f"Member {member_id} has no managing provider on the current care plan"}
        )

    claim = NewClaim(
        claimId=new_claim_id(),
        memberId=member["memberId"],
        policyId=member["policyId"],
        provider=ClaimProvider(
            providerId=provider["providerId"],
            name=provider.get("name", ""),
            specialty=provider.get("specialty", ""),
        ),
        procedureCode=procedure_code.upper(),
        procedureDesc=procedure_desc,
        diagnosisCode=diagnosis_code.upper(),
        diagnosisDisplay=diagnosis_display,
        serviceDate=service_date or today_iso(),
        claimType=claim_type,
        billedAmt=billed_amt,
    )
    try:
        created = store.create_claim(claim)
    except Exception as e:
        return json.dumps({"error": str(e)})
    return json.dumps({"status": "created", "claim": created}, indent=2, default=str)


@app.tool(is_local=False)
def update_claim_status(
    claim_id: str,
    status: str,
    paid_amt: float = 0.0,
    member_owed: float = 0.0,
    denial_reason: str = "",
    linked_audit_trace_id: str = "",
) -> str:
    """Apply the outcome of an authorization decision to its claim.

    Guardrail: a claim can never be marked approved or paid while its linked
    audit trace records a denial or is still pending. The claim and the trace
    must always tell the same story.

    Args:
        claim_id: Claim business key
        status: paid, approved, approved_restricted, denied or pending
        paid_amt: Amount paid by the insurer
        member_owed: Amount owed by the member
        denial_reason: Reason for denial, when applicable
        linked_audit_trace_id: Trace that authorized this claim, if prior auth applied
    """
    if store is None:
        return _no_store()
    claim = store.get_claim(claim_id)
    if not claim:
        return json.dumps({"error": f"No claim found: {claim_id}"})

    trace_id = linked_audit_trace_id or claim.get("linkedAuditTraceId") or ""
    if status in ("approved", "approved_restricted", "paid") and trace_id:
        trace = store.get_trace(trace_id)
        decision = ((trace or {}).get("outcome") or {}).get("decision")
        if decision in ("denied", "pending") or decision is None:
            return json.dumps(
                {
                    "error": "guardrail_blocked",
                    "detail": (
                        f"Cannot set claim {claim_id} to {status!r} while trace {trace_id} "
                        f"records decision {decision!r}. Resolve the trace first."
                    ),
                }
            )

    updates: dict[str, Any] = {
        "status": status,
        "paidAmt": paid_amt,
        "memberOwed": member_owed,
        "denialReason": denial_reason or None,
    }
    if trace_id:
        updates["linkedAuditTraceId"] = trace_id
    updated = store.update_claim(claim_id, updates)
    return json.dumps({"status": "updated", "claim": updated}, indent=2, default=str)


# =============================================================================
# Audit Log / authorization tools
# =============================================================================


@app.tool(is_local=False)
def create_audit_trace(
    subject_ref: str,
    decision_type: str = "PRIOR_AUTHORIZATION",
    subject_type: str = "MEMBER",
    triggered_by: str = "system:pa_agent",
    guideline_ref: str = "",
    input_facts: str = "",
) -> str:
    """Open a new decision trace at the start of a request.

    Every decision — approval, denial or escalation — must have one. Record the
    administrative gate results you already have as `input_facts`.

    Args:
        subject_ref: memberId or claimId this decision concerns
        decision_type: PRIOR_AUTHORIZATION or CLAIM_ADJUDICATION
        subject_type: MEMBER or CLAIM
        triggered_by: System or user that initiated the decision
        guideline_ref: Clinical Guideline _id used (e.g. "CMG-RA-2026.3")
        input_facts: Short factual inputs, separated by ";" or newlines
    """
    if store is None:
        return _no_store()
    trace = store.create_trace(
        decision_type=decision_type,
        subject_ref=subject_ref,
        subject_type=subject_type,
        triggered_by=triggered_by,
        guideline_ref=guideline_ref or None,
        input_facts=_split_list(input_facts),
    )
    return json.dumps({"status": "created", "trace": trace}, indent=2, default=str)


@app.tool(is_local=False)
def append_reasoning_step(
    trace_id: str,
    memory_type: str,
    name: str,
    detail: str,
    confidence: float,
    step_input: str = "",
    step_output: str = "",
) -> str:
    """Record one reasoning step on a trace, tagged by memory type.

    `memory_type` is not optional: it is what makes the four-memory-type claim
    verifiable rather than asserted. `detail` must be a plain-language sentence a
    human reviewer or auditor can read.

    Args:
        trace_id: Trace business key
        memory_type: semantic, taxonomic, episodic or procedural
        name: Short label for the step
        detail: Plain-language explanation of the step's reasoning
        confidence: Step-level confidence, 0-1
        step_input: What the step consumed (JSON object or short prose)
        step_output: What the step produced (JSON object or short prose)
    """
    if store is None:
        return _no_store()
    memory_type = memory_type.strip().lower()
    if memory_type not in ("semantic", "taxonomic", "episodic", "procedural"):
        return json.dumps(
            {
                "error": "invalid_memory_type",
                "detail": "memory_type must be semantic, taxonomic, episodic or procedural.",
            }
        )
    trace = store.get_trace(trace_id)
    if not trace:
        return json.dumps({"error": f"No trace found: {trace_id}"})

    step = ReasoningStep(
        stepId=f"STP-{len(trace.get('steps') or []) + 1:03d}",
        memoryType=cast(Any, memory_type),
        name=name,
        input=_as_object(step_input),
        output=_as_object(step_output),
        confidence=confidence,
        detail=detail,
    )
    updated = store.append_step(trace_id, step)
    return json.dumps({"status": "appended", "trace": updated}, indent=2, default=str)


@app.tool(is_local=False)
def recommend_decision(trace_id: str, decision: str, rationale: str, confidence: float) -> str:
    """Propose an outcome on a trace, without closing the case.

    This tool only ever recommends — it never sets `review.closedBy`. The
    response tells you which closure path applies: when `requires_escalation` is
    true you MUST call `escalate_to_human` next, and you may not close the case
    yourself under any circumstances.

    Args:
        trace_id: Trace business key
        decision: approved, approved_restricted, denied or pending
        rationale: Plain-language summary of the overall decision
        confidence: Overall decision confidence from compute_decision_confidence
    """
    if store is None:
        return _no_store()
    decision = decision.strip().lower()
    if decision not in VALID_DECISIONS:
        return json.dumps(
            {"error": "invalid_decision", "detail": f"decision must be one of {VALID_DECISIONS}"}
        )
    trace = store.get_trace(trace_id)
    if not trace:
        return json.dumps({"error": f"No trace found: {trace_id}"})

    guideline_ref = (trace.get("contextSnapshot") or {}).get("guidelineRef")
    threshold = _guideline_threshold(store.get_guideline(guideline_ref) if guideline_ref else None)
    clinical = _has_clinical_reasoning(trace)

    # Bounded authority, evaluated from the trace itself rather than from the
    # agent's own judgement about what it is allowed to do.
    if decision == "denied" and clinical:
        escalation_reason: Optional[str] = ESCALATION_REASON_CLINICAL_DENIAL
    elif decision == "pending" or confidence < threshold:
        escalation_reason = ESCALATION_REASON_LOW_CONFIDENCE
    else:
        escalation_reason = None

    updated = store.set_outcome(trace_id, decision, rationale, confidence)
    return json.dumps(
        {
            "status": "recommended",
            "traceId": trace_id,
            "outcome": (updated or {}).get("outcome"),
            "confidenceThreshold": threshold,
            "clinicalReasoningPresent": clinical,
            "requiresEscalation": escalation_reason is not None,
            "escalationReason": escalation_reason,
            "nextAction": (
                f"escalate_to_human(reason='{escalation_reason}')"
                if escalation_reason
                else "close_administrative_determination"
            ),
        },
        indent=2,
        default=str,
    )


@app.tool(is_local=True)
def escalate_to_human(
    trace_id: str,
    reason: str,
    case_brief: str,
    final_decision_maker: str = "medical_director",
) -> str:
    """Route a case to a medical director and SUSPEND execution until they respond.

    Must be called — not optionally — whenever `recommend_decision` reports
    `requiresEscalation: true`, i.e. on any clinical denial recommendation and on
    any decision whose confidence is below the guideline threshold.

    When the review resumes with a decision, call `close_by_medical_director`
    with the reviewer's identity, then `update_claim_status`, then
    `update_member_summary`.

    Args:
        trace_id: Trace business key
        reason: Why review is required, e.g. "clinical_denial_requires_physician_closure"
        case_brief: Full brief for the reviewer — member, requested treatment,
            eligibility and coverage findings, the criteria applied, what the
            documented trial shows, and the recommendation with its confidence
        final_decision_maker: Role responsible for closing the case
    """
    if store is None:
        return _no_store()
    trace = store.get_trace(trace_id)
    if not trace:
        return json.dumps({"error": f"No trace found: {trace_id}"})

    store.set_escalation(trace_id, reason, final_decision_maker)
    outcome = trace.get("outcome") or {}

    return SuspendPayload(
        suspend_reason="awaiting_human_review",
        suspend_context={
            "task_id": f"REVIEW-{uuid.uuid4().hex[:8].upper()}",
            "trace_id": trace_id,
            "subject_ref": trace.get("subjectRef"),
            "decision_type": trace.get("decisionType"),
            "recommended_decision": outcome.get("decision"),
            "confidence": outcome.get("confidence"),
            "reason": reason,
            "final_decision_maker": final_decision_maker,
            "case_brief": case_brief,
            "guideline_ref": (trace.get("contextSnapshot") or {}).get("guidelineRef"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "instructions": (
                "Review the brief and close the case with a final determination. "
                "The agent cannot close a clinical denial."
            ),
        },
    ).to_json()


@app.tool(is_local=False)
def close_administrative_determination(
    trace_id: str,
    reason: str,
    closed_by: str = "system:pa_agent",
) -> str:
    """Close a case as the agent — only for determinations the agent may own.

    Permitted reasons:
    - "eligibility_lapsed": the policy was not active on the date of service
    - "benefit_exclusion": the plan does not cover the treatment or its tier
    - "clinical_approval_within_threshold": an approval whose confidence met the
      guideline's threshold

    Hard guardrail: this tool refuses to close a denial that was reached through
    clinical reasoning (any episodic or procedural step on the trace), and
    refuses any trace already routed to a human. That refusal is the literal
    implementation of bounded authority — the agent assembles the case, but it is
    never the final word on a clinical denial.

    Args:
        trace_id: Trace business key
        reason: One of the permitted reasons above
        closed_by: System identity closing the case
    """
    if store is None:
        return _no_store()
    reason = reason.strip().lower()
    if reason not in AGENT_CLOSABLE_REASONS:
        return json.dumps(
            {
                "error": "guardrail_blocked",
                "detail": f"reason must be one of {AGENT_CLOSABLE_REASONS}.",
            }
        )
    trace = store.get_trace(trace_id)
    if not trace:
        return json.dumps({"error": f"No trace found: {trace_id}"})

    outcome = trace.get("outcome") or {}
    decision = outcome.get("decision")
    if not decision:
        return json.dumps(
            {
                "error": "no_recommendation",
                "detail": "Call recommend_decision before closing a case.",
            }
        )
    if (trace.get("audit") or {}).get("reviewRequired") or (trace.get("review") or {}).get(
        "routedToHuman"
    ):
        return json.dumps(
            {
                "error": "guardrail_blocked",
                "detail": (
                    f"Trace {trace_id} is routed to {(trace.get('review') or {}).get('finalDecisionMaker')}. "
                    "Only that reviewer may close it, via close_by_medical_director."
                ),
            }
        )

    if reason == "clinical_approval_within_threshold":
        if decision not in ("approved", "approved_restricted"):
            return json.dumps(
                {
                    "error": "guardrail_blocked",
                    "detail": f"Decision is {decision!r}; this reason only closes approvals.",
                }
            )
        guideline_ref = (trace.get("contextSnapshot") or {}).get("guidelineRef")
        threshold = _guideline_threshold(
            store.get_guideline(guideline_ref) if guideline_ref else None
        )
        if float(outcome.get("confidence") or 0) < threshold:
            return json.dumps(
                {
                    "error": "guardrail_blocked",
                    "detail": (
                        f"Confidence {outcome.get('confidence')} is below the guideline threshold "
                        f"{threshold}. Escalate to a medical director instead."
                    ),
                }
            )
    elif decision == "denied" and _has_clinical_reasoning(trace):
        return json.dumps(
            {
                "error": "guardrail_blocked",
                "detail": (
                    "This denial was reached through clinical reasoning (episodic/procedural "
                    "steps are on the trace), so it is not an administrative determination. "
                    "Call escalate_to_human — only a medical director may close a clinical denial."
                ),
            }
        )

    if not closed_by.startswith("system:"):
        return json.dumps(
            {
                "error": "guardrail_blocked",
                "detail": "closed_by must be a system identity, e.g. 'system:pa_agent'.",
            }
        )

    closed = store.close_trace(
        trace_id,
        closed_by=closed_by,
        final_decision_maker="agent",
        regulatory_flag=reason if reason != "clinical_approval_within_threshold" else None,
    )
    return json.dumps(
        {
            "status": "closed",
            "traceId": trace_id,
            "reason": reason,
            "decision": decision,
            "review": (closed or {}).get("review"),
            "nextAction": "update_claim_status, then update_member_summary",
        },
        indent=2,
        default=str,
    )


@app.tool(is_local=False)
def close_by_medical_director(
    trace_id: str,
    closed_by: str,
    final_decision: str,
    override_flag: bool = False,
    override_reason: str = "",
) -> str:
    """Record a medical director's final determination on an escalated case.

    Call this only after `escalate_to_human` has resumed with a human decision,
    passing that human's identity — the agent may never supply a system identity
    here, and may never invent a determination the reviewer did not give.

    Args:
        trace_id: Trace business key
        closed_by: The reviewer's name or ID (e.g. "Dr. R. Sandoval")
        final_decision: approved, approved_restricted, denied or pending
        override_flag: True when the human overrode the recommendation
        override_reason: Why the recommendation was overridden
    """
    if store is None:
        return _no_store()
    final_decision = final_decision.strip().lower()
    if final_decision not in VALID_DECISIONS:
        return json.dumps(
            {"error": "invalid_decision", "detail": f"decision must be one of {VALID_DECISIONS}"}
        )
    if not closed_by or closed_by.startswith("system:") or closed_by.strip().lower() == "agent":
        return json.dumps(
            {
                "error": "guardrail_blocked",
                "detail": "closed_by must identify the human reviewer, not a system identity.",
            }
        )
    trace = store.get_trace(trace_id)
    if not trace:
        return json.dumps({"error": f"No trace found: {trace_id}"})
    if not (trace.get("review") or {}).get("routedToHuman"):
        return json.dumps(
            {
                "error": "guardrail_blocked",
                "detail": (
                    f"Trace {trace_id} was never escalated. Call escalate_to_human first, or "
                    "close it with close_administrative_determination if the agent may own it."
                ),
            }
        )

    recommended = (trace.get("outcome") or {}).get("decision")
    override = {
        "overrideFlag": bool(override_flag or final_decision != recommended),
        "overrideBy": closed_by,
        "overrideReason": override_reason or None,
        "decision": final_decision,
    }
    closed = store.close_trace(
        trace_id,
        closed_by=closed_by,
        final_decision_maker=(trace.get("review") or {}).get("finalDecisionMaker")
        or "medical_director",
        override=override,
    )
    return json.dumps(
        {
            "status": "closed",
            "traceId": trace_id,
            "recommendedDecision": recommended,
            "finalDecision": final_decision,
            "outcome": (closed or {}).get("outcome"),
            "review": (closed or {}).get("review"),
            "nextAction": "update_claim_status, then update_member_summary, then notify_member",
        },
        indent=2,
        default=str,
    )


@app.tool(is_local=False)
def get_audit_trail(subject_ref: str = "", claim_id: str = "") -> str:
    """Reconstruct the complete reasoning history for a member or a claim.

    Read-only regulatory retrieval: returns every trace in full, unedited,
    ordered by creation time, including linkedTraces[] chains. This is the tool a
    regulator-facing report calls.

    Args:
        subject_ref: memberId (or claimId) whose traces to retrieve
        claim_id: Claim business key, to follow linkedAuditTraceId to its trace
    """
    if store is None:
        return _no_store()
    if claim_id:
        traces = store.list_traces_by_claim(claim_id)
    elif subject_ref:
        traces = store.list_traces(subject_ref)
    else:
        return json.dumps({"error": "Provide either subject_ref or claim_id"})
    return json.dumps({"count": len(traces), "traces": traces}, indent=2, default=str)


@app.tool(is_local=True, redact_fields=["message"])
def notify_member(member_id: str, message: str, status: str, trace_id: str = "") -> str:
    """Notify a member about the outcome or progress of an authorization.

    Write the message in plain language, addressed to the member. Note: the
    message body is redacted in execution logs because it can carry PHI.

    Args:
        member_id: Member business key
        message: Member-facing message
        status: Decision status the message concerns
        trace_id: Trace this notification relates to
    """
    if store is None:
        return _no_store()
    notification = store.create_notification(member_id, message, status, trace_id or None)
    # `delivery` rather than `status`: the notification carries its own `status`,
    # which is the decision it concerns, not whether it was sent.
    return json.dumps({"delivery": "sent", "notification": notification}, indent=2, default=str)


# =============================================================================
# Agent Definition
# =============================================================================


class _AgentStateOptional(TypedDict, total=False):
    """Optional fields for agent state (not required in partial updates)."""

    user_id: Optional[str]
    session_id: Optional[str]  # Thread/session ID for conversation tracking
    # Prior-authorization case fields
    member_id: Optional[str]
    policy_id: Optional[str]
    claim_id: Optional[str]
    trace_id: Optional[str]


class AgentState(_AgentStateOptional):
    """State for the prior-authorization workflow.

    Uses inheritance to make optional fields truly optional (not required keys),
    while messages remains required. This allows LangGraph's partial state updates
    to type-check correctly.
    """

    messages: Annotated[list[BaseMessage], add_messages]


SYSTEM_PROMPT = """You are the prior-authorization agent for a health insurer.

## Your Role
You assemble and decide prior-authorization cases for members: you read the
member's record as it already stands, apply the plan's benefits and the clinical
guideline's criteria, and leave a complete, regulator-ready reasoning trace.

You work for the member and the reviewer at once: be quick and decisive where the
facts are mechanical, and careful where clinical judgement is involved.

## Response Rules
- You MUST always end every conversational turn with a natural-language response.
- Tool results are NOT visible to the user — after any tool call, summarize the
  result in your own words. Never end a turn with only a tool call.
- Name the member, the treatment, the decision and the reason in plain language.
  Never quote confidence scores at a member without explaining what they mean.

## The Data Model You Work With
- **Member** is the single, continuously-updated record: eligibility, diagnoses,
  medications, `treatment_responses[]` (the member's own trial history), clinical
  notes, and the current care plan. Read it as-is. Never reconstruct it.
- **Policy** (`Member.policyId` -> `policyNumber`) is the contract; it references
  exactly one **Plan** (`Policy.planId`).
- **Plan** carries `treatments[]`, each with `steps[]` — a treatment is a
  sequence of stages, and a plan can cover some stages but not others.
- **Claim** bridges the health event and the insurance outcome.
- **Audit Log** is the decision trace: memory-tagged reasoning steps, outcome,
  and review closure.
- **Clinical Guideline** is versioned reference data: drug classification and
  step-therapy criteria, plus the `confidence_threshold` for auto-resolution.

## The Four Memory Types
Every reasoning step you record must declare which memory type it represents:
- `semantic` — the requested drug and the member's on-file diagnosis are the same
  clinical concept (`normalize_clinical_concept`)
- `taxonomic` — where the drug sits in the class/tier structure
  (`classify_treatment`)
- `episodic` — the member's own trial history, and comparable past cases
  (`review_treatment_response_history`, `get_comparable_cases`)
- `procedural` — the encoded criteria and gates applied at runtime
  (`evaluate_step_therapy`)

## Workflow — follow this order
1. `get_member_profile(member_id)` — always first. Note the considered therapy,
   the active diagnoses, and the documented trial history.
2. `get_policy_by_member(member_id)`.
3. `verify_eligibility_on_date(policy_id, service_date)` — **administrative gate**.
4. `get_plan_by_policy(plan_id)`.
5. `check_treatment_coverage(plan_id, treatment_code, condition, drug)` —
   **administrative gate**.
6. `get_applicable_guideline(condition)` — gives you the `guidelineRef` and the
   `confidence_threshold`.
7. `create_audit_trace(subject_ref=member_id, guideline_ref=..., input_facts=...)`.
8. Clinical reasoning, appending a step after each with
   `append_reasoning_step`: `normalize_clinical_concept` (semantic),
   `classify_treatment` (taxonomic), `review_treatment_response_history` and
   `get_comparable_cases` (episodic), `evaluate_step_therapy` (procedural).
9. `compute_decision_confidence(step_confidences, criteria_satisfied)`.
10. `recommend_decision(trace_id, decision, rationale, confidence)`.
11. Close the case by the path the recommendation tells you (see below).
12. `update_claim_status`, then `update_member_summary`, then `notify_member`.

### The gates are independent and they short-circuit
- If `verify_eligibility_on_date` returns `eligible: false` → STOP. Open the
  trace, record the eligibility gate as a step, recommend `denied`, and close it
  yourself with `close_administrative_determination(reason="eligibility_lapsed")`.
  Do NOT run any clinical reasoning.
- If `check_treatment_coverage` returns `covered: false` → STOP. Open the trace,
  record the semantic and taxonomic steps if useful, recommend `denied`, and close
  it yourself with `close_administrative_determination(reason="benefit_exclusion")`.
  Do NOT run episodic or procedural reasoning.
- A shorter trace on an administrative determination is CORRECT, not missing
  data: a factual gate decided the case before clinical judgement was relevant.
- If `check_treatment_coverage` returns `restriction: "partial"`, the decision is
  `approved_restricted`, never a plain approval. Tell the member which stages are
  covered and that they carry the cost of the rest.

## Bounded Authority — the rule you may never bend
| Situation | Who closes it |
|---|---|
| Eligibility lapsed | You, `close_administrative_determination` |
| Treatment/tier not covered | You, `close_administrative_determination` |
| Approval with confidence >= guideline threshold | You, `close_administrative_determination(reason="clinical_approval_within_threshold")` |
| **Any clinical denial recommendation** | **Medical director only** |
| Confidence below threshold, in either direction | **Medical director only** |

When `recommend_decision` returns `requiresEscalation: true` you MUST call
`escalate_to_human` immediately, with a `case_brief` complete enough for a
physician to decide without re-reading the record: the member and requested
treatment, the eligibility and coverage findings, the criteria applied, what the
documented trial actually shows, your recommendation and its confidence, and any
anomaly you found. Then say so plainly to the user — the case is with a medical
director, and you do not have the authority to deny it yourself.

After the review resumes, call `close_by_medical_director` with the reviewer's
own name — never a system identity, and never a determination they did not give.

## Investigate Before You Penalize
If `review_treatment_response_history` reports an anomaly (a hold, a refill gap):
- If a clinical note explains it, say so and credit the trial.
- If nothing explains it, do NOT resolve it in the member's favour and do NOT
  silently ignore it. It lowers confidence and the case goes to a human.

## Trace Discipline
- Every decision gets a trace. Every step declares its `memory_type`.
- Every `detail` is a plain-language sentence an auditor can read on its own.
- `recommend_decision` only ever recommends. Only the closure tools close.
- Never leave `Member.summary` stale — `update_member_summary` runs at the end of
  every closed decision.
- Use `get_audit_trail` when asked why a decision was made, or for a compliance
  or regulator-facing answer.
"""


@app.entrypoint
def build_agent(llm: Optional[BaseChatModel] = None) -> CompiledStateGraph:
    """Build the LangGraph agent.

    Args:
        llm: LLM to use. Defaults to app.llm() when None. Pass an explicit
             LLM (e.g. a FakeLLM) for testing without real API calls.
    """
    logger.info("Building LangGraph agent...")

    # Get LLM from runtime
    if llm is None:
        llm = app.llm(_build_runtime_llm())

    # Get tools from runtime (automatically wrapped for SecureToolWrapper in AER mode)
    tools = app.get_tools()

    # Bind tool schemas to LLM
    llm_with_tools = llm.bind_tools(app.get_tool_schemas())

    def agent_node(state: AgentState) -> AgentState:
        messages = state["messages"]
        user_id = state.get("user_id", "")
        session_id = state.get("session_id", "")
        logger.info(f"User ID: {user_id}, Session ID: {session_id}")

        system_prompt = SYSTEM_PROMPT

        # Today's date decides eligibility on the date of service, so state it
        # rather than letting the model assume it.
        system_prompt += f"\n\n## Current Session\nToday's date is {today_iso()}."
        if user_id:
            system_prompt += f" You are speaking with user_id: {user_id}."

        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=system_prompt)] + list(messages)
        else:
            messages = [SystemMessage(content=system_prompt)] + list(messages[1:])

        # Invoke the LLM
        response = llm_with_tools.invoke(messages)

        # Apply guardrails validation to LLM response (if enabled)
        response = app.validate_llm_response(response)

        return {"messages": [response]}

    def should_continue(state: AgentState) -> Literal["tools", "end"]:
        last = state["messages"][-1]
        return "tools" if hasattr(last, "tool_calls") and last.tool_calls else "end"  # type: ignore[union-attr]  # LangChain BaseMessage subclass has tool_calls

    logger.info("  → Compiling graph...")
    builder = StateGraph(AgentState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END})
    builder.add_edge("tools", "agent")

    # A checkpointer needs MongoDB. If it is unreachable the agent should still
    # answer single-turn requests rather than fail to build at all, which would
    # turn every request into a 500.
    try:
        checkpointer = app.checkpointer()
    except Exception as e:
        logger.warning(f"Failed to construct checkpointer ({e}) — running without conversation persistence.")
        checkpointer = None

    graph = builder.compile(checkpointer=checkpointer)
    logger.info("✅ Agent graph compiled")
    return graph


# =============================================================================
# Run
# =============================================================================


def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info(f"🚀 Starting {APP_NAME} (Runner SDK)")
    logger.info(f"   Database: {MONGODB_DATABASE}")
    logger.info("=" * 60)

    app.run()


if __name__ == "__main__":
    main()
