/**
 * Everything the Cost Estimator shows, as plain functions of the data the tool
 * already loads (member, policy, plan, claims, traces, and the reference price).
 *
 * Deliberately no React in here, so the arithmetic can be read and tested on its
 * own. Same mixed-casing caveat as the other presenters: FastAPI serializes by
 * alias, so accept either spelling of a key.
 *
 * What the estimate is, and is not. Nothing in the data stores a price, so the
 * reference price is what other members' approved claims for the same therapy
 * were billed (a median, from `GET /api/claims/precedent`). The member's share is
 * then worked out from the plan's own rules: deductible first, then coinsurance,
 * never past the yearly out-of-pocket maximum. Claims do not record how much of a
 * deductible has been met, so the estimate is a range: the high end assumes the
 * deductible is still unmet, the low end that it is already met.
 */

import { findPlanTreatment, toRequestedTreatment } from "@/lib/insurancePresenter";

function pick(source, ...keys) {
  if (!source) return undefined;
  return keys.map((key) => source[key]).find((value) => value != null);
}

function titleCase(value) {
  if (!value) return null;
  return String(value).charAt(0).toUpperCase() + String(value).slice(1).toLowerCase();
}

/** Whole dollars: an estimate does not pretend to the cent. */
export function formatMoney(amount) {
  if (amount == null || Number.isNaN(Number(amount))) return null;
  return `$${Math.round(Number(amount)).toLocaleString("en-US")}`;
}

/** "$1,080 – $1,480", or just "$1,080" when both ends agree. */
export function formatRange(low, high) {
  if (low == null || high == null) return null;
  return Math.round(low) === Math.round(high)
    ? formatMoney(high)
    : `${formatMoney(low)} – ${formatMoney(high)}`;
}

/**
 * The therapy this member is being priced for, and the diagnosis it was raised
 * against. Mirrors the Insurance tab: the care plan's considered therapy, else
 * the open (or most recent) order, else the therapy that was approved.
 */
export function resolveTherapy(member) {
  const actions = pick(member, "pending_actions", "pendingActions") ?? [];
  const open = actions.find((action) => action.status !== "resolved");
  const latest = open ?? actions[actions.length - 1] ?? null;
  const carePlan = pick(member, "current_care_plan", "currentCarePlan") ?? {};

  const therapy =
    pick(carePlan, "considering_therapy", "consideringTherapy") ??
    pick(latest, "proposed_treatment", "proposedTreatment") ??
    pick(carePlan, "approved_therapy", "approvedTherapy") ??
    null;

  return {
    therapy,
    diagnosisCode: pick(latest, "related_diagnosis_code", "relatedDiagnosisCode") ?? null,
  };
}

/** The display name of a diagnosis code on the member's record. */
export function diagnosisName(member, code) {
  const history = pick(member, "clinical_history", "clinicalHistory");
  const diagnoses = pick(history, "diagnoses") ?? [];
  const wanted = String(code ?? "").toUpperCase();

  return diagnoses.find((entry) => String(entry.code).toUpperCase() === wanted)?.display ?? null;
}

/** The plan's cost-sharing rules for the tier a treatment sits in. */
export function costSharingFor(plan, treatment) {
  const tiers = pick(plan?.coverage, "tiers") ?? {};
  const key = Object.keys(tiers).find(
    (name) => name.toLowerCase() === String(treatment?.tier ?? "").toLowerCase()
  );
  const tier = key ? tiers[key] : null;
  if (!tier) return null;

  return {
    tier: key,
    covered: tier.covered !== false,
    deductible: tier.deductible ?? 0,
    coinsurance: tier.coinsurance ?? null,
    copay: tier.copay ?? null,
    outOfPocketMax: pick(tier, "out_of_pocket_max", "outOfPocketMax") ?? null,
  };
}

/** What the member has already owed this year: it counts toward the out-of-pocket maximum. */
export function amountMetThisYear(claims = [], year = new Date().getFullYear()) {
  return claims
    .filter((claim) =>
      String(pick(claim, "service_date", "serviceDate") ?? "").startsWith(String(year))
    )
    .reduce((total, claim) => total + (pick(claim, "member_owed", "memberOwed") ?? 0), 0);
}

/**
 * The reference price for a therapy, from `GET /api/claims/precedent`.
 * Null when there is none to rest on.
 */
export function toReferencePrice(precedent) {
  const price = precedent?.billed?.median;
  if (!precedent || !precedent.count || price == null) return null;

  return {
    price,
    memberOwed: precedent.member_owed?.median ?? null,
    count: precedent.count,
  };
}

/**
 * The member's share of a price under the plan's rules.
 *
 * Coinsurance plans: `low` assumes the deductible is already met (coinsurance on the
 * whole price), `high` that it is not (the deductible first, then coinsurance on the
 * rest). Both are held under what is left of the out-of-pocket maximum. A flat copay
 * is a flat copay.
 *
 * `parts` splits the high case for the cost bar. When the maximum cuts the total
 * short, coinsurance gives way first.
 */
export function estimateCost({ price, sharing, amountMet = 0 }) {
  if (price == null || !sharing) return null;

  const remaining =
    sharing.outOfPocketMax != null ? Math.max(0, sharing.outOfPocketMax - amountMet) : null;
  const cap = (value) => (remaining == null ? value : Math.min(value, remaining));

  if (sharing.coinsurance != null) {
    const deductible = Math.min(price, sharing.deductible ?? 0);
    const uncappedHigh = deductible + sharing.coinsurance * Math.max(0, price - deductible);
    const high = cap(uncappedHigh);
    const low = cap(sharing.coinsurance * price);
    const deductiblePart = Math.min(deductible, high);

    return {
      kind: "coinsurance",
      price,
      low,
      high,
      parts: { deductible: deductiblePart, coinsurance: high - deductiblePart },
      capApplied: uncappedHigh > high,
      remaining,
    };
  }

  if (sharing.copay != null) {
    const copay = Math.min(price, sharing.copay);
    return {
      kind: "copay",
      price,
      low: copay,
      high: copay,
      parts: { copay },
      capApplied: false,
      remaining,
    };
  }

  return null;
}

/**
 * Where this therapy's prior authorization stands, from the member's traces. The
 * newest trace for the same therapy decides; none means nothing was requested yet.
 */
export function toDecisionState(traces = [], therapy) {
  const wanted = String(therapy ?? "").toLowerCase();
  const matching = traces
    .filter((trace) => {
      const service =
        pick(trace, "requested_service", "requestedService") ??
        pick(trace.request, "requestedService", "requested_service");
      return wanted && String(service ?? "").toLowerCase() === wanted;
    })
    .sort((a, b) =>
      String(pick(b, "created_at", "createdAt") ?? "").localeCompare(
        String(pick(a, "created_at", "createdAt") ?? "")
      )
    );

  const trace = matching[0];
  if (!trace) {
    return {
      kind: "estimate",
      label: "Estimate",
      tone: "neutral",
      text: "Nothing has been requested yet. This is what your plan's rules suggest.",
    };
  }

  const review = trace.review ?? {};
  const outcome = trace.outcome ?? {};
  const stage = trace.workflow?.stage;
  const closed = stage === "CLOSED" || Boolean(pick(review, "closed_by", "closedBy"));
  const decision = String(outcome.decision ?? trace.status ?? "").toLowerCase();
  const partial =
    pick(trace.administrativeGates ?? trace.administrative_gates, "coverageRestriction", "coverage_restriction") ===
    "partial";

  if (closed && decision.includes("denied")) {
    return {
      kind: "denied",
      label: "Denied",
      tone: "denied",
      text: "This request was denied, so the plan will not pay for it as requested.",
    };
  }
  if (closed && (decision === "approved_restricted" || (decision.includes("approved") && partial))) {
    return {
      kind: "approvedLimited",
      label: "Approved with limits",
      tone: "success",
      text: "Approved, but some stages are not covered. You pay those stages in full.",
    };
  }
  if (closed && decision.includes("approved")) {
    return {
      kind: "approved",
      label: "Approved",
      tone: "success",
      text: "Approved. The plan covers this therapy, so the estimate below applies.",
    };
  }
  if (stage === "ESCALATED" || (pick(review, "routed_to_human", "routedToHuman") && !closed)) {
    return {
      kind: "awaitingDirector",
      label: "Awaiting a doctor",
      tone: "progress",
      text: "A medical director is reviewing your request. The estimate may change.",
    };
  }
  return {
    kind: "inReview",
    label: "In review",
    tone: "progress",
    text: "Your request is being reviewed. The estimate may change with the decision.",
  };
}

/** The premium as the policy states it, and per payment. Separate from any care cost. */
export function toPremium(policy) {
  const premium = policy?.premium ?? {};
  const annual = pick(premium, "annual_premium", "annualPremium");
  if (annual == null) return null;

  const frequency = String(pick(premium, "payment_frequency", "paymentFrequency") ?? "").toLowerCase();
  const divisor = { monthly: 12, quarterly: 4, yearly: 1, annual: 1 }[frequency] ?? 1;

  return {
    annual,
    perPayment: annual / divisor,
    frequency: frequency || null,
    perLabel: { monthly: "month", quarterly: "quarter", yearly: "year", annual: "year" }[frequency] ?? null,
  };
}

/** The plan's cost sharing by tier, as short lines. Used when no therapy is being priced. */
export function toTierLines(plan) {
  const tiers = pick(plan?.coverage, "tiers") ?? {};

  return Object.entries(tiers).map(([name, tier]) => {
    if (tier.covered === false) return { name: titleCase(name), line: "Not covered by this plan" };

    const max = pick(tier, "out_of_pocket_max", "outOfPocketMax");
    const parts = [
      tier.copay != null && `${formatMoney(tier.copay)} copay`,
      tier.coinsurance != null && `${Math.round(tier.coinsurance * 100)}% coinsurance`,
      tier.deductible ? `${formatMoney(tier.deductible)} deductible` : null,
      max != null && `${formatMoney(max)} out-of-pocket max`,
    ].filter(Boolean);

    return { name: titleCase(name), line: parts.join(" · ") };
  });
}

/**
 * The whole view model. `mode`:
 *   "none"      no therapy is being considered: show the plan's cost sharing instead
 *   "blocked"   the plan will not pay (not listed, excluded, or the request was denied)
 *   "estimate"  the member's share is worked out from the plan's rules
 */
export function buildCostView({ member, policy, plan, claims = [], traces = [], precedent = null }) {
  const premium = toPremium(policy);
  const { therapy, diagnosisCode } = resolveTherapy(member);

  if (!therapy) {
    return { mode: "none", premium, tiers: toTierLines(plan) };
  }

  const treatment = findPlanTreatment(plan, therapy, diagnosisCode);
  const requested = toRequestedTreatment({ plan, therapyName: therapy, diagnosisCode });
  const sharing = treatment ? costSharingFor(plan, treatment) : null;
  const decision = toDecisionState(traces, therapy);
  const reference = toReferencePrice(precedent);

  const base = {
    therapy,
    name: requested?.name ?? titleCase(therapy),
    diagnosisCode,
    diagnosis: diagnosisName(member, diagnosisCode),
    premium,
    decision,
    reference,
    stages: requested?.steps ?? [],
    priorAuthRequired: requested?.priorAuthRequired ?? false,
  };

  let blockedReason = null;
  if (!treatment) blockedReason = "notListed";
  else if (treatment.covered === false || sharing?.covered === false) blockedReason = "excluded";
  else if (decision.kind === "denied") blockedReason = "denied";

  if (blockedReason) {
    return { ...base, mode: "blocked", blockedReason, fullPrice: reference?.price ?? null };
  }

  const amountMet = amountMetThisYear(claims);
  const estimate = estimateCost({ price: reference?.price, sharing, amountMet });

  return { ...base, mode: "estimate", sharing, amountMet, estimate };
}
