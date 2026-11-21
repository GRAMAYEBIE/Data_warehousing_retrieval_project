import { useMutation } from "@tanstack/react-query";
import {
  CheckCircle2,
  ClipboardCheck,
  ExternalLink,
  FileBarChart2,
  Loader2,
  Rocket,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import { motion } from "framer-motion";
import { useState } from "react";
import { ApiError, api, type CatalogView, type ReportView } from "../api/client";
import DataTable from "./DataTable";
import { ease } from "./motion";
import ResultChart from "./ResultChart";
import TaxiScene from "./TaxiScene";
import ThinkingCard from "./ThinkingCard";

const SUPERSET = import.meta.env.VITE_SUPERSET_URL ?? "http://localhost:8088";
const EXAMPLE =
  "Create a weekly demand report for Manhattan and add a chart comparing airport trips this month with last month.";

// Request -> draft (specification, previews, data summary) -> explicit confirmation.
// Nothing is published until the manager ticks the review box and confirms.
export default function ReportBuilder({ catalog }: { catalog?: CatalogView }) {
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
    <div className="space-y-6">
      <motion.div
        className="relative overflow-hidden rounded-[2rem] bg-night-900 text-white shadow-lift"
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease }}
      >
        <div className="absolute inset-0 bg-hero-glow" />
        <div className="absolute inset-x-0 bottom-0 z-10 h-2 bg-checker" />
        <div className="relative grid items-center gap-6 px-8 pb-10 pt-9 lg:grid-cols-[1.2fr,0.8fr] lg:px-10">
        <div>
          <span className="chip bg-white/10 text-sm text-taxi-300">
            <FileBarChart2 size={15} /> Report builder
          </span>
          <h1 className="mt-4 text-4xl font-extrabold tracking-tight">Describe the report you need.</h1>
          <p className="mt-3 max-w-2xl text-lg leading-relaxed text-slate-300">
            The assistant plans each chart with governed measures only, previews the data, and creates a draft
            dashboard in Superset. You review it; it goes live only after your explicit confirmation.
          </p>
          <Stepper step={step} />
        </div>
        <TaxiScene className="hidden w-full drop-shadow-2xl lg:block" />
        </div>
      </motion.div>

      <div className="panel p-6">
        <label className="eyebrow" htmlFor="request">1 · Your request</label>
        <textarea
          id="request"
          className="mt-2 h-32 w-full resize-none rounded-2xl border border-slate-200 bg-mist/60 p-4 text-[1.05rem] outline-none transition focus:border-taxi-400 focus:bg-white focus:ring-4 focus:ring-taxi-400/15"
          value={request}
          maxLength={600}
          onChange={(e) => setRequest(e.target.value)}
        />
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button className="btn-taxi" disabled={draft.isPending || request.trim().length < 10} onClick={() => draft.mutate()}>
            {draft.isPending ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
            {draft.isPending ? "Building the draft…" : "Create the draft"}
          </button>
          <span className="text-xs text-slate-500">Uses only the governed measures; one chart per request part.</span>
        </div>
      </div>

      {draft.isPending && <ThinkingCard />}

      {error && (
        <div className="panel flex gap-3 border-coral-100 bg-coral-50 p-5 text-sm text-coral-600">
          <ShieldAlert size={20} className="shrink-0" />
          <div>
            <div className="font-semibold">
              {error instanceof ApiError && error.status === 422 ? "Request refused" : "The request could not be completed"}
            </div>
            <ul className="mt-1 list-inside list-disc">
              {(error instanceof ApiError ? error.reasons : [String(error)]).map((r) => <li key={r}>{r}</li>)}
            </ul>
          </div>
        </div>
      )}

      {report && (
        <div className="panel animate-fade-up overflow-hidden">
          <header className="flex flex-wrap items-center gap-3 border-b border-slate-100 px-6 py-4">
            <span className="eyebrow">2 · Review the draft</span>
            <span
              className={`chip ring-1 ${
                report.status === "published"
                  ? "bg-mint-50 text-mint-700 ring-mint-100"
                  : "bg-taxi-400/15 text-taxi-600 ring-taxi-400/30"
              }`}
            >
              {report.status === "published" ? <CheckCircle2 size={14} /> : <ClipboardCheck size={14} />}
              {report.status === "published" ? "Published" : "Draft · not published"}
            </span>
            <a className="btn-soft ml-auto py-2" href={`${SUPERSET}${report.dashboard_url}`} target="_blank" rel="noreferrer">
              Open in Superset <ExternalLink size={14} />
            </a>
          </header>

          <div className="space-y-6 px-6 py-5">
            <div>
              <h2 className="text-2xl font-bold tracking-tight">{report.dashboard_title}</h2>
              {spec?.explanation && <p className="mt-1 text-sm text-slate-600">{spec.explanation}</p>}
            </div>

            <div className="grid gap-5 lg:grid-cols-2">
              {report.preview.map((p, i) => (
                <section key={p.title} className="rounded-2xl border border-slate-100 bg-gradient-to-b from-white to-mist/60 p-4">
                  <div className="mb-2 flex items-baseline justify-between gap-2">
                    <h3 className="text-sm font-semibold">{p.title}</h3>
                    <span className="chip bg-white text-slate-500 ring-1 ring-slate-200">
                      {p.chart} · {p.row_count} rows
                    </span>
                  </div>
                  <ResultChart columns={p.columns} rows={p.rows} metrics={metricsOf(i)} units={units} labels={labels} />
                  <details className="mt-2">
                    <summary className="cursor-pointer text-xs font-semibold text-night-600">Data summary and query</summary>
                    <div className="mt-2 space-y-2">
                      <DataTable columns={p.columns} rows={p.rows} units={units} max={20} />
                      <pre className="overflow-auto rounded-xl bg-night-950 p-3 text-[11px] text-slate-200">{p.sql}</pre>
                    </div>
                  </details>
                </section>
              ))}
            </div>

            <details className="rounded-xl bg-mist px-4 py-3">
              <summary className="cursor-pointer text-xs font-semibold text-night-600">
                Generated specification (validated plan of every chart)
              </summary>
              <pre className="mt-2 overflow-auto text-[11px] text-night-700">{JSON.stringify(report.specification, null, 2)}</pre>
            </details>

            {report.status === "draft" ? (
              <div className="rounded-2xl border border-taxi-400/40 bg-taxi-400/10 p-5">
                <div className="eyebrow text-taxi-600">3 · Publish</div>
                <label className="mt-2 flex cursor-pointer items-start gap-3 text-sm text-night-800">
                  <input
                    type="checkbox"
                    className="mt-0.5 h-4 w-4 accent-night-800"
                    checked={reviewed}
                    onChange={(e) => setReviewed(e.target.checked)}
                  />
                  I reviewed the specification, the previews and the data summary of this draft.
                </label>
                <button className="btn-night mt-4" disabled={!reviewed || publish.isPending} onClick={() => publish.mutate()}>
                  {publish.isPending ? <Loader2 size={16} className="animate-spin" /> : <Rocket size={16} />}
                  {publish.isPending ? "Publishing…" : "Publish the dashboard"}
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-3 rounded-2xl bg-mint-50 p-5 text-sm text-mint-700">
                <CheckCircle2 size={20} /> Published after your confirmation. It is now visible in Superset.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Stepper({ step }: { step: number }) {
  const steps = ["Request", "Review the draft", "Publish"];
  return (
    <ol className="mt-6 flex flex-wrap items-center gap-2 text-sm">
      {steps.map((text, i) => {
        const n = i + 1;
        const state = n < step ? "done" : n === step ? "current" : "next";
        return (
          <li key={text} className="flex items-center gap-2">
            <span
              className={`grid h-7 w-7 place-items-center rounded-full text-xs font-bold ${
                state === "done"
                  ? "bg-mint-500 text-white"
                  : state === "current"
                    ? "bg-taxi-gradient text-night-900 shadow-glow"
                    : "bg-white/10 text-slate-400"
              }`}
            >
              {state === "done" ? <CheckCircle2 size={15} /> : n}
            </span>
            <span className={state === "next" ? "text-slate-400" : "font-semibold text-white"}>{text}</span>
            {n < steps.length && <span className="mx-1 h-px w-8 bg-white/20" />}
          </li>
        );
      })}
    </ol>
  );
}
