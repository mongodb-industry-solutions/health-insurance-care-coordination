/**
 * `/api/*` is proxied to the backend by the route handler in
 * `app/api/[...path]/route.js`, not by a rewrite here — rewrite destinations are
 * frozen into the build manifest, which would bake `BACKEND_URL` into the image.
 */

/** @type {import('next').NextConfig} */
const nextConfig = {};

export default nextConfig;
