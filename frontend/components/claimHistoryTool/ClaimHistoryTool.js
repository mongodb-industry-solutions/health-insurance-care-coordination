"use client";

import { useState } from "react";
import Icon from "@leafygreen-ui/icon";
import { useClaimTrace } from "./useClaimTrace";
import styles from "./ClaimHistoryTool.module.css";

/** Matches the Claim schema's status values, not a generic approved/denied set. */
const STATUS_FILTERS = [
  { id: "all", label: "All" },
  { id: "paid", label: "Paid" },
  { id: "approved", label: "Approved" },
  { id: "denied", label: "Denied" },
  { id: "approved_restricted", label: "Approved (restricted)" },
  { id: "pending", label: "Pending" },
];

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

function readable(value) {
  if (!value) return null;
  return String(value).replaceAll("_", " ");
}

/** The decision behind a claim — a compact preview of the full trace view. */
function ClaimExpansion({ trace, loading }) {
  if (loading) {
    return <p className={styles.review}>Loading decision…</p>;
  }

  if (!trace || trace.error) {
    return (
      <p className={styles.review}>
        Could not load the decision trace for this claim.
      </p>
    );
  }

  const outcome = trace.outcome ?? {};
  const review = trace.review ?? {};
  const routedToHuman = pick(review, "routed_to_human", "routedToHuman");
  const closedBy =
    pick(review, "final_decision_maker", "finalDecisionMaker") ??
    pick(review, "closed_by", "closedBy");

  return (
    <div className={styles.expansion}>
      <span className={styles.expansionLabel}>Decision</span>
      <p className={styles.decision}>
        {readable(outcome.decision ?? trace.status) ?? "No decision recorded"}
      </p>

      {outcome.rationale && (
        <p className={styles.rationale}>{outcome.rationale}</p>
      )}

      {(routedToHuman || closedBy) && (
        <p className={styles.review}>
          {[
            routedToHuman && "Routed to a medical director",
            closedBy && `closed by ${closedBy}`,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      )}
    </div>
  );
}

/**
 * Claim History: every claim on the member, filterable by status. A row only
 * expands when the claim carries a `linkedAuditTraceId` — a routine claim that
 * never went through prior authorization has no "why" to show, so it gets no
 * chevron rather than an empty panel.
 *
 * @param {Array} props.claims  From GET /api/claims/member/{memberId}.
 */
export default function ClaimHistoryTool({ claims = [] }) {
  const [status, setStatus] = useState("all");
  const [expandedId, setExpandedId] = useState(null);
  const { traces, loadingId, loadTrace } = useClaimTrace();

  const present = new Set(claims.map((claim) => claim.status).filter(Boolean));
  const visible =
    status === "all"
      ? claims
      : claims.filter((claim) => claim.status === status);

  const sorted = [...visible].sort((a, b) =>
    String(pick(b, "service_date", "serviceDate") ?? "").localeCompare(
      String(pick(a, "service_date", "serviceDate") ?? "")
    )
  );

  const toggle = (claimId, traceId) => {
    if (expandedId === claimId) {
      setExpandedId(null);
      return;
    }

    setExpandedId(claimId);
    loadTrace(traceId);
  };

  if (!claims.length) {
    return <p className={styles.empty}>No claims on record.</p>;
  }

  return (
    <>
      <div className={styles.filters} role="group" aria-label="Filter by status">
        {STATUS_FILTERS.map((filter) => (
          <button
            key={filter.id}
            type="button"
            className={`${styles.filter} ${
              status === filter.id ? styles.filterActive : ""
            }`}
            // Statuses absent from this member's claims stay visible but inert,
            // so the filter set still communicates the full schema.
            disabled={filter.id !== "all" && !present.has(filter.id)}
            aria-pressed={status === filter.id}
            onClick={() => setStatus(filter.id)}
          >
            {filter.label}
          </button>
        ))}
      </div>

      {sorted.length === 0 ? (
        <p className={styles.empty}>No claims with this status.</p>
      ) : (
        <ul className={styles.list}>
          {sorted.map((claim) => {
            const claimId = pick(claim, "claim_id", "claimId");
            const traceId = pick(
              claim,
              "linked_audit_trace_id",
              "linkedAuditTraceId"
            );
            const isExpanded = expandedId === claimId;

            const body = (
              <>
                <div className={styles.main}>
                  <span className={styles.procedure}>
                    {pick(claim, "procedure_desc", "procedureDesc") ??
                      claim.service ??
                      "Claim"}
                  </span>
                  {(pick(claim, "diagnosis_display", "diagnosisDisplay") ??
                    claim.diagnosis) && (
                    <p className={styles.diagnosis}>
                      {pick(claim, "diagnosis_display", "diagnosisDisplay") ??
                        claim.diagnosis}
                    </p>
                  )}
                  <p className={styles.date}>
                    {[
                      pick(claim, "service_date", "serviceDate"),
                      readable(pick(claim, "denial_reason", "denialReason")),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                </div>

                <div className={styles.amounts}>
                  <div className={styles.owed}>
                    {money(
                      pick(claim, "member_owed", "memberOwed"),
                      claim.currency
                    ) ?? "—"}
                  </div>
                  <p className={styles.billed}>
                    of{" "}
                    {money(
                      pick(claim, "billed_amt", "billedAmt"),
                      claim.currency
                    ) ?? "—"}{" "}
                    billed
                  </p>
                  {claim.status && (
                    <span
                      className={`${styles.statusPill} ${
                        styles[claim.status] ?? ""
                      }`}
                    >
                      {readable(claim.status)}
                    </span>
                  )}
                </div>
              </>
            );

            return (
              <li key={claimId} className={styles.claim}>
                {traceId ? (
                  <button
                    type="button"
                    className={styles.rowButton}
                    aria-expanded={isExpanded}
                    onClick={() => toggle(claimId, traceId)}
                  >
                    {body}
                    <span
                      className={`${styles.chevron} ${
                        isExpanded ? styles.chevronOpen : ""
                      }`}
                    >
                      <Icon glyph="ChevronRight" size={16} />
                    </span>
                  </button>
                ) : (
                  <div className={styles.rowStatic}>{body}</div>
                )}

                {isExpanded && traceId && (
                  <ClaimExpansion
                    trace={traces[traceId]}
                    loading={loadingId === traceId}
                  />
                )}
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
