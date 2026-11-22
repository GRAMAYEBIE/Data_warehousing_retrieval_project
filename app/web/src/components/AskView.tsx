import { useMutation, useQuery } from "@tanstack/react-query";
import { AnimatePresence, LayoutGroup, motion, useReducedMotion } from "framer-motion";
import { ArrowUp, BookOpen, CircleDollarSign, MapPinned, RotateCcw, ShieldAlert, TrendingUp, X } from "lucide-react";
import { type KeyboardEvent, type ReactNode, type RefObject, useEffect, useRef, useState } from "react";
import { type Answer, ApiError, api, type CatalogView, type Health } from "../api/client";
import AnswerCard from "./AnswerCard";
import ErrorBoundary from "./ErrorBoundary";
import HeroScene from "./HeroScene";
import { ease, rise, spring, stagger } from "./motion";
import ThinkingCard from "./ThinkingCard";

const SUGGESTIONS: { icon: ReactNode; tone: string; topic: string; question: string }[] = [
  {
    icon: <CircleDollarSign size={17} />,
    tone: "bg-primary/10 text-primary-strong",
    topic: "Revenue",
    question: "What was total revenue in February 2025?",
  },
  { icon: <TrendingUp size={17} />, tone: "bg-primary/10 text-primary-strong", topic: "Demand", question: "Weekly trend of trips in Manhattan" },
  {
    icon: <MapPinned size={17} />,
    tone: "bg-primary/10 text-primary-strong",
    topic: "Geography",
    question: "Which pickup zones had the biggest drop in trips last month?",
  },
  { icon: <ShieldAlert size={17} />, tone: "bg-bad/10 text-bad-ink", topic: "Safeguards", question: "How much do drivers earn per shift?" },
];

type Turn = { id: number; question: string; answer?: Answer; error?: string };
type Chip = { id: string; kind: "measure" | "filter" | "period"; text: string; phrase: string };

function monthWords(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
}

// The context of the conversation as chips: the measures, the filters and the period of the
// last answer. The API keeps it in the session; removing a chip resets the session and
// writes the next question with the chips that remain (the backend has no partial edit).
function chipsOf(answer: Answer | undefined, labels: Record<string, string>): Chip[] {
  if (!answer?.plan || answer.status !== "answered") return [];
  const chips: Chip[] = answer.plan.metrics.map((m) => ({
    id: `m:${m}`,
    kind: "measure",
    text: labels[m] ?? m.replace(/_/g, " "),
    phrase: labels[m] ?? m.replace(/_/g, " "),
  }));
  for (const f of answer.active_filters) {
    for (const v of f.values) {
      const negated = f.operator === "!=" || f.operator === "not in";
      const where = f.dimension.includes("borough") || f.dimension.includes("zone");
      chips.push({
        id: `f:${f.dimension}:${v}`,
        kind: "filter",
        text: negated ? `not ${v}` : String(v),
        phrase: negated
          ? `excluding ${v}`
          : where
            ? `in ${v}`
            : `with ${f.dimension.replace(/_/g, " ")} ${v}`,
      });
    }
  }
  const months = (answer.provenance?.period_resolved?.period ?? "").split(/\s*,\s*/).filter(Boolean);
  if (months.length) {
    const text = months.length === 1 ? monthWords(months[0]) : `${monthWords(months[0])} – ${monthWords(months[months.length - 1])}`;
    const long = (m: string) => {
      const [y, n] = m.split("-").map(Number);
      return new Date(Date.UTC(y, n - 1, 1)).toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
    };
    chips.push({
      id: "period",
      kind: "period",
      text,
      phrase: months.length === 1 ? `in ${long(months[0])}` : `from ${long(months[0])} to ${long(months[months.length - 1])}`,
    });
  }
  return chips;
}

function questionFrom(chips: Chip[]): string {
  const measures = chips.filter((c) => c.kind === "measure").map((c) => c.phrase);
  const rest = chips.filter((c) => c.kind !== "measure").map((c) => c.phrase);
  const head = measures.length ? measures.join(" and ") : "Trips";
  return [head, ...rest].join(" ");
}

type Props = {
  catalog?: CatalogView;
  health?: Health;
  injected?: { text: string; nonce: number };
  onOpenMeasures: () => void;
};

export default function AskView({ catalog, health, injected, onOpenMeasures }: Props) {
  const reduce = useReducedMotion();
  const [sessionId, setSessionId] = useState<string>();
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [edited, setEdited] = useState<Chip[] | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  const session = useQuery({ queryKey: ["session"], queryFn: api.newSession, staleTime: Infinity });
  useEffect(() => {
    setSessionId(session.data);
  }, [session.data]);

  // A measure's "Ask about this measure" fills the box.
  useEffect(() => {
    if (!injected) return;
    setQuestion(injected.text);
    input.current?.focus();
  }, [injected]);

  const ask = useMutation({
    mutationFn: (q: string) => api.ask(sessionId!, q),
    onSuccess: (answer) => setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, answer } : turn))),
    onError: (error) =>
      setTurns((t) =>
        t.map((turn, i) =>
          i === t.length - 1 ? { ...turn, error: error instanceof ApiError ? error.message : String(error) } : turn,
        ),
      ),
  });
  const newAnalysis = useMutation({
    mutationFn: () => api.reset(sessionId!),
    onSuccess: () => {
      setTurns([]);
      setEdited(null);
      setQuestion("");
    },
  });
  const resetContext = useMutation({ mutationFn: () => api.reset(sessionId!) });

  // Keep the newest exchange in view. Braces, not an expression body: recent Chromium
  // returns a Promise from scrolling methods and React takes a returned value for a
  // clean-up function ("destroy is not a function", observed).
  useEffect(() => {
    const el = scroller.current;
    if (el && turns.length) el.scrollTo({ top: el.scrollHeight, behavior: reduce ? "auto" : "smooth" });
  }, [turns, reduce]);

  // "/" focuses the question box from anywhere.
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && /input|textarea/i.test(e.target.tagName);
      if (e.key === "/" && !typing) {
        e.preventDefault();
        input.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const submit = (q: string) => {
    const text = q.trim();
    if (text.length < 3 || !sessionId || ask.isPending) return;
    setTurns((t) => [...t, { id: Date.now(), question: text }]);
    setQuestion("");
    setEdited(null);
    ask.mutate(text);
  };

  const labels = Object.fromEntries(Object.entries(catalog?.metrics ?? {}).map(([k, m]) => [k, m.label]));
  const units = Object.fromEntries(Object.entries(catalog?.metrics ?? {}).map(([k, m]) => [k, m.unit]));
  const last = [...turns].reverse().find((t) => t.answer)?.answer;
  const chips = edited ?? chipsOf(last, labels);
  const months = health?.complete_months ?? [];
  const empty = turns.length === 0;
  const narrow = typeof window !== "undefined" && window.matchMedia("(max-width: 480px)").matches;

  const removeChip = (chip: Chip) => {
    const remaining = chips.filter((c) => c.id !== chip.id);
    setEdited(remaining);
    resetContext.mutate();
    setQuestion(remaining.length ? questionFrom(remaining) : "");
    input.current?.focus();
  };

  const composer = (
    <Composer
      inputRef={input}
      value={question}
      onChange={setQuestion}
      onSubmit={() => submit(question)}
      disabled={!sessionId}
      busy={ask.isPending}
      large={empty}
      placeholder={empty ? (narrow ? "Ask about trips, revenue, zones…" : "Ask about trips, revenue, fares, zones…") : "Ask a follow-up…"}
    />
  );

  return (
    <LayoutGroup>
      <div className="flex h-full min-h-0 flex-col">
        <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-3xl px-4 sm:px-6">
            <div className={empty ? "pt-6" : "sticky top-0 z-10 -mx-4 bg-page/95 px-4 pb-1 pt-3 backdrop-blur sm:-mx-6 sm:px-6"}>
            <motion.header
              layout
              transition={reduce ? { duration: 0 } : { duration: 0.45, ease }}
              className={`relative overflow-hidden rounded-card border border-line bg-surface shadow-soft ${
                empty ? "min-h-[190px] sm:h-[200px]" : "h-14"
              }`}
            >
              <HeroScene />
              <AnimatePresence mode="wait" initial={false}>
                {empty ? (
                  <motion.div
                    key="hero"
                    className="relative flex h-full flex-col justify-center px-5 py-6 sm:px-8"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.2 }}
                  >
                    <h1 className="text-[26px] font-semibold leading-tight sm:text-[32px]">
                      Ask New York&apos;s taxi data anything
                    </h1>
                    <p className="mt-2 max-w-md text-[15px] text-ink-2">
                      Plain-English questions, answered with governed measures and their source.
                    </p>
                    <div className="mt-3.5 flex flex-wrap gap-2">
                      {months.length > 0 && (
                        <span className="chip num border-line bg-surface/90 text-ink-2">
                          {months[0]} → {months[months.length - 1]}
                        </span>
                      )}
                      {months.length > 0 && (
                        <span className="chip border-line bg-surface/90 text-ink-2">{months.length} months published</span>
                      )}
                      <span className="chip border-good/30 bg-good/10 text-good-ink">Numbers verified</span>
                    </div>
                  </motion.div>
                ) : (
                  <motion.div
                    key="bar"
                    className="relative flex h-full items-center gap-3 px-4"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.2 }}
                  >
                    <h1 className="truncate text-[15px] font-semibold">Ask New York&apos;s taxi data</h1>
                    {months.length > 0 && (
                      <span className="chip num hidden border-line bg-surface/90 text-ink-2 sm:inline-flex">
                        {months[0]} → {months[months.length - 1]}
                      </span>
                    )}
                    <button className="btn-ghost ml-auto h-8 px-2.5 text-xs xl:hidden" onClick={onOpenMeasures}>
                      <BookOpen size={14} aria-hidden="true" /> Measures
                    </button>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.header>
            </div>

            {empty ? (
              <div className="pb-10">
                <motion.div layoutId="composer" transition={spring} className="mt-5">
                  {composer}
                </motion.div>
                <div className="mt-2 flex items-center justify-between text-xs text-ink-3">
                  <span className="hidden sm:inline">Enter to send · Shift+Enter for a new line · / to focus</span>
                  <button className="btn-ghost h-7 px-2 text-xs xl:hidden" onClick={onOpenMeasures}>
                    <BookOpen size={13} aria-hidden="true" /> Governed measures
                  </button>
                </div>
                <motion.ul className="mt-5 grid gap-3 sm:grid-cols-2" variants={stagger} initial="hidden" animate="show">
                  {SUGGESTIONS.map((s) => (
                    <motion.li key={s.question} variants={rise}>
                      <button
                        onClick={() => submit(s.question)}
                        disabled={!sessionId}
                        className="lift card flex h-full w-full items-start gap-3 p-4 text-left hover:border-line-strong disabled:opacity-50"
                      >
                        <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-input ${s.tone}`} aria-hidden="true">
                          {s.icon}
                        </span>
                        <span>
                          <span className="block text-xs font-medium text-ink-3">{s.topic}</span>
                          <span className="mt-0.5 block text-sm font-medium leading-5 text-ink">{s.question}</span>
                        </span>
                      </button>
                    </motion.li>
                  ))}
                </motion.ul>
              </div>
            ) : (
              <div className="space-y-9 pb-8 pt-6">
                {turns.map((turn) => (
                  <section key={turn.id} className="space-y-4" aria-label={`Question: ${turn.question}`}>
                    <motion.div
                      initial={reduce ? false : { opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.25, ease }}
                      className="flex justify-end"
                    >
                      <div className="max-w-[85%] rounded-card rounded-br-[4px] bg-primary/10 px-4 py-2.5 text-[15px] leading-6 text-ink">
                        {turn.question}
                      </div>
                    </motion.div>
                    {turn.answer && (
                      <ErrorBoundary label="answer" compact>
                        <AnswerCard answer={turn.answer} units={units} labels={labels} onFollowUp={submit} />
                      </ErrorBoundary>
                    )}
                    {turn.error && (
                      <div className="rounded-card border border-line border-l-4 border-l-bad bg-surface px-4 py-3 text-sm text-ink">
                        The question could not be answered: {turn.error}
                      </div>
                    )}
                    {!turn.answer && !turn.error && <ThinkingCard />}
                  </section>
                ))}
              </div>
            )}
          </div>
        </div>

        {!empty && (
          <div className="shrink-0 border-t border-line/70 bg-page/90 pt-2.5 backdrop-blur">
            <div className="mx-auto w-full max-w-3xl px-4 pb-3 sm:px-6">
              <ContextChips
                chips={chips}
                edited={edited !== null}
                onRemove={removeChip}
                onNewAnalysis={() => newAnalysis.mutate()}
                busy={ask.isPending || newAnalysis.isPending}
              />
              <motion.div layoutId="composer" transition={spring}>
                {composer}
              </motion.div>
            </div>
          </div>
        )}
      </div>
    </LayoutGroup>
  );
}

function ContextChips({
  chips,
  edited,
  onRemove,
  onNewAnalysis,
  busy,
}: {
  chips: Chip[];
  edited: boolean;
  onRemove: (chip: Chip) => void;
  onNewAnalysis: () => void;
  busy: boolean;
}) {
  return (
    <div className="mb-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs text-ink-3">Context</span>
        <AnimatePresence initial={false} mode="popLayout">
          {chips.map((chip) => (
            <motion.span
              key={chip.id}
              layout
              initial={{ opacity: 0, scale: 0.92 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.92 }}
              transition={{ duration: 0.15 }}
              className={`chip ${
                chip.kind === "measure" ? "border-primary/25 bg-primary/10 text-primary-strong" : "border-line bg-surface text-ink-2"
              }`}
            >
              {chip.text}
              <button
                className="-mr-1 grid h-4 w-4 place-items-center rounded-full hover:bg-ink/10"
                onClick={() => onRemove(chip)}
                disabled={busy}
                aria-label={`Remove ${chip.text} from the context`}
              >
                <X size={11} aria-hidden="true" />
              </button>
            </motion.span>
          ))}
        </AnimatePresence>
        {chips.length === 0 && <span className="text-xs text-ink-3">whole city, all measures</span>}
        <button className="btn-ghost ml-auto h-7 px-2 text-xs" onClick={onNewAnalysis} disabled={busy}>
          <RotateCcw size={13} aria-hidden="true" /> New analysis
        </button>
      </div>
      <p className="mt-1 text-xs text-ink-3" aria-live="polite">
        {edited
          ? "Context updated: the question below uses the chips you kept. Edit it or press Enter."
          : "Follow-ups keep these filters unless you change them."}
      </p>
    </div>
  );
}

function Composer({
  inputRef,
  value,
  onChange,
  onSubmit,
  disabled,
  busy,
  large,
  placeholder,
}: {
  inputRef: RefObject<HTMLTextAreaElement>;
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  disabled: boolean;
  busy: boolean;
  large: boolean;
  placeholder: string;
}) {
  // The box grows with the question, up to six lines.
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 168)}px`;
  }, [value, inputRef]);
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSubmit();
    }
  };
  const ready = value.trim().length >= 3 && !busy && !disabled;
  return (
    <form
      className="flex items-end gap-2 rounded-card border border-line bg-surface p-2 shadow-soft transition-shadow duration-200 focus-within:border-primary/50 focus-within:ring-4 focus-within:ring-primary/10"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <textarea
        ref={inputRef}
        rows={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKey}
        disabled={disabled}
        placeholder={disabled ? "Connecting to the assistant…" : placeholder}
        aria-label="Your question"
        className={`block flex-1 resize-none bg-transparent px-3 leading-6 text-ink outline-none placeholder:text-ink-3 focus-visible:ring-0 focus-visible:ring-offset-0 ${
          large ? "py-3 text-base" : "py-2 text-[15px]"
        }`}
      />
      <motion.button
        type="submit"
        disabled={!ready}
        whileTap={ready ? { scale: 0.94 } : undefined}
        className={`grid shrink-0 place-items-center rounded-input transition-colors duration-150 ${large ? "h-11 w-11" : "h-9 w-9"} ${
          ready ? "bg-accent text-accent-ink hover:brightness-105" : "bg-tint text-ink-3"
        }`}
        aria-label="Send the question"
      >
        <ArrowUp size={18} strokeWidth={2.4} aria-hidden="true" />
      </motion.button>
    </form>
  );
}
