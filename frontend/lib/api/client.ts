import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

/**
 * The typed client generated from `openapi.json` (`npm run generate:api`).
 *
 * Requests go to this origin's `/api`, which `next.config.ts` forwards to
 * the backend, so the browser never talks to port 8000 directly. `fetch`
 * is looked up per request rather than captured once, so tests can stub it.
 */
export const api = createClient<paths>({
  baseUrl: typeof window === "undefined" ? "" : window.location.origin,
  fetch: (request) => globalThis.fetch(request),
});

export type Schemas = components["schemas"];
