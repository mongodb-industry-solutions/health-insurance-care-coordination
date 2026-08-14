"use client";

import { useState } from "react";
import ComparisonTable from "@/components/comparisonTable/ComparisonTable";
import {
  toCrossPlanCoverage,
  toTreatmentCoverage,
} from "@/lib/insurancePresenter";
import styles from "./PlanComparisonTool.module.css";

function pick(source, ...keys) {
  if (!source) return undefined;
  return keys.map((key) => source[key]).find((value) => value != null);
}

/** { [icd10]: display } from the member's own diagnoses, for group labels. */
function conditionNamesOf(member) {
  const history = member?.clinical_history ?? member?.clinicalHistory ?? {};

  return (history.diagnoses ?? []).reduce((names, diagnosis) => {
    if (diagnosis.code) names[diagnosis.code] = diagnosis.display;
    return names;
  }, {});
}

/**
 * Plan Comparison: a treatment-coverage matrix. Answers "what is covered" —
 * costs live in the premium tool, so no copay/deductible figures appear here.
 *
 * Reads `Plan.treatments[]`, already fetched with the plan; no new request.
 *
 * @param {object} props.data  { policy, plan, plans }
 * @param {object} props.member
 */
export default function PlanComparisonTool({ data, member }) {
  const [expandedRowId, setExpandedRowId] = useState(null);

  const plan = data?.plan;
  const activeTier = member?.eligibility?.tier;
  const { columns, groups } = toTreatmentCoverage(
    plan,
    activeTier,
    conditionNamesOf(member)
  );

  const treatmentCount = groups.reduce(
    (total, group) => total + group.rows.length,
    0
  );

  const renderCell = (row, column) => {
    // Each treatment declares a single tier, so it only speaks to that column.
    if (row.tier && row.tier !== column.id.toLowerCase()) {
      return <span className={styles.notApplicable}>—</span>;
    }

    const isExpanded = expandedRowId === row.id;

    return (
      <div className={styles.cell}>
        <span
          className={`${styles.mark} ${row.covered ? "" : styles.markUncovered}`}
          aria-label={row.covered ? "Covered" : "Not covered"}
        >
          {row.covered ? "✓" : "✗"}
        </span>

        {row.isPartial && (
          <button
            type="button"
            className={styles.partial}
            aria-expanded={isExpanded}
            onClick={() => setExpandedRowId(isExpanded ? null : row.id)}
          >
            Partial
          </button>
        )}

        {row.priorAuthRequired && (
          <span className={styles.tag}>Prior auth required</span>
        )}

        {isExpanded && row.steps.length > 0 && (
          <ul className={styles.steps}>
            {row.steps.map((step) => (
              <li key={step.id} className={styles.step}>
                <span
                  className={
                    step.covered ? styles.stepMark : styles.stepMarkUncovered
                  }
                >
                  {step.covered ? "✓" : "✗"}
                </span>
                {step.name}
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  };

  if (!columns.length || !treatmentCount) {
    return (
      <p className={styles.empty}>
        This plan lists no treatments to compare.
      </p>
    );
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
        {planMeta && ` — ${planMeta}`}. What this plan covers, by tier and
        condition. The member&apos;s enrolled tier is highlighted.
      </p>

      <ComparisonTable
        columns={columns}
        groups={groups}
        renderCell={renderCell}
        attributeLabel="Treatment"
      />

      <CrossPlanCoverage
        plans={data?.plans ?? []}
        currentPlanId={pick(plan, "plan_id", "planId")}
        tierName={activeTier}
      />
    </>
  );
}

/**
 * How the rest of the catalog treats the member's tier. Framed as the catalog,
 * not "plans available to you" — nothing models enrollment eligibility, and
 * premiums live on the Policy rather than the Plan.
 */
function CrossPlanCoverage({ plans, currentPlanId, tierName }) {
  const entries = toCrossPlanCoverage(plans, currentPlanId, tierName);
  if (!entries.length) return null;

  const tierLabel = String(tierName ?? "specialty").toLowerCase();

  return (
    <>
      <h4 className={styles.sectionLabel}>
        {tierLabel.charAt(0).toUpperCase() + tierLabel.slice(1)} coverage across
        plans
      </h4>

      <ul className={styles.list}>
        {entries.map((entry) => (
          <li key={entry.id}>
            <div
              className={`${styles.planCard} ${
                entry.isCurrent ? styles.planCardCurrent : ""
              }`}
            >
              <div className={styles.planHeader}>
                <p
                  className={`${styles.planName} ${
                    entry.isCurrent ? styles.planNameCurrent : ""
                  }`}
                >
                  {entry.name}
                  {entry.isCurrent && <span className={styles.badge}>Current</span>}
                </p>
                <span className={styles.planValue}>
                  {entry.covered ? "Covered" : "Not covered"}
                </span>
              </div>

              <p className={styles.planMeta}>
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
