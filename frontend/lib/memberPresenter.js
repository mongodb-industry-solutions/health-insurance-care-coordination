/**
 * Shapes the raw member document from `GET /api/members/{id}` into the fields
 * the dashboard renders. Kept out of the components so the API shape only has
 * to be understood in one place.
 *
 * Note on casing: FastAPI serializes by alias, and only some fields in
 * `backend/members/models.py` declare one. So the payload is mixed — aliased
 * fields arrive camelCase (`memberId`, `dateOfBirth`, `pendingActions`,
 * `effectiveDate`), while un-aliased ones keep their snake_case field names
 * (`clinical_history`, `current_care_plan`, `treatment_responses`). `pick()`
 * accepts either, so this keeps working if aliases are added later.
 */

/** First present value among the given keys. */
function pick(source, ...keys) {
  if (!source) return undefined;
  return keys.map((key) => source[key]).find((value) => value != null);
}

function titleCase(value) {
  if (!value) return null;
  return String(value)
    .split(/[\s_]+/)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(" ");
}

function clinicalHistoryOf(member) {
  return pick(member, "clinical_history", "clinicalHistory") ?? {};
}

function carePlanOf(member) {
  return pick(member, "current_care_plan", "currentCarePlan") ?? {};
}

function treatmentResponsesOf(member) {
  return (
    pick(clinicalHistoryOf(member), "treatment_responses", "treatmentResponses") ??
    []
  );
}

/** Label/value rows for the patient identity card. */
export function toIdentityRows(member) {
  const eligibility = member?.eligibility ?? {};
  const provider = pick(carePlanOf(member), "managing_provider", "managingProvider");

  const effectiveDate = pick(eligibility, "effective_date", "effectiveDate");
  const eligibilityValue = eligibility.status
    ? [titleCase(eligibility.status), effectiveDate && `since ${effectiveDate}`]
        .filter(Boolean)
        .join(" ")
    : null;

  const providerValue = provider
    ? [provider.name, provider.specialty && titleCase(provider.specialty)]
        .filter(Boolean)
        .join(" · ")
    : null;

  return [
    { label: "Gender", value: titleCase(member?.gender) },
    { label: "Date of birth", value: pick(member, "date_of_birth", "dateOfBirth") },
    { label: "Eligibility", value: eligibilityValue },
    { label: "Coverage tier", value: titleCase(eligibility.tier) },
    { label: "Managing provider", value: providerValue },
  ];
}

/**
 * Reverse-chronological timeline built from the member's clinical history. The
 * current entry comes from the open pending action or the therapy under
 * consideration, so it reflects what the member is actually waiting on.
 */
export function toTimelineEvents(member) {
  const history = clinicalHistoryOf(member);
  const events = [];

  const openAction = (pick(member, "pending_actions", "pendingActions") ?? []).find(
    (action) => action.status === "pending" || action.status === "in_progress"
  );
  const consideringTherapy = pick(
    carePlanOf(member),
    "considering_therapy",
    "consideringTherapy"
  );

  if (openAction || consideringTherapy) {
    events.push({
      id: "current",
      isCurrent: true,
      description: consideringTherapy
        ? `Awaiting approval for ${titleCase(consideringTherapy)}`
        : "Awaiting new treatment approval",
    });
  }

  (pick(history, "treatment_responses", "treatmentResponses") ?? []).forEach(
    (response, index) => {
      events.push({
        id: `treatment-${index}`,
        date: pick(response, "documented_on", "documentedOn"),
        actor: pick(response, "documented_by", "documentedBy"),
        eventType: "Medication change",
        description: response.notes,
      });
    }
  );

  (pick(history, "clinical_notes", "clinicalNotes") ?? []).forEach(
    (note, index) => {
      events.push({
        id: pick(note, "note_id", "noteId") ?? `note-${index}`,
        date: note.date,
        actor: note.author,
        eventType: titleCase(note.type),
        description: note.note,
      });
    }
  );

  return events.sort((a, b) => {
    if (a.isCurrent) return -1;
    if (b.isCurrent) return 1;
    return String(b.date ?? "").localeCompare(String(a.date ?? ""));
  });
}

/** The highlighted "Active Treatment" pill under the timeline. */
export function toActiveTreatment(member) {
  const responses = treatmentResponsesOf(member);
  const latest = responses[responses.length - 1];

  if (!latest?.drug) return null;

  const months = pick(latest, "duration_months", "durationMonths");
  const duration = months ? `${months} Month Trial` : null;

  return {
    label: "Active Treatment",
    value: [titleCase(latest.drug), duration].filter(Boolean).join(" - "),
  };
}

/** Pending actions, with the raw type turned into readable copy. */
export function toPendingActions(member) {
  return (pick(member, "pending_actions", "pendingActions") ?? [])
    .filter((action) => action.status !== "resolved")
    .map((action) => ({
      id: pick(action, "action_id", "actionId"),
      status: action.status,
      label: titleCase(action.type),
      proposedTreatment: pick(action, "proposed_treatment", "proposedTreatment"),
    }));
}
