"use client";

import AuthorizationHistory from "@/components/authorizationHistory/AuthorizationHistory";
import CoverageTierCard from "@/components/coverageTierCard/CoverageTierCard";
import OutOfPocketProgress from "@/components/outOfPocketProgress/OutOfPocketProgress";
import RequestedTreatmentCoverage from "@/components/requestedTreatmentCoverage/RequestedTreatmentCoverage";
import {
  toAuthorizationHistory,
  toCoverageTiers,
  toOutOfPocket,
  toPolicySummary,
  toRequestedTreatment,
} from "@/lib/insurancePresenter";
import { useInsuranceInformation } from "./useInsuranceInformation";
import styles from "./InsuranceInformation.module.css";

/**
 * Insurance Information tab: policy summary, then coverage by tier.
 *
 * @param {object} props.member  Raw member document (supplies the policy id and active tier).
 */
export default function InsuranceInformation({ member }) {
  const policyId = member?.policyId ?? member?.policy_id;
  const memberId = member?.memberId ?? member?.member_id;
  const { policy, plan, claims, traces, loading, error } =
    useInsuranceInformation(policyId, memberId);

  if (!policyId) {
    return <p className={styles.status}>No policy on file for this member.</p>;
  }

  if (loading) {
    return <p className={styles.status}>Loading policy…</p>;
  }

  if (error) {
    return (
      <p className={styles.status}>
        Could not load policy details ({error.message}).
      </p>
    );
  }

  const summary = toPolicySummary(policy);
  const activeTier = member?.eligibility?.tier;
  const tiers = toCoverageTiers(plan, activeTier);
  const outOfPocket = toOutOfPocket({ plan, activeTier, claims });

  // The therapy under consideration, and the diagnosis it was raised against.
  const carePlan = member?.current_care_plan ?? member?.currentCarePlan ?? {};
  const openAction = (member?.pendingActions ?? member?.pending_actions ?? []).find(
    (action) => action.status !== "resolved"
  );
  const requestedTreatment = toRequestedTreatment({
    plan,
    therapyName:
      carePlan.considering_therapy ??
      carePlan.consideringTherapy ??
      openAction?.proposedTreatment ??
      openAction?.proposed_treatment,
    diagnosisCode:
      openAction?.relatedDiagnosisCode ?? openAction?.related_diagnosis_code,
  });

  const authorizations = toAuthorizationHistory(traces);

  return (
    <div className={styles.stack}>
      <dl className={styles.summary}>
        {summary.map((row) => (
          <div key={row.label}>
            <dt className={styles.label}>{row.label}</dt>
            <dd className={styles.value}>{row.value ?? "Not on file"}</dd>
          </div>
        ))}
      </dl>

      <OutOfPocketProgress outOfPocket={outOfPocket} />

      {requestedTreatment && (
        <section>
          <h3 className={styles.sectionLabel}>Requested treatment</h3>
          <RequestedTreatmentCoverage treatment={requestedTreatment} />
        </section>
      )}

      {tiers.length > 0 && (
        <section>
          <h3 className={styles.sectionLabel}>Coverage by tier</h3>

          <div className={styles.tiers}>
            {tiers.map((tier) => (
              <CoverageTierCard
                key={tier.id}
                title={tier.title}
                isActive={tier.isActive}
                priorAuthLabel={tier.priorAuthLabel}
                costLine={tier.costLine}
              />
            ))}
          </div>
        </section>
      )}

      <section>
        <h3 className={styles.sectionLabel}>Authorization history</h3>
        <AuthorizationHistory entries={authorizations} />
      </section>
    </div>
  );
}
