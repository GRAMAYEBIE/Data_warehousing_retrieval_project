import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, BookOpen, Search, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { CatalogView } from "../api/client";
import { CATEGORIES, DATA_OWNER, type Measure, measuresOf } from "../lib/measures";
import { ease, spring } from "./motion";

type Props = { catalog?: CatalogView; onAsk: (question: string) => void };

// Governed measures: searchable, grouped by category, one line each; a row opens its
// full definition with an "Ask about this measure" shortcut.
export function MeasuresList({ catalog, onAsk }: Props) {
  const [term, setTerm] = useState("");
  const [open, setOpen] = useState<Measure | null>(null);
  const measures = useMemo(() => measuresOf(catalog), [catalog]);
  const shown = measures.filter((m) =>
    `${m.name} ${m.label} ${m.description} ${m.category}`.toLowerCase().includes(term.trim().toLowerCase()),
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="px-4 pb-3 pt-4">
        <h2 className="font-display text-base font-semibold">Governed measures</h2>
        <p className="mt-0.5 text-xs text-ink-3">One definition each, shared with the dashboards.</p>
        <label className="mt-3 flex items-center gap-2 rounded-input border border-line bg-surface px-3 py-2 focus-within:ring-2 focus-within:ring-primary">
          <Search size={14} className="text-ink-3" aria-hidden="true" />
          <input
            className="w-full bg-transparent text-sm outline-none placeholder:text-ink-3"
            placeholder="Search a measure"
            aria-label="Search a measure"
            value={term}
            onChange={(e) => setTerm(e.target.value)}
          />
        </label>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4" aria-busy={!catalog}>
        {!catalog &&
          Array.from({ length: 7 }, (_, i) => (
            <div key={i} className="space-y-1.5 px-2.5 py-2.5">
              <div className="skeleton h-3.5 w-2/3" />
              <div className="skeleton h-3 w-11/12" />
            </div>
          ))}
        {CATEGORIES.map((category) => {
          const rows = shown.filter((m) => m.category === category);
          if (!rows.length) return null;
          return (
            <section key={category} className="mb-2">
              <h3 className="label px-2.5 pb-1 pt-2">{category}</h3>
              <ul>
                {rows.map((m) => (
                  <li key={m.name}>
                    <button
                      onClick={() => setOpen(m)}
                      className="group w-full rounded-input px-2.5 py-2 text-left transition-colors duration-150 hover:bg-tint"
                      aria-haspopup="dialog"
                    >
                      <span className="flex items-center gap-2">
                        <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">{m.label}</span>
                        <span className="pill">{m.unitShort}</span>
                      </span>
                      <span className="mt-0.5 block truncate text-xs text-ink-2">{m.description}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
        {catalog && shown.length === 0 && <p className="px-2.5 py-2 text-sm text-ink-3">No measure matches “{term}”.</p>}
      </div>
      <MeasureDetail
        measure={open}
        onClose={() => setOpen(null)}
        onAsk={(q) => {
          setOpen(null);
          onAsk(q);
        }}
      />
    </div>
  );
}

function MeasureDetail({
  measure,
  onClose,
  onAsk,
}: {
  measure: Measure | null;
  onClose: () => void;
  onAsk: (question: string) => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!measure) return undefined;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [measure, onClose]);
  return (
    <AnimatePresence>
      {measure && (
        <motion.div
          className="fixed inset-0 z-50 grid place-items-center bg-ink/20 p-4 backdrop-blur-[2px]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-labelledby="measure-title"
            className="card w-full max-w-lg p-5 shadow-raised"
            initial={{ opacity: 0, y: 10, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.98 }}
            transition={{ duration: 0.2, ease }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-3">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-input bg-primary/10 text-primary-strong">
                <BookOpen size={17} aria-hidden="true" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-xs text-ink-3">{measure.category}</div>
                <h3 id="measure-title" className="font-display text-lg font-semibold">
                  {measure.label}
                </h3>
              </div>
              <button ref={closeRef} className="btn-ghost h-8 w-8 p-0" onClick={onClose} aria-label="Close">
                <X size={16} />
              </button>
            </div>
            <p className="mt-3 text-sm leading-6 text-ink">{measure.description}</p>
            <dl className="mt-4 grid grid-cols-[120px,1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-ink-3">Unit</dt>
              <dd>
                {measure.unit}
                {measure.estimate && <span className="pill ml-2">estimate</span>}
              </dd>
              <dt className="text-ink-3">Formula</dt>
              <dd>
                <code className="block break-all rounded-md bg-tint px-2 py-1.5 font-mono text-xs text-ink">{measure.formula}</code>
              </dd>
              <dt className="text-ink-3">Filters</dt>
              <dd className="text-ink-2">{measure.filters}</dd>
              <dt className="text-ink-3">Grains</dt>
              <dd className="text-ink-2">{measure.grains}</dd>
              <dt className="text-ink-3">Source</dt>
              <dd className="font-mono text-xs text-ink-2">{measure.source}</dd>
              <dt className="text-ink-3">Owner</dt>
              <dd className="text-ink-2">{DATA_OWNER}</dd>
            </dl>
            <div className="mt-5 flex justify-end">
              <button className="btn-primary" onClick={() => onAsk(`${measure.label} last month by pickup borough`)}>
                Ask about this measure <ArrowRight size={15} aria-hidden="true" />
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// Below 1280 px the panel is a drawer opened from a button.
export function MeasuresDrawer({ open, onClose, ...props }: Props & { open: boolean; onClose: () => void }) {
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            className="fixed inset-0 z-40 bg-ink/20"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.aside
            className="fixed inset-y-0 right-0 z-40 flex w-full max-w-sm flex-col border-l border-line bg-surface shadow-raised"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={spring}
            aria-label="Governed measures"
          >
            <button className="btn-ghost absolute right-3 top-3 h-8 w-8 p-0" onClick={onClose} aria-label="Close the measures">
              <X size={16} />
            </button>
            <MeasuresList
              {...props}
              onAsk={(q) => {
                onClose();
                props.onAsk(q);
              }}
            />
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
