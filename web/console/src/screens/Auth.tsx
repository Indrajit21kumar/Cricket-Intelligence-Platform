// Onboarding / sign-in (Book 6 §4.1). Register -> verify -> sign in. Consent
// (guardian flow for minors) is handled by M02 server-side; the UI states are
// non-punitive and specific (§13).
import { useState } from "react";
import { api, CipError } from "../lib/api";
import { useSession } from "../lib/session";
import { Button, Card, Field, Input } from "../ui";

type Mode = "login" | "register";

export function Auth() {
  const { signIn } = useSession();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [dob, setDob] = useState("2005-01-01");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [verifyToken, setVerifyToken] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (mode === "register") {
        const r = await api.register(email, password, dob, displayName || undefined);
        // In dev, M02 returns a verification hint we can act on directly.
        const token = new URLSearchParams(r.verification_url_hint.split("?")[1] ?? "").get("token");
        setVerifyToken(token);
        setNotice("Account created. Verify your email to continue.");
      } else {
        const tokens = await api.login(email, password);
        await signIn({ accessToken: tokens.access_token, refreshToken: tokens.refresh_token });
      }
    } catch (e) {
      setError(e instanceof CipError ? e.message : "Unexpected error");
    } finally {
      setBusy(false);
    }
  };

  const verify = async () => {
    if (!verifyToken) return;
    setBusy(true);
    setError(null);
    try {
      await api.verifyEmail(verifyToken);
      const tokens = await api.login(email, password);
      await signIn({ accessToken: tokens.access_token, refreshToken: tokens.refresh_token });
    } catch (e) {
      setError(e instanceof CipError ? e.message : "Unexpected error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto grid min-h-[70vh] max-w-md place-items-center px-4">
      <Card className="w-full">
        <div className="mb-5 text-center">
          <div className="mx-auto grid h-11 w-11 place-items-center rounded-xl bg-brand-600 font-extrabold text-white">
            CIP
          </div>
          <h1 className="mt-3 text-lg font-bold text-slate-900">
            {mode === "login" ? "Sign in" : "Create your account"}
          </h1>
          <p className="mt-1 text-sm text-slate-500">Your honest, explained cricket coach.</p>
        </div>

        <div className="space-y-3">
          <Field label="Email">
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
          </Field>
          <Field label="Password">
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} />
          </Field>
          {mode === "register" ? (
            <>
              <Field label="Date of birth" hint="Under-18 accounts require guardian consent (handled next).">
                <Input type="date" value={dob} onChange={(e) => setDob(e.target.value)} />
              </Field>
              <Field label="Display name" hint="Optional">
                <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
              </Field>
            </>
          ) : null}

          {error ? <p className="rounded-lg bg-critical-bg px-3 py-2 text-sm text-critical-fg" role="alert">{error}</p> : null}
          {notice ? <p className="rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-700">{notice}</p> : null}

          {verifyToken ? (
            <Button className="w-full" onClick={verify} disabled={busy}>
              Verify email &amp; continue
            </Button>
          ) : (
            <Button className="w-full" onClick={submit} disabled={busy || !email || !password}>
              {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
            </Button>
          )}

          <button
            className="w-full pt-1 text-center text-sm text-brand-700 hover:underline"
            onClick={() => {
              setMode(mode === "login" ? "register" : "login");
              setError(null);
              setNotice(null);
              setVerifyToken(null);
            }}
          >
            {mode === "login" ? "New here? Create an account" : "Already have an account? Sign in"}
          </button>
        </div>
      </Card>
    </div>
  );
}
