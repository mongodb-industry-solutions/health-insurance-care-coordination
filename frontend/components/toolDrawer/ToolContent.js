"use client";

import CareGapsTool from "@/components/careGapsTool/CareGapsTool";
import ClaimHistoryTool from "@/components/claimHistoryTool/ClaimHistoryTool";
import ClinicalHistoryTool from "@/components/clinicalHistoryTool/ClinicalHistoryTool";
import ComparisonTable from "@/components/comparisonTable/ComparisonTable";
import DecisionTracingTool from "@/components/decisionTracingTool/DecisionTracingTool";
import Skeleton from "@/components/skeleton/Skeleton";
import {
  toCrossPlanCoverage,
  toTierComparison,
} from "@/lib/insurancePresenter";
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

/**
 * Plan Comparison — the tiers on the member's own plan, side by side.
 *
 * Only the tiers embedded on this plan are guaranteed by the data model, so the
 * comparison is Standard vs Specialty. ComparisonTable takes an array of columns,
 * so a cross-plan endpoint would extend this horizontally without a rewrite.
 */
function PlanComparison({ data, member }) {
  const plan = data?.plan;
  const activeTier = member?.eligibility?.tier;
  const { columns, rows } = toTierComparison(plan, activeTier);

  if (!columns.length) {
    return <p className={styles.empty}>No tier information on this plan.</p>;
  }

  const planName =
    pick(plan, "plan_name", "planName") ?? pick(plan, "plan_id", "planId");
  const planMeta = [
    pick(plan, "plan_type", "planType"),
    plan?.network?.replaceAll("_", " "),
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <>
      <p className={styles.intro}>
        {planName}
        {planMeta && ` — ${planMeta}`}. The member&apos;s current tier is
        highlighted; specialty-tier coverage is what determines whether a biologic
        therapy can be approved at all.
      </p>

      <ComparisonTable columns={columns} rows={rows} attributeLabel="Attribute" />

      <CrossPlanCoverage
        plans={data?.plans ?? []}
        currentPlanId={pick(plan, "plan_id", "planId")}
        tierName={activeTier}
      />
    </>
  );
}

/**
 * How the rest of the catalog treats the member's tier. Deliberately framed as
 * the catalog, not "plans available to you" — nothing models enrollment
 * eligibility, and premiums live on the Policy rather than the Plan, so this
 * cannot speak to what switching would cost.
 */
function CrossPlanCoverage({ plans, currentPlanId, tierName }) {
  const entries = toCrossPlanCoverage(plans, currentPlanId, tierName);
  if (!entries.length) return null;

  const tierLabel = String(tierName ?? "specialty").toLowerCase();

  return (
    <>
      <h4 className={styles.sectionLabel}>
        {/* Sentence case: the tier name is lowercased for mid-sentence use in
            the body copy below, so only the heading's first letter is raised. */}
        {tierLabel.charAt(0).toUpperCase() + tierLabel.slice(1)} coverage across
        plans
      </h4>
      <p className={styles.intro}>
        Every plan in the catalog, and how each treats the {tierLabel} tier. Plan
        records carry no premium, so this compares coverage only — not cost of
        switching.
      </p>

      <ul className={styles.list}>
        {entries.map((entry) => (
          <li key={entry.id}>
            <div
              className={`${styles.planCard} ${
                entry.isCurrent ? styles.planCardCurrent : ""
              }`}
            >
              <div className={styles.itemHeader}>
                <p
                  className={`${styles.planName} ${
                    entry.isCurrent ? styles.planNameCurrent : ""
                  }`}
                >
                  {entry.name}
                  {entry.isCurrent && (
                    <span className={styles.badge}>Current</span>
                  )}
                </p>
                <span className={styles.itemAmount}>
                  {entry.covered ? entry.costShare ?? "Covered" : "Not covered"}
                </span>
              </div>

              <p className={styles.itemMeta}>
                {[
                  entry.planType,
                  entry.network,
                  entry.exclusions.length > 0 &&
                    `excludes ${entry.exclusions
                      .map((service) => service.replaceAll("_", " "))
                      .join(", ")}`,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </div>
          </li>
        ))}
      </ul>
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
    return <ClinicalHistoryTool member={member} />;
  }

  // Fetches nothing — it owns its own brief skeleton before the empty state.
  if (toolId === "recent-care-gaps") return <CareGapsTool />;

  if (loading) return <Skeleton lines={7} />;

  if (error) {
    return <p className={styles.error}>Could not load this tool ({error.message}).</p>;
  }

  if (!data) return <Skeleton lines={7} />;

  if (toolId === "claim-history")
    return <ClaimHistoryTool claims={data.claims} />;
  if (toolId === "decision-tracing")
    return <DecisionTracingTool traces={data.traces} />;
  if (toolId === "recent-care-gaps") return <RecentCareGaps data={data} />;
  if (toolId === "premium-calculation") return <PremiumCalculation data={data} />;
  if (toolId === "plan-comparison")
    return <PlanComparison data={data} member={member} />;

  return <p className={styles.empty}>This tool has no content yet.</p>;
}
