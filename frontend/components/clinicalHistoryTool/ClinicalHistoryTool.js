"use client";

import { useState } from "react";
import styles from "./ClinicalHistoryTool.module.css";

function pick(source, ...keys) {
  if (!source) return undefined;
  return keys.map((key) => source[key]).find((value) => value != null);
}

function readable(value) {
  if (!value) return null;
  const text = String(value).replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * Outcome vocabulary is written by the agent, not fixed by an enum — seeds use
 * `ongoing`, the care-coordination path writes `gap_reviewed`, and Phase 1 writes
 * the adequate/inadequate assessment. Matching on substrings covers all of them
 * without pinning to exact strings.
 */
function outcomeClass(outcome) {
  const value = String(outcome ?? "").toLowerCase();

  if (value.includes("gap_reviewed")) return styles.outcomeGapReviewed;
  if (value.includes("inadequate") || value.includes("partial")) {
    return styles.outcomeInadequate;
  }
  if (value.includes("adequate") || value.includes("approved")) {
    return styles.outcomeAdequate;
  }
  return styles.outcomeNeutral;
}

function isGapReviewed(outcome) {
  return String(outcome ?? "").toLowerCase() === "gap_reviewed";
}

function Diagnoses({ items }) {
  return (
    <ul className={styles.list}>
      {items.map((diagnosis) => (
        <li key={diagnosis.code} className={styles.item}>
          <div className={styles.itemHeader}>
            <span className={styles.itemTitle}>{diagnosis.display}</span>
            <span
              className={`${styles.pill} ${
                diagnosis.status === "active"
                  ? styles.statusActive
                  : styles.statusOther
              }`}
            >
              {readable(diagnosis.status)}
            </span>
          </div>
          <p className={styles.meta}>
            {diagnosis.system} {diagnosis.code}
          </p>
        </li>
      ))}
    </ul>
  );
}

function Medications({ items }) {
  return (
    <ul className={styles.list}>
      {items.map((medication, index) => (
        <li key={`${medication.code}-${index}`} className={styles.item}>
          <div className={styles.itemHeader}>
            <span className={styles.itemTitle}>{medication.display}</span>
            <span
              className={`${styles.pill} ${
                medication.status === "active"
                  ? styles.statusActive
                  : styles.statusOther
              }`}
            >
              {readable(medication.status)}
            </span>
          </div>
          <p className={styles.meta}>
            {[
              [medication.system, medication.code].filter(Boolean).join(" "),
              medication.reason,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </li>
      ))}
    </ul>
  );
}

/**
 * The richest section: the model's episodic memory. A `gap_reviewed` entry means
 * an apparent gap was investigated and explained, so it is tagged neutrally
 * rather than treated as a failed trial.
 */
function TreatmentHistory({ items }) {
  return (
    <ul className={styles.list}>
      {items.map((response, index) => {
        const outcome = response.outcome;
        const months = pick(response, "duration_months", "durationMonths");
        const gapReviewed = isGapReviewed(outcome);

        return (
          <li key={`${response.drug}-${index}`} className={styles.item}>
            <div className={styles.itemHeader}>
              <span className={styles.itemTitle}>
                {response.drug}
                {months != null && (
                  <span className={styles.duration}> · {months} months</span>
                )}
              </span>
              <span className={`${styles.pill} ${outcomeClass(outcome)}`}>
                {gapReviewed ? "Gap reviewed" : readable(outcome)}
              </span>
            </div>

            {response.notes && <p className={styles.note}>{response.notes}</p>}

            <p className={styles.meta}>
              {[
                pick(response, "documented_by", "documentedBy"),
                pick(response, "documented_on", "documentedOn"),
                pick(response, "related_note", "relatedNote") &&
                  `cites ${pick(response, "related_note", "relatedNote")}`,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </li>
        );
      })}
    </ul>
  );
}

function ClinicalNotes({ items }) {
  const sorted = [...items].sort((a, b) =>
    String(a.date ?? "").localeCompare(String(b.date ?? ""))
  );

  return (
    <ul className={styles.list}>
      {sorted.map((note, index) => (
        <li key={pick(note, "note_id", "noteId") ?? index} className={styles.item}>
          <div className={styles.itemHeader}>
            <span className={styles.itemTitle}>{readable(note.type)}</span>
            <span className={styles.duration}>{note.date}</span>
          </div>
          {/* `note` is already the full text in this schema — nothing to expand. */}
          <p className={styles.note}>{note.note}</p>
          <p className={styles.meta}>{note.author}</p>
        </li>
      ))}
    </ul>
  );
}

/**
 * Clinical History Review: the four real sub-arrays of `clinical_history`, one
 * per filter, rather than a flattened list with a fuzzy category field.
 *
 * Reads the member document the dashboard already loaded — `clinical_history` is
 * part of `GET /api/members/{id}`, so no scoped route is needed.
 *
 * @param {object} props.member
 */
export default function ClinicalHistoryTool({ member }) {
  const history = member?.clinical_history ?? member?.clinicalHistory ?? {};

  const sections = [
    {
      id: "diagnoses",
      label: "Diagnoses",
      items: history.diagnoses ?? [],
      render: Diagnoses,
    },
    {
      id: "medications",
      label: "Medications",
      items: history.medications ?? [],
      render: Medications,
    },
    {
      id: "treatments",
      label: "Treatment History",
      items: pick(history, "treatment_responses", "treatmentResponses") ?? [],
      render: TreatmentHistory,
    },
    {
      id: "notes",
      label: "Clinical Notes",
      items: pick(history, "clinical_notes", "clinicalNotes") ?? [],
      render: ClinicalNotes,
    },
  ];

  // Open on Treatment History when there is any, since it carries the most.
  const [activeId, setActiveId] = useState(
    sections.find((section) => section.id === "treatments")?.items.length
      ? "treatments"
      : "diagnoses"
  );

  const active = sections.find((section) => section.id === activeId);
  const Render = active?.render;

  return (
    <>
      <div className={styles.tabs} role="group" aria-label="Record section">
        {sections.map((section) => (
          <button
            key={section.id}
            type="button"
            className={`${styles.tab} ${
              activeId === section.id ? styles.tabActive : ""
            }`}
            disabled={section.items.length === 0}
            aria-pressed={activeId === section.id}
            onClick={() => setActiveId(section.id)}
          >
            {section.label}{" "}
            <span className={styles.count}>({section.items.length})</span>
          </button>
        ))}
      </div>

      {active?.items.length ? (
        <Render items={active.items} />
      ) : (
        <p className={styles.empty}>Nothing recorded in this section.</p>
      )}
    </>
  );
}
