"""Business logic for clinical guidelines (procedural and taxonomic memory)."""

from ..db.mdb import get_connector
from .repository import GuidelineRepository


# Aggregation is the MINIMUM of the step confidences: a chain of reasoning is only as
# strong as its weakest link, and averaging would let four strong steps bury one weak
# one. Fixed and documented rather than tuned, because the bounded-authority gate keys
# off the result and an opaque aggregation would undermine the audit trail.
#
# When a clinical criterion was evaluated and NOT met, a fixed penalty is subtracted.
# High confidence that a criterion failed is not confidence in the resulting adverse
# decision — recording a denial at 0.90 reads as "we are sure this should be denied",
# when the honest reading is "this needs a human". The penalty is what makes the
# recorded number say the latter. Kept aligned with the insurance agent's
# `aggregate_confidence`, so both agents score an identical case identically.
_CLINICAL_FAILURE_PENALTY = 0.55

# Procedural-gate confidence. A failure is scored slightly lower than a pass, not
# because the arithmetic is less certain, but because a shortfall is more often an
# artefact of incomplete documentation than a pass is. A drug mismatch is lower still:
# it means the trial on file is not the one the criteria are about, so the comparison
# answers a different question than the one asked. Kept aligned with the insurance
# agent's `evaluate_step_therapy`.
_STEP_SATISFIED_CONFIDENCE = 0.95
_STEP_NOT_SATISFIED_CONFIDENCE = 0.90
_STEP_DRUG_MISMATCH_CONFIDENCE = 0.85

# Taxonomic-classification confidence. A drug the guideline names is a stated fact;
# one it does not is an inference from the condition's coverage tier. The gap between
# these two numbers is what carries "we reasoned this rather than read it" into the
# Step 7 aggregate. Kept aligned with the insurance agent's `classify_treatment`.
_CLASSIFY_STATED_CONFIDENCE = 0.97
_CLASSIFY_INFERRED_CONFIDENCE = 0.75


def normalize_drug_name(requested: str) -> str:
    """Reduce a requested service string to the bare therapy name.

    Callers pass either the therapy name ("secukinumab") or the full canonical
    service string ("biologic therapy - secukinumab"). `classification` is keyed
    by the bare name, so take the token after the last " - " and lowercase it.
    """
    if not requested:
        return ""
    return requested.split(" - ")[-1].strip().lower()


class GuidelineService:
    """Service layer for guidelines operations.

    Provides access to medical necessity criteria, taxonomic classification
    (reason by category), and procedural memory (decision gates).
    """

    def __init__(self, connector=None):
        connector = connector or get_connector()
        self.repository = GuidelineRepository(connector)

    def get_guideline_for_condition(self, condition_code: str) -> dict:
        """Retrieve the latest guideline for a condition (Phase 1, step 4).

        Returns taxonomic classification and procedural criteria that agents use to
        evaluate medical necessity. The exact version consulted is captured on the
        decision trace's `contextSnapshot.guidelineRef` when the case is processed.
        """
        return self.repository.latest_for_condition(condition_code)

    def get_all_guidelines_for_condition(self, condition_code: str) -> list:
        """Retrieve all guideline versions for a condition (newest first)."""
        return self.repository.find_by_condition(condition_code)

    def get_guideline(self, guideline_id: str) -> dict:
        """Retrieve a specific guideline by ID."""
        return self.repository.get_by_id(guideline_id)

    def list_all_guidelines(self) -> list:
        """Retrieve all guidelines."""
        return self.repository.find()

    @staticmethod
    def _therapy_key(guideline: dict, requested: str) -> str:
        """Resolve the classification key for a requested therapy.

        `classification` is keyed by therapy name (e.g. "secukinumab"), but callers
        pass either that name or the full service string (e.g.
        "biologic therapy - secukinumab"). Try an exact match, then the token after
        the last " - ", then a case-insensitive scan of the classification keys.
        """
        classification = guideline.get("classification", {})
        if not requested:
            return requested
        if requested in classification:
            return requested
        tail = requested.split(" - ")[-1].strip()
        if tail in classification:
            return tail
        for key in classification:
            if key.lower() == tail.lower() or key.lower() == requested.lower():
                return key
        return tail

    def evaluate_coverage_tier(self, guideline: dict, requested_service: str) -> dict:
        """Evaluate whether a requested service meets coverage tier requirements.

        Resolves the therapy name from the requested service so classification —
        which is keyed by therapy name, not the full service string — is found.
        """
        classification = guideline.get("classification", {})
        key = self._therapy_key(guideline, requested_service)
        service_class = classification.get(key, {})

        return {
            "service": requested_service,
            "therapy": key,
            "tier": service_class.get("tier", "unknown"),
            "prior_auth_required": service_class.get("prior_auth_required", False),
            "class": service_class.get("class", "unknown"),
        }

    def get_step_therapy_requirement(self, guideline: dict) -> dict:
        """Extract step therapy requirement from guideline."""
        criteria = guideline.get("criteria", {})
        step_therapy = criteria.get("step_therapy", {})
        return step_therapy or None

    def compute_recommendation(
        self,
        condition_code: str,
        step_confidences: list,
        criteria_satisfied: bool,
        coverage_restriction: str = "none",
    ) -> dict:
        """Step 7: aggregate the reasoning steps and propose a decision.

        Aggregation is the minimum of the step confidences, less a fixed penalty when a
        clinical criterion was evaluated and not met (see `_CLINICAL_FAILURE_PENALTY`).

        The proposal follows from two facts already established upstream — whether the
        criteria were met, and whether coverage was partial:

        * criteria not met                -> `denied`
        * criteria met, coverage partial   -> `approved_restricted`
        * criteria met, coverage full      -> `approved`

        **This only ever recommends.** It reports whether the aggregate clears the
        guideline's threshold, but does not decide who may close the case: that is the
        bounded-authority check in Step 8, and keeping it out of here is what stops this
        step from becoming a closure by accident.

        Returns None when no guideline covers the condition, so the route can 404.
        """
        guideline = self.get_guideline_for_condition(condition_code)
        if not guideline:
            return None

        confidences = [float(c) for c in step_confidences or []]
        weakest = round(min(confidences), 2) if confidences else 0.0
        penalty_applied = bool(confidences) and not criteria_satisfied
        confidence = round(
            max(weakest - _CLINICAL_FAILURE_PENALTY, 0.0) if penalty_applied else weakest, 2
        )

        threshold = guideline.get("confidence_threshold")
        meets_threshold = bool(threshold is not None and confidence >= threshold)
        restricted = (coverage_restriction or "none").strip().lower() == "partial"

        if not criteria_satisfied:
            recommendation = "denied"
            rationale = (
                "Step-therapy criteria were not satisfied, so the requested therapy is not "
                "clinically justified on the record as it stands."
            )
        elif restricted:
            recommendation = "approved_restricted"
            rationale = (
                "Criteria were satisfied, but the plan covers only part of the treatment "
                "protocol, so approval extends to the covered stages only."
            )
        else:
            recommendation = "approved"
            rationale = (
                "Criteria were satisfied and the plan covers the full treatment protocol."
            )

        aggregation = (
            f"min({', '.join(f'{c:g}' for c in confidences)}) = {weakest:g}"
            if confidences
            else "no step confidences supplied"
        )
        if penalty_applied:
            aggregation += f" − {_CLINICAL_FAILURE_PENALTY:g} (criteria not met) = {confidence:g}"

        return {
            "condition": guideline.get("condition"),
            "guideline_ref": guideline.get("_id"),
            "step_confidences": confidences,
            "aggregation": aggregation,
            "weakest_step_confidence": weakest,
            "clinical_failure_penalty_applied": penalty_applied,
            "confidence": confidence,
            "confidence_threshold": threshold,
            "meets_threshold": meets_threshold,
            "criteria_satisfied": bool(criteria_satisfied),
            "coverage_restriction": "partial" if restricted else "none",
            "recommendation": recommendation,
            "rationale": rationale,
            "detail": (
                f"Recommendation: {recommendation} at confidence {confidence:g} "
                f"({aggregation}) against a threshold of "
                f"{threshold if threshold is not None else 'n/a'} — "
                f"{'clears' if meets_threshold else 'does NOT clear'} it. "
                "This is a recommendation only; who may close the case is decided by the "
                "bounded-authority check."
            ),
        }

    def evaluate_step_therapy(
        self,
        condition_code: str,
        documented_drug: str,
        documented_months: float,
    ) -> dict:
        """Step 6 (procedural memory): apply the guideline's step-therapy gate.

        The criteria live in versioned reference data rather than being decided per
        request, so every member with the same condition is held to the same bar —
        which is what makes the decision defensible as non-discriminatory.

        Two ways to fail, kept distinct because they mean different things:

        * the trial is of the right drug but too short — a genuine shortfall;
        * the trial is of a different drug entirely — the required conventional therapy
          is simply not documented, so duration is beside the point.

        This gate never stops the process. A `satisfied: False` result is an input to
        the recommendation, not a decision — the agent has no authority to close a
        clinical denial, so the case still has to go through confidence aggregation and
        the escalation check.

        Returns None when no guideline covers the condition, so the route can 404.
        """
        guideline = self.get_guideline_for_condition(condition_code)
        if not guideline:
            return None

        criteria = self.get_step_therapy_requirement(guideline) or {}
        required_drug = criteria.get("drug")
        required_months = float(criteria.get("min_months") or 0)
        documented_months = float(documented_months or 0)

        common = {
            "condition": guideline.get("condition"),
            "guideline_ref": guideline.get("_id"),
            "required_drug": required_drug,
            "required_months": required_months,
            "documented_drug": documented_drug,
            "documented_months": documented_months,
            "confidence_threshold": guideline.get("confidence_threshold"),
        }

        if not required_drug or not required_months:
            # No gate to clear. Not a pass by narrow margin — there is simply no
            # step-therapy requirement for this condition.
            return {
                **common,
                "step_therapy_applies": False,
                "drug_matches": None,
                "satisfied": True,
                "confidence": _STEP_SATISFIED_CONFIDENCE,
                "detail": (
                    f"{guideline.get('_id')} sets no step-therapy requirement for "
                    f"{guideline.get('condition')}, so there is no prior-trial gate to clear."
                ),
            }

        drug_matches = (documented_drug or "").strip().lower() == required_drug.strip().lower()

        if not drug_matches:
            return {
                **common,
                "step_therapy_applies": True,
                "drug_matches": False,
                "satisfied": False,
                "confidence": _STEP_DRUG_MISMATCH_CONFIDENCE,
                "detail": (
                    f"Step therapy requires {required_drug}; the documented trial is "
                    f"{documented_drug or 'unspecified'} — the required conventional therapy "
                    "is not documented, so its duration does not answer the criteria."
                ),
            }

        satisfied = documented_months >= required_months
        return {
            **common,
            "step_therapy_applies": True,
            "drug_matches": True,
            "satisfied": satisfied,
            "confidence": (
                _STEP_SATISFIED_CONFIDENCE if satisfied else _STEP_NOT_SATISFIED_CONFIDENCE
            ),
            "detail": (
                f"Step therapy requires {required_months:g} months of {required_drug}; "
                f"{documented_months:g} effective months documented — "
                f"{'satisfied' if satisfied else 'NOT satisfied'}."
            ),
        }

    def classify_treatment(self, condition_code: str, requested_treatment: str) -> dict:
        """Step 4 (taxonomic memory): a treatment's class, tier and prior-auth status.

        Two paths, deliberately distinguished by `inferred` and by confidence:

        * the drug is enumerated in `classification` — the answer is *stated* by the
          guideline, so confidence is high;
        * it is not — the answer is *reasoned from category*. The guideline for the
          condition still fixes the coverage tier, so a tier and a conservative
          prior-auth requirement can be derived, but confidence drops to reflect that
          nothing named this drug specifically.

        Also reports whether step-therapy criteria apply, since that is what Step 5
        and Step 6 go on to evaluate.

        Returns None when no guideline covers the condition, so the route can 404.
        """
        guideline = self.get_guideline_for_condition(condition_code)
        if not guideline:
            return None

        therapy = self._therapy_key(guideline, requested_treatment)
        step = self.get_step_therapy_requirement(guideline) or {}
        common = {
            "condition": guideline.get("condition"),
            "guideline_ref": guideline.get("_id"),
            "therapy": therapy,
            # Carried so Step 6 does not need a second guideline read to know the gate
            # it is applying, or the bar the case has to clear.
            "step_therapy_applies": bool(step.get("drug")),
            "step_therapy_drug": step.get("drug"),
            "step_therapy_min_months": step.get("min_months"),
            "confidence_threshold": guideline.get("confidence_threshold"),
        }

        if not therapy:
            # Nothing was asked about. Not an inference — an unanswerable call. Prior
            # auth stays True so an empty response can never read as "no auth needed".
            return {
                **common,
                "classified": False,
                "inferred": False,
                "treatment_class": None,
                "tier": None,
                "prior_auth_required": True,
                "confidence": 0.0,
                "detail": "No treatment was supplied, so there is nothing to classify.",
            }

        if therapy in (guideline.get("classification") or {}):
            stated = self.evaluate_coverage_tier(guideline, requested_treatment)
            return {
                **common,
                "classified": True,
                "inferred": False,
                "treatment_class": stated.get("class"),
                "tier": stated.get("tier"),
                "prior_auth_required": stated.get("prior_auth_required"),
                "confidence": _CLASSIFY_STATED_CONFIDENCE,
                "detail": (
                    f"{therapy} is classified in {guideline.get('_id')} as "
                    f"{stated.get('class')} -> {stated.get('tier')} tier; prior auth "
                    f"required: {stated.get('prior_auth_required')}."
                ),
            }

        # Not enumerated. The class genuinely is not knowable from this data — say so
        # rather than guessing one — but the tier is, and prior auth is assumed
        # required because under-requiring it is the costlier error.
        inferred_tier = (guideline.get("criteria") or {}).get("coverage_tier")
        return {
            **common,
            "classified": False,
            "inferred": True,
            "treatment_class": None,
            "tier": inferred_tier,
            "prior_auth_required": True,
            "confidence": _CLASSIFY_INFERRED_CONFIDENCE,
            "detail": (
                f"{therapy} is not individually enumerated in {guideline.get('_id')}. "
                f"Reasoning from category: treatments for {guideline.get('condition')} fall "
                f"under the {inferred_tier} tier and require prior authorization. Class is "
                "left null because no reference data names this drug. Confidence reduced "
                "because the answer was inferred, not stated."
            ),
        }
