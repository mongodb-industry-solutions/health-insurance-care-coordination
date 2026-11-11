import { apiFetch } from "./client";

/**
 * POST /api/admin/reset-demo — wipe every seeded collection and reseed the
 * canonical members plus the shared catalog (plans, guidelines, precedent
 * claims). Destructive: audit traces and notifications from previous runs go
 * too, which is the point — it is how a demo gets a clean slate.
 *
 * Backed by the same `AdminService.reset_all()` the root `POST /reset-demo` and
 * `python -m seed.seed_data --reset` run; `/api/admin` is the path the browser
 * can reach through the Next.js proxy.
 *
 * Takes a second or two for six members. Resolves to
 * `{ removed: {collection: count}, seeded: {...} }`.
 */
export function resetDemo() {
  return apiFetch("/api/admin/reset-demo", { method: "POST" });
}

/**
 * POST /api/admin/members/{memberId}/reset-demo — restore one member to their
 * pre-run baseline, leaving the other members and the shared catalog alone.
 * Rejects with a 404 message when the id has no canonical profile.
 */
export function resetMember(memberId) {
  return apiFetch(`/api/admin/members/${memberId}/reset-demo`, {
    method: "POST",
  });
}
