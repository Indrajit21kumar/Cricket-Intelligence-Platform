// App shell + router. Book 6: a calm, consistent frame around the hero flows,
// with the same design system across every screen (§3, §12).
import { BrowserRouter, Link, NavLink, Navigate, Route, Routes } from "react-router-dom";
import { SessionProvider, useSession } from "./lib/session";
import { Loading } from "./ui";
import { Auth } from "./screens/Auth";
import { Home } from "./screens/Home";
import { Capture } from "./screens/Capture";
import { Progress } from "./screens/Progress";

export function App() {
  return (
    <SessionProvider>
      <BrowserRouter>
        <Shell />
      </BrowserRouter>
    </SessionProvider>
  );
}

function Shell() {
  const { tokens, me, loading, signOut } = useSession();

  if (!tokens) return <Auth />;
  if (loading && !me) {
    return (
      <div className="grid min-h-screen place-items-center">
        <Loading label="Loading your profile…" />
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <TopBar onSignOut={signOut} />
      <main>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/capture" element={<Capture />} />
          <Route path="/progress" element={<Progress />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      <Footer />
    </div>
  );
}

function TopBar({ onSignOut }: { onSignOut: () => void }) {
  const link = ({ isActive }: { isActive: boolean }) =>
    `rounded-lg px-3 py-1.5 text-sm font-medium ${isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100"}`;
  return (
    <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-3">
        <Link to="/" className="flex items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand-600 text-sm font-extrabold text-white">
            CIP
          </span>
          <span className="text-sm font-bold text-slate-900">Cricket Intelligence</span>
        </Link>
        <nav className="flex items-center gap-1">
          <NavLink to="/" end className={link}>
            Home
          </NavLink>
          <NavLink to="/capture" className={link}>
            Analyse
          </NavLink>
          <NavLink to="/progress" className={link}>
            Progress
          </NavLink>
          <button
            onClick={onSignOut}
            className="ml-2 rounded-lg px-3 py-1.5 text-sm font-medium text-slate-500 hover:bg-slate-100"
          >
            Sign out
          </button>
        </nav>
      </div>
    </header>
  );
}

function Footer() {
  return (
    <footer className="mx-auto max-w-5xl px-4 py-8 text-center text-xs text-slate-400">
      Cricket Intelligence Platform · Every number invites “why?” · Measured, estimated, and
      modelled values are shown honestly.
    </footer>
  );
}
