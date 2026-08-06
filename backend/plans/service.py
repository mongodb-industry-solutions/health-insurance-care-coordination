"""Business logic for plan operations."""

from typing import Optional

from db.mdb import get_connector
from .repository import PlanRepository


class PlanService:
    """Service layer for plan-related operations."""

    def __init__(self, connector=None):
        self.repository = PlanRepository(connector or get_connector())

    def get_plan(self, plan_id: str) -> dict:
        """Retrieve a plan by ID."""
        return self.repository.get_by_key(plan_id)

    def list_all_plans(self) -> list:
        """Retrieve all plans."""
        return self.repository.find()

    # --- treatment resolution -------------------------------------------------

    @staticmethod
    def find_treatment(
        plan: dict,
        condition: str,
        treatment_code: str = None,
        drug: str = None,
    ) -> tuple:
        """Resolve one `treatments[]` entry. Returns (entry_or_None, matched_on).

        **`treatment_code` alone is not a unique key.** The same code appears once
        per condition it applies to — methotrexate `6851` is listed under both
        `M06.9` and `L40.50` in a single plan — so `condition` is always part of
        the match.

        Two resolution paths, in order of precision:

        1. `treatment_code` + `condition` — exact, and always preferred.
        2. `drug` + `condition` — a case-insensitive substring match of the therapy
           name against `treatmentName` (so "secukinumab" resolves
           "Secukinumab (Cosentyx) therapy"). Necessary because the final data
           model dropped the `drug` field that used to be the lookup key, while the
           agents still name therapies in prose and never see J-codes. It is
           fuzzier than a code match, so callers report lower confidence when this
           is what matched — `matched_on` says which path was taken.

        A legacy `drug` field is still matched exactly where present, so documents
        predating the final model resolve too.

        An entry recording no `condition` matches any condition rather than none:
        absent scoping means the treatment is not condition-specific, and excluding
        it would silently drop coverage the plan does provide.

        This is the single treatment matcher — `audit/service.py::_coverage` calls
        it too, so the clinical path and the administrative gate can never disagree
        about whether a plan covers something.
        """
        entries = plan.get("treatments") or []
        wanted_condition = (condition or "").strip().upper()
        wanted_code = (treatment_code or "").strip().upper()
        wanted_drug = (drug or "").strip().lower()

        def condition_matches(entry: dict) -> bool:
            entry_condition = (entry.get("condition") or "").strip().upper()
            if not entry_condition or not wanted_condition:
                return True
            return entry_condition == wanted_condition

        if wanted_code:
            for entry in entries:
                if (entry.get("treatmentCode") or "").strip().upper() != wanted_code:
                    continue
                if condition_matches(entry):
                    return entry, "treatment_code"

        if wanted_drug:
            for entry in entries:
                if not condition_matches(entry):
                    continue
                legacy = (entry.get("drug") or "").strip().lower()
                if legacy and legacy == wanted_drug:
                    return entry, "drug"
                name = (entry.get("treatmentName") or "").strip().lower()
                if name and wanted_drug in name:
                    return entry, "treatment_name"

        return None, None

    def check_treatment_coverage(
        self,
        plan_id: str,
        condition: str,
        treatment_code: str = None,
        drug: str = None,
    ) -> Optional[dict]:
        """Insurance Agent, step 2: the second administrative gate.

        Implements the coverage-check logic from the data model (§3.3): resolve the
        treatment, then evaluate its `steps[]`. A treatment is not a single yes/no
        gate — it is a sequence of stages, and a plan can fund some and not others,
        which is what makes a genuine `approved_restricted` outcome exist as data
        rather than narrative.

        Returns None when the plan does not exist (-> HTTP 404). Raises ValueError
        when neither `treatment_code` nor `drug` is supplied (-> HTTP 400), since
        there would be nothing to look up.
        """
        if not (treatment_code or "").strip() and not (drug or "").strip():
            raise ValueError(
                "Provide treatment_code (preferred) or drug to identify the treatment."
            )

        plan = self.repository.get_by_key(plan_id)
        if not plan:
            return None

        entry, matched_on = self.find_treatment(
            plan, condition=condition, treatment_code=treatment_code, drug=drug
        )
        requested = (treatment_code or drug or "").strip()
        base = {
            "planId": plan.get("planId", plan_id),
            "condition": (condition or "").strip().upper() or None,
            "matchedOn": matched_on,
        }

        # 1. Not listed for this condition at all.
        if not entry:
            return {
                **base,
                "covered": False,
                "restriction": None,
                "coveredSteps": [],
                "uncoveredSteps": [],
                "priorAuthRequired": None,
                "reason": "treatment_not_listed_for_condition",
                "tier": None,
                "treatmentCode": treatment_code or None,
                "treatmentName": None,
                "confidence": 0.99,
                "detail": (
                    f"Plan {base['planId']} lists no treatment matching {requested!r} for "
                    f"condition {base['condition'] or 'unspecified'}. The benefit is not "
                    "provided under this plan."
                ),
            }

        tier = entry.get("tier")
        name = entry.get("treatmentName")
        code = entry.get("treatmentCode")
        # A name match is a substring comparison on prose, not an exact key, so it
        # is reported as slightly less certain than a code match.
        found = {
            **base,
            "tier": tier,
            "treatmentCode": code,
            "treatmentName": name,
            "confidence": 0.99 if matched_on in ("treatment_code", "drug") else 0.95,
        }
        label = name or code or requested

        # 2. Listed, but explicitly not covered — a benefit exclusion.
        if not entry.get("covered"):
            return {
                **found,
                "covered": False,
                "restriction": None,
                "coveredSteps": [],
                "uncoveredSteps": [
                    s.get("stepCode") for s in (entry.get("steps") or []) if s.get("stepCode")
                ],
                # Prior authorization is moot for a benefit the plan does not provide.
                "priorAuthRequired": None,
                "reason": "benefit_exclusion",
                "detail": (
                    f"{label} is listed under plan {found['planId']} for condition "
                    f"{found['condition']} but is explicitly not covered"
                    + (f" ({tier} tier)" if tier else "")
                    + ". Benefit exclusion — an administrative determination."
                ),
            }

        steps = entry.get("steps") or []
        covered_steps = [s.get("stepCode") for s in steps if s.get("covered")]
        uncovered_steps = [
            s.get("stepCode") for s in steps if not s.get("covered") and s.get("stepCode")
        ]
        prior_auth = entry.get("priorAuthRequired")
        if prior_auth is None and tier:
            # Fall back to the tier default when the treatment states none itself.
            tiers = (plan.get("coverage") or {}).get("tiers") or {}
            prior_auth = (tiers.get(tier) or {}).get("priorAuthRequired")
        pa_text = "yes" if prior_auth else "no"

        # 3. Covered with no stage breakdown recorded — treat as fully covered. A
        #    covered treatment with no steps[] is not "no stages funded"; the
        #    protocol simply is not itemized, as conventional drugs often are not.
        if not steps:
            return {
                **found,
                "covered": True,
                "restriction": "none",
                "coveredSteps": [],
                "uncoveredSteps": [],
                "priorAuthRequired": prior_auth,
                "reason": None,
                "detail": (
                    f"{label} is covered under plan {found['planId']} for condition "
                    f"{found['condition']}"
                    + (f" at the {tier} tier" if tier else "")
                    + ". No per-stage breakdown is recorded, so the treatment is covered "
                    f"in full. Prior authorization required: {pa_text}."
                ),
            }

        # 4. Every stage funded — fully covered.
        if not uncovered_steps:
            return {
                **found,
                "covered": True,
                "restriction": "none",
                "coveredSteps": covered_steps,
                "uncoveredSteps": [],
                "priorAuthRequired": prior_auth,
                "reason": None,
                "detail": (
                    f"{label} is covered under plan {found['planId']} for condition "
                    f"{found['condition']}"
                    + (f" at the {tier} tier" if tier else "")
                    + f", and all {len(covered_steps)} stages of the protocol are funded "
                    f"({', '.join(covered_steps)}). Prior authorization required: {pa_text}."
                ),
            }

        # 5. Some funded, some not — a genuine partial/restricted outcome.
        if covered_steps:
            return {
                **found,
                "covered": True,
                "restriction": "partial",
                "coveredSteps": covered_steps,
                "uncoveredSteps": uncovered_steps,
                "priorAuthRequired": prior_auth,
                "reason": None,
                "detail": (
                    f"{label} is covered under plan {found['planId']} for condition "
                    f"{found['condition']}, but only for part of the protocol: "
                    f"{', '.join(covered_steps)} funded, {', '.join(uncovered_steps)} not. "
                    "Any approval must be approved_restricted, with the member "
                    f"responsible for the uncovered stages. Prior authorization "
                    f"required: {pa_text}."
                ),
            }

        # 6. Listed and nominally covered, but no stage is actually funded.
        return {
            **found,
            "covered": False,
            "restriction": None,
            "coveredSteps": [],
            "uncoveredSteps": uncovered_steps,
            "priorAuthRequired": None,
            "reason": "no_steps_covered",
            "detail": (
                f"{label} is listed as covered under plan {found['planId']} for condition "
                f"{found['condition']}, but no stage of the protocol is funded "
                f"({', '.join(uncovered_steps)} are all excluded). Nothing is payable, so "
                "this is a benefit exclusion in effect."
            ),
        }
