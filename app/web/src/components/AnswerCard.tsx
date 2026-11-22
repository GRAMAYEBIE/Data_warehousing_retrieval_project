import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowRight, Check, ChevronDown, CircleHelp, Copy, Info, MessageCircle, ShieldAlert } from "lucide-react";
import { type ReactNode, useState } from "react";
import type { Answer } from "../api/client";
import { filterText, formatValue, seconds } from "../lib/format";
import DataTable from "./DataTable";
import Markdown from "./Markdown";
import { CountUp, ease } from "./motion";
import ResultChart from "./ResultChart";

// Answers arrive in sequence: status, headline figure, chart, text, actions.
const SEQUENCE = { hidden: {}, show: { transition: { staggerChildren: 0.12, delayChildren: 0.05 } } };
const STEP = { hidden: { opacity: 0, y: 10 }, show: { opacity: 1, y: 0, transition: { duration: 0.38, ease } } };

type Props = {
  answer: Answer;
  units: Record<string, string>;
  labels: Record<string, string>;
  onFollowUp: (question: string) => void;
  streamed?: boolean; // the text was already shown as it was written
};

// Valid questions offered when a request cannot be answered as asked.
const ALTERNATIVES: Record<string, string[]> = {
  unsupported: ["Average fare by pickup borough last month", "Tip rate of card trips last month"],
  rejected: ["Total revenue last month", "Top 5 pickup zones by trips last month"],
  clarify: ["Trips last month by pickup borough", "Total revenue last month"],
  empty: ["Trips last month by pickup borough", "Trips last month"],
  query_failed: ["Trips last month", "Total revenue last month"],
  model_unavailable: ["Open the dashboards for the same figures"],
};
const REFUSAL_TITLE: Record<string, string> = {
  unsupported: "Not in the data",
  rejected: "Stopped by a safeguard",
  clarify: "Needs one more detail",
  empty: "No matching trips",
  query_failed: "The query failed",
  model_unavailable: "The assistant is offline",
};

function monthsText(period?: string | null): string {
  const months = (period ?? "").split(/\s*,\s*/).filter(Boolean);
  const name = (p: string) => {
    const m = /^(\d{4})-(\d{2})/.exec(p);
    return m
      ? new Date(Date.UTC(+m[1], +m[2] - 1, 1)).toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" })
      : p;
  };
  if (!months.length) return "";
  return months.length === 1 ? name(months[0]) : `${name(months[0])} – ${name(months[months.length - 1])}`;
}

export default function AnswerCard({ answer, units, labels, onFollowUp, streamed = false }: Props) {
  const reduce = useReducedMotion();
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<"data" | "sql" | "timing" | null>(null);
  const [copied, setCopied] = useState(false);
  const answered = answer.status === "answered";
  const verified = answered && answer.narrative_check !== "replaced";
  const plan = answer.plan;
  const metrics = plan?.metrics ?? [];
  const prov = answer.provenance;
  const label = (m: string) => labels[m] ?? m.replace(/_/g, " ");
  const adjustments = answer.reasons.filter((r) => r.startsWith("plan "));
  const notes = answer.reasons.filter(
    (r) => !r.startsWith("plan ") && !r.startsWith("narrative ") && !answer.narrative.toLowerCase().includes(r.toLowerCase()),
  );

  const dims = answer.columns.filter((c) => !metrics.some((m) => c === m || c.startsWith(`${m}_`)) && c !== "period_role");
  const headline =
    answered && answer.rows.length === 1 && dims.length === 0
      ? metrics.filter((m) => answer.columns.includes(m) || answer.columns.includes(`${m}_current`))
      : [];
  const row = Object.fromEntries(answer.columns.map((c, i) => [c, answer.rows[0]?.[i]]));
  const period = monthsText(prov?.period_resolved?.period);
  const compared = monthsText(prov?.period_resolved?.compared_with);
  const lowQuality = prov?.valid_trip_rate != null && prov.valid_trip_rate < 0.85;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(answer.narrative);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  if (answer.status === "general") {
    // Questions the answer suggests ("What was total revenue last month?") become buttons.
    const suggested = Array.from(new Set(Array.from(answer.narrative.matchAll(/["“]([^"”\n]{8,140}\?)["”]/g), (m) => m[1]))).slice(0, 3);
    return (
      <motion.article
        initial={reduce || streamed ? false : { opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease }}
        className="space-y-3"
        aria-live="polite"
      >
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="chip border-primary/25 bg-primary/10 text-primary-strong" title="Written by the model from general knowledge and the platform documentation">
            <MessageCircle size={12} aria-hidden="true" /> General answer · not computed from the data
          </span>
          <span className="num ml-auto text-ink-3">{seconds(answer.duration_ms)}</span>
        </div>
        <Markdown text={answer.narrative} className="text-base leading-7 text-ink" />
        {answer.narrative_check === "replaced" && (
          <p className="flex gap-2 text-xs text-ink-3">
            <Info size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
            Sentences stating figures about the taxi data were removed: such figures come only from governed queries.
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          {(suggested.length ? suggested : answer.suggested_followup ? [answer.suggested_followup] : []).map((q) => (
            <button key={q} className="btn-outline min-h-8 justify-start px-3 py-1.5 text-left text-sm" onClick={() => onFollowUp(q)}>
              {q}
              <ArrowRight size={13} className="text-ink-3" aria-hidden="true" />
            </button>
          ))}
          <button className="btn-ghost h-8 px-2.5 text-sm" onClick={copy} aria-label="Copy the answer">
            {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />} {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </motion.article>
    );
  }

  if (!answered) {
    const refusal = answer.status !== "clarify";
    return (
      <motion.article
        initial={reduce ? false : { opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease }}
        className={`card border-l-4 p-5 ${refusal ? "border-l-bad" : "border-l-primary"}`}
        aria-live="polite"
      >
        <div className={`flex items-center gap-2 text-sm font-semibold ${refusal ? "text-bad-ink" : "text-primary-strong"}`}>
          {refusal ? <ShieldAlert size={16} aria-hidden="true" /> : <CircleHelp size={16} aria-hidden="true" />}
          {REFUSAL_TITLE[answer.status] ?? "Not answered"}
        </div>
        <p className="mt-2 text-base leading-7 text-ink">{answer.narrative}</p>
        {notes.length > 0 && (
          <ul className="mt-2 space-y-1 text-sm text-ink-2">
            {notes.map((r) => (
              <li key={r}>· {r}</li>
            ))}
          </ul>
        )}
        <div className="mt-4">
          <div className="text-xs font-medium text-ink-3">You can ask instead</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {(ALTERNATIVES[answer.status] ?? ALTERNATIVES.rejected).map((q) => (
              <button key={q} className="btn-outline h-8 px-3 text-sm" onClick={() => onFollowUp(q)}>
                {q} <ArrowRight size={13} className="text-ink-3" aria-hidden="true" />
              </button>
            ))}
          </div>
        </div>
      </motion.article>
    );
  }

  return (
    <motion.article
      initial={reduce ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease }}
      className="card overflow-hidden"
      aria-live="polite"
    >
      <motion.div className="space-y-4 p-5" variants={reduce ? undefined : SEQUENCE} initial="hidden" animate="show">
        <motion.div variants={STEP} className="flex flex-wrap items-center gap-2 text-xs">
          {verified ? (
            <span className="chip border-good/30 bg-good/10 text-good-ink">
              <Check size={12} strokeWidth={3} aria-hidden="true" /> Numbers verified
            </span>
          ) : (
            <span className="chip border-line bg-tint text-ink-2" title="Written by code from the result, not by the model">
              <Info size={12} aria-hidden="true" /> Factual summary
            </span>
          )}
          {period && (
            <span className="chip border-line bg-surface text-ink-2">
              {period}
              {compared && ` vs ${compared}`}
            </span>
          )}
          {answer.active_filters.map((f) => (
            <span key={filterText(f)} className="chip border-line bg-surface text-ink-2">
              {filterText(f)}
            </span>
          ))}
          <span className="num ml-auto text-ink-3">{seconds(answer.duration_ms)}</span>
        </motion.div>

        {headline.length > 0 && (
          <motion.div variants={STEP} className={`grid gap-3 ${headline.length > 1 ? "sm:grid-cols-2" : ""}`}>
            {headline.map((m) => (
              <Headline key={m} label={label(m)} unit={units[m] ?? ""} metric={m} row={row} compared={compared} />
            ))}
          </motion.div>
        )}

        {answer.rows.length > 1 && (
          <motion.div variants={STEP} className="rounded-input border border-line p-3">
            <ResultChart columns={answer.columns} rows={answer.rows} metrics={metrics} units={units} labels={labels} />
            {plan?.grain === "week" && answer.columns.includes("period") && (
              <p className="mt-2 text-xs text-ink-3">
                Weeks start on Monday; the first and last weeks count only the days inside the period.
              </p>
            )}
          </motion.div>
        )}

        <motion.div variants={STEP}>
          <Markdown text={answer.narrative} className="text-base leading-7 text-ink" />
        </motion.div>

        {lowQuality && (
          <div className="flex gap-2 rounded-input border border-bad/30 border-l-4 border-l-bad bg-surface px-3 py-2 text-sm text-ink">
            <ShieldAlert size={16} className="mt-1 shrink-0 text-bad-ink" aria-hidden="true" />
            Only {formatValue(prov?.valid_trip_rate, "ratio")} of the trips of this period are valid (agreed threshold
            85 %). Check before deciding.
          </div>
        )}

        {answer.limitations.length > 0 && (
          <p className="text-xs leading-5 text-ink-3">
            <span className="font-medium text-ink-2">Limits. </span>
            {answer.limitations.join(" ")}
          </p>
        )}

        <motion.div variants={STEP} className="flex flex-wrap items-center gap-2">
          {answer.suggested_followup && (
            <button className="btn-outline min-h-8 justify-start px-3 py-1.5 text-left text-sm" onClick={() => onFollowUp(answer.suggested_followup!)}>
              {answer.suggested_followup}
              <ArrowRight size={13} className="text-ink-3" aria-hidden="true" />
            </button>
          )}
          <button className="btn-ghost h-8 px-2.5 text-sm" onClick={copy} aria-label="Copy the answer">
            {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />} {copied ? "Copied" : "Copy"}
          </button>
        </motion.div>
      </motion.div>

      <div className="border-t border-line bg-page/50">
        <button
          className="flex w-full items-center gap-2 px-5 py-3 text-left text-sm font-medium text-ink-2 hover:text-ink"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
        >
          How this number was produced
          <ChevronDown size={16} className={`ml-auto transition-transform duration-200 ${open ? "rotate-180" : ""}`} aria-hidden="true" />
        </button>
        <AnimatePresence initial={false}>
          {open && (
            <motion.div
              initial={reduce ? false : { height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={reduce ? { opacity: 0 } : { height: 0, opacity: 0 }}
              transition={{ duration: 0.22, ease }}
              className="overflow-hidden"
            >
              <div className="space-y-4 px-5 pb-5">
                {prov && (
                  <dl className="grid grid-cols-[140px,1fr] gap-x-4 gap-y-2 text-sm">
                    {prov.metrics.map((m) => (
                      <Item key={m.name} term={m.label}>
                        <span className="text-ink">{m.definition}</span>
                        <code className="mt-1 block break-all rounded-md bg-tint px-2 py-1 font-mono text-xs text-ink-2">{m.sql_expression}</code>
                      </Item>
                    ))}
                    <Item term="Filters">
                      {[prov.metrics[0]?.filters, ...answer.active_filters.map(filterText)].filter(Boolean).join("; ") || "none"}
                    </Item>
                    <Item term="Source period">
                      {period}
                      {compared && ` compared with ${compared}`}
                    </Item>
                    <Item term="Refreshed">
                      <span className="num">{prov.published_at.slice(0, 16).replace("T", " ")} UTC</span>
                    </Item>
                    <Item term="Publication">
                      <code className="font-mono text-xs">{prov.published_run}</code>
                    </Item>
                    <Item term="Query template">
                      <code className="font-mono text-xs">
                        {plan?.intent ?? "lookup"} · {prov.data_layer}
                      </code>
                    </Item>
                    <Item term="Valid trips">{formatValue(prov.valid_trip_rate, "ratio")}</Item>
                  </dl>
                )}
                {adjustments.length > 0 && (
                  <div className="space-y-1 text-xs text-ink-2">
                    <div className="font-medium text-ink-3">Plan corrected by code</div>
                    {adjustments.map((r) => (
                      <p key={r}>· {r}</p>
                    ))}
                  </div>
                )}
                <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="More detail">
                  {(
                    [
                      ["data", `Data (${answer.rows.length} rows)`],
                      ["sql", "SQL"],
                      ["timing", "Timing"],
                    ] as const
                  ).map(([key, text]) => (
                    <button
                      key={key}
                      role="tab"
                      aria-selected={detail === key}
                      onClick={() => setDetail(detail === key ? null : key)}
                      className={`h-7 rounded-md px-2.5 text-xs font-medium transition-colors ${
                        detail === key ? "bg-primary/10 text-primary-strong" : "text-ink-2 hover:bg-tint"
                      }`}
                    >
                      {text}
                    </button>
                  ))}
                </div>
                {detail === "data" && <DataTable columns={answer.columns} rows={answer.rows} units={units} />}
                {detail === "sql" && prov && (
                  <pre className="overflow-auto rounded-input bg-tint p-3 font-mono text-xs leading-relaxed text-ink-2">
                    {prov.rendered_sql}
                  </pre>
                )}
                {detail === "timing" && <StepBars steps={answer.step_ms} total={answer.duration_ms} traceId={answer.trace_id} />}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.article>
  );
}

function Item({ term, children }: { term: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-ink-3">{term}</dt>
      <dd className="min-w-0 text-ink-2">{children}</dd>
    </>
  );
}

function Headline({
  label,
  unit,
  metric,
  row,
  compared,
}: {
  label: string;
  unit: string;
  metric: string;
  row: Record<string, unknown>;
  compared: string;
}) {
  const current = row[metric] ?? row[`${metric}_current`];
  const previous = row[`${metric}_previous`];
  const value = Number(current);
  const change =
    previous !== undefined && previous !== null && Number(previous) !== 0
      ? ((value - Number(previous)) / Math.abs(Number(previous))) * 100
      : null;
  return (
    <div className="rounded-input border border-line bg-page/40 px-4 py-3.5">
      <div className="text-xs font-medium text-ink-3">{label}</div>
      <div className="num mt-1 font-display text-[34px] font-semibold leading-tight text-ink">
        {Number.isFinite(value) ? <CountUp value={value} format={(n) => formatValue(n, unit)} /> : formatValue(current, unit)}
      </div>
      {change !== null && (
        <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
          <span
            className={`chip num ${change >= 0 ? "border-good/30 bg-good/10 text-good-ink" : "border-bad/30 bg-bad/10 text-bad-ink"}`}
            aria-label={`${change >= 0 ? "up" : "down"} ${Math.abs(change).toFixed(1)} percent`}
          >
            {change >= 0 ? "▲" : "▼"} {Math.abs(change).toFixed(1)} %
          </span>
          <span className="num text-ink-3">
            vs {formatValue(previous, unit)}
            {compared && ` in ${compared}`}
          </span>
        </div>
      )}
    </div>
  );
}

function StepBars({ steps, total, traceId }: { steps: Record<string, number>; total: number; traceId?: string | null }) {
  const max = Math.max(total, 1);
  return (
    <div className="space-y-1.5">
      {Object.entries(steps).map(([step, ms]) => (
        <div key={step} className="grid grid-cols-[96px,1fr,60px] items-center gap-3 text-xs">
          <span className="text-ink-2">{step.replace(/_/g, " ")}</span>
          <span className="h-1.5 overflow-hidden rounded-full bg-tint">
            <span
              className={`block h-1.5 rounded-full ${["plan", "narrate", "repair"].includes(step) ? "bg-accent" : "bg-primary"}`}
              style={{ width: `${Math.max(2, (100 * ms) / max)}%` }}
            />
          </span>
          <span className="num text-right text-ink-3">{seconds(ms)}</span>
        </div>
      ))}
      <p className="pt-1 text-xs text-ink-3">
        Amber: model steps. Blue: code and database.
        {traceId && (
          <>
            {" "}
            Trace <code className="font-mono">{traceId}</code> in Grafana (Explore, Tempo).
          </>
        )}
      </p>
    </div>
  );
}
