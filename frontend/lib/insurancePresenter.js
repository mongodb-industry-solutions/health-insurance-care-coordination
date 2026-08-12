/**
 * Shapes `GET /api/policies/{id}` and `GET /api/plans/{id}` into the Insurance
 * Information tab's fields. Same mixed-casing caveat as `memberPresenter.js`:
 * FastAPI serializes by alias, so accept either spelling.
 */

function pick(source, ...keys) {
  if (!source) return undefined;
  return keys.map((key) => source[key]).find((value) => value != null);
}

function titleCase(value) {
  if (!value) return null;
  return String(value).charAt(0).toUpperCase() + String(value).slice(1).toLowerCase();
}

function formatAmount(amount, currency = "USD") {
  if (amount == null) return null;
  const symbol = currency === "USD" ? "$" : `${currency} `;
  return `${symbol}${amount.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
}

/**
 * "Yearly Renewal" style label, derived from the span between the effective and
 * expiry dates — the policy model has no renewal-type field of its own.
 */
function renewalLabel(startDate, endDate) {
  if (!startDate || !endDate) return null;

  const months = Math.round(
    (new Date(endDate) - new Date(startDate)) / (1000 * 60 * 60 * 24 * 30.44)
  );

  if (months >= 11 && months <= 13) return "Yearly Renewal";
  if (months === 1) return "Monthly Renewal";
  if (months >= 5 && months <= 7) return "Half-yearly Renewal";
  return null;
}

/**
 * Premium as an amount per payment period. The policy stores an annual figure,
 * so a monthly frequency is divided down rather than shown as-is.
 */
function premiumValue(premium) {
  const annual = pick(premium, "annual_premium", "annualPremium");
  if (annual == null) return null;

  // The seed stores this uppercase ("MONTHLY"), so match case-insensitively.
  const frequency = String(
    pick(premium, "payment_frequency", "paymentFrequency") ?? ""
  ).toLowerCase();
  const currency = premium?.currency ?? "USD";
  const divisor = { monthly: 12, quarterly: 4, yearly: 1, annual: 1 }[frequency] ?? 1;

  const amount = formatAmount(annual / divisor, currency);
  return frequency ? `${amount} / ${frequency}` : amount;
}

/** Stacked label/value pairs at the top of the tab. */
export function toPolicySummary(policy) {
  const period = pick(policy, "effective_period", "effectivePeriod") ?? {};
  const startDate = pick(period, "effective_date", "effectiveDate");
  const endDate =
    pick(period, "expiry_date", "expiryDate") ??
    pick(period, "renewal_date", "renewalDate");

  const range = startDate && endDate ? `${startDate} to ${endDate}` : startDate;
  const renewal = renewalLabel(startDate, endDate);

  return [
    { label: "Policy", value: pick(policy, "policy_id", "policyId") },
    {
      label: "Effective from - to",
      value: [renewal && `${renewal}.`, range].filter(Boolean).join(" ") || null,
    },
    { label: "Premium", value: premiumValue(policy?.premium) },
  ];
}

/**
 * Out-of-pocket progress for the current year, or null when it can't be
 * established — the caller omits the whole block in that case.
 *
 * The max comes from the member's active tier (`outOfPocketMax`). The amount met
 * is summed from `memberOwed` on this year's claims, since the backend has no
 * accumulator field of its own.
 */
export function toOutOfPocket({ plan, activeTier, claims = [], year }) {
  const tiers = pick(plan?.coverage, "tiers") ?? {};
  const tierKey = Object.keys(tiers).find(
    (name) => name.toLowerCase() === String(activeTier).toLowerCase()
  );
  const tier = tierKey ? tiers[tierKey] : null;
  const max = pick(tier, "out_of_pocket_max", "outOfPocketMax");

  if (!max) return null;

  const currentYear = String(year ?? new Date().getFullYear());
  const amountMet = claims
    .filter((claim) => {
      const serviceDate = pick(claim, "service_date", "serviceDate") ?? "";
      return String(serviceDate).startsWith(currentYear);
    })
    .reduce(
      (total, claim) => total + (pick(claim, "member_owed", "memberOwed") ?? 0),
      0
    );

  return {
    amountMet,
    max,
    currency: tier.currency ?? "USD",
    percent: Math.min(Math.round((amountMet / max) * 100), 100),
    label: `${formatAmount(amountMet)} of ${formatAmount(max)} met this year`,
  };
}

/**
 * How the plan treats the therapy the member is actually waiting on.
 *
 * `plan.treatments` is keyed by treatment code *and* condition — the same drug
 * is listed once per condition it applies to, so both must match. The member's
 * side of that comes from the care plan's considered therapy and the pending
 * action's related diagnosis code.
 */
export function toRequestedTreatment({ plan, therapyName, diagnosisCode }) {
  if (!therapyName) return null;

  const treatments = plan?.treatments ?? [];
  const wanted = String(therapyName).toLowerCase();

  const match = treatments.find((treatment) => {
    const name = String(
      pick(treatment, "treatment_name", "treatmentName") ?? treatment.drug ?? ""
    ).toLowerCase();
    const conditionMatches =
      !diagnosisCode || !treatment.condition || treatment.condition === diagnosisCode;

    return conditionMatches && name.includes(wanted);
  });

  if (!match) return null;

  const priorAuth = pick(match, "prior_auth_required", "priorAuthRequired");

  return {
    name: pick(match, "treatment_name", "treatmentName") ?? titleCase(therapyName),
    tier: titleCase(match.tier),
    covered: match.covered,
    priorAuthRequired: Boolean(priorAuth),
    steps: (match.steps ?? []).map((step, index) => ({
      id: pick(step, "step_code", "stepCode") ?? `step-${index}`,
      name: pick(step, "step_name", "stepName") ?? pick(step, "step_code", "stepCode"),
      covered: step.covered,
      cost:
        step.coinsurance != null
          ? `${Math.round(step.coinsurance * 100)}% coinsurance`
          : step.copay != null
            ? `${formatAmount(step.copay)} copay`
            : null,
    })),
  };
}

/**
 * Past prior-authorization decisions, most recent first, from
 * `GET /api/audit/member/{id}/traces`.
 */
export function toAuthorizationHistory(traces = []) {
  return traces
    .map((trace) => {
      const outcome = trace.outcome ?? {};
      const review = trace.review ?? {};
      const decision = outcome.decision ?? trace.status;

      return {
        id: pick(trace, "trace_id", "traceId"),
        service: pick(trace, "requested_service", "requestedService"),
        decision: decision ? titleCase(String(decision).replaceAll("_", " ")) : null,
        rawDecision: decision,
        date:
          pick(review, "closed_at", "closedAt") ??
          pick(trace, "created_at", "createdAt"),
        routedToHuman: Boolean(pick(review, "routed_to_human", "routedToHuman")),
        decidedBy:
          pick(review, "final_decision_maker", "finalDecisionMaker") ??
          pick(review, "closed_by", "closedBy"),
      };
    })
    .sort((a, b) => String(b.date ?? "").localeCompare(String(a.date ?? "")));
}

/**
 * Treatment-coverage matrix: which treatments the plan covers, at which tier,
 * and requiring what. Answers "what's covered" — dollar figures belong to the
 * premium/cost tool instead.
 *
 * Rows are grouped by `condition`, since that is how a member reads it ("what's
 * covered for my condition") rather than as a treatment catalog. Each treatment
 * entry declares a single tier, so it fills only the matching column.
 *
 * @param {object} plan
 * @param {string} activeTier  The member's enrolled tier, for the highlight.
 * @param {object} conditionNames  { [icd10Code]: displayName } from the member's diagnoses.
 */
export function toTreatmentCoverage(plan, activeTier, conditionNames = {}) {
  const tiers = pick(plan?.coverage, "tiers") ?? {};

  const columns = Object.entries(tiers).map(([name, tier]) => ({
    id: name,
    label: titleCase(name),
    isCurrent: name.toLowerCase() === String(activeTier).toLowerCase(),
    tier,
  }));

  const rows = (plan?.treatments ?? []).map((treatment, index) => {
    const steps = treatment.steps ?? [];
    const coveredSteps = steps.filter((step) => step.covered !== false);
    const uncoveredSteps = steps.filter((step) => step.covered === false);

    return {
      id: `${pick(treatment, "treatment_code", "treatmentCode") ?? index}-${
        treatment.condition ?? "any"
      }`,
      label:
        pick(treatment, "treatment_name", "treatmentName") ??
        treatment.drug ??
        "Treatment",
      condition: treatment.condition,
      tier: String(treatment.tier ?? "").toLowerCase(),
      covered: treatment.covered !== false,
      priorAuthRequired: Boolean(
        pick(treatment, "prior_auth_required", "priorAuthRequired")
      ),
      // The model represents partial coverage as a mix of covered steps.
      isPartial: coveredSteps.length > 0 && uncoveredSteps.length > 0,
      steps: steps.map((step, stepIndex) => ({
        id: pick(step, "step_code", "stepCode") ?? `step-${stepIndex}`,
        name:
          pick(step, "step_name", "stepName") ??
          pick(step, "step_code", "stepCode"),
        covered: step.covered !== false,
      })),
    };
  });

  // Group by condition, preserving the order conditions first appear.
  const groups = [];
  rows.forEach((row) => {
    const code = row.condition ?? "any";
    let group = groups.find((candidate) => candidate.id === code);

    if (!group) {
      group = {
        id: code,
        label: conditionNames[code] ?? (row.condition ? code : "All conditions"),
        code: conditionNames[code] ? code : null,
        rows: [],
      };
      groups.push(group);
    }

    group.rows.push(row);
  });

  return { columns, groups };
}

/**
 * How every plan in the catalog treats one tier — the secondary section of the
 * comparison tool.
 *
 * Framed as the catalog rather than "plans available to you" on purpose: nothing
 * in the data models enrollment eligibility, and premiums live on the Policy, not
 * the Plan, so switching cost is genuinely unknown here.
 */
export function toCrossPlanCoverage(plans = [], currentPlanId, tierName) {
  const tier = String(tierName ?? "specialty").toLowerCase();

  return plans.map((plan) => {
    const planId = pick(plan, "plan_id", "planId");
    const tiers = pick(plan?.coverage, "tiers") ?? {};
    const tierKey = Object.keys(tiers).find(
      (name) => name.toLowerCase() === tier
    );
    const tierData = tierKey ? tiers[tierKey] : null;

    const costShare = !tierData?.covered
      ? null
      : tierData.coinsurance != null
        ? `${Math.round(tierData.coinsurance * 100)}% coinsurance`
        : tierData.copay != null
          ? `${formatAmount(tierData.copay)} copay`
          : null;

    const excluded = pick(plan?.coverage, "excluded_services", "excludedServices") ?? [];

    return {
      id: planId,
      name: pick(plan, "plan_name", "planName") ?? planId,
      planType: pick(plan, "plan_type", "planType"),
      network: plan?.network?.replaceAll("_", " "),
      isCurrent: planId === currentPlanId,
      covered: Boolean(tierData?.covered),
      costShare,
      // Named exclusions explain *why* a tier isn't covered.
      exclusions: excluded.filter((service) => service.includes(tier)),
    };
  });
}

/**
 * Coverage tier cards. `plan.coverage.tiers` is an object keyed by tier name,
 * and the member's own `eligibility.tier` decides which card is highlighted.
 */
export function toCoverageTiers(plan, activeTier) {
  const tiers = pick(plan?.coverage, "tiers") ?? {};

  return Object.entries(tiers).map(([tierName, tier]) => {
    const currency = tier.currency ?? "USD";
    const priorAuth = pick(tier, "prior_auth_required", "priorAuthRequired");
    const outOfPocketMax = pick(tier, "out_of_pocket_max", "outOfPocketMax");

    // Coinsurance plans quote a percentage and a cap; copay plans quote a flat
    // fee and a deductible.
    const costParts = tier.coinsurance
      ? [
          `${Math.round(tier.coinsurance * 100)}% coinsurance`,
          outOfPocketMax != null && `${formatAmount(outOfPocketMax, currency)} max`,
        ]
      : [
          tier.copay != null && `${formatAmount(tier.copay, currency)} copay`,
          tier.deductible != null &&
            `${formatAmount(tier.deductible, currency)} deductible`,
        ];

    return {
      id: tierName,
      title: titleCase(tierName),
      isActive: String(tierName).toLowerCase() === String(activeTier).toLowerCase(),
      priorAuthLabel: priorAuth ? "Prior auth required" : "No prior auth",
      costLine: costParts.filter(Boolean).join(" – ") || "Not covered",
      covered: tier.covered,
    };
  });
}
