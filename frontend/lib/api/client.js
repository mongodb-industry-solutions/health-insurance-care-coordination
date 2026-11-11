/**
 * Thin wrapper around the FastAPI backend (see `backend/main.py`). Every route
 * there is mounted under `/api/...`, so callers pass paths like
 * `/api/members/MBR-2026-44109`.
 */

// Empty by default: requests go same-origin and `next.config.mjs` rewrites
// `/api/*` to the backend.
const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

export async function apiFetch(path, options = {}) {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(
      `${options.method ?? "GET"} ${path} failed (${response.status}) ${detail}`
    );
  }

  return response.json();
}
