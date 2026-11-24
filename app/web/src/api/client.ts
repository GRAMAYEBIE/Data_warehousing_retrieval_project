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
export type OverviewView = components["schemas"]["OverviewView"];
export type ForecastView = components["schemas"]["ForecastView"];

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

// Live progress of an answer (POST .../ask/stream, one JSON object per line).
export type StreamEvent =
  | { type: "step"; step: string; state: "start" | "done"; ms?: number }
  | { type: "token"; text: string }
  | { type: "answer"; answer: Answer }
  | { type: "error"; message: string };

async function askStream(sessionId: string, question: string, onEvent: (event: StreamEvent) => void): Promise<Answer> {
  const response = await fetch(`/api/sessions/${sessionId}/ask/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => ({}));
    const detail = payload?.detail;
    throw new ApiError(response.status, detail?.reasons ?? (typeof detail === "string" ? [detail] : [`HTTP ${response.status}`]));
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let answer: Answer | undefined;
  for (;;) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line) as StreamEvent;
      onEvent(event);
      if (event.type === "answer") answer = event.answer;
      if (event.type === "error") throw new ApiError(500, [event.message]);
    }
    if (done) break;
  }
  if (!answer) throw new ApiError(500, ["the answer stream ended without an answer"]);
  return answer;
}

export const api = {
  askStream,
  health: () => call<Health>("GET", "/health"),
  catalog: () => call<CatalogView>("GET", "/catalog"),
  overview: () => call<OverviewView>("GET", "/overview"),
  forecast: () => call<ForecastView>("GET", "/forecast"),
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
