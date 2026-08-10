"use client";

import { useState } from "react";
import ClinicalTimeline from "@/components/clinicalTimeline/ClinicalTimeline";
import { toActiveTreatment, toTimelineEvents } from "@/lib/memberPresenter";
import styles from "./DetailPanel.module.css";

const TABS = [
  { id: "clinical", label: "Clinical Context" },
  { id: "insurance", label: "Insurance Information" },
];

/**
 * Insurance fields taken from what the member document actually carries. The
 * full field list for this tab is still unconfirmed — see the note rendered
 * below the rows.
 */
function insuranceRows(member) {
  const eligibility = member?.eligibility ?? {};

  // The Member model carries a policy id, not a plan id (see backend/members/models.py).
  return [
    { label: "Policy", value: member?.policyId ?? member?.policy_id },
    { label: "Coverage tier", value: eligibility.tier },
    { label: "Status", value: eligibility.status },
    {
      label: "Effective date",
      value: eligibility.effectiveDate ?? eligibility.effective_date,
    },
    {
      label: "Coverage end",
      value: eligibility.termDate ?? eligibility.term_date ?? "—",
    },
    { label: "State", value: member?.state },
  ];
}

/**
 * Tabbed detail panel below the identity card. Both tabs read from the member
 * document already loaded by the dashboard, so switching tabs costs no request.
 */
export default function DetailPanel({ member }) {
  const [activeTab, setActiveTab] = useState("clinical");

  return (
    <div className={styles.panel}>
      <div className={styles.tabBar} role="tablist">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            className={`${styles.tab} ${
              activeTab === tab.id ? styles.tabActive : ""
            }`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className={styles.content} role="tabpanel">
        {activeTab === "clinical" ? (
          <ClinicalTimeline
            events={toTimelineEvents(member)}
            activeTreatment={toActiveTreatment(member)}
          />
        ) : (
          <>
            <dl className={styles.rows}>
              {insuranceRows(member).map((row) => (
                <div key={row.label} style={{ display: "contents" }}>
                  <dt className={styles.label}>{row.label}</dt>
                  <dd className={styles.value}>{row.value ?? "Not on file"}</dd>
                </div>
              ))}
            </dl>
            {/* TODO: confirm the intended field list for this tab (deductible
                status, claim summary, premium?) — these are placeholders drawn
                from the member document. */}
            <p className={styles.note}>
              Field list for this tab is not finalized.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
