"use client";

import CareGapsTool from "@/components/careGapsTool/CareGapsTool";
import ClaimHistoryTool from "@/components/claimHistoryTool/ClaimHistoryTool";
import ClinicalHistoryTool from "@/components/clinicalHistoryTool/ClinicalHistoryTool";
import DecisionTracingTool from "@/components/decisionTracingTool/DecisionTracingTool";
import PlanComparisonTool from "@/components/planComparisonTool/PlanComparisonTool";
import Skeleton from "@/components/skeleton/Skeleton";
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
  if (toolId === "premium-calculation") return <PremiumCalculation data={data} />;
  if (toolId === "plan-comparison")
    return <PlanComparisonTool data={data} member={member} />;

  return <p className={styles.empty}>This tool has no content yet.</p>;
}
