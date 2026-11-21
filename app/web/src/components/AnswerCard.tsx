import {
  AlertTriangle,
  ArrowRight,
  Ban,
  BadgeCheck,
  CircleHelp,
  Clock3,
  Code2,
  Database,
  FileSearch,
  Layers,
  ShieldAlert,
  Table2,
  Wand2,
} from "lucide-react";
import { LayoutGroup, motion } from "framer-motion";
import { type ReactNode, useState } from "react";
import type { Answer } from "../api/client";
import { filterText, formatValue, seconds } from "../lib/format";
import DataTable from "./DataTable";
import { ease } from "./motion";
import ResultChart from "./ResultChart";

const STATUS: Record<string, { text: string; tone: string; icon: ReactNode }> = {
  answered: { text: "Answered", tone: "bg-mint-50 text-mint-700 ring-mint-100", icon: <BadgeCheck size={15} /> },
  clarify: { text: "Needs a precision", tone: "bg-sky-50 text-sky-500 ring-sky-100", icon: <CircleHelp size={15} /> },
  rejected: { text: "Stopped by a safeguard", tone: "bg-coral-50 text-coral-600 ring-coral-100", icon: <ShieldAlert size={15} /> },
  unsupported: { text: "Outside the data", tone: "bg-taxi-400/15 text-taxi-600 ring-taxi-400/30", icon: <Ban size={15} /> },
  empty: { text: "No matching trips", tone: "bg-slate-100 text-slate-600 ring-slate-200", icon: <FileSearch size={15} /> },
  model_unavailable: { text: "Model offline", tone: "bg-coral-50 text-coral-600 ring-coral-100", icon: <AlertTriangle size={15} /> },
  query_failed: { text: "Query failed", tone: "bg-coral-50 text-coral-600 ring-coral-100", icon: <AlertTriangle size={15} /> },
};
type Tab = "plan" | "provenance" | "sql" | "timing";

type Props = {
  answer: Answer;
  units: Record<string, string>;
  labels: Record<string, string>;
  onFollowUp: (question: string) => void;
};

export default function AnswerCard({ answer, units, labels, onFollowUp }: Props) {
  const [tab, setTab] = useState<Tab | null>(null);
  const [table, setTable] = useState(false);
  const status = STATUS[answer.status] ?? STATUS.empty;
  const plan = answer.plan;
  const metrics = plan?.metrics ?? [];
  const prov = answer.provenance;
  const adjustments = answer.reasons.filter((r) => r.startsWith("plan "));
  const notes = answer.reasons.filter((r) => !r.startsWith("plan "));
  const lowQuality = prov?.valid_trip_rate != null && prov.valid_trip_rate < 0.85;

  return (
    <motion.article initial={{ opacity: 0, y: 18, scale: 0.99 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ duration: 0.5, ease }} className="panel overflow-hidden">
      <header className="flex flex-wrap items-center gap-2 px-6 pt-5">
        <span className="grid h-9 w-9 place-items-center rounded-xl bg-taxi-gradient text-sm font-black text-night-900">
          M
        </span>
        <span className={`chip ring-1 ${status.tone}`}>
          {status.icon} {status.text}
        </span>
        {answer.narrative_check === "passed" && (
          <span className="chip bg-mint-50 text-mint-700 ring-1 ring-mint-100">
            <BadgeCheck size={14} /> Numbers verified
          </span>
        )}
        {answer.narrative_check === "replaced" && (
          <span
            className="chip bg-taxi-400/15 text-taxi-600 ring-1 ring-taxi-400/30"
            title="The model's text quoted a number or a ranking that is not in the result. A factual summary of the result is shown instead."
          >
            <ShieldAlert size={14} /> Text replaced by the factual summary
          </span>
        )}
        {adjustments.length > 0 && (
          <span className="chip bg-sky-50 text-sky-500 ring-1 ring-sky-100">
            <Wand2 size={14} /> Plan corrected ({adjustments.length})
          </span>
        )}
        <span className="ml-auto flex items-center gap-1 text-xs text-slate-400">
          <Clock3 size={13} /> {seconds(answer.duration_ms)}
        </span>
      </header>

      <div className="space-y-5 px-6 py-5">
        <p className="whitespace-pre-line text-[1.08rem] leading-relaxed text-night-900">{answer.narrative}</p>

        {lowQuality && (
          <div className="flex gap-2 rounded-xl bg-coral-50 px-4 py-3 text-sm text-coral-600">
            <AlertTriangle size={18} className="shrink-0" />
            Only {formatValue(prov?.valid_trip_rate, "ratio")} of the trips of this period are valid (agreed
            threshold 85 %). Check before deciding.
          </div>
        )}

        {answer.rows.length > 0 && (
          <div className="rounded-2xl border border-slate-100 bg-gradient-to-b from-white to-mist/60 p-4">
            <ResultChart columns={answer.columns} rows={answer.rows} metrics={metrics} units={units} labels={labels} />
            <button
              className="mt-3 inline-flex items-center gap-1.5 text-xs font-semibold text-night-600 hover:text-night-800"
              onClick={() => setTable(!table)}
            >
              <Table2 size={14} /> {table ? "Hide" : "Show"} the data ({answer.rows.length} rows)
            </button>
            {table && (
              <div className="mt-3">
                <DataTable columns={answer.columns} rows={answer.rows} units={units} />
              </div>
            )}
          </div>
        )}

        {notes.length > 0 && answer.status !== "answered" && (
          <ul className="space-y-1.5">
            {notes.map((r) => (
              <li key={r} className="flex gap-2 rounded-xl bg-mist px-3 py-2 text-sm text-slate-600">
                <ShieldAlert size={16} className="mt-0.5 shrink-0 text-coral-500" /> {r}
              </li>
            ))}
          </ul>
        )}

        {answer.limitations.length > 0 && (
          <p className="text-xs leading-relaxed text-slate-500">
            <span className="font-semibold text-slate-600">Limits · </span>
            {answer.limitations.join(" ")}
          </p>
        )}

        {answer.suggested_followup && (
          <button
            className="group inline-flex items-center gap-2 rounded-xl bg-night-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-night-700"
            onClick={() => onFollowUp(answer.suggested_followup!)}
          >
            {answer.suggested_followup}
            <ArrowRight size={16} className="text-taxi-400 transition group-hover:translate-x-0.5" />
          </button>
        )}
      </div>

      {(plan || prov) && (
        <footer className="border-t border-slate-100 bg-mist/70">
          <LayoutGroup id={answer.trace_id ?? answer.question}>
          <div className="flex flex-wrap items-center gap-1 px-4 py-2">
            <span className="eyebrow mr-2 pl-2">Behind the answer</span>
            {plan && <TabButton active={tab === "plan"} onClick={() => setTab(tab === "plan" ? null : "plan")} icon={<Layers size={14} />} text="Plan" />}
            {prov && <TabButton active={tab === "provenance"} onClick={() => setTab(tab === "provenance" ? null : "provenance")} icon={<Database size={14} />} text="Provenance" />}
            {prov && <TabButton active={tab === "sql"} onClick={() => setTab(tab === "sql" ? null : "sql")} icon={<Code2 size={14} />} text="SQL" />}
            <TabButton active={tab === "timing"} onClick={() => setTab(tab === "timing" ? null : "timing")} icon={<Clock3 size={14} />} text="Timing" />
          </div>
          </LayoutGroup>

          {tab === "plan" && plan && (
            <div className="space-y-3 px-6 pb-5">
              <p className="text-xs text-slate-500">Written by the model, validated and grounded by code.</p>
              <div className="flex flex-wrap gap-1.5">
                <Pill>intent · {plan.intent}</Pill>
                {metrics.map((m) => <Pill key={m}>measure · {labels[m] ?? m}</Pill>)}
                {plan.dimensions.map((d) => <Pill key={d}>by · {d.replace(/_/g, " ")}</Pill>)}
                {plan.filters.map((f) => <Pill key={filterText(f)}>filter · {filterText(f)}</Pill>)}
                <Pill>period · {plan.date_range.period.replace(/_/g, " ")}</Pill>
              </div>
              {adjustments.map((r) => (
                <div key={r} className="flex gap-2 rounded-xl bg-white px-3 py-2 text-xs text-slate-600 ring-1 ring-slate-200">
                  <Wand2 size={14} className="mt-0.5 shrink-0 text-sky-500" /> {r}
                </div>
              ))}
            </div>
          )}

          {tab === "provenance" && prov && (
            <div className="grid gap-4 px-6 pb-5 md:grid-cols-2">
              <dl className="grid grid-cols-[auto,1fr] content-start gap-x-4 gap-y-2 text-sm">
                <dt className="text-slate-500">Months</dt>
                <dd className="font-medium">
                  {prov.period_resolved.period}
                  {prov.period_resolved.compared_with && ` vs ${prov.period_resolved.compared_with}`}
                </dd>
                <dt className="text-slate-500">Publication</dt>
                <dd className="font-medium">{prov.published_run}</dd>
                <dt className="text-slate-500">Published at</dt>
                <dd>{prov.published_at.slice(0, 16)} UTC</dd>
                <dt className="text-slate-500">Valid trips</dt>
                <dd>{formatValue(prov.valid_trip_rate, "ratio")}</dd>
                <dt className="text-slate-500">Rows</dt>
                <dd>{prov.row_count}</dd>
                <dt className="text-slate-500">Source</dt>
                <dd className="text-xs text-slate-600">{prov.data_layer}</dd>
              </dl>
              <div className="space-y-2">
                {prov.metrics.map((m) => (
                  <div key={m.name} className="rounded-xl bg-white p-3 ring-1 ring-slate-200">
                    <div className="flex items-center gap-2 text-sm font-semibold">
                      {m.label}
                      {m.is_estimate && <span className="chip bg-taxi-400/15 text-taxi-600">estimate</span>}
                    </div>
                    <p className="mt-1 text-xs leading-relaxed text-slate-600">{m.definition}</p>
                    <code className="mt-2 block break-all rounded-lg bg-mist px-2 py-1.5 text-[11px] text-night-700">
                      {m.sql_expression}
                    </code>
                  </div>
                ))}
              </div>
            </div>
          )}

          {tab === "sql" && prov && (
            <div className="px-6 pb-5">
              <p className="mb-2 text-xs text-slate-500">
                Built from an approved template, checked by SQLGlot, run with a read-only role (10 s limit).
              </p>
              <pre className="overflow-auto rounded-xl bg-night-950 p-4 text-[12px] leading-relaxed text-slate-200">
                {prov.rendered_sql}
              </pre>
            </div>
          )}

          {tab === "timing" && (
            <div className="space-y-3 px-6 pb-5">
              <StepBars steps={answer.step_ms} total={answer.duration_ms} />
              {answer.trace_id && (
                <p className="text-xs text-slate-500">
                  Trace <code className="rounded bg-white px-1.5 py-0.5 ring-1 ring-slate-200">{answer.trace_id}</code> in
                  Grafana (Explore, Tempo).
                </p>
              )}
            </div>
          )}
        </footer>
      )}
    </motion.article>
  );
}

function TabButton({ active, onClick, icon, text }: { active: boolean; onClick: () => void; icon: ReactNode; text: string }) {
  return (
    <button
      onClick={onClick}
      className={`relative inline-flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-sm font-semibold transition-colors ${
        active ? "text-white" : "text-slate-600 hover:text-night-800"
      }`}
    >
      {active && (
        <motion.span
          layoutId="answer-tab"
          className="absolute inset-0 rounded-xl bg-night-900"
          transition={{ type: "spring", stiffness: 420, damping: 34 }}
        />
      )}
      <span className="relative inline-flex items-center gap-1.5">
        {icon} {text}
      </span>
    </button>
  );
}

function Pill({ children }: { children: ReactNode }) {
  return <span className="chip bg-white text-night-700 ring-1 ring-slate-200">{children}</span>;
}

function StepBars({ steps, total }: { steps: Record<string, number>; total: number }) {
  const max = Math.max(total, 1);
  return (
    <div className="space-y-1.5">
      {Object.entries(steps).map(([step, ms]) => (
        <div key={step} className="grid grid-cols-[110px,1fr,70px] items-center gap-3 text-xs">
          <span className="text-slate-600">{step.replace(/_/g, " ")}</span>
          <span className="h-2 overflow-hidden rounded-full bg-slate-200">
            <span
              className={`block h-2 rounded-full ${["plan", "narrate", "repair"].includes(step) ? "bg-taxi-gradient" : "bg-night-500"}`}
              style={{ width: `${Math.max(2, (100 * ms) / max)}%` }}
            />
          </span>
          <span className="text-right tabular-nums text-slate-500">{seconds(ms)}</span>
        </div>
      ))}
      <p className="pt-1 text-[11px] text-slate-400">Yellow: model steps. Blue: code and database.</p>
    </div>
  );
}
