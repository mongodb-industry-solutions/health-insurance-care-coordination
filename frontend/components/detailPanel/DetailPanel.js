"use client";

import { useState } from "react";
import ClinicalTimeline from "@/components/clinicalTimeline/ClinicalTimeline";
import InsuranceInformation from "@/components/insuranceInformation/InsuranceInformation";
import { toActiveTreatment, toTimelineEvents } from "@/lib/memberPresenter";
import styles from "./DetailPanel.module.css";

const TABS = [
  { id: "clinical", label: "Clinical Context" },
  { id: "insurance", label: "Insurance Information" },
];

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
          <InsuranceInformation member={member} />
        )}
      </div>
    </div>
  );
}
