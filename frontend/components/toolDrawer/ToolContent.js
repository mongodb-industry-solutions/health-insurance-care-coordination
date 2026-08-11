"use client";

import Skeleton from "@/components/skeleton/Skeleton";
import { toTimelineEvents } from "@/lib/memberPresenter";
import { useToolData } from "./useToolData";
import styles from "./ToolContent.module.css";

function pick(source, ...keys) {
  if (!source) return undefined;
  return keys.map((key) => source[key]).find((value) => value != null);
}

function money(amount, currency = "USD") {
  if (amount == null) return null;
  const symbol = currency === "USD" ? "$" : `${currency} `;
  return `${symbol}${Number(amount).toLocaleString("en-US", {
    maximumFractionDigits: 2,
  })}`;
}

/** Claim History — every claim on the member, most recent first. */
function ClaimHistory({ claims }) {
  if (!claims.length) {
    return <p className={styles.empty}>No claims on record.</p>;
  }

  const sorted = [...claims].sort((a, b) =>
    String(pick(b, "service_date", "serviceDate") ?? "").localeCompare(
      String(pick(a, "service_date", "serviceDate") ?? "")
    )
  );

  return (
    <>
      <p className={styles.intro}>
        {claims.length} claim{claims.length === 1 ? "" : "s"} on record.
      </p>

      <ul className={styles.list}>
        {sorted.map((claim) => (
          <li key={pick(claim, "claim_id", "claimId")} className={styles.item}>
            <div className={styles.itemHeader}>
              <span className={styles.itemTitle}>
                {pick(claim, "procedure_desc", "procedureDesc") ??
                  claim.service ??
                  "Claim"}
              </span>
              <span className={styles.itemAmount}>
                {money(
                  pick(claim, "member_owed", "memberOwed"),
                  claim.currency
                ) ?? "—"}
              </span>
            </div>
            <p className={styles.itemMeta}>
              {[
                pick(claim, "service_date", "serviceDate"),
                claim.provider?.name,
                claim.status,
                pick(claim, "denial_reason", "denialReason"),
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </li>
        ))}
      </ul>
    </>
  );
}

/** Recent Care Gaps — breaks in refill cadence found in pharmacy claims. */
function RecentCareGaps({ data }) {
  const gaps = data?.gaps ?? [];
  const cadence = pick(data, "expected_cadence_days", "expectedCadenceDays");

  if (!gaps.length) {
    return (
      <p className={styles.empty}>
        No refill gaps detected. Fills are within the expected
        {cadence ? ` ${cadence}-day` : ""} cadence.
      </p>
    );
  }

  return (
    <>
      <p className={styles.intro}>
        {gaps.length} gap{gaps.length === 1 ? "" : "s"} found against an expected
        {cadence ? ` ${cadence}-day` : ""} refill cadence. A gap is not
        necessarily a discontinuation — it may have a clinical explanation.
      </p>

      <ul className={styles.list}>
        {gaps.map((gap, index) => (
          <li key={`${gap.drug}-${index}`} className={styles.item}>
            <div className={styles.itemHeader}>
              <span className={styles.itemTitle}>{gap.drug}</span>
              <span className={styles.itemAmount}>
                {pick(gap, "gap_days", "gapDays")} days
              </span>
            </div>
            <p className={styles.itemMeta}>
              {[
                `${pick(gap, "previous_fill", "previousFill")} → ${pick(
                  gap,
                  "next_fill",
                  "nextFill"
                )}`,
                `~${pick(gap, "approx_missed_fills", "approxMissedFills")} missed fill(s)`,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </li>
        ))}
      </ul>
    </>
  );
}

/** Premium Calculation — what the member pays, and what care costs on top. */
function PremiumCalculation({ data }) {
  const premium = data?.policy?.premium ?? {};
  const annual = pick(premium, "annual_premium", "annualPremium");
  const currency = premium.currency ?? "USD";
  const frequency = String(
    pick(premium, "payment_frequency", "paymentFrequency") ?? ""
  ).toLowerCase();
  const divisor = { monthly: 12, quarterly: 4, yearly: 1, annual: 1 }[frequency] ?? 1;

  const tiers = pick(data?.plan?.coverage, "tiers") ?? {};

  const rows = [
    { label: "Annual premium", value: money(annual, currency) },
    { label: "Payment frequency", value: frequency || "—" },
    {
      label: "Per payment",
      value: annual != null ? money(annual / divisor, currency) : null,
    },
  ];

  return (
    <>
      <p className={styles.intro}>
        Premium is set at the policy level. Cost sharing below is what the plan
        adds on top when care is actually used.
      </p>

      <dl className={styles.rows}>
        {rows.map((row) => (
          <div key={row.label} style={{ display: "contents" }}>
            <dt className={styles.label}>{row.label}</dt>
            <dd className={styles.value}>{row.value ?? "Not on file"}</dd>
          </div>
        ))}
      </dl>

      {Object.keys(tiers).length > 0 && (
        <>
          <h4 className={styles.sectionLabel}>Cost sharing by tier</h4>
          <ul className={styles.list}>
            {Object.entries(tiers).map(([name, tier]) => (
              <li key={name} className={styles.item}>
                <div className={styles.itemHeader}>
                  <span className={styles.itemTitle}>{name}</span>
                </div>
                <p className={styles.itemMeta}>
                  {[
                    tier.copay != null && `${money(tier.copay)} copay`,
                    tier.coinsurance != null &&
                      `${Math.round(tier.coinsurance * 100)}% coinsurance`,
                    tier.deductible != null &&
                      `${money(tier.deductible)} deductible`,
                    pick(tier, "out_of_pocket_max", "outOfPocketMax") != null &&
                      `${money(
                        pick(tier, "out_of_pocket_max", "outOfPocketMax")
                      )} out-of-pocket max`,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </li>
            ))}
          </ul>
        </>
      )}

      {annual != null && (
        <div className={styles.total}>
          <span className={styles.totalLabel}>Yearly premium total</span>
          <span className={styles.totalValue}>{money(annual, currency)}</span>
        </div>
      )}
    </>
  );
}

/** Plan Comparison — the member's plan against the others on offer. */
function PlanComparison({ data }) {
  const plans = data?.plans ?? [];

  if (!plans.length) {
    return <p className={styles.empty}>No plans available to compare.</p>;
  }

  return (
    <>
      <p className={styles.intro}>
        The member&apos;s current plan is highlighted. Specialty-tier coverage is
        what determines whether a biologic therapy can be approved at all.
      </p>

      <ul className={styles.list}>
        {plans.map((plan) => {
          const planId = pick(plan, "plan_id", "planId");
          const isCurrent = planId === data.currentPlanId;
          const tiers = pick(plan.coverage, "tiers") ?? {};
          const specialty = tiers.specialty ?? tiers.Specialty;

          return (
            <li key={planId}>
              <div
                className={`${styles.planCard} ${
                  isCurrent ? styles.planCardCurrent : ""
                }`}
              >
                <p
                  className={`${styles.planName} ${
                    isCurrent ? styles.planNameCurrent : ""
                  }`}
                >
                  {pick(plan, "plan_name", "planName") ?? planId}
                  {isCurrent && <span className={styles.badge}>Current</span>}
                </p>
                <p className={styles.itemMeta}>
                  {[
                    pick(plan, "plan_type", "planType"),
                    plan.network?.replaceAll("_", " "),
                    specialty?.covered
                      ? "specialty tier covered"
                      : "specialty tier not covered",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </div>
            </li>
          );
        })}
      </ul>
    </>
  );
}

/** Clinical History Review — the full record, read from the member document. */
function ClinicalHistoryReview({ member }) {
  const history = member?.clinical_history ?? member?.clinicalHistory ?? {};
  const diagnoses = history.diagnoses ?? [];
  const medications = history.medications ?? [];
  const events = toTimelineEvents(member).filter((event) => !event.isCurrent);

  return (
    <>
      <p className={styles.intro}>
        The complete coded record and narrative notes behind this member&apos;s
        case.
      </p>

      {diagnoses.length > 0 && (
        <>
          <h4 className={styles.sectionLabel}>Diagnoses</h4>
          <ul className={styles.list}>
            {diagnoses.map((diagnosis) => (
              <li key={diagnosis.code} className={styles.item}>
                <div className={styles.itemHeader}>
                  <span className={styles.itemTitle}>{diagnosis.display}</span>
                  <span className={styles.itemAmount}>{diagnosis.status}</span>
                </div>
                <p className={styles.itemMeta}>
                  {diagnosis.system} {diagnosis.code}
                </p>
              </li>
            ))}
          </ul>
        </>
      )}

      {medications.length > 0 && (
        <>
          <h4 className={styles.sectionLabel}>Medications</h4>
          <ul className={styles.list}>
            {medications.map((medication) => (
              <li key={`${medication.code}-${medication.display}`} className={styles.item}>
                <div className={styles.itemHeader}>
                  <span className={styles.itemTitle}>{medication.display}</span>
                  <span className={styles.itemAmount}>{medication.status}</span>
                </div>
                {medication.reason && (
                  <p className={styles.itemMeta}>{medication.reason}</p>
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      {events.length > 0 && (
        <>
          <h4 className={styles.sectionLabel}>Notes & responses</h4>
          <ul className={styles.list}>
            {events.map((event) => (
              <li key={event.id} className={styles.item}>
                <div className={styles.itemHeader}>
                  <span className={styles.itemTitle}>
                    {event.eventType ?? "Note"}
                  </span>
                  <span className={styles.itemAmount}>{event.date}</span>
                </div>
                <p className={styles.itemMeta}>
                  {[event.actor, event.description].filter(Boolean).join(" — ")}
                </p>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}

/**
 * Routes a tool id to its content. Each tool reads from routes that already
 * exist in the backend — see useToolData for the mapping.
 */
export default function ToolContent({ toolId, member }) {
  const { data, loading, error } = useToolData(toolId, member);

  if (toolId === "clinical-history-review") {
    return <ClinicalHistoryReview member={member} />;
  }

  if (loading) return <Skeleton lines={7} />;

  if (error) {
    return <p className={styles.error}>Could not load this tool ({error.message}).</p>;
  }

  if (!data) return <Skeleton lines={7} />;

  if (toolId === "claim-history") return <ClaimHistory claims={data.claims} />;
  if (toolId === "recent-care-gaps") return <RecentCareGaps data={data} />;
  if (toolId === "premium-calculation") return <PremiumCalculation data={data} />;
  if (toolId === "plan-comparison") return <PlanComparison data={data} />;

  return <p className={styles.empty}>This tool has no content yet.</p>;
}
