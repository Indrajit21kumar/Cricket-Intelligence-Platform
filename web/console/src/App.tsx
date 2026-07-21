import { useCallback, useEffect, useState } from "react";
import { api, CipError, type Me } from "./api";

// Demo academies seeded in the DB (fixed UUIDs). In the real product these
// come from the Academy service (M18) + an invitation flow.
const DEMO_ACADEMIES = [
  { id: "11111111-1111-1111-1111-111111111111", name: "PIR Cricket Academy" },
  { id: "22222222-2222-2222-2222-222222222222", name: "Delhi Cricket Club" },
  { id: "33333333-3333-3333-3333-333333333333", name: "Mumbai Youth Cricket" },
];

const ROLES = ["player", "coach", "academy_admin"];

interface Session {
  accessToken: string;
  refreshToken: string;
}

function loadSession(): Session | null {
  const raw = localStorage.getItem("cip_session");
  return raw ? (JSON.parse(raw) as Session) : null;
}

export function App() {
  const [session, setSession] = useState<Session | null>(loadSession());

  const onLogin = (s: Session) => {
    localStorage.setItem("cip_session", JSON.stringify(s));
    setSession(s);
  };
  const onLogout = () => {
    if (session) api.logout(session.refreshToken).catch(() => {});
    localStorage.removeItem("cip_session");
    setSession(null);
  };

  return (
    <div className="min-h-full">
      <TopBar loggedIn={!!session} onLogout={onLogout} />
      {session ? (
        <Dashboard session={session} onLogout={onLogout} />
      ) : (
        <AuthScreen onLogin={onLogin} />
      )}
      <Footer />
    </div>
  );
}

function TopBar({ loggedIn, onLogout }: { loggedIn: boolean; onLogout: () => void }) {
  return (
    <header className="bg-pitch-800 text-white">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-pitch-500 font-extrabold">
            CIP
          </div>
          <div>
            <div className="text-sm font-bold leading-tight">Cricket Intelligence Platform</div>
            <div className="text-[11px] uppercase tracking-widest text-pitch-100/80">
              Console · Identity (M02)
            </div>
          </div>
        </div>
        {loggedIn && (
          <button
            onClick={onLogout}
            className="rounded-lg border border-white/20 px-3 py-1.5 text-sm font-medium hover:bg-white/10"
          >
            Sign out
          </button>
        )}
      </div>
    </header>
  );
}

function Footer() {
  return (
    <footer className="mx-auto max-w-5xl px-6 py-8 text-center text-xs text-slate-400">
      Live demo · talking to the real M02 identity-service · data stored in Postgres with
      row-level tenant isolation
    </footer>
  );
}

// ---------------------------------------------------------------------------
// Auth screen (login + signup)
// ---------------------------------------------------------------------------

function AuthScreen({ onLogin }: { onLogin: (s: Session) => void }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <div className="grid items-center gap-10 md:grid-cols-2">
        <div>
          <h1 className="text-4xl font-extrabold leading-tight text-slate-900">
            Understand movement,
            <br />
            <span className="text-pitch-600">not just detect it.</span>
          </h1>
          <p className="mt-4 max-w-md text-slate-600">
            The explainable cricket-coaching intelligence platform. This is the account
            console — sign in or create an account to see your identity, academy
            memberships, and roles.
          </p>
          <ul className="mt-6 space-y-2 text-sm text-slate-600">
            <li className="flex items-center gap-2">
              <Dot /> Portable identity — your account follows you across academies
            </li>
            <li className="flex items-center gap-2">
              <Dot /> Role-based access — player, coach, academy admin
            </li>
            <li className="flex items-center gap-2">
              <Dot /> Secure by design — argon2 passwords, JWT sessions, tenant isolation
            </li>
          </ul>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="mb-5 flex rounded-lg bg-slate-100 p-1 text-sm font-medium">
            <button
              className={`flex-1 rounded-md py-2 ${
                mode === "login" ? "bg-white shadow text-pitch-700" : "text-slate-500"
              }`}
              onClick={() => setMode("login")}
            >
              Sign in
            </button>
            <button
              className={`flex-1 rounded-md py-2 ${
                mode === "signup" ? "bg-white shadow text-pitch-700" : "text-slate-500"
              }`}
              onClick={() => setMode("signup")}
            >
              Create account
            </button>
          </div>
          {mode === "login" ? (
            <LoginForm onLogin={onLogin} />
          ) : (
            <SignupForm onLogin={onLogin} />
          )}
        </div>
      </div>
    </main>
  );
}

function LoginForm({ onLogin }: { onLogin: (s: Session) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const t = await api.login(email, password);
      onLogin({ accessToken: t.access_token, refreshToken: t.refresh_token });
    } catch (err) {
      setError(err instanceof CipError ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label="Email" type="email" value={email} onChange={setEmail} required />
      <Field label="Password" type="password" value={password} onChange={setPassword} required />
      {error && <ErrorNote>{error}</ErrorNote>}
      <Submit busy={busy}>Sign in</Submit>
    </form>
  );
}

function SignupForm({ onLogin }: { onLogin: (s: Session) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [dob, setDob] = useState("1995-01-01");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState<string>("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      // 1. Register → returns the verification token (dev convenience).
      setStep("Creating account…");
      const reg = await api.register(email, password, dob, name);
      // 2. Auto-verify with the returned token (in prod this is an email link).
      setStep("Verifying email…");
      const verified = await api.verifyEmail(reg.verification_url_hint);
      if (verified.status === "pending_consent") {
        setError(
          "Account created, but this is a minor account — guardian consent is required before sign-in (coming in a later step)."
        );
        setBusy(false);
        setStep("");
        return;
      }
      // 3. Log in.
      setStep("Signing in…");
      const t = await api.login(email, password);
      onLogin({ accessToken: t.access_token, refreshToken: t.refresh_token });
    } catch (err) {
      setError(err instanceof CipError ? err.message : "Signup failed");
      setBusy(false);
      setStep("");
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label="Full name" value={name} onChange={setName} placeholder="Optional" />
      <Field label="Email" type="email" value={email} onChange={setEmail} required />
      <Field
        label="Password"
        type="password"
        value={password}
        onChange={setPassword}
        required
        hint="At least 12 characters"
      />
      <Field label="Date of birth" type="date" value={dob} onChange={setDob} required />
      {error && <ErrorNote>{error}</ErrorNote>}
      <Submit busy={busy}>{busy ? step || "Working…" : "Create account"}</Submit>
      <p className="text-center text-[11px] text-slate-400">
        Under-18 accounts require guardian consent before sign-in.
      </p>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

function Dashboard({ session }: { session: Session; onLogout: () => void }) {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setMe(await api.me(session.accessToken));
    } catch (err) {
      setError(err instanceof CipError ? err.message : "Failed to load profile");
    }
  }, [session.accessToken]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const flash = (msg: string) => {
    setNotice(msg);
    setTimeout(() => setNotice(null), 3500);
  };

  if (error) {
    return (
      <main className="mx-auto max-w-5xl px-6 py-10">
        <ErrorNote>{error}</ErrorNote>
        <p className="mt-3 text-sm text-slate-500">
          Your session may have expired. Sign out and sign back in.
        </p>
      </main>
    );
  }

  if (!me) {
    return <main className="mx-auto max-w-5xl px-6 py-10 text-slate-400">Loading…</main>;
  }

  return (
    <main className="mx-auto max-w-5xl space-y-6 px-6 py-8">
      {notice && (
        <div className="rounded-lg border border-pitch-200 bg-pitch-50 px-4 py-2 text-sm text-pitch-700">
          {notice}
        </div>
      )}

      <div>
        <h2 className="text-2xl font-bold text-slate-900">
          Welcome{me.display_name ? `, ${me.display_name}` : ""}
        </h2>
        <p className="text-slate-500">{me.email}</p>
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        <IdentityCard me={me} />
        <div className="md:col-span-2 space-y-6">
          <JoinCard
            session={session}
            existing={me.memberships.map((m) => m.tenant_id)}
            onJoined={(n) => {
              flash(`Joined ${n}. Sign out and back in to see the new role in your token.`);
              refresh();
            }}
          />
          <MembershipsCard session={session} me={me} onChanged={() => refresh()} onFlash={flash} />
        </div>
      </div>
    </main>
  );
}

function IdentityCard({ me }: { me: Me }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
        Your identity
      </h3>
      <dl className="space-y-3 text-sm">
        <Row label="Status">
          <Badge tone={me.status === "active" ? "green" : "amber"}>{me.status}</Badge>
        </Row>
        <Row label="Age band">{me.dob_band ?? "—"}</Row>
        <Row label="Roles">
          {me.roles.length ? (
            <span className="flex flex-wrap gap-1">
              {me.roles.map((r) => (
                <Badge key={r} tone="slate">
                  {r}
                </Badge>
              ))}
            </span>
          ) : (
            <span className="text-slate-400">none yet</span>
          )}
        </Row>
        <Row label="Person ID">
          <code className="text-[11px] text-slate-400">{me.person_id.slice(0, 8)}…</code>
        </Row>
      </dl>
    </div>
  );
}

function JoinCard({
  session,
  existing,
  onJoined,
}: {
  session: Session;
  existing: string[];
  onJoined: (name: string) => void;
}) {
  const available = DEMO_ACADEMIES.filter((a) => !existing.includes(a.id));
  const [tenantId, setTenantId] = useState(available[0]?.id ?? "");
  const [role, setRole] = useState("player");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const join = async () => {
    if (!tenantId) return;
    setBusy(true);
    setError(null);
    try {
      await api.joinTenant(session.accessToken, tenantId, role);
      const name = DEMO_ACADEMIES.find((a) => a.id === tenantId)?.name ?? "academy";
      onJoined(name);
    } catch (err) {
      setError(err instanceof CipError ? err.message : "Could not join");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
        Join an academy
      </h3>
      {available.length === 0 ? (
        <p className="text-sm text-slate-400">
          You've joined every demo academy. Leave one below to rejoin.
        </p>
      ) : (
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm">
            <span className="mb-1 block text-slate-500">Academy</span>
            <select
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-2"
            >
              {available.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block text-slate-500">Role</span>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="rounded-lg border border-slate-300 px-3 py-2"
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </label>
          <button
            onClick={join}
            disabled={busy}
            className="rounded-lg bg-pitch-600 px-4 py-2 text-sm font-semibold text-white hover:bg-pitch-700 disabled:opacity-50"
          >
            {busy ? "Joining…" : "Join"}
          </button>
        </div>
      )}
      {error && <div className="mt-3"><ErrorNote>{error}</ErrorNote></div>}
    </div>
  );
}

function MembershipsCard({
  session,
  me,
  onChanged,
  onFlash,
}: {
  session: Session;
  me: Me;
  onChanged: () => void;
  onFlash: (m: string) => void;
}) {
  const leave = async (membershipId: string, name: string) => {
    try {
      await api.leaveTenant(session.accessToken, membershipId);
      onFlash(`Left ${name}. Your account and history are retained.`);
      onChanged();
    } catch {
      onFlash("Could not leave that academy.");
    }
  };

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
        Your academies ({me.memberships.length})
      </h3>
      {me.memberships.length === 0 ? (
        <p className="text-sm text-slate-400">
          You're not part of any academy yet. Join one above.
        </p>
      ) : (
        <ul className="divide-y divide-slate-100">
          {me.memberships.map((m) => {
            const name =
              DEMO_ACADEMIES.find((a) => a.id === m.tenant_id)?.name ?? m.tenant_id.slice(0, 8);
            return (
              <li key={m.id} className="flex items-center justify-between py-3">
                <div>
                  <div className="font-medium text-slate-800">{name}</div>
                  <div className="text-xs text-slate-500">
                    <Badge tone="slate">{m.role}</Badge> · {m.status}
                  </div>
                </div>
                <button
                  onClick={() => leave(m.id, name)}
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
                >
                  Leave
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Small UI helpers
// ---------------------------------------------------------------------------

function Field({
  label,
  value,
  onChange,
  type = "text",
  required,
  placeholder,
  hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  required?: boolean;
  placeholder?: string;
  hint?: string;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-slate-600">{label}</span>
      <input
        type={type}
        value={value}
        required={required}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-pitch-500 focus:ring-1 focus:ring-pitch-500"
      />
      {hint && <span className="mt-1 block text-[11px] text-slate-400">{hint}</span>}
    </label>
  );
}

function Submit({ busy, children }: { busy: boolean; children: React.ReactNode }) {
  return (
    <button
      type="submit"
      disabled={busy}
      className="w-full rounded-lg bg-pitch-600 py-2.5 text-sm font-semibold text-white hover:bg-pitch-700 disabled:opacity-60"
    >
      {children}
    </button>
  );
}

function ErrorNote({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
      {children}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-slate-500">{label}</dt>
      <dd className="font-medium text-slate-800">{children}</dd>
    </div>
  );
}

function Badge({
  children,
  tone = "slate",
}: {
  children: React.ReactNode;
  tone?: "green" | "amber" | "slate";
}) {
  const tones = {
    green: "bg-pitch-100 text-pitch-700",
    amber: "bg-amber-100 text-amber-700",
    slate: "bg-slate-100 text-slate-600",
  };
  return (
    <span className={`inline-block rounded-md px-2 py-0.5 text-xs font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}

function Dot() {
  return <span className="inline-block h-1.5 w-1.5 rounded-full bg-pitch-500" />;
}
