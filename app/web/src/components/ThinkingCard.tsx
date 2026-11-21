import { CheckCircle2, Database, Loader2, ScanSearch, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

// The four steps of every answer. The server does not stream its progress, so the current
// step is an estimate from typical durations on a laptop CPU; it is labelled as such.
const STEPS = [
  { icon: Sparkles, text: "Understanding the question", until: 70 },
  { icon: ScanSearch, text: "Checking the plan against the governed vocabulary", until: 80 },
  { icon: Database, text: "Querying the published data", until: 95 },
  { icon: ShieldCheck, text: "Writing and checking the explanation", until: Infinity },
];

export default function ThinkingCard() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  const current = STEPS.findIndex((s) => seconds < s.until);

  return (
    <div className="panel overflow-hidden">
      <div className="h-1 w-full bg-slate-100">
        <div className="h-1 animate-shimmer bg-taxi-gradient" style={{ width: `${Math.min(95, seconds / 1.8)}%` }} />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 px-5 pt-4">
        <span className="text-sm font-semibold text-night-800">Working on your answer</span>
        <span className="tabular-nums text-sm text-slate-500">
          {Math.floor(seconds / 60) ? `${Math.floor(seconds / 60)} min ` : ""}
          {seconds % 60} s
        </span>
      </div>
      <ol className="space-y-2.5 px-5 py-4">
        {STEPS.map((step, i) => {
          const done = i < current;
          const active = i === current;
          const Icon = done ? CheckCircle2 : active ? Loader2 : step.icon;
          return (
            <li
              key={step.text}
              className={`flex items-center gap-3 text-sm ${
                done ? "text-mint-700" : active ? "font-medium text-night-800" : "text-slate-400"
              }`}
            >
              <Icon size={17} className={active ? "animate-spin text-taxi-500" : ""} />
              {step.text}
            </li>
          );
        })}
      </ol>
      <p className="border-t border-slate-100 bg-mist px-5 py-2.5 text-xs text-slate-500">
        Typical steps; about 1 to 3 minutes on a laptop CPU, a few seconds on a GPU.
      </p>
    </div>
  );
}
