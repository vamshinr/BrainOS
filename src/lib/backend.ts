// Single source of truth for the backend URL.
// Server-side (API routes): reads BACKEND_URL env var.
// Falls back to localhost:8081 for local dev.
export const BACKEND_URL =
  (process.env.BACKEND_URL || "http://localhost:8081").replace(/\/$/, "");
