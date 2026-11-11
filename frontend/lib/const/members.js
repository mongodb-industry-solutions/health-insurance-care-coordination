/**
 * Selectable demo members for the landing page.
 *
 * Mirrors the seeded profiles in `backend/seed/generators/profiles.py` — keep
 * `memberId`, `birthDate` and `gender` in sync with that file, which is the
 * source of truth. The copy fields (`summary`, `pathNote`) are demo narration
 * and only live here.
 */

export const MEMBERS = [
  {
    memberId: "MBR-2026-44109",
    firstName: "Maria",
    name: "Maria Reyes",
    birthDate: "1983-04-12",
    gender: "Female",
    avatar: "/avatars/girl_user_1.png",
    caseType: "clean_approval",
    summary:
      "Requests secukinumab for rheumatoid arthritis after seven months of methotrexate with an inadequate response and one explained refill gap.",
    pathNote: "Shows a happy path with quick & smart verification.",
  },
  {
    memberId: "MBR-2026-51882",
    firstName: "Robert",
    name: "Robert Chen",
    birthDate: "1975-11-03",
    gender: "Male",
    avatar: "/avatars/male_user_1.png",
    caseType: "clean_approval",
    summary:
      "Requests adalimumab for psoriatic arthritis after eight uninterrupted months of methotrexate with an inadequate response.",
    pathNote: "Shows a clean approval with no gaps to explain.",
  },
  {
    memberId: "MBR-2026-60417",
    firstName: "Aisha",
    name: "Aisha Bello",
    birthDate: "1990-07-22",
    gender: "Female",
    avatar: "/avatars/girl_user_2.png",
    caseType: "human_review",
    summary:
      "Requests ustekinumab for Crohn's disease after only a partial response to azathioprine, with an atypical presentation.",
    pathNote: "Shows an ambiguous case routed to a medical director.",
  },
  {
    memberId: "MBR-2026-73305",
    firstName: "David",
    name: "David Thompson",
    birthDate: "1968-02-17",
    gender: "Male",
    avatar: "/avatars/male_user_1.png",
    caseType: "denial",
    summary:
      "Requests secukinumab for rheumatoid arthritis after just three months of methotrexate, short of the required step-therapy trial.",
    pathNote: "Shows a denial recommendation a medical director must close.",
  },
  {
    memberId: "MBR-2026-88214",
    firstName: "Grace",
    name: "Grace Kim",
    birthDate: "1979-09-30",
    gender: "Female",
    avatar: "/avatars/girl_user_3.png",
    caseType: "coverage_denial",
    summary:
      "Clinically qualifies for secukinumab, but her standard plan does not cover the specialty tier the therapy sits in.",
    pathNote: "Shows an administrative benefit denial, not a clinical one.",
  },
  {
    memberId: "MBR-2026-90733",
    firstName: "Frank",
    name: "Frank Alvarez",
    birthDate: "1972-06-08",
    gender: "Male",
    avatar: "/avatars/male_user_1.png",
    caseType: "ineligible",
    summary:
      "Requests adalimumab for psoriatic arthritis, but his coverage ended on May 31, 2026 — before the request was filed.",
    pathNote: "Shows an eligibility check failing before any clinical review.",
  },
];

/**
 * Badge shown at the bottom of the hover info card, per case type. `variant`
 * values are LeafyGreen Badge variants: green for the straight-through path,
 * yellow when a human has to weigh in, red for the paths that end in a denial.
 */
export const CASE_TYPE_BADGES = {
  clean_approval: { label: "Straight-through", variant: "green" },
  human_review: { label: "Human in the loop", variant: "yellow" },
  denial: { label: "Denial recommended", variant: "red" },
  coverage_denial: { label: "Benefit denial", variant: "red" },
  ineligible: { label: "Not eligible", variant: "red" },
};

/** Age in whole years from an ISO birth date, so the cards never go stale. */
export function getAge(birthDate, today = new Date()) {
  const born = new Date(birthDate);
  let age = today.getFullYear() - born.getFullYear();
  const beforeBirthday =
    today.getMonth() < born.getMonth() ||
    (today.getMonth() === born.getMonth() && today.getDate() < born.getDate());

  if (beforeBirthday) age -= 1;
  return age;
}
