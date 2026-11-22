import { motion, useReducedMotion } from "framer-motion";
import { Check } from "lucide-react";
import { useEffect, useState } from "react";
import Markdown from "./Markdown";

// The real progress of an answer, from the API's events: the guardrail chain of a data
// question (Plan -> Validate -> Query -> Explain) or the shorter path of a conversational
// one (Plan -> Answer), then the text as the model writes it.
export type Progress = { started: string[]; done: string[]; text: string };

const DATA_STAGES = [
  { name: "Plan", steps: ["guards", "plan"], detail: "The model turns the question into a plan of governed measures" },
  { name: "Validate", steps: ["validate", "repair", "validate_repaired"], detail: "Code checks the plan against the catalogue and the question" },
  { name: "Query", steps: ["execute", "provenance"], detail: "An approved SQL template runs read-only on the published data" },
  { name: "Explain", steps: ["narrate"], detail: "The model explains; every number will be checked against the result" },
];
const TALK_STAGES = [
  { name: "Plan", steps: ["guards", "plan"], detail: "Reading the question" },
  { name: "Answer", steps: ["converse"], detail: "Writing the answer; figures of the data only come from queries" },
];

export default function ThinkingCard({ progress }: { progress?: Progress }) {
  const reduce = useReducedMotion();
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(() => setSeconds((Date.now() - started) / 1000), 250);
    return () => clearInterval(timer);
  }, []);
  const started = progress?.started ?? [];
  const done = progress?.done ?? [];
  const stages = started.includes("converse") ? TALK_STAGES : DATA_STAGES;
  const stateOf = (steps: string[]) =>
    steps.some((s) => started.includes(s)) && steps.every((s) => !started.includes(s) || done.includes(s)) && steps.some((s) => done.includes(s))
      ? "done"
      : steps.some((s) => started.includes(s))
        ? "active"
        : "next";
  const states = stages.map((s) => stateOf(s.steps));
  // Before the first event, the first stage is the active one.
  if (!states.includes("active") && !states.every((s) => s === "done")) {
    const first = states.indexOf("next");
    if (first >= 0) states[first] = "active";
  }
  const current = Math.max(0, states.lastIndexOf("active"));
  const text = progress?.text ?? "";
  const explaining = started.includes("narrate") || started.includes("converse");

  return (
    <div className="space-y-4" role="status" aria-live="polite" aria-label={`Working: ${stages[current].name}`}>
      <div className="card p-4">
        <ol className="flex items-center gap-2">
          {stages.map((stage, i) => {
            const state = states[i];
            return (
              <li key={stage.name} className="flex flex-1 items-center gap-2 last:flex-none">
                <span
                  className={`relative grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-semibold transition-colors duration-300 ${
                    state === "done" ? "bg-good text-white" : state === "active" ? "bg-accent text-accent-ink" : "border border-line bg-surface text-ink-3"
                  }`}
                >
                  {state === "active" && !reduce && (
                    <motion.span
                      className="absolute inset-0 rounded-full ring-2 ring-accent/60"
                      animate={{ scale: [1, 1.5], opacity: [0.8, 0] }}
                      transition={{ duration: 1.2, repeat: Infinity, ease: "easeOut" }}
                    />
                  )}
                  {state === "done" ? <Check size={14} strokeWidth={3} aria-hidden="true" /> : i + 1}
                </span>
                <span className={`text-sm ${state === "next" ? "text-ink-3" : "font-medium text-ink"}`}>{stage.name}</span>
                {i < stages.length - 1 && (
                  <span className="relative mx-1 h-px flex-1 overflow-hidden bg-line">
                    <motion.span
                      className="absolute inset-y-0 left-0 bg-good"
                      initial={false}
                      animate={{ width: state === "done" ? "100%" : "0%" }}
                      transition={{ duration: reduce ? 0 : 0.45, ease: "easeOut" }}
                    />
                  </span>
                )}
              </li>
            );
          })}
        </ol>
        <p className="mt-3 text-sm text-ink-2">
          {stages[current].detail}… <span className="num text-ink-3">{Math.floor(seconds)} s</span>
        </p>
      </div>
      {explaining && (
        <div className="px-1 text-base leading-7 text-ink">
          <Markdown text={text} caret />
        </div>
      )}
    </div>
  );
}
