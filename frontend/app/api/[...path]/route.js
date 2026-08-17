/**
 * Proxies every `/api/*` call to the FastAPI backend.
 *
 * The browser only ever talks to this origin, so the backend stays on the
 * internal network — a Compose service name locally, a Kubernetes service name
 * in Kanopy — and needs no public ingress.
 *
 * This is a route handler rather than a `next.config.mjs` rewrite on purpose:
 * rewrite destinations are resolved at `next build` and frozen into
 * `.next/routes-manifest.json`, so `BACKEND_URL` would be baked into the image.
 * Read here, it is a real runtime value and one image serves every environment.
 *
 * The upstream body is passed through untouched so the SSE endpoints
 * (`/api/chat/{agent}/stream`, `/api/members/{id}/authorization/start`) stream
 * rather than buffer.
 */

// Never prerender or cache: every call is a live proxy.
export const dynamic = "force-dynamic";

const BACKEND_URL = () => process.env.BACKEND_URL ?? "http://localhost:8000";

/** Hop-by-hop headers, and ones that describe the *inbound* request only. */
const STRIPPED = new Set([
  "host",
  "connection",
  "keep-alive",
  "transfer-encoding",
  "upgrade",
  "content-length",
]);

function forwardable(headers) {
  const out = new Headers();
  for (const [key, value] of headers) {
    if (!STRIPPED.has(key.toLowerCase())) out.set(key, value);
  }
  return out;
}

async function proxy(request, { params }) {
  const { path } = await params;
  const { search } = new URL(request.url);
  const target = `${BACKEND_URL()}/api/${path.join("/")}${search}`;

  const hasBody = request.method !== "GET" && request.method !== "HEAD";

  let upstream;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers: forwardable(request.headers),
      body: hasBody ? request.body : undefined,
      // Required when streaming a request body through undici.
      duplex: hasBody ? "half" : undefined,
      redirect: "manual",
      cache: "no-store",
    });
  } catch (error) {
    // The backend being unreachable is an infrastructure fault, not a 404 —
    // name the target so a misconfigured BACKEND_URL is obvious in the logs.
    console.error(`Proxy to ${target} failed:`, error);
    return Response.json(
      { detail: `Backend unreachable at ${BACKEND_URL()}` },
      { status: 502 }
    );
  }

  // Stream the body straight through; only drop the encoding headers, which
  // describe a transfer fetch has already undone.
  const headers = new Headers(upstream.headers);
  headers.delete("content-encoding");
  headers.delete("content-length");

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const HEAD = proxy;
export const OPTIONS = proxy;
