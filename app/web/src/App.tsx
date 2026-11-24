import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { BarChart3, FileBarChart2, LayoutDashboard, MessagesSquare, TrendingUp } from "lucide-react";
import { useState } from "react";
import { api } from "./api/client";
import AskView from "./components/AskView";
import ErrorBoundary from "./components/ErrorBoundary";
import ForecastView from "./components/ForecastView";
import { MeasuresDrawer, MeasuresList } from "./components/MeasuresPanel";
import { ease } from "./components/motion";
import OverviewView from "./components/OverviewView";
import ReportBuilder from "./components/ReportBuilder";
import Sidebar, { BrandMark, type Page, ThemeSwitch } from "./components/Sidebar";
import { useConfig } from "./lib/config";

// Visibility is the class (display), the motion is a short fade and rise on top of it.
const PAGE = {
  shown: { opacity: 1, y: 0, transition: { duration: 0.25, ease } },
  hidden: { opacity: 0, y: 6, transition: { duration: 0 } },
};

export default function App() {
  const [page, setPageState] = useState<Page>("overview");
  const [seen, setSeen] = useState<Partial<Record<Page, boolean>>>({ overview: true });
  const setPage = (next: Page) => {
    setSeen((s) => ({ ...s, [next]: true }));
    setPageState(next);
  };
  const [measuresOpen, setMeasuresOpen] = useState(false);
  const [injected, setInjected] = useState<{ text: string; nonce: number }>();
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30_000 });
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: api.catalog });
  const askAbout = (text: string) => {
    setPage("ask");
    setInjected({ text, nonce: Date.now() });
  };

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar page={page} onPage={setPage} health={health.data} catalog={catalog.data} />
      <div className="flex min-w-0 flex-1 flex-col">
        <MobileNav page={page} onPage={setPage} ready={health.data?.status === "ok" && Boolean(health.data?.model_available)} />
        <div className="flex min-h-0 flex-1">
          {/* Every page stays mounted: switching page never loses a conversation or a draft. */}
          <motion.main
            className={`min-h-0 min-w-0 flex-1 flex-col overflow-y-auto ${page === "overview" ? "flex" : "hidden"}`}
            initial={false}
            animate={page === "overview" ? PAGE.shown : PAGE.hidden}
            aria-label="Overview"
          >
            <ErrorBoundary label="overview">
              <OverviewView catalog={catalog.data} onAsk={askAbout} />
            </ErrorBoundary>
          </motion.main>
          <motion.main
            className={`min-h-0 min-w-0 flex-1 flex-col overflow-y-auto ${page === "forecast" ? "flex" : "hidden"}`}
            initial={false}
            animate={page === "forecast" ? PAGE.shown : PAGE.hidden}
            aria-label="Forecast"
          >
            {/* Loaded on first visit only: the overview stays the first request. */}
            <ErrorBoundary label="forecast">{(page === "forecast" || seen.forecast) && <ForecastView />}</ErrorBoundary>
          </motion.main>
          <motion.main
            className={`min-h-0 min-w-0 flex-1 flex-col ${page === "ask" ? "flex" : "hidden"}`}
            initial={false}
            animate={page === "ask" ? PAGE.shown : PAGE.hidden}
            aria-label="Ask a question"
          >
            <ErrorBoundary label="conversation">
              <AskView
                catalog={catalog.data}
                health={health.data}
                injected={injected}
                onOpenMeasures={() => setMeasuresOpen(true)}
              />
            </ErrorBoundary>
          </motion.main>
          <motion.main
            className={`min-h-0 min-w-0 flex-1 flex-col overflow-y-auto ${page === "reports" ? "flex" : "hidden"}`}
            initial={false}
            animate={page === "reports" ? PAGE.shown : PAGE.hidden}
            aria-label="Report builder"
          >
            <ErrorBoundary label="report builder">
              <ReportBuilder catalog={catalog.data} />
            </ErrorBoundary>
          </motion.main>
          {page === "ask" && (
            <aside className="hidden w-[300px] shrink-0 border-l border-line bg-surface xl:block" aria-label="Governed measures">
              <MeasuresList catalog={catalog.data} onAsk={askAbout} />
            </aside>
          )}
        </div>
      </div>
      <MeasuresDrawer open={measuresOpen} onClose={() => setMeasuresOpen(false)} catalog={catalog.data} onAsk={askAbout} />
    </div>
  );
}

// Below 1024 px the sidebar becomes a top bar.
function MobileNav({ page, onPage, ready }: { page: Page; onPage: (page: Page) => void; ready: boolean }) {
  const config = useConfig();
  const item = (target: Page, icon: JSX.Element, text: string) => (
    <button
      onClick={() => onPage(target)}
      aria-current={page === target ? "page" : undefined}
      className={`btn h-9 px-2.5 ${page === target ? "bg-primary/10 text-primary-strong" : "text-ink-2 hover:bg-tint"}`}
    >
      {icon}
      <span className="hidden sm:inline">{text}</span>
    </button>
  );
  return (
    <nav className="flex h-14 shrink-0 items-center gap-1 border-b border-line bg-surface px-3 lg:hidden" aria-label="Main">
      <BrandMark size={28} />
      <span className="ml-1.5 mr-auto flex items-center gap-1.5 font-display text-sm font-semibold">
        <span className="hidden min-[420px]:inline">MetroMove</span>
        <span className={`h-2 w-2 rounded-full ${ready ? "bg-good" : "bg-bad"}`} aria-label={ready ? "Assistant ready" : "Assistant offline"} />
      </span>
      {item("overview", <LayoutDashboard size={17} aria-hidden="true" />, "Overview")}
      {item("forecast", <TrendingUp size={17} aria-hidden="true" />, "Forecast")}
      {item("ask", <MessagesSquare size={17} aria-hidden="true" />, "Ask")}
      {item("reports", <FileBarChart2 size={17} aria-hidden="true" />, "Reports")}
      <a className="btn h-9 px-2.5 text-ink-2 hover:bg-tint" href={config.supersetUrl} target="_blank" rel="noreferrer" aria-label="Dashboards (opens in a new tab)">
        <BarChart3 size={17} aria-hidden="true" />
      </a>
      <ThemeSwitch />
    </nav>
  );
}
