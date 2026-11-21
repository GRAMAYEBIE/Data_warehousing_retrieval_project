import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { FileBarChart2, MessageSquareText } from "lucide-react";
import { useState } from "react";
import { api } from "./api/client";
import AskView from "./components/AskView";
import { ease } from "./components/motion";
import ReportBuilder from "./components/ReportBuilder";
import Sidebar, { type Page } from "./components/Sidebar";

const PAGE = {
  shown: { opacity: 1, y: 0, display: "block", transition: { duration: 0.35, ease } },
  hidden: { opacity: 0, y: 10, transition: { duration: 0.15 }, transitionEnd: { display: "none" } },
};

export default function App() {
  const [page, setPage] = useState<Page>("ask");
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30_000 });
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: api.catalog });

  return (
    <div className="flex min-h-screen">
      <Sidebar page={page} onPage={setPage} health={health.data} catalog={catalog.data} />

      <div className="min-w-0 flex-1">
        {/* Compact navigation on small screens (the sidebar is hidden there). */}
        <div className="flex items-center gap-3 bg-night-900 px-4 py-3 lg:hidden">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-taxi-gradient font-black">M</span>
          <span className="mr-auto font-bold text-white">MetroMove Insight</span>
          <button className="text-slate-300" onClick={() => setPage("ask")} aria-label="Ask a question">
            <MessageSquareText size={22} />
          </button>
          <button className="text-slate-300" onClick={() => setPage("reports")} aria-label="Report builder">
            <FileBarChart2 size={22} />
          </button>
        </div>

        <main className="mx-auto max-w-[1240px] px-4 py-6 sm:px-8 sm:py-9">
          {/* Both pages stay mounted: switching page never loses a conversation or a draft. */}
          <motion.div variants={PAGE} initial={false} animate={page === "ask" ? "shown" : "hidden"}>
            <AskView catalog={catalog.data} health={health.data} />
          </motion.div>
          <motion.div variants={PAGE} initial={false} animate={page === "reports" ? "shown" : "hidden"}>
            <ReportBuilder catalog={catalog.data} />
          </motion.div>
        </main>
      </div>
    </div>
  );
}
