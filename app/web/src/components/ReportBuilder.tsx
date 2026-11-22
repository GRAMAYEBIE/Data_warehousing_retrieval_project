import { useMutation } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowUpRight, Check, CircleAlert, FileBarChart2, Loader2, Send } from "lucide-react";
import { useState } from "react";
import { ApiError, api, type CatalogView, type ReportView } from "../api/client";
import { useConfig } from "../lib/config";
import DataTable from "./DataTable";
import { ease, spring } from "./motion";
import ResultChart from "./ResultChart";
import ThinkingCard from "./ThinkingCard";

const EXAMPLE =
  "Create a weekly demand report for Manhattan and add a chart comparing airport trips this month with last month.";

// Request -> draft (specification, previews, data summary) -> explicit confirmation.
// Nothing is published until the manager ticks the review box and confirms.
export default function ReportBuilder({ catalog }: { catalog?: CatalogView }) {
  const config = useConfig();
  const [request, setRequest] = useState(EXAMPLE);
  const [reviewed, setReviewed] = useState(false);
  const [report, setReport] = useState<ReportView>();

  const draft = useMutation({
    mutationFn: () => api.createReport(request),
    onSuccess: (r) => {
      setReport(r);
      setReviewed(false);
    },
  });
  const publish = useMutation({ mutationFn: () => api.confirmReport(report!.report_id), onSuccess: setReport });

  const units = Object.fromEntries(Object.entries(catalog?.metrics ?? {}).map(([k, m]) => [k, m.unit]));
  const labels = Object.fromEntries(Object.entries(catalog?.metrics ?? {}).map(([k, m]) => [k, m.label]));
  const spec = report?.specification as
    | { explanation?: string; metrics?: string[]; extra_charts?: { metrics?: string[] }[] }
    | undefined;
  const metricsOf = (i: number) => (i === 0 ? spec?.metrics : spec?.extra_charts?.[i - 1]?.metrics) ?? [];
  const error = draft.error ?? publish.error;
  const step = report?.status === "published" ? 3 : report ? 2 : 1;

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6 px-4 py-8 sm:px-6">
      <div>
        <h2 className="text-[26px] font-semibold tracking-tight">Build a dashboard from a sentence</h2>
        <p className="mt-1.5 max-w-2xl text-sm leading-6 text-ink-2">
          Each chart is planned with governed measures only and previewed on the published data. A draft dashboard is
          created in Superset; it goes live only after your explicit confirmation.
        </p>
        <Stepper step={step} />
      </div>

      <div className="card p-4">
        <label className="text-xs font-medium text-ink-2" htmlFor="request">
          Request
        </label>
        <textarea
          id="request"
          className="mt-2 h-28 w-full resize-none rounded-input border border-line bg-page/60 p-3 text-base leading-6 outline-none transition focus:border-line-strong focus:bg-surface focus:shadow-focus"
          value={request}
          maxLength={600}
          onChange={(e) => setRequest(e.target.value)}
        />
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            className="btn-primary"
            disabled={draft.isPending || request.trim().length < 10}
            onClick={() => draft.mutate()}
          >
            {draft.isPending ? <Loader2 size={15} className="animate-spin" /> : <FileBarChart2 size={15} />}
            {draft.isPending ? "Building the draft…" : "Create the draft"}
          </button>
          <span className="text-xs text-ink-3">One chart per part of the request · governed measures only</span>
        </div>
      </div>

      {draft.isPending && (
        <div className="card p-5">
          <ThinkingCard />
        </div>
      )}

      {error && (
        <div className="flex gap-3 rounded-input border border-bad/30 bg-bad/5 p-4 text-sm">
          <CircleAlert size={18} className="mt-0.5 shrink-0 text-bad-ink" />
          <div>
            <div className="font-semibold text-ink">
              {error instanceof ApiError && error.status === 422 ? "Request refused" : "The request could not be completed"}
            </div>
            <ul className="mt-1 list-inside list-disc text-ink-2">
              {(error instanceof ApiError ? error.reasons : [String(error)]).map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <AnimatePresence>
        {report && (
          <motion.div
            key={report.report_id}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.35, ease }}
            className="card overflow-hidden"
          >
            <header className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3.5">
              <div className="min-w-0 flex-1">
                <h3 className="truncate text-base font-semibold">{report.dashboard_title}</h3>
                {spec?.explanation && <p className="mt-0.5 text-xs text-ink-2">{spec.explanation}</p>}
              </div>
              <span className={`chip ${report.status === "published" ? "border-good/30 bg-good/10 text-good-ink" : "border-accent/40 bg-accent/15 text-ink"}`}>
                {report.status === "published" ? <Check size={13} /> : null}
                {report.status === "published" ? "Published" : "Draft · not published"}
              </span>
              <a className="btn-outline h-8 px-3 text-xs" href={`${config.supersetUrl}${report.dashboard_url}`} target="_blank" rel="noreferrer">
                Open in Superset <ArrowUpRight size={13} />
              </a>
            </header>

            <div className="grid gap-4 p-5 lg:grid-cols-2">
              {report.preview.map((p, i) => (
                <section key={p.title} className="rounded-input border border-line p-4">
                  <div className="mb-3 flex items-baseline justify-between gap-2">
                    <h4 className="text-sm font-medium">{p.title}</h4>
                    <span className="text-xs text-ink-3">
                      {p.chart} · {p.row_count} rows
                    </span>
                  </div>
                  <ResultChart columns={p.columns} rows={p.rows} metrics={metricsOf(i)} units={units} labels={labels} />
                  {p.rows.length === 1 && <DataTable columns={p.columns} rows={p.rows} units={units} />}
                  <details className="mt-3">
                    <summary className="cursor-pointer text-xs font-medium text-ink-2 hover:text-ink">Data and query</summary>
                    <div className="mt-2 space-y-2">
                      <DataTable columns={p.columns} rows={p.rows} units={units} max={20} />
                      <pre className="overflow-auto rounded-lg bg-tint p-3 font-mono text-xs text-ink-2">{p.sql}</pre>
                    </div>
                  </details>
                </section>
              ))}
            </div>

            <details className="mx-5 mb-5 rounded-input bg-tint px-4 py-3">
              <summary className="cursor-pointer text-xs font-medium text-ink-2">
                Specification (validated plan of every chart)
              </summary>
              <pre className="mt-2 overflow-auto font-mono text-xs text-ink-2">{JSON.stringify(report.specification, null, 2)}</pre>
            </details>

            <div className="border-t border-line bg-page/50 px-5 py-4">
              {report.status === "draft" ? (
                <div className="flex flex-wrap items-center gap-4">
                  <label className="flex flex-1 cursor-pointer items-start gap-2.5 text-sm text-ink-2">
                    <input
                      type="checkbox"
                      className="mt-0.5 h-4 w-4 accent-[rgb(var(--ink))]"
                      checked={reviewed}
                      onChange={(e) => setReviewed(e.target.checked)}
                    />
                    I reviewed the specification, the previews and the data of this draft.
                  </label>
                  <button className="btn-accent" disabled={!reviewed || publish.isPending} onClick={() => publish.mutate()}>
                    {publish.isPending ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
                    {publish.isPending ? "Publishing…" : "Publish the dashboard"}
                  </button>
                </div>
              ) : (
                <div className="flex items-center gap-2 text-sm text-good-ink">
                  <Check size={16} /> Published after your confirmation. It is now visible in Superset.
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Stepper({ step }: { step: number }) {
  const steps = ["Request", "Review the draft", "Publish"];
  return (
    <ol className="mt-5 flex flex-wrap items-center gap-2 text-sm">
      {steps.map((text, i) => {
        const n = i + 1;
        const state = n < step ? "done" : n === step ? "current" : "next";
        return (
          <li key={text} className="flex items-center gap-2">
            <span className="relative grid h-6 w-6 place-items-center rounded-full text-xs font-semibold">
              {state === "current" && (
                <motion.span layoutId="step-current" className="absolute inset-0 rounded-full bg-ink" transition={spring} />
              )}
              <span
                className={`relative grid h-6 w-6 place-items-center rounded-full ${
                  state === "done" ? "bg-good text-white" : state === "current" ? "text-surface" : "border border-line text-ink-3"
                }`}
              >
                {state === "done" ? <Check size={13} strokeWidth={3} /> : n}
              </span>
            </span>
            <span className={state === "next" ? "text-ink-3" : "font-medium text-ink"}>{text}</span>
            {n < steps.length && <span className="mx-1 h-px w-8 bg-line" />}
          </li>
        );
      })}
    </ol>
  );
}
