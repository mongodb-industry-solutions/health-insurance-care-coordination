"""Business logic for member operations.

Reads and narrow clinical writes on the core member object. Under the official
data model the regulator-ready record is the Audit Log decision trace (see the
`audit` domain), which captures reasoning as memory-typed `steps[]`; there is no
longer a separate per-read event trail, so these operations no longer emit
incidental audit rows.
"""

from datetime import date, datetime, timezone

from claims.repository import ClaimRepository
from db.mdb import get_connector
from guidelines.repository import GuidelineRepository
from guidelines.service import normalize_drug_name
from .repository import MemberRepository
from shared.collections import Collections
from shared.summary import compute_summary_fields

# Mean days per month. Trial durations are compared against guideline minimums
# expressed in whole months, so fill spans are converted with this rather than 30.
_MONTH_DAYS = 30.44

# Clinical-note types that can explain an interruption in a trial.
_EXPLANATORY_NOTE_TYPES = ("medication_hold", "refill_gap", "gap_review")

# Episodic-review confidence. An unexplained interruption must not be resolved in
# the member's favour: it lowers confidence and leans toward escalation rather than
# crediting a trial that may never have been continuous. Kept aligned with the
# insurance agent's `review_treatment_response_history`.
_TRIAL_CLEAN_CONFIDENCE = 0.95
_TRIAL_UNEXPLAINED_CONFIDENCE = 0.60

# Semantic-match confidence. A requested therapy that a guideline classifies for
# a diagnosis already coded on the member record is a near-certain match; the
# residual doubt is vocabulary drift, not clinical doubt. A miss is scored low
# but not zero, because an unlisted drug is unconfirmed rather than disproven —
# and a low score here is what carries the case toward escalation instead of
# silently resolving it. Kept aligned with the insurance agent's own
# `normalize_clinical_concept`, so both agents score the step identically.
_CONCEPT_MATCH_CONFIDENCE = 0.98
_CONCEPT_MISS_CONFIDENCE = 0.40

# Lifecycle a pending action may move through. Enforced here rather than trusted
# from the caller: an unrecognised status would leave the frontend's "Pending
# Actions" card unable to decide what to render.
PENDING_ACTION_STATUSES = ("pending", "in_progress", "resolved")


class MemberService:
    """Service layer for member-related operations."""

    def __init__(self, connector=None):
        connector = connector or get_connector()
        self.repository = MemberRepository(connector)
        # Step 3 resolves a requested drug to a diagnosis code, and only the
        # guidelines carry that mapping — the member record never states which
        # condition a therapy treats.
        self.guidelines = GuidelineRepository(connector)
        # Step 5 needs pharmacy fill dates, which live on claims rather than on
        # `treatment_responses` — the record says how long a trial was, the claims
        # show whether it was actually continuous.
        self.claims = ClaimRepository(connector)
        # Traces are read directly rather than through AuditRepository: `audit`'s
        # package __init__ imports its service, which imports `members`, so a
        # domain-level import here would close a cycle. The summary derivation
        # itself lives in shared.summary, shared with that service.
        self._connector = connector

    def get_clinical_context(self, member_id: str) -> dict:
        """Retrieve member's clinical history and eligibility for decision-making
        (Phase 1, step 3)."""
        doc = self.repository.get_clinical_history(member_id)
        if not doc:
            return None
        return {
            "member_id": member_id,
            "clinical_history": doc.get("clinical_history"),
            "eligibility": doc.get("eligibility"),
            "current_care_plan": doc.get("current_care_plan"),
        }

    def get_member(self, member_id: str) -> dict:
        """Retrieve complete member document."""
        return self.repository.get_by_key(member_id)

    def get_open_case(self, member_id: str) -> dict:
        """The member's open pending action — the entry point for a downstream agent.

        The two agents in this workflow never call each other: the insurance agent
        opens a case by flipping a `pendingActions[]` entry to `in_progress` and
        attaching `linkedAuditTraceId`, and any agent picking the case up reads that
        state back off the record. This is that read, so a healthcare agent handed
        nothing but a `memberId` can discover which therapy was requested and which
        trace to append its reasoning to.

        `related_diagnosis_code` is returned for comparison only. It is the referring
        physician's own assertion of the drug/diagnosis pairing; the step that
        verifies it (`match_clinical_concept`) derives the code independently from
        the coded record and must not be fed this value.

        Returns None when the member does not exist, so the route can 404. A member
        with no open action is not an error — `has_open_case` is False.
        """
        member = self.repository.get_by_key(member_id)
        if not member:
            return None

        actions = member.get("pendingActions") or []
        # `in_progress` outranks `pending`: a case already opened is the one a
        # downstream agent should be working, not a second unstarted item.
        open_actions = [
            a for a in actions if (a.get("status") or "") in ("in_progress", "pending")
        ]
        open_actions.sort(key=lambda a: 0 if a.get("status") == "in_progress" else 1)

        if not open_actions:
            resolved = [a for a in actions if (a.get("status") or "") == "resolved"]
            return {
                "member_id": member_id,
                "has_open_case": False,
                "open_action_count": 0,
                "detail": (
                    f"Member {member_id} has no open pending action"
                    + (
                        f" ({len(resolved)} already resolved). A reset would be needed "
                        "to replay this case."
                        if resolved
                        else "."
                    )
                ),
            }

        action = open_actions[0]
        trace_id = action.get("linkedAuditTraceId")
        return {
            "member_id": member_id,
            "has_open_case": True,
            # Surfaced rather than hidden: the model permits more than one open item,
            # and a caller silently working only the first should be able to tell.
            "open_action_count": len(open_actions),
            "action_id": action.get("actionId"),
            "type": action.get("type"),
            "status": action.get("status"),
            "proposed_treatment": action.get("proposedTreatment"),
            "related_diagnosis_code": action.get("relatedDiagnosisCode"),
            "raised_by": action.get("raisedBy"),
            "raised_at": action.get("raisedAt"),
            "trace_id": trace_id,
            "detail": (
                f"Action {action.get('actionId')} is {action.get('status')}: "
                f"{action.get('raisedBy') or 'a physician'} proposed "
                f"{action.get('proposedTreatment') or 'an unspecified therapy'}"
                + (
                    f", reasoning steps append to trace {trace_id}."
                    if trace_id
                    else ". No trace is open yet — the case has not been started."
                )
            ),
        }

    def review_trial_history(
        self,
        member_id: str,
        drug: str,
        cadence_days: int = 30,
        gap_factor: float = 1.5,
    ) -> dict:
        """Step 5 (episodic memory): the member's own trial of the required therapy,
        with any interruption investigated rather than assumed.

        `treatment_responses[].duration_months` is what someone wrote down; the
        pharmacy fills are what actually happened. This reads the fills and derives
        the duration from them, because the documented figure goes stale the moment
        the member keeps refilling — and a trial that looks too short on paper is
        exactly how an adequate trial gets wrongly rejected.

        The duration spans the first fill to the last, plus one cadence period for the
        final fill's own supply, since a fill covers the days that follow it.

        An interruption longer than `cadence_days * gap_factor` is an anomaly. What
        happens next depends entirely on whether documentation explains it:

        * explained (a `medication_hold` note, or a prior `gap_reviewed` entry) — the
          trial is continuous and the full span stands;
        * unexplained — only the longest uninterrupted run is credited, and confidence
          drops. Never resolve an unexplained gap in the member's favour.

        Returns None when the member does not exist, so the route can 404.
        """
        member = self.repository.get_by_key(member_id)
        if not member:
            return None

        history = member.get("clinical_history") or {}
        wanted = (drug or "").strip().lower()

        if not wanted:
            return {
                "member_id": member_id,
                "drug": drug,
                "documented_months": 0.0,
                "fill_count": 0,
                "first_fill": None,
                "last_fill": None,
                "expected_cadence_days": cadence_days,
                "observed_span_months": None,
                "longest_continuous_months": None,
                "anomaly_detected": False,
                "gaps": [],
                "anomaly_explained": False,
                "explanation": None,
                "related_note": None,
                "effective_trial_months": 0.0,
                "confidence": 0.0,
                "detail": (
                    "No drug was supplied, so there is no trial to review. Pass the "
                    "guideline's required step-therapy drug."
                ),
            }

        responses = [
            r
            for r in history.get("treatment_responses") or []
            if (r.get("drug") or "").strip().lower() == wanted
        ]
        # `documented_months` is what a CLINICIAN wrote down, so a gap_reviewed entry
        # is excluded: that one holds `effective_trial_months`, which this method
        # derived itself. Counting it would let a resolved gap raise the documented
        # figure on the next read — the agent's own output feeding back in as though
        # it were documentation, and the stale interim record (Maria: 3 months against
        # 7 months of fills) quietly disappearing after the first run.
        clinician_documented = [
            r for r in responses if (r.get("outcome") or "") != "gap_reviewed"
        ]
        # Later entries supersede earlier interim ones rather than adding to them.
        documented_months = max(
            [float(r.get("duration_months") or 0) for r in clinician_documented] or [0.0]
        )

        fills = self._fill_dates(member_id, drug)
        threshold = cadence_days * gap_factor

        gaps = []
        # Runs of fills with no gap between them, so an unexplained interruption
        # credits only the longest stretch that was genuinely uninterrupted.
        runs = [[fills[0]]] if fills else []
        for previous, following in zip(fills, fills[1:]):
            interval = (following - previous).days
            if interval > threshold:
                gaps.append(
                    {
                        "drug": drug,
                        "previous_fill": previous.isoformat(),
                        "next_fill": following.isoformat(),
                        "gap_days": interval,
                        "approx_missed_fills": max(1, round(interval / cadence_days) - 1),
                    }
                )
                runs.append([following])
            else:
                runs[-1].append(following)

        def months(start, end):
            return round(((end - start).days + cadence_days) / _MONTH_DAYS)

        observed_span_months = months(fills[0], fills[-1]) if fills else None
        longest_run_months = (
            max(months(r[0], r[-1]) for r in runs) if runs else None
        )

        explanatory_notes = [
            n
            for n in history.get("clinical_notes") or []
            if (n.get("type") or "") in _EXPLANATORY_NOTE_TYPES
        ]
        prior_reviews = [r for r in responses if (r.get("outcome") or "") == "gap_reviewed"]

        anomaly_detected = bool(gaps)
        explanation = None
        related_note = None
        if anomaly_detected:
            if explanatory_notes:
                explanation = explanatory_notes[-1].get("note")
                related_note = explanatory_notes[-1].get("note_id")
            elif prior_reviews:
                explanation = prior_reviews[-1].get("notes")
        anomaly_explained = bool(anomaly_detected and explanation)

        if not fills:
            # No pharmacy evidence either way: fall back to what was written down,
            # and say that the number is unverified rather than implying it was checked.
            effective = documented_months
            confidence = _TRIAL_CLEAN_CONFIDENCE
            detail = (
                f"No pharmacy fills on file for {drug}. Falling back to the documented "
                f"{documented_months:g} months, which could not be verified against fill history."
            )
        elif not anomaly_detected:
            effective = observed_span_months
            confidence = _TRIAL_CLEAN_CONFIDENCE
            detail = (
                f"{drug}: {len(fills)} fills from {fills[0].isoformat()} to "
                f"{fills[-1].isoformat()}, no interruptions. Effective trial "
                f"{effective} months (record documents {documented_months:g})."
            )
        elif anomaly_explained:
            effective = observed_span_months
            confidence = _TRIAL_CLEAN_CONFIDENCE
            # Report the missed refills, not just the elapsed days: a short clinical
            # hold makes a member miss a whole monthly refill, so "60-day interval"
            # sitting next to a note saying "10-day hold" otherwise reads as a
            # contradiction.
            detail = (
                f"{drug}: {gaps[0]['gap_days']}-day interval between fills "
                f"(~{gaps[0]['approx_missed_fills']} missed refill), explained by "
                f"documentation — {explanation} Trial treated as continuous: effective "
                f"{effective} months (record documents {documented_months:g})."
            )
        else:
            effective = longest_run_months
            confidence = _TRIAL_UNEXPLAINED_CONFIDENCE
            detail = (
                f"{drug}: {gaps[0]['gap_days']}-day interval between fills "
                f"(~{gaps[0]['approx_missed_fills']} missed refill) with no clinical note "
                f"explaining it. Crediting only the longest uninterrupted run "
                f"({effective} months) rather than the full {observed_span_months}-month span. "
                "Reduce confidence and lean toward human review."
            )

        return {
            "member_id": member_id,
            "drug": drug,
            "documented_months": documented_months,
            "fill_count": len(fills),
            "first_fill": fills[0].isoformat() if fills else None,
            "last_fill": fills[-1].isoformat() if fills else None,
            "expected_cadence_days": cadence_days,
            "observed_span_months": observed_span_months,
            "longest_continuous_months": longest_run_months,
            "anomaly_detected": anomaly_detected,
            "gaps": gaps,
            "anomaly_explained": anomaly_explained,
            "explanation": explanation,
            "related_note": related_note,
            "effective_trial_months": effective,
            "confidence": confidence,
            "detail": detail,
        }

    def _fill_dates(self, member_id: str, drug: str):
        """Sorted pharmacy fill dates for one drug.

        Fill dates live only on pharmacy claims — `treatment_responses` records a
        duration, never the individual fills.
        """
        wanted = (drug or "").strip().lower()
        dates = []
        for claim in self.claims.find_by_member(member_id):
            service = str(claim.get("service") or "")
            if not service.startswith("pharmacy - "):
                continue
            if service.replace("pharmacy - ", "").strip().lower() != wanted:
                continue
            stamp = claim.get("adjudicated_at") or claim.get("serviceDate")
            if not stamp:
                continue
            try:
                dates.append(date.fromisoformat(str(stamp)[:10]))
            except ValueError:
                continue
        return sorted(dates)

    def match_clinical_concept(self, member_id: str, requested_treatment: str) -> dict:
        """Step 3 (semantic memory): does the requested therapy correspond to a
        condition already documented on this member's record?

        The provider names a therapy; the record carries ICD-10 codes. Neither
        states the other, so the bridge is the guideline: whichever conditions
        any guideline classifies this drug under are intersected with the
        member's *active* diagnoses.

        Deliberately does not read `pendingActions[].relatedDiagnosisCode`. That
        field is the referring physician's own assertion of the pairing, which is
        the very thing this step exists to verify — trusting it would make the
        check circular.

        Returns None when the member does not exist, so the route can 404.
        """
        member = self.repository.get_by_key(member_id)
        if not member:
            return None

        diagnoses = (member.get("clinical_history") or {}).get("diagnoses") or []
        # Resolved conditions must not authorize new therapy, so only active ones count.
        member_codes = [
            (d.get("code") or "").upper()
            for d in diagnoses
            if (d.get("status") or "active") == "active"
        ]

        drug = normalize_drug_name(requested_treatment)
        guidelines = self.guidelines.find_by_classified_drug(drug)
        # Newest-first from the repository, so the first hit per condition is the
        # version in force.
        conditions = {}
        for g in guidelines:
            code = (g.get("condition") or "").upper()
            conditions.setdefault(code, g)

        matched_code = next((c for c in member_codes if c in conditions), None)

        if not matched_code:
            if not drug:
                detail = "No treatment was supplied, so there is no clinical concept to match."
            elif not member_codes:
                detail = (
                    f"Member {member_id} has no active diagnosis on file, so "
                    f"{drug} cannot be tied to a documented condition."
                )
            elif not guidelines:
                detail = (
                    f"No guideline classifies {drug}, so it cannot be resolved to a "
                    "condition. Treat the clinical concept as unconfirmed."
                )
            else:
                detail = (
                    f"{drug or requested_treatment} is classified for "
                    f"{sorted(conditions)}, none of which is active on member {member_id} "
                    f"(active: {member_codes})."
                )
            return {
                "member_id": member_id,
                "requested_treatment": requested_treatment,
                "therapy": drug,
                "matched": False,
                "matched_condition": None,
                "matched_display": None,
                "guideline_ref": None,
                "member_diagnosis_codes": member_codes,
                "guideline_conditions": sorted(conditions),
                "confidence": _CONCEPT_MISS_CONFIDENCE,
                "detail": detail,
            }

        guideline = conditions[matched_code]
        display = next(
            (
                d.get("display")
                for d in diagnoses
                if (d.get("code") or "").upper() == matched_code
            ),
            None,
        )
        return {
            "member_id": member_id,
            "requested_treatment": requested_treatment,
            "therapy": drug,
            "matched": True,
            "matched_condition": matched_code,
            "matched_display": display,
            "guideline_ref": guideline.get("_id"),
            "member_diagnosis_codes": member_codes,
            "guideline_conditions": sorted(conditions),
            "confidence": _CONCEPT_MATCH_CONFIDENCE,
            "detail": (
                f"Matched requested therapy {drug} to {matched_code}"
                f"{f' ({display})' if display else ''}, already documented as active on "
                f"member {member_id}. Bridged via guideline {guideline.get('_id')}."
            ),
        }

    def get_members_by_policy(self, policy_id: str) -> list:
        """Retrieve all members enrolled under a policy."""
        return self.repository.find_by_policy(policy_id)

    def list_all_members(self) -> list:
        """Retrieve all members."""
        return self.repository.find()

    def list_pending_authorizations(self) -> list:
        """Insurance Agent work queue: members with an unresolved pending action.

        Includes both `pending` (never started) and `in_progress` (a case is open,
        possibly waiting on a medical director). An escalated case must keep showing
        up here — it is not finished, and dropping it would make an awaited human
        decision invisible.
        """
        return self.repository.find_with_open_pending_actions()

    def update_pending_action(
        self,
        member_id: str,
        action_id: str,
        status: str,
        linked_audit_trace_id: str = None,
    ) -> dict:
        """Advance one `pendingActions[]` entry through its lifecycle.

        This is what drives the member-facing "Start Process" trigger and its
        resolution: `in_progress` at the very start of a case, `resolved` only once
        the case has actually closed. An escalated case stays `in_progress` with its
        trace attached, so the frontend can distinguish "awaiting medical director"
        from "not started".

        `linked_audit_trace_id` is written only when supplied, so a later
        status-only call cannot erase a trace link set earlier.

        Returns the updated entry. Raises ValueError for an unknown status
        (-> HTTP 400) or when the member or action does not exist (-> HTTP 404,
        distinguished by the caller on the message).
        """
        status = (status or "").strip().lower()
        if status not in PENDING_ACTION_STATUSES:
            raise ValueError(
                f"status must be one of {PENDING_ACTION_STATUSES}, got {status!r}"
            )

        member = self.repository.get_by_key(member_id)
        if not member:
            raise LookupError(f"Member {member_id} not found")
        actions = member.get("pendingActions") or []
        if not any(a.get("actionId") == action_id for a in actions):
            # Distinguished from a missing member: the agent can act on the
            # difference — a wrong member id is a lookup bug, a wrong action id
            # usually means the action was already resolved and replaced.
            raise LookupError(
                f"Member {member_id} has no pending action {action_id}. "
                f"Known actions: {[a.get('actionId') for a in actions] or 'none'}"
            )

        updates = {"status": status}
        if linked_audit_trace_id:
            updates["linkedAuditTraceId"] = linked_audit_trace_id
        self.repository.update_pending_action(member_id, action_id, updates)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # The record changed, but the summary projection was not recalculated —
        # only `updatedAt` moves. `summary.updated_at` belongs to
        # `recompute_summary`.
        self.repository.touch(member_id, now)

        member = self.repository.get_by_key(member_id)
        entry = next(
            a for a in (member.get("pendingActions") or []) if a.get("actionId") == action_id
        )
        return {"memberId": member_id, "pendingAction": entry, "updatedAt": now}

    def recompute_summary(self, member_id: str, last_authorization_status: str = None) -> dict:
        """Refresh `Member.summary` from the member's decision traces.

        Derived, not incremented. The tool catalog frames this as applying an
        `open_authorization_delta`, but a delta assumes exactly one writer and this
        field has two — this endpoint and the closure paths in `AuditService`.
        Counting the traces instead means the two can run in any order, or twice,
        and still agree. `shared.summary` holds the derivation both use.

        `last_authorization_status` is accepted as an override for the rare case
        where a caller knows the outcome before it has landed on a trace; when
        omitted (the normal path) it is derived too.

        Returns the updated summary, or None when the member does not exist.
        """
        member = self.repository.get_by_key(member_id)
        if not member:
            return None

        traces = list(
            self._connector.get_collection(Collections.AUDIT_LOG).find(
                {"subjectRef": member_id}
            )
        )
        fields = compute_summary_fields(traces)
        if last_authorization_status:
            fields["last_authorization_status"] = last_authorization_status
        fields["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        self.repository.set_summary(member_id, fields)
        summary = {**(member.get("summary") or {}), **fields}
        return {"memberId": member_id, "summary": summary, "traceCount": len(traces)}

    def _provider_name(self, member: dict) -> str:
        provider = member.get("current_care_plan", {}).get("managing_provider")
        if isinstance(provider, dict):
            return provider.get("name", "unknown")
        return provider or "unknown"

    def document_treatment_response(
        self,
        member_id: str,
        drug: str,
        duration_months: int,
        outcome: str,
        notes: str,
        considering_therapy: str,
    ) -> dict:
        """Phase 1, step 1: Dr. Patel documents the treatment response.

        Appends a treatment_response assessment, marks the first-line drug
        discontinued with that reason, records the therapy now being considered,
        and bumps updatedAt. Returns the updated member, or None if it does not
        exist.
        """
        member = self.repository.get_by_key(member_id)
        if not member:
            return None

        now = datetime.now(timezone.utc)
        provider = self._provider_name(member)

        clinical = member.setdefault("clinical_history", {})

        # Append the assessment (keeps the trajectory: earlier 'ongoing' -> this one).
        clinical.setdefault("treatment_responses", []).append({
            "drug": drug,
            "duration_months": duration_months,
            "outcome": outcome,
            "notes": notes,
            "documented_by": provider,
            "documented_on": now.strftime("%Y-%m-%d"),
        })

        # Discontinue the matching medication with the documented reason.
        for med in clinical.get("medications", []):
            if med.get("display") == drug:
                med["status"] = "discontinued"
                med["reason"] = f"{outcome} response"

        # Record the therapy now under consideration.
        member.setdefault("current_care_plan", {})["considering_therapy"] = considering_therapy

        member["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.repository.upsert(member)
        return member

    def resolve_refill_gap(
        self,
        member_id: str,
        drug: str,
        effective_trial_months: float,
        conclusion: str,
        related_note: str = None,
    ) -> dict:
        """Step 5b: the care-coordination agent attaches its gap conclusion.

        Records the agent-authored `conclusion` as a treatment_response so an explained
        gap stays explained — `review_trial_history` reads a `gap_reviewed` entry back
        as documentation on a later run. Generic: no condition or drug is hardcoded.

        **Idempotent per drug.** A re-run leaves exactly one `gap_reviewed` entry for
        the drug, as the newest one. The same gap reviewed twice is one conclusion
        re-stated, not two findings.

        Only `gap_reviewed` entries for this drug are dropped — every one of them, not
        just the entry being superseded — so a record carrying duplicates from before
        this was idempotent is repaired on the next write. That matters because
        `review_trial_history` reads `prior_reviews[-1]`: leaving an older duplicate
        in place after the new entry would keep serving a stale conclusion no re-run
        could displace.

        Clinician-written responses for this drug are untouched, as are all entries
        for other drugs. This method only ever supersedes its own output.

        Returns the updated member, or None if it does not exist.
        """
        member = self.repository.get_by_key(member_id)
        if not member:
            return None

        now = datetime.now(timezone.utc)
        clinical = member.setdefault("clinical_history", {})
        entry = {
            "drug": drug,
            "duration_months": effective_trial_months,
            "outcome": "gap_reviewed",
            "notes": conclusion,
            "documented_by": "care_coordination_agent",
            "documented_on": now.strftime("%Y-%m-%d"),
        }
        # Provenance: cite the clinical note that explained the gap so the
        # conclusion can be traced back to its source documentation (the audit
        # trail no longer carries this — it lives on the record).
        if related_note:
            entry["related_note"] = related_note

        wanted = (drug or "").strip().lower()
        kept = [
            r
            for r in clinical.get("treatment_responses") or []
            if not (
                (r.get("outcome") or "") == "gap_reviewed"
                and (r.get("drug") or "").strip().lower() == wanted
            )
        ]
        # Appended last, so `prior_reviews[-1]` reads this conclusion and not an older
        # one. Entries for other drugs, and this drug's clinician-written responses,
        # keep their original order.
        kept.append(entry)
        clinical["treatment_responses"] = kept

        member["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.repository.upsert(member)
        return member
