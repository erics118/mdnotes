import { NavLink, Route, Routes } from "react-router-dom";
import Search from "./pages/Search";
import Folders from "./pages/Folders";
import Setup from "./pages/Setup";
import Reader from "./pages/Reader";

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
          <Route path="/note/*" element={<Reader />} />
        </Routes>
      </main>
    </div>
  );
}
