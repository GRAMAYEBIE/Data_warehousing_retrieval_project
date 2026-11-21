import { useMutation, useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  ArrowUp,
  ArrowUpRight,
  CircleDollarSign,
  Filter as FilterIcon,
  MapPinned,
  RotateCcw,
  Search,
  ShieldCheck,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { type Answer, ApiError, api, type CatalogView, type Health } from "../api/client";
import { filterText } from "../lib/format";
import AnswerCard from "./AnswerCard";
import { ease, rise, stagger } from "./motion";
import TaxiScene from "./TaxiScene";
import ThinkingCard from "./ThinkingCard";

const SUGGESTIONS: { icon: ReactNode; tone: string; topic: string; question: string }[] = [
  {
    icon: <CircleDollarSign size={22} />,
    tone: "bg-taxi-400/15 text-taxi-600",
    topic: "Revenue",
    question: "What was total revenue in February 2025?",
  },
  {
    icon: <TrendingUp size={22} />,
    tone: "bg-sky-100 text-sky-500",
    topic: "Demand",
    question: "Weekly trend of trips in Manhattan",
  },
  {
    icon: <MapPinned size={22} />,
    tone: "bg-mint-100 text-mint-700",
    topic: "Geography",
    question: "Which pickup zones had the biggest drop in trips last month, and was revenue affected too?",
  },
  {
    icon: <ShieldCheck size={22} />,
    tone: "bg-coral-100 text-coral-600",
    topic: "Safeguards",
    question: "How much do drivers earn per shift?",
  },
];

type Turn = { question: string; answer?: Answer; error?: string };

export default function AskView({ catalog, health }: { catalog?: CatalogView; health?: Health }) {
  const [sessionId, setSessionId] = useState<string>();
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const end = useRef<HTMLDivElement>(null);

  const session = useQuery({ queryKey: ["session"], queryFn: api.newSession, staleTime: Infinity });
  useEffect(() => setSessionId(session.data), [session.data]);

  const ask = useMutation({
    mutationFn: (q: string) => api.ask(sessionId!, q),
    onSuccess: (answer) =>
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, answer } : turn))),
    onError: (error) =>
      setTurns((t) =>
        t.map((turn, i) =>
          i === t.length - 1
            ? { ...turn, error: error instanceof ApiError ? error.message : String(error) }
            : turn,
        ),
      ),
  });
  const reset = useMutation({
    mutationFn: () => api.reset(sessionId!),
    onSuccess: () => setTurns([]),
  });

  useEffect(() => end.current?.scrollIntoView({ behavior: "smooth", block: "end" }), [turns]);

  const submit = (q: string) => {
    const text = q.trim();
    if (text.length < 3 || !sessionId || ask.isPending) return;
    setTurns((t) => [...t, { question: text }]);
    setQuestion("");
    ask.mutate(text);
  };

  const last = [...turns].reverse().find((t) => t.answer)?.answer;
  const units = Object.fromEntries(Object.entries(catalog?.metrics ?? {}).map(([k, m]) => [k, m.unit]));
  const labels = Object.fromEntries(Object.entries(catalog?.metrics ?? {}).map(([k, m]) => [k, m.label]));

  return (
    <div className="grid gap-8 xl:grid-cols-[1fr,300px]">
      <section className="min-w-0">
        {turns.length === 0 ? (
          <Welcome onPick={submit} health={health} />
        ) : (
          <div className="space-y-6 pb-4">
            {turns.map((turn, i) => (
              <div key={i} className="animate-fade-up space-y-3">
                <div className="flex justify-end">
                  <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.35, ease }} className="max-w-[80%] rounded-3xl rounded-br-lg bg-night-800 px-5 py-3.5 text-[1.02rem] text-white shadow-soft">
                    {turn.question}
                  </motion.div>
                </div>
                {turn.answer && (
                  <AnswerCard answer={turn.answer} units={units} labels={labels} onFollowUp={submit} />
                )}
                {turn.error && (
                  <div className="panel border-coral-100 bg-coral-50 px-5 py-4 text-sm text-coral-600">
                    {turn.error}
                  </div>
                )}
                {!turn.answer && !turn.error && <ThinkingCard />}
              </div>
            ))}
          </div>
        )}
        <div ref={end} />

        <form
          className="sticky bottom-5 mt-8 flex items-center gap-3 rounded-[1.4rem] border border-slate-200 bg-white/95 p-2.5 pl-5 shadow-lift ring-taxi-400/30 backdrop-blur transition focus-within:ring-4"
          onSubmit={(e) => {
            e.preventDefault();
            submit(question);
          }}
        >
          <Sparkles size={20} className="shrink-0 text-taxi-500" />
          <input
            className="min-w-0 flex-1 bg-transparent py-2.5 text-[1.05rem] outline-none placeholder:text-slate-400"
            placeholder={
              turns.length ? "Follow up, e.g. “And for Queens?”" : "Ask about trips, revenue, fares, zones…"
            }
            value={question}
            maxLength={500}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={!sessionId}
          />
          <button
            className="btn-taxi h-12 w-12 shrink-0 rounded-2xl p-0"
            disabled={ask.isPending || question.trim().length < 3}
            aria-label="Ask"
          >
            <ArrowUp size={20} strokeWidth={2.5} />
          </button>
        </form>
      </section>

      <aside className="space-y-4 xl:sticky xl:top-8 xl:self-start">
        <ContextPanel
          filters={last?.active_filters ?? []}
          canReset={turns.length > 0 && !ask.isPending}
          onReset={() => reset.mutate()}
        />
        <Glossary catalog={catalog} />
      </aside>
    </div>
  );
}

function Welcome({ onPick, health }: { onPick: (q: string) => void; health?: Health }) {
  const months = health?.complete_months ?? [];
  return (
    <div className="space-y-8">
      <motion.div
        className="relative overflow-hidden rounded-[2rem] bg-night-900 text-white shadow-lift"
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease }}
      >
        <div className="absolute inset-0 bg-hero-glow" />
        <div className="absolute inset-x-0 bottom-0 z-10 h-2 bg-checker" />
        <div className="relative grid items-center gap-6 px-8 pb-10 pt-9 lg:grid-cols-[1.05fr,1fr] lg:px-10">
          <div>
            <motion.span
              className="chip bg-white/10 text-sm text-taxi-300"
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.2, duration: 0.5, ease }}
            >
              <Sparkles size={15} /> Governed AI analytics
            </motion.span>
            <motion.h1
              className="mt-5 text-4xl font-extrabold leading-[1.1] tracking-tight xl:text-5xl"
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3, duration: 0.6, ease }}
            >
              Ask New York&apos;s taxi data{" "}
              <span className="bg-taxi-gradient bg-clip-text text-transparent">anything</span>.
            </motion.h1>
            <motion.p
              className="mt-4 text-lg leading-relaxed text-slate-300"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.45, duration: 0.6, ease }}
            >
              The model plans your question and explains the result. Every number comes from a governed
              metric on the published data, and every answer shows how it was produced.
            </motion.p>
            {months.length > 0 && (
              <motion.div
                className="mt-6 flex flex-wrap gap-2"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.6, duration: 0.5 }}
              >
                <span className="chip bg-white/10 text-slate-200">
                  {months[0]} → {months[months.length - 1]}
                </span>
                <span className="chip bg-white/10 text-slate-200">{months.length} months published</span>
                <span className="chip bg-mint-500/20 text-mint-100">Numbers verified</span>
              </motion.div>
            )}
          </div>
          <motion.div
            initial={{ opacity: 0, x: 40 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.25, duration: 0.8, ease }}
          >
            <TaxiScene className="w-full drop-shadow-2xl" />
          </motion.div>
        </div>
      </motion.div>

      <div>
        <div className="eyebrow mb-4 text-xs">Try a question</div>
        <motion.div className="grid gap-4 sm:grid-cols-2" variants={stagger} initial="hidden" animate="show">
          {SUGGESTIONS.map((s) => (
            <motion.button
              key={s.question}
              variants={rise}
              whileHover={{ y: -4, boxShadow: "0 18px 40px -14px rgba(10,22,40,0.28)" }}
              whileTap={{ scale: 0.98 }}
              onClick={() => onPick(s.question)}
              className="panel group flex items-start gap-4 p-5 text-left"
            >
              <span className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl ${s.tone}`}>{s.icon}</span>
              <span className="flex-1">
                <span className="eyebrow">{s.topic}</span>
                <span className="mt-1 block text-[1.02rem] font-semibold leading-snug text-night-800">{s.question}</span>
              </span>
              <ArrowUpRight size={18} className="mt-1 text-slate-300 transition group-hover:text-taxi-500" />
            </motion.button>
          ))}
        </motion.div>
      </div>
    </div>
  );
}

function ContextPanel({
  filters,
  canReset,
  onReset,
}: {
  filters: Answer["active_filters"];
  canReset: boolean;
  onReset: () => void;
}) {
  return (
    <div className="panel p-5">
      <div className="flex items-center gap-2">
        <FilterIcon size={16} className="text-night-600" />
        <h3 className="text-sm font-semibold">Conversation context</h3>
      </div>
      <div className="mt-3">
        <div className="eyebrow mb-2">Active filters</div>
        {filters.length ? (
          <div className="flex flex-wrap gap-1.5">
            {filters.map((f) => (
              <span key={filterText(f)} className="chip bg-taxi-400/20 text-night-800">
                {filterText(f)}
              </span>
            ))}
          </div>
        ) : (
          <p className="text-sm text-slate-500">None: the whole city.</p>
        )}
      </div>
      <p className="mt-3 text-xs leading-relaxed text-slate-500">
        A follow-up keeps the measure, the period and these filters unless it names new ones.
      </p>
      <button className="btn-soft mt-4 w-full" disabled={!canReset} onClick={onReset}>
        <RotateCcw size={15} /> New analysis
      </button>
    </div>
  );
}

function Glossary({ catalog }: { catalog?: CatalogView }) {
  const [term, setTerm] = useState("");
  const metrics = Object.entries(catalog?.metrics ?? {}).filter(([name, m]) =>
    `${name} ${m.label} ${m.description}`.toLowerCase().includes(term.toLowerCase()),
  );
  return (
    <div className="panel p-5">
      <h3 className="text-sm font-semibold">Governed measures</h3>
      <p className="mt-1 text-xs text-slate-500">One definition each, shared with the dashboards.</p>
      <label className="mt-3 flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2">
        <Search size={14} className="text-slate-400" />
        <input
          className="w-full bg-transparent text-sm outline-none"
          placeholder="Search a measure"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
        />
      </label>
      <ul className="mt-3 max-h-80 space-y-2 overflow-auto pr-1">
        {metrics.map(([name, m]) => (
          <li key={name} className="rounded-xl bg-mist px-3 py-2">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-sm font-medium text-night-800">{m.label}</span>
              <span className="text-[11px] text-slate-500">{m.unit}</span>
            </div>
            <p className="mt-0.5 line-clamp-2 text-xs text-slate-500">{m.description}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
