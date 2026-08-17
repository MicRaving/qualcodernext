/** Shared configuration constants — no magic numbers in business logic. */

/** Backend dev-port fallback. */
export const DEV_API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8765/api/v1";

/** Maximum port-file polling attempts when resolving the Tauri backend port. */
export const PORT_POLL_MAX_ATTEMPTS = 150;

/** Milliseconds between port-file polls. */
export const PORT_POLL_INTERVAL_MS = 200;

/** Default request timeout (ms) for normal API calls. */
export const REQUEST_TIMEOUT_MS = 15_000;

/** Timeout for raw source-file fetches (large PDFs, images). */
export const SOURCE_TIMEOUT_MS = 60_000;
