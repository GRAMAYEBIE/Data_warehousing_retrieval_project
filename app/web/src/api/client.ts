// Typed client of the assistant API. Every type comes from schema.d.ts, generated from the
// API's OpenAPI contract (`npm run types`): nothing here describes the API by hand.
// The browser calls /api; nginx (or the Vite dev server) adds the API token, so the token
// is never shipped to the browser.
import type { components } from "./schema";

export type Answer = components["schemas"]["Answer"];
export type Filter = components["schemas"]["Filter"];
export type Health = components["schemas"]["Health"];
export type CatalogView = components["schemas"]["CatalogView"];
export type ReportView = components["schemas"]["ReportView"];
export type ReportPreview = components["schemas"]["ReportPreview"];
export type QueryPlan = components["schemas"]["QueryPlan"];

export class ApiError extends Error {
  constructor(
    public status: number,
    public reasons: string[],
  ) {
    super(reasons.join("; ") || `HTTP ${status}`);
  }
}

async function call<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = payload?.detail;
    const reasons: string[] =
      detail?.reasons ?? (typeof detail === "string" ? [detail] : [`HTTP ${response.status}`]);
    throw new ApiError(response.status, reasons);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => call<Health>("GET", "/health"),
  catalog: () => call<CatalogView>("GET", "/catalog"),
  newSession: () =>
    call<components["schemas"]["SessionCreated"]>("POST", "/sessions").then((s) => s.session_id),
  ask: (sessionId: string, question: string) =>
    call<Answer>("POST", `/sessions/${sessionId}/ask`, { question }),
  reset: (sessionId: string) =>
    call<components["schemas"]["SessionReset"]>("POST", `/sessions/${sessionId}/reset`),
  createReport: (request: string) => call<ReportView>("POST", "/reports", { request }),
  confirmReport: (reportId: string) =>
    call<ReportView>("POST", `/reports/${reportId}/confirm`, { confirm: true }),
};
