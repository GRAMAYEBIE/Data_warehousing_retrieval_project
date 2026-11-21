import { motion } from "framer-motion";
import { Activity, BarChart3, ExternalLink, FileBarChart2, Lock, MessageSquareText } from "lucide-react";
import type { ReactNode } from "react";
import type { CatalogView, Health } from "../api/client";
import { useConfig } from "../lib/config";

export type Page = "ask" | "reports";

type Props = {
  page: Page;
  onPage: (page: Page) => void;
  health?: Health;
  catalog?: CatalogView;
};

export default function Sidebar({ page, onPage, health, catalog }: Props) {
  const config = useConfig();
  const ready = health?.status === "ok" && health.model_available;
  const months = health?.complete_months ?? [];
  return (
    <aside className="sticky top-0 hidden h-screen w-[290px] shrink-0 flex-col bg-night-gradient text-slate-200 lg:flex">
      <div className="h-1.5 bg-checker" />
      <div className="flex items-center gap-3 px-6 pb-7 pt-7">
        <motion.div
          className="grid h-12 w-12 place-items-center rounded-2xl bg-taxi-gradient shadow-glow"
          initial={{ rotate: -12, scale: 0.8, opacity: 0 }}
          animate={{ rotate: 0, scale: 1, opacity: 1 }}
          transition={{ type: "spring", stiffness: 260, damping: 18 }}
        >
          <span className="text-xl font-black tracking-tight text-night-900">M</span>
        </motion.div>
        <div>
          <div className="text-lg font-bold tracking-tight text-white">MetroMove Insight</div>
          <div className="text-sm text-slate-400">NYC Taxi analytics</div>
        </div>
      </div>

      <nav className="space-y-1.5 px-3">
        <div className="eyebrow px-3 pb-2 text-slate-500">Assistant</div>
        <NavItem
          active={page === "ask"}
          onClick={() => onPage("ask")}
          icon={<MessageSquareText size={19} />}
          title="Ask a question"
          hint="Plain English, governed answers"
        />
        <NavItem
          active={page === "reports"}
          onClick={() => onPage("reports")}
          icon={<FileBarChart2 size={19} />}
          title="Report builder"
          hint="Draft, review, publish"
        />
        <div className="eyebrow px-3 pb-2 pt-6 text-slate-500">Platform</div>
        <LinkItem href={config.supersetUrl} icon={<BarChart3 size={19} />} title="Dashboards" hint="Six strategic dashboards" />
        {config.showPlatformHealth && (
          <LinkItem
            href={config.grafanaUrl}
            icon={<Activity size={19} />}
            title="Platform health"
            hint="Administrators · login required"
            badge={<Lock size={13} className="text-taxi-400" />}
          />
        )}
      </nav>

      <div className="mt-auto space-y-3 p-4">
        <div className="rounded-2xl border border-white/10 bg-white/5 p-4 backdrop-blur">
          <div className="flex items-center gap-2.5 font-semibold text-white">
            <span className="relative flex h-3 w-3">
              {ready && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-mint-500 opacity-60" />}
              <span className={`relative inline-flex h-3 w-3 rounded-full ${ready ? "bg-mint-500" : "bg-coral-500"}`} />
            </span>
            {!health ? "Connecting…" : ready ? "Assistant ready" : "Model offline"}
          </div>
          <dl className="mt-3 space-y-2 text-sm">
            <Row label="Model" value={health?.model ?? "-"} />
            <Row label="Data" value={months.length ? `${months[0]} → ${months[months.length - 1]}` : "-"} />
            <Row label="Publication" value={catalog?.published_run ?? "-"} />
          </dl>
          {health && !ready && (
            <p className="mt-3 text-xs leading-relaxed text-slate-400">
              Safeguards still answer; dashboards keep working.
            </p>
          )}
        </div>
        <p className="px-1 text-xs text-slate-500">Data owner · AYEBIE GRAM MESCHAC</p>
      </div>
    </aside>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-slate-400">{label}</dt>
      <dd className="truncate font-medium text-slate-100">{value}</dd>
    </div>
  );
}

type ItemProps = { icon: ReactNode; title: string; hint: string };

function NavItem({ active, onClick, icon, title, hint }: ItemProps & { active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`relative flex w-full items-center gap-3 rounded-2xl px-3 py-3 text-left transition-colors ${
        active ? "text-white" : "text-slate-300 hover:text-white"
      }`}
    >
      {active && (
        <motion.span
          layoutId="nav-active"
          className="absolute inset-0 rounded-2xl bg-white/10 ring-1 ring-white/10"
          transition={{ type: "spring", stiffness: 380, damping: 32 }}
        />
      )}
      <span
        className={`relative grid h-10 w-10 place-items-center rounded-xl transition ${
          active ? "bg-taxi-gradient text-night-900 shadow-glow" : "bg-white/5 text-slate-300"
        }`}
      >
        {icon}
      </span>
      <span className="relative">
        <span className="block font-semibold">{title}</span>
        <span className="block text-xs text-slate-400">{hint}</span>
      </span>
    </button>
  );
}

function LinkItem({ href, icon, title, hint, badge }: ItemProps & { href: string; badge?: ReactNode }) {
  return (
    <motion.a
      href={href}
      target="_blank"
      rel="noreferrer"
      whileHover={{ x: 3 }}
      className="group flex items-center gap-3 rounded-2xl px-3 py-3 text-slate-300 transition-colors hover:bg-white/5 hover:text-white"
    >
      <span className="grid h-10 w-10 place-items-center rounded-xl bg-white/5">{icon}</span>
      <span className="flex-1">
        <span className="flex items-center gap-1.5 font-semibold">
          {title} {badge}
        </span>
        <span className="block text-xs text-slate-400">{hint}</span>
      </span>
      <ExternalLink size={15} className="opacity-0 transition group-hover:opacity-100" />
    </motion.a>
  );
}
