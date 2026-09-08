import { Suspense, lazy, useEffect, useRef } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useStatus } from "./lib/queries";
import Search from "./pages/Search";
import Folders from "./pages/Folders";
import Setup from "./pages/Setup";

// pdfjs is ~700 KB; keep it off the Search/Folders/Setup pages
const Reader = lazy(() => import("./pages/Reader"));

// keep status polling app-wide and refresh derived data when a sync finishes
function SyncWatcher() {
  const { data } = useStatus();
  const qc = useQueryClient();
  const wasRunning = useRef(false);
  const running = !!data?.sync.running;
  useEffect(() => {
    if (wasRunning.current && !running) {
      for (const key of ["notes", "courses", "search", "folders", "note"]) {
        qc.invalidateQueries({ queryKey: [key] });
      }
    }
    wasRunning.current = running;
  }, [running, qc]);
  return null;
}

function Tab({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) =>
        `rounded-lg px-3 py-1.5 text-sm ${isActive ? "bg-accentSoft text-accent font-semibold" : "text-muted hover:text-ink"}`
      }
    >
      {label}
    </NavLink>
  );
}

export default function App() {
  return (
    <div className="flex h-screen flex-col">
      <SyncWatcher />
      <header className="flex-none border-b border-line px-5 py-2.5">
        <div className="mx-auto flex max-w-3xl items-center gap-4">
          <div className="text-[17px] font-bold tracking-tight">
            md<span className="text-accent">notes</span>
          </div>
          <nav className="flex gap-1">
            <Tab to="/" label="Search" />
            <Tab to="/folders" label="Folders" />
            <Tab to="/setup" label="Setup" />
          </nav>
        </div>
      </header>
      <main className="min-h-0 flex-1 overflow-auto">
        <Routes>
          <Route path="/" element={<Search />} />
          <Route path="/folders" element={<Folders />} />
          <Route path="/setup" element={<Setup />} />
          <Route path="/note/*" element={<Suspense fallback={null}><Reader /></Suspense>} />
        </Routes>
      </main>
    </div>
  );
}
